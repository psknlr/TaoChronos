"""Confidence is a vector, never a single probability.

Scholars need to see *where* a conclusion is strong (the text clearly says it)
and where it is weak (the modern interpretation is unknown).
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .base import Model

DIMENSIONS = (
    "textual",
    "philological",
    "semantic",
    "extraction",
    "cross_source",
    "temporal",
    "statistical",
    "modern_mapping",
)


def level(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.75:
        return "high"
    if value >= 0.45:
        return "medium"
    return "low"


def _known(*values: float | None) -> list[float]:
    return [v for v in values if v is not None]


@dataclass(kw_only=True)
class ConfidenceVector(Model):
    textual: float | None = None  # how directly the text states it
    philological: float | None = None  # collation / variants / OCR / edition quality
    semantic: float | None = None  # sense resolution of the terms involved
    extraction: float | None = None  # reliability of the extractor that produced it
    cross_source: float | None = None  # independent replication
    temporal: float | None = None  # dating and ordering consistency
    statistical: float | None = None  # significance of a mined pattern
    modern_mapping: float | None = None  # None = modern validity unknown (the default!)
    contradiction_penalty: float = 0.0

    def as_dict(self) -> dict[str, float | None]:
        return {name: getattr(self, name) for name in DIMENSIONS}

    def combine(self, other: "ConfidenceVector", how: str = "min") -> "ConfidenceVector":
        merged: dict[str, float | None] = {}
        for name in DIMENSIONS:
            a, b = getattr(self, name), getattr(other, name)
            if a is None or b is None:
                merged[name] = a if b is None else b
            elif how == "min":
                merged[name] = min(a, b)
            elif how == "max":
                merged[name] = max(a, b)
            else:
                merged[name] = (a + b) / 2
        return ConfidenceVector(
            **merged, contradiction_penalty=max(self.contradiction_penalty, other.contradiction_penalty)
        )

    @staticmethod
    def mean(vectors: list["ConfidenceVector"]) -> "ConfidenceVector":
        if not vectors:
            return ConfidenceVector()
        merged: dict[str, float | None] = {}
        for name in DIMENSIONS:
            values = _known(*(getattr(v, name) for v in vectors))
            merged[name] = round(sum(values) / len(values), 4) if values else None
        penalty = max(v.contradiction_penalty for v in vectors)
        return ConfidenceVector(**merged, contradiction_penalty=penalty)

    def scholar_view(self) -> dict[str, str]:
        """The five-line summary shown to historians (see design §19)."""

        def mean(*values: float | None) -> float | None:
            known = _known(*values)
            return sum(known) / len(known) if known else None

        text = _known(self.textual, self.philological)
        return {
            "Text confidence": level(min(text) if text else None),
            "Semantic confidence": level(mean(self.semantic, self.extraction)),
            "Historical attribution": level(self.temporal),
            "Medical interpretation": level(mean(self.semantic, self.cross_source)),
            "Modern biomedical validity": level(self.modern_mapping),
        }

    def ranking_score(self) -> float:
        """A scalar *only* for sorting; reports always show the full vector."""
        known = _known(*(getattr(self, name) for name in DIMENSIONS if name != "modern_mapping"))
        if not known:
            return 0.0
        return max(0.0, sum(known) / len(known) - self.contradiction_penalty)

    def rounded(self, digits: int = 3) -> "ConfidenceVector":
        values = {}
        for f in fields(self):
            v = getattr(self, f.name)
            values[f.name] = None if v is None else round(v, digits)
        return ConfidenceVector(**values)
