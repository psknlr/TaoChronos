"""The registry of textual cruxes (校勘疑义): which clauses of a classic its commentators judged transposed, miswritten,
interpolated or lost, and where such a clause stands in any witness.

The registry is data (``domains/classics/cruxes.yaml``), harvested from the commentaries in the corpus store by
``taochronos study cruxes`` (``plugins/classics/study/cruxes.py``) and reviewable like any other domain file.  The
index finds a crux in a text through the clause's 4-grams — half of them suffice — so a witness with other characters,
other punctuation, an edition's numbering or a word more or less still matches; it reports where the clause and its
doubted words (the target) stand, and who doubts them.  It records doubts; it does not decide the reading.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Callable, Iterable

HAN = re.compile(r"[一-鿿㐀-䶿]")
K = 4  # clause grams: specific enough over a whole clause, short enough to survive a variant or an added character
NUMBERING = re.compile(r"(?:第[一二三四五六七八九十百零〇]+|[一二三四五六七八九十百零〇]+方)$")  # an edition's numbering, not text


def han_view(text: str) -> tuple[str, list[int]]:
    """The Han characters of a text and, for each, its offset in the text."""
    chars, offsets = [], []
    for i, ch in enumerate(text):
        if HAN.match(ch):
            chars.append(ch)
            offsets.append(i)
    return "".join(chars), offsets


class CruxIndex:
    """Looks up the cruxes a stretch of (normalised) text rests on."""

    def __init__(self, entries: Iterable[dict[str, Any]], normalize: Callable[[str], str] | None = None, *,
                 coverage: float = 0.5) -> None:
        self.normalize = normalize or (lambda t: t)
        self.coverage = coverage
        self.entries: list[dict[str, Any]] = []
        self._grams: dict[str, set[int]] = {}
        self._size: list[int] = []
        for e in entries:
            clause = NUMBERING.sub("", han_view(self.normalize(e.get("clause", "")))[0])
            if len(clause) < 2 * K:
                continue
            entry = dict(e, clause=clause, target=han_view(self.normalize(e.get("target") or ""))[0] or None)
            idx = len(self.entries)
            self.entries.append(entry)
            grams = {clause[i: i + K] for i in range(len(clause) - K + 1)}
            self._size.append(len(grams))
            for g in grams:
                self._grams.setdefault(g, set()).add(idx)

    def __len__(self) -> int:
        return len(self.entries)

    @lru_cache(maxsize=4096)
    def _located(self, norm: str) -> tuple[tuple[int, int, int, int, int], ...]:
        """(entry, clause start, clause end, target start, target end) for every crux clause present in ``norm`` —
        spans in ``norm``'s offsets; the target span is (-1, -1) when the entry names no words or they are absent."""
        han, offsets = han_view(norm)
        hits: dict[int, list[int]] = {}
        for i in range(len(han) - K + 1):
            for idx in self._grams.get(han[i: i + K], ()):
                hits.setdefault(idx, []).append(i)
        out = []
        for idx, positions in hits.items():
            if len(set(han[p: p + K] for p in positions)) < self.coverage * self._size[idx]:
                continue
            lo, hi = min(positions), max(positions) + K
            start, end = offsets[lo], offsets[hi - 1] + 1
            target = self.entries[idx]["target"]
            ts = te = -1
            if target:
                at = han.find(target, max(0, lo - 2), hi + 2)
                if at >= 0:
                    ts, te = offsets[at], offsets[at + len(target) - 1] + 1
                else:
                    continue  # the doubted words are not in this witness: this crux is not its problem
            out.append((idx, start, end, ts, te))
        return tuple(sorted(out, key=lambda x: (x[1], x[0])))

    def overlapping(self, norm: str, lo: int, hi: int, spans: Iterable[tuple[int, int]] = ()) -> list[dict[str, Any]]:
        """The cruxes whose clause overlaps [lo, hi) of the normalised text.  A crux that names the doubted words touches
        the span only when those words lie inside it and — given the claim's argument spans — overlap one of them: a
        claim that does not rest on the doubted words is not touched by the doubt."""
        spans = [(a, b) for a, b in spans if a is not None and b is not None]
        found = []
        for idx, start, end, ts, te in self._located(norm):
            if not (start < hi and lo < end):
                continue
            if ts >= 0 and not (lo <= ts and te <= hi):
                continue
            if ts >= 0 and spans and not any(a < te and ts < b for a, b in spans):
                continue
            e = self.entries[idx]
            found.append({"id": e.get("id"), "kinds": e.get("kinds", []), "target": e.get("target"), "proposed": e.get("proposed"),
                          "span": [start, end], "by": [b.get("commentator") for b in e.get("by", [])][:6],
                          "commentators": e.get("commentators", len(e.get("by", [])))})
        return found


def load_cruxes(path: Any, normalize: Callable[[str], str] | None = None) -> CruxIndex:
    from ...protocol.yamlio import load_yaml

    data = load_yaml(path) if path is not None and path.exists() else {}
    return CruxIndex((data or {}).get("cruxes") or [], normalize)


__all__ = ["CruxIndex", "han_view", "load_cruxes"]
