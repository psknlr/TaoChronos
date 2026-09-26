"""Evidence Retriever: the Evidence Ledger.

Round 0 builds a question-level ledger with the philology-aware temporal
GraphRAG search.  Later rounds are targeted: for hypotheses the meta-review
flags as under-replicated, the agent looks for *independent* witnesses (other
author clusters, not transcriptions of the same source).  Every record is a
verbatim span; the commit re-verifies it, so a fabricated quote never reaches
the ledger.
"""

from __future__ import annotations

from typing import Any

from ...protocol.claims import Claim
from ...protocol.events import EventType
from ...protocol.evidence import EvidenceRecord, Stance
from ...verification.provenance import verify_evidence
from .common import block, cluster_fn, evidence_from_claim, evidence_record, focus_term_ids, locate, period_binner, surface, year_fn

OUTPUT = "EvidenceSet"
PER_QUERY = 8
PER_HYPOTHESIS = 3


def instructions(ctx: Any) -> str:
    if ctx.inputs.get("hypothesis_ids"):
        return ("Find independent textual witnesses (other books / author clusters, not transcriptions) for the listed "
                "hypotheses. Use classics.search and kg.claims; return records with verbatim quotes and a stance "
                "(supports / contradicts / context) and the hypothesis_id.")
    return ("Build the question-level evidence ledger: search the classics for the research question and focus terms "
            "(respect the period constraints) and return the most relevant verbatim passages with stance 'neutral'.")


def _members(claim: Claim) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated}


def _replicate(ctx: Any, h: Any) -> list[tuple[Claim, Stance, str]]:
    """Kind-specific replication: what would count as an *independent* witness for this hypothesis?

    Only hypotheses whose statement a further text can confirm are replicable by claims: an early
    attestation of a lost association, another indication with the rule's findings and formula, or a
    use of a drifting term in the sense its period predicts (a use in another sense is counter-evidence).
    Contradictions, testimony, lineages, renamings and lost sources are local by nature.
    """
    state = ctx.state
    obs = [state.observations[o] for o in h.observation_ids if o in state.observations]
    data = obs[0].data if obs else {}
    year = year_fn(ctx)
    out: list[tuple[Claim, Stance, str]] = []
    if h.kind == "lost_knowledge":
        terms = {data.get("left"), data.get("right")} - {None}
        pivot = data.get("pivot_year")
        for c in state.claims.values():
            y = year(c)
            if terms <= _members(c) and y is not None and pivot is not None and y < pivot:
                out.append((c, Stance.SUPPORTS, "early attestation"))
    elif h.kind == "association_rule":
        terms = set(data.get("lhs", [])) | {data.get("rhs")} - {None}
        for c in state.claims.values():
            if c.relation.value == "indicated_for" and terms <= _members(c):
                out.append((c, Stance.SUPPORTS, "same findings, same formula"))
    elif h.kind == "concept_drift":
        term = data.get("term")
        dominant = data.get("dominant_sense", {})
        binner = period_binner(ctx)
        senses = {(r.passage_id, r.term_id): r for r in state.term_resolutions.values()}
        for c in state.claims.values():
            if term not in _members(c):
                continue
            period = binner.of(year(c))
            res = senses.get((c.passage_id, term))
            if period not in dominant or res is None or res.sense_id is None:
                continue
            if res.sense_id == dominant[period]:
                out.append((c, Stance.SUPPORTS, f"sense {res.sense_id} as predicted for {period}"))
            elif res.probability >= 0.6:
                out.append((c, Stance.CONTRADICTS, f"sense {res.sense_id} ≠ {dominant[period]} predicted for {period}"))
    return sorted(out, key=lambda t: (year(t[0]) or 0, t[0].id))


def _targeted(ctx: Any, ids: list[str]) -> list[EvidenceRecord]:
    state = ctx.state
    cluster = cluster_fn(ctx)
    out: list[EvidenceRecord] = []
    for hid in ids:
        h = state.hypotheses.get(hid)
        if h is None:
            continue
        used = {state.evidence[e].claim_id for e in h.supporting_evidence + h.contradictory_evidence if e in state.evidence}
        clusters = {cluster(state.evidence[e].book_id) for e in h.supporting_evidence if e in state.evidence}
        found = 0
        for c, stance, why in _replicate(ctx, h):
            if c.id in used:
                continue
            if stance == Stance.SUPPORTS:
                if cluster(c.book_id) in clusters or found >= PER_HYPOTHESIS:
                    continue
                clusters.add(cluster(c.book_id))
                found += 1
            rec = evidence_from_claim(ctx, c, hypothesis_id=hid, stance=stance, method="replication:claims")
            rec.note = why
            out.append(rec)
            used.add(c.id)
        if not found:
            ctx.note(f"{hid}: no independent witness in scope")
    return out


def _question_level(ctx: Any) -> list[EvidenceRecord]:
    retriever = ctx.cap("retriever")
    corpus = ctx.cap("corpus")
    queries = [q for q in ctx.inputs.get("queries", []) if q]
    queries += [surface(t) for t in focus_term_ids(ctx)]
    out: dict[str, EvidenceRecord] = {}
    for q in dict.fromkeys(queries):
        result = ctx.tool("classics.search", query=q, k=PER_QUERY)
        for hit in result["hits"]:
            passage = corpus.passage(hit["passage_id"])
            start, end = retriever.best_span(passage, hit.get("matched", []))
            rec = evidence_record(ctx, passage.id, start, end, method="retrieval:hybrid", stance=Stance.NEUTRAL, query=q,
                                  score=hit.get("score"), note="routes: " + ",".join(hit.get("routes", [])))
            rec.routes = list(hit.get("routes", []))
            out.setdefault(rec.id, rec)
    return list(out.values())


def draft(ctx: Any) -> dict[str, Any]:
    ids = ctx.inputs.get("hypothesis_ids") or []
    records = _targeted(ctx, ids) if ids else _question_level(ctx)
    return {"records": [r.to_dict() for r in records]}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    in_scope = set(ctx.state.corpus.passage_ids) if ctx.state.corpus else None
    accepted: dict[str, dict[str, Any]] = {}
    rejected = 0
    for raw in output.get("records", []):
        if "id" in raw and "locator" in raw:
            rec = EvidenceRecord.from_dict(raw)
        else:  # model-proposed: the harness locates the span itself
            span = locate(ctx, raw.get("passage_id", ""), raw.get("quote", ""))
            if span is None:
                rejected += 1
                block(ctx, "provenance_validator", "BeforeGraphWrite", "evidence quote not found verbatim", raw.get("passage_id", ""))
                continue
            hid = raw.get("hypothesis_id")
            if hid and hid not in ctx.state.hypotheses:
                hid = None
            rec = evidence_record(ctx, raw["passage_id"], span[0], span[1], method=f"model:{ctx.route.model}",
                                  stance=Stance(raw.get("stance", "neutral")), hypothesis_id=hid,
                                  claim=ctx.state.claims.get(raw.get("claim_id") or ""), query=raw.get("query"), note=raw.get("note", ""))
        problems = verify_evidence(rec, corpus)
        if in_scope is not None and rec.passage_id not in in_scope:
            problems.append("passage outside research scope")
        if problems:
            rejected += 1
            block(ctx, "provenance_validator", "BeforeGraphWrite", "; ".join(problems), rec.id)
            continue
        accepted.setdefault(rec.id, rec.to_dict())
    records = [accepted[k] for k in sorted(accepted)]
    if records:
        ctx.emit(EventType.EVIDENCE_RETRIEVED, {"records": records}, generated=[r["id"] for r in records])
    targeted = sum(1 for r in records if r.get("hypothesis_id"))
    books = len({r["book_id"] for r in records})
    note = f"; {'; '.join(ctx.notes[:3])}" if ctx.notes else ""
    return f"{len(records)} evidence records from {books} books ({targeted} hypothesis-linked); {rejected} rejected{note}"
