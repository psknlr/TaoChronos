"""Textual criticism (计算校勘与版本谱系): witnesses, readings, variant units and the stemma.

A *witness* is one transmission of a text — an edition or transcription of the work, or a quotation of a passage in
another work.  Witnesses are aligned to a *base* (the coordinate system, not a claim that the base is right); a
*variant unit* is a stretch of the base where at least one witness reads differently, with every reading and the
witnesses that carry it (TEI's ``<app>`` with ``<lem>`` / ``<rdg wit>``).  Readings shared by some witnesses and not
others group the witnesses; groups that the tree cannot hold together point to contamination (a witness copied
from more than one exemplar) — so the stemma is a tree *plus* contamination edges, never forced to be a pure tree.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Model, field_dict, field_list


@dataclass(kw_only=True)
class Witness(Model):
    id: str  # siglum (A, B, C …)
    book_id: str | None = None  # the transcription in the corpus, when there is one
    title: str = ""
    kind: str = "edition"  # edition | quotation | reconstruction
    years: list[float] = field_list()  # [start, end] of the witness (edition, or the quoting book)
    source: str = ""
    license: str = ""
    characters: int = 0  # characters of the witness in the collated range
    coverage: float = 0.0  # share of the base the witness carries (the rest is lacuna or out of scope)
    passage_id: str | None = None  # quotation witnesses: the passage


@dataclass(kw_only=True)
class Reading(Model):
    text: str  # normalised for comparison; "" is an omission
    witnesses: list[str] = field_list()  # sigla
    forms: dict[str, str] = field_dict()  # siglum → the reading in that witness's own characters


@dataclass(kw_only=True)
class VariantUnit(Model):
    id: str
    start: int  # base coordinates (Han characters of the normalised base)
    end: int
    lemma: str  # the base reading
    kind: str  # substitution | omission | addition | transposition | mixed
    readings: list[Reading] = field_list()  # the lemma's reading first
    lacunose: list[str] = field_list()  # witnesses without text here
    weight: float = 1.0  # variants of function words only weigh less
    structural: bool = False  # long additions (commentary) or omissions: listed, not used for the stemma
    passage_id: str | None = None  # the base passage
    locator: str = ""
    context: str = ""  # the base around the unit, 〔lemma〕 marked


@dataclass(kw_only=True)
class StemmaEdge(Model):
    parent: str  # a witness siglum or a hypothetical node (α, β …)
    child: str
    length: float = 0.0  # differences per 1 000 shared characters
    support: float = 0.0  # weight of shared readings that define the child's group


@dataclass(kw_only=True)
class ContaminationEdge(Model):
    witness: str  # the contaminated witness
    source: str  # the witness (or group) it also agrees with, against the tree
    share: float  # share of the witness's shared readings that conflict with the tree
    support: float  # weight of those readings
    examples: list[str] = field_list()  # variant unit ids


__all__ = ["ContaminationEdge", "Reading", "StemmaEdge", "VariantUnit", "Witness"]
