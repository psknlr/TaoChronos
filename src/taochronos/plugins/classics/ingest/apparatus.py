"""The modern apparatus of kept editions, separated from the old text by rules of the catalog entry.

A modern edition of an old book mixes the old text with its editors' work: commentary (唐步祺's 【闡釋】 on
郑钦安, 徐荣斋's 【榮齋按】 on 俞根初), the source references of a reconstructed lost work (（《大觀》卷三，《政和》八一頁）),
sigla (〔證〕), footnotes and their calls, doses converted to grams (6克).  The catalog entry names them, and the 笈成
and document parsers apply the rules:

* ``paragraphs`` — a paragraph matching ``pattern`` takes ``layer`` (none given: the main text).  With ``block``
  the layer runs on over the following unmarked paragraphs until another rule matches or a heading comes, and
  with ``while`` only over paragraphs that match it (the modern punctuation of a 1950s commentator among older
  layers punctuated with 。 alone), with ``until`` up to and including the paragraph that matches it (an
  editor's 〔…〕 insertion running over several paragraphs); ``drop`` takes the paragraph out of the text into the
  metadata of the passage it belongs to (a source reference line of a reconstructed work).
* ``apparatus`` — pieces of a paragraph matching ``pattern`` leave the text: with a ``layer`` they become
  commentary of that layer anchored to the passage, otherwise they go to the passage's metadata
  (``extra.apparatus``).
* ``drop_sections`` — headings of sections an editor wrote (a 凡例, a 校勘记 of 1963), dropped with their content.
* ``heading_layers`` — headings whose section, up to the next heading of the same or a higher level, is a later
  addition (徐荣斋's （新增） sections).
* ``own_sections`` — headings that look like paratext but are the author's own text (陶弘景's 序錄), dated with the
  book instead of as front matter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .kanripo import LayerSpec


@dataclass
class ParagraphRule:
    pattern: re.Pattern[str]
    layer: LayerSpec | None = None  # None: the main layer
    block: bool = False
    while_: re.Pattern[str] | None = None
    until: re.Pattern[str] | None = None
    drop: bool = False


@dataclass
class ApparatusRule:
    pattern: re.Pattern[str]
    layer: LayerSpec | None = None  # None: into the passage's metadata


def _layer(raw: dict[str, Any]) -> LayerSpec | None:
    if not raw.get("layer"):
        return None
    year = raw["year"]
    year = (int(year), int(year)) if isinstance(year, int) else (int(year[0]), int(year[1]))
    return LayerSpec(raw["layer"], year, raw.get("attribution", ""))


def paragraph_rules(raw: list[dict[str, Any]] | None) -> list[ParagraphRule]:
    return [ParagraphRule(re.compile(r["pattern"]), _layer(r), bool(r.get("block")),
                          re.compile(r["while"]) if r.get("while") else None,
                          re.compile(r["until"]) if r.get("until") else None, bool(r.get("drop"))) for r in raw or []]


def apparatus_rules(raw: list[dict[str, Any]] | None) -> list[ApparatusRule]:
    return [ApparatusRule(re.compile(r["pattern"]), _layer(r)) for r in raw or []]


def heading_rules(raw: list[dict[str, Any]] | None) -> list[tuple[re.Pattern[str], LayerSpec]]:
    return [(re.compile(r["pattern"]), lay) for r in raw or [] if (lay := _layer(r)) is not None]


class ParagraphState:
    """The paragraph rules of one book, with the block that is running."""

    def __init__(self, rules: list[ParagraphRule]) -> None:
        self.rules = rules
        self.running: ParagraphRule | None = None

    def heading(self) -> None:
        self.running = None

    def classify(self, text: str) -> ParagraphRule | None:
        """The rule that decides a paragraph (its own, or the block it continues); None: no rule applies."""
        for rule in self.rules:
            if rule.pattern.search(text):
                self.running = rule if rule.block else None
                return rule
        rule = self.running
        if rule is not None:
            if rule.until is not None:
                if rule.until.search(text):
                    self.running = None
                return rule
            if rule.while_ is None or rule.while_.search(text):
                return rule
            self.running = None
        return None


def cut(text: str, rules: list[ApparatusRule]) -> tuple[str, list[tuple[LayerSpec, str]], list[str]]:
    """A paragraph without its apparatus: (text, commentary pieces with their layer, pieces for the metadata)."""
    commentary: list[tuple[LayerSpec, str]] = []
    dropped: list[str] = []
    for rule in rules:
        def take(m: re.Match[str], rule: ApparatusRule = rule) -> str:
            piece = m.group(0).strip("　 ")
            if piece:
                if rule.layer is not None:
                    commentary.append((rule.layer, piece))
                else:
                    dropped.append(piece)
            return ""
        text = rule.pattern.sub(take, text)
    return text, commentary, dropped


def describe(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The rules of a catalog entry as layer records of the book (for its provenance)."""
    out: list[dict[str, Any]] = []
    for r in entry.get("paragraphs") or []:
        if r.get("layer"):
            out.append({"kind": "paragraphs", **r})
    for r in entry.get("apparatus") or []:
        out.append({"kind": "apparatus", **({"layer": "（移入元数据）"} if not r.get("layer") else {}), **r})
    for r in entry.get("heading_layers") or []:
        out.append({"kind": "heading_layers", **r})
    if entry.get("drop_sections"):
        out.append({"kind": "drop_sections", "patterns": list(entry["drop_sections"])})
    if entry.get("own_sections"):
        out.append({"kind": "own_sections", "patterns": list(entry["own_sections"])})
    return out


class Attacher:
    """Metadata pieces taken out of the text go to the passage they belong to: the last passage of the same
    section when the piece follows it (〔嘉‧證〕 after a fragment), otherwise the next passage (a source line
    under a heading, before its entry)."""

    def __init__(self) -> None:
        self.pending: list[str] = []

    def add(self, rows: list[dict[str, Any]], pieces: list[str], loc: dict[str, Any]) -> None:
        if not pieces:
            return
        if rows and rows[-1]["locator"] == loc:
            rows[-1]["extra"].setdefault("apparatus", []).extend(pieces)
        else:
            self.pending.extend(pieces)

    def attach(self, row: dict[str, Any], pieces: list[str] = ()) -> None:
        both = [*self.pending, *pieces]
        if both:
            row["extra"].setdefault("apparatus", []).extend(both)
        self.pending = []


__all__ = ["ApparatusRule", "Attacher", "ParagraphRule", "ParagraphState", "apparatus_rules", "cut", "describe",
           "heading_rules", "paragraph_rules"]
