"""The research task vocabulary and its dependency skeleton.

The Director (an agent, possibly an LLM) decides *which* tasks a round needs
and with what inputs.  The harness decides *how* they are wired: dependencies
come from this table, mandatory validation is always appended, and every task
whose producing spec has ``review_required`` gets a Skeptic review.  An LLM
planner therefore cannot produce an invalid or unreviewed task graph.
"""

from __future__ import annotations

from typing import Any

from ..protocol.research import TaskNode

# task kind → executing role
KIND_ROLE: dict[str, str] = {
    "plan": "director",
    "scope_corpus": "curator",
    "assess_philology": "philologist",
    "resolve_terms": "semanticist",
    "extract_claims": "extractor",
    "validate_claims": "validator",
    "map_terminology": "ontologist",
    "build_lineage": "lineage",
    "gather_evidence": "evidence",
    "mine_patterns": "pattern_miner",
    "test_statistics": "statistician",
    "trace_evolution": "evolution",
    "generate_hypotheses": "hypothesis",
    "falsify": "skeptic",
    "modern_evidence": "modern_evidence",
    "revise_hypotheses": "hypothesis",
    "falsify_revisions": "skeptic",
    "validate": "validator",
    "score": "validator",
    "meta_review": "meta_reviewer",
}

# roles executed by deterministic harness validators, never by agents
KERNEL_ROLES = frozenset({"validator"})

# kind → kinds it depends on (only those present in the same plan are wired)
DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "scope_corpus": (),
    "assess_philology": ("scope_corpus",),
    "resolve_terms": ("assess_philology",),
    "extract_claims": ("assess_philology", "resolve_terms"),
    "validate_claims": ("extract_claims",),
    "map_terminology": ("resolve_terms",),
    "build_lineage": ("extract_claims",),
    "gather_evidence": ("extract_claims", "build_lineage", "validate_claims"),
    "mine_patterns": (),
    "test_statistics": ("mine_patterns",),
    "trace_evolution": ("mine_patterns",),
    "generate_hypotheses": ("test_statistics", "trace_evolution"),
    "falsify": ("generate_hypotheses", "gather_evidence"),
    "modern_evidence": ("generate_hypotheses",),
    "revise_hypotheses": ("falsify",),
    "falsify_revisions": ("revise_hypotheses",),
    "validate": ("falsify", "falsify_revisions", "modern_evidence", "gather_evidence"),
    "score": ("validate",),
    "meta_review": ("score",),
}

# canonical order inside a round (also the tie-breaker for scheduling)
ORDER = {kind: i for i, kind in enumerate(DEPENDS_ON)}
ORDER["plan"] = -1

FOUNDATION_KINDS = ("scope_corpus", "assess_philology", "resolve_terms", "extract_claims", "validate_claims",
                    "map_terminology", "build_lineage", "gather_evidence")
DISCOVERY_KINDS = ("mine_patterns", "test_statistics", "trace_evolution", "generate_hypotheses", "falsify",
                   "modern_evidence", "revise_hypotheses", "falsify_revisions", "validate", "score", "meta_review")
MANDATORY_AFTER_HYPOTHESES = ("falsify", "validate", "score")
TOUCHES_HYPOTHESES = frozenset({"generate_hypotheses", "revise_hypotheses", "falsify", "falsify_revisions", "gather_evidence",
                                "modern_evidence"})


def task_id(round_: int, kind: str, suffix: str = "") -> str:
    return f"r{round_}.{kind}{'.' + suffix if suffix else ''}"


def plan_task(round_: int) -> TaskNode:
    return TaskNode(id=task_id(round_, "plan"), kind="plan", role="director", round=round_, inputs={"round": round_},
                    priority=0)


def wire(round_: int, items: list[dict[str, Any]], *, review_roles: set[str] | None = None) -> list[TaskNode]:
    """Turn planner output ``[{kind, inputs?, priority?, reason?}]`` into a valid, reviewed task graph."""
    review_roles = review_roles if review_roles is not None else {"hypothesis"}
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        kind = item.get("kind")
        if kind not in KIND_ROLE or kind == "plan":
            continue
        seen.setdefault(kind, item)
    kinds = set(seen)
    # harness-enforced structure: produced hypotheses are always reviewed, validated and scored …
    if kinds & {"generate_hypotheses", "revise_hypotheses"} or any(KIND_ROLE[k] in review_roles for k in kinds):
        for kind in MANDATORY_AFTER_HYPOTHESES:
            seen.setdefault(kind, {"kind": kind, "reason": "mandatory review/validation (harness policy)"})
    # … and anything that changes their evidence or reviews is followed by fresh gates and scores
    if round_ > 0 and kinds & TOUCHES_HYPOTHESES:
        for kind in ("validate", "score"):
            seen.setdefault(kind, {"kind": kind, "reason": "evidence or reviews changed: re-evaluate gates and scores (harness policy)"})
    if "revise_hypotheses" in seen:
        seen.setdefault("falsify_revisions", {"kind": "falsify_revisions", "reason": "revisions are re-reviewed (harness policy)"})
    if "extract_claims" in seen:
        seen.setdefault("validate_claims", {"kind": "validate_claims", "reason": "claims pass gates G0–G4 (harness policy)"})
    plan_id = task_id(round_, "plan")
    nodes = []
    for kind in sorted(seen, key=lambda k: ORDER.get(k, 99)):
        item = seen[kind]
        deps = [task_id(round_, d) for d in DEPENDS_ON.get(kind, ()) if d in seen]
        inputs = dict(item.get("inputs") or {})
        if item.get("reason"):
            inputs.setdefault("reason", item["reason"])
        nodes.append(TaskNode(
            id=task_id(round_, kind),
            kind=kind,
            role=KIND_ROLE[kind],
            round=round_,
            inputs=inputs,
            depends_on=[plan_id, *deps],
            priority=int(item.get("priority", 100 + ORDER.get(kind, 50))),
        ))
    return nodes
