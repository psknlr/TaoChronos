"""Philology-Aware Temporal GraphRAG.

A research question is not a keyword query.  “宋代以前是否存在类似后世‘湿热蕴结’的理论？”
is executed as: concept decomposition → historical-sense expansion → variant
expansion → temporal constraint → seven retrieval routes (lexical, dense,
graph, temporal, citation, variant, sense) → reciprocal-rank fusion →
citation-lineage expansion → period-grouped claim comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...protocol.base import stable_id
from ...protocol.documents import Passage
from ...protocol.evidence import EvidenceRecord, Stance
from ...protocol.confidence import ConfidenceVector
from ..classics.corpus import Corpus
from ..classics.domain import DomainPack
from .index import BM25Index, DenseIndex, HashingEmbedder, query_tokens

ROUTES = ("bm25", "dense", "graph", "temporal", "citation", "variant", "sense")
DEFAULT_WEIGHTS = {"bm25": 1.0, "dense": 0.6, "graph": 1.0, "temporal": 0.5, "citation": 0.5, "variant": 0.6, "sense": 0.7}


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


class QueryAnalyzer:
    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack
        self._reverse_variants: dict[str, list[str]] = {}
        for src, (to, _) in pack.variants.chars.items():
            self._reverse_variants.setdefault(to, []).append(src)
        for w in pack.variants.words:
            self._reverse_variants.setdefault(w["to"], []).append(w["from"])

    def variant_spellings(self, surface: str) -> list[str]:
        forms = {surface}
        for norm, originals in self._reverse_variants.items():
            if norm in surface:
                for orig in originals:
                    forms.add(surface.replace(norm, orig))
        return sorted(forms - {surface})

    def analyze(self, text: str, *, after: int | None = None, before: int | None = None) -> ParsedQuery:
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
        mentions = [m for m in lex.match(norm) if not m.weak or len(norm) <= 4]
        for quoted in q.quoted:
            inner = [m for m in lex.match(self.pack.variants.normalize_text(quoted))]
            if inner:
                q.decomposition[quoted] = [m.term_id for m in inner]
                mentions.extend(inner)
        for m in mentions:
            if m.category in ("condition",) and m.entry.kind == "season":
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
        for surface in q.all_surfaces():
            spellings = self.variant_spellings(surface)
            if spellings:
                q.variants[surface] = spellings
        return q


class HybridRetriever:
    def __init__(self, pack: DomainPack, corpus: Corpus, knowledge: Any = None, embedder: Any = None,
                 weights: dict[str, float] | None = None) -> None:
        self.pack = pack
        self.corpus = corpus
        self.knowledge = knowledge
        self.analyzer = QueryAnalyzer(pack)
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.bm25 = BM25Index()
        self.dense = DenseIndex(embedder or HashingEmbedder())
        self._norm: dict[str, str] = {}
        for p in corpus.passages():
            norm = pack.variants.normalize_text(p.text)
            self._norm[p.id] = norm
            self.bm25.add(p.id, norm)
            self.dense.add(p.id, norm)

    # ------------------------------------------------------------------ routes
    def _candidates(self, q: ParsedQuery) -> set[str]:
        ids = set()
        for p in self.corpus.passages(after=q.after, before=q.before):
            ids.add(p.id)
        return ids

    def route_bm25(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        toks: list[str] = []
        for s in q.all_surfaces():
            toks.extend(query_tokens(self.pack.variants.normalize_text(s)))
        if not toks:
            toks = query_tokens(self.pack.variants.normalize_text(q.text))
        return self.bm25.search(toks, k, cand)

    def route_dense(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float]]:
        text = " ".join([q.text, *q.all_surfaces()])
        return self.dense.search(self.pack.variants.normalize_text(text), k, cand)

    def route_graph(self, q: ParsedQuery, cand: set[str], k: int) -> list[tuple[str, float, list[str]]]:
        if self.knowledge is None or not q.terms:
            return []
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
        norm = self._norm[pid]
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
        for pid in cand:
            norm = self._norm[pid]
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
               routes: list[str] | None = None, books: list[str] | None = None,
               allowed: set[str] | None = None) -> tuple[ParsedQuery, list[Hit]]:
        """``allowed`` restricts the search space (e.g. a session scope with a temporal hold-out)."""
        q = self.analyzer.analyze(text, after=after, before=before)
        cand = self._candidates(q)
        if allowed is not None:
            cand &= allowed
        if books:
            cand = {pid for pid in cand if self.corpus.passage(pid).book_id in set(books)}
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
            for edge in self.knowledge.lineage():
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
                hit.matched = [t for t in sense_heads if t in self._norm[hit.passage_id]]
                hit.note = hit.note or "concept-level match (sense route)"
            hit.claim_ids = claim_ids.get(hit.passage_id, [])
            hit.score = round(hit.score * 1000, 4)
        # relevance floor: a hit must match the query surfaces, a graph claim, a lineage edge or a targeted sense
        relevant = [h for h in fused.values() if h.matched or "graph" in h.routes or "citation" in h.routes]
        pool = relevant if (relevant or q.terms) else list(fused.values())
        hits = sorted(pool, key=lambda h: (-h.score, h.passage_id))[:k]
        if q.intent == "earliest":
            hits.sort(key=lambda h: (h.year if h.year is not None else 9999, -h.score))
        return q, hits

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
