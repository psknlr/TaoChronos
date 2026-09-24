"""GoalSpec contract, the research task graph and the shared ResearchObject (the blackboard).

Agents never coordinate by chatting.  They read slices of the ResearchObject and
change it only by emitting typed events that the kernel's reducer applies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .artifacts import Artifact
from .base import Model, content_hash, field_dict, field_list
from .claims import Claim
from .documents import YearRange
from .evidence import EvidenceRecord
from .hypothesis import Hypothesis, HypothesisReview, Observation
from .outputs import PhilologyAssessment, TermResolution

ALL_TRACKS = ("D1", "D2", "D3", "D4", "D5")
TRACK_NAMES = {
    "D1": "lost_knowledge",
    "D2": "concept_drift",
    "D3": "formula_evolution",
    "D4": "hidden_association",
    "D5": "contradiction",
}
ALL_GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


@dataclass(kw_only=True)
class CorpusScope(Model):
    books: list[str] = field_list()
    exclude_books: list[str] = field_list()
    categories: list[str] = field_list()
    tags: list[str] = field_list()


@dataclass(kw_only=True)
class StopConfig(Model):
    max_rounds: int = 2
    evidence_saturation: float = 0.05
    min_novel_source_gain: int = 1
    stop_on_validation: bool = True
    require_contradictions_addressed: bool = False
    expert_intervention_on_critical: bool = True


@dataclass(kw_only=True)
class RequiredEvidence(Model):
    min_independent_sources: int = 2
    min_supporting_evidence: int = 2
    require_verbatim_quotes: bool = True


@dataclass(kw_only=True)
class GoalSpec(Model):
    """The research contract. Immutable once the session is created."""

    question: str
    focus_terms: list[str] = field_list()
    tracks: list[str] = field(default_factory=lambda: list(ALL_TRACKS))
    success_criteria: list[str] = field_list()
    acceptance_criteria: list[str] = field_list()
    corpus: CorpusScope = field(default_factory=CorpusScope)
    temporal_scope: YearRange | None = None
    holdout_after: int | None = None
    time_basis: str = "composition"
    forbidden_assumptions: list[str] = field_list()
    required_evidence: RequiredEvidence = field(default_factory=RequiredEvidence)
    required_validation: list[str] = field(default_factory=lambda: ["G0", "G1", "G2", "G3", "G4", "G5", "G6"])
    stop: StopConfig = field(default_factory=StopConfig)
    profile: str = "full-discovery"
    language: str = "zh"

    def digest(self) -> str:
        return content_hash(self)


@dataclass(kw_only=True)
class TaskNode(Model):
    id: str
    kind: str
    role: str
    round: int = 0
    inputs: dict = field_dict()
    depends_on: list[str] = field_list()
    status: str = "pending"  # pending | running | done | failed | skipped
    summary: str = ""
    outputs: list[str] = field_list()
    priority: int = 100


@dataclass(kw_only=True)
class AgentInstance(Model):
    id: str
    role: str
    name: str
    task_id: str | None = None
    model: str | None = None
    provider: str | None = None
    status: str = "active"
    parent: str | None = None
    usage: dict = field_dict()


@dataclass(kw_only=True)
class CorpusManifest(Model):
    book_ids: list[str]
    passage_ids: list[str]
    excluded: dict[str, str] = field_dict()
    coverage: dict[str, int] = field_dict()
    holdout_passage_ids: list[str] = field_list()
    time_basis: str = "composition"
    warnings: list[str] = field_list()


@dataclass(kw_only=True)
class LineageEdge(Model):
    """Knowledge lineage: cites / transcribes / rephrases / modifies / opposes / derives."""

    id: str
    relation: str
    source_id: str  # the later / derived item
    target_id: str  # the earlier / original item
    source_kind: str  # passage | book | formula | concept | external
    target_kind: str
    detector: str
    confidence: float = 0.5
    direction_certain: bool = True
    source_passage: str | None = None
    target_passage: str | None = None
    evidence: dict = field_dict()
    note: str = ""


@dataclass(kw_only=True)
class Contradiction(Model):
    id: str
    claim_a: str
    claim_b: str
    subject: str
    axis: str
    label: str  # benchmark label: contradiction | conditional | apparent | support | unrelated
    type: str  # direct | theoretical | conditional | apparent_homonym | philological | definitional_drift
    explanation: str
    candidate_explanations: list[str] = field_list()
    evidence: dict = field_dict()
    resolved: bool = False
    confidence: float = 0.5


@dataclass(kw_only=True)
class GateResult(Model):
    gate: str
    subject_id: str
    status: str  # pass | warn | fail | pending | not_applicable
    score: float | None = None
    details: str = ""


@dataclass(kw_only=True)
class ProposedChange(Model):
    """Agents may only *propose* changes to canonical knowledge; validators or humans commit."""

    id: str
    target: str  # terminology | ontology | canonical_kg | gold | memory.domain | memory.skill
    op: str  # add | update | delete
    payload: dict
    rationale: str
    proposer: str
    status: str = "proposed"
    decided_by: str | None = None
    evidence_ids: list[str] = field_list()
    note: str = ""


@dataclass(kw_only=True)
class Decision(Model):
    id: str
    kind: str
    summary: str
    rationale: str
    made_by: str
    refs: list[str] = field_list()


@dataclass(kw_only=True)
class BranchInfo(Model):
    id: str
    parent_session: str
    at_seq: int
    purpose: str
    hypothesis_id: str | None = None
    status: str = "open"
    outcome: dict = field_dict()


# Fields that make up the *scientific* state.  Operational telemetry (agent
# instances, counters, attempt numbers) is excluded so that a crashed-and-resumed
# run hashes identically to an uninterrupted one.
SCIENTIFIC_FIELDS = (
    "goal",
    "goal_digest",
    "status",
    "round",
    "corpus",
    "task_graph",
    "philology",
    "term_resolutions",
    "claims",
    "rejected_claims",
    "evidence",
    "lineage",
    "contradictions",
    "observations",
    "analyses",
    "hypotheses",
    "reviews",
    "gates",
    "changes",
    "decisions",
    "expert_actions",
    "branches",
    "artifacts",
    "rounds",
    "stop",
)


@dataclass(kw_only=True)
class ResearchObject(Model):
    session_id: str
    goal: GoalSpec | None = None
    goal_digest: str | None = None
    profile: str | None = None
    status: str = "empty"
    round: int = 0
    corpus: CorpusManifest | None = None
    task_graph: dict[str, TaskNode] = field_dict()
    agents: dict[str, AgentInstance] = field_dict()
    philology: dict[str, PhilologyAssessment] = field_dict()
    term_resolutions: dict[str, TermResolution] = field_dict()
    claims: dict[str, Claim] = field_dict()
    rejected_claims: dict[str, dict] = field_dict()
    evidence: dict[str, EvidenceRecord] = field_dict()
    lineage: dict[str, LineageEdge] = field_dict()
    contradictions: dict[str, Contradiction] = field_dict()
    observations: dict[str, Observation] = field_dict()
    analyses: dict[str, dict] = field_dict()
    hypotheses: dict[str, Hypothesis] = field_dict()
    reviews: dict[str, HypothesisReview] = field_dict()
    gates: dict[str, dict[str, GateResult]] = field_dict()
    changes: dict[str, ProposedChange] = field_dict()
    decisions: dict[str, Decision] = field_dict()
    expert_actions: dict[str, dict] = field_dict()
    branches: dict[str, BranchInfo] = field_dict()
    artifacts: dict[str, Artifact] = field_dict()
    rounds: dict[str, dict] = field_dict()
    stop: dict | None = None
    metrics: dict = field_dict()

    def scientific_state(self) -> dict:
        data = self.to_dict()
        state = {k: data[k] for k in SCIENTIFIC_FIELDS}
        for task in state["task_graph"].values():
            if task.get("status") == "running":  # an interrupted attempt is not scientific state
                task["status"] = "pending"
        return state

    def state_hash(self) -> str:
        return content_hash(self.scientific_state())

    # --- convenience queries used by agents and reports -------------------
    def reviews_for(self, hypothesis_id: str) -> list[HypothesisReview]:
        return [r for r in self.reviews.values() if r.hypothesis_id == hypothesis_id]

    def active_hypotheses(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses.values() if h.status not in ("rejected", "superseded", "expert_rejected")]

    def gate_status(self, subject_id: str, gate: str) -> str:
        result = self.gates.get(subject_id, {}).get(gate)
        return "pending" if result is None else result.status
