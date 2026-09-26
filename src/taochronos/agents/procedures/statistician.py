"""Statistician (tool-first, no model): significance, multiple testing and coverage for every observation.

* lost knowledge — probability of seeing *no* later co-occurrence if the
  association had persisted at its early rate (and Wilson interval of that rate);
* concept drift — permutation p-values with Benjamini–Hochberg control;
* association rules — Fisher p-values with Benjamini–Hochberg control;
* hidden associations — empirical percentile of the link score among all
  unlinked candidate pairs;
* contradictions — temporal distance and school membership;
* coverage — passages per period, so absence in thin periods is not over-read.
"""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.events import EventType
from ...science.stats import benjamini_hochberg, wilson_interval
from .common import period_binner, year_fn

OUTPUT = "AnalysisSet"
FDR = 0.1


def instructions(ctx: Any) -> str:
    return "Test every new observation: significance, multiple-testing control, coverage."


def _members(claim: Any) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated}


def _lost(ctx: Any, obs: Any) -> dict[str, Any]:
    d = obs.data
    left, right, pivot = d["left"], d["right"], float(d["pivot_year"])
    year = year_fn(ctx)
    counts = {"left_early": 0, "both_early": 0, "left_late": 0, "right_early": 0, "right_late": 0}
    for c in ctx.state.claims.values():
        y = year(c)
        if y is None:
            continue
        m = _members(c)
        early = y < pivot
        if left in m:
            counts["left_early" if early else "left_late"] += 1
        if right in m:
            counts["right_early" if early else "right_late"] += 1
        if early and left in m and right in m:
            counts["both_early"] += 1
    rate_l = counts["both_early"] / counts["left_early"] if counts["left_early"] else 0.0
    rate_r = counts["both_early"] / counts["right_early"] if counts["right_early"] else 0.0
    p_l = (1 - rate_l) ** counts["left_late"]
    p_r = (1 - rate_r) ** counts["right_late"]
    lo, hi = wilson_interval(counts["both_early"], max(1, counts["left_early"]))
    coverage = ctx.state.corpus.coverage if ctx.state.corpus else {}
    return {"p_absence": round(max(p_l, p_r), 4), "early_rate": round(rate_l, 4), "early_rate_ci95": [round(lo, 4), round(hi, 4)],
            "counts": counts, "late_coverage": {k: v for k, v in coverage.items()},
            "significant": max(p_l, p_r) < 0.05,
            "method": "P(no later co-occurrence | association persisted at its early rate); conservative max over both terms"}


def _hidden(ctx: Any, obs: Any, universe: list[dict]) -> dict[str, Any]:
    scores = sorted((p["score"] for p in universe), reverse=True)
    mine = obs.data.get("score", 0.0)
    rank = sum(1 for s in scores if s > mine) + 1
    return {"rank": rank, "candidates": len(scores), "empirical_p": round(rank / max(1, len(scores)), 4),
            "method": "rank of the Adamic–Adar score among all unlinked candidate pairs"}


def _contradiction(ctx: Any, obs: Any) -> dict[str, Any]:
    claims = [ctx.state.claims[c] for c in obs.claim_ids if c in ctx.state.claims]
    year = year_fn(ctx)
    corpus = ctx.cap("corpus")
    years = [year(c) for c in claims if year(c) is not None]
    schools = {corpus.books[c.book_id].school for c in claims if c.book_id in corpus.books}
    return {"temporal_gap_years": round(max(years) - min(years), 1) if len(years) > 1 else 0.0,
            "same_school": len(schools) <= 1, "label": obs.data.get("label"), "type": obs.data.get("type")}


def draft(ctx: Any) -> dict[str, Any]:
    state = ctx.state
    done = {a.get("target_id") for a in state.analyses.values() if a.get("kind") == "statistics"}
    todo = [o for o in sorted(state.observations.values(), key=lambda o: o.id) if o.id not in done]
    analyses: list[dict[str, Any]] = []
    drift_p = {o.id: o.statistics.get("p_value", 1.0) for o in todo if o.kind == "concept_drift"}
    rule_p = {o.id: o.statistics.get("p_value", 1.0) for o in todo if o.kind == "association_rule"}
    drift_sig = benjamini_hochberg(drift_p, FDR) if drift_p else {}
    rule_sig = benjamini_hochberg(rule_p, FDR) if rule_p else {}
    universe = ctx.tool("analysis.link_prediction", k=5000) if any(o.kind == "hidden_association" for o in todo) else []
    binner = period_binner(ctx)
    for o in todo:
        if o.kind == "lost_knowledge":
            stats, method = _lost(ctx, o), "absence_probability"
        elif o.kind == "concept_drift":
            stats = {"p_value": o.statistics.get("p_value"), "bh_significant": bool(drift_sig.get(o.id)), "fdr": FDR,
                     "min_period_n": min((o.statistics.get("occurrences") or {"-": 0}).values())}
            method = "permutation_test+benjamini_hochberg"
        elif o.kind == "association_rule":
            stats = {"p_value": o.statistics.get("p_value"), "bh_significant": bool(rule_sig.get(o.id)), "fdr": FDR}
            method = "fisher_exact+benjamini_hochberg"
        elif o.kind == "hidden_association":
            stats, method = _hidden(ctx, o, universe), "empirical_rank"
        elif o.kind == "contradiction":
            stats, method = _contradiction(ctx, o), "temporal_school_profile"
        elif o.kind == "formula_evolution":
            overlaps = [s.get("overlap") for s in o.data.get("steps", []) if s.get("overlap") is not None]
            stats = {"mean_parent_child_overlap": round(sum(overlaps) / len(overlaps), 4) if overlaps else None,
                     "core_size": len(o.data.get("stable_core", [])), "size": o.data.get("size")}
            method = "family_profile"
        else:
            stats, method = {"qualitative": True, "n_passages": len(o.passage_ids)}, "descriptive"
        periods = sorted({binner.of(ctx.cap("corpus").year(ctx.cap("corpus").passage(p))) or "?" for p in o.passage_ids
                          if ctx.cap("corpus").has_passage(p)})
        stats["periods"] = periods
        analyses.append({"target_id": o.id, "kind": "statistics", "method": method, "result": {"statistics": stats}})
    return {"analyses": analyses}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    n = 0
    for a in output.get("analyses", []):
        target = a.get("target_id")
        if target not in ctx.state.observations:
            continue
        aid = stable_id("ana", "statistics", target, a.get("method"))
        ctx.emit(EventType.ANALYSIS_RECORDED, {"analysis_id": aid, "target_id": target, "kind": "statistics",
                                               "method": a.get("method"), "round": ctx.task.round, "result": a["result"]},
                 generated=[aid])
        n += 1
    return f"{n} observations tested"
