"""TaoChronos research protocol: typed, serialisable objects shared by every layer.

The protocol layer depends on nothing else in the package (see
``architecture-policy.yaml``).
"""

from .artifacts import ARTIFACT_KINDS, Artifact
from .base import Model, canonical_json, content_hash, from_dict, sha256_hex, stable_id, to_jsonable
from .claims import (
    CONDITION_ROLES,
    FINDING_ROLES,
    INTERVENTION_ROLES,
    Claim,
    ClaimArgument,
    ClaimRelation,
    ExtractionInfo,
    Role,
)
from .concepts import (
    MODERN_EVIDENCE_DOMAINS,
    ConceptMapping,
    EvidenceDomain,
    HistoricalTerm,
    KnowledgeSpace,
    MappingRelation,
    Sense,
    StandardConcept,
    Synonym,
    SynonymKind,
)
from .confidence import DIMENSIONS, ConfidenceVector, level
from .documents import (
    BBox,
    Book,
    CollationStatus,
    Edition,
    Locator,
    Passage,
    SourceInfo,
    TemporalContext,
    VariantKind,
    VariantReading,
    YearRange,
)
from .events import OPERATIONAL_EVENTS, Event, EventType
from .evidence import EvidenceRecord, Stance
from .hypothesis import (
    DEFAULT_SCORE_WEIGHTS,
    SCORE_DIMENSIONS,
    Hypothesis,
    HypothesisReview,
    Objection,
    Observation,
    Prediction,
    ScoreCard,
)
from .outputs import ContestedSpan, DiscoveryReport, PhilologyAssessment, ReadingOption, ReportSection, TermResolution
from .research import (
    ALL_GATES,
    ALL_TRACKS,
    SCIENTIFIC_FIELDS,
    TRACK_NAMES,
    AgentInstance,
    BranchInfo,
    Contradiction,
    CorpusManifest,
    CorpusScope,
    Decision,
    GateResult,
    GoalSpec,
    LineageEdge,
    ProposedChange,
    RequiredEvidence,
    ResearchObject,
    StopConfig,
    TaskNode,
)

PROTOCOL_TYPES = [
    Book,
    Edition,
    Passage,
    Locator,
    VariantReading,
    TemporalContext,
    HistoricalTerm,
    Sense,
    StandardConcept,
    ConceptMapping,
    Claim,
    ClaimArgument,
    EvidenceRecord,
    ConfidenceVector,
    Observation,
    Hypothesis,
    HypothesisReview,
    Objection,
    ScoreCard,
    GoalSpec,
    TaskNode,
    LineageEdge,
    Contradiction,
    GateResult,
    ProposedChange,
    Decision,
    PhilologyAssessment,
    TermResolution,
    DiscoveryReport,
    Artifact,
    ResearchObject,
    Event,
]

__all__ = [name for name in dir() if not name.startswith("_")]
