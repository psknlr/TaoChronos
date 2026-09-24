"""Adapters that turn plugin services into the plain inputs the science engine expects."""

from __future__ import annotations

from typing import Any, Callable

from ..protocol.claims import Claim
from ..science.contradiction import ContradictionContext
from ..science.temporal import PeriodBinner


def binner(pack: Any) -> PeriodBinner:
    return PeriodBinner((p.id, p.label, p.start, p.end) for p in pack.periods.analysis)


def claim_year_fn(corpus: Any, basis: str | None = None) -> Callable[[Claim], float | None]:
    cache: dict[str, float | None] = {}

    def year(claim: Claim) -> float | None:
        if claim.passage_id not in cache:
            cache[claim.passage_id] = corpus.year(corpus.passage(claim.passage_id), basis) if corpus.has_passage(claim.passage_id) else claim.year()
        return cache[claim.passage_id]

    return year


class SenseOracle:
    """Resolves the period-bound sense of a term inside a claim's passage (memoised)."""

    def __init__(self, pack: Any, corpus: Any, resolutions: dict[str, Any] | None = None) -> None:
        self.pack = pack
        self.corpus = corpus
        self.resolutions = resolutions or {}
        self._cache: dict[tuple[str, str], str | None] = {}

    def __call__(self, claim: Claim, term_id: str) -> str | None:
        key = (claim.passage_id, term_id)
        if key in self._cache:
            return self._cache[key]
        surface = term_id.split(":", 1)[-1]
        sense = None
        for res in self.resolutions.values():
            if res.passage_id == claim.passage_id and res.term_id == term_id:
                sense = res.sense_id
                break
        if sense is None and self.pack.terminology.term(surface) and self.corpus.has_passage(claim.passage_id):
            passage = self.corpus.passage(claim.passage_id)
            norm = self.pack.variants.normalize_text(passage.text)
            context = {m.entry.term for m in self.pack.lexicon.match(norm)}
            sense, _, _, _ = self.pack.terminology.resolve(surface, norm, context, self.corpus.year(passage))
        self._cache[key] = sense
        return sense


def contradiction_context(pack: Any, corpus: Any, philology: Any, resolutions: dict[str, Any] | None = None,
                          lineage: list | None = None) -> ContradictionContext:
    lex = pack.lexicon
    polarity = {e.term_id: dict(e.polarity) for e in lex.entries.values() if e.polarity}
    origin = {e.term_id: e.origin for e in lex.entries.values() if e.origin}
    nature = {e.term_id: e.nature for e in lex.entries.values() if e.nature}
    related: dict[str, set[str]] = {}
    for e in lex.entries.values():
        for other in e.broader + e.related:
            target = lex.resolve(other)
            if target is None:
                continue
            related.setdefault(e.term_id, set()).add(target.term_id)
            related.setdefault(target.term_id, set()).add(e.term_id)
    for a, b in (pack.ontology.get("subject_links") or {}).items():
        related.setdefault(a, set()).add(b)
        related.setdefault(b, set()).add(a)
    name_etiology = {}
    for e in lex.entries.values():
        if e.name_etiology:
            name_etiology[e.term_id] = [t for t in (lex.canonical(x, "etiology") for x in e.name_etiology) if t]
    opposites: dict[str, str] = {}
    for a, b in pack.ontology.get("opposite_findings") or []:
        ta = lex.canonical(a) if not a.startswith("脉") else f"pulse:{a[1:]}"
        tb = lex.canonical(b) if not b.startswith("脉") else f"pulse:{b[1:]}"
        if ta and tb:
            opposites[ta], opposites[tb] = tb, ta
    for e in lex.entries.values():  # 不恶寒 ↔ 恶寒, 不渴 ↔ 渴 …
        if e.term[:1] in ("不", "无") and len(e.term) > 1:
            base = lex.canonical(e.term[1:])
            if base and e.category in ("symptom", "sign"):
                opposites.setdefault(e.term_id, base)
                opposites.setdefault(base, e.term_id)
    components = {}
    for e in lex.entries.values():
        if e.components and e.category in ("symptom", "sign"):
            components[e.term_id] = [t for t in (lex.canonical(c) for c in e.components) if t]
    school_of = {b.id: b.school for b in corpus.books.values()}

    def contested(claim: Claim, start: int | None, end: int | None) -> bool:
        if start is None or end is None or not corpus.has_passage(claim.passage_id):
            return False
        assessment = philology.assess(corpus.passage(claim.passage_id))
        return any(c.base_probability() < 0.6 for c in assessment.contested_at(start, end))

    reuse = {(e.source_passage, e.target_passage): e.relation for e in lineage or []
             if e.relation in ("transcribes", "rephrases", "inherits") and e.source_passage and e.target_passage}

    return ContradictionContext(
        reuse_fn=lambda a, b: reuse.get((a, b)),
        polarity=polarity,
        origin=origin,
        nature=nature,
        related=related,
        name_etiology=name_etiology,
        opposites=opposites,
        components=components,
        school_of=school_of,
        year_fn=claim_year_fn(corpus),
        sense_fn=SenseOracle(pack, corpus, resolutions),
        contested_fn=contested,
    )


def author_clusters(corpus: Any, lineage: list | None = None) -> Callable[[str], str]:
    """Books sharing an author or linked by transcription are not independent witnesses."""
    parent: dict[str, str] = {b: b for b in corpus.books}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_author: dict[str, str] = {}
    for book in corpus.books.values():
        for author in book.authors:
            key = author.split("（")[0].split(" ")[0]
            if key in by_author:
                union(by_author[key], book.id)
            else:
                by_author[key] = book.id
    for edge in lineage or []:
        if edge.relation in ("transcribes", "rephrases") and edge.source_passage and edge.target_passage:
            a = corpus.passage(edge.source_passage).book_id if corpus.has_passage(edge.source_passage) else None
            b = corpus.passage(edge.target_passage).book_id if corpus.has_passage(edge.target_passage) else None
            if a and b and a in parent and b in parent:
                union(a, b)
    return lambda book_id: find(book_id) if book_id in parent else book_id
