"""Near-duplicate detection between a new transcription and the texts already in the corpus store.

Many digital collections of Chinese medical texts are copies of one another (the 笈成 transcriptions reappear,
converted to simplified characters, in several web and GitHub collections).  Ingesting a copy adds no witness —
it only inflates frequencies — so every candidate text is compared with the store before it is ingested.

Texts are compared on their normalised Han characters only (script, variants, punctuation and layout removed),
through a content-defined sample of 12-character shingles: a shingle is kept when it starts at an anchor
character and its CRC32 is 0 mod 8 — the same shingles are sampled in every copy of a passage, about one in 64
positions.  The *containment* of a candidate in a stored book is the share of the candidate's sampled shingles
that the book also has.

The index of the store is cached between runs (:func:`load_sketch`) and brought up to date book by book: only
books added, removed or changed since the cache was written are read again.
"""

from __future__ import annotations

import pickle
import re
import zlib
from array import array
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

K = 12
_HAN = re.compile(r"[^㐀-䶿一-鿿\U00020000-\U0002ffff]+")
# anchors: one CJK code point in eight, spread by a multiplicative hash (content-defined, identical in all copies)
_ANCHORS = "".join(chr(cp) for cp in range(0x4E00, 0xA000) if ((cp * 2654435761) >> 13) % 8 == 0)
_ANCHOR = re.compile("[" + re.escape(_ANCHORS) + "]")


def han(normalized: str) -> str:
    """Only the Han characters of an already normalised text."""
    return _HAN.sub("", normalized)


def sample(han_text: str) -> set[int]:
    out: set[int] = set()
    limit = len(han_text) - K
    for m in _ANCHOR.finditer(han_text):
        i = m.start()
        if i > limit:
            break
        h = zlib.crc32(han_text[i:i + K].encode("utf-8"))
        if h % 8 == 0:
            out.add(h)
    return out


@dataclass
class Match:
    book_id: str
    containment: float  # share of the candidate found in the book
    reverse: float  # share of the book found in the candidate
    shared: int


class SketchIndex:
    """Sampled shingles of every book in the store (a few megabytes per hundred million characters)."""

    def __init__(self) -> None:
        self.books: dict[str, int] = {}  # book id -> number of sampled shingles
        self.grams: dict[str, array] = {}  # book id -> its shingles (to remove or save the book)
        self._owners: dict[int, object] = {}  # shingle -> book id, or a set of book ids when shared

    def add(self, book_id: str, grams: Iterable[int]) -> None:
        if book_id in self.grams:
            self.remove(book_id)
        kept = array("I")
        for h in grams:
            cur = self._owners.get(h)
            if cur is None:
                self._owners[h] = book_id
            elif isinstance(cur, set):
                if book_id in cur:
                    continue
                cur.add(book_id)
            elif cur != book_id:
                self._owners[h] = {cur, book_id}
            else:
                continue
            kept.append(h)
        self.grams[book_id] = kept
        self.books[book_id] = len(kept)

    def remove(self, book_id: str) -> None:
        for h in self.grams.pop(book_id, ()):
            cur = self._owners.get(h)
            if isinstance(cur, set):
                cur.discard(book_id)
                if len(cur) == 1:
                    self._owners[h] = next(iter(cur))
            elif cur == book_id:
                del self._owners[h]
        self.books.pop(book_id, None)

    @classmethod
    def from_store(cls, store: object, normalize: Callable[[str], str], *, exclude: Iterable[str] = (),
                   only: Iterable[str] | None = None, progress: Callable[[str], None] | None = None) -> "SketchIndex":
        index = cls()
        for book_id, grams in _store_samples(store, normalize, exclude=exclude, only=only):
            index.add(book_id, grams)
            if progress:
                progress(book_id)
        return index

    def match(self, grams: set[int], *, top: int = 5, ignore: Iterable[str] = ()) -> list[Match]:
        if not grams:
            return []
        skip = set(ignore)
        counts: Counter = Counter()
        for h in grams:
            owner = self._owners.get(h)
            if owner is None:
                continue
            if isinstance(owner, set):
                counts.update(owner)
            else:
                counts[owner] += 1
        for b in skip:
            counts.pop(b, None)
        ranked = sorted(counts.items(), key=lambda bn: (-bn[1], bn[0]))[:top]  # ties: the main file before its "a" copy
        return [Match(b, round(n / len(grams), 4), round(n / max(1, self.books.get(b, 1)), 4), n) for b, n in ranked]

    def union_containment(self, grams: set[int], book_ids: Iterable[str]) -> float:
        """Share of the candidate found in any of the given books (a compilation of several stored texts)."""
        wanted = set(book_ids)
        if not grams:
            return 0.0
        hit = 0
        for h in grams:
            owner = self._owners.get(h)
            if owner is None:
                continue
            if (isinstance(owner, set) and owner & wanted) or owner in wanted:
                hit += 1
        return round(hit / len(grams), 4)


def _store_samples(store: object, normalize: Callable[[str], str], *, exclude: Iterable[str] = (),
                   only: Iterable[str] | None = None) -> Iterable[tuple[str, set[int]]]:
    skip = set(exclude)
    wanted = set(only) if only is not None else None
    db = getattr(store, "db")
    if wanted is not None and len(wanted) < 200:
        books = sorted(wanted - skip)
        for book_id in books:
            parts = [normalize(t) for (t,) in db.execute(
                "SELECT text FROM passages WHERE book_id=? AND kind != 'toc' ORDER BY seq", (book_id,))]
            yield book_id, sample(han("".join(parts)))
        return
    cur_book, parts = None, []
    for book_id, text in db.execute("SELECT book_id, text FROM passages WHERE kind != 'toc' ORDER BY book_id, seq"):
        if book_id != cur_book:
            if cur_book is not None and cur_book not in skip and (wanted is None or cur_book in wanted):
                yield cur_book, sample(han("".join(parts)))
            cur_book, parts = book_id, []
        if book_id in skip or (wanted is not None and book_id not in wanted):
            continue
        parts.append(normalize(text))  # passage by passage: short strings, bounded cache
    if cur_book is not None and cur_book not in skip and (wanted is None or cur_book in wanted):
        yield cur_book, sample(han("".join(parts)))


def store_signatures(store: object) -> dict[str, tuple[int, int]]:
    """Book id → (passages, characters) of its searchable text: changes whenever a book is re-ingested differently."""
    db = getattr(store, "db")
    return {b: (n, c or 0) for b, n, c in db.execute(
        "SELECT book_id, COUNT(*), SUM(LENGTH(text)) FROM passages WHERE kind != 'toc' GROUP BY book_id")}


def load_sketch(store: object, normalize: Callable[[str], str], cache: str | Path | None, fingerprint: str,
                log: Callable[[str], None] = lambda m: None) -> SketchIndex:
    """The sketch index of the store, from the cache when it is current; updated and saved back otherwise."""
    sigs = store_signatures(store)
    state: dict[str, Any] = {}
    if cache is not None and Path(cache).exists():
        try:
            with open(cache, "rb") as f:
                state = pickle.load(f)
        except Exception:  # noqa: BLE001 - a broken cache is rebuilt
            state = {}
    if state.get("fingerprint") != fingerprint or state.get("k") != K:
        state = {}
    index = SketchIndex()
    old_sigs: dict[str, tuple[int, int]] = state.get("sigs", {})
    for book_id, grams in state.get("grams", {}).items():
        if sigs.get(book_id) == old_sigs.get(book_id):
            index.add(book_id, grams)
    stale = sorted(b for b in sigs if b not in index.grams)
    if stale:
        log(f"  sketch: reading {len(stale)} of {len(sigs)} books from the store")
        for book_id, grams in _store_samples(store, normalize, only=stale):
            index.add(book_id, grams)
    for book_id in [b for b in index.grams if b not in sigs]:
        index.remove(book_id)
    if cache is not None and (stale or set(old_sigs) != set(sigs)):
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(cache) + ".tmp")
        with open(tmp, "wb") as f:
            pickle.dump({"fingerprint": fingerprint, "k": K, "sigs": sigs, "grams": index.grams}, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(cache)
    return index


DUPLICATE = 0.85  # a candidate this much contained in stored texts is a copy
RECENSION = 0.30  # above this, a title-matched candidate is another witness of the same work


def classify(index: SketchIndex, grams: set[int], *, duplicate: float = DUPLICATE, union: float = 0.9,
             ignore: Iterable[str] = ()) -> tuple[str, list[Match], float]:
    """("duplicate" | "overlap" | "new", best matches, union containment of the top matches)."""
    matches = index.match(grams, top=10, ignore=ignore)  # a large work may be stored in several volumes
    joint = index.union_containment(grams, [m.book_id for m in matches]) if matches else 0.0
    if matches and (matches[0].containment >= duplicate or joint >= union):
        return "duplicate", matches, joint
    if matches and matches[0].containment >= RECENSION:
        return "overlap", matches, joint
    return "new", matches, joint


__all__ = ["DUPLICATE", "K", "Match", "RECENSION", "SketchIndex", "classify", "han", "load_sketch", "sample", "store_signatures"]
