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
from ...science.stats import benjamini_hochberg, cluster_bootstrap, leave_one_cluster_out, wilson_interval
from .common import cluster_fn, period_binner, year_fn

OUTPUT = "AnalysisSet"
FDR = 0.1


def instructions(ctx: Any) -> str:
    return "Test every new observation: significance, multiple-testing control, coverage."


def _members(claim: Any) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated}


ABSENCE_LEVELS = {
    1: "在当前研究语料中未见（not found in the current corpus）",
    2: "在指定覆盖范围内未见（not found within the stated coverage）",
    3: "对抽样与来源假设稳健地未见（robust to sampling and source assumptions）",
}
MIN_LATE_PASSAGES = 20


def _lost(ctx: Any, obs: Any) -> dict[str, Any]:
    """Absence, stated in layers.  Level 1: the later texts of this corpus do not state the association.  Level 2:
    the later material is broad enough (passages and periods) for that silence to mean something.  Level 3: the early
    rate is replicated across source families and the absence stays significant with any one family left out.  A
    *historical decline* (level 4) is a hypothesis for experts to weigh, never a machine result."""
    d = obs.data
    left, right, pivot = d["left"], d["right"], float(d["pivot_year"])
    year = year_fn(ctx)
    cluster = cluster_fn(ctx)
    counts = {"left_early": 0, "both_early": 0, "left_late": 0, "right_early": 0, "right_late": 0}
    early_by_family: dict[str, list[int]] = {}
    for c in ctx.state.claims.values():
        y = year(c)
        if y is None:
            continue
        m = _members(c)
        early = y < pivot
        if left in m:
            counts["left_early" if early else "left_late"] += 1
            if early:
                early_by_family.setdefault(cluster(c.book_id), []).append(int(right in m))
        if right in m:
            counts["right_early" if early else "right_late"] += 1
        if early and left in m and right in m:
            counts["both_early"] += 1
    rate_l = counts["both_early"] / counts["left_early"] if counts["left_early"] else 0.0
    rate_r = counts["both_early"] / counts["right_early"] if counts["right_early"] else 0.0
    p_l = (1 - rate_l) ** counts["left_late"]
    p_r = (1 - rate_r) ** counts["right_late"]
    p_abs = max(p_l, p_r)
    lo, hi = wilson_interval(counts["both_early"], max(1, counts["left_early"]))
    rate = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    lofo = leave_one_cluster_out(early_by_family, lambda xs: round((1 - rate(xs)) ** counts["left_late"], 4))
    blo, bhi = cluster_bootstrap(early_by_family, rate, n=299, seed=3)
    coverage = ctx.state.corpus.coverage if ctx.state.corpus else {}
    manifest = ctx.state.corpus
    late_ids = [pid for pid in (manifest.passage_ids if manifest else []) if (ctx.cap("corpus").year(ctx.cap("corpus").passage(pid)) or 0) >= pivot
                if ctx.cap("corpus").has_passage(pid)] if manifest else []
    binner = period_binner(ctx)
    late_periods = {binner.of(ctx.cap("corpus").year(ctx.cap("corpus").passage(pid))) for pid in late_ids}
    families = sorted(early_by_family)
    level = 1
    if len(late_ids) >= MIN_LATE_PASSAGES and len(late_periods - {None}) >= 2:
        level = 2
        if p_abs < 0.05 and len(families) >= 2 and lofo["max"] < 0.05:
            level = 3
    return {"p_absence": round(p_abs, 4), "early_rate": round(rate_l, 4), "early_rate_ci95": [round(lo, 4), round(hi, 4)],
            "counts": counts, "late_coverage": {k: v for k, v in coverage.items()},
            "significant": p_abs < 0.05,
            "method": "P(no later co-occurrence | association persisted at its early rate); conservative max over both terms",
            "null": "the association persisted after the pivot at its early rate",
            "effect": {"early_rate": round(rate_l, 4), "early_rate_ci95_wilson": [round(lo, 4), round(hi, 4)],
                       "early_rate_ci95_family_bootstrap": [round(blo, 4), round(bhi, 4)]},
            "n": {"early_mentions": counts["left_early"], "late_mentions": counts["left_late"], "late_passages": len(late_ids)},
            "clusters": len(families),
            "sensitivity": {"leave_one_family_out_p_absence": lofo},
            "correction": "none (one test per observation; mined candidates are ranked, not selected by p)",
            "absence": {"level": level, "statement": ABSENCE_LEVELS[level],
                        "not_asserted": "历史上的衰落或失传（第 4 层）只能作为待专家判断的假说，不是机器结论"}}


def _hidden(ctx: Any, obs: Any, universe: list[dict]) -> dict[str, Any]:
    scores = sorted((p["score"] for p in universe), reverse=True)
    mine = obs.data.get("score", 0.0)
    rank = sum(1 for s in scores if s > mine) + 1
    return {"rank": rank, "candidates": len(scores), "empirical_p": round(rank / max(1, len(scores)), 4),
            "method": "rank of the Adamic–Adar score among all unlinked candidate pairs",
            "null": "the pair is an arbitrary unlinked pair of the graph", "effect": {"adamic_adar": mine},
            "correction": "none: a rank among candidates, not a significance test"}


def _families(ctx: Any, obs: Any) -> dict[str, list[str]]:
    """The observation's claims grouped by independent source family (author and transcription clusters)."""
    cluster = cluster_fn(ctx)
    out: dict[str, list[str]] = {}
    for cid in obs.claim_ids:
        c = ctx.state.claims.get(cid)
        if c is not None:
            out.setdefault(cluster(c.book_id), []).append(cid)
    return out


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
            occ = o.statistics.get("occurrences") or {"-": 0}
            stats = {"p_value": o.statistics.get("p_value"), "bh_significant": bool(drift_sig.get(o.id)), "fdr": FDR,
                     "min_period_n": min(occ.values()),
                     "method": "Jensen–Shannon divergence of context profiles; max-statistic permutation over all period boundaries",
                     "null": "the term's contexts are exchangeable across periods",
                     "effect": {"jsd": o.statistics.get("jsd")}, "n": occ,
                     "correction": f"Benjamini–Hochberg across {len(drift_p)} drift observation(s), q={FDR}; the boundary choice is inside the test",
                     "sensitivity": {"p_value_naive_chosen_boundary": o.statistics.get("p_value_naive")},
                     "clusters": len({b for books in (o.data.get("books") or {}).values() for b in books})}
            method = "max_statistic_permutation+benjamini_hochberg"
        elif o.kind == "association_rule":
            fam = _families(ctx, o)
            support = {k: len(v) for k, v in fam.items()}
            lofo = leave_one_cluster_out(fam, len)
            stats = {"p_value": o.statistics.get("p_value"), "bh_significant": bool(rule_sig.get(o.id)), "fdr": FDR,
                     "method": "one-sided Fisher exact test on indication claims",
                     "null": "the formula is used independently of the finding combination",
                     "effect": {"lift": o.statistics.get("lift"), "confidence": o.statistics.get("confidence")},
                     "n": {"support": o.statistics.get("support")},
                     "correction": f"Benjamini–Hochberg across {len(rule_p)} rule(s), q={FDR}",
                     "clusters": len(fam), "sensitivity": {"leave_one_family_out_support": {**lofo, "by_family": support}}}
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
