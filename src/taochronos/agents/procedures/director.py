"""TaoChronos — the Research Director.

Decides which specialist agents a round needs (dynamic spawning, not a fixed
team) and records why.  Round 0 builds the evidence foundation; round 1 runs
discovery; later rounds deepen evidence for promising but weakly replicated
hypotheses, revise what the Skeptic sent back, or run sensitivity analyses.
An empty plan means “no productive next step” — the harness then stops.
"""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.events import EventType
from ...protocol.research import Decision
from ..planning import wire
from .common import focus_term_ids, surface

OUTPUT = "ResearchPlan"


def instructions(ctx: Any) -> str:
    r = ctx.inputs.get("round", ctx.task.round)
    return (
        f"Plan research round {r}. Pick the task kinds (and inputs) that best serve the research question given the "
        "current state and the meta-review. Round 0 builds the evidence foundation (curation, philology, semantics, "
        "extraction, lineage, evidence). Round 1 mines patterns and generates, falsifies and revises hypotheses. Later "
        "rounds should deepen evidence for promising hypotheses that lack independent sources, revise hypotheses the "
        "Skeptic sent back, or run sensitivity analyses — never repeat work that cannot change the result. Return an "
        "empty task list if nothing productive remains. The harness wires dependencies and always adds review, "
        "validation and scoring."
    )


def _modern_relevant(ctx: Any, focus: list[str]) -> bool:
    if "G8" in (ctx.goal.required_validation if ctx.goal else []):
        return True
    records = ctx.services.get("modern_evidence", [])
    surfaces = {surface(t) for t in focus}
    return any(surfaces & set(r.get("related_terms", [])) for r in records)


def _mapping_relevant(ctx: Any, focus: list[str]) -> bool:
    terminology = ctx.cap("domain").terminology
    for tid in focus:
        term = terminology.term(surface(tid))
        if term and any(terminology.sense_meta.get(s.id, {}).get("candidates") for s in term.senses):
            return True
    return False


def _latest_meta(ctx: Any) -> dict[str, Any]:
    metas = [a for a in ctx.state.analyses.values() if a.get("kind") == "meta_review"]
    return max(metas, key=lambda a: a.get("round", 0)).get("result", {}) if metas else {}


def draft(ctx: Any) -> dict[str, Any]:
    r = int(ctx.inputs.get("round", ctx.task.round))
    goal = ctx.goal
    tracks = list(goal.tracks) if goal else ["D1", "D2", "D3", "D4", "D5"]
    focus = focus_term_ids(ctx)
    tasks: list[dict[str, Any]] = []
    if r == 0:
        tasks += [
            {"kind": "scope_corpus", "reason": "freeze the corpus manifest (scope, hold-out, coverage) before any analysis"},
            {"kind": "assess_philology", "reason": "readings, variants and collation status condition every later claim"},
            {"kind": "resolve_terms", "reason": "period-bound senses guard against homonymy and anachronism"},
            {"kind": "extract_claims", "reason": "claim hyperedges with verbatim spans are the unit of analysis"},
            {"kind": "build_lineage", "reason": "citation / transcription / formula lineage separates independent witnesses"},
            {"kind": "gather_evidence", "inputs": {"queries": [goal.question] if goal else []},
             "reason": "question-level evidence ledger"},
        ]
        if _mapping_relevant(ctx, focus):
            tasks.append({"kind": "map_terminology", "inputs": {"terms": focus},
                          "reason": "focus terms have modern candidates: propose typed (never '=') mappings"})
        rationale = f"Foundation round for “{goal.question if goal else ''}”; focus terms: {', '.join(surface(t) for t in focus) or '—'}."
        return {"rationale": rationale, "focus": [surface(t) for t in focus], "tasks": tasks}

    has_hypotheses = bool(ctx.state.hypotheses)
    if r == 1 or not has_hypotheses:
        tasks += [
            {"kind": "mine_patterns", "inputs": {"tracks": tracks}, "reason": f"tool-first discovery engines {', '.join(tracks)}"},
            {"kind": "test_statistics", "reason": "significance, multiple-testing control and coverage checks"},
            {"kind": "generate_hypotheses", "reason": "turn observations into testable, evidence-bound hypotheses"},
            {"kind": "revise_hypotheses", "reason": "narrow hypotheses the Skeptic sends back"},
            {"kind": "meta_review", "reason": "systemic weaknesses and next-round recommendations"},
        ]
        if {"D2", "D3"} & set(tracks):
            tasks.append({"kind": "trace_evolution", "reason": "concept timelines and formula family trees"})
        if _modern_relevant(ctx, focus):
            tasks.append({"kind": "modern_evidence", "reason": "cross-space bridge candidates need Gate G8"})
        return {"rationale": f"Discovery round {r}: mine, hypothesise, falsify, revise, validate, score.",
                "focus": [surface(t) for t in focus], "tasks": tasks}

    # deepening rounds: act on the meta-review, never repeat work that cannot change the outcome
    meta = _latest_meta(ctx)
    recs = meta.get("recommendations", [])
    replicate = sorted({rec["target"] for rec in recs if rec.get("action") == "gather_evidence" and rec.get("target") in ctx.state.hypotheses})
    revise = sorted(h.id for h in ctx.state.hypotheses.values() if h.status == "needs_revision")
    sensitivity = [rec for rec in recs if rec.get("action") == "sensitivity"]
    if replicate:
        tasks.append({"kind": "gather_evidence", "inputs": {"hypothesis_ids": replicate},
                      "reason": f"{len(replicate)} hypotheses lack independent sources (G5)"})
    if revise:
        tasks.append({"kind": "revise_hypotheses", "inputs": {"hypothesis_ids": revise},
                      "reason": f"{len(revise)} hypotheses await revision"})
    if sensitivity and "D1" in tracks:
        pivots = sorted({int(rec.get("pivot_year", 1127)) for rec in sensitivity})
        tasks += [{"kind": "mine_patterns", "inputs": {"tracks": ["D1"], "pivot_year": pivots[0], "sensitivity": True},
                   "reason": "sensitivity analysis: alternative pivot for lost-knowledge detection"},
                  {"kind": "test_statistics", "reason": "statistics for the sensitivity observations"},
                  {"kind": "generate_hypotheses", "reason": "hypotheses from the sensitivity analysis"}]
    if tasks:
        tasks.append({"kind": "falsify", "inputs": {"hypothesis_ids": replicate, "rereview": True},
                      "reason": "re-review after new evidence"})
        tasks.append({"kind": "meta_review", "reason": "update recommendations"})
        rationale = f"Deepening round {r}: " + "; ".join(t["reason"] for t in tasks[:3])
    else:
        rationale = f"Round {r}: no recommendation can change the result (no replication gaps, revisions or sensitivity analyses pending)."
    return {"rationale": rationale, "focus": [surface(t) for t in focus], "tasks": tasks}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    r = int(ctx.inputs.get("round", ctx.task.round))
    review_roles = {s.role for s in ctx.runtime.specs.values() if s.review_required}
    nodes = wire(r, output.get("tasks", []), review_roles=review_roles)
    if nodes:
        ctx.emit(EventType.TASK_PLANNED, {"tasks": [n.to_dict() for n in nodes]}, generated=[n.id for n in nodes])
    decision = Decision(
        id=stable_id("dec", "plan", r),
        kind="plan",
        summary=f"round {r}: " + (", ".join(n.kind for n in nodes) if nodes else "no further tasks"),
        rationale=output.get("rationale", ""),
        made_by=ctx.actor.id,
        refs=[n.id for n in nodes],
    )
    ctx.emit(EventType.DECISION_RECORDED, {"decisions": [decision.to_dict()]}, generated=[decision.id])
    return f"planned {len(nodes)} task(s) for round {r}"
