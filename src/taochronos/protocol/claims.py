"""Claim: the minimal unit of historical medical knowledge.

A claim is *what a physician asserted, in a given text, edition and context*.
It is a hyperedge: the whole symptom-set + pulse + pattern + principle +
formula combination is one semantic unit, not a bag of independent triples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .base import Model, field_dict, field_list
from .concepts import EvidenceDomain, KnowledgeSpace
from .confidence import ConfidenceVector
from .documents import TemporalContext


class ClaimRelation(str, Enum):
    INDICATED_FOR = "indicated_for"  # …主之 / 宜… / 可与…
    CONTRAINDICATED = "contraindicated"  # 不可服 / 不可与 / 禁
    DEFINES = "defines"  # X之为病… / 名为X / 此名X
    CAUSES = "causes"  # etiology: 因于… / …所致 / …所感 / 伤于…
    PATHOGENESIS = "pathogenesis"  # 诸…皆属于… / …所生
    TREATMENT_PRINCIPLE = "treatment_principle"  # 寒者热之 / 当以…和之
    COMPOSED_OF = "composed_of"  # formula composition
    HERB_INDICATION = "herb_indication"  # 本草: X，味…，性…。主…
    TRANSFORMS_TO = "transforms_to"  # 转为… / 传…
    COMPLICATION = "complication"  # …发痈疽
    PROGNOSIS = "prognosis"  # …则愈 / …者死
    THEORY = "theory"  # general theoretical assertion


class Role(str, Enum):
    DISEASE = "disease"
    PATTERN = "pattern"
    SYMPTOM = "symptom"
    SIGN = "sign"
    PULSE = "pulse"
    TONGUE = "tongue"
    PATHOGENESIS = "pathogenesis"
    ETIOLOGY = "etiology"
    TREATMENT_PRINCIPLE = "treatment_principle"
    TREATMENT_METHOD = "treatment_method"
    FORMULA = "formula"
    HERB = "herb"
    ORGAN = "organ"
    CONDITION = "condition"  # age / sex / season / climate / region / constitution / stage
    NATURE = "nature"  # 药性: 寒热温凉平
    FLAVOR = "flavor"  # 药味
    CONCEPT = "concept"  # theory concept: 阴阳, 元气, 营卫…
    INDICATION = "indication"  # unmatched raw indication text (本草 主…)


INTERVENTION_ROLES = (Role.FORMULA, Role.HERB, Role.TREATMENT_METHOD)
FINDING_ROLES = (Role.SYMPTOM, Role.SIGN, Role.PULSE, Role.TONGUE)
CONDITION_ROLES = (Role.DISEASE, Role.PATTERN)


@dataclass(kw_only=True)
class ClaimArgument(Model):
    role: Role
    surface: str
    term_id: str | None = None
    sense_id: str | None = None
    start: int | None = None
    end: int | None = None
    negated: bool = False
    qualifiers: dict[str, str] = field_dict()  # dose, processing, optional (或), from_heading…

    @property
    def key(self) -> str:
        return self.term_id or self.surface


@dataclass(kw_only=True)
class ExtractionInfo(Model):
    method: str  # lexicon-rule | llm | manual
    rule: str | None = None
    model: str | None = None
    agent: str | None = None
    confidence: float = 0.5


@dataclass(kw_only=True)
class Claim(Model):
    id: str
    passage_id: str
    book_id: str
    relation: ClaimRelation
    arguments: list[ClaimArgument]
    quote: str
    start: int
    end: int
    temporal: TemporalContext
    extraction: ExtractionInfo
    edition_id: str | None = None
    polarity: str = "affirm"  # affirm | negate
    modality: str = "assertive"  # assertive | advisory | hedged | conditional
    context: str = ""
    space: KnowledgeSpace = KnowledgeSpace.CLASSICAL
    evidence_domain: EvidenceDomain = EvidenceDomain.HISTORICAL_TEXT
    confidence: ConfidenceVector = field(default_factory=ConfidenceVector)
    status: str = "extracted"
    tags: list[str] = field_list()

    def args(self, *roles: Role) -> list[ClaimArgument]:
        return [a for a in self.arguments if not roles or a.role in roles]

    def terms(self, *roles: Role, include_negated: bool = False) -> list[str]:
        out: list[str] = []
        for a in self.args(*roles):
            if a.negated and not include_negated:
                continue
            if a.key not in out:
                out.append(a.key)
        return out

    def hyperedge_key(self) -> str:
        members = sorted(f"{a.role.value}:{a.key}{'!' if a.negated else ''}" for a in self.arguments)
        return f"{self.relation.value}|" + ",".join(members)

    def year(self, basis: str = "composition") -> float | None:
        return self.temporal.year(basis)
