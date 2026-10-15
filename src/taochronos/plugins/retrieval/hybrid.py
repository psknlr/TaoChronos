"""Philology-Aware Temporal GraphRAG.

A research question is not a keyword query.  “宋代以前是否存在类似后世‘湿热蕴结’的理论？”
is executed as: concept decomposition → historical-sense expansion → variant
expansion → temporal constraint → seven retrieval routes (lexical, dense,
graph, temporal, citation, variant, sense) → reciprocal-rank fusion →
citation-lineage expansion → period-grouped claim comparison.

With the pack's alias layer on (ADR 0023) a drug is also found under its other
names — 国老 for 甘草, 通草 for 木通 before 960 — in a side queue that fills at
most 3 of 10 places, each hit labelled with the name, the drug and the source;
the question's own spelling keeps the other places.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import zip_longest
from types import SimpleNamespace
from typing import Any

from ...protocol.base import stable_id
from ...protocol.documents import Passage
from ...protocol.evidence import EvidenceRecord, Stance
from ...protocol.confidence import ConfidenceVector
from ..classics.aliases import DEFAULT_ALIAS, DIRECTIONS, KINDS, AliasIndex, Expansion, assemble, gate_form, overlaps
from ..classics.corpus import Corpus
from ..classics.domain import DomainPack, Mention
from ..classics.store import is_han
from .index import BM25Index, DenseIndex, HashingEmbedder, query_tokens

ROUTES = ("bm25", "dense", "graph", "temporal", "citation", "variant", "sense")
DEFAULT_WEIGHTS = {"bm25": 1.0, "dense": 0.6, "graph": 1.0, "temporal": 0.5, "citation": 0.5, "variant": 0.6, "sense": 0.7}
# large corpora: candidate generation from the full-text index, then the routes run on the candidates
CANDIDATES = 4000  # BM25-ranked candidates from the index
EDGE_CANDIDATES = 60  # earliest and latest attestations kept per query surface (temporal questions)
DENSE_LIMIT = 1500  # the dense route re-ranks at most this many candidates
GRAPH_LIMIT = 600  # claims are extracted (and cached) for at most this many candidates per query
SENSE_LIMIT = 1500
ALIAS_MODES = ("auto", "on", "off")  # search(aliases=…): the profile's choice, the layer whenever there is one, never
ASKED_SCORE = 0.5  # passages writing the asked name found beyond the fused pool (retention), scored like side hits
# How a question asks a name as a drug.  A name the corpus mostly writes in other senses — of the passages that write
# it (n ≥ COMMON_N), fewer than COMMON_SH in drug context (the build's stop rule), or fewer than COMMON_CUE_SH for a
# name all of whose drugs are ``cue`` (将军, 去水) — is asked as a drug only where the question reads as one: the name
# alone, a drug word or a dose beside it, or another drug's name in the question.
COMMON_N, COMMON_SH, COMMON_CUE_SH = 20, 0.10, 0.5
DRUG_WORDS = ("药", "本草", "功效", "功用", "性味", "炮制", "一名", "又名", "别名", "异名", "是什么", "是哪", "方书", "方剂",
              "方中", "处方", "配伍", "用量", "剂量")
RUN_STOPS = frozenset("的之治论何病是与和及或吗呢么什哪怎功效用主")  # an unknown name never runs over these (葛的功效)


@dataclass
class ParsedQuery:
    text: str
    terms: list[str] = field(default_factory=list)  # lexicon term ids
    surfaces: dict[str, list[str]] = field(default_factory=dict)  # term id → searchable surfaces
    variants: dict[str, list[str]] = field(default_factory=dict)  # surface → raw variant spellings
    decomposition: dict[str, list[str]] = field(default_factory=dict)
    groups: dict[str, list[list[str]]] = field(default_factory=dict)  # term id → component groups that must co-occur
    related: dict[str, list[str]] = field(default_factory=dict)
    after: int | None = None
    before: int | None = None
    intent: str = "general"  # earliest | evolution | contradiction | general
    quoted: list[str] = field(default_factory=list)
    # alias search (ADR 0023): the names the question writes (→ lexicon term id or None), those of them it asks as drugs
    # (the layer gates, expands and labels these only), the other names searched for them (one hop, ``Expansion``) and
    # the ``query.aliases`` block that shows both
    asked: dict[str, str | None] = field(default_factory=dict)
    drugs: list[str] = field(default_factory=list)
    expansions: list[Expansion] = field(default_factory=list)
    alias_view: dict[str, Any] = field(default_factory=dict)

    def all_surfaces(self) -> list[str]:
        out: list[str] = []
        for forms in self.surfaces.values():
            for f in forms:
                if f not in out:
                    out.append(f)
        for q in self.quoted:
            if q not in out:
                out.append(q)
        return out

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Hit:
    passage_id: str
    score: float
    routes: dict[str, int] = field(default_factory=dict)  # route → rank
    matched: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    year: float | None = None
    period: str | None = None
    note: str = ""
    via: list[dict[str, Any]] = field(default_factory=list)  # alias search: the name, drug and source it came by
    flags: list[str] = field(default_factory=list)  # anachronism:… homonym:… demoted:… other-referent:…
    # alias search, internal: A an asked drug's name · D demoted · O no surface · L another term's form · H an asked
    # drug's other lexicon form · X/B side queue
    tier: str = ""


class QueryAnalyzer:
    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack
        self._reverse_variants: dict[str, list[str]] = {}
        for src, (to, _) in pack.variants.chars.items():
            self._reverse_variants.setdefault(to, []).append(src)
        for w in pack.variants.words:
            self._reverse_variants.setdefault(w["to"], []).append(w["from"])
        self._herbs = frozenset(_layer(pack).context.get("herbs") or ())  # the alias layer's drug names (context.json)

    def variant_spellings(self, surface: str) -> list[str]:
        forms = {surface}
        for norm, originals in self._reverse_variants.items():
            if norm in surface:
                for orig in originals:
                    forms.add(surface.replace(norm, orig))
        return sorted(forms - {surface})

    def analyze(self, text: str, *, after: int | None = None, before: int | None = None, aliases: bool = False,
                cfg: dict[str, Any] | None = None) -> ParsedQuery:
        """The question parsed.  With ``aliases`` it is read against the pack's alias layer too (ADR 0023): an alias
        outranks a weak or shorter lexicon mention it overlaps, a weak herb character inside a short name nobody knows
        gives way to the name (干葛 is not 葛), and the names asked, those asked as drugs, their one-hop expansions and
        the ``query.aliases`` view are filled in; a name asked without a lexicon term is searched as written.  A name
        the question writes only inside a longer one is not asked, and an alias the corpus mostly writes in other
        senses only where the question reads it as a drug (:meth:`_analyze_aliases`).  ``cfg``: the alias parameters."""
        lex = self.pack.lexicon
        norm = self.pack.variants.normalize_text(text)
        q_after, q_before = self.pack.periods.parse_constraint(norm)
        q = ParsedQuery(text=text, after=after if after is not None else q_after, before=before if before is not None else q_before)
        q.quoted = [m for m in re.findall(r"[‘'“\"「『]([^’'”\"」』]{1,12})[’'”\"」』]", text)]
        if re.search(r"最早|起源|源流|出处|首见|以前|之前|早于", text):
            q.intent = "earliest"
        elif re.search(r"演变|变化|发展|历史|流变|沿革|转变", text):
            q.intent = "evolution"
        elif re.search(r"矛盾|争议|分歧|不同观点|相反", text):
            q.intent = "contradiction"
        if aliases:
            return self._analyze_aliases(q, norm, {**DEFAULT_ALIAS, **(cfg or {})})
        self._terms(q, [m for m in lex.match(norm) if not m.weak or len(norm) <= 4])
        self._spellings(q)
        return q

    def _terms(self, q: ParsedQuery, mentions: list[Mention]) -> list[Mention]:
        """Terms, their searchable surfaces, components and related terms from the mentions (and the quoted strings'
        own mentions, which are returned with them)."""
        lex = self.pack.lexicon
        for quoted in q.quoted:
            inner = [m for m in lex.match(self.pack.variants.normalize_text(quoted))]
            if inner:
                q.decomposition[quoted] = [m.term_id for m in inner]
                mentions.extend(inner)
        for m in mentions:
            if _season(m):
                continue
            if m.term_id not in q.terms:
                q.terms.append(m.term_id)
        for term_id in list(q.terms):
            entry = lex.entry(term_id)
            if entry is None:
                continue
            forms = [entry.term, *entry.aliases, *entry.synonyms]
            comps = []
            for comp in entry.components:
                ce = lex.resolve(comp)
                if ce is not None:
                    q.decomposition.setdefault(entry.term, []).append(ce.term_id)
                    comps.append(ce.term)
            if comps:
                q.groups[term_id] = [comps]
            related = list(entry.related) + list(entry.broader)
            hist = self.pack.terminology.term(entry.term)
            if hist is not None:
                related += [r for r in hist.related if r not in related]
            if related:
                q.related[term_id] = related
                forms.extend(related)
            q.surfaces[term_id] = list(dict.fromkeys(f for f in forms if f))
        return mentions

    def _spellings(self, q: ParsedQuery) -> None:
        for surface in q.all_surfaces():
            spellings = self.variant_spellings(surface)
            if spellings:
                q.variants[surface] = spellings

    def _analyze_aliases(self, q: ParsedQuery, norm: str, cfg: dict[str, Any]) -> ParsedQuery:
        """The question read against the alias layer.

        1. A name written only inside one of its own blockers is not asked (将军 in 将军之官, 人言 in 古人言): an alias
           span is dropped, a lexicon mention keeps its term (today's reading) but is no asked name.  A blocker that
           names a drug itself is asked as written in its place, the mentions inside it dropped (石南藤, not 石南).
        2. An alias span is kept only where the question asks it as a drug (:meth:`_asks_drug`); a dropped one gives
           the lexicon mentions it overlapped back, so a question about something else reads as today.
        3. A kept span outranks a weak or shorter lexicon mention it overlaps (山蓟 over 山).
        4. A question of four characters or fewer that is one name nobody knows, a weak herb character inside it,
           asks that name (干葛 is not 葛); question words stay outside it (葛的功效 asks 葛, 肝藏血 asks 肝 and 血).
        The names asked go to ``q.asked`` in the order written, those asked as drugs to ``q.drugs``; only these are
        expanded and listed."""
        lex, index = self.pack.lexicon, _layer(self.pack)
        g = gate_form(norm)
        raw = lex.match(norm)
        spans = index.scan(norm)
        blocked: set[tuple[int, str]] = set()
        written: list[tuple[int, int, str]] = []
        for i, s in [(i, s) for i, _, s in spans] + [(m.start, m.surface) for m in raw]:
            cover = self._cover(g, i, s)
            if cover is None:
                continue
            blocked.add((i, s))
            k, b = cover
            if self._names_drug(b) and not any(a < k + len(b) and k < z for a, z, _ in written):
                written.append((k, k + len(b), b))

        def held(i: int, j: int) -> bool:
            return any(a < j and i < z for a, z, _ in written)

        raw = [m for m in raw if not held(m.start, m.end)]
        terms = {(m.start, m.surface): m.term_id for m in raw}
        spans = [(i, j, s) for i, j, s in spans if (i, s) not in blocked and not held(i, j)]
        strong = [(i, j) for i, j, s in spans if self._drug_reading(s, terms.get((i, s))) == "drug"]
        strong += [(m.start, m.end) for m in raw if not m.weak and (m.start, m.surface) not in blocked
                   and self._drug_reading(m.surface, m.term_id) == "drug"]
        spans = [(i, j, s) for i, j, s in spans if self._asks_drug(norm, g, i, j, s, terms.get((i, s)), strong, cfg)]
        mentions: list[Mention] = []
        for m in raw:
            over = [j - i for i, j, _ in spans if i < m.end and m.start < j]
            if over and (m.weak or len(m.surface) < max(over)):
                continue  # the alias 山蓟 over the weak 山; a longer alias over a shorter lexicon name inside it
            if not m.weak or len(norm) <= 4:
                mentions.append(m)
        runs: list[tuple[int, str]] = []
        if cfg["unknown_runs"] and len(norm) <= 4:
            # a weak herb character inside a short name nobody knows is not what was asked: 干葛 is not 葛, and 斑杖根
            # is neither 斑 nor 根 (but 姜枣, all known characters, is 姜 and 枣)
            weak = [m for m in mentions if m.weak and m.category == "herb"]
            taken = {x for i, j, _ in spans + written for x in range(i, j)}
            known = {x for o in mentions for x in range(o.start, o.end)}
            for m in weak:
                if m not in mentions:
                    continue
                others = taken | {x for o in mentions if o not in weak for x in range(o.start, o.end)}
                lo, hi = m.start, m.end
                while lo > 0 and _runs_over(norm[lo - 1]) and lo - 1 not in others:
                    lo -= 1
                while hi < len(norm) and _runs_over(norm[hi]) and hi not in others:
                    hi += 1
                # the run is the question's one name: nothing but question words beside it (藏血 in 肝藏血 is none)
                if (2 <= hi - lo <= 4 and not any(_runs_over(c) for c in norm[:lo] + norm[hi:])
                        and not set(range(lo, hi)) <= known):
                    for o in [o for o in weak if lo <= o.start and o.end <= hi and o in mentions]:
                        mentions.remove(o)
                    runs.append((lo, norm[lo:hi]))
                    taken |= set(range(lo, hi))
        own = list(mentions)
        inner = self._terms(q, mentions)[len(own):]
        # the names asked, in the order written: the mentions (but those inside a blocker), the alias spans no mention
        # holds, the unknown runs, the blockers asked as written; then the quoted strings' mentions and the quoted
        # strings themselves (a span a kept mention overlaps is the mention's: the lexicon's reading of the same
        # characters wins a tie)
        found = [(m.start, m.surface, m.term_id) for m in own if not _season(m) and (m.start, m.surface) not in blocked]
        found += [(i, s, None) for i, j, s in spans if not any(m.start < j and i < m.end for m in own)]
        found += [(i, s, None) for i, s in runs]
        found += [(i, s, None) for i, _, s in written]
        where: dict[str, int] = {}
        for i, s, term in sorted(found, key=lambda t: t[0]):
            q.asked.setdefault(s, term)
            where.setdefault(s, i)
        for m in inner:
            if not _season(m):
                q.asked.setdefault(m.surface, m.term_id)
        quoted = [self.pack.variants.normalize_text(x) for x in q.quoted]
        for x in quoted:
            q.asked.setdefault(x, None)
        q.quoted += [s for s, term in q.asked.items() if term is None and s not in quoted]  # searched as written
        self._spellings(q)
        for s, term in q.asked.items():
            i = where.get(s, max(0, norm.find(s)))
            if self._asks_drug(norm, g, i, i + len(s), s, term, strong, cfg):
                q.drugs.append(s)
        drugs = SimpleNamespace(asked={s: q.asked[s] for s in q.drugs}, after=q.after, before=q.before,
                                all_surfaces=q.all_surfaces, groups=q.groups)
        q.expansions = index.expansions(drugs, lex, cfg)
        q.alias_view = index.view(drugs, cfg, lex, q.expansions)
        return q

    def _cover(self, g: str, i: int, s: str) -> tuple[int, str] | None:
        """The blocker of ``s`` the question writes it inside at ``i`` (its offset and text), or None when it is free
        there (by the passages' rule: a blocker inside one of its own covers nothing)."""
        index = _layer(self.pack)
        rec = index.record(s)
        for b in rec.b if rec is not None else ():
            text = b if isinstance(b, str) else b[0]
            k = index.covers(g, i, s, text, None) if s in text and text != s else None
            if k is not None:
                return k, text
        return None

    def _names_drug(self, s: str) -> bool:
        """Whether a string is a drug's name: one the layer's herb set, a record or a lexicon herb holds."""
        rec = _layer(self.pack).record(s)
        return (s in self._herbs or (rec is not None and not rec.stop and bool(rec.r or rec.ho or rec.fl is not None))
                or any(e.category == "herb" for e, _ in self.pack.lexicon.lookup(s)))

    def _drug_reading(self, s: str, term: str | None) -> str | None:
        """How a name may be asked as a drug: ``drug`` as written, ``context`` only where the question reads as one
        (a name the corpus mostly writes in other senses, a false friend the lexicon files as a herb, a name with only
        doubtful pairings), None never (no drug's name, or one the lexicon reads as a disease, an acupoint …)."""
        entry = self.pack.lexicon.entry(term) if term else None
        if (entry is not None and entry.category != "herb") or len(s) < 2:
            return None  # a single character is no name the layer reads (葛 stays the lexicon's)
        rec = _layer(self.pack).record(s)
        if rec is None:
            return "drug" if entry is not None or s in self._herbs else None
        if rec.stop:
            return "context" if entry is not None else None
        live = [r for r in rec.r if r.st != "candidate"]
        if not live and rec.ho is None and rec.fl is None:
            return "drug" if entry is not None else "context"
        cue = rec.ho is None and rec.fl is None and all(r.st == "cue" for r in live)
        return "context" if rec.n >= COMMON_N and rec.sh < (COMMON_CUE_SH if cue else COMMON_SH) else "drug"

    def _asks_drug(self, norm: str, g: str, i: int, j: int, s: str, term: str | None, strong: list[tuple[int, int]],
                   cfg: dict[str, Any]) -> bool:
        """Whether the question asks the name at ``norm[i:j]`` as a drug.  Where its reading needs the question's
        context: the name stands alone, a drug word (:data:`DRUG_WORDS`) or another drug's name (``strong``: their
        spans) is in the question, or the name reads as a drug by the passage gate (a dose, 一名, a cue near it)."""
        reading = self._drug_reading(s, term)
        if reading != "context":
            return reading == "drug"
        rest = norm[:i] + "|" * (j - i) + norm[j:]
        if not gate_form(rest).strip("|") or any(w in rest for w in DRUG_WORDS):
            return True
        if any(not (a < j and i < b) for a, b in strong):
            return True
        index = _layer(self.pack)
        return index.drug_context(g, gate_form(s), [i], _cues(self.pack, s, term), cfg=cfg)


def _season(m: Mention) -> bool:
    return m.category in ("condition",) and m.entry.kind == "season"


def _runs_over(c: str) -> bool:
    """Whether an unknown name's run may take in a character: Han, and no question word."""
    return is_han(c) and c not in RUN_STOPS


_NO_LAYER = AliasIndex.empty()


def _layer(pack: Any) -> AliasIndex:
    """The pack's alias layer; empty for a pack without one."""
    index = getattr(pack, "aliases", None)
    return _NO_LAYER if index is None else index


def _ablations(cfg: dict[str, Any]) -> set[str]:
    value = cfg.get("ablate") or ()
    return {value} if isinstance(value, str) else set(value)


def _share(value: Any) -> tuple[int, int]:
    """The side queue's share of the places, ``[num, den]`` with 0 ≤ num ≤ den and den > 0."""
    try:
        num, den = value
        if not all(isinstance(x, int) or (isinstance(x, float) and x.is_integer()) for x in (num, den)):
            raise TypeError
        num, den = int(num), int(den)
    except (TypeError, ValueError):
        raise ValueError(f"alias share must be [num, den] of whole numbers, not {value!r}") from None
    if den <= 0 or not 0 <= num <= den:
        raise ValueError(f"alias share must have 0 ≤ num ≤ den and den > 0, not {value!r}")
    return num, den


def _bound(a: float | None, b: float | None, pick: Any) -> float | None:
    """Two bounds on one side of a window met: the tighter, or whichever is set."""
    return b if a is None else a if b is None else pick(a, b)


def _cues(pack: Any, s: str, term: str | None) -> list[str]:
    """What says a name means a drug where it may not: its referents' cues, or for a false friend the lexicon files as a
    herb (救火 for 景天) that herb's other names."""
    rec = _layer(pack).record(s)
    if rec is not None and rec.stop:
        entry = pack.lexicon.entry(term) if term else None
        normalize = pack.variants.normalize_text
        return sorted({normalize(f) for f in entry.surfaces()} - {s}) if entry is not None else []
    return sorted({c for r in (rec.r if rec is not None else ()) if r.st != "candidate" for c in r.c})


def _covering(index: AliasIndex, g: str, s: str, blockers: list[Any], yr: tuple[int | None, int | None]) -> str:
    """The blocker a demoted name stands inside (the first that covers an occurrence), for its flag."""
    offs = [i for i in range(len(g)) if g.startswith(s, i)]
    for b in blockers:
        text, window = (b, None) if isinstance(b, str) else (b[0], (b[1], b[2]))
        if s in text and text != s and overlaps(window, yr) and any(
                index.covers(g, i, s, text, yr) is not None for i in offs):
            return text
    return "?"


def _lexicon_kind(entry: Any, name: str, normalize: Any, related: str | None = None) -> str:
    """How a lexicon entry files one of its names (``alias`` or its synonym kind); ``related`` for a name it only
    relates (a related or broader term)."""
    for f in entry.surfaces():
        if f == name or normalize(f) == name:
            return entry.synonyms.get(f) or "alias"
    return "alias" if related is None else related


def _by_year(h: Hit) -> tuple[float, float]:
    return (h.year if h.year is not None else 9999, -h.score)


def _in_years(hits: list[Hit]) -> list[Hit]:
    """An origin question's answer: each queue's hits in order of years in that queue's own places — in the main places
    the asked drug's name first (its earliest first), then the rest; the other names' in the side places; the demoted
    last.  Without a drug asked, today's order of years."""
    out = list(hits)
    side = [i for i, h in enumerate(hits) if h.tier in ("X", "B")]
    demoted = [i for i, h in enumerate(hits) if h.tier == "D"]
    main = [i for i, h in enumerate(hits) if h.tier not in ("X", "B", "D")]
    asked = sorted((hits[i] for i in main if hits[i].tier == "A"), key=_by_year)
    rest = sorted((hits[i] for i in main if hits[i].tier != "A"), key=_by_year)
    for places, ordered in ((side, sorted((hits[i] for i in side), key=_by_year)),
                            (demoted, sorted((hits[i] for i in demoted), key=_by_year)), (main, asked + rest)):
        for i, h in zip(places, ordered):
            out[i] = h
    return out


def _witness(wits: list[Any], cfg: dict[str, Any]) -> str | None:
    """The witness an answer shows: the first, or with ``witness_scope: web`` the first the site's corpus holds."""
    web = cfg["witness_scope"] == "web"
    return next((w.pid for w in wits if w.web or not web), None)


class HybridRetriever:
    def __init__(self, pack: DomainPack, corpus: Corpus, knowledge: Any = None, embedder: Any = None,
                 weights: dict[str, float] | None = None, alias: dict[str, Any] | None = None) -> None:
        self.pack = pack
        self.alias = {**DEFAULT_ALIAS, **(alias or {})}  # the profile's retrieval.alias (ADR 0023)
        self.corpus = corpus
        self.knowledge = knowledge
        self.analyzer = QueryAnalyzer(pack)
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.embedder = embedder or HashingEmbedder()
        self.bm25 = BM25Index()
        self.dense = DenseIndex(self.embedder)
        self.large = bool(getattr(corpus, "large", False))
        self._norm: dict[str, str] = {}
        self._rank: dict[str, float] = {}  # large corpora: index BM25 rank of the current candidates
        if not self.large:
            for p in corpus.passages():
                norm = pack.variants.normalize_text(p.text)
                self._norm[p.id] = norm
                self.bm25.add(p.id, norm)
                self.dense.add(p.id, norm)

    def norm(self, pid: str) -> str:
        cached = self._norm.get(pid)
        if cached is None:
            cached = self.pack.variants.normalize_text(self.corpus.passage(pid).text)
            if len(self._norm) > 60_000:
                self._norm.clear()
            self._norm[pid] = cached
        return cached

    # ------------------------------------------------------------------ routes
    def _candidates(self, q: ParsedQuery) -> set[str]:
        if self.large:
            return self._index_candidates(q)
        ids = set()
        for p in self.corpus.passages(after=q.after, before=q.before):
            ids.add(p.id)
        return ids

    def _index_candidates(self, q: ParsedQuery) -> set[str]:
        """Full-text-index candidates: the BM25 top of an OR query over every query surface, plus the earliest
        and latest attestations of each surface (so questions about origins or later fate are not decided by
        rank), plus passages naming a targeted sense's head term."""
        surfaces = list(dict.fromkeys(q.all_surfaces() + [s for forms in q.variants.values() for s in forms]))
        for group in (g for gs in q.groups.values() for g in gs):
            surfaces.extend(group)
        if not surfaces:
            surfaces = [x for x in re.findall(r"[㐀-鿿]{2,4}", self.pack.variants.normalize_text(q.text))][:8]
        ranked = self.corpus.search(surfaces, limit=CANDIDATES, after=q.after, before=q.before)
        self._rank = {pid: score for pid, score in ranked}
        ids = {pid for pid, _ in ranked}
        for surface in dict.fromkeys(surfaces):
            if len(surface) < 2 and len(surfaces) > 1:
                continue
            hits = self.corpus.contains(surface, after=q.after, before=q.before, verify=False)
            ids.update(hits[:EDGE_CANDIDATES])
            ids.update(hits[-EDGE_CANDIDATES:])
        for term, _wanted, _anchors in self.sense_targets(q):
            hits = self.corpus.contains(term, after=q.after, before=q.before, verify=False)
            ids.update(hits[:SENSE_LIMIT // 4])
        return ids

    def _local_indexes(self, cand: set[str]) -> tuple[BM25Index, DenseIndex]:
        """Per-query BM25 / dense indexes over the candidates (large corpora)."""
        bm25 = BM25Index()
        for pid in cand:
            bm25.add(pid, self.norm(pid))
        dense = DenseIndex(self.embedder)
        order = sorted(cand, key=lambda pid: (-self._rank.get(pid, 0.0), pid))[:DENSE_LIMIT]
        for pid in order:
            dense.add(pid, self.norm(pid))
        return bm25, dense

    def route_bm25(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        toks: list[str] = []
        for s in q.all_surfaces():
            toks.extend(query_tokens(self.pack.variants.normalize_text(s)))
        if not toks:
            toks = query_tokens(self.pack.variants.normalize_text(q.text))
        index = self._local[0] if self.large else self.bm25
        return index.search(toks, k, cand if not self.large else set(index.docs) & cand)

    def route_dense(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        text = " ".join([q.text, *q.all_surfaces()])
        index = self._local[1] if self.large else self.dense
        return index.search(self.pack.variants.normalize_text(text), k, cand if not self.large else set(index.vectors) & cand)

    def route_graph(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float, list[str]]]:
        if self.knowledge is None or not q.terms:
            return []
        if self.large:
            top = sorted(cand, key=lambda pid: (-self._rank.get(pid, 0.0), pid))[:GRAPH_LIMIT]
            self.knowledge.touch(top)
            hg = self.knowledge.hypergraph(passage_ids=top)
        else:
            hg = self.knowledge.hypergraph()
        targets: list[tuple[set[str], float]] = []  # (term set that must all be members, weight)
        for tid in q.terms:
            targets.append(({tid}, 1.0))
            for group in q.groups.get(tid, []):
                ids = {e.term_id for e in (self.pack.lexicon.resolve(c) for c in group) if e}
                if ids:
                    targets.append((ids, 0.7))
            for rel in q.related.get(tid, []):
                entry = self.pack.lexicon.resolve(rel)
                if entry:
                    targets.append(({entry.term_id}, 0.6))
        scores: dict[str, tuple[float, list[str]]] = {}
        for cid, claim in hg.claims.items():
            if claim.passage_id not in cand:
                continue
            members = set(hg.members(claim, include_negated=True))
            weight = sum(w for need, w in targets if need <= members)
            if not weight:
                continue
            weight /= max(1, len(members)) ** 0.5
            prev, ids = scores.get(claim.passage_id, (0.0, []))
            scores[claim.passage_id] = (prev + weight, ids + [cid])
        ranked = sorted(scores.items(), key=lambda t: (-t[1][0], t[0]))[:k]
        return [(pid, s, ids) for pid, (s, ids) in ranked]

    def _contains_any(self, pid: str, surfaces: list[str], groups: list[list[str]] | None = None) -> list[str]:
        norm = self.norm(pid)
        found = [s for s in surfaces if s and self.pack.variants.normalize_text(s) in norm]
        for group in groups or []:
            if all(self.pack.variants.normalize_text(c) in norm for c in group):
                found.append("+".join(group))
        return found

    def route_temporal(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        surfaces = q.all_surfaces()
        groups = [g for gs in q.groups.values() for g in gs]
        hits = [pid for pid in cand if self._contains_any(pid, surfaces, groups)]
        reverse = q.intent != "earliest"
        hits.sort(key=lambda pid: ((self.corpus.year(self.corpus.passage(pid)) or 0) * (-1 if reverse else 1), pid))
        return [(pid, 1.0 / (i + 1)) for i, pid in enumerate(hits[:k])]

    def route_variant(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        out = []
        for pid in cand:
            raw = self.corpus.passage(pid).text
            count = 0
            for surface, spellings in q.variants.items():
                count += sum(raw.count(sp) for sp in spellings)
            if count:
                out.append((pid, float(count)))
        out.sort(key=lambda t: (-t[1], t[0]))
        return out[:k]

    def sense_targets(self, q: ParsedQuery) -> list[tuple[str, str | None, tuple[str, ...]]]:
        """(historical term, targeted sense or None, anchor cues).

        A query term that is itself a curated term targets all its senses.  A query term that *names* a
        specific sense (appears in its label, e.g. 三消 → 消渴#病·三消) targets that sense of its head term:
        concept-level retrieval of passages that describe the concept before the later name existed.  Such
        a passage must contain an anchor — a cue sharing a morpheme with the query term (消中, 肾消, 上消…) —
        so associated-but-not-defining cues (痈疽 as a complication) do not count as the concept.
        """
        terminology = self.pack.terminology
        surfaces = {t.split(":", 1)[1] for t in q.terms}
        targets: list[tuple[str, str | None, tuple[str, ...]]] = [(s, None, ()) for s in sorted(surfaces) if terminology.term(s)]
        for term in terminology.terms.values():
            for sense in term.senses:
                for surface in surfaces:
                    if len(surface) < 2 or surface == term.id or surface not in sense.label:
                        continue
                    morphemes = set(surface) - {"之", "病", "证"}
                    anchors = tuple(c for c in sense.cues if len(c) >= 2 and set(c) & morphemes)
                    if anchors:
                        targets.append((term.id, sense.id, anchors))
        return targets

    def route_sense(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        targets = self.sense_targets(q)
        if not targets:
            return []
        mid = None
        if q.after is not None or q.before is not None:
            lo = q.after if q.after is not None else -500
            hi = q.before if q.before is not None else 1912
            mid = (lo + hi) / 2
        out = []
        pool = cand
        if self.large and len(cand) > SENSE_LIMIT:
            heads = {term for term, _, _ in targets}
            pool = {pid for pid in cand if any(h in self.norm(pid) for h in heads)}
            pool = set(sorted(pool, key=lambda pid: (-self._rank.get(pid, 0.0), pid))[:SENSE_LIMIT])
        for pid in pool:
            norm = self.norm(pid)
            passage = self.corpus.passage(pid)
            year = self.corpus.year(passage)
            best = 0.0
            for term, wanted, anchors in targets:
                if term not in norm or (anchors and not any(a in norm for a in anchors)):
                    continue
                context = {m.entry.term for m in self.pack.lexicon.match(norm)}
                sense, p, alts, _ = self.pack.terminology.resolve(term, norm, context, year)
                if sense is None:
                    continue
                if wanted is not None:
                    p = alts.get(wanted, 0.0) if sense != wanted else p
                    if p < 0.3:
                        continue
                target = self.pack.terminology.sense(wanted or sense)
                period_fit = 1.0
                if mid is not None and target is not None and target.period is not None and not target.period.contains(mid):
                    period_fit = 0.5
                best = max(best, p * period_fit)
            if best:
                out.append((pid, best))
        out.sort(key=lambda t: (-t[1], t[0]))
        return out[:k]

    # ------------------------------------------------------------------ fusion
    def search(self, text: str, *, k: int = 10, after: int | None = None, before: int | None = None,
               routes: list[str] | None = None, books: list[str] | None = None, allowed: set[str] | None = None,
               aliases: str = "auto", alias_params: dict[str, Any] | None = None) -> tuple[ParsedQuery, list[Hit]]:
        """``allowed`` restricts the search space (e.g. a session scope with a temporal hold-out).

        ``aliases`` (ADR 0023): ``auto`` searches the asked drugs' other names when the profile turns the layer on
        (``retrieval.alias.enabled``), ``on`` whenever the pack has a layer, ``off`` never — today's search, unchanged,
        which a pack without a layer always gets.  ``alias_params`` overrides the alias parameters for one call
        (ablations, ``asked_first``, ``share``; not part of the tool).  ``routes`` restricts the alias search too: its
        side queue runs only when it names ``alias``, its search for more passages in the asked name only when it names
        ``bm25``."""
        if aliases not in ALIAS_MODES:
            raise ValueError(f"aliases must be one of {', '.join(ALIAS_MODES)}, not {aliases!r}")
        cfg = {**self.alias, **(alias_params or {})}
        cfg["share"] = _share(cfg["share"])
        if not _layer(self.pack).enabled or not (aliases == "on" or (aliases == "auto" and cfg["enabled"])):
            return self._legacy_search(text, k=k, after=after, before=before, routes=routes, books=books,
                                       allowed=allowed)
        return self._alias_search(text, k=k, after=after, before=before, routes=routes, books=books, allowed=allowed,
                                  cfg=cfg)

    def _legacy_search(self, text: str, *, k: int, after: int | None, before: int | None, routes: list[str] | None,
                       books: list[str] | None, allowed: set[str] | None) -> tuple[ParsedQuery, list[Hit]]:
        """The search without the alias layer."""
        q = self.analyzer.analyze(text, after=after, before=before)
        fused, ranked, pool = self._fuse(q, k=k, routes=routes, books=books, allowed=allowed)
        hits = sorted(pool, key=lambda h: (-h.score, h.passage_id))[:k]
        if self.large and q.intent == "earliest" and ranked.get("temporal"):
            # in a large corpus the earliest attestations rarely win on relevance score: keep the three
            # earliest matching passages in the answer to an origin question
            earliest = [fused[pid] for pid, _ in ranked["temporal"][:3] if pid in fused and fused[pid] in pool]
            keep = [h for h in hits if h not in earliest][: max(0, k - len(earliest))]
            hits = earliest + keep
        if q.intent == "earliest":
            hits.sort(key=lambda h: (h.year if h.year is not None else 9999, -h.score))
        return q, hits

    def _fuse(self, q: ParsedQuery, *, k: int, routes: list[str] | None, books: list[str] | None,
              allowed: set[str] | None) -> tuple[dict[str, Hit], dict[str, list[tuple[str, float]]], list[Hit]]:
        """Candidates, the routes and their reciprocal-rank fusion: every fused hit, each route's ranking, and the
        pool past the relevance floor."""
        cand = self._candidates(q)
        if allowed is not None:
            cand &= allowed
        if books:
            wanted = set(books)
            cand = {pid for pid in cand if self.corpus.passage(pid).book_id in wanted}
        if self.large:
            self.corpus.passages_by_id(sorted(cand))  # one batched fetch warms the passage cache
            self._local = self._local_indexes(cand)
        active = [r for r in (routes or list(ROUTES)) if r in ROUTES]
        ranked: dict[str, list[tuple[str, float]]] = {}
        claim_ids: dict[str, list[str]] = {}
        depth = max(k * 3, 20)
        for route in active:
            if route == "citation":
                continue
            if route == "graph":
                res = self.route_graph(q, cand, depth)
                ranked[route] = [(pid, s) for pid, s, _ in res]
                for pid, _, ids in res:
                    claim_ids[pid] = ids
            else:
                ranked[route] = getattr(self, f"route_{route}")(q, cand, depth)
        fused: dict[str, Hit] = {}
        for route, results in ranked.items():
            w = self.weights.get(route, 1.0)
            for rank, (pid, _) in enumerate(results):
                hit = fused.setdefault(pid, Hit(passage_id=pid, score=0.0))
                hit.score += w / (60 + rank + 1)
                hit.routes[route] = rank + 1
        surfaces = q.all_surfaces()
        groups = [g for gs in q.groups.values() for g in gs]
        if "citation" in active and self.knowledge is not None:
            relevant_seeds = [
                h for h in fused.values()
                if "graph" in h.routes or self._contains_any(h.passage_id, surfaces, groups)
            ]
            seeds = sorted(relevant_seeds, key=lambda h: -h.score)[:k]
            edges = self.knowledge.lineage(passage_ids=[h.passage_id for h in seeds]) if self.large else self.knowledge.lineage()
            for edge in edges:
                for seed in seeds:
                    other = None
                    if edge.source_passage == seed.passage_id and edge.target_passage:
                        other = edge.target_passage
                    elif edge.target_passage == seed.passage_id and edge.source_passage:
                        other = edge.source_passage
                    if other and other in cand:
                        hit = fused.setdefault(other, Hit(passage_id=other, score=0.0))
                        hit.score += self.weights["citation"] * edge.confidence / 61
                        hit.routes.setdefault("citation", 1)
                        hit.note = f"{edge.relation} {seed.passage_id}"
        sense_heads = [term for term, wanted, _ in self.sense_targets(q) if wanted is not None]
        for hit in fused.values():
            passage = self.corpus.passage(hit.passage_id)
            hit.year = self.corpus.year(passage)
            hit.period = self.pack.periods.period_of(hit.year)
            hit.matched = self._contains_any(hit.passage_id, surfaces, groups)
            if not hit.matched and "sense" in hit.routes:
                hit.matched = [t for t in sense_heads if t in self.norm(hit.passage_id)]
                hit.note = hit.note or "concept-level match (sense route)"
            hit.claim_ids = claim_ids.get(hit.passage_id, [])
            hit.score = round(hit.score * 1000, 4)
        # relevance floor: a hit must match the query surfaces, a graph claim, a lineage edge or a targeted sense
        relevant = [h for h in fused.values() if h.matched or "graph" in h.routes or "citation" in h.routes]
        pool = relevant if (relevant or q.terms) else list(fused.values())
        return fused, ranked, pool

    # ------------------------------------------------------------------ alias search (ADR 0023)
    def _alias_search(self, text: str, *, k: int, after: int | None, before: int | None, routes: list[str] | None,
                      books: list[str] | None, allowed: set[str] | None,
                      cfg: dict[str, Any]) -> tuple[ParsedQuery, list[Hit]]:
        """Today's fusion, split by tier.  The main queue M holds hits on an asked drug's name (A), hits without a
        surface (O) and hits on the question's other terms (L), in today's order; where the asked-first rule holds (a
        drug asked, at ``herbs``) the first k − ⌊num·k/den⌋ places keep the asked name.  The side queue interleaves hits
        on an asked drug's other lexicon forms (H, which become X; at ``all``, on any other form) with passages found
        under the expansions (B), and takes at most ⌊num·k/den⌋ reserved places while M lasts.  Demoted hits (D: the
        name only inside a longer one, or without drug context where it needs one) come after both.  An origin
        question reads each queue in order of years, in its own places.  A question that asks no drug is ranked as
        today."""
        ablate = _ablations(cfg)
        q = self.analyzer.analyze(text, after=after, before=before, aliases=True, cfg=cfg)
        fused, ranked, pool = self._fuse(q, k=k, routes=routes, books=books, allowed=allowed)
        P = sorted(pool, key=lambda h: (-h.score, h.passage_id))
        gates = self._gates(q, cfg)
        for h in P:
            h.tier, h.flags = self._tier(h, gates, cfg)
        first = cfg["asked_first"] == "all" or (cfg["asked_first"] == "herbs" and bool(q.drugs))
        side = ({"H", "L"} if cfg["asked_first"] == "all" else {"H"}) if first else set()
        later = side | {"D"}
        pins: list[Hit] = []
        if self.large and q.intent == "earliest" and ranked.get("temporal"):
            # as today, the three earliest attestations stay in the answer to an origin question — of the main queue
            inside = {h.passage_id for h in P}
            pins = [fused[pid] for pid, _ in ranked["temporal"] if pid in inside and fused[pid].tier not in later][:3]
        pinned = {h.passage_id for h in pins}
        M = pins + [h for h in P if h.tier not in later and h.passage_id not in pinned]
        num, den = cfg["share"]
        if first:
            M = self._retain(q, M, k - (num * k) // den, k, books, allowed, {h.passage_id for h in P}, gates, cfg,
                             search=routes is None or "bm25" in routes)
        X: list[Hit] = []
        if side:
            groups = self._asked_groups(q) if "period" not in ablate else set()
            lexical = [h for h in P if h.tier in side]
            if q.intent == "earliest":
                lexical.sort(key=_by_year)
            for h in lexical:
                other = self._other_referent(h, groups)
                h.flags += [f"other-referent:{s}" for s in dict.fromkeys(other)]
                if other and len(other) == len(h.matched):  # every form it matched means another drug then
                    M.append(h)
                else:
                    h.tier = "X"
                    X.append(h)
        B: list[Hit] = []
        if routes is None or "alias" in routes:
            B = self._side(q, {h.passage_id for h in M} | {h.passage_id for h in P}, books, allowed, cfg)
        S = [h for pair in zip_longest(X, B) for h in pair if h is not None]
        D = [h for h in P if h.tier == "D"]
        if "slots" in ablate:
            hits = sorted(M + S + D, key=lambda h: (-h.score, h.passage_id))[:k]
            if q.intent == "earliest":
                hits.sort(key=_by_year)
        else:
            hits = assemble(M, S, k, num, den)
            hits += D[:k - len(hits)]
            if q.intent == "earliest":
                hits = _in_years(hits)
        self._annotate(q, hits, gates, cfg)
        return q, hits

    def _range(self, passage: Passage) -> tuple[int | None, int | None]:
        """A passage's date range, as the gates read it; (None, None) when undated."""
        rng = self.corpus.year_range(passage)
        return (None, None) if rng is None else (rng.start, rng.end)

    def _hit(self, q: ParsedQuery, pid: str, score: float, routes: dict[str, int],
             matched: list[str] | None = None) -> Hit:
        passage = self.corpus.passage(pid)
        hit = Hit(passage_id=pid, score=score, routes=routes)
        hit.year = self.corpus.year(passage)
        hit.period = self.pack.periods.period_of(hit.year)
        hit.matched = matched if matched is not None else self._contains_any(
            pid, q.all_surfaces(), [g for gs in q.groups.values() for g in gs])
        return hit

    def _gates(self, q: ParsedQuery, cfg: dict[str, Any]) -> dict[str, Any]:
        """What the tiers read.  ``asked``: per drug asked, what makes an occurrence count — (gate-form name, its
        blockers, the cues of the drug context it needs, None when it needs none); a name needs drug context when every
        drug it may be searched as is ``cue`` (将军) and it heads none itself, or when it is a false friend the lexicon
        files as a herb (救火, cued by 景天's other names).  ``forms``: the query's own surfaces and component groups as
        ``matched`` holds them (a sense head alone is no surface).  ``drug``: the asked drugs' lexicon forms → (their
        entry, the asked name)."""
        index, lex = _layer(self.pack), self.pack.lexicon
        ablate = _ablations(cfg)
        out = []
        drug: dict[str, tuple[Any, str]] = {}
        for s in q.drugs:
            rec, term = index.record(s), q.asked.get(s)
            cues = None
            if rec is not None and "gates" not in ablate:
                refs = [r for r in rec.r if r.st != "candidate"]
                if rec.stop or (rec.ho is None and rec.fl is None and refs and all(r.st == "cue" for r in refs)):
                    cues = _cues(self.pack, s, term)
            out.append((gate_form(s), list(rec.b) if rec is not None and "boundary" not in ablate else [], cues))
            entry = lex.entry(term) if term else None
            if entry is not None and entry.category == "herb":
                for f in entry.surfaces():
                    drug.setdefault(f, (entry, s))
        forms = set(q.all_surfaces()) | {"+".join(g) for gs in q.groups.values() for g in gs}
        return {"asked": out, "forms": forms, "drug": drug}

    def _tier(self, hit: Hit, gates: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, list[str]]:
        """A pooled hit's tier and, when demoted, why: A when an asked drug's name occurs free (and as a drug where it
        must), D when it occurs but never so; else O when the hit matched no surface (a graph, lineage or sense hit), H
        when it matched only other lexicon forms of an asked drug (D when each stands only inside a longer name: 金沸
        in 金沸草), L when it matched another term's forms."""
        index = _layer(self.pack)
        g = gate_form(self.norm(hit.passage_id))
        present = [t for t in gates["asked"] if t[0] and t[0] in g]
        if present:
            yr = self._range(self.corpus.passage(hit.passage_id))
            why = ""
            for s, blockers, cues in present:
                offs = index.free_offsets(g, s, blockers, yr)
                if not offs:
                    why = why or f"demoted:inside {_covering(index, g, s, blockers, yr)}"
                elif cues is not None and not index.drug_context(g, s, offs, cues, cfg=cfg):
                    why = why or "demoted:no-context"
                else:
                    return "A", []
            return "D", [why]
        forms = [m for m in hit.matched if m in gates["forms"]]
        if not forms:
            return "O", []
        drug = [m for m in forms if m in gates["drug"]]
        if len(drug) < len(forms):
            return "L", []
        if "boundary" not in _ablations(cfg):
            normalize = self.pack.variants.normalize_text
            yr = self._range(self.corpus.passage(hit.passage_id))
            covers = []
            for raw in drug:
                s = normalize(raw)
                rec = index.record(s)
                blockers = list(rec.b) if rec is not None else []
                if not blockers or index.free_offsets(g, gate_form(s), blockers, yr):
                    break
                covers.append(_covering(index, g, gate_form(s), blockers, yr))
            else:
                return "D", [f"demoted:inside {covers[0]}"]
        return "H", []

    def _asked_groups(self, q: ParsedQuery) -> set[str]:
        """The alias groups of the drugs asked."""
        index, lex = _layer(self.pack), self.pack.lexicon
        out: set[str] = set()
        for s in q.drugs:
            term = q.asked.get(s)
            out.update(index.groups_for(None, [s]))
            entry = lex.entry(term) if term else None
            if entry is not None and entry.category == "herb":
                out.update(index.groups_for(entry.term_id, entry.surfaces()))
        return out

    def _other_referent(self, hit: Hit, groups: set[str]) -> list[str]:
        """The forms a lexicon-form hit matched that name an asked drug only in a window the passage misses (通草 for
        木通 in a passage of the Qing)."""
        index = _layer(self.pack)
        out: list[str] = []
        yr = None
        for raw in hit.matched if groups else ():
            s = self.pack.variants.normalize_text(raw)
            rec = index.record(s)
            pairs = [r for r in rec.r if r.g in groups] if rec is not None and not rec.stop else []
            if not pairs:
                continue
            yr = yr or self._range(self.corpus.passage(hit.passage_id))
            if all(r.v is not None and not overlaps(r.v, yr) for r in pairs):
                out.append(s)
        return out

    def _retain(self, q: ParsedQuery, M: list[Hit], m: int, k: int, books: list[str] | None, allowed: set[str] | None,
                seen: set[str], gates: dict[str, Any], cfg: dict[str, Any], search: bool = True) -> list[Hit]:
        """The asked name keeps the first ``m`` main places: when fewer of them write it, the best hits that do — from
        deeper in the pool, or (``search``) from a search of the asked drugs when the pool holds too few — take the
        places of the lowest others, which follow right after (moved down, never dropped)."""
        if sum(h.tier == "A" for h in M[:m]) >= m:
            return M
        if search and sum(h.tier == "A" for h in M) < m:
            M = M + self._asked_extra(q, k, books, allowed, seen, gates, cfg)
        top, rest = M[:m], M[m:]
        up = [h for h in rest if h.tier == "A"]
        places = [i for i, h in enumerate(top) if h.tier != "A"]
        n = min(len(places), len(up))
        if not n:
            return M
        places = places[len(places) - n:]
        down = [top[i] for i in places]
        for i, h in zip(places, up):
            top[i] = h
        moved = {id(h) for h in up[:n]}
        return top + down + [h for h in rest if id(h) not in moved]

    def _asked_extra(self, q: ParsedQuery, k: int, books: list[str] | None, allowed: set[str] | None, seen: set[str],
                     gates: dict[str, Any], cfg: dict[str, Any]) -> list[Hit]:
        """Passages that write an asked drug as asked (tier A) and that the fused pool missed, in BM25 order."""
        ranked = [pid for pid, _ in self.corpus.search(list(q.drugs), limit=4 * k, after=q.after, before=q.before,
                                                       book_ids=books)]
        if self.large:
            self.corpus.passages_by_id(ranked)
        wanted = set(books) if books else None
        out = []
        for i, pid in enumerate(ranked):
            if pid in seen or (allowed is not None and pid not in allowed):
                continue
            if wanted is not None and self.corpus.passage(pid).book_id not in wanted:
                continue
            hit = self._hit(q, pid, round(1000 * ASKED_SCORE / (61 + i), 4), {"bm25": i + 1})
            hit.tier, hit.flags = self._tier(hit, gates, cfg)
            if hit.tier == "A":
                out.append(hit)
        return out

    def _side(self, q: ParsedQuery, seen: set[str], books: list[str] | None, allowed: set[str] | None,
              cfg: dict[str, Any]) -> list[Hit]:
        """The side queue's alias hits (B): passages that write a searched expansion and none of the question's own
        surfaces, inside the query window met with the expansions' windows (widened, for passages dated by a range),
        taken by the first expansion whose gates they pass, and dealt round-robin over the drugs so that a shared name
        never gives every place to one of them."""
        index = _layer(self.pack)
        exps = [e for e in q.expansions if e.searched]
        if not exps:
            return []
        widen = int(cfg["widen"])
        lows = [None if e.valid is None or e.valid[0] is None else e.valid[0] - widen for e in exps]
        highs = [None if e.valid is None or e.valid[1] is None else e.valid[1] + widen for e in exps]
        lo = _bound(q.after, None if None in lows else min(lows), max)
        hi = _bound(q.before, None if None in highs else max(highs), min)
        if lo is not None and hi is not None and lo >= hi:
            return []
        ranked = [pid for pid, _ in self.corpus.search([e.surface for e in exps], limit=int(cfg["candidates"]),
                                                       after=lo, before=hi, book_ids=books)]
        if q.intent == "earliest":
            for e in exps:
                ranked += self.corpus.contains(e.surface, after=lo, before=hi, book_ids=books,
                                               verify=False)[:int(cfg["edges"])]
        ranked = [pid for pid in dict.fromkeys(ranked) if pid not in seen and (allowed is None or pid in allowed)]
        if self.large:
            self.corpus.passages_by_id(ranked)
        wanted = set(books) if books else None
        own = [x for x in (self.pack.variants.normalize_text(s) for s in q.all_surfaces()) if x]
        claimed: dict[str, list[tuple[str, Expansion, str, tuple[int | None, int | None], float | None]]] = {}
        for pid in ranked:
            passage = self.corpus.passage(pid)
            norm = self.norm(pid)
            if (wanted is not None and passage.book_id not in wanted) or any(s in norm for s in own):
                continue
            g, yr = gate_form(norm), self._range(passage)
            for e in exps:
                if index.accept(g, e, yr, cfg=cfg)[0]:
                    claimed.setdefault(e.group, []).append((pid, e, g, yr, self.corpus.year(passage)))
                    break
        queues = list(claimed.values())
        if q.intent == "earliest":
            for queue in queues:
                queue.sort(key=lambda t: t[4] if t[4] is not None else 9999)
            queues.sort(key=lambda queue: queue[0][4] if queue[0][4] is not None else 9999)
        order = [queue[i] for i in range(max(map(len, queues), default=0)) for queue in queues if i < len(queue)]
        hits = []
        for i, (pid, e, g, yr, _) in enumerate(order):
            score = round(1000 * float(cfg["alias_score"]) / (61 + i), 4)
            hit = self._hit(q, pid, score, {"alias": i + 1}, [e.surface])
            hit.tier = "B"
            reading, p = self._reading(g, e.surface, yr, cfg)
            hit.via = [{"surface": e.surface, "referent": e.head, "direction": e.direction,
                        "kind": KINDS.get(e.kind, e.kind), "status": e.status, "source": index.source_labels(e.src),
                        "witness": _witness(e.wit, cfg), "reading": reading, "p": p}]
            hits.append(hit)
        return hits

    def _reading(self, g: str, s: str, yr: tuple[int | None, int | None],
                 cfg: dict[str, Any]) -> tuple[str | None, float | None]:
        """The drug a name with alias referents reads as in a passage, and its p; (None, None) for any other name."""
        index = _layer(self.pack)
        rec = index.record(s)
        if rec is None or rec.stop or not rec.r:
            return None, None
        ref, p = index.reading(g, s, yr, cfg=cfg)
        return (ref.h if ref is not None else None), p

    def _annotate(self, q: ParsedQuery, hits: list[Hit], gates: dict[str, Any], cfg: dict[str, Any]) -> None:
        """``via`` for the side queue's lexicon-form hits and for hits on an asked drug's name (tier A) that is
        ambiguous or needs drug context (the reading, and ``homonym`` when there is none); an ``anachronism`` flag for
        any matched name written before its floor."""
        index, lex = _layer(self.pack), self.pack.lexicon
        normalize = self.pack.variants.normalize_text
        noted = {}
        for s, (gs, _, cues) in zip(q.drugs, gates["asked"]):
            rec = index.record(s)
            if rec is not None and rec.stop:
                continue  # a false friend asked through the lexicon: a demoted hit's flag says why
            ambiguous = len({r.g for r in index.referents(s, q.asked.get(s), lex) if r.st != "candidate"}) > 1
            if ambiguous or cues is not None:
                noted[s] = (gs, ambiguous)
        for h in hits:
            passage = self.corpus.passage(h.passage_id)
            yr = self._range(passage)
            if h.tier == "A" and noted:  # a demoted hit is no reading's: its flag says why it is not the drug
                g = gate_form(self.norm(h.passage_id))
                for s, (gs, ambiguous) in noted.items():
                    if gs not in g:
                        continue
                    reading, p = self._reading(g, s, yr, cfg)
                    # the drug it heads itself is no alias pair: it has no kind, status or source of its own
                    ref = next((r for r in index.readings(s) if r.h == reading and r.h != s), None)
                    h.via.append({"surface": s, "referent": reading, "direction": "asked",
                                  "kind": KINDS.get(ref.k, ref.k) if ref else None, "status": ref.st if ref else None,
                                  "source": index.source_labels(ref.src) if ref else [],
                                  "witness": _witness(ref.w, cfg) if ref else None, "reading": reading, "p": p})
                    if ambiguous and reading is None:
                        h.flags.append(f"homonym:{s}")
            elif h.tier == "X":
                h.via += self._lexicon_via(q, h, gates)
            edition = passage.temporal.t_edition
            for raw in h.matched:
                flag = index.floor_flag(normalize(raw), yr, (edition.start, edition.end) if edition else None)
                if flag and flag not in h.flags:
                    h.flags.append(flag)

    def _lexicon_via(self, q: ParsedQuery, h: Hit, gates: dict[str, Any]) -> list[dict[str, Any]]:
        """The labels of a side hit on lexicon forms: per form, the drug and the way it was reached — the drug an asked
        name is another name of (黄丹 → 铅丹: alias→drug, of the asked name's kind) or another name of an asked drug
        (山药 → 薯蓣: drug→alias, of the form's kind).  At ``asked_first: all`` a form of another term is labelled
        by its entry, a related term without a kind."""
        lex, normalize = self.pack.lexicon, self.pack.variants.normalize_text
        terms = {f: tid for tid, fs in q.surfaces.items() for f in fs}
        out = []
        for raw in dict.fromkeys(h.matched):
            if normalize(raw) in q.asked:
                continue
            if raw in gates["drug"]:
                entry, s = gates["drug"][raw]
                name, direction = (s, DIRECTIONS[0]) if raw == entry.term else (raw, DIRECTIONS[1])
                kind = _lexicon_kind(entry, name, normalize)
            else:
                entry = lex.entry(terms.get(raw, ""))
                if entry is None:
                    continue
                direction, kind = DIRECTIONS[1], _lexicon_kind(entry, raw, normalize, related="")
            out.append({"surface": normalize(raw), "referent": entry.term, "direction": direction,
                        "kind": self.pack.synonym_kind_label(kind) or None, "status": "open",
                        "source": _layer(self.pack).source_labels(["lexicon"]), "witness": None, "reading": None,
                        "p": None})
        return out

    def timeline(self, hits: list[Hit]) -> dict[str, list[str]]:
        periods: dict[str, list[str]] = {}
        for h in sorted(hits, key=lambda h: (h.year or 0, h.passage_id)):
            periods.setdefault(h.period or "?", []).append(h.passage_id)
        return periods

    # -------------------------------------------------------------- evidence
    def to_evidence(self, hit: Hit, *, agent: str, query: str, stance: Stance = Stance.NEUTRAL,
                    hypothesis_id: str | None = None, philological: float | None = None) -> EvidenceRecord:
        passage: Passage = self.corpus.passage(hit.passage_id)
        start, end = self.best_span(passage, hit.matched)
        return EvidenceRecord(
            id=stable_id("evd", passage.id, start, end, hypothesis_id, stance.value),
            passage_id=passage.id,
            book_id=passage.book_id,
            edition_id=passage.edition_id,
            locator=passage.locator,
            quote=passage.text[start:end],
            start=start,
            end=end,
            agent=agent,
            retrieval_method="hybrid",
            retrieval_score=hit.score,
            routes=sorted(hit.routes),
            query=query,
            hypothesis_id=hypothesis_id,
            stance=stance,
            transformation_history=["normalize:variants", f"retrieve:hybrid[{','.join(sorted(hit.routes))}]"],
            temporal=passage.temporal,
            confidence=ConfidenceVector(textual=0.8, philological=philological),
        )

    def best_span(self, passage: Passage, matched: list[str]) -> tuple[int, int]:
        """The sentence (。/；-delimited) containing the first matched surface; whole passage otherwise."""
        norm = self.pack.variants.normalize_text(passage.text)
        pos = -1
        for surface in matched:
            pos = norm.find(self.pack.variants.normalize_text(surface))
            if pos >= 0:
                break
        if pos < 0:
            return 0, len(passage.text)
        start = max(norm.rfind(c, 0, pos) for c in "。；！？") + 1
        ends = [norm.find(c, pos) for c in "。；！？" if norm.find(c, pos) != -1]
        end = min(ends) + 1 if ends else len(norm)
        return start, end
