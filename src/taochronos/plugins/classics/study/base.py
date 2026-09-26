"""What every study function shares: citing a passage, dating it, finding a surface, period totals.

A *witness* is a passage as a scholar cites it — 《书名》卷·篇·节, the book's dynasty and date, the kind of text
(正文, 注, 序跋 …), the source and licence of the transcription, and a verbatim quote with its character span.  All
study outputs are made of witnesses, so every statement can be checked against the text it rests on.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from ....protocol.documents import Passage
from ..domain import DomainPack

PUNCT = set("，。；：、？！“”‘’（）《》〈〉…—·‧「」『』【】〔〕［］｛｝ 　\n\t,.;:!?()[]{}<>\"'")
HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff〓□]")


def han_only(text: str) -> tuple[str, list[int]]:
    """The Han characters of a text and, for each, its offset in the original."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if HAN.match(ch):
            chars.append(ch)
            index.append(i)
    return "".join(chars), index


def snippet(text: str, start: int, end: int, width: int = 24) -> str:
    """Key word in context: the span with ``width`` characters on each side, cut at sentence ends."""
    left = text[max(0, start - width): start]
    right = text[end: end + width]
    cut = max(left.rfind(c) for c in "。；！？\n")
    if cut >= 0:
        left = left[cut + 1:]
    stop = min((right.find(c) for c in "。；！？\n" if right.find(c) >= 0), default=-1)
    if stop >= 0:
        right = right[: stop + 1]
    return (left + text[start:end] + right).strip()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def normal_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def trend_test(rows: list[tuple[int, int]]) -> tuple[float, float] | None:
    """Cochran–Armitage test for a trend in proportions k/n over ordered groups: (z, two-sided p)."""
    rows = [(k, n) for k, n in rows if n > 0]
    if len(rows) < 3:
        return None
    big_n = sum(n for _, n in rows)
    big_k = sum(k for k, _ in rows)
    if big_k in (0, big_n):
        return None
    p = big_k / big_n
    scores = list(range(len(rows)))
    t = sum(s * (k - n * p) for s, (k, n) in zip(scores, rows))
    mean = sum(s * n for s, (_, n) in zip(scores, rows)) / big_n
    var = p * (1 - p) * sum(n * (s - mean) ** 2 for s, (_, n) in zip(scores, rows))
    if var <= 0:
        return None
    z = t / math.sqrt(var)
    return round(z, 3), round(2 * normal_sf(abs(z)), 6)


@dataclass
class Period:
    id: str
    label: str
    start: float
    end: float


class StudyBase:
    """Corpus, domain and the helpers of the study functions (works on the demo corpus and on the store)."""

    def __init__(self, pack: DomainPack, corpus: Any) -> None:
        self.pack = pack
        self.corpus = corpus
        self.normalize: Callable[[str], str] = pack.variants.normalize_text
        self.periods = [Period(p.id, p.label, p.start, p.end) for p in pack.periods.analysis]
        self._period_totals: dict[str, dict[str, int]] | None = None
        self._headings: dict[str, dict[str, list[tuple[str, int, str]]]] = {}
        self._entries_db: sqlite3.Connection | None = None
        self._entries_mem: dict[str, list[tuple[str, str, list[str]]]] | None = None
        self._entries_lock = threading.Lock()

    # ------------------------------------------------------------ data files
    def data(self, name: str) -> dict[str, Any]:
        return _load_yaml(str(self.pack.root / name))

    # ------------------------------------------------------------ dating
    def years(self, p: Passage) -> tuple[float, float] | None:
        rng = self.corpus.year_range(p)
        return None if rng is None else (rng.start, rng.end)

    def year(self, p: Passage) -> float | None:
        return self.corpus.year(p)

    def period_of(self, year: float | None) -> Period | None:
        if year is None:
            return None
        for per in self.periods:
            if per.start <= year < per.end:
                return per
        return None

    # ------------------------------------------------------------ citing
    def book_title(self, book_id: str) -> str:
        book = self.corpus.books.get(book_id)
        return book.title if book else book_id

    def locator(self, p: Passage) -> str:
        loc = p.locator
        parts = [x for x in (loc.volume, loc.chapter, loc.section) if x]
        page = f"（{loc.page}）" if loc.page else ""
        return f"《{self.book_title(p.book_id)}》" + "·".join(dict.fromkeys(parts)) + page

    def witness(self, p: Passage, *, start: int | None = None, end: int | None = None, width: int = 24,
                quote: str | None = None) -> dict[str, Any]:
        book = self.corpus.books.get(p.book_id)
        yrs = self.years(p)
        layer = next((t.split(":", 1)[1] for t in p.tags if t.startswith("layer:")), "正文")
        if quote is None:
            quote = snippet(p.text, start, end, width) if start is not None and end is not None else p.text[: 2 * width]
        per = self.period_of(self.year(p))
        return {
            "passage_id": p.id, "book_id": p.book_id, "title": book.title if book else p.book_id,
            "work": getattr(book, "work", None) if book else None, "authors": list(book.authors) if book else [],
            "dynasty": (book.dynasty if book else "") or "", "years": list(yrs) if yrs else None,
            "period": per.label if per else None, "category": book.category if book else "", "kind": p.kind,
            "layer": layer, "locator": self.locator(p), "quote": quote,
            **({"span": [start, end]} if start is not None and end is not None else {}),
            "source": book.source.origin if book else "", "license": book.source.license if book else "",
            "punctuation": p.punctuation,
        }

    # ------------------------------------------------------------ finding
    def surfaces(self, term: str, category: str | None = None) -> tuple[str | None, list[tuple[str, str]]]:
        """The lexicon entry of ``term`` and its written forms with their kind (本名, 异名, 避讳改名 …)."""
        entry = self.pack.lexicon.resolve(term, category) or self.pack.lexicon.resolve(self.normalize(term), category)
        if entry is None:
            return None, [(term, "本名")]
        forms: list[tuple[str, str]] = [(entry.term, "本名")]
        forms += [(a, "异名") for a in entry.aliases]
        forms += [(s, self.pack.synonym_kind_label(k) or "异名") for s, k in entry.synonyms.items()]
        if term not in {f for f, _ in forms}:
            forms.insert(0, (term, "检索词"))
        seen: set[str] = set()
        out = []
        for f, kind in forms:
            key = self.normalize(f)
            if key in seen or len(key) < 1:
                continue
            seen.add(key)
            out.append((f, kind))
        return entry.term_id, out

    def find(self, surface: str, *, book_ids: Iterable[str] | None = None, limit: int | None = None) -> list[str]:
        if getattr(self.corpus, "large", False):
            return self.corpus.contains(surface, book_ids=book_ids, limit=limit)
        return self.corpus.contains(surface, book_ids=book_ids, limit=limit, normalize=self.normalize)

    def passages(self, ids: Iterable[str]) -> list[Passage]:
        return self.corpus.passages_by_id(list(ids))

    def book_ids(self, *, categories: Iterable[str] | None = None) -> list[str]:
        cats = set(categories) if categories is not None else None
        return sorted(b.id for b in self.corpus.books.values() if cats is None or b.category in cats)

    def heading_index(self, book_ids: list[str], key: str) -> dict[str, list[tuple[str, int, str]]]:
        """Normalised section heading (notes in brackets dropped) → [(book, seq, passage)] in the given books, cached
        under ``key``.  笈成 writes a drug's or a formula's name as the heading of its entry, not in the text."""
        if key in self._headings:
            return self._headings[key]
        index: dict[str, list[tuple[str, int, str]]] = {}
        rows: list[tuple[str, str, int, dict[str, Any]]] = []
        store = getattr(self.corpus, "store", None)
        if store is not None and book_ids:
            marks = ",".join("?" * len(book_ids))
            with store.lock:
                for pid, bid, seq, loc in store.db.execute(
                        f"SELECT id, book_id, seq, locator FROM passages WHERE book_id IN ({marks}) AND kind != 'toc'", book_ids):
                    rows.append((pid, bid, seq, json.loads(loc)))
        elif book_ids:
            for i, p in enumerate(self.corpus.passages(book_ids=book_ids)):
                rows.append((p.id, p.book_id, i, {"section": p.locator.section, "chapter": p.locator.chapter}))
        for pid, bid, seq, loc in rows:
            head = (loc.get("section") or loc.get("chapter") or "").split("·")[-1]
            head = re.sub(r"[（(〔][^）)〕]*[）)〕]", "", head).strip()
            han, _ = han_only(self.normalize(head))
            if 1 <= len(han) <= 14:
                index.setdefault(han, []).append((bid, seq, pid))
        self._headings[key] = index
        return index

    # ------------------------------------------------------------ entries under a heading
    @staticmethod
    def _heading_of(loc: dict[str, Any]) -> str:
        head = (loc.get("section") or loc.get("chapter") or "").split("·")[-1].split("‧")[-1].strip("【】〖〗 　")
        return re.sub(r"[（(〔][^）)〕]*[）)〕]", "", head).strip()

    def entries(self, names: Iterable[str], *, limit: int = 400, span: int = 8) -> list[tuple[str, list[Passage]]]:
        """Entries headed by one of ``names`` anywhere in the corpus: (the heading as printed, the first ``span``
        passages under it).  笈成 prints a formula's or a drug's name as the heading of its entry, and the indication,
        the drugs and the preparation as paragraphs under it, so the name is in no passage's text."""
        keys = sorted({han_only(self.normalize(n))[0] for n in names} - {""})
        if not keys:
            return []
        store = getattr(self.corpus, "store", None)
        out: list[tuple[str, list[Passage]]] = []
        if store is None:
            index = self._entry_index_memory()
            for key in keys:
                for raw, _, ids in index.get(key, [])[:limit]:
                    out.append((raw, self.passages(ids[:span])))
            return out[:limit]
        db = self._entry_index_store()
        marks = ",".join("?" * len(keys))
        rows = db.execute(f"SELECT raw, book_id, first_seq, last_seq FROM entries WHERE head IN ({marks}) "
                          f"ORDER BY book_id, first_seq LIMIT ?", (*keys, limit)).fetchall()
        with store.lock:
            for raw, book_id, first, last in rows:
                ids = [r[0] for r in store.db.execute(
                    "SELECT id FROM passages WHERE book_id=? AND seq BETWEEN ? AND ? AND kind != 'toc' ORDER BY seq LIMIT ?",
                    (book_id, first, last, span))]
                out.append((raw, ids))  # type: ignore[arg-type]
        return [(raw, self.passages(ids)) for raw, ids in out]

    def _entry_index_memory(self) -> dict[str, list[tuple[str, str, list[str]]]]:
        if self._entries_mem is None:
            index: dict[str, list[tuple[str, str, list[str]]]] = {}
            prev: tuple[str, str] | None = None
            for p in self.corpus.passages():
                if p.kind == "toc":
                    continue
                raw = self._heading_of({"section": p.locator.section, "chapter": p.locator.chapter})
                if prev == (p.book_id, raw) and index.get(han_only(self.normalize(raw))[0]):
                    index[han_only(self.normalize(raw))[0]][-1][2].append(p.id)
                    continue
                prev = (p.book_id, raw)
                key = han_only(self.normalize(raw))[0]
                if 1 <= len(key) <= 14:
                    index.setdefault(key, []).append((raw, p.book_id, [p.id]))
            self._entries_mem = index
        return self._entries_mem

    def _entry_index_store(self) -> sqlite3.Connection:
        """The headings of the whole store, one row per entry (a run of passages under one heading), cached in
        ``study-cache/headings-<corpus digest>.sqlite`` — built once, in about half a minute."""
        with self._entries_lock:
            if self._entries_db is not None:
                return self._entries_db
            store = self.corpus.store
            path = store.path.parent / "study-cache" / f"headings-v2-{self.signature()['corpus_digest']}.sqlite"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.unlink(missing_ok=True)
                db = sqlite3.connect(tmp)
                db.execute("CREATE TABLE entries(head TEXT, raw TEXT, book_id TEXT, first_seq INTEGER, last_seq INTEGER)")
                rows: list[tuple[str, str, str, int, int]] = []
                run: list[Any] | None = None  # [head, raw, book, first, last]
                with store.lock:
                    cur = store.db.execute("SELECT book_id, seq, locator FROM passages WHERE kind != 'toc' ORDER BY book_id, seq")
                    for book_id, seq, loc in cur:
                        raw = self._heading_of(json.loads(loc))
                        if run is not None and run[2] == book_id and run[1] == raw:
                            run[4] = seq
                            continue
                        if run is not None and 1 <= len(run[0]) <= 14:
                            rows.append(tuple(run))  # type: ignore[arg-type]
                        run = [han_only(self.normalize(raw))[0], raw, book_id, seq, seq]
                if run is not None and 1 <= len(run[0]) <= 14:
                    rows.append(tuple(run))  # type: ignore[arg-type]
                db.executemany("INSERT INTO entries VALUES (?,?,?,?,?)", rows)
                db.execute("CREATE INDEX entries_head ON entries(head)")
                db.commit()
                db.close()
                tmp.replace(path)
            self._entries_db = sqlite3.connect(path, check_same_thread=False)
            return self._entries_db

    def following(self, p: Passage, n: int = 2) -> list[Passage]:
        """The next passages of the same book (an entry often continues in the passages after its heading)."""
        store = getattr(self.corpus, "store", None)
        if store is not None:
            with store.lock:
                row = store.db.execute("SELECT seq FROM passages WHERE id=?", (p.id,)).fetchone()
                if row is None:
                    return []
                ids = [r[0] for r in store.db.execute(
                    "SELECT id FROM passages WHERE book_id=? AND seq>? ORDER BY seq LIMIT ?", (p.book_id, row[0], n))]
            return self.passages(ids)
        order = [q for q in self.corpus.passages(book_ids=[p.book_id])]
        ids = [q.id for q in order]
        if p.id not in ids:
            return []
        i = ids.index(p.id)
        return order[i + 1: i + 1 + n]

    def book_counts(self, passage_ids: list[str]) -> dict[str, int]:
        """Book id → number of the given passages it holds."""
        out: dict[str, int] = {}
        store = getattr(self.corpus, "store", None)
        if store is not None:
            for i in range(0, len(passage_ids), 900):
                chunk = passage_ids[i: i + 900]
                marks = ",".join("?" * len(chunk))
                with store.lock:
                    for bid, n in store.db.execute(
                            f"SELECT book_id, COUNT(*) FROM passages WHERE id IN ({marks}) GROUP BY book_id", chunk):
                        out[bid] = out.get(bid, 0) + n
            return out
        for p in self.passages(passage_ids):
            out[p.book_id] = out.get(p.book_id, 0) + 1
        return out

    def book_texts(self, book_id: str) -> Iterable[str]:
        store = getattr(self.corpus, "store", None)
        if store is not None:
            with store.lock:
                rows = store.db.execute("SELECT text FROM passages WHERE book_id=? AND kind != 'toc' ORDER BY seq",
                                        (book_id,)).fetchall()
            return [r[0] for r in rows]
        return [p.text for p in self.corpus.passages(book_ids=[book_id]) if p.kind != "toc"]

    # ------------------------------------------------------------ denominators
    def period_totals(self) -> dict[str, dict[str, int]]:
        """Passages and characters per analysis period (the denominators of relative frequencies)."""
        if self._period_totals is not None:
            return self._period_totals
        totals = {per.id: {"passages": 0, "characters": 0} for per in self.periods}
        store = getattr(self.corpus, "store", None)
        excluded = getattr(self.corpus, "exclude_books", set())
        if store is not None:
            with store.lock:
                rows = store.db.execute(
                    "SELECT book_id, year, COUNT(*), SUM(LENGTH(text)) FROM passages WHERE kind != 'toc' "
                    "GROUP BY book_id, year").fetchall()
            for book_id, year, n, chars in rows:
                if book_id in excluded or book_id not in self.corpus.books:
                    continue
                per = self.period_of(year)
                if per is not None:
                    totals[per.id]["passages"] += n
                    totals[per.id]["characters"] += chars or 0
        else:
            for p in self.corpus.passages():
                if p.kind == "toc":
                    continue
                per = self.period_of(self.year(p))
                if per is not None:
                    totals[per.id]["passages"] += 1
                    totals[per.id]["characters"] += len(p.text)
        self._period_totals = totals
        return totals

    def signature(self) -> dict[str, Any]:
        """What a study result was computed on (for the provenance footer of every output)."""
        store = getattr(self.corpus, "store", None)
        books = len(self.corpus.books)
        passages = len(self.corpus)
        sources = sorted(set(getattr(self.corpus, "sources", {}).values())) or ["demo"]
        normalizer = getattr(self.pack.variants, "fingerprint", None)
        # the book records too: a re-dated or re-assigned book changes periods, works and so every cached result
        records = sorted((b.id, str(b.composition), b.work or "", b.category) for b in self.corpus.books.values())
        digest = hashlib.sha1(json.dumps([books, passages, sources, normalizer, records], ensure_ascii=False, default=str)
                              .encode()).hexdigest()[:12]
        return {"books": books, "passages": passages, "sources": sources, "normalizer": normalizer,
                "store": str(getattr(store, "path", "")) if store is not None else "demo", "corpus_digest": digest}


def dated(years: Any) -> tuple[float, float]:
    """Sort key for "earliest": the latest date a witness can have (terminus ante quem), then its earliest — so a book
    dated only by its dynasty (宋, 960–1279) does not come before one dated to a reign (1107–1151)."""
    if not years:
        return (9999.0, 9999.0)
    return (float(years[1]), float(years[0]))


@lru_cache(maxsize=16)
def _load_yaml(path: str) -> dict[str, Any]:
    p = Path(path)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


__all__ = ["PUNCT", "Period", "StudyBase", "dated", "han_only", "normal_sf", "snippet", "trend_test", "wilson"]
