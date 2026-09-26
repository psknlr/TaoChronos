"""版本与影像见证 — every witness of a work: the transcriptions in the store and the digitised copies held by libraries.

A work's transcriptions (its books in the store, each an edition with its date, holder, source and licence) are
listed with the number of their passages and whether those passages link the image of their page (CMETA's editions
do).  The digitised copies come from the image-witness catalog (``corpus/catalog/images/*.csv``, harvested by
``taochronos corpus images``): prints and manuscripts in NIJL's holders, the Staatsbibliothek zu Berlin, the Library of
Congress, 早稲田 and NDL, each with its IIIF manifest and its terms of use, linked to the work by title.  A title link
is a candidate: the record's ``match`` says how it was made, and a person should check the record before relying on it.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from .base import StudyBase
from .stemma import SOURCE_NAMES


def _year_key(row: dict[str, Any]) -> tuple[int, str]:
    y = str(row.get("years") or "")
    return (int(y.split("-")[0]) if y[:4].isdigit() else 9999, str(row.get("title") or ""))


class WitnessStudy:
    def __init__(self, base: StudyBase, stemma: Any, catalog_dir: Path | None = None) -> None:
        self.b = base
        self.stemma = stemma
        self.catalog_dir = catalog_dir or base.pack.root.parent.parent / "corpus" / "catalog" / "images"
        self._rows: list[dict[str, str]] | None = None

    def image_rows(self) -> list[dict[str, str]]:
        if self._rows is None:
            rows: list[dict[str, str]] = []
            if self.catalog_dir.exists():
                for path in sorted(self.catalog_dir.glob("*.csv")):
                    with open(path, encoding="utf-8", newline="") as f:
                        rows += list(csv.DictReader(f))
            self._rows = rows
        return self._rows

    def _text_witness(self, ids: list[str]) -> dict[str, Any]:
        corpus = self.b.corpus
        book = corpus.books.get(ids[0])
        edition = next((e for e in (book.editions if book else []) if e), None)
        first = next(iter(corpus.passages(book_ids=[ids[0]])), None) if not hasattr(corpus, "store") else None
        images = False
        store = getattr(corpus, "store", None)
        if store is not None:
            with store.lock:
                row = store.db.execute("SELECT locator FROM passages WHERE book_id=? AND locator LIKE '%image_uri%' LIMIT 1",
                                       (ids[0],)).fetchone()
            images = row is not None
        elif first is not None:
            images = bool(first.locator.image_uri)
        count = getattr(corpus, "book_passage_count", None)
        return {
            "books": ids, "title": book.title if book else ids[0],
            "edition": edition.name if edition else "", "edition_years": [edition.year.start, edition.year.end]
            if edition and edition.year else None, "holding": edition.holding_institution if edition else None,
            "source": SOURCE_NAMES.get(src := (getattr(corpus, "sources", {}) or {}).get(ids[0], ""), src),
            "license": book.source.license if book else "", "passages": sum(count(b) for b in ids) if count else None,
            "page_images": images,
        }

    def run(self, work: str, *, books: list[str] | None = None, limit: int = 200) -> dict[str, Any]:
        sets = self.stemma.witness_sets(work, books)
        texts = [self._text_witness(ids) for ids in sets]
        texts.sort(key=lambda t: (t["edition_years"] or [9999])[0])
        members = [self.b.corpus.books[b] for s in sets for b in s if b in self.b.corpus.books]
        first = min(members, key=lambda bk: (len(bk.title), bk.id)) if members else None  # the work's plain title
        key = (first.work or first.id) if first else work
        ids = {b for s in sets for b in s}
        images = [r for r in self.image_rows() if r.get("work") == key or r.get("book") in ids]
        images.sort(key=_year_key)
        holders = Counter(r.get("holder", "") for r in images)
        name = key.split(":", 1)[1] if ":" in key else (first.title if first else work)  # ws:伤寒杂病论 → 伤寒杂病论
        return {
            "work": name, "work_key": key, "text_witnesses": texts,
            "image_witnesses": images[:limit], "image_count": len(images), "holders": dict(holders.most_common()),
            "with_manifest": sum(1 for r in images if r.get("manifest")),
            "note": "text witnesses: the work's transcriptions in the store (page_images: its passages link their page "
                    "image); image witnesses: digitised copies in libraries, linked by title — `match` says how, check the "
                    "record before relying on it; terms of use per record (`rights`)",
        }


__all__ = ["WitnessStudy"]
