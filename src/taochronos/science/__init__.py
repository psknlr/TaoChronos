"""Scientific engine: tool-first, non-LLM discovery algorithms (D1–D5), statistics and scoring.

Depends only on the protocol layer; plugins adapt their data into these functions.
"""

from .association import CooccurrenceGraph, association_rules, communities, link_prediction
from .concept_drift import concept_drift
from .contradiction import ContradictionContext, classify, classify_passages, find_contradictions
from .formula_evolution import formula_families
from .lost_knowledge import association_units, lost_knowledge
from .scoring import DEFAULT_DISCOVERY_WEIGHTS, discovery_score, elo_tournament, novelty
from .sources import infer_missing_sources
from .stats import (
    benjamini_hochberg,
    bootstrap_ci,
    context_jsd,
    entropy,
    fisher_exact_greater,
    jaccard,
    jensen_shannon,
    permutation_test,
    wilson_interval,
)
from .temporal import PeriodBinner, coverage, series

__all__ = [name for name in dir() if not name.startswith("_")]
