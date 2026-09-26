"""Ancient Classics Data Lake (L0): books, editions and passages with full provenance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from ...protocol.documents import (
    Book,
    CollationStatus,
    Edition,
    Locator,
    Passage,
    SourceInfo,
    TemporalContext,
    VariantKind,
    VariantReading,
    YearRange,
)


@dataclass
class ExternalWork:
    id: str
    title: str
    aliases: list[str]
    authors: list[str]
    dynasty: str
    composition: YearRange | None
    status: str
    notes: str = ""


def _positions(text: str, sub: str) -> list[int]:
    out, start = [], 0
    while sub:
        i = text.find(sub, start)
        if i < 0:
            return out
        out.append(i)
        start = i + 1
    return out


def _merge(base: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base or {})
    out.update(override or {})
    return out


class Corpus:
    """In-memory corpus (YAML).  ``large`` corpora (``StoreCorpus``) share the same interface."""

    large = False

    def __init__(
        self,
        books: dict[str, Book],
        passages: dict[str, Passage],
        external: dict[str, ExternalWork] | None = None,
        root: Path | None = None,
    ) -> None:
        self.books = books
        self._passages = passages
        self.external = external or {}
        self.root = root
        self._order = sorted(passages, key=lambda pid: (self.year(passages[pid]) or 0, pid))

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, root: str | Path) -> "Corpus":
        root = Path(root)
        meta = yaml.safe_load((root / "books.yaml").read_text(encoding="utf-8"))
        books: dict[str, Book] = {}
        for raw in meta["books"]:
            editions = [
                Edition(
                    id=e["id"],
                    book_id=raw["id"],
                    name=e["name"],
                    year=YearRange.parse(e.get("year")),
                    holding_institution=e.get("holding_institution"),
                    quality=float(e.get("quality", 0.5)),
                    notes=e.get("notes", ""),
                )
                for e in raw.get("editions", [])
            ]
            books[raw["id"]] = Book(
                id=raw["id"],
                title=raw["title"],
                dynasty=raw["dynasty"],
                category=raw["category"],
                source=SourceInfo(**raw["source"]) if raw.get("source") else SourceInfo(origin="", license="", acquisition=""),
                authors=list(raw.get("authors", [])),
                aliases=list(raw.get("aliases", [])),
                composition=YearRange.parse(raw.get("composition")),
                author_life=YearRange.parse(raw.get("author_life")),
                dating_basis=raw.get("dating_basis", "composition"),
                attribution=raw.get("attribution", "traditional"),
                school=raw.get("school"),
                editions=editions,
                notes=raw.get("notes", ""),
                work=raw.get("work"),
            )
        external = {
            raw["id"]: ExternalWork(
                id=raw["id"],
                title=raw["title"],
                aliases=list(raw.get("aliases", [])),
                authors=list(raw.get("authors", [])),
                dynasty=raw.get("dynasty", ""),
                composition=YearRange.parse(raw.get("composition")),
                status=raw.get("status", "lost"),
                notes=raw.get("notes", ""),
            )
            for raw in meta.get("external_works", [])
        }
        passages: dict[str, Passage] = {}
        for path in sorted((root / "books").glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for block in data if isinstance(data, list) else [data]:
                for p in cls._parse_block(block, books):
                    if p.id in passages:
                        raise ValueError(f"duplicate passage id {p.id}")
                    passages[p.id] = p
        return cls(books, passages, external, root)

    @staticmethod
    def _parse_block(block: dict[str, Any], books: dict[str, Book]) -> list[Passage]:
        book = books[block["book"]]
        edition_id = block.get("edition") or (book.editions[0].id if book.editions else None)
        edition = book.edition(edition_id)
        defaults = block.get("defaults", {})
        out = []
        for raw in block["passages"]:
            loc = _merge(defaults.get("locator"), raw.get("locator"))
            loc.setdefault("precision", "approximate")
            locator = Locator(book_id=book.id, edition_id=edition_id, **loc)
            temporal_override = raw.get("temporal", {})
            temporal = TemporalContext(
                dynasty=book.dynasty,
                t_author=book.author_life,
                t_composition=YearRange.parse(temporal_override.get("t_composition")) or book.composition,
                t_edition=edition.year if edition else None,
                t_citation=YearRange.parse(temporal_override.get("t_citation")),
            )
            text = raw["text"]
            variants = []
            for i, v in enumerate(raw.get("variants", [])):
                start = v.get("start")
                if start is None:
                    start = text.find(v["base"])
                    if start < 0:
                        raise ValueError(f"{raw['id']}: variant base {v['base']!r} not found in text")
                variants.append(
                    VariantReading(
                        id=f"{raw['id']}.v{i + 1}",
                        passage_id=raw["id"],
                        start=start,
                        end=v.get("end", start + len(v["base"])),
                        base=v["base"],
                        reading=v["reading"],
                        witness=v["witness"],
                        witness_type=v.get("witness_type", "edition"),
                        kind=VariantKind(v.get("kind", "variant_char")),
                        note=v.get("note", ""),
                    )
                )
            out.append(
                Passage(
                    id=raw["id"],
                    book_id=book.id,
                    edition_id=edition_id,
                    locator=locator,
                    text=text,
                    temporal=temporal,
                    raw_text=raw.get("raw_text"),
                    ocr_confidence=raw.get("ocr_confidence"),
                    collation_status=CollationStatus(raw.get("collation_status", "unverified")),
                    punctuation=raw.get("punctuation", "editorial"),
                    variants=variants,
                    kind=raw.get("kind", defaults.get("kind", "text")),
                    tags=list(raw.get("tags", [])),
                    translation=raw.get("translation"),
                    notes=raw.get("notes", ""),
                    abridged=bool(raw.get("abridged", False)),
                )
            )
        return out

    # --------------------------------------------------------------- queries
    def book(self, book_id: str) -> Book:
        return self.books[book_id]

    def passage(self, passage_id: str) -> Passage:
        return self._passages[passage_id]

    def has_passage(self, passage_id: str) -> bool:
        return passage_id in self._passages

    def passage_ids(self) -> list[str]:
        return list(self._order)

    def __len__(self) -> int:
        return len(self._passages)

    def basis_for(self, passage: Passage, basis: str | None = None) -> str:
        if basis:
            return basis
        book = self.books.get(passage.book_id)
        return book.dating_basis if book else "composition"

    def year(self, passage: Passage, basis: str | None = None) -> float | None:
        return passage.temporal.year(self.basis_for(passage, basis))

    def year_range(self, passage: Passage, basis: str | None = None) -> YearRange | None:
        return passage.temporal.effective(self.basis_for(passage, basis))

    def passages(
        self,
        *,
        book_ids: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        kinds: Iterable[str] | None = None,
        after: float | None = None,
        before: float | None = None,
        basis: str | None = None,
    ) -> list[Passage]:
        books = set(book_ids) if book_ids is not None else None
        tagset = set(tags) if tags is not None else None
        kindset = set(kinds) if kinds is not None else None
        out = []
        for pid in self._order:
            p = self._passages[pid]
            if books is not None and p.book_id not in books:
                continue
            if tagset is not None and not tagset.intersection(p.tags):
                continue
            if kindset is not None and p.kind not in kindset:
                continue
            y = self.year(p, basis)
            if after is not None and (y is None or y < after):
                continue
            if before is not None and (y is None or y >= before):
                continue
            out.append(p)
        return out

    def subset(self, passage_ids: Iterable[str]) -> "Corpus":
        keep = set(passage_ids)
        passages = {pid: p for pid, p in self._passages.items() if pid in keep}
        books = {bid: b for bid, b in self.books.items() if any(p.book_id == bid for p in passages.values())}
        return Corpus(books, passages, self.external, self.root)

    def without_books(self, book_ids: Iterable[str]) -> "Corpus":
        drop = set(book_ids)
        return self.subset(pid for pid, p in self._passages.items() if p.book_id not in drop)

    def witnesses(self, target: str) -> list[str]:
        """Books that transmit ``target`` — the book itself, or every witness of the work of that id
        (a generic reference to 《伤寒论》 resolves to 注解伤寒论 when only that witness is ingested)."""
        if target in self.books:
            return [target]
        hits = [b for b in self.books.values() if getattr(b, "work", None) == target]
        return [b.id for b in sorted(hits, key=lambda b: (b.composition.start if b.composition else 0, b.id))]

    def title_index(self) -> dict[str, tuple[str, str]]:
        """Surface title/alias → (kind, id) where kind is 'book' or 'external'."""
        index: dict[str, tuple[str, str]] = {}
        for book in self.books.values():
            for name in [book.title, *book.aliases]:
                index.setdefault(name, ("book", book.id))
        for work in self.external.values():
            for name in [work.title, *work.aliases]:
                index.setdefault(name, ("external", work.id))
        return index

    # ------------------------------------------------ search interface (scan)
    def passages_by_id(self, ids: Iterable[str]) -> list[Passage]:
        return [self._passages[i] for i in ids if i in self._passages]

    def count_range(self, *, after: float | None = None, before: float | None = None) -> int:
        return len(self.passages(after=after, before=before))

    def book_passage_count(self, book_id: str) -> int:
        return sum(1 for p in self._passages.values() if p.book_id == book_id)

    def contains(self, surface: str, *, after: float | None = None, before: float | None = None,
                 book_ids: Iterable[str] | None = None, limit: int | None = None, verify: bool = True,
                 normalize: Any = None) -> list[str]:
        norm_fn = normalize or self.normalize or (lambda t: t)
        target = norm_fn(surface)
        out = [p.id for p in self.passages(book_ids=book_ids, after=after, before=before) if target in norm_fn(p.text)]
        return out[:limit] if limit else out

    def count(self, surface: str, *, after: float | None = None, before: float | None = None) -> int:
        return len(self.contains(surface, after=after, before=before))

    def search(self, surfaces: Iterable[str], *, limit: int = 200, after: float | None = None, before: float | None = None,
               book_ids: Iterable[str] | None = None) -> list[tuple[str, float]]:
        norm_fn = self.normalize or (lambda t: t)
        targets = [norm_fn(s) for s in surfaces if s]
        scored = []
        for p in self.passages(book_ids=book_ids, after=after, before=before):
            text = norm_fn(p.text)
            hits = sum(text.count(t) for t in targets)
            if hits:
                scored.append((p.id, float(hits)))
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:limit]

    def near(self, left: Iterable[str], right: Iterable[str], *, distance: int = 24, after: float | None = None,
             before: float | None = None, limit: int | None = None) -> list[str]:
        norm_fn = self.normalize or (lambda t: t)
        ls = [norm_fn(x) for x in left if x]
        rs = [norm_fn(x) for x in right if x]
        out = []
        for p in self.passages(after=after, before=before):
            text = norm_fn(p.text)
            lpos = [i for s in ls for i in _positions(text, s)]
            rpos = [i for s in rs for i in _positions(text, s)]
            if any(abs(a - b) <= distance for a in lpos for b in rpos):
                out.append(p.id)
        return out[:limit] if limit else out

    normalize: Any = None  # set by the classics plugin (the domain's variant normaliser)

    def stats(self, periods: Any = None) -> dict[str, Any]:
        by_book: dict[str, int] = {}
        by_period: dict[str, int] = {}
        for p in self._passages.values():
            by_book[p.book_id] = by_book.get(p.book_id, 0) + 1
            if periods is not None:
                pid = periods.period_of(self.year(p))
                by_period[pid] = by_period.get(pid, 0) + 1
        chars = sum(len(p.text) for p in self._passages.values())
        return {
            "books": len(self.books),
            "passages": len(self._passages),
            "characters": chars,
            "by_book": dict(sorted(by_book.items())),
            "by_period": {k: by_period[k] for k in (periods.ids() if periods else []) if k in by_period},
            "external_works": sorted(self.external),
        }
