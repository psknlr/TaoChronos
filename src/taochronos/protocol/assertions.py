"""Evidence Graph and Evidence Audit: who asserts each link, in which layer it lives, and what an audit concludes.

Every edge of the evidence graph says *who* asserts it — the source text, a scholar (a commentator, a curator of this
project), a model that extracted or inferred it, modern evidence, or nobody yet (a hypothesis) — because a reader must be
able to tell 「《金匮》言消渴小便反多」 (the source says so) from 「消渴与糖尿病表型相似」 (the system infers so) at a
glance.  The graph has six layers, from the witness to the modern evidence; an audit reads a claim against them and
gives one of five verdicts.
"""

from __future__ import annotations

from enum import Enum


class AssertionType(str, Enum):
    SOURCE_ASSERTED = "SOURCE_ASSERTED"  # the text says it (a verbatim, located quote)
    SCHOLAR_INTERPRETED = "SCHOLAR_INTERPRETED"  # a commentator's gloss, a curated sense or mapping of this project
    MODEL_EXTRACTED = "MODEL_EXTRACTED"  # read from the text by rules or a model (a finding, an entity)
    MODEL_INFERRED = "MODEL_INFERRED"  # inferred beyond the text (a sense selected, a resemblance scored)
    MODERN_EVIDENCE_SUPPORTED = "MODERN_EVIDENCE_SUPPORTED"  # a modern study, review or guideline bears on it
    HYPOTHESIS = "HYPOTHESIS"  # proposed, not yet supported


class GraphLayer(str, Enum):
    SOURCE = "source"  # works, editions, passages, quotes
    HISTORICAL = "historical"  # what the texts state: findings, formulas, claims, names as used
    TCM_SEMANTIC = "tcm_semantic"  # concepts of TCM: phenotypes, senses, patterns
    MAPPING = "mapping"  # typed links between ancient and modern concepts
    MODERN = "modern"  # HPO terms, diseases (ICD-10), drugs, compounds
    EVIDENCE = "evidence"  # modern studies, audits, hypotheses


class AuditVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTESTED = "CONTESTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED = "UNSUPPORTED"


class ClaimKind(str, Enum):
    """What an atomic claim asserts — each kind is checked differently."""

    HISTORICAL = "historical"  # a text says X (checked against the witness)
    INTERPRETIVE = "interpretive"  # X means Y (needs a gloss or a curated sense)
    MAPPING = "mapping"  # an ancient concept resembles / corresponds to a modern one (needs a typed relation)
    MODERN = "modern"  # a modern finding (needs modern evidence of the right level)
    INFERENCE = "inference"  # therefore … (a step from one space to another)
    CLINICAL = "clinical"  # advice on treating people (never given)


__all__ = ["AssertionType", "AuditVerdict", "ClaimKind", "GraphLayer"]
