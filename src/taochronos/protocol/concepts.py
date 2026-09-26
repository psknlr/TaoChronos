"""Historical Semantic Layer: historical terms, period-bound senses and guarded mappings.

A historical term is never overwritten by a modern standard term.  The link
between them is an explicit, typed :class:`ConceptMapping` that records *how*
they correspond (``partially_overlapping`` rather than ``=``), which is the
central defence against medical anachronism (医学时代错置).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .base import Model, field_list
from .documents import YearRange


class KnowledgeSpace(str, Enum):
    """Isolated knowledge spaces; crossing between them needs an explicit mapping + gate."""

    CLASSICAL = "classical"  # what the ancient text says
    HISTORICAL_INTERPRETATION = "historical_interpretation"  # how it is read in its own period
    COMPUTATIONAL_HYPOTHESIS = "computational_hypothesis"  # what TaoChronos infers
    MODERN_TCM = "modern_tcm"
    BIOMEDICAL = "biomedical"


class EvidenceDomain(str, Enum):
    HISTORICAL_TEXT = "historical_text"
    MODERN_CLINICAL = "modern_clinical"
    PHARMACOLOGY = "pharmacology"
    MOLECULAR = "molecular"


MODERN_EVIDENCE_DOMAINS = (EvidenceDomain.MODERN_CLINICAL, EvidenceDomain.PHARMACOLOGY, EvidenceDomain.MOLECULAR)


class MappingRelation(str, Enum):
    EQUIVALENT = "equivalent"
    RELATED = "related"  # historicallyRelatedTo
    PARTIALLY_OVERLAPPING = "partially_overlapping"  # partiallyMapsTo / mayOverlapWith
    UNCERTAIN = "uncertain"
    NOT_EQUIVALENT = "not_equivalent"


class SynonymKind(str, Enum):
    ALIAS = "alias"  # 异名同义
    TABOO_RENAME = "taboo_rename"  # 避讳改名, e.g. 薯蓣→山药, 玄参→元参
    PART_NAME = "part_name"  # 山萸肉 / 山茱萸, 归尾 / 当归
    PROCESSING = "processing_variant"  # 干地黄 / 熟地黄 / 生地黄
    ABBREVIATION = "abbreviation"  # 银花 / 金银花, 芥穗 / 荆芥穗
    VARIETY = "variety"  # 抚芎 / 川芎


@dataclass(kw_only=True)
class Synonym(Model):
    surface: str
    kind: SynonymKind = SynonymKind.ALIAS
    period: YearRange | None = None
    note: str = ""


@dataclass(kw_only=True)
class Sense(Model):
    """A period-bound meaning of a historical term."""

    id: str
    term_id: str
    label: str
    gloss: str
    category: str
    period: YearRange | None = None
    cues: list[str] = field_list()
    anti_cues: list[str] = field_list()
    exemplars: list[str] = field_list()
    notes: str = ""


@dataclass(kw_only=True)
class HistoricalTerm(Model):
    id: str
    surface: str
    category: str
    variants: list[str] = field_list()
    synonyms: list[Synonym] = field_list()
    senses: list[Sense] = field_list()
    related: list[str] = field_list()
    broader: list[str] = field_list()
    narrower: list[str] = field_list()
    components: list[str] = field_list()  # decomposition of compound concepts, e.g. 湿热 → 湿 + 热
    notes: str = ""

    def sense(self, sense_id: str) -> Sense | None:
        for s in self.senses:
            if s.id == sense_id:
                return s
        return None


@dataclass(kw_only=True)
class StandardConcept(Model):
    id: str
    label: str
    system: str
    space: KnowledgeSpace
    category: str
    code: str | None = None
    notes: str = ""


@dataclass(kw_only=True)
class ConceptMapping(Model):
    id: str
    sense_id: str
    concept_id: str
    relation: MappingRelation
    rationale: str
    status: str = "proposed"  # proposed | approved | rejected
    proposed_by: str = ""
    approved_by: str | None = None
