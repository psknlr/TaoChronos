"""Original Document layer: Book → Edition → Volume → Page → Region → Line → Passage.

Nothing here is a model inference: these objects describe the physical and
textual witnesses that every downstream claim must trace back to
("Claim → Pixel").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .base import Model, field_list


@dataclass(frozen=True)
class YearRange(Model):
    """Closed interval of years; negative values are BCE (公元前)."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"YearRange end {self.end} precedes start {self.start}")

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2

    def contains(self, year: float) -> bool:
        return self.start <= year <= self.end

    def overlaps(self, other: "YearRange") -> bool:
        return self.start <= other.end and other.start <= self.end

    def strictly_before(self, other: "YearRange") -> bool:
        return self.end < other.start

    def label(self) -> str:
        def fmt(y: int) -> str:
            return f"前{-y}" if y < 0 else str(y)

        return fmt(self.start) if self.start == self.end else f"{fmt(self.start)}–{fmt(self.end)}"

    @classmethod
    def parse(cls, value: Any) -> "YearRange | None":
        if value is None:
            return None
        if isinstance(value, YearRange):
            return value
        if isinstance(value, int):
            return cls(value, value)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return cls(int(value[0]), int(value[1]))
        if isinstance(value, dict):
            return cls(int(value["start"]), int(value["end"]))
        raise ValueError(f"cannot parse YearRange from {value!r}")


@dataclass(kw_only=True)
class SourceInfo(Model):
    """Where the digital text came from and under what terms (Gate G0)."""

    origin: str
    license: str
    acquisition: str
    url: str | None = None
    transcription: str = ""
    verified: bool = False


@dataclass(kw_only=True)
class Edition(Model):
    id: str
    book_id: str
    name: str
    year: YearRange | None = None
    holding_institution: str | None = None
    quality: float = 0.5
    base_text: bool = True
    notes: str = ""


@dataclass(kw_only=True)
class Book(Model):
    id: str
    title: str
    dynasty: str
    category: str
    source: SourceInfo
    authors: list[str] = field_list()
    aliases: list[str] = field_list()
    composition: YearRange | None = None  # t_composition (成书)
    author_life: YearRange | None = None  # t_author
    dating_basis: str = "composition"  # composition | author: which date analyses should use
    attribution: str = "traditional"  # traditional | disputed | pseudepigraphic | compiled
    school: str | None = None
    editions: list[Edition] = field_list()
    notes: str = ""
    work: str | None = None  # the work this witness transmits; witnesses of one work are not independent sources

    def edition(self, edition_id: str | None) -> Edition | None:
        for ed in self.editions:
            if edition_id is None or ed.id == edition_id:
                return ed
        return None


@dataclass(frozen=True, kw_only=True)
class BBox(Model):
    x: float
    y: float
    w: float
    h: float


@dataclass(kw_only=True)
class Locator(Model):
    """Hierarchical address of a passage inside its witness."""

    book_id: str
    edition_id: str | None = None
    volume: str | None = None  # 卷
    chapter: str | None = None  # 篇
    section: str | None = None  # 条文 / 方名
    page: str | None = None
    line: int | None = None
    region: BBox | None = None
    image_uri: str | None = None
    precision: str = "unknown"  # exact | approximate | unknown

    def chain(self) -> list[tuple[str, str | None]]:
        return [
            ("Book", self.book_id),
            ("Edition", self.edition_id),
            ("Volume", self.volume),
            ("Chapter", self.chapter),
            ("Section", self.section),
            ("Page", self.page),
            ("Line", None if self.line is None else str(self.line)),
            ("Region", None if self.region is None else f"{self.region.x},{self.region.y},{self.region.w},{self.region.h}"),
            ("Image", self.image_uri),
        ]

    def label(self) -> str:
        parts = [p for p in (self.volume, self.chapter, self.section) if p]
        return " · ".join(parts) if parts else self.book_id


@dataclass(kw_only=True)
class TemporalContext(Model):
    """The four clocks of a passage: author, composition, edition and citation."""

    dynasty: str | None = None
    t_author: YearRange | None = None
    t_composition: YearRange | None = None
    t_edition: YearRange | None = None
    t_citation: YearRange | None = None  # date of earlier material quoted inside the passage

    def effective(self, basis: str = "composition") -> YearRange | None:
        order = {
            "composition": (self.t_composition, self.t_author, self.t_edition),
            "author": (self.t_author, self.t_composition, self.t_edition),
            "edition": (self.t_edition, self.t_composition, self.t_author),
            "citation": (self.t_citation, self.t_composition, self.t_author),
            "earliest": (self.t_citation, self.t_author, self.t_composition, self.t_edition),
        }[basis]
        for value in order:
            if value is not None:
                return value
        return None

    def year(self, basis: str = "composition") -> float | None:
        rng = self.effective(basis)
        return None if rng is None else rng.midpoint


class VariantKind(str, Enum):
    VARIANT_CHAR = "variant_char"  # 异体字
    LOAN_CHAR = "loan_char"  # 通假字
    TABOO = "taboo_avoidance"  # 避讳
    EMENDATION = "emendation"  # 校改
    OMISSION = "omission"  # 脱文
    INTERPOLATION = "interpolation"  # 衍文
    TRANSPOSITION = "transposition"  # 倒文
    SCRIBAL_ERROR = "scribal_error"  # 讹文


@dataclass(kw_only=True)
class VariantReading(Model):
    """An alternative reading of a span of the base text, attested by a witness."""

    id: str
    passage_id: str
    start: int
    end: int
    base: str
    reading: str
    witness: str
    kind: VariantKind
    witness_type: str = "edition"  # base_edition | edition | commentator | conjecture
    note: str = ""


class CollationStatus(str, Enum):
    UNVERIFIED = "unverified"
    COLLATED = "collated"
    EXPERT_VERIFIED = "expert_verified"


@dataclass(kw_only=True)
class Passage(Model):
    id: str
    book_id: str
    locator: Locator
    text: str
    temporal: TemporalContext
    edition_id: str | None = None
    raw_text: str | None = None  # OCR layer if different from the collated text
    ocr_confidence: float | None = None  # None = manual transcription, no OCR involved
    collation_status: CollationStatus = CollationStatus.UNVERIFIED
    punctuation: str = "editorial"  # editorial | original | none
    variants: list[VariantReading] = field_list()
    kind: str = "text"  # text | formula | materia_medica | commentary | preface | verse
    tags: list[str] = field_list()
    translation: str | None = None
    notes: str = ""
    abridged: bool = False

    def year(self, basis: str = "composition") -> float | None:
        return self.temporal.year(basis)
