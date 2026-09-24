"""Observations, hypotheses and their adversarial reviews."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .base import Model, field_dict, field_list
from .concepts import KnowledgeSpace
from .confidence import ConfidenceVector
from .documents import YearRange


@dataclass(kw_only=True)
class Observation(Model):
    """A pattern found by a (non-LLM) mining algorithm. Observations trigger hypotheses."""

    id: str
    kind: str  # lost_knowledge | concept_drift | formula_evolution | hidden_association | community | contradiction | lineage
    title: str
    summary: str
    detector: str
    data: dict = field_dict()
    statistics: dict = field_dict()
    claim_ids: list[str] = field_list()
    passage_ids: list[str] = field_list()
    terms: list[str] = field_list()
    score: float = 0.0


@dataclass(kw_only=True)
class Prediction(Model):
    """A structured, checkable consequence of a hypothesis (used by falsification and time-machine evals)."""

    kind: str  # cooccurrence_after | absent_before | link_appears | herb_retained | sense_shift
    subject: str
    description: str
    object: str | None = None
    period: YearRange | None = None


@dataclass(kw_only=True)
class Objection(Model):
    id: str
    check: str  # earlier_source | counterexample | edition_variant | homonym | transcription_dependence | …
    severity: str  # critical | major | minor | info
    detail: str
    evidence_ids: list[str] = field_list()
    passage_ids: list[str] = field_list()
    resolved: bool = False
    resolution: str = ""


SCORE_DIMENSIONS = (
    "textual_support",
    "cross_source_replication",
    "philological_robustness",
    "temporal_coherence",
    "novelty",
    "explanatory_power",
    "counterevidence_robustness",
    "testability",
    "anachronism_risk",  # lower is better
)

DEFAULT_SCORE_WEIGHTS = {
    "textual_support": 0.16,
    "cross_source_replication": 0.14,
    "philological_robustness": 0.12,
    "temporal_coherence": 0.10,
    "novelty": 0.12,
    "explanatory_power": 0.10,
    "counterevidence_robustness": 0.12,
    "testability": 0.08,
    "anachronism_risk": 0.06,
}


@dataclass(kw_only=True)
class ScoreCard(Model):
    textual_support: float = 0.0
    cross_source_replication: float = 0.0
    philological_robustness: float = 0.0
    temporal_coherence: float = 0.0
    novelty: float = 0.0
    explanatory_power: float = 0.0
    counterevidence_robustness: float = 0.0
    testability: float = 0.0
    anachronism_risk: float = 0.0

    def weighted(self, weights: dict[str, float] | None = None) -> float:
        weights = weights or DEFAULT_SCORE_WEIGHTS
        total = 0.0
        for f in fields(self):
            value = getattr(self, f.name)
            w = weights.get(f.name, 0.0)
            total += w * ((1.0 - value) if f.name == "anachronism_risk" else value)
        return round(total, 4)


@dataclass(kw_only=True)
class HypothesisReview(Model):
    id: str
    hypothesis_id: str
    reviewer: str
    verdict: str  # survives | revise | reject
    objections: list[Objection] = field_list()
    summary: str = ""
    round: int = 0
    checks_run: list[str] = field_list()

    def unresolved(self, *severities: str) -> list[Objection]:
        return [o for o in self.objections if not o.resolved and (not severities or o.severity in severities)]


@dataclass(kw_only=True)
class Hypothesis(Model):
    id: str
    statement: str
    kind: str
    observation_ids: list[str] = field_list()
    terms: list[str] = field_list()
    supporting_evidence: list[str] = field_list()
    contradictory_evidence: list[str] = field_list()
    earliest_evidence: str | None = None
    replication_sources: list[str] = field_list()
    novelty: float = 0.0
    novelty_rationale: str = ""
    alternative_explanations: list[str] = field_list()
    philological_risk: str = "unknown"
    philological_risk_note: str = ""
    anachronism_risk: str = "unknown"
    anachronism_risk_note: str = ""
    testable_prediction: str = ""
    predictions: list[Prediction] = field_list()
    confidence: ConfidenceVector = field(default_factory=ConfidenceVector)
    scores: ScoreCard | None = None
    discovery_score: float | None = None
    discovery_components: dict = field_dict()
    elo: float = 1200.0
    status: str = "proposed"
    generation: int = 0
    parent_id: str | None = None
    revision_note: str = ""
    branch: str | None = None
    space: KnowledgeSpace = KnowledgeSpace.COMPUTATIONAL_HYPOTHESIS
    generated_by: str = ""
    round: int = 0
