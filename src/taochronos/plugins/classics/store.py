"""Scalable corpus store (SQLite + FTS5) and the lazy StoreCorpus.

The demo corpus fits in memory; the full corpus (hundreds of books, tens of millions of characters) does
not.  Passages live in one SQLite file with their locators, the four temporal clocks and provenance; a
contentless FTS5 index over *overlapping character bigrams of the normalised text* answers substring,
phrase and proximity queries for terms of any length (most classical terms are two characters, which a
trigram index cannot serve).  The original text is stored verbatim; normalisation (script conversion,
variant forms) exists only in the index, whose normaliser fingerprint is recorded so a changed variant
table is detected.

``StoreCorpus`` implements the ``Corpus`` interface lazily (passages are materialised on demand behind an
LRU cache) and adds the search interface used by retrieval, curation and falsification at scale:
``contains``, ``search``, ``near`` and ``count``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from ...protocol.base import to_jsonable
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
from .corpus import Corpus, ExternalWork

SCHEMA_VERSION = 1
PAD = "z"  # closes a run so every character starts one token (single-character prefix queries)
BREAK = "x"  # separates runs so phrases cannot match across punctuation


def is_han(ch: str) -> bool:
    o = ord(ch)
    return 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3134F or o == 0x3007 or o == 0x3013


def grams(norm: str) -> str:
    """Overlapping bigram tokens of each run of Han characters (plus a padded final token)."""
    out: list[str] = []
    run_start = -1
    n = len(norm)
    for i in range(n + 1):
        han = i < n and is_han(norm[i])
        if han and run_start < 0:
            run_start = i
        elif not han and run_start >= 0:
            run = norm[run_start:i]
            out.extend(run[j: j + 2] for j in range(len(run) - 1))
            out.append(run[-1] + PAD)
            run_start = -1
            if i < n:
                out.append(BREAK)
        elif not han and i < n and out and out[-1] != BREAK:
            out.append(BREAK)
    return " ".join(out)


def fts_phrase(norm_surface: str) -> str | None:
    """FTS5 query for a normalised surface: a bigram phrase, or a prefix query for one character."""
    chars = [c for c in norm_surface if is_han(c)]
    if not chars:
        return None
    if len(chars) == 1:
        return f"{chars[0]}*"
    toks = [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return '"' + " ".join(toks) + '"'


def _dump(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, separators=(",", ":"))


def book_from_dict(raw: dict[str, Any]) -> Book:
    editions = [
        Edition(
            id=e["id"], book_id=raw["id"], name=e["name"], year=YearRange.parse(e.get("year")),
            holding_institution=e.get("holding_institution"), quality=float(e.get("quality", 0.5)),
            base_text=bool(e.get("base_text", True)), notes=e.get("notes", ""),
        )
        for e in raw.get("editions", [])
    ]
    src = raw.get("source") or {}
    return Book(
        id=raw["id"], title=raw["title"], dynasty=raw.get("dynasty", ""), category=raw.get("category", ""),
        source=SourceInfo(origin=src.get("origin", ""), license=src.get("license", ""), acquisition=src.get("acquisition", ""),
                          url=src.get("url"), transcription=src.get("transcription", ""), verified=bool(src.get("verified", False))),
        authors=list(raw.get("authors", [])), aliases=list(raw.get("aliases", [])),
        composition=YearRange.parse(raw.get("composition")), author_life=YearRange.parse(raw.get("author_life")),
        dating_basis=raw.get("dating_basis", "composition"), attribution=raw.get("attribution", "traditional"),
        school=raw.get("school"), editions=editions, notes=raw.get("notes", ""), work=raw.get("work"),
    )


def _temporal(raw: dict[str, Any]) -> TemporalContext:
    return TemporalContext(
        dynasty=raw.get("dynasty"),
        t_author=YearRange.parse(raw.get("t_author")),
        t_composition=YearRange.parse(raw.get("t_composition")),
        t_edition=YearRange.parse(raw.get("t_edition")),
        t_citation=YearRange.parse(raw.get("t_citation")),
    )


class CorpusStore:
    """Low-level access to the SQLite file (writer and reader)."""

    def __init__(self, path: str | Path, *, create: bool = False, readonly: bool = False) -> None:
        self.path = Path(path)
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            raise FileNotFoundError(f"corpus store not found: {self.path} (run `taochronos corpus ingest`)")
        uri = f"file:{self.path}?mode=ro" if readonly else f"file:{self.path}"
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL" if not readonly else "PRAGMA query_only=1")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA cache_size=-200000")
        self.lock = threading.RLock()
        if create:
            self._schema()

    def _schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, source TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS external(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS passages(
                rid INTEGER PRIMARY KEY,
                id TEXT UNIQUE NOT NULL,
                book_id TEXT NOT NULL,
                edition_id TEXT,
                seq INTEGER NOT NULL,
                kind TEXT NOT NULL,
                layer TEXT,
                year REAL,
                y_start INTEGER,
                y_end INTEGER,
                locator TEXT NOT NULL,
                temporal TEXT NOT NULL,
                text TEXT NOT NULL,
                punctuation TEXT,
                extra TEXT
            );
            CREATE INDEX IF NOT EXISTS passages_book ON passages(book_id, seq);
            CREATE INDEX IF NOT EXISTS passages_year ON passages(year);
            CREATE VIRTUAL TABLE IF NOT EXISTS grams USING fts5(g, content='', detail=full, tokenize='unicode61 remove_diacritics 0');
            CREATE TABLE IF NOT EXISTS claim_cache(passage_id TEXT, version TEXT, data TEXT, PRIMARY KEY(passage_id, version));
            """
        )
        self.set_meta("schema_version", str(SCHEMA_VERSION))
        self.db.commit()

    # ------------------------------------------------------------------ meta
    def meta(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    # --------------------------------------------------------------- writing
    def put_book(self, raw: dict[str, Any], source: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO books(id, source, data) VALUES (?, ?, ?)", (raw["id"], source, _dump(raw)))

    def put_external(self, raw: dict[str, Any]) -> None:
        self.db.execute("INSERT OR REPLACE INTO external(id, data) VALUES (?, ?)", (raw["id"], _dump(raw)))

    def set_external(self, works: Iterable[dict[str, Any]]) -> int:
        """Replace the registry of works cited but not in the corpus (lost or extant elsewhere)."""
        self.db.execute("DELETE FROM external")
        n = 0
        for raw in works:
            self.put_external(raw)
            n += 1
        self.db.commit()
        return n

    def delete_book(self, book_id: str, normalize: Callable[[str], str]) -> int:
        """Remove a book's passages (the contentless index needs the indexed tokens to delete them)."""
        rows = self.db.execute("SELECT rid, text FROM passages WHERE book_id=?", (book_id,)).fetchall()
        for rid, text in rows:
            self.db.execute("INSERT INTO grams(grams, rowid, g) VALUES('delete', ?, ?)", (rid, grams(normalize(text))))
        self.db.execute("DELETE FROM passages WHERE book_id=?", (book_id,))
        self.db.execute("DELETE FROM books WHERE id=?", (book_id,))
        self.db.execute("DELETE FROM claim_cache WHERE passage_id LIKE ?", (book_id + ".%",))
        return len(rows)

    def add_passages(self, rows: Iterable[dict[str, Any]], normalize: Callable[[str], str]) -> int:
        n = 0
        cur = self.db.cursor()
        for r in rows:
            cur.execute(
                "INSERT INTO passages(id, book_id, edition_id, seq, kind, layer, year, y_start, y_end, locator, temporal, text, punctuation, extra)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r["book_id"], r.get("edition_id"), r["seq"], r.get("kind", "text"), r.get("layer"), r.get("year"),
                 r.get("y_start"), r.get("y_end"), _dump(r["locator"]), _dump(r["temporal"]), r["text"], r.get("punctuation", "none"),
                 _dump(r.get("extra") or {})),
            )
            cur.execute("INSERT INTO grams(rowid, g) VALUES (?, ?)", (cur.lastrowid, grams(normalize(r["text"]))))
            n += 1
        return n

    def reindex(self, normalize: Callable[[str], str], fingerprint: str, progress: Callable[[int], None] | None = None) -> int:
        """Rebuild the FTS index (e.g. after the variant table changed)."""
        self.db.execute("DROP TABLE IF EXISTS grams")
        self.db.execute("CREATE VIRTUAL TABLE grams USING fts5(g, content='', detail=full, tokenize='unicode61 remove_diacritics 0')")
        n = 0
        cur = self.db.cursor()
        for rid, text in self.db.execute("SELECT rid, text FROM passages ORDER BY rid").fetchall():
            cur.execute("INSERT INTO grams(rowid, g) VALUES (?, ?)", (rid, grams(normalize(text))))
            n += 1
            if progress and n % 50000 == 0:
                progress(n)
        self.set_meta("normalizer", fingerprint)
        self.db.execute("DELETE FROM claim_cache")
        self.db.commit()
        return n

    def optimize(self) -> None:
        self.db.execute("INSERT INTO grams(grams) VALUES('optimize')")
        self.db.commit()

    def commit(self) -> None:
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class StoreCorpus:
    """``Corpus`` over a ``CorpusStore`` — lazy, cached, searchable."""

    large = True

    def __init__(self, store: CorpusStore | str | Path, normalize: Callable[[str], str], *, fingerprint: str | None = None,
                 exclude_books: Iterable[str] = (), cache_size: int = 50_000, root: Path | None = None) -> None:
        self.store = store if isinstance(store, CorpusStore) else CorpusStore(store, readonly=False)
        self.normalize = normalize
        self.root = root
        self.exclude_books = set(exclude_books)
        self.fingerprint_ok = fingerprint is None or self.store.meta("normalizer") in (None, fingerprint)
        self.books: dict[str, Book] = {}
        self.sources: dict[str, str] = {}
        for bid, source, data in self.store.db.execute("SELECT id, source, data FROM books ORDER BY id"):
            if bid in self.exclude_books:
                continue
            self.books[bid] = book_from_dict(json.loads(data))
            self.sources[bid] = source
        self.external: dict[str, ExternalWork] = {}
        for _, data in self.store.db.execute("SELECT id, data FROM external ORDER BY id"):
            raw = json.loads(data)
            self.external[raw["id"]] = ExternalWork(
                id=raw["id"], title=raw["title"], aliases=list(raw.get("aliases", [])), authors=list(raw.get("authors", [])),
                dynasty=raw.get("dynasty", ""), composition=YearRange.parse(raw.get("composition")),
                status=raw.get("status", "lost"), notes=raw.get("notes", ""),
            )
        self._cache: OrderedDict[str, Passage] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.RLock()
        self._count: int | None = None
        self._chapters: dict[str, str] | None = None

    # ------------------------------------------------------------ plumbing
    def _book_filter(self) -> tuple[str, list[str]]:
        if not self.exclude_books:
            return "", []
        marks = ",".join("?" * len(self.exclude_books))
        return f" AND p.book_id NOT IN ({marks})", sorted(self.exclude_books)

    def _row_to_passage(self, row: tuple) -> Passage:
        pid, book_id, edition_id, kind, locator, temporal, text, punctuation, extra = row
        loc = json.loads(locator)
        ex = json.loads(extra) if extra else {}
        variants = []
        for i, v in enumerate(ex.get("variants", [])):
            variants.append(VariantReading(
                id=v.get("id") or f"{pid}.v{i + 1}", passage_id=pid, start=v["start"], end=v["end"], base=v["base"],
                reading=v["reading"], witness=v["witness"], kind=VariantKind(v.get("kind", "variant_char")),
                witness_type=v.get("witness_type", "edition"), note=v.get("note", ""),
            ))
        return Passage(
            id=pid, book_id=book_id, edition_id=edition_id,
            locator=Locator(book_id=book_id, edition_id=edition_id, **{k: v for k, v in loc.items() if k not in ("book_id", "edition_id")}),
            text=text, temporal=_temporal(json.loads(temporal)), raw_text=ex.get("raw_text"),
            ocr_confidence=ex.get("ocr_confidence"), collation_status=CollationStatus(ex.get("collation_status", "unverified")),
            punctuation=punctuation or "none", variants=variants, kind=kind,
            tags=list(ex.get("tags", [])) + ([f"layer:{ex['layer']}"] if ex.get("layer") and ex["layer"] != "正文" else []),
            notes=ex.get("notes", ""), abridged=bool(ex.get("abridged", False)),
        )

    _COLS = "p.id, p.book_id, p.edition_id, p.kind, p.locator, p.temporal, p.text, p.punctuation, p.extra"

    def _fetch(self, ids: list[str]) -> dict[str, Passage]:
        out: dict[str, Passage] = {}
        missing = []
        with self._lock:
            for pid in ids:
                p = self._cache.get(pid)
                if p is not None:
                    self._cache.move_to_end(pid)
                    out[pid] = p
                else:
                    missing.append(pid)
        for i in range(0, len(missing), 500):
            chunk = missing[i: i + 500]
            marks = ",".join("?" * len(chunk))
            with self.store.lock:
                rows = self.store.db.execute(f"SELECT {self._COLS} FROM passages p WHERE p.id IN ({marks})", chunk).fetchall()
            for row in rows:
                if row[1] in self.exclude_books:
                    continue
                p = self._row_to_passage(row)
                out[p.id] = p
                with self._lock:
                    self._cache[p.id] = p
                    if len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
        return out

    # ----------------------------------------------------- Corpus interface
    def book(self, book_id: str) -> Book:
        return self.books[book_id]

    def passage(self, passage_id: str) -> Passage:
        got = self._fetch([passage_id])
        if passage_id not in got:
            raise KeyError(passage_id)
        return got[passage_id]

    def passages_by_id(self, ids: Iterable[str]) -> list[Passage]:
        ids = list(ids)
        got = self._fetch(ids)
        return [got[i] for i in ids if i in got]

    def has_passage(self, passage_id: str) -> bool:
        if passage_id in self._cache:
            return True
        with self.store.lock:
            row = self.store.db.execute("SELECT book_id FROM passages WHERE id=?", (passage_id,)).fetchone()
        return row is not None and row[0] not in self.exclude_books

    def passage_ids(self) -> list[str]:
        extra, params = self._book_filter()
        with self.store.lock:
            return [r[0] for r in self.store.db.execute(f"SELECT p.id FROM passages p WHERE 1{extra} ORDER BY p.year, p.id", params)]

    def __len__(self) -> int:
        if self._count is None:
            extra, params = self._book_filter()
            with self.store.lock:
                self._count = self.store.db.execute(f"SELECT COUNT(*) FROM passages p WHERE 1{extra}", params).fetchone()[0]
        return self._count

    def basis_for(self, passage: Passage, basis: str | None = None) -> str:
        if basis:
            return basis
        book = self.books.get(passage.book_id)
        return book.dating_basis if book else "composition"

    def year(self, passage: Passage, basis: str | None = None) -> float | None:
        return passage.temporal.year(self.basis_for(passage, basis))

    def year_range(self, passage: Passage, basis: str | None = None) -> YearRange | None:
        return passage.temporal.effective(self.basis_for(passage, basis))

    def iter_passages(self, *, book_ids: Iterable[str] | None = None, kinds: Iterable[str] | None = None,
                      after: float | None = None, before: float | None = None, batch: int = 2000) -> Iterator[Passage]:
        where, params = self._where(book_ids=book_ids, kinds=kinds, after=after, before=before)
        last = ""
        while True:
            with self.store.lock:
                rows = self.store.db.execute(
                    f"SELECT {self._COLS} FROM passages p WHERE p.id > ?{where} ORDER BY p.id LIMIT ?", [last, *params, batch]
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield self._row_to_passage(row)
            last = rows[-1][0]

    def _where(self, *, book_ids: Iterable[str] | None = None, kinds: Iterable[str] | None = None,
               after: float | None = None, before: float | None = None) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if book_ids is not None:
            ids = [b for b in book_ids]
            if not ids:
                return " AND 0", []
            clauses.append(f"p.book_id IN ({','.join('?' * len(ids))})")
            params.extend(ids)
        if kinds is not None:
            ks = list(kinds)
            clauses.append(f"p.kind IN ({','.join('?' * len(ks))})")
            params.extend(ks)
        if after is not None:
            clauses.append("p.year >= ?")
            params.append(after)
        if before is not None:
            clauses.append("p.year < ?")
            params.append(before)
        extra, bparams = self._book_filter()
        where = "".join(f" AND {c}" for c in clauses) + extra
        return where, params + bparams

    def passages(self, *, book_ids: Iterable[str] | None = None, tags: Iterable[str] | None = None,
                 kinds: Iterable[str] | None = None, after: float | None = None, before: float | None = None,
                 basis: str | None = None, limit: int | None = None) -> list[Passage]:
        where, params = self._where(book_ids=book_ids, kinds=kinds)
        sql = f"SELECT {self._COLS} FROM passages p WHERE 1{where} ORDER BY p.year, p.id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self.store.lock:
            rows = self.store.db.execute(sql, params).fetchall()
        tagset = set(tags) if tags is not None else None
        out = []
        for row in rows:
            p = self._row_to_passage(row)
            if tagset is not None and not tagset.intersection(p.tags):
                continue
            y = self.year(p, basis)
            if after is not None and (y is None or y < after):
                continue
            if before is not None and (y is None or y >= before):
                continue
            out.append(p)
        return out

    def count_range(self, *, after: float | None = None, before: float | None = None) -> int:
        where, params = self._where(after=after, before=before)
        with self.store.lock:
            return self.store.db.execute(f"SELECT COUNT(*) FROM passages p WHERE p.kind != 'toc'{where}", params).fetchone()[0]

    def book_passage_count(self, book_id: str) -> int:
        with self.store.lock:
            return self.store.db.execute("SELECT COUNT(*) FROM passages WHERE book_id=?", (book_id,)).fetchone()[0]

    def subset(self, passage_ids: Iterable[str]) -> Corpus:
        ps = {p.id: p for p in self.passages_by_id(passage_ids)}
        books = {bid: b for bid, b in self.books.items() if any(p.book_id == bid for p in ps.values())}
        return Corpus(books, ps, self.external, self.root)

    def without_books(self, book_ids: Iterable[str]) -> "StoreCorpus":
        view = StoreCorpus.__new__(StoreCorpus)
        view.__dict__.update(self.__dict__)
        view.exclude_books = self.exclude_books | set(book_ids)
        view.books = {k: v for k, v in self.books.items() if k not in view.exclude_books}
        view._cache = OrderedDict()
        view._count = None
        return view

    def witnesses(self, target: str) -> list[str]:
        """Books that transmit ``target`` — the book itself, or every witness of the work of that id
        (a generic reference to 《伤寒论》 resolves to 注解伤寒论 when only that witness is ingested)."""
        if target in self.books:
            return [target]
        hits = [b for b in self.books.values() if getattr(b, "work", None) == target]
        return [b.id for b in sorted(hits, key=lambda b: (b.composition.start if b.composition else 0, b.id))]

    def title_index(self) -> dict[str, tuple[str, str]]:
        index: dict[str, tuple[str, str]] = {}
        for book in self.books.values():
            for name in [book.title, *book.aliases]:
                index.setdefault(name, ("book", book.id))
        for work in self.external.values():
            for name in [work.title, *work.aliases]:
                index.setdefault(name, ("external", work.id))
        return index

    # works whose chapters are cited by name; punctuated editions put the names in 书名号 (《脉要精微论》)
    CHAPTER_WORKS = ("suwen", "lingshu", "taisu", "jiayi", "nanjing", "shanghanlun", "jinkui", "maijing")
    _CHAPTER = re.compile(r"^[〇○]?《?(.{2,12}?)篇?第[一二三四五六七八九十百]+》?$")

    def chapter_titles(self) -> dict[str, str]:
        """Normalised chapter names of the canonical classics (上古天真论, 九针十二原, 伤寒例 …) → the earliest book
        transmitting them, so that a citation of a chapter is not taken for the title of a lost book."""
        if self._chapters is None:
            out: dict[str, str] = {}
            books = sorted((b for b in self.books.values() if getattr(b, "work", None) in self.CHAPTER_WORKS),
                           key=lambda b: (b.composition.start if b.composition else 0, b.id))
            with self.store.lock:
                for book in books:
                    rows = self.store.db.execute(
                        "SELECT DISTINCT json_extract(locator, '$.volume'), json_extract(locator, '$.chapter'), "
                        "json_extract(locator, '$.section') FROM passages WHERE book_id=?", (book.id,)).fetchall()
                    for raw in (x for row in rows for x in row if x):
                        m = self._CHAPTER.match(raw.strip())
                        if m:
                            out.setdefault(self.normalize(m.group(1)), book.id)
            self._chapters = out
        return self._chapters

    def stats(self, periods: Any = None) -> dict[str, Any]:
        extra, params = self._book_filter()
        with self.store.lock:
            by_book = dict(self.store.db.execute(
                f"SELECT p.book_id, COUNT(*) FROM passages p WHERE 1{extra} GROUP BY p.book_id ORDER BY p.book_id", params).fetchall())
            chars = self.store.db.execute(f"SELECT COALESCE(SUM(LENGTH(p.text)), 0) FROM passages p WHERE 1{extra}", params).fetchone()[0]
            years = self.store.db.execute(f"SELECT p.year, COUNT(*) FROM passages p WHERE 1{extra} GROUP BY p.year", params).fetchall()
        by_period: dict[str, int] = {}
        if periods is not None:
            for y, n in years:
                pid = periods.period_of(y)
                if pid:
                    by_period[pid] = by_period.get(pid, 0) + n
        return {
            "books": len(self.books),
            "passages": sum(by_book.values()),
            "characters": chars,
            "by_book": by_book,
            "by_period": {k: by_period[k] for k in (periods.ids() if periods else []) if k in by_period},
            "external_works": sorted(self.external),
            "sources": dict(sorted({s: sum(1 for b in self.sources.values() if b == s) for s in set(self.sources.values())}.items())),
            "index_current": self.fingerprint_ok,
        }

    # -------------------------------------------------------------- search
    def normalized(self, passage: Passage) -> str:
        return self.normalize(passage.text)

    def _match(self, query: str, where: str, params: list[Any], limit: int | None, ranked: bool) -> list[tuple[str, float, float]]:
        """(passage id, score, year) for an FTS query; ranked by BM25 when ``ranked``."""
        order = " ORDER BY rank" if ranked else ""
        lim = f" LIMIT {int(limit)}" if limit else ""
        score = "bm25(grams)" if ranked else "0"
        sql = (f"SELECT p.id, {score}, p.year FROM grams JOIN passages p ON p.rid = grams.rowid "
               f"WHERE grams MATCH ?{where}{order}{lim}")
        with self.store.lock:
            try:
                rows = self.store.db.execute(sql, [query, *params]).fetchall()
            except sqlite3.OperationalError:
                return []
        return [(r[0], -float(r[1]), 9999.0 if r[2] is None else float(r[2])) for r in rows]

    def contains(self, surface: str, *, after: float | None = None, before: float | None = None,
                 book_ids: Iterable[str] | None = None, limit: int | None = None, verify: bool = True) -> list[str]:
        """Ids of passages whose normalised text contains ``surface`` (normalised), in (year, id) order."""
        norm = self.normalize(surface)
        query = fts_phrase(norm)
        if query is None:
            return []
        where, params = self._where(book_ids=book_ids, after=after, before=before)
        rows = sorted(self._match(query, where, params, None, False), key=lambda r: (r[2], r[0]))
        hits = [pid for pid, _, _ in rows]
        if verify:
            out = []
            for i in range(0, len(hits), 2000):
                chunk = hits[i: i + 2000]
                got = self._fetch(chunk)
                out.extend(pid for pid in chunk if pid in got and norm in self.normalize(got[pid].text))
                if limit and len(out) >= limit:
                    break
            hits = out
        return hits[:limit] if limit else hits

    def count(self, surface: str, *, after: float | None = None, before: float | None = None) -> int:
        query = fts_phrase(self.normalize(surface))
        if query is None:
            return 0
        where, params = self._where(after=after, before=before)
        sql = f"SELECT COUNT(*) FROM grams JOIN passages p ON p.rid = grams.rowid WHERE grams MATCH ?{where}"
        with self.store.lock:
            try:
                return self.store.db.execute(sql, [query, *params]).fetchone()[0]
            except sqlite3.OperationalError:
                return 0

    def search(self, surfaces: Iterable[str], *, limit: int = 200, after: float | None = None, before: float | None = None,
               book_ids: Iterable[str] | None = None) -> list[tuple[str, float]]:
        """BM25-ranked passages matching any of the surfaces (OR query over bigram phrases)."""
        parts = [q for q in (fts_phrase(self.normalize(s)) for s in surfaces if s) if q]
        if not parts:
            return []
        query = " OR ".join(dict.fromkeys(parts))
        where, params = self._where(book_ids=book_ids, after=after, before=before)
        return [(pid, score) for pid, score, _ in self._match(query, where, params, limit, True)]

    def near(self, left: Iterable[str], right: Iterable[str], *, distance: int = 24, after: float | None = None,
             before: float | None = None, limit: int | None = None) -> list[str]:
        """Passages where a left surface and a right surface occur within ``distance`` characters."""
        lq = [q for q in (fts_phrase(self.normalize(s)) for s in left if s) if q]
        rq = [q for q in (fts_phrase(self.normalize(s)) for s in right if s) if q]
        if not lq or not rq:
            return []
        clauses = [f"NEAR({a} {b}, {int(distance)})" for a in dict.fromkeys(lq) for b in dict.fromkeys(rq)]
        where, params = self._where(after=after, before=before)
        ids: list[str] = []
        for i in range(0, len(clauses), 40):
            ids.extend(pid for pid, _, _ in self._match(" OR ".join(clauses[i: i + 40]), where, params, None, False))
        return sorted(set(ids))[:limit] if limit else sorted(set(ids))

    def document_frequency(self, gram_list: Iterable[str]) -> dict[str, int]:
        """Number of passages containing each normalised bigram (from the FTS vocabulary)."""
        with self.store.lock:
            self.store.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.grams_vocab USING fts5vocab(main, grams, row)")
            out = {}
            for g in gram_list:
                row = self.store.db.execute("SELECT doc FROM temp.grams_vocab WHERE term=?", (g,)).fetchone()
                out[g] = row[0] if row else 0
        return out


def corpus_contains(corpus: Any, surface: str, normalize: Callable[[str], str], *, after: float | None = None,
                    before: float | None = None, allowed: set[str] | None = None) -> list[str]:
    """Passage ids containing a surface, for either corpus kind (index-backed when available)."""
    if getattr(corpus, "large", False):
        hits = corpus.contains(surface, after=after, before=before)
    else:
        norm = normalize(surface)
        hits = [p.id for p in corpus.passages(after=after, before=before) if norm in normalize(p.text)]
    return [h for h in hits if allowed is None or h in allowed]
