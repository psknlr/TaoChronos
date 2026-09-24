"""Typed outputs of specialist agents (the ``output_schema`` referenced by AgentSpecs)."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Model, field_dict, field_list


@dataclass(kw_only=True)
class ReadingOption(Model):
    reading: str
    probability: float
    witness: str
    kind: str
    note: str = ""


@dataclass(kw_only=True)
class ContestedSpan(Model):
    """A span whose reading is uncertain. The philologist never forces a single answer."""

    start: int
    end: int
    base: str
    options: list[ReadingOption]
    uncertain: float
    rationale: str = ""

    def base_probability(self) -> float:
        for option in self.options:
            if option.reading == self.base:
                return option.probability
        return 0.0


@dataclass(kw_only=True)
class PhilologyAssessment(Model):
    passage_id: str
    normalized_text: str
    normalizations: list[dict] = field_list()  # {start, end, from, to, kind}
    contested: list[ContestedSpan] = field_list()
    ocr_confidence: float | None = None
    collation_status: str = "unverified"
    edition_quality: float = 0.5
    philological_confidence: float = 0.5
    notes: list[str] = field_list()

    def contested_at(self, start: int, end: int) -> list[ContestedSpan]:
        return [c for c in self.contested if c.start < end and start < c.end]


@dataclass(kw_only=True)
class TermResolution(Model):
    id: str
    term_id: str
    surface: str
    passage_id: str
    start: int
    end: int
    sense_id: str | None
    probability: float
    alternatives: dict[str, float] = field_dict()
    homonym_risk: bool = False
    rationale: str = ""


@dataclass(kw_only=True)
class ReportSection(Model):
    title: str
    body: str
    refs: list[str] = field_list()


@dataclass(kw_only=True)
class DiscoveryReport(Model):
    title: str
    question: str
    sections: list[ReportSection]
    ranked_hypotheses: list[str] = field_list()
    recommended_verification: list[str] = field_list()
    evidence_refs: list[str] = field_list()
