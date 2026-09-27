"""Event-level authority: who may say what.

The reducer enforces what an event may *do* (the invariants of the research object); this table enforces who may
*emit* it.  A principal comes from an identity object the kernel handles (an :class:`~taochronos.kernel.policy.Actor`),
never from the text of an actor id: an agent that writes ``actor="human:x"`` is still an agent.

The four principals, by what they are trusted with:

* ``kernel`` — the harness itself: lifecycle, scheduling, the contract, checkpoints;
* ``validator`` — deterministic checks that grade work: gates, scores, rankings, objection closure after re-running a
  check, contract evaluation;
* ``human`` — expert decisions: G7, closing an interpretive objection, approving changes to canonical knowledge;
* ``agent`` — everything a model or procedure proposes: claims, evidence, observations, hypotheses, reviews, revisions,
  proposals.  An agent never grades, approves, closes or completes the research.
"""

from __future__ import annotations

from ..protocol.events import EventType as E

KERNEL, VALIDATOR, HUMAN, AGENT = "kernel", "validator", "human", "agent"
PRINCIPALS = (KERNEL, VALIDATOR, HUMAN, AGENT)
# how much a principal is trusted with (an identity may be narrowed, never widened)
RANK = {AGENT: 0, VALIDATOR: 1, HUMAN: 2, KERNEL: 3}

_ANY = frozenset(PRINCIPALS)
_WORK = frozenset({KERNEL, VALIDATOR, AGENT})  # producing or proposing knowledge
_GRADE = frozenset({KERNEL, VALIDATOR})  # grading it
_KERNEL = frozenset({KERNEL})
_HUMAN = frozenset({HUMAN})

EVENT_AUTHORITY: dict[str, frozenset[str]] = {
    # lifecycle: only the harness opens, scopes, advances and closes a research
    E.RESEARCH_CREATED.value: _KERNEL,
    E.PROFILE_LOADED.value: _KERNEL,
    E.CORPUS_SCOPED.value: _WORK,  # the curator proposes; the reducer keeps withheld material withheld
    E.ROUND_STARTED.value: _KERNEL,
    E.ROUND_COMPLETED.value: _KERNEL,
    E.STOP_CONDITION_MET.value: _KERNEL,
    E.RESEARCH_COMPLETED.value: _KERNEL,
    E.RESEARCH_STOPPED.value: frozenset({KERNEL, HUMAN}),
    E.CONTRACT_EVALUATED.value: _GRADE,
    # operations
    E.TASK_PLANNED.value: _WORK,
    E.TASK_STARTED.value: _WORK,
    E.TASK_COMPLETED.value: _WORK,
    E.TASK_FAILED.value: _WORK,
    E.TASK_SKIPPED.value: _WORK,
    E.AGENT_SPAWNED.value: _KERNEL,
    E.AGENT_RELEASED.value: _KERNEL,
    E.MODEL_ROUTED.value: _KERNEL,
    E.LLM_CALLED.value: frozenset({KERNEL, AGENT}),
    E.TOOL_CALLED.value: _ANY,
    E.TOOL_RESULT.value: _ANY,
    E.TOOL_DENIED.value: _ANY,
    E.HOOK_BLOCKED.value: _ANY,
    E.BUDGET_EXCEEDED.value: _ANY,
    E.BUDGET_RESERVED.value: _KERNEL,
    E.BUDGET_SETTLED.value: _KERNEL,
    E.RUN_MANIFEST_RECORDED.value: _KERNEL,
    # knowledge: produced by agents (and by validators re-deriving it)
    E.PASSAGE_ASSESSED.value: _WORK,
    E.TERM_RESOLVED.value: _WORK,
    E.EVIDENCE_RETRIEVED.value: _WORK,
    E.EVIDENCE_RETRACTED.value: frozenset({KERNEL, VALIDATOR, HUMAN}),
    E.CLAIM_EXTRACTED.value: _WORK,
    E.CLAIM_REJECTED.value: _WORK,
    E.LINEAGE_DETECTED.value: _WORK,
    E.CONTRADICTION_FOUND.value: _WORK,
    E.OBSERVATION_RECORDED.value: _WORK,
    E.ANALYSIS_RECORDED.value: _WORK,
    E.WARRANT_RECORDED.value: _WORK,
    # hypotheses: agents propose and review; validators grade; humans decide
    E.HYPOTHESIS_GENERATED.value: _WORK,
    E.COUNTER_EVIDENCE_FOUND.value: _WORK,
    E.HYPOTHESIS_REVIEWED.value: _WORK,
    E.HYPOTHESIS_REVISED.value: _WORK,
    E.HYPOTHESIS_REJECTED.value: frozenset({KERNEL, VALIDATOR, HUMAN}),
    E.HYPOTHESIS_SCORED.value: _GRADE,
    E.HYPOTHESIS_RANKED.value: _GRADE,
    E.HYPOTHESIS_CONFIRMED.value: _GRADE,
    E.GATE_EVALUATED.value: _GRADE,
    E.OBJECTION_RESOLUTION_PROPOSED.value: _WORK,
    E.OBJECTION_CLOSED.value: frozenset({VALIDATOR, HUMAN}),
    # governance
    E.CHANGE_PROPOSED.value: _ANY,
    E.CHANGE_APPROVED.value: frozenset({VALIDATOR, HUMAN}),
    E.CHANGE_REJECTED.value: frozenset({VALIDATOR, HUMAN}),
    E.EXPERT_APPROVED.value: _HUMAN,
    E.EXPERT_REJECTED.value: _HUMAN,
    E.EXPERT_STEERED.value: _HUMAN,
    E.DECISION_RECORDED.value: _ANY,
    E.MEMORY_WRITTEN.value: frozenset({KERNEL, VALIDATOR, HUMAN}),
    # durability
    E.BRANCH_FORKED.value: _KERNEL,
    E.BRANCH_MERGED.value: _KERNEL,
    E.CHECKPOINT_CREATED.value: _KERNEL,
    E.ARTIFACT_PUBLISHED.value: _GRADE,
    E.TRANSACTION_COMMITTED.value: _KERNEL,
}

WHY = {
    E.GATE_EVALUATED.value: "gates are graded by validators, never by the work they grade",
    E.HYPOTHESIS_SCORED.value: "scores are computed by validators",
    E.HYPOTHESIS_RANKED.value: "rankings are computed by validators",
    E.HYPOTHESIS_CONFIRMED.value: "confirmation is a validator's re-test on withheld material",
    E.OBJECTION_CLOSED.value: "an objection is closed by re-running its check (validator) or by an expert, never by a model",
    E.EXPERT_APPROVED.value: "only a human expert may approve or reject a hypothesis (Gate G7)",
    E.EXPERT_REJECTED.value: "only a human expert may approve or reject a hypothesis (Gate G7)",
    E.EXPERT_STEERED.value: "only a human expert steers a research",
    E.CHANGE_APPROVED.value: "agents may only propose changes; a validator or human must decide",
    E.CHANGE_REJECTED.value: "agents may only propose changes; a validator or human must decide",
    E.RESEARCH_COMPLETED.value: "only the harness completes a research",
    E.RESEARCH_CREATED.value: "only the harness opens a research contract",
    E.CONTRACT_EVALUATED.value: "the research contract is evaluated by validators",
    E.ARTIFACT_PUBLISHED.value: "publication is a validator's act after the contract is evaluated",
}


def allowed(event_type: str, principal: str) -> bool:
    return principal in EVENT_AUTHORITY.get(event_type, frozenset())


def reason(event_type: str, principal: str) -> str:
    why = WHY.get(event_type, "")
    allowed_ = "/".join(sorted(EVENT_AUTHORITY.get(event_type, frozenset()))) or "nobody"
    return f"{principal} may not emit {event_type} (allowed: {allowed_})" + (f": {why}" if why else "")
