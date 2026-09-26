"""Explicit citation extraction (《书名》, 经曰 …) with alias and lost-work resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...protocol.documents import Passage
from .corpus import Corpus
from .domain import DomainPack

_QUOTE_STOP = re.compile(r"[。；！？]")
_CHAPTER_CHARS = str.maketrans({"藏": "脏", "府": "腑"})  # 邪氣藏府病形 ~ 邪氣臟腑病形


def _chapter_key(name: str) -> str:
    return name.removesuffix("篇").translate(_CHAPTER_CHARS)


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
        norm = pack.variants.normalize_text
        self.norm_titles: dict[str, tuple[str, str]] = {}
        for name, value in self.titles.items():
            self.norm_titles.setdefault(norm(name), value)
        chapters = getattr(corpus, "chapter_titles", None)
        self.chapters: dict[str, str] = {_chapter_key(k): v for k, v in (chapters() if chapters else {}).items()}
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
        norm = self.pack.variants.normalize_text(title)
        if norm in self.norm_titles:  # 《内經》 against the alias 内经 …
            kind, target = self.norm_titles[norm]
            return kind, {target: 1.0}
        if norm in self.generic:
            return "book", self._witnessed(dict(self.generic[norm]["candidates"]))
        if _chapter_key(norm) in self.chapters:  # 《脉要精微论》: a chapter of the 素问, not a lost book
            return "book", {self.chapters[_chapter_key(norm)]: 0.9}
        parts = [p for p in re.split(r"[·‧・]", norm) if p]
        if len(parts) > 1:  # 《內經‧陰陽別論》: book · chapter
            kind, candidates = self._resolve_title(parts[0])
            if kind != "unresolved":
                return kind, {k: round(v * 0.9, 4) for k, v in candidates.items()}
            if _chapter_key(parts[-1]) in self.chapters:
                return "book", {self.chapters[_chapter_key(parts[-1])]: 0.8}
        # a longer or shorter form of a known title (伤寒杂病论 ~ 伤寒论 is not matched: names of two characters or
        # more only, the longest wins)
        best: tuple[int, str, str] | None = None
        for name, (kind, target) in self.norm_titles.items():
            if len(name) >= 2 and len(norm) >= 2 and (norm in name or name in norm):
                if best is None or len(name) > best[0]:
                    best = (len(name), kind, target)
        if best is not None:
            return best[1], {best[2]: 0.8}
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
