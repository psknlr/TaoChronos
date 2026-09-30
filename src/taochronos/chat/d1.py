"""The full corpus in Cloudflare D1 — the site's backup when it has no container (docs/adr/0017-d1-backup.md).

On the Workers Free plan there are no Containers, so the site's own Worker answers the page's API (``/api/info``,
``/api/catalog``, ``/api/call``, ``/api/passage``) itself, from D1, with the tools rewritten in JavaScript
(``cloud/site/src/backup/``).  A Worker has 10 ms of CPU per request: the work is done in SQL, where it costs none,
or ahead of time.  This module turns the store the site may publish (``taochronos web store``: ``WEB_SOURCES`` only,
never ``NEVER_PACKED``) into the databases and imports them, a daily slice at a time (D1 Free: 100,000 rows written a
day, 500 MB a database):

* **chunks** — the passages of one book with one temporal context (a book's layers are often dated apart and
  alternate), in reading order, at most ``CHUNK_PASSAGES`` passages and ``CHUNK_CHARS`` characters: one row each,
  numbered (``cid``) in the order of their year, so that a time bound is a range of numbers.  ``body`` holds the
  passages as the tools cite them, ``norm`` their normalised text one character a token (the page's normaliser,
  ported to JavaScript), which the per-passage filters read with ``instr``;
* **fts** — FTS5 over the chunks' ``norm`` (the ascii tokenizer: every character is a token, punctuation and the
  passages' ends break a phrase), contentless and without document sizes, built from the chunks in SQL in a few
  large statements (a segment each) and optimized once: an index that costs a row per chunk;
* **books**, **seqmap**, **lex**, **results**, **meta** — in database 0: the books with their chunk maps and, for a
  book whose passages fall into several temporal groups, which group each passage is in (a passage id finds its
  chunk without an index), the lexicon by first character, the precomputed results of the tools a Worker cannot
  compute (``results``), the corpus statistics, and ``complete`` last.

Every statement is one INSERT, at most ``MAX_SQL_BYTES`` of SQL and values and ``MAX_PARAMS`` parameters, and a
statement is atomic: where the import has got to is read from the databases themselves (the last chunk, the last
book …, and ``progress`` for the index), so an interrupted run resumes where it stopped, without duplicates.

* ``python -m taochronos.chat.d1 plan <store>`` — the databases, their sizes and the rows each step writes;
* ``python -m taochronos.chat.d1 import <store> --api|--sqlite DIR|--bridge CMD [--budget N] [--precompute]`` — import
  the next slice (the daily run, ``.github/workflows/d1.yml``; the store may be the compressed one, with ``--manifest``);
* ``python -m taochronos.chat.d1 version`` / ``status --api`` — the version this checkout wants; what the databases hold;
* ``python -m taochronos.chat.d1 tables`` — write the JavaScript module of the normaliser's tables, the periods, the
  catalog … (``cloud/site/src/backup/tables.js``);
* ``python -m taochronos.chat.d1 fixture <dir>`` — a small store exported as the Node tests read it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA = 1
PREFIX = "taochronos-d1"  # the databases: taochronos-d1-0, -1, …; bound to the site's Worker as D1_0, D1_1, …
MAX_SQL_BYTES = 100_000  # D1: a statement's SQL (here: its SQL and its values together, to be safe)
MAX_PARAMS = 100  # D1: bound parameters per statement
STATEMENT_BYTES = 90_000  # what a statement is filled to (a margin under MAX_SQL_BYTES)
CHUNK_PASSAGES = 64
CHUNK_CHARS = 4000
DB_BYTES = 320_000_000  # what one database is filled to (D1 Free: 500 MB a database)
DB0_RESERVE = 80_000_000  # database 0's room for the books, the lexicon, the precomputed results and the meta
FTS_CHARS = 6_000_000  # characters indexed by one statement (one index segment; well inside D1's 30 s)
DAY_BUDGET = 90_000  # rows written a day, of D1 Free's 100,000
USE_RECORD_ROWS = 5_000  # the day's use is recorded at least this often (rows): a killed run under-counts it by less
BREAK = "zx"  # the token in place of ASCII punctuation, space and control characters (no phrase runs across them)
END = "zq"  # the token between two passages of a chunk
FTS_CONFIG = (("pgsz", 64000), ("automerge", 0), ("crisismerge", 1999), ("hashsize", 64 * 1024 * 1024))


# ------------------------------------------------------------------ the text as the index reads it
def fts_form(norm: str) -> str:
    """A normalised text one character a token, for FTS5's ascii tokenizer (every non-ASCII character is a token
    character, ASCII punctuation separates): ASCII letters and digits and every other character stand for
    themselves, ASCII punctuation, spaces and control characters become ``BREAK``, so that — as in the store's own
    index (``store.grams``) — no phrase matches across them.  ``instr`` on this form with a needle in this form is a
    substring test on the normalised text."""
    return " ".join(ch if (ord(ch) >= 128 or ch.isalnum()) else BREAK for ch in norm)


def fts_phrase(norm_surface: str) -> str | None:
    """The FTS5 phrase for a normalised surface: its Han characters as one phrase (``store.fts_phrase``: a surface is
    looked up by its Han characters; one character is a token of its own here, not a prefix)."""
    from ..plugins.classics.store import is_han

    chars = [c for c in norm_surface if is_han(c)]
    return '"' + " ".join(chars) + '"' if chars else None


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _size(value: Any) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    return len(str(value))


# ------------------------------------------------------------------ the plan
@dataclass
class Chunk:
    cid: int
    book: str
    group: int  # the book's temporal context, numbered in order of first appearance
    rank0: int  # the position of its first passage among the passages of that context
    seqs: list[int]
    year: float | None
    chars: int
    db: int = 0


@dataclass
class Batch:
    """One statement: where it goes, what it writes, and how the import knows it was done."""

    db: int
    step: str  # schema | chunks | fts | optimize | books | lex | results | meta
    key: Any  # the progress it leaves: the last cid, the last key, the range's end …
    sql: str
    params: list[Any] = field(default_factory=list)
    rows: int = 0  # rows written as D1 reports them (a row per table row, per indexed document, per config value)
    bound: int = 0  # at most, should D1 also count the rows of FTS5's own tables (the index's pages)

    def __post_init__(self) -> None:
        self.bound = max(self.bound, self.rows)

    @property
    def bytes(self) -> int:
        return len(self.sql.encode("utf-8")) + sum(_size(p) for p in self.params)


class Plan:
    """The databases made from a store: chunks, their order and the databases they go to, and every statement."""

    def __init__(self, store: str | Path, normalize: Callable[[str], str], *, version: str | None = None, normalizer: str = "",
                 lexicon: Any = None, periods: Any = None, canon: list[dict[str, Any]] | None = None, results: Any = None,
                 db_bytes: int = DB_BYTES, db0_reserve: int = DB0_RESERVE, chunk_passages: int = CHUNK_PASSAGES,
                 chunk_chars: int = CHUNK_CHARS) -> None:
        from ..plugins.classics.webcorpus import NEVER_PACKED, WEB_SOURCES

        self.path = Path(store)
        self.normalize = normalize
        self.lexicon = lexicon
        self.periods = periods
        self.canon = canon or []
        self._results = results
        self.chunk_passages, self.chunk_chars = chunk_passages, chunk_chars
        self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.meta = dict(self.db.execute("SELECT key, value FROM meta").fetchall())
        self.books: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, str] = {}
        for bid, source, data in self.db.execute("SELECT id, source, data FROM books ORDER BY id"):
            # what the site may carry, and never what may not be passed on — whatever store this is given
            if source in NEVER_PACKED or source not in WEB_SOURCES:
                continue
            self.books[bid] = json.loads(data)
            self.sources[bid] = source
        # the store (cloud/store.json's sha256), the normaliser the index is built with, and the layout: another of any of
        # them is imported afresh
        self.normalizer = normalizer or self.meta.get("normalizer", "")
        self.version = f"{(version or self.fingerprint())[:12]}-{self.normalizer[:8]}-s{SCHEMA}"
        self._chunk()
        self._place(db_bytes, db0_reserve)

    def fingerprint(self) -> str:
        """The store's identity when it does not say its own (the sha256 of cloud/store.json is used in CI)."""
        h = hashlib.sha256()
        h.update(self.meta.get("counted", "").encode("utf-8"))
        h.update(self.meta.get("normalizer", "").encode("utf-8"))
        return h.hexdigest()[:12]

    # -------------------------------------------------------------- chunks
    def _chunk(self) -> None:
        """Group each book's passages by temporal context (in order of first appearance), cut each group into chunks
        of consecutive passages, and number the chunks by (year, book, context, position)."""
        chunks: list[Chunk] = []
        self.groups: dict[str, list[str]] = {}  # book → the temporal contexts (JSON) of its groups
        # book → per seq, the group's number as a character ("-" where no passage has that seq): for a book of several
        # groups, or with gaps in its numbering (a store the site publishes has none)
        self.group_of: dict[str, str] = {}
        self.span: dict[str, int] = {}  # book → its last seq + 1
        self.passages = 0
        self.characters = 0
        years: dict[float | None, int] = defaultdict(int)
        rows = self.db.execute("SELECT book_id, seq, temporal, year, length(text) FROM passages ORDER BY book_id, seq")
        current = None
        order: dict[str, int] = {}
        open_chunk: dict[int, Chunk] = {}
        marks: list[str] = []
        expect = 0
        gaps = False

        def close_book() -> None:
            if current is not None:
                self.groups[current] = list(order)
                self.span[current] = expect
                if len(order) > 1 or gaps:
                    self.group_of[current] = "".join(marks)

        for bid, seq, temporal, year, length in rows:
            if bid not in self.books:
                continue
            if bid != current:
                close_book()
                current, order, open_chunk, marks, expect, gaps = bid, {}, {}, [], 0, False
            if seq < expect:
                raise ValueError(f"{bid}: two passages numbered {seq}")
            if seq > expect:
                marks.extend("-" * (seq - expect))
                gaps = True
            expect = seq + 1
            g = order.setdefault(temporal, len(order))
            if g >= 62:
                raise ValueError(f"{bid}: more than 62 temporal contexts")
            marks.append(_mark(g))
            c = open_chunk.get(g)
            if c is None or len(c.seqs) >= self.chunk_passages or c.chars + length > self.chunk_chars:
                rank0 = (c.rank0 + len(c.seqs)) if c is not None else 0
                c = Chunk(cid=0, book=bid, group=g, rank0=rank0, seqs=[], year=year, chars=0)
                open_chunk[g] = c
                chunks.append(c)
            c.seqs.append(seq)
            c.chars += length
            self.passages += 1
            self.characters += length
            years[year] += 1
        close_book()
        chunks.sort(key=lambda c: (c.year is None, c.year if c.year is not None else 0.0, c.book, c.group, c.rank0))
        for i, c in enumerate(chunks, 1):
            c.cid = i
        self.chunks = chunks
        self.years = dict(years)

    def _place(self, db_bytes: int, reserve: int) -> None:
        """Consecutive chunks to each database, up to ``db_bytes`` each: a chunk takes ~11.7 bytes a character on disk
        (its body ~4, ``norm`` ~4, the index ~2, and SQLite's pages; measured on the full store); database 0 keeps
        ``DB0_RESERVE`` for the tables only it has (books, lexicon, results, meta)."""
        per_char = 11.7
        self.ranges: list[tuple[int, int]] = []
        start, size = 1, float(reserve)
        for c in self.chunks:
            weight = c.chars * per_char + 20 * len(c.seqs)
            if size + weight > db_bytes and c.cid > start:
                self.ranges.append((start, c.cid - 1))
                start, size = c.cid, 0.0
            size += weight
        if self.chunks:
            self.ranges.append((start, self.chunks[-1].cid))
        for k, (lo, hi) in enumerate(self.ranges):
            for c in self.chunks[lo - 1:hi]:
                c.db = k

    @property
    def databases(self) -> int:
        return max(1, len(self.ranges))

    def names(self) -> list[str]:
        return [f"{PREFIX}-{k}" for k in range(self.databases)]

    # -------------------------------------------------------------- one chunk
    def rows(self, c: Chunk) -> tuple[str, str]:
        """A chunk's ``body`` and ``norm``: {"T": temporal, "L": [[volume, chapter, section] …], "Y": [layers …], "p":
        [{"q": seq, "t": text, "l": locator, "y": layer, "k": kind, "m": the id's middle part, "g": page, "n": line,
        "u": image, "x": the rest of extra} …]} (defaults left out), and the passages' normalised text in the
        index's form."""
        marks = ",".join("?" * len(c.seqs))
        got = self.db.execute(f"SELECT id, seq, kind, layer, locator, temporal, text, extra FROM passages "
                              f"WHERE book_id=? AND seq IN ({marks}) ORDER BY seq", [c.book, *c.seqs]).fetchall()
        if [r[1] for r in got] != c.seqs:
            raise ValueError(f"chunk {c.cid}: passages missing from {c.book}")
        locs: dict[tuple, int] = {}
        layers: dict[str, int] = {}
        temporal = None
        passages, norms = [], []
        for pid, seq, kind, layer, locator, tem, text, extra in got:
            temporal = temporal or tem
            loc = json.loads(locator)
            key = (loc.get("volume"), loc.get("chapter"), loc.get("section"))
            p: dict[str, Any] = {"q": seq, "t": text}
            li = locs.setdefault(key, len(locs))
            if li:
                p["l"] = li
            yi = layers.setdefault(layer or "", len(layers))
            if yi:
                p["y"] = yi
            if kind != "text":
                p["k"] = kind
            rest = pid[len(c.book) + 1:]
            if "." in rest:
                p["m"] = rest.rsplit(".", 1)[0]
            for src, dst in (("page", "g"), ("line", "n"), ("image_uri", "u")):
                if loc.get(src) is not None:
                    p[dst] = loc[src]
            if loc.get("precision", "exact") != "exact":
                p["r"] = loc["precision"]
            ex = {k: v for k, v in json.loads(extra or "{}").items() if k not in ("layer", "source_file")}
            if ex:
                p["x"] = ex
            passages.append(p)
            norms.append(fts_form(self.normalize(text)))
        body = {"T": json.loads(temporal), "L": [list(k) for k in locs], "Y": list(layers), "p": passages}
        return _dump(body), _dump(norms)

    # -------------------------------------------------------------- the books' records
    def book_row(self, bid: str) -> tuple[str, str, str, str]:
        """(id, card, data, map): the card the tools cite a book by, its whole record, and where its passages are —
        {"C": per temporal group, [[rank of the first passage in the group, cid] …]}.  A book of several groups also
        has ``seqmap`` rows: which group each passage is in."""
        from ..plugins.classics.webcorpus import site_record

        data = site_record(self.books[bid], self.sources[bid])
        comp = data.get("composition")
        card = {"title": data.get("title") or bid, "dynasty": data.get("dynasty") or "", "category": data.get("category") or "",
                "authors": list(data.get("authors") or []), "aliases": list(data.get("aliases") or []),
                "composition": comp, "author_life": data.get("author_life"), "dating_basis": data.get("dating_basis") or "composition",
                "attribution": data.get("attribution") or "traditional", "school": data.get("school"),
                "work": data.get("work"), "source": self.sources[bid],
                "edition": (data.get("editions") or [{}])[0].get("id"),
                "quality": float((data.get("editions") or [{}])[0].get("quality", 0.5)),
                "punctuation": self._punctuation.get(bid, "none"), "passages": self._counts.get(bid, 0),
                "span": self.span.get(bid, 0)}
        groups: list[list[list[int]]] = [[] for _ in self.groups.get(bid, [])]
        for c in self._by_book.get(bid, []):
            groups[c.group].append([c.rank0, c.cid])
        where: dict[str, Any] = {"C": groups}
        if bid in self.group_of:
            where["S"] = 1  # read the passage's group from seqmap
        return bid, _dump(card), _dump(data), _dump(where)

    def seqmap_rows(self) -> Iterator[list[Any]]:
        """For each book of several temporal groups (or with gaps in its numbering), in parts of ``SEQMAP_PART`` seqs:
        the group of each passage (one character each: 0–9, a–z, A–Z; "-" for no passage) and how many passages of
        each group come before the part — with them a passage's rank in its group is counted without reading the
        parts before it."""
        for bid in sorted(self.group_of):
            marks = self.group_of[bid]
            before = [0] * len(self.groups[bid])
            for part in range(0, len(marks), SEQMAP_PART):
                piece = marks[part: part + SEQMAP_PART]
                yield [bid, part // SEQMAP_PART, piece, _dump(before)]
                for ch in piece:
                    if ch != "-":
                        before[_MARKS.index(ch)] += 1

    def _book_index(self) -> None:
        if hasattr(self, "_by_book"):
            return
        self._by_book: dict[str, list[Chunk]] = defaultdict(list)
        for c in self.chunks:
            self._by_book[c.book].append(c)
        for cs in self._by_book.values():
            cs.sort(key=lambda c: (c.group, c.rank0))
        self._counts = dict(self.db.execute("SELECT book_id, COUNT(*) FROM passages GROUP BY book_id").fetchall())
        self._punctuation = dict(self.db.execute("SELECT book_id, MAX(punctuation) FROM passages GROUP BY book_id").fetchall())

    # -------------------------------------------------------------- the lexicon
    def lex_rows(self) -> list[tuple[str, str]]:
        """The lexicon by first character: {surface: [entry …]} with each surface's entries in lookup order (the
        category ranking of ``Lexicon.lookup``) and the synonym kind the surface has for it.  An entry is found by its id
        in the bucket of the id's term part (formula:桂枝汤 → 桂); one whose id names another term than its own (pulse:浮,
        whose term is 脉浮) is also there, as "@<id>"."""
        if self.lexicon is None:
            return []
        lex = self.lexicon
        buckets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
        for surface in sorted(lex._by_surface):
            buckets[surface[0]][surface] = [{**lex_entry(e), **({"sk": kind} if kind else {})} for e, kind in lex.lookup(surface)]
        for e in sorted(lex.entries.values(), key=lambda e: e.term_id):
            named = e.term_id.split(":", 1)[1] if ":" in e.term_id else ""
            if named and named != e.term:
                buckets[named[0]][f"@{e.term_id}"] = [lex_entry(e)]
        return [(k, _dump(buckets[k])) for k in sorted(buckets)]

    # -------------------------------------------------------------- statistics
    def stats(self) -> dict[str, Any]:
        """What ``/api/info`` says of the corpus, and what the Worker needs to find things: the databases' chunk ranges,
        the first chunk of each year, the works held."""
        by_period: dict[str, int] = {}
        if self.periods is not None:
            for y, n in self.years.items():
                pid = self.periods.period_of(y)
                if pid:
                    by_period[pid] = by_period.get(pid, 0) + n
            by_period = {k: by_period[k] for k in self.periods.ids() if k in by_period}
        firsts: list[list[Any]] = []
        null_from = None
        for c in self.chunks:
            if c.year is None:
                null_from = null_from or c.cid
            elif not firsts or firsts[-1][0] != c.year:
                firsts.append([c.year, c.cid])
        works = self.works()
        held = sum(1 for w in self.canon if w.get("work") in set(works))
        return {"version": self.version, "schema": SCHEMA, "books": len(self.books), "passages": self.passages,
                "characters": self.characters, "by_period": by_period, "chunks": len(self.chunks),
                "databases": self.databases, "ranges": [list(r) for r in self.ranges], "years": firsts,
                "null_years_from": null_from, "canon": {"listed": len(self.canon), "held": held},
                "normalizer": self.normalizer, "sources": dict(sorted(Counter(self.sources.values()).items()))}

    def works(self) -> list[str]:
        """The works this corpus holds a witness of (and its books' own ids): classics.canon's in_this_corpus."""
        return sorted({(b.get("work") or bid) for bid, b in self.books.items()} | set(self.books))

    # -------------------------------------------------------------- statements
    def schema(self, db: int) -> list[Batch]:
        """The tables of one database (idempotent), then its version; database 0 also has the meta, books, lexicon
        and results."""
        # a table, view or trigger is a row of the schema (D1 reports two for a table); a setting of the index, a row
        out = [Batch(db, "schema", 0, sql, rows=1 if sql.startswith("INSERT") else 2, bound=2 if sql.startswith("INSERT") else 4)
               for sql in schema_sql(db)]
        out.append(Batch(db, "schema", 0, "INSERT OR IGNORE INTO progress(k, v) VALUES ('version', ?)", [self.version], 1))
        return out

    def batches(self, db: int) -> Iterator[Batch]:
        """Every statement of one database, in order (after its schema): its chunks, its index in segments, the
        index optimized; for database 0 after all the others' (``order``): the books, the lexicon, the results and the
        meta, ``complete`` last."""
        self._book_index()
        lo, hi = self.ranges[db] if self.ranges else (1, 0)
        rows: list[list[Any]] = []
        size = 0
        sql_head = "INSERT INTO chunks(cid, book, g, r0, n, year, body, norm) VALUES "
        for c in self.chunks[lo - 1:hi]:
            body, norm = self.rows(c)
            row = [c.cid, c.book, c.group, c.rank0, len(c.seqs), c.year, body, norm]
            weight = sum(_size(v) for v in row) + 20
            if rows and (size + weight > STATEMENT_BYTES or (len(rows) + 1) * len(row) > MAX_PARAMS):
                yield _insert(db, "chunks", sql_head, rows, key=rows[-1][0])
                rows, size = [], 0
            if weight + len(sql_head) > MAX_SQL_BYTES:
                raise ValueError(f"chunk {c.cid} ({c.book}) is {weight:,} bytes: more than one statement may hold")
            rows.append(row)
            size += weight
        if rows:
            yield _insert(db, "chunks", sql_head, rows, key=rows[-1][0])
        # the index, a segment per statement: each indexed chunk is a row written, and the range's end
        start, chars, total = lo, 0, 0
        for c in self.chunks[lo - 1:hi]:
            if chars and chars + c.chars > FTS_CHARS:
                yield Batch(db, "fts", c.cid - 1, FTS_LOAD, [start, c.cid - 1], rows=(c.cid - start) + 1,
                            bound=(c.cid - start) + 1 + index_pages(chars))
                start, chars = c.cid, 0
            chars += c.chars
            total += c.chars
        if hi >= lo:
            yield Batch(db, "fts", hi, FTS_LOAD, [start, hi], rows=(hi - start + 1) + 1, bound=(hi - start + 2) + index_pages(chars))
            # optimizing rewrites every page of the index once (and deletes the segments it merges)
            yield Batch(db, "optimize", 1, "INSERT INTO fts_optimize(v) VALUES (1)", [], rows=2, bound=2 + 2 * index_pages(total))

    def tail(self, *, results_start: Callable[[str], str | None] = lambda plan: None, deadline: Callable[[], bool] = lambda: False,
             count: Callable[[], dict[str, int]] | None = None) -> Iterator[Batch]:
        """Database 0's tables, after every database's chunks: books, their seqmaps, lexicon, the precomputed results
        (computed as their statements are due, until ``deadline``; ``results_start(plan)`` — the key list's digest —
        says after which key they resume), meta (``complete`` last: with ``count``, the precomputed results the
        databases hold, by tool)."""
        from .d1results import pack

        self._book_index()
        rows = [list(self.book_row(bid)) for bid in sorted(self.books)]
        yield from _fill(0, "books", "INSERT INTO books(id, card, data, map) VALUES ", rows)
        yield from _fill(0, "seqmap", "INSERT INTO seqmap(book, part, marks, counts) VALUES ", list(self.seqmap_rows()),
                         key=lambda r: f"{r[0]}\t{r[1]:06d}")
        yield from _fill(0, "lex", "INSERT INTO lex(k, v) VALUES ", [list(r) for r in self.lex_rows()])
        if self._results is not None:
            after = results_start(self._results.digest())
            rows_iter = ([f"{tool}\t{key}", pack(value)] for tool, key, value in self._results.rows(after, deadline=deadline))
            yield from _fill(0, "results", "INSERT INTO results(k, v) VALUES ", rows_iter)
            if deadline():
                return
        yield Batch(0, "meta", "works", "INSERT INTO meta(k, v) VALUES (?, ?)", ["works", _dump(self.works())], 1)
        stats = self.stats()
        stats["precomputed"] = count() if count is not None else {}
        yield Batch(0, "meta", "stats", "INSERT INTO meta(k, v) VALUES (?, ?)", ["stats", _dump(stats)], 1)
        yield Batch(0, "meta", "complete", "INSERT INTO meta(k, v) VALUES (?, ?)", ["complete", self.version], 1)

    def order(self, **tail: Any) -> Iterator[Batch]:
        """Every statement of every database, in the order they are imported (``tail``: what ``tail`` takes)."""
        for db in range(self.databases):
            yield from self.schema(db)
            yield from self.batches(db)
        yield from self.tail(**tail)


FTS_LOAD = "INSERT INTO fts_load(lo, hi) VALUES (?, ?)"
INDEX_BYTES_PER_CHAR = 2.0  # the index is ~1.85 bytes a character indexed (measured on the full store)
SEQMAP_PART = 30_000  # passages a seqmap row covers (a character each)
_MARKS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def index_pages(chars: int) -> int:
    """The rows FTS5's own tables get for ``chars`` characters indexed: 64 KB pages, each with its entry in the page
    index, and the segment's structure — what D1 would count should it count them."""
    pages = int(chars * INDEX_BYTES_PER_CHAR / FTS_CONFIG[0][1]) + 1
    return 2 * pages + 4


def _mark(g: int) -> str:
    return _MARKS[g]


def lex_entry(e: Any) -> dict[str, Any]:
    """A lexicon entry, its defaults left out (``domain.LexEntry``)."""
    out: dict[str, Any] = {"id": e.term_id, "term": e.term, "cat": e.category}
    for key, value in (("aliases", e.aliases), ("synonyms", e.synonyms), ("synonym_notes", e.synonym_notes),
                       ("polarity", e.polarity), ("origin", e.origin), ("nature", e.nature), ("components", e.components),
                       ("broader", e.broader), ("related", e.related), ("weak", e.weak), ("kind", e.kind), ("school", e.school),
                       ("name_herbs", e.name_herbs), ("name_complete", e.name_complete), ("name_etiology", e.name_etiology)):
        if value not in (None, False, [], {}, ""):
            out[key] = value
    return out


def _insert(db: int, step: str, head: str, rows: list[list[Any]], *, key: Any) -> Batch:
    marks = ", ".join("(" + ", ".join("?" * len(r)) + ")" for r in rows)
    return Batch(db, step, key, head + marks, [v for r in rows for v in r], rows=len(rows))


def _fill(db: int, step: str, head: str, rows: list[list[Any]], key: Callable[[list[Any]], Any] = lambda r: r[0]) -> Iterator[Batch]:
    """Rows (in key order) into statements within D1's limits; each statement's key is its last row's."""
    batch: list[list[Any]] = []
    size = 0
    for row in rows:
        weight = sum(_size(v) for v in row) + 12
        if weight + len(head) > MAX_SQL_BYTES:
            raise ValueError(f"{step} {row[0]!r} is {weight:,} bytes: more than one statement may hold")
        if batch and (size + weight > STATEMENT_BYTES or (len(batch) + 1) * len(row) > MAX_PARAMS):
            yield _insert(db, step, head, batch, key=key(batch[-1]))
            batch, size = [], 0
        batch.append(row)
        size += weight
    if batch:
        yield _insert(db, step, head, batch, key=key(batch[-1]))


def schema_sql(db: int) -> list[str]:
    """The tables of database ``db`` (every statement idempotent)."""
    out = [
        "CREATE TABLE IF NOT EXISTS progress(k TEXT PRIMARY KEY, v) WITHOUT ROWID",
        "CREATE TABLE IF NOT EXISTS chunks(cid INTEGER PRIMARY KEY, book TEXT NOT NULL, g INTEGER NOT NULL, r0 INTEGER NOT NULL, "
        "n INTEGER NOT NULL, year REAL, body TEXT NOT NULL, norm TEXT NOT NULL)",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(t, content='', columnsize=0, detail=full, tokenize='ascii')",
        *[f"INSERT INTO fts(fts, rank) VALUES ('{k}', {v})" for k, v in FTS_CONFIG],
        # the index is built from the chunks in SQL: a range of chunks a statement, its end recorded with it
        "CREATE VIEW IF NOT EXISTS fts_load(lo, hi) AS SELECT 0, 0 WHERE 0",
        # (a view's columns have no type: the bounds are cast, whether they come as numbers or as text)
        f"CREATE TRIGGER IF NOT EXISTS fts_load INSTEAD OF INSERT ON fts_load BEGIN "
        f"INSERT INTO fts(rowid, t) SELECT cid, replace(norm, '\",\"', ' {END} ') FROM chunks "
        f"WHERE cid BETWEEN CAST(NEW.lo AS INTEGER) AND CAST(NEW.hi AS INTEGER) ORDER BY cid; "
        f"INSERT OR REPLACE INTO progress(k, v) VALUES ('fts', CAST(NEW.hi AS INTEGER)); END",
        "CREATE VIEW IF NOT EXISTS fts_optimize(v) AS SELECT 0 WHERE 0",
        "CREATE TRIGGER IF NOT EXISTS fts_optimize INSTEAD OF INSERT ON fts_optimize BEGIN "
        "INSERT INTO fts(fts) VALUES ('optimize'); INSERT OR REPLACE INTO progress(k, v) VALUES ('optimized', CAST(NEW.v AS INTEGER)); END",
    ]
    if db == 0:
        out += [
            "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID",
            "CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, card TEXT NOT NULL, data TEXT NOT NULL, map TEXT NOT NULL) WITHOUT ROWID",
            "CREATE TABLE IF NOT EXISTS seqmap(book TEXT NOT NULL, part INTEGER NOT NULL, marks TEXT NOT NULL, counts TEXT NOT NULL, "
            "PRIMARY KEY(book, part)) WITHOUT ROWID",
            "CREATE TABLE IF NOT EXISTS lex(k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID",
            "CREATE TABLE IF NOT EXISTS results(k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID",
        ]
    return out


# ------------------------------------------------------------------ where the statements go
class TargetError(RuntimeError):
    """A statement failed.  ``transient``: it may succeed if sent again (after checking it was not applied);
    ``exhausted``: the account's daily allowance is used up (the next run resumes)."""

    def __init__(self, message: str, *, transient: bool = False, exhausted: bool = False) -> None:
        super().__init__(message)
        self.transient = transient
        self.exhausted = exhausted


class SqliteTarget:
    """Local SQLite files, one per database (``db-<k>.sqlite``): tests, the fixture, and planning.  What a statement
    writes is counted as SQLite counts it (``total_changes``: table rows, the index documents *and* the FTS5 shadow
    rows, which D1 does not report) — the upper bound the daily budget is checked against."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._dbs: dict[int, sqlite3.Connection] = {}

    def path(self, db: int) -> Path:
        return self.root / f"db-{db}.sqlite"

    def _db(self, db: int) -> sqlite3.Connection:
        if db not in self._dbs:
            con = sqlite3.connect(self.path(db), isolation_level=None)
            con.execute("PRAGMA journal_mode=DELETE")
            self._dbs[db] = con
        return self._dbs[db]

    def run(self, batch: Batch) -> dict[str, Any]:
        con = self._db(batch.db)
        before = con.total_changes
        try:
            con.execute(batch.sql, batch.params)
        except sqlite3.Error as exc:
            raise TargetError(f"{batch.step} {batch.key}: {exc}") from exc
        return {"rows_written": con.total_changes - before}

    def query(self, db: int, sql: str, params: list[Any] | None = None) -> list[tuple]:
        if not self.path(db).exists():
            raise TargetError("no such table: the database does not exist yet")
        try:
            return self._db(db).execute(sql, params or []).fetchall()
        except sqlite3.Error as exc:
            raise TargetError(str(exc)) from exc

    def reset(self, databases: int) -> None:
        for con in self._dbs.values():
            con.close()
        self._dbs.clear()
        for p in self.root.glob("db-*.sqlite*"):
            p.unlink()

    def close(self) -> None:
        for con in self._dbs.values():
            con.close()
        self._dbs.clear()


class BridgeTarget:
    """The local D1 emulator (wrangler's, i.e. workerd's own D1), through ``cloud/test/d1-emulator.mjs``: a process
    reading one JSON request a line and answering with D1's result, ``meta.rows_written`` as D1 reports it."""

    def __init__(self, command: list[str]) -> None:
        import subprocess

        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                                     bufsize=1)
        ready = self._line()
        if "ready" not in ready:
            raise RuntimeError("the emulator did not start")
        self.databases = int(ready.get("databases") or 0)  # the databases it has bindings for

    def _line(self) -> dict[str, Any]:
        """The next answer (lines that are not one — what wrangler may print — are passed over)."""
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise TargetError("the emulator stopped", transient=False)
            if line.startswith("{"):
                return json.loads(line)

    def _ask(self, request: dict[str, Any]) -> dict[str, Any]:
        self.proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        answer = self._line()
        if not answer.get("ok"):
            raise TargetError(answer.get("error") or "error")
        return answer

    def run(self, batch: Batch) -> dict[str, Any]:
        try:
            meta = self._ask({"db": batch.db, "sql": batch.sql, "params": batch.params, "mode": "run"})["meta"]
        except TargetError as exc:
            raise TargetError(f"{batch.step} {batch.key}: {exc}") from exc
        return {"rows_written": int(meta.get("rows_written") or 0), "rows_read": int(meta.get("rows_read") or 0)}

    def query(self, db: int, sql: str, params: list[Any] | None = None) -> list[tuple]:
        rows = self._ask({"db": db, "sql": sql, "params": params or [], "mode": "raw"})["results"]
        return [tuple(r) for r in rows]

    def reset(self, databases: int) -> None:
        self._ask({"reset": True, "databases": databases})

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)


class ApiTarget:
    """Cloudflare D1 through its REST API (``/accounts/{account}/d1/database``), with the account's API token: the
    databases are found (or created) by name; a statement is one ``/query`` request."""

    API = "https://api.cloudflare.com/client/v4"

    def __init__(self, account: str, token: str, *, location: str = "apac", pause: float = 0.2, log: Callable[[str], None] = print) -> None:
        self.account, self.token, self.location, self.pause, self.log = account, token, location, pause, log
        self.ids: dict[int, str] = {}

    def _request(self, method: str, path: str, body: Any = None, *, timeout: float = 120) -> Any:
        import urllib.error
        import urllib.request

        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.API}/accounts/{self.account}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "User-Agent": "taochronos-d1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the Cloudflare API
                answer = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            text = exc.read()[:2000].decode("utf-8", "replace")
            exhausted = exc.code == 429 and "exceed" in text.lower() or "limit" in text.lower() and "daily" in text.lower()
            raise TargetError(f"HTTP {exc.code}: {text}", transient=exc.code in (429, 500, 502, 503, 504) and not exhausted,
                              exhausted=exhausted) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TargetError(f"{exc}", transient=True) from exc
        if not answer.get("success", False):
            text = json.dumps(answer.get("errors") or answer, ensure_ascii=False)[:2000]
            raise TargetError(text, exhausted="exceed" in text.lower())
        return answer.get("result")

    def databases(self) -> dict[str, str]:
        """name → uuid of the account's databases."""
        out: dict[str, str] = {}
        page = 1
        while True:
            got = self._request("GET", f"/d1/database?per_page=100&page={page}") or []
            out.update({d["name"]: d["uuid"] for d in got})
            if len(got) < 100:
                return out
            page += 1

    def ensure(self, databases: int) -> dict[int, str]:
        """The plan's databases, created where missing (placed near the site's readers)."""
        have = self.databases()
        for k in range(databases):
            name = f"{PREFIX}-{k}"
            if name not in have:
                made = self._request("POST", "/d1/database", {"name": name, "primary_location_hint": self.location})
                have[name] = made["uuid"]
                self.log(f"created D1 database {name}")
            self.ids[k] = have[name]
        return self.ids

    def _query(self, db: int, sql: str, params: list[Any]) -> dict[str, Any]:
        result = self._request("POST", f"/d1/database/{self.ids[db]}/query", {"sql": sql, "params": params})
        time.sleep(self.pause)
        return (result or [{}])[0]

    def run(self, batch: Batch) -> dict[str, Any]:
        try:
            meta = self._query(batch.db, batch.sql, batch.params).get("meta") or {}
        except TargetError as exc:
            raise TargetError(f"{batch.step} {batch.key}: {exc}", transient=exc.transient, exhausted=exc.exhausted) from exc
        return {"rows_written": int(meta.get("rows_written") or 0), "rows_read": int(meta.get("rows_read") or 0)}

    def query(self, db: int, sql: str, params: list[Any] | None = None) -> list[tuple]:
        rows = self._query(db, sql, params or []).get("results") or []
        return [tuple(r.values()) for r in rows]

    def reset(self, databases: int) -> None:
        """A new store: the old databases are deleted and made anew (deleting writes no rows; the site is deployed again
        with the new databases' ids)."""
        for name, uuid in self.databases().items():
            if name.startswith(f"{PREFIX}-"):
                self._request("DELETE", f"/d1/database/{uuid}")
                self.log(f"deleted D1 database {name}")
        self.ids.clear()
        self.ensure(databases)

    def close(self) -> None:
        pass


# ------------------------------------------------------------------ the import
STEPS = ("schema", "chunks", "fts", "optimize", "books", "seqmap", "lex", "results", "meta")


def status(target: Any, db: int) -> dict[str, Any]:
    """What a database holds: {} when it has no tables yet; else its version and how far each step has got."""
    def ask(sql: str) -> list[tuple] | None:
        try:
            return target.query(db, sql)
        except TargetError as exc:
            if "no such table" in str(exc).lower():  # the schema is not all there yet
                return None
            raise

    rows = ask("SELECT k, v FROM progress")
    if rows is None:
        return {}
    st: dict[str, Any] = {k: v for k, v in rows}
    st["chunks"] = ((ask("SELECT max(cid) FROM chunks") or [(0,)])[0][0]) or 0
    if db == 0:
        for step, sql in (("books", "SELECT max(id) FROM books"), ("lex", "SELECT max(k) FROM lex"),
                          ("seqmap", "SELECT book || char(9) || printf('%06d', part) FROM seqmap ORDER BY book DESC, part DESC LIMIT 1"),
                          ("results", "SELECT max(k) FROM results")):
            got = ask(sql)
            st[step] = got[0][0] if got else None
        st["meta"] = {k: v for k, v in (ask("SELECT k, substr(v, 1, 64) FROM meta") or [])}
    return st


def done(batch: Batch, st: dict[str, Any]) -> bool:
    """Is this statement already in the database (whose ``status`` is ``st``)?"""
    if not st:
        return False
    if batch.step == "schema":
        return bool(st.get("version"))
    if batch.step == "chunks":
        return int(st.get("chunks") or 0) >= int(batch.key)
    if batch.step == "fts":
        return int(st.get("fts") or 0) >= int(batch.key)
    if batch.step == "optimize":
        return bool(st.get("optimized"))
    if batch.step in ("books", "seqmap", "lex", "results"):
        return st.get(batch.step) is not None and st[batch.step] >= batch.key
    if batch.step == "meta":
        return batch.key in (st.get("meta") or {})
    raise ValueError(batch.step)


def run_import(plan: Plan, target: Any, *, budget: int = DAY_BUDGET, log: Callable[[str], None] = print,
               reset: bool = False, stop_after: int | None = None, minutes: float | None = None) -> dict[str, Any]:
    """Import the next statements of ``plan`` into ``target`` until ``budget`` rows are written (as D1 reports them;
    a statement is sent only if even its upper bound fits) or ``minutes`` have passed.  Resumable: what is done is
    read from the databases.  Returns what was done, the rows written by step and database, and whether the import
    is complete."""
    # the UTC day whose allowance this run uses (TAOCHRONOS_D1_DAY: another, to simulate a run of days)
    today = os.environ.get("TAOCHRONOS_D1_DAY") or time.strftime("%Y-%m-%d", time.gmtime())
    end = time.monotonic() + minutes * 60 if minutes else None
    deadline = (lambda: time.monotonic() > end) if end else (lambda: False)
    states = {db: status(target, db) for db in range(plan.databases)}
    versions = {st["version"] for st in states.values() if st.get("version")}
    if versions - {plan.version}:
        if not reset:
            raise SystemExit(f"the databases hold version {sorted(v for v in versions if v)} and the store is {plan.version}: "
                             "run with --reset to import the new store afresh")
        log(f"a new store ({plan.version}): the databases are made anew")
        target.reset(plan.databases)
        states = {db: {} for db in range(plan.databases)}
    used_before = int((states.get(0) or {}).get(f"used:{today}") or 0)
    used = recorded = 0
    # seconds: the slowest statement of each step, as long as it took from here (D1's limit is 30 s a query)
    report: dict[str, Any] = {"version": plan.version, "databases": plan.databases, "day": today, "used_before": used_before,
                              "statements": 0, "rows_written": 0, "by_step": {}, "by_db": {}, "seconds": {},
                              "complete": False, "stopped": None}
    sent = 0

    def results_start(digest: str) -> str | None:
        """Where the precomputed results resume; another key list than the one they were made with: afresh."""
        nonlocal used
        st0 = states[0]
        if st0.get("results_plan") != digest:
            if st0.get("results") is not None:
                log(f"  results: another key list ({digest}): the old results are deleted")
                res = target.run(Batch(0, "results", "", "DELETE FROM results", [], 0))
                used += int(res.get("rows_written") or 0)
                report["rows_written"] += int(res.get("rows_written") or 0)
            res = target.run(Batch(0, "results", "", "INSERT OR REPLACE INTO progress(k, v) VALUES ('results_plan', ?)", [digest], 1))
            used += int(res.get("rows_written") or 0)
            st0["results_plan"], st0["results"] = digest, None
        return st0.get("results")

    def count() -> dict[str, int]:
        return {t: n for t, n in target.query(0, "SELECT substr(k, 1, instr(k, char(9)) - 1) AS t, count(*) FROM results GROUP BY t")}

    for batch in plan.order(results_start=results_start, deadline=deadline, count=count):
        st = states[batch.db]
        if done(batch, st):
            continue
        if deadline():
            report["stopped"] = f"the run's time is up ({minutes} minutes)"
            break
        if used_before + used + batch.bound > budget:
            report["stopped"] = f"the day's budget: {used_before + used:,} of {budget:,} rows written"
            break
        if stop_after is not None and sent >= stop_after:
            report["stopped"] = f"stopped after {sent} statements"
            break
        started = time.perf_counter()
        for attempt in range(1, 6):
            try:
                res = target.run(batch)
                took = time.perf_counter() - started
                report["seconds"][batch.step] = max(report["seconds"].get(batch.step, 0), round(took, 2))
                break
            except TargetError as exc:
                if exc.exhausted:
                    report["stopped"] = f"the account's daily allowance is used up: {exc}"
                    break
                states[batch.db] = st = status(target, batch.db)
                if done(batch, st):  # it was applied, the answer was lost
                    res = {"rows_written": batch.rows, "assumed": True}
                    break
                if not exc.transient or attempt == 5:
                    raise
                log(f"  {exc} — again ({attempt})")
                time.sleep(min(60, 2 ** attempt))
        if report["stopped"]:
            break
        sent += 1
        rows = int(res.get("rows_written") or 0)
        used += rows
        report["statements"] += 1
        report["rows_written"] += rows
        report["by_step"][batch.step] = report["by_step"].get(batch.step, 0) + rows
        report["by_db"][str(batch.db)] = report["by_db"].get(str(batch.db), 0) + rows
        _advance(st, batch)
        if sent % 500 == 0:
            log(f"  {sent} statements, {used:,} rows written")
        # the day's use, kept often enough that a run killed between two records under-counts it by less than the
        # margin between the budget and D1's allowance (a record is a row written)
        if sent % 500 == 0 or used - recorded >= USE_RECORD_ROWS:
            _record_use(target, today, used_before + used, log)
            recorded = used
    if not report["stopped"] and deadline():
        report["stopped"] = f"the run's time is up ({minutes} minutes)"
    report["complete"] = "complete" in (states.get(0, {}).get("meta") or {})
    if states.get(0):
        _record_use(target, today, used_before + used, log)
    return report


def _advance(st: dict[str, Any], batch: Batch) -> None:
    if batch.step == "schema":
        st.setdefault("version", batch.params[0] if batch.params else None)
        st.setdefault("chunks", 0)
    elif batch.step in ("chunks", "fts"):
        st[batch.step] = batch.key
    elif batch.step == "optimize":
        st["optimized"] = 1
    elif batch.step == "meta":
        st.setdefault("meta", {})[batch.key] = True
    else:
        st[batch.step] = batch.key


def _record_use(target: Any, day: str, rows: int, log: Callable[[str], None]) -> None:
    """The rows written today, kept in database 0 so that a second run the same day counts them."""
    try:
        target.run(Batch(0, "use", day, "INSERT OR REPLACE INTO progress(k, v) VALUES (?, ?)", [f"used:{day}", rows], 1))
    except TargetError as exc:
        log(f"  could not record the day's use: {exc}")


# ------------------------------------------------------------------ making the plan
def make_plan(store: str | Path, *, home: str | Path | None = None, version: str | None = None, results: Any = None,
              **kw: Any) -> Plan:
    """The plan for ``store`` with this checkout's domain: its normaliser, the lexicon as the full-corpus profile reads it
    (with the harvested vocabularies), the periods and the 要籍 list; ``results``: the precomputed results
    (``d1results.Precompute``)."""
    from ..config import find_home
    from ..plugins.classics.domain import DomainPack
    from ..protocol.yamlio import load_yaml

    root = find_home(str(home) if home else None)
    profile = load_yaml(root / "profiles" / "full-corpus.yaml") or {}
    config = next((b.get("config") or {} for b in profile.get("bundles", []) if b.get("plugin") == "taochronos.plugins.classics"), {})
    pack = DomainPack(root / config.get("domain", "domains/classics"), extra_lexicons=config.get("lexicon_extra", ()))
    canon = (load_yaml(root / "corpus" / "catalog" / "canon.yaml") or {}).get("works") or []
    return Plan(store, pack.variants.normalize_text, version=version, normalizer=pack.variants.fingerprint, lexicon=pack.lexicon,
                periods=pack.periods, canon=canon, results=results, **kw)


def summary(plan: Plan, *, statements: bool = True) -> dict[str, Any]:
    """The databases, their chunks and characters, and the rows each step writes (as D1 reports them, and at most)."""
    dbs = []
    for k, (lo, hi) in enumerate(plan.ranges):
        cs = plan.chunks[lo - 1:hi]
        dbs.append({"name": f"{PREFIX}-{k}", "chunks": [lo, hi], "passages": sum(len(c.seqs) for c in cs),
                    "characters": sum(c.chars for c in cs)})
    out: dict[str, Any] = {"version": plan.version, "books": len(plan.books), "passages": plan.passages,
                           "characters": plan.characters, "chunks": len(plan.chunks), "databases": dbs}
    if statements:
        steps: dict[str, dict[str, int]] = {}
        for b in plan.order():
            s = steps.setdefault(b.step, {"statements": 0, "rows": 0, "bound": 0, "bytes": 0})
            s["statements"] += 1
            s["rows"] += b.rows
            s["bound"] += b.bound
            s["bytes"] += b.bytes
        out["steps"] = steps
        rows, bound = sum(s["rows"] for s in steps.values()), sum(s["bound"] for s in steps.values())
        out["rows"] = {"reported": rows, "at_most": bound, "days_at_budget": [-(-rows // DAY_BUDGET), -(-bound // DAY_BUDGET)],
                       "budget": DAY_BUDGET}
    return out


def wanted_version(manifest: str | Path, home: str | Path | None = None) -> str:
    """The version the databases should hold for this checkout: the store cloud/store.json names, the normaliser, the
    layout (``Plan.version``) — known without the store, so that a run with nothing to do stops before fetching it."""
    from ..config import find_home
    from ..plugins.classics.domain import DomainPack

    root = find_home(str(home) if home else None)
    sha = json.loads(Path(manifest).read_text(encoding="utf-8"))["sha256"]
    return f"{sha[:12]}-{DomainPack(root / 'domains' / 'classics').variants.fingerprint[:8]}-s{SCHEMA}"


def _target(args: Any, databases: int | None) -> Any:
    """Where the import goes (``--api``, ``--sqlite``, ``--bridge``); with ``databases`` None only the databases there
    are (``status``), else the plan's, created if missing."""
    if args.api:
        token, account = os.environ.get("CLOUDFLARE_API_TOKEN", ""), os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account:
            raise SystemExit("set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID")
        target = ApiTarget(account, token, log=lambda m: print(m, flush=True))
        if databases is None:  # the databases that are there
            have = target.databases()
            target.ids = {int(n.rsplit("-", 1)[1]): u for n, u in have.items() if n.startswith(f"{PREFIX}-") and n.rsplit("-", 1)[1].isdigit()}
        else:
            target.ensure(databases)
        return target
    if args.sqlite:
        return SqliteTarget(args.sqlite)
    import shlex

    return BridgeTarget(shlex.split(args.bridge))


def _store(path: str, manifest: str | None, work: str | None) -> Path:
    """The store to export: as given, or unpacked from the compressed store the site's KV namespace holds (checked
    against cloud/store.json) into ``work``."""
    p = Path(path)
    if p.suffix != ".xz":
        return p
    from .cloud import unpack

    dest = Path(work or p.parent / "d1") / "data" / "corpus" / "tcm.sqlite"
    if not dest.exists():
        unpack(p, dest, json.loads(Path(manifest).read_text(encoding="utf-8")) if manifest else None)
    return dest


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python -m taochronos.chat.d1", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def where(sp: Any) -> None:
        w = sp.add_mutually_exclusive_group(required=True)
        w.add_argument("--api", action="store_true", help="Cloudflare D1 ($CLOUDFLARE_API_TOKEN, $CLOUDFLARE_ACCOUNT_ID)")
        w.add_argument("--sqlite", help="local SQLite files in this directory")
        w.add_argument("--bridge", help="the local D1 emulator: the command that starts cloud/test/d1-emulator.mjs")

    def store(sp: Any) -> None:
        sp.add_argument("store", help="the store (a .sqlite, or the compressed .sqlite.xz with --manifest)")
        sp.add_argument("--manifest", help="cloud/store.json: the compressed store's digests, and its sha256 as the version")
        sp.add_argument("--version", help="the store's sha256 (default: the manifest's)")
        sp.add_argument("--work", help="where a compressed store is unpacked (default: beside it)")

    sp = sub.add_parser("plan", help="the databases, their sizes and the rows each step writes")
    store(sp)
    sp = sub.add_parser("import", help="import the next slice, within the day's budget")
    store(sp)
    where(sp)
    sp.add_argument("--budget", type=int, default=DAY_BUDGET, help=f"rows to write at most today (default {DAY_BUDGET:,})")
    sp.add_argument("--minutes", type=float, help="stop after this many minutes (the job's time)")
    sp.add_argument("--reset", action="store_true", help="another store: make the databases anew")
    sp.add_argument("--stop-after", type=int, help="stop after this many statements (tests)")
    sp.add_argument("--precompute", action="store_true", help="also compute the precomputed results with the Python tools "
                                                              "(the store is indexed for them when the import comes to them)")
    sp.add_argument("--report", help="also write the report (JSON) to this file")
    sp = sub.add_parser("version", help="the version the databases should hold for this checkout (cloud/store.json …)")
    sp.add_argument("--manifest", default=None, help="default: cloud/store.json")
    sp = sub.add_parser("status", help="what each database holds (its version, how far each step has got)")
    where(sp)
    sp = sub.add_parser("tables", help="write the JavaScript module of the normaliser's tables, periods, catalog …")
    sp.add_argument("-o", "--output", help="default: cloud/site/src/backup/tables.js")
    sp.add_argument("--check", action="store_true", help="only check that the module is up to date")
    sp = sub.add_parser("fixture", help="a small D1 backup for the tests (local SQLite files)")
    sp.add_argument("output")
    args = p.parse_args(argv)
    log = lambda m: print(m, flush=True)  # noqa: E731

    if args.cmd == "tables":
        from .d1tables import write_tables

        return write_tables(args.output, check=args.check)
    if args.cmd == "fixture":
        from .d1fixture import build_fixture

        build_fixture(args.output)
        return 0
    if args.cmd == "version":
        from ..config import find_home

        print(wanted_version(args.manifest or find_home() / "cloud" / "store.json"))
        return 0
    if args.cmd == "status":
        target = _target(args, None)
        try:
            if args.api:
                dbs = sorted(target.ids)
            elif args.sqlite:
                dbs = sorted(int(f.stem.split("-")[1]) for f in Path(args.sqlite).glob("db-*.sqlite"))
            else:
                dbs = list(range(target.databases))
            out = {}
            for k in dbs:
                st = status(target, k)
                out[f"{PREFIX}-{k}"] = {key: v for key, v in st.items() if key != "meta"} | ({"meta": sorted(st["meta"])} if "meta" in st else {})
        finally:
            target.close()
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    path = _store(args.store, args.manifest, args.work)
    version = args.version or (json.loads(Path(args.manifest).read_text(encoding="utf-8"))["sha256"] if args.manifest else None)
    results = None
    if getattr(args, "precompute", False):
        from .d1results import Precompute, runtime_for

        results = Precompute(lambda: runtime_for(path, log=log), log=log)
    plan = make_plan(path, version=version, results=results)
    if args.cmd == "plan":
        print(json.dumps(summary(plan), ensure_ascii=False, indent=1))
        return 0
    target = _target(args, plan.databases)
    try:
        report = run_import(plan, target, budget=args.budget, reset=args.reset, stop_after=args.stop_after, minutes=args.minutes,
                            log=log)
    finally:
        target.close()
    report["names"] = plan.names()
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
