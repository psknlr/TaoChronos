"""Evidence Ledger records: every quote the system relies on, with its full lineage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .base import Model, field_list
from .concepts import EvidenceDomain
from .confidence import ConfidenceVector
from .documents import Locator, TemporalContext


class Stance(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    CONTEXT = "context"


@dataclass(kw_only=True)
class EvidenceRecord(Model):
    """One verbatim, locatable piece of evidence.

    Timestamps live on the event that recorded the evidence (the ledger view
    joins them), which keeps research state hashes deterministic.
    """

    id: str
    passage_id: str
    book_id: str
    locator: Locator
    quote: str
    start: int
    end: int
    agent: str
    retrieval_method: str
    edition_id: str | None = None
    claim_id: str | None = None
    hypothesis_id: str | None = None
    stance: Stance = Stance.NEUTRAL
    retrieval_score: float | None = None
    routes: list[str] = field_list()
    query: str | None = None
    extraction_model: str | None = None
    transformation_history: list[str] = field_list()
    evidence_domain: EvidenceDomain = EvidenceDomain.HISTORICAL_TEXT
    temporal: TemporalContext | None = None
    confidence: ConfidenceVector = field(default_factory=ConfidenceVector)
    note: str = ""
