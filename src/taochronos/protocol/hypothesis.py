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


# Objections a validator can re-run mechanically.  They close only when the re-run passes — never on a model's say-so,
# and not by an expert either: a quote that is not in the text does not become one by agreement.
HARD_CHECKS = frozenset({
    "provenance",  # a quote is not verbatim at its locator
    "semantic_support",  # the quoted words do not bear the stated relation
    "anachronism",  # the statement equates a historical concept with a modern category / breaks the contract
    "scope",  # evidence from outside the research scope (hold-out, confirmation-only, expert-only material)
    "version_mismatch",  # the evidence's edition is not the one the claim names
    "data_scope",  # a data-use restriction (licence, withheld material) is violated
    "object_signature",  # an object's id does not match its content
    "contraindication",  # the corpus states the opposite (a contraindication for the claimed indication)
    "taxonomy",  # the association is already implied by the term hierarchy
    "differential",  # the same passage assigns the finding to a rival
})
OBJECTION_STATUSES = ("raised", "resolution_proposed", "closed", "noted")
# the qualifier a revision adds to narrow its claim along an interpretive objection's axis
NARROWING_AXIS = {
    "sample_size": "scope", "single_source": "scope", "homonym": "sense", "edition_variant": "reading",
    "statistical": "status", "transcription_dependence": "tradition", "earliest_source": "level", "counterexample": "level",
    "partial_persistence": "level", "hub_driven": "status",
}
CLOSURE_METHODS = ("validator_rerun", "new_evidence", "scope_restriction", "expert")


def objection_kind(check: str) -> str:
    return "hard" if check in HARD_CHECKS else "interpretive"


@dataclass(kw_only=True)
class Objection(Model):
    """One objection and where it stands: raised → resolution_proposed → closed (info-level notes are "noted").

    Who may move it: an agent raises it and may propose a resolution (a qualifier that narrows the claim, new evidence,
    or a rationale); a validator closes it by re-running the check (hard objections: only that way) or by verifying the
    new evidence or the narrowing; an expert may close an interpretive one.  ``resolved`` is true only once closed."""

    id: str
    check: str  # earlier_source | counterexample | edition_variant | homonym | transcription_dependence | …
    severity: str  # critical | major | minor | info
    detail: str
    evidence_ids: list[str] = field_list()
    passage_ids: list[str] = field_list()
    resolved: bool = False
    resolution: str = ""
    kind: str = ""  # hard | interpretive (empty: by the check)
    status: str = "raised"
    proposal: dict = field_dict()  # {basis: qualifier|new_evidence|rationale, rationale, evidence_ids, qualifier, proposed_by}
    closed_by: str = ""
    closure: str = ""  # validator_rerun | new_evidence | scope_restriction | expert

    @property
    def hard(self) -> bool:
        return (self.kind or objection_kind(self.check)) == "hard"

    @property
    def is_open(self) -> bool:
        return not self.resolved and self.status != "noted"


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
        return [o for o in self.objections if o.is_open and (not severities or o.severity in severities)]

    def objection(self, objection_id: str) -> Objection | None:
        return next((o for o in self.objections if o.id == objection_id), None)


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
    # scope qualifiers added by revision, e.g. {"scope": "surveyed_corpus", "sense": "消渴#病·三消", "reading": "base"}
    qualifiers: dict = field_dict()
    branch: str | None = None
    space: KnowledgeSpace = KnowledgeSpace.COMPUTATIONAL_HYPOTHESIS
    generated_by: str = ""
    round: int = 0
    # a revision says what kind it is: "restricting" (narrows scope, sense, reading or level — the evidence that bore
    # the parent still bears it) or "substantive" (a different claim: a new hypothesis that must earn its own support)
    revision_kind: str = ""
    changed_fields: list[str] = field_list()
    invalidated: list[str] = field_list()  # validations of the parent that do not carry over (gates, reviews)
    confirmation: dict = field_dict()  # the re-test of its predictions on material withheld from exploration
    warrant_id: str | None = None
    # the statistics of its observations as a record (method, null hypothesis, effect and interval, n, source families,
    # correction, sensitivity) — never folded into a "confidence" such as 1 − p
    statistics: dict = field_dict()
    novelty_profile: dict = field_dict()  # novelty by scope: curated known findings, the corpus, literature (unassessed)

    def version(self) -> str:
        """The content a validation is bound to: a gate or review computed on an earlier version does not count."""
        from .base import content_hash

        return content_hash({
            "statement": self.statement, "kind": self.kind, "terms": self.terms, "qualifiers": self.qualifiers,
            "supporting": sorted(self.supporting_evidence), "contradictory": sorted(self.contradictory_evidence),
            "space": self.space.value,
        })[:16]
