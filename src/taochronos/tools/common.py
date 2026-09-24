"""Shared helpers for tool implementations (scope, claims, serialisation)."""

from __future__ import annotations

from typing import Any

from ..kernel.tools import ToolContext
from ..protocol.base import to_jsonable
from ..protocol.claims import Claim
from ..protocol.documents import Passage


def scope_ids(ctx: ToolContext) -> set[str] | None:
    """Passage ids the current session may see (corpus manifest minus hold-outs); None = everything."""
    session = ctx.session
    if session is None or session.state.corpus is None:
        return None
    return set(session.state.corpus.passage_ids)


def scope_passages(ctx: ToolContext) -> list[Passage]:
    corpus = ctx.cap("corpus")
    allowed = scope_ids(ctx)
    if getattr(corpus, "large", False):
        if allowed is None:
            # outside a research session a large corpus is represented by the working set (passages retrieved so far)
            knowledge = ctx.cap("knowledge")
            return corpus.passages_by_id(list(getattr(knowledge, "_working", {})))
        return corpus.passages_by_id(sorted(allowed))
    return [p for p in corpus.passages() if allowed is None or p.id in allowed]


def claims_in_scope(ctx: ToolContext) -> list[Claim]:
    """Session claims (the blackboard) when present; the corpus-wide index otherwise."""
    session = ctx.session
    if session is not None and session.state.claims:
        return sorted(session.state.claims.values(), key=lambda c: c.id)
    allowed = scope_ids(ctx)
    knowledge = ctx.cap("knowledge")
    if allowed is not None and getattr(ctx.cap("corpus"), "large", False):
        return knowledge.claims_for(sorted(allowed))
    claims = knowledge.claims()
    return [c for c in claims if allowed is None or c.passage_id in allowed]


def lineage_in_scope(ctx: ToolContext) -> list:
    session = ctx.session
    if session is not None and session.state.lineage:
        return sorted(session.state.lineage.values(), key=lambda e: e.id)
    if scope_ids(ctx) is None:
        return ctx.cap("knowledge").lineage()
    return ctx.cap("lineage").build(scope_passages(ctx), claims_in_scope(ctx))


def passage_card(ctx: ToolContext, passage: Passage, *, full: bool = False) -> dict[str, Any]:
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    book = corpus.book(passage.book_id)
    year = corpus.year(passage)
    card = {
        "passage_id": passage.id,
        "book_id": book.id,
        "title": book.title,
        "dynasty": book.dynasty,
        "year": year,
        "period": pack.periods.label(pack.periods.period_of(year) or ""),
        "locator": passage.locator.label(),
        "text": passage.text if full or len(passage.text) <= 120 else passage.text[:120] + "…",
    }
    if full:
        card["variants"] = [to_jsonable(v) for v in passage.variants]
        card["collation_status"] = passage.collation_status.value
        card["notes"] = passage.notes
        card["temporal"] = to_jsonable(passage.temporal)
    return card


def claim_card(claim: Claim) -> dict[str, Any]:
    return {
        "claim_id": claim.id,
        "passage_id": claim.passage_id,
        "relation": claim.relation.value,
        "quote": claim.quote,
        "arguments": [
            {"role": a.role.value, "term": a.term_id or a.surface, "negated": a.negated, **({"optional": True} if a.qualifiers.get("optional") else {})}
            for a in claim.arguments
        ],
        "modality": claim.modality,
    }
