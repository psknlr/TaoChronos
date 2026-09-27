"""Ancient–Modern Bridge: how an ancient finding or description relates to a modern phenotype or disease.

A *relation* says how far two concepts overlap (the written form 渴欲饮水 and the HPO term Polydipsia are CLOSE; 消渴 and
diabetes mellitus are at most PHENOTYPIC_SIMILARITY, and a HISTORICAL_SEMANTIC_SHIFT where the name itself moved).  A
*strength* says how well an ancient description's findings fit a modern disease profile.  Neither is a probability: a
strength is a rule over matched findings and stays uncalibrated until a gold standard of historical descriptions with
known modern diagnoses exists — which, for most of history, it cannot.
"""

from __future__ import annotations

from enum import Enum


class BridgeRelation(str, Enum):
    EXACT = "EXACT"
    CLOSE = "CLOSE"
    BROADER = "BROADER"  # the ancient concept is wider than the modern one
    NARROWER = "NARROWER"
    PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
    PHENOTYPIC_SIMILARITY = "PHENOTYPIC_SIMILARITY"  # the findings resemble; the concepts are not claimed to overlap
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    HISTORICAL_SEMANTIC_SHIFT = "HISTORICAL_SEMANTIC_SHIFT"
    NO_MODERN_EQUIVALENT = "NO_MODERN_EQUIVALENT"
    UNCERTAIN = "UNCERTAIN"


# how much a finding projected with a relation counts as the modern phenotype it names
RELATION_WEIGHT: dict[BridgeRelation, float] = {
    BridgeRelation.EXACT: 1.0,
    BridgeRelation.CLOSE: 0.9,
    BridgeRelation.NARROWER: 0.85,
    BridgeRelation.BROADER: 0.6,
    BridgeRelation.PARTIAL_OVERLAP: 0.6,
    BridgeRelation.PHENOTYPIC_SIMILARITY: 0.5,
    BridgeRelation.CONTEXT_DEPENDENT: 0.45,
    BridgeRelation.HISTORICAL_SEMANTIC_SHIFT: 0.35,
    BridgeRelation.UNCERTAIN: 0.25,
    BridgeRelation.NO_MODERN_EQUIVALENT: 0.0,
}


class Strength(str, Enum):
    """The qualitative strength of a description's fit to a disease profile (not a probability)."""

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    INSUFFICIENT = "insufficient"


STRENGTH_ORDER = [Strength.INSUFFICIENT, Strength.LOW, Strength.MODERATE, Strength.HIGH]


def weaker(a: Strength, b: Strength) -> Strength:
    return a if STRENGTH_ORDER.index(a) <= STRENGTH_ORDER.index(b) else b


def step_down(s: Strength) -> Strength:
    return STRENGTH_ORDER[max(0, STRENGTH_ORDER.index(s) - 1)]


__all__ = ["BridgeRelation", "RELATION_WEIGHT", "STRENGTH_ORDER", "Strength", "step_down", "weaker"]
