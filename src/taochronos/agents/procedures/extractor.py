"""Claim Extractor: passages → claim hyperedges with verbatim spans.

The lexicon-rule extractor always runs.  In hybrid mode a model may propose
additional claims for passages the rules could not parse; those arrive in a
simplified form (relation, quote, argument surfaces) and the harness locates
every span itself.  All claims — rule or model — pass the BeforeClaimCommit
hooks (provenance validator, anachronism guard) or are rejected on the record.
"""

from __future__ import annotations

from typing import Any

from ...kernel.hooks import HookPoint
from ...protocol.base import stable_id
from ...protocol.claims import Claim, ClaimArgument, ClaimRelation, ExtractionInfo, Role
from ...protocol.confidence import ConfidenceVector
from ...protocol.events import EventType
from .common import locate, philological_confidence, scope_passages

OUTPUT = "ClaimSet"
LLM_CLAIM_CONFIDENCE = 0.55


def instructions(ctx: Any) -> str:
    relations = ", ".join(r.value for r in ClaimRelation)
    roles = ", ".join(r.value for r in Role)
    return ("The rule-based extractor has already processed every passage. Propose additional claims only for passages "
            "listed under 'Passages without extracted claims' where the text makes a clear medical assertion. Each claim "
            f"needs: passage_id, relation (one of: {relations}), a verbatim quote from the passage, and arguments "
            f"(role one of: {roles}; surface copied exactly from the quote; negated=true for 不/无/非 negations). "
            "Do not normalise, translate or modernise terms.")


def draft(ctx: Any) -> dict[str, Any]:
    extractor = ctx.cap("extractor")
    philology = ctx.cap("philology")
    claims = []
    for p in scope_passages(ctx):
        assessment = ctx.state.philology.get(p.id) or philology.assess(p)
        claims.extend(c.to_dict() for c in extractor.extract(p, assessment))
    return {"claims": claims}


def llm_draft(ctx: Any, full: dict[str, Any]) -> dict[str, Any]:
    return {"claims": []}


def _from_model(ctx: Any, raw: dict[str, Any]) -> tuple[Claim | None, str]:
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    normalize = pack.variants.normalize_text
    pid = raw.get("passage_id", "")
    if not corpus.has_passage(pid):
        return None, f"unknown passage {pid}"
    try:
        relation = ClaimRelation(raw.get("relation"))
    except ValueError:
        return None, f"unknown relation {raw.get('relation')!r}"
    span = locate(ctx, pid, raw.get("quote", ""))
    if span is None:
        return None, "quote not found verbatim in the passage"
    passage = corpus.passage(pid)
    start, end = span
    norm = normalize(passage.text)
    args: list[ClaimArgument] = []
    for a in raw.get("arguments", []):
        try:
            role = Role(a.get("role"))
        except ValueError:
            return None, f"unknown role {a.get('role')!r}"
        surface = a.get("surface", "")
        idx = norm.find(normalize(surface), start, end) if surface else -1
        if idx < 0:
            return None, f"argument '{surface}' not inside the quote"
        entry = pack.lexicon.resolve(surface)
        args.append(ClaimArgument(role=role, surface=passage.text[idx: idx + len(surface)], term_id=entry.term_id if entry else None,
                                  start=idx, end=idx + len(surface), negated=bool(a.get("negated", False))))
    if len(args) < 2 and relation != ClaimRelation.THEORY:
        return None, "a claim needs at least two arguments"
    key_args = sorted(f"{a.role.value}:{a.key}:{a.start}:{int(a.negated)}" for a in args)
    claim = Claim(
        id=stable_id("clm", pid, relation.value, start, end, key_args),
        passage_id=pid, book_id=passage.book_id, edition_id=passage.edition_id, relation=relation, arguments=args,
        quote=passage.text[start:end], start=start, end=end, temporal=passage.temporal,
        extraction=ExtractionInfo(method="llm", model=ctx.route.model, agent=ctx.actor.id, confidence=LLM_CLAIM_CONFIDENCE),
        modality=raw.get("modality", "assertive"), context=raw.get("context", ""),
        confidence=ConfidenceVector(textual=0.7, philological=philological_confidence(ctx, pid, start, end), extraction=LLM_CLAIM_CONFIDENCE),
    )
    return claim, ""


def commit(ctx: Any, output: dict[str, Any]) -> str:
    in_scope = {p.id for p in scope_passages(ctx)}
    candidates: dict[str, Claim] = {}
    rejections: list[dict[str, Any]] = []
    for raw in (ctx.draft or {}).get("claims", []) if ctx.draft is not output else []:
        claim = Claim.from_dict(raw)
        candidates[claim.id] = claim
    for raw in output.get("claims", []):
        if "id" in raw and "temporal" in raw:
            claim = Claim.from_dict(raw)
        else:
            claim, why = _from_model(ctx, raw)
            if claim is None:
                rejections.append({"claim_id": stable_id("clm", raw.get("passage_id"), raw.get("quote")), "reason": why,
                                   "passage_id": raw.get("passage_id"), "quote": raw.get("quote", ""), "source": "model"})
                continue
        candidates.setdefault(claim.id, claim)
    accepted = []
    for claim in sorted(candidates.values(), key=lambda c: c.id):
        if claim.passage_id not in in_scope:
            rejections.append({"claim_id": claim.id, "reason": "passage outside research scope", "passage_id": claim.passage_id,
                               "quote": claim.quote})
            continue
        verdict = ctx.hook(HookPoint.BEFORE_CLAIM_COMMIT, claim, subject_id=claim.id)
        if not verdict.allow:
            rejections.append({"claim_id": claim.id, "reason": f"{verdict.hook}: {verdict.reason}", "passage_id": claim.passage_id,
                               "quote": claim.quote})
            continue
        accepted.append(claim.to_dict())
    if accepted:
        ctx.emit(EventType.CLAIM_EXTRACTED, {"claims": accepted}, generated=[c["id"] for c in accepted])
    if rejections:
        ctx.emit(EventType.CLAIM_REJECTED, {"rejections": rejections})
    by_method: dict[str, int] = {}
    for c in accepted:
        by_method[c["extraction"]["method"]] = by_method.get(c["extraction"]["method"], 0) + 1
    detail = ", ".join(f"{k}={v}" for k, v in sorted(by_method.items()))
    return f"{len(accepted)} claims committed ({detail}); {len(rejections)} rejected"
