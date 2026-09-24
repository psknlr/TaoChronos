"""Knowledge Lineage Engine: cites / transcribes / rephrases / opposes / formula derivation.

Direction is decided by dates, not by assumption.  When date ranges overlap
the edge is kept but marked ``direction_certain = False``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable

from ...protocol.base import stable_id
from ...protocol.claims import Claim, ClaimRelation, Role
from ...protocol.documents import Passage
from ...protocol.research import LineageEdge
from ..classics.citations import CitationExtractor
from ..classics.corpus import Corpus
from ..classics.domain import DomainPack
from ..classics.reuse import TextReuseDetector, strip_punct

DETECTOR = "lineage@0.1"
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNIT_WEIGHT = {"斤": 16.0, "两": 1.0, "钱": 0.1, "分": 0.01, "铢": 1 / 24}


def cn_number(text: str) -> float | None:
    if text == "半":
        return 0.5
    total, current = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    return float(total + current) if (total + current) else None


def dose_value(dose: str | None) -> float | None:
    """Relative weight of a dose string (两-equivalents); None for counts/volumes/等分."""
    if not dose or "等分" in dose:
        return None
    value = 0.0
    matched = False
    for num, unit, half in re.findall(r"([一二三四五六七八九十百半]+)(斤|两|钱|分|铢)(半)?", dose.split("或")[0]):
        n = cn_number(num)
        if n is None:
            continue
        w = _UNIT_WEIGHT[unit]
        value += n * w + (0.5 * w if half else 0)
        matched = True
    return value if matched else None


@dataclass
class FormulaProfile:
    formula_id: str
    label: str
    herbs: list[str]
    surfaces: dict[str, str] = field(default_factory=dict)
    doses: dict[str, float] = field(default_factory=dict)
    claim_id: str | None = None
    passage_id: str | None = None
    book_id: str | None = None
    year: float | None = None
    year_range: tuple[float, float] | None = None
    source: str = "composition"  # composition | name

    @property
    def herb_set(self) -> set[str]:
        return set(self.herbs)

    def monarchs(self) -> set[str]:
        if self.doses:
            top = max(self.doses.values())
            return {h for h, d in self.doses.items() if d >= top - 1e-9}
        return set(self.herbs[:1])


class LineageBuilder:
    def __init__(
        self,
        pack: DomainPack,
        corpus: Corpus,
        citations: CitationExtractor,
        reuse: TextReuseDetector,
        *,
        min_shared: int = 3,
        min_overlap: float = 0.5,
    ) -> None:
        self.pack = pack
        self.corpus = corpus
        self.citations = citations
        self.reuse = reuse
        self.min_shared = min_shared
        self.min_overlap = min_overlap

    # ------------------------------------------------------------ helpers
    def _year(self, passage: Passage) -> float | None:
        return self.corpus.year(passage)

    def _range(self, passage: Passage) -> tuple[float, float] | None:
        rng = self.corpus.year_range(passage)
        return None if rng is None else (rng.start, rng.end)

    @staticmethod
    def _edge(relation: str, source: str, target: str, source_kind: str, target_kind: str, *, confidence: float,
              direction_certain: bool = True, evidence: dict | None = None, note: str = "",
              source_passage: str | None = None, target_passage: str | None = None, detector: str = DETECTOR) -> LineageEdge:
        return LineageEdge(
            id=stable_id("lin", relation, source, target),
            relation=relation,
            source_id=source,
            target_id=target,
            source_kind=source_kind,
            target_kind=target_kind,
            detector=detector,
            confidence=round(confidence, 4),
            direction_certain=direction_certain,
            source_passage=source_passage,
            target_passage=target_passage,
            evidence=evidence or {},
            note=note,
        )

    # ---------------------------------------------------------- citations
    def citation_edges(self, passages: Iterable[Passage]) -> list[LineageEdge]:
        edges: list[LineageEdge] = []
        all_passages = self.corpus.passages()
        for p in passages:
            for mention in self.citations.extract(p):
                fragments = [f for f in re.split(r"[，。；：、]", self.pack.variants.normalize_text(mention.quote)) if len(f) >= 3]
                parallels = []
                for other in all_passages:
                    if other.id == p.id:
                        continue
                    norm_other, _ = strip_punct(self.pack.variants.normalize_text(other.text))
                    hits = [f for f in fragments if f in norm_other]
                    if hits:
                        parallels.append({"passage": other.id, "book": other.book_id, "fragments": hits})
                for target, weight in sorted(mention.candidates.items(), key=lambda t: -t[1]):
                    in_target = [x for x in parallels if x["book"] == target]
                    if not in_target and weight < 0.3:
                        continue  # weak generic candidates (经曰 → 本经?) are not asserted
                    confidence = weight * (0.95 if in_target else 0.7)
                    edges.append(
                        self._edge(
                            "cites",
                            p.id,
                            target,
                            "passage",
                            mention.target_kind if mention.target_kind != "unresolved" else "external",
                            confidence=confidence,
                            evidence={
                                "marker": mention.surface,
                                "marker_kind": mention.kind,
                                "quote": mention.quote,
                                "candidate_weight": weight,
                                "quote_found_in_target": [x["passage"] for x in in_target],
                                "parallel_text": parallels,
                            },
                            source_passage=p.id,
                            target_passage=in_target[0]["passage"] if in_target else None,
                            note="explicit citation" + ("" if in_target else "; quoted text not found in the cited book within this corpus"),
                        )
                    )
        return edges

    # --------------------------------------------------------------- reuse
    def reuse_edges(self, passages: Iterable[Passage]) -> list[LineageEdge]:
        ps = [p for p in passages if p.kind != "formula"]
        edges: list[LineageEdge] = []
        for a, b in combinations(ps, 2):
            if a.book_id == b.book_id:
                continue
            ra, rb = self._range(a), self._range(b)
            ya, yb = self._year(a) or 0, self._year(b) or 0
            later, earlier = (a, b) if ya >= yb else (b, a)
            match = self.reuse.compare(later, earlier)
            if match is None:
                continue
            certain = ra is not None and rb is not None and (ra[1] < rb[0] or rb[1] < ra[0])
            confidence = max(match.containment, match.weighted_overlap) * (0.9 if certain else 0.7)
            edges.append(
                self._edge(
                    match.relation,
                    later.id,
                    earlier.id,
                    "passage",
                    "passage",
                    confidence=min(0.95, confidence + 0.1),
                    direction_certain=certain,
                    evidence={
                        "blocks": match.blocks,
                        "longest_block": match.longest_block,
                        "containment": match.containment,
                        "weighted_bigram_overlap": match.weighted_overlap,
                    },
                    source_passage=later.id,
                    target_passage=earlier.id,
                    note="" if certain else "overlapping date ranges: direction uncertain",
                )
            )
        return edges

    # ------------------------------------------------------------ formulas
    def formula_profiles(self, claims: Iterable[Claim], mention_claims: Iterable[Claim] = ()) -> list[FormulaProfile]:
        profiles: dict[str, FormulaProfile] = {}
        for c in claims:
            if c.relation != ClaimRelation.COMPOSED_OF:
                continue
            formula = c.args(Role.FORMULA)
            if not formula or formula[0].term_id is None:
                continue
            herbs = [a for a in c.args(Role.HERB) if a.term_id]
            passage = self.corpus.passage(c.passage_id)
            prof = FormulaProfile(
                formula_id=formula[0].term_id,
                label=formula[0].term_id.split(":", 1)[1],
                herbs=[a.term_id for a in herbs],  # type: ignore[misc]
                surfaces={a.term_id: a.surface for a in herbs},  # type: ignore[misc]
                doses={a.term_id: v for a in herbs if (v := dose_value(a.qualifiers.get("dose"))) is not None},  # type: ignore[misc]
                claim_id=c.id,
                passage_id=c.passage_id,
                book_id=c.book_id,
                year=self._year(passage),
                year_range=self._range(passage),
            )
            key = f"{prof.formula_id}@{prof.book_id}"
            if key not in profiles or (prof.year or 0) < (profiles[key].year or 0):
                profiles[key] = prof
        # compositions inferred from formula names (e.g. 麻黄杏仁甘草石膏汤)
        known = {p.formula_id for p in profiles.values()}
        for c in mention_claims:
            for a in c.args(Role.FORMULA):
                entry = self.pack.lexicon.entry(a.term_id or "")
                if entry is None or entry.term_id in known or not entry.name_complete:
                    continue
                herbs = [h for h in (self.pack.lexicon.canonical(x, "herb") for x in entry.name_herbs) if h]
                passage = self.corpus.passage(c.passage_id)
                profiles[f"{entry.term_id}@{c.book_id}"] = FormulaProfile(
                    formula_id=entry.term_id,
                    label=entry.term,
                    herbs=herbs,
                    surfaces={h: h.split(":", 1)[1] for h in herbs},
                    claim_id=c.id,
                    passage_id=c.passage_id,
                    book_id=c.book_id,
                    year=self._year(passage),
                    year_range=self._range(passage),
                    source="name",
                )
                known.add(entry.term_id)
        return sorted(profiles.values(), key=lambda p: (p.year or 0, p.formula_id))

    def compare_formulas(self, child: FormulaProfile, parent: FormulaProfile) -> dict:
        lex = self.pack.lexicon
        shared = child.herb_set & parent.herb_set
        related_pairs = []
        for h in child.herb_set - parent.herb_set:
            entry = lex.entry(h)
            for p in parent.herb_set - child.herb_set:
                pe = lex.entry(p)
                if entry and pe and (pe.term in entry.related or entry.term in pe.related):
                    related_pairs.append((p, h))
        effective = len(shared) + 0.5 * len(related_pairs)
        overlap = effective / max(1, min(len(child.herb_set), len(parent.herb_set)))
        processing = []
        renames = []
        for h in sorted(shared):
            cs, ps = child.surfaces.get(h, ""), parent.surfaces.get(h, "")
            if cs != ps:
                kind_c = next((k for s, k in (lex.entry(h).synonyms.items() if lex.entry(h) else []) if s == cs), None)
                kind_p = next((k for s, k in (lex.entry(h).synonyms.items() if lex.entry(h) else []) if s == ps), None)
                record = {"herb": h, "parent_surface": ps, "child_surface": cs, "kinds": [kind_p, kind_c]}
                (renames if "taboo_rename" in (kind_c, kind_p) else processing).append(record)
        return {
            "shared": sorted(shared),
            "added": sorted(child.herb_set - parent.herb_set - {h for _, h in related_pairs}),
            "removed": sorted(parent.herb_set - child.herb_set - {p for p, _ in related_pairs}),
            "substituted": [{"from": p, "to": h} for p, h in related_pairs],
            "surface_changes": processing,
            "renames": renames,
            "overlap": round(overlap, 4),
            "jaccard": round(len(shared) / max(1, len(child.herb_set | parent.herb_set)), 4),
            "monarch_shared": bool(parent.monarchs() & child.herb_set),
            "child_monarch_shared": bool(child.monarchs() & parent.herb_set),
        }

    def formula_edges(self, claims: list[Claim]) -> list[LineageEdge]:
        profiles = self.formula_profiles(claims, claims)
        edges: list[LineageEdge] = []
        # 1. name-pattern derivation: X加Y汤 → X汤
        names = {p.formula_id: p for p in profiles}
        for p in profiles:
            m = re.match(r"^(.+?)加(.+?)(汤|丸|散|饮)$", p.label)
            if m:
                base = self.pack.lexicon.canonical(m.group(1) + m.group(3), "formula")
                if base and base != p.formula_id:
                    edges.append(self._edge("formula_derived_from", p.formula_id, base, "formula", "formula", confidence=0.9,
                                            evidence={"pattern": "X加Y", "added": [m.group(2)]}, source_passage=p.passage_id,
                                            target_passage=names[base].passage_id if base in names else None, note="derivation stated by the formula name"))
        for c in claims:
            for a in c.args(Role.FORMULA):
                m = re.match(r"^(.+?)加(.+?)(汤|丸|散|饮)$", (a.term_id or ":").split(":", 1)[1])
                if m and not any(e.source_id == a.term_id for e in edges):
                    base = self.pack.lexicon.canonical(m.group(1) + m.group(3), "formula")
                    if base and base != a.term_id:
                        edges.append(self._edge("formula_derived_from", a.term_id, base, "formula", "formula", confidence=0.9,  # type: ignore[arg-type]
                                                evidence={"pattern": "X加Y", "added": [m.group(2)]}, source_passage=c.passage_id,
                                                note="derivation stated by the formula name"))
        # 2. composition similarity
        for child in profiles:
            best: tuple[float, float, FormulaProfile, dict] | None = None
            for parent in profiles:
                if parent.formula_id == child.formula_id or parent.year is None or child.year is None:
                    continue
                if not (parent.year_range and child.year_range and parent.year_range[1] < child.year_range[0]):
                    continue  # the parent must be strictly earlier
                cmp = self.compare_formulas(child, parent)
                if len(cmp["shared"]) < self.min_shared or cmp["overlap"] < self.min_overlap:
                    continue
                if not (cmp["monarch_shared"] and cmp["child_monarch_shared"]):
                    continue  # a derivation keeps the chief herb (君药) on both sides
                score = (cmp["overlap"], len(cmp["shared"]) + 0.5 * len(cmp["substituted"]), parent.year or 0)
                if best is None or score > best[:2] + ((best[2].year or 0),):
                    best = (score[0], score[1], parent, cmp)
            if best is not None:
                _, _, parent, cmp = best
                conf = 0.45 + 0.5 * cmp["overlap"] * (0.7 if child.source == "name" or parent.source == "name" else 1.0)
                edges.append(self._edge("formula_derived_from", child.formula_id, parent.formula_id, "formula", "formula",
                                        confidence=min(0.92, conf), evidence=cmp, source_passage=child.passage_id,
                                        target_passage=parent.passage_id,
                                        note=f"composition overlap {cmp['overlap']:.2f} ({'name-inferred' if 'name' in (child.source, parent.source) else 'text'})"))
        # 3. the same formula name re-used in a later book → inherits
        first_seen: dict[str, tuple[float, str, str]] = {}
        for c in sorted(claims, key=lambda c: (self.corpus.year(self.corpus.passage(c.passage_id)) or 0, c.id)):
            for a in c.args(Role.FORMULA):
                if a.term_id is None:
                    continue
                y = self.corpus.year(self.corpus.passage(c.passage_id)) or 0
                if a.term_id not in first_seen:
                    first_seen[a.term_id] = (y, c.book_id, c.passage_id)
                    continue
                y0, book0, passage0 = first_seen[a.term_id]
                shared_author = set(self.corpus.book(book0).authors) & set(self.corpus.book(c.book_id).authors)
                if c.book_id != book0 and y > y0 and not shared_author:
                    edge = self._edge("inherits", c.passage_id, passage0, "passage", "passage", confidence=0.75,
                                      evidence={"formula": a.term_id}, source_passage=c.passage_id, target_passage=passage0,
                                      note=f"re-uses {a.term_id.split(':', 1)[1]} first recorded in {book0}")
                    edge.id = stable_id("lin", "inherits", c.passage_id, passage0, a.term_id)
                    edges.append(edge)
        uniq: dict[str, LineageEdge] = {}
        for e in edges:
            uniq.setdefault(e.id, e)
        return list(uniq.values())

    # ------------------------------------------------------------ opposition
    def opposition_edges(self, passages: Iterable[Passage]) -> list[LineageEdge]:
        edges = []
        canon = self.pack.ontology.get("school_canon", {})
        for p in passages:
            norm = self.pack.variants.normalize_text(p.text)
            for marker in self.pack.opposition_markers:
                idx = norm.find(marker)
                if idx < 0:
                    continue
                window = norm[max(0, idx - 12): idx + len(marker) + 12]
                for school, book_id in canon.items():
                    if school in window and book_id != p.book_id and book_id in self.corpus.books:
                        edges.append(self._edge("opposes", p.id, book_id, "passage", "book", confidence=0.6,
                                                evidence={"marker": marker, "window": window, "school": school},
                                                source_passage=p.id, note=f"explicit disagreement with the {school} tradition"))
        uniq: dict[str, LineageEdge] = {}
        for e in edges:
            uniq.setdefault(e.id, e)
        return list(uniq.values())

    def build(self, passages: list[Passage], claims: list[Claim]) -> list[LineageEdge]:
        edges = self.citation_edges(passages) + self.reuse_edges(passages) + self.formula_edges(claims) + self.opposition_edges(passages)
        return sorted(edges, key=lambda e: e.id)
