"""Modern evidence (S13) and real-world data (S14): the kinds of evidence, how strongly each can bear on a claim, and the
structured study specification a question about real-world data is turned into.

The evidence hierarchy is the usual one of evidence-based medicine, with the population a study was done in kept apart
from its design: an RCT in mice is animal evidence, however well randomised.  The cross-level guard refuses the steps the
literature on TCM keeps taking — an animal or cell study read as efficacy in people, a network-pharmacology prediction
read as efficacy at all.

A ``StudySpec`` is what a model may write about a real-world-data question (it never writes SQL): exposures and outcomes
as concept sets, the population, the design and the time windows.  The compiler turns a validated spec into a fixed,
parameterised query over the OMOP common data model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .base import Model, field_list


class EvidenceType(str, Enum):
    SYSTEMATIC_REVIEW = "systematic_review"  # systematic review or meta-analysis
    GUIDELINE = "guideline"
    RCT = "rct"
    COHORT = "cohort"
    CASE_CONTROL = "case_control"
    CROSS_SECTIONAL = "cross_sectional"
    CASE_SERIES = "case_series"
    CASE_REPORT = "case_report"
    NARRATIVE_REVIEW = "narrative_review"
    ANIMAL = "animal"
    IN_VITRO = "in_vitro"
    IN_SILICO = "in_silico"  # network pharmacology, docking, predictions
    EXPERT_OPINION = "expert_opinion"
    UNKNOWN = "unknown"


class Population(str, Enum):
    HUMAN = "human"
    ANIMAL = "animal"
    IN_VITRO = "in_vitro"
    IN_SILICO = "in_silico"
    UNKNOWN = "unknown"


# rank of a design for a claim about people (1 strongest); animal, cell and computational work cannot rank here at all
EVIDENCE_RANK: dict[EvidenceType, int] = {
    EvidenceType.SYSTEMATIC_REVIEW: 1, EvidenceType.GUIDELINE: 1, EvidenceType.RCT: 2, EvidenceType.COHORT: 3,
    EvidenceType.CASE_CONTROL: 4, EvidenceType.CROSS_SECTIONAL: 5, EvidenceType.CASE_SERIES: 6, EvidenceType.CASE_REPORT: 7,
    EvidenceType.NARRATIVE_REVIEW: 8, EvidenceType.EXPERT_OPINION: 9,
}


class ClaimLevel(str, Enum):
    """What a modern claim asserts, from the strongest to the weakest."""

    HUMAN_EFFICACY = "human_efficacy"  # it works in patients (effective, improves, reduces …)
    HUMAN_ASSOCIATION = "human_association"  # it is associated with … in people
    MECHANISM = "mechanism"  # it acts on a target, a pathway (in cells or animals)
    PREDICTION = "prediction"  # it may act on … (computed)
    SAFETY = "safety"  # it is toxic, interacts …


# which evidence types can support a claim of each level
SUPPORTS: dict[ClaimLevel, set[EvidenceType]] = {
    ClaimLevel.HUMAN_EFFICACY: {EvidenceType.SYSTEMATIC_REVIEW, EvidenceType.GUIDELINE, EvidenceType.RCT},
    ClaimLevel.HUMAN_ASSOCIATION: {EvidenceType.SYSTEMATIC_REVIEW, EvidenceType.GUIDELINE, EvidenceType.RCT, EvidenceType.COHORT,
                                   EvidenceType.CASE_CONTROL, EvidenceType.CROSS_SECTIONAL},
    ClaimLevel.MECHANISM: {EvidenceType.ANIMAL, EvidenceType.IN_VITRO, EvidenceType.RCT, EvidenceType.SYSTEMATIC_REVIEW},
    ClaimLevel.PREDICTION: {EvidenceType.IN_SILICO, EvidenceType.ANIMAL, EvidenceType.IN_VITRO},
    ClaimLevel.SAFETY: {EvidenceType.SYSTEMATIC_REVIEW, EvidenceType.GUIDELINE, EvidenceType.RCT, EvidenceType.COHORT,
                        EvidenceType.CASE_CONTROL, EvidenceType.CASE_SERIES, EvidenceType.CASE_REPORT, EvidenceType.ANIMAL,
                        EvidenceType.IN_VITRO},
}


def cross_level(claim: ClaimLevel, evidence: EvidenceType) -> str | None:
    """Why ``evidence`` cannot carry ``claim`` (None when it can)."""
    if evidence in SUPPORTS[claim]:
        return None
    if evidence in (EvidenceType.ANIMAL, EvidenceType.IN_VITRO) and claim in (ClaimLevel.HUMAN_EFFICACY, ClaimLevel.HUMAN_ASSOCIATION):
        return "animal or cell evidence read as a finding in people"
    if evidence == EvidenceType.IN_SILICO:
        return "a computational prediction read as an effect"
    if evidence in (EvidenceType.NARRATIVE_REVIEW, EvidenceType.EXPERT_OPINION, EvidenceType.CASE_REPORT, EvidenceType.CASE_SERIES):
        return "a review, opinion or case read as proof of efficacy"
    return f"{evidence.value} evidence cannot carry a {claim.value} claim"


@dataclass(kw_only=True)
class ModernRecord(Model):
    """One piece of modern literature, typed."""

    id: str
    title: str
    source: str  # pubmed | curated | …
    year: int | None = None
    journal: str = ""
    pmid: str | None = None
    doi: str | None = None
    publication_types: list[str] = field_list()
    evidence_type: EvidenceType = EvidenceType.UNKNOWN
    population: Population = Population.UNKNOWN
    typing_rule: str = ""
    abstract: str = ""
    url: str = ""
    retracted: bool = False


# ------------------------------------------------------------------ S14: the structured study specification
STUDY_DESIGNS = ("cohort", "descriptive", "case_control")

STUDY_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["question", "design", "outcome", "population", "time"],
    "properties": {
        "question": {"type": "string"},
        "design": {"enum": list(STUDY_DESIGNS)},
        "exposure": {"type": "object", "required": ["name", "concepts"], "properties": {
            "name": {"type": "string"}, "concepts": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
            "domain": {"enum": ["drug", "condition", "observation"]}}},
        "comparator": {"type": "object", "properties": {"name": {"type": "string"},
                                                        "concepts": {"type": "array", "items": {"type": "integer"}}}},
        "outcome": {"type": "object", "required": ["name", "concepts"], "properties": {
            "name": {"type": "string"}, "concepts": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
            "domain": {"enum": ["condition", "observation", "measurement"]}}},
        "population": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string"}, "concepts": {"type": "array", "items": {"type": "integer"}},
            "age_min": {"type": "integer"}, "age_max": {"type": "integer"}, "sex": {"enum": ["any", "female", "male"]}}},
        "time": {"type": "object", "required": ["washout_days", "followup_days"], "properties": {
            "washout_days": {"type": "integer"}, "followup_days": {"type": "integer"}}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


__all__ = ["ClaimLevel", "EVIDENCE_RANK", "EvidenceType", "ModernRecord", "Population", "STUDY_DESIGNS", "STUDY_SPEC_SCHEMA",
           "SUPPORTS", "cross_level"]
