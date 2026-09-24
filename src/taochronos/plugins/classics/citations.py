"""Explicit citation extraction (《书名》, 经曰 …) with alias and lost-work resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...protocol.documents import Passage
from .corpus import Corpus
from .domain import DomainPack

_QUOTE_STOP = re.compile(r"[。；！？]")


@dataclass
class CitationMention:
    passage_id: str
    start: int
    end: int
    surface: str
    kind: str  # title | generic
    candidates: dict[str, float] = field(default_factory=dict)  # target id → weight
    target_kind: str = "book"  # book | external | unresolved
    quote: str = ""


class CitationExtractor:
    def __init__(self, pack: DomainPack, corpus: Corpus) -> None:
        self.pack = pack
        self.corpus = corpus
        self.titles = corpus.title_index()
        self.generic = pack.citations.get("generic_references", {})
        self.patterns = [(re.compile(p["regex"]), p["kind"]) for p in pack.citations.get("patterns", [])]

    def _witnessed(self, candidates: dict[str, float]) -> dict[str, float]:
        """Map candidate work ids onto the books that transmit them (weights split between witnesses)."""
        witnesses = getattr(self.corpus, "witnesses", None)
        if witnesses is None:
            return candidates
        out: dict[str, float] = {}
        for target, weight in candidates.items():
            books = witnesses(target) or [target]
            for b in books:
                out[b] = round(out.get(b, 0.0) + weight / len(books), 4)
        return out

    def _resolve_title(self, title: str) -> tuple[str, dict[str, float]]:
        if title in self.titles:
            kind, target = self.titles[title]
            return kind, {target: 1.0}
        if title in self.generic:
            return "book", self._witnessed(dict(self.generic[title]["candidates"]))
        for name, (kind, target) in self.titles.items():
            if title in name or name in title:
                return kind, {target: 0.8}
        return "unresolved", {title: 1.0}

    @staticmethod
    def _quote_after(text: str, pos: int) -> str:
        tail = text[pos:]
        tail = re.sub(r"^(所谓|论|曰|云|言|：|:|，)+", "", tail)
        tail = re.sub(r"^(所谓|论|曰|云|言|：|:|，)+", "", tail)
        stop = _QUOTE_STOP.search(tail)
        quote = tail[: stop.start()] if stop else tail
        return re.sub(r"(是也|也)$", "", quote)

    def extract(self, passage: Passage) -> list[CitationMention]:
        out: list[CitationMention] = []
        taken: list[tuple[int, int]] = []
        for regex, kind in self.patterns:
            for m in regex.finditer(passage.text):
                if any(s <= m.start() < e for s, e in taken):
                    continue
                surface = m.group(1)
                if kind == "title":
                    target_kind, candidates = self._resolve_title(surface)
                else:
                    spec = self.generic.get(surface, {})
                    target_kind, candidates = "book", self._witnessed(dict(spec.get("candidates", {})))
                    if not candidates:
                        continue
                taken.append((m.start(), m.end()))
                out.append(
                    CitationMention(
                        passage_id=passage.id,
                        start=m.start(),
                        end=m.end(),
                        surface=surface,
                        kind=kind,
                        candidates=candidates,
                        target_kind=target_kind,
                        quote=self._quote_after(passage.text, m.end()),
                    )
                )
        return out
