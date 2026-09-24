"""Verification layer: provenance checks, epistemic gates and built-in guard hooks."""

from .gates import GATE_NAMES, GateEvaluator, contradicting, worst
from .hooks import anachronism_guard, install_default_hooks, provenance_validator, publish_guard
from .provenance import find_quote, provenance_chain, verify_claim, verify_evidence

__all__ = [
    "GATE_NAMES",
    "GateEvaluator",
    "anachronism_guard",
    "contradicting",
    "find_quote",
    "install_default_hooks",
    "provenance_chain",
    "provenance_validator",
    "publish_guard",
    "verify_claim",
    "verify_evidence",
    "worst",
]
