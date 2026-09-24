"""Provenance verification and the Claim → Pixel chain.

Every claim and evidence record must quote its passage verbatim at the stated
span.  The chain Hypothesis → Evidence/Claim → Passage → Book → Edition →
Volume → Chapter → Section → Page → Line → Region → Image is resolved as far
as the data allow, and each level reports whether it is available.
"""

from __future__ import annotations

from typing import Any, Callable

from ..protocol.claims import Claim
from ..protocol.evidence import EvidenceRecord


def _heading(passage: Any) -> str:
    loc = passage.locator
    return " ".join(x for x in (loc.volume, loc.chapter, loc.section) if x)


def verify_claim(claim: Claim, corpus: Any, normalize: Callable[[str], str]) -> list[str]:
    """Return a list of provenance problems (empty = verified)."""
    problems: list[str] = []
    if not corpus.has_passage(claim.passage_id):
        return [f"unknown passage {claim.passage_id}"]
    passage = corpus.passage(claim.passage_id)
    if passage.book_id != claim.book_id:
        problems.append(f"book mismatch: claim says {claim.book_id}, passage is in {passage.book_id}")
    if not (0 <= claim.start < claim.end <= len(passage.text)):
        problems.append(f"span {claim.start}:{claim.end} outside passage (len {len(passage.text)})")
    elif passage.text[claim.start: claim.end] != claim.quote:
        problems.append("quote is not verbatim at the stated span")
    heading = normalize(_heading(passage))
    for arg in claim.arguments:
        if arg.qualifiers.get("from_heading"):
            if normalize(arg.surface) not in heading:
                problems.append(f"heading-derived argument '{arg.surface}' not found in locator heading")
            continue
        if arg.start is None or arg.end is None:
            if not (arg.qualifiers.get("referent") or arg.qualifiers.get("inherited")):
                problems.append(f"argument '{arg.surface}' has no span")
            continue
        if not (0 <= arg.start < arg.end <= len(passage.text)):
            problems.append(f"argument '{arg.surface}' span outside passage")
            continue
        if normalize(passage.text[arg.start: arg.end]) != normalize(arg.surface):
            problems.append(f"argument '{arg.surface}' does not match text '{passage.text[arg.start: arg.end]}'")
    return problems


def verify_evidence(record: EvidenceRecord, corpus: Any) -> list[str]:
    if not corpus.has_passage(record.passage_id):
        return [f"unknown passage {record.passage_id}"]
    passage = corpus.passage(record.passage_id)
    if passage.book_id != record.book_id:
        return [f"book mismatch for evidence {record.id}"]
    if passage.text[record.start: record.end] != record.quote:
        return ["evidence quote is not verbatim at the stated span"]
    return []


def find_quote(corpus: Any, quote: str, normalize: Callable[[str], str], passage_id: str | None = None) -> list[tuple[str, int, int]]:
    """Locate a quote verbatim (or after variant normalisation) — used to catch fabricated citations."""
    targets = [corpus.passage(passage_id)] if passage_id and corpus.has_passage(passage_id) else corpus.passages()
    hits = []
    nq = normalize(quote)
    for p in targets:
        idx = p.text.find(quote)
        if idx >= 0:
            hits.append((p.id, idx, idx + len(quote)))
            continue
        idx = normalize(p.text).find(nq)
        if idx >= 0:
            hits.append((p.id, idx, idx + len(quote)))
    return hits


def provenance_chain(object_id: str, state: Any, corpus: Any) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    passage_id = None
    if object_id in getattr(state, "hypotheses", {}):
        h = state.hypotheses[object_id]
        chain.append({"level": "Hypothesis", "id": h.id, "label": h.statement[:80], "available": True})
        if h.supporting_evidence:
            object_id = h.supporting_evidence[0]
    if object_id in getattr(state, "evidence", {}):
        rec = state.evidence[object_id]
        chain.append({"level": "Evidence", "id": rec.id, "label": rec.quote, "available": True})
        if rec.claim_id and rec.claim_id in state.claims:
            c = state.claims[rec.claim_id]
            chain.append({"level": "Claim", "id": c.id, "label": f"{c.relation.value}: {c.quote}", "available": True})
        passage_id = rec.passage_id
    elif object_id in getattr(state, "claims", {}):
        c = state.claims[object_id]
        chain.append({"level": "Claim", "id": c.id, "label": f"{c.relation.value}: {c.quote}", "available": True})
        passage_id = c.passage_id
    elif corpus.has_passage(object_id):
        passage_id = object_id
    if passage_id is None or not corpus.has_passage(passage_id):
        return chain
    passage = corpus.passage(passage_id)
    chain.append({"level": "Passage", "id": passage.id, "label": passage.text, "available": True})
    book = corpus.books.get(passage.book_id)
    chain.append({"level": "Book", "id": passage.book_id, "label": book.title if book else passage.book_id, "available": book is not None})
    edition = book.edition(passage.edition_id) if book else None
    chain.append({"level": "Edition", "id": passage.edition_id, "label": edition.name if edition else None, "available": edition is not None})
    for level, value in passage.locator.chain()[2:]:
        chain.append({"level": level, "id": value, "label": value, "available": value is not None})
    return chain
