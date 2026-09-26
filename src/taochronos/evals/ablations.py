"""Ablations: which harness components carry the results?

* retrieval routes — earliest-attestation accuracy with all routes vs without the variant or sense route, BM25 only
* contradiction context — without sense resolution / without philology (contested readings)
* skeptic — the same pipeline with falsification switched off: what survives that should not?
* lineage clusters — replication (G5) counting books vs counting independent author/transcription clusters
* context OS — tokens a model call sees with the budgeted context view vs a naive dump of the blackboard
"""

from __future__ import annotations

import json
from typing import Any

from ..agents.context_views import ViewInput, build_sections
from ..kernel.context import ContextManager, estimate_tokens
from ..protocol.research import TaskNode
from ..verification.gates import GateEvaluator
from .base import EvalContext, SuiteResult
from .suites import contradiction, temporal


def retrieval_routes(ctx: EvalContext) -> dict[str, Any]:
    from ..plugins.retrieval import ROUTES

    variants = {"all": None, "no_variant": [r for r in ROUTES if r != "variant"], "no_sense": [r for r in ROUTES if r != "sense"],
                "bm25_only": ["bm25"], "dense_only": ["dense"]}
    return {name: temporal(ctx, routes=routes, name=f"temporal[{name}]").metrics["earliest_accuracy"] for name, routes in variants.items()}


def contradiction_context(ctx: EvalContext) -> dict[str, Any]:
    return {
        "full": contradiction(ctx).metrics["accuracy"],
        "no_sense_resolution": contradiction(ctx, sense=False).metrics["accuracy"],
        "no_philology": contradiction(ctx, philology_aware=False).metrics["accuracy"],
    }


def skeptic(ctx: EvalContext) -> dict[str, Any]:
    ref_h, ref = ctx.pipeline()
    h = ctx.harness()
    h.specs["skeptic"].procedure = "taochronos.evals.ablation_procedures"
    abl = ctx.run(h, session_id="ablation-skeptic")
    rejected = {x.statement for x in ref.state.hypotheses.values() if x.status == "rejected"}
    survived_abl = {x.statement for x in abl.state.hypotheses.values() if x.status == "survived"}
    return {
        "survived_with_skeptic": sum(1 for x in ref.state.hypotheses.values() if x.status == "survived"),
        "survived_without_skeptic": len(survived_abl),
        "rejected_with_skeptic": len(rejected),
        "false_survivals_without_skeptic": len(rejected & survived_abl),
        "revisions_with_skeptic": sum(1 for x in ref.state.hypotheses.values() if x.generation > 0),
    }


def lineage_clusters(ctx: EvalContext) -> dict[str, Any]:
    h, session = ctx.pipeline()
    state = session.state
    clustered = h.gates(state)
    naive = GateEvaluator(h.corpus, h.philology, h.pack, cluster_of=lambda b: b,
                          min_independent_sources=state.goal.required_evidence.min_independent_sources)
    inflated, passing = [], 0
    for x in state.active_hypotheses():
        g5c = next(r for r in clustered.evaluate_hypothesis(x, state) if r.gate == "G5").status
        g5n = next(r for r in naive.evaluate_hypothesis(x, state) if r.gate == "G5").status
        passing += g5c == "pass"
        if g5n == "pass" and g5c != "pass":
            inflated.append(x.id)
    return {"g5_pass_with_clusters": passing, "inflated_without_clusters": len(inflated), "inflated": inflated}


def context_os(ctx: EvalContext) -> dict[str, Any]:
    h, session = ctx.pipeline()
    state = session.state
    spec = h.specs["hypothesis"]
    task = TaskNode(id="r1.generate_hypotheses", kind="generate_hypotheses", role="hypothesis", round=1)
    view = ContextManager(int(spec.model.get("context_tokens", 24000))).build(
        build_sections(spec.context_view, ViewInput(state=state, task=task, spec=spec, capabilities=h.capabilities,
                                                    skills=h.skills, memory=h.memory)))
    naive = estimate_tokens(json.dumps({"observations": [o.to_dict() for o in state.observations.values()],
                                        "claims": [c.to_dict() for c in state.claims.values()],
                                        "evidence": [e.to_dict() for e in state.evidence.values()]}, ensure_ascii=False))
    return {"view_tokens": view.tokens, "naive_dump_tokens": naive, "reduction": round(1 - view.tokens / naive, 4) if naive else None,
            "compacted_sections": view.compacted, "omitted_sections": view.omitted}


def ablations(ctx: EvalContext) -> SuiteResult:
    metrics = {
        "retrieval_routes": retrieval_routes(ctx),
        "contradiction_context": contradiction_context(ctx),
        "lineage_clusters": lineage_clusters(ctx),
        "context_os": context_os(ctx),
    }
    if not ctx.quick:
        metrics["skeptic"] = skeptic(ctx)
    return SuiteResult("ablations", metrics)
