"""The append-only event vocabulary. State is always ``reduce(events)``."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .base import Model, field_dict, field_list


class EventType(str, Enum):
    # lifecycle
    RESEARCH_CREATED = "ResearchCreated"
    PROFILE_LOADED = "ProfileLoaded"
    CORPUS_SCOPED = "CorpusScoped"
    ROUND_STARTED = "RoundStarted"
    ROUND_COMPLETED = "RoundCompleted"
    STOP_CONDITION_MET = "StopConditionMet"
    RESEARCH_COMPLETED = "ResearchCompleted"
    RESEARCH_STOPPED = "ResearchStopped"
    # task graph / agents (operational)
    TASK_PLANNED = "TaskPlanned"
    TASK_STARTED = "TaskStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    TASK_SKIPPED = "TaskSkipped"
    AGENT_SPAWNED = "AgentSpawned"
    AGENT_RELEASED = "AgentReleased"
    MODEL_ROUTED = "ModelRouted"
    LLM_CALLED = "LLMCalled"
    TOOL_CALLED = "ToolCalled"
    TOOL_RESULT = "ToolResult"
    TOOL_DENIED = "ToolDenied"
    HOOK_BLOCKED = "HookBlocked"
    BUDGET_EXCEEDED = "BudgetExceeded"
    # knowledge
    PASSAGE_ASSESSED = "PassageAssessed"
    TERM_RESOLVED = "TermResolved"
    EVIDENCE_RETRIEVED = "EvidenceRetrieved"
    CLAIM_EXTRACTED = "ClaimExtracted"
    CLAIM_REJECTED = "ClaimRejected"
    LINEAGE_DETECTED = "LineageDetected"
    CONTRADICTION_FOUND = "ContradictionFound"
    OBSERVATION_RECORDED = "ObservationRecorded"
    ANALYSIS_RECORDED = "AnalysisRecorded"
    # hypotheses
    HYPOTHESIS_GENERATED = "HypothesisGenerated"
    COUNTER_EVIDENCE_FOUND = "CounterEvidenceFound"
    HYPOTHESIS_REVIEWED = "HypothesisReviewed"
    HYPOTHESIS_REVISED = "HypothesisRevised"
    HYPOTHESIS_REJECTED = "HypothesisRejected"
    HYPOTHESIS_SCORED = "HypothesisScored"
    HYPOTHESIS_RANKED = "HypothesisRanked"
    GATE_EVALUATED = "GateEvaluated"
    # governance
    CHANGE_PROPOSED = "ChangeProposed"
    CHANGE_APPROVED = "ChangeApproved"
    CHANGE_REJECTED = "ChangeRejected"
    EXPERT_APPROVED = "ExpertApproved"
    EXPERT_REJECTED = "ExpertRejected"
    EXPERT_STEERED = "ExpertSteered"
    DECISION_RECORDED = "DecisionRecorded"
    MEMORY_WRITTEN = "MemoryWritten"
    # durability
    BRANCH_FORKED = "BranchForked"
    BRANCH_MERGED = "BranchMerged"
    CHECKPOINT_CREATED = "CheckpointCreated"
    ARTIFACT_PUBLISHED = "ArtifactPublished"
    TRANSACTION_COMMITTED = "TransactionCommitted"


OPERATIONAL_EVENTS = frozenset(
    {
        EventType.TASK_STARTED.value,
        EventType.AGENT_SPAWNED.value,
        EventType.AGENT_RELEASED.value,
        EventType.MODEL_ROUTED.value,
        EventType.LLM_CALLED.value,
        EventType.TOOL_CALLED.value,
        EventType.TOOL_RESULT.value,
        EventType.TOOL_DENIED.value,
        EventType.HOOK_BLOCKED.value,
        EventType.BUDGET_EXCEEDED.value,
        EventType.CHECKPOINT_CREATED.value,
        EventType.TRANSACTION_COMMITTED.value,
    }
)


@dataclass(kw_only=True)
class Event(Model):
    session_id: str
    seq: int
    type: str
    actor: str
    payload: dict = field_dict()
    task_id: str | None = None
    tx: str | None = None
    parent_seq: int | None = None
    used: list[str] = field_list()  # PROV: entities used
    generated: list[str] = field_list()  # PROV: entities generated
    ts: str = ""

    @property
    def id(self) -> str:
        return f"{self.session_id}:{self.seq}"

    @property
    def operational(self) -> bool:
        return self.type in OPERATIONAL_EVENTS
