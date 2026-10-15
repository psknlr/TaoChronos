"""Shared helpers for tool implementations (scope, claims, serialisation)."""

from __future__ import annotations

from typing import Any

from ..kernel.tools import ToolContext
from ..protocol.base import to_jsonable
from ..protocol.claims import Claim
from ..protocol.documents import Passage
from ..verification.scope import context_scope


def scope_ids(ctx: ToolContext) -> set[str] | None:
    """Passage ids the caller may see in the current session (its reading scope: an agent sees the exploration
    material; withheld sets are for validators and humans); None = everything."""
    scope = context_scope(ctx)
    return None if scope is None or scope.allowed is None else set(scope.allowed)


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


TERM_PASSAGES = 400


def whole_store(ctx: ToolContext) -> bool:
    """A large corpus read outside any research scope (a conversation, a command): the whole store is the scope."""
    session = ctx.session
    return (getattr(ctx.cap("corpus"), "large", False) and scope_ids(ctx) is None
            and not (session is not None and session.state.claims))


def term_passages(ctx: ToolContext, term_ids: list[str], *, after: float | None = None, before: float | None = None,
                  limit: int = TERM_PASSAGES) -> list[str]:
    """The passages of the whole store that write a term (any of its written forms of two characters or more; a single
    character is a word as often as a term), spread evenly over time when there are more than ``limit`` per term.
    They join the working set, so the analyses that read it see them too."""
    corpus, lex = ctx.cap("corpus"), ctx.cap("domain").lexicon
    ids: list[str] = []
    for tid in term_ids:
        entry = lex.entry(tid)
        found: list[str] = []
        for form in (entry.surfaces() if entry else [tid.split(":", 1)[-1]]):
            if len(form) >= 2:
                found += corpus.contains(form, after=after, before=before, verify=False)
        found = list(dict.fromkeys(found))
        if len(found) > limit:  # an even spread over the (year, id) order the index returns
            found = [found[round(i * (len(found) - 1) / (limit - 1))] for i in range(limit)]
        ids += found
    ids = list(dict.fromkeys(ids))
    ctx.cap("knowledge").touch(ids)
    return ids


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


def passage_card(ctx: ToolContext, passage: Passage, *, full: bool = False,
                 focus: list[str] | None = None) -> dict[str, Any]:
    """A passage as tools show it: its first 120 characters — or, when the first of the ``focus`` surfaces the text
    writes (a search hit's matched names) starts at character 100 or later of the normalised text, the 120 from 40
    before it, so that a passage found under a drug's other name shows that name."""
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
        "text": passage.text if full or len(passage.text) <= 120 else _excerpt(pack, passage.text, focus),
    }
    if full:
        card["variants"] = [to_jsonable(v) for v in passage.variants]
        card["collation_status"] = passage.collation_status.value
        card["notes"] = passage.notes
        card["temporal"] = to_jsonable(passage.temporal)
    return card


def _excerpt(pack: Any, text: str, focus: list[str] | None) -> str:
    """120 characters of a passage longer than that: from its start, or from 40 before the first focus surface it
    writes (found in the normalised text, which keeps the offsets) when that starts at character 100 or later."""
    norm = pack.variants.normalize_text(text) if focus else ""
    pos = -1
    for surface in focus or ():
        pos = norm.find(pack.variants.normalize_text(surface)) if surface else -1
        if pos >= 0:
            break
    if pos < 100:
        return text[:120] + "…"
    start = pos - 40
    return "…" + text[start:start + 120] + ("…" if start + 120 < len(text) else "")


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
