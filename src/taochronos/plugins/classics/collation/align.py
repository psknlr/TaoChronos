"""Aligning two long witnesses.

Two transcriptions of a work share most of their text but differ in variants, lacunae, added commentary and, now
and then, the order of passages.  A character-level edit distance over whole books is too slow and gets lost in long
insertions, so the alignment is anchored: k-grams that occur exactly once in each text are paired, the longest chain
of pairs increasing in both texts (patience sorting) is kept, anchors on one diagonal are merged into matched runs,
and the stretches between runs are aligned again — with shorter anchors while they are long, with ``difflib`` once
they are short.  What cannot be anchored even with short k-grams is one replaced block (a different text there).
"""

from __future__ import annotations

import bisect
import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

Op = tuple[str, int, int, int, int]  # tag, b0, b1, w0, w1 — like difflib opcodes
HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff〓□]")


def han_only(text: str) -> tuple[str, list[int]]:
    """The Han characters of a text (punctuation, spaces and markup dropped) and their offsets."""
    index = [i for i, ch in enumerate(text) if HAN.match(ch)]
    return "".join(text[i] for i in index), index


@dataclass
class WitnessText:
    """A witness as a string of normalised Han characters, mapped back to its passages."""

    siglum: str
    book_id: str | None
    text: str  # normalised Han characters
    raw: str  # the same characters as written (same length)
    where: list[tuple[int, int]] = field(default_factory=list)  # per character: (passage index, offset in its text)
    passages: list[tuple[str, str, str]] = field(default_factory=list)  # (passage id, locator label, layer)

    @classmethod
    def build(cls, siglum: str, book_id: str | None, rows: list[tuple[str, str, str, str]], normalize) -> "WitnessText":
        """``rows``: (passage id, locator label, layer, text) in reading order."""
        norm: list[str] = []
        raw: list[str] = []
        where: list[tuple[int, int]] = []
        passages = []
        for k, (pid, label, layer, text) in enumerate(rows):
            passages.append((pid, label, layer))
            n = normalize(text)
            chars, index = han_only(n)
            norm.append(chars)
            raw.append("".join(text[i] for i in index))
            where.extend((k, i) for i in index)
        return cls(siglum, book_id, "".join(norm), "".join(raw), where, passages)

    def locate(self, i: int) -> tuple[str | None, str, str]:
        """(passage id, locator, layer) of character ``i``."""
        if not self.where:
            return None, "", ""
        k, _ = self.where[min(max(i, 0), len(self.where) - 1)]
        pid, label, layer = self.passages[k]
        return pid, label, layer


def _unique(s: str, k: int, lo: int, hi: int) -> dict[str, int]:
    counts = Counter(s[i: i + k] for i in range(lo, hi - k + 1))
    return {s[i: i + k]: i for i in range(lo, hi - k + 1) if counts[s[i: i + k]] == 1}


def _chain(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest chain of anchor pairs increasing in both texts (patience sorting, O(n log n))."""
    if not pairs:
        return []
    pairs.sort()
    tails: list[int] = []
    tails_at: list[int] = []
    prev = [-1] * len(pairs)
    for idx, (_, w) in enumerate(pairs):
        j = bisect.bisect_left(tails, w)
        if j == len(tails):
            tails.append(w)
            tails_at.append(idx)
        else:
            tails[j] = w
            tails_at[j] = idx
        prev[idx] = tails_at[j - 1] if j else -1
    out = []
    idx = tails_at[-1]
    while idx >= 0:
        out.append(pairs[idx])
        idx = prev[idx]
    return out[::-1]


def align(b: str, w: str, *, k: int = 12, min_k: int = 4, local: int = 240) -> list[Op]:
    """Opcodes turning ``b`` into ``w`` (``equal`` / ``replace`` / ``delete`` / ``insert``)."""
    ops: list[Op] = []
    _align(b, w, 0, len(b), 0, len(w), k, min_k, local, ops)
    return _merge(ops)


def _align(b: str, w: str, b0: int, b1: int, w0: int, w1: int, k: int, min_k: int, local: int, ops: list[Op]) -> None:
    if b0 >= b1 and w0 >= w1:
        return
    if b0 >= b1:
        ops.append(("insert", b0, b0, w0, w1))
        return
    if w0 >= w1:
        ops.append(("delete", b0, b1, w0, w0))
        return
    nb, nw = b1 - b0, w1 - w0
    if nb <= local and nw <= local:
        for tag, i0, i1, j0, j1 in difflib.SequenceMatcher(None, b[b0:b1], w[w0:w1], autojunk=False).get_opcodes():
            ops.append((tag, b0 + i0, b0 + i1, w0 + j0, w0 + j1))
        return
    kk = min(k, nb, nw)
    while kk >= min_k:
        ub = _unique(b, kk, b0, b1)
        uw = _unique(w, kk, w0, w1)
        chain = _chain([(i, uw[g]) for g, i in ub.items() if g in uw])
        if chain:
            break
        kk -= 2
    else:
        chain = []
    if not chain:
        # no unique anchors: a repetitive stretch, or a short stretch against a long one — align it directly while
        # that is affordable, else it is a different text here
        if min(nb, nw) <= 8 or nb * nw <= 4_000_000:
            for tag, i0, i1, j0, j1 in difflib.SequenceMatcher(None, b[b0:b1], w[w0:w1], autojunk=False).get_opcodes():
                ops.append((tag, b0 + i0, b0 + i1, w0 + j0, w0 + j1))
        else:
            ops.append(("replace", b0, b1, w0, w1))
        return
    runs: list[list[int]] = []  # [b start, b end, w start, w end], equal text
    for i, j in chain:
        if runs:
            pb, pw = runs[-1][1], runs[-1][3]
            if i - runs[-1][0] == j - runs[-1][2] and i <= pb:  # same diagonal, overlapping: extend
                end = i + kk
                if end > pb:
                    runs[-1][1] = end
                    runs[-1][3] = runs[-1][2] + (end - runs[-1][0])
                continue
            shift = max(pb - i, pw - j, 0)  # another diagonal overlapping the last run: trim the anchor
            if shift >= kk:
                continue
            i, j = i + shift, j + shift
            runs.append([i, i + kk - shift, j, j + kk - shift])
        else:
            runs.append([i, i + kk, j, j + kk])
    cb, cw = b0, w0
    for run in runs:
        bs, be, ws, we = run
        while bs > cb and ws > cw and b[bs - 1] == w[ws - 1]:  # extend matched runs over non-unique text
            bs, ws = bs - 1, ws - 1
        _align(b, w, cb, bs, cw, ws, max(min_k, kk - 2), min_k, local, ops)
        ops.append(("equal", bs, be, ws, we))
        cb, cw = be, we
    _align(b, w, cb, b1, cw, w1, max(min_k, kk - 2), min_k, local, ops)


def _merge(ops: list[Op]) -> list[Op]:
    out: list[Op] = []
    for op in ops:
        tag, b0, b1, w0, w1 = op
        if b0 == b1 and w0 == w1:
            continue
        if out and out[-1][0] == tag and out[-1][2] == b0 and out[-1][4] == w0:
            out[-1] = (tag, out[-1][1], b1, out[-1][3], w1)
        else:
            out.append(op)
    # adjacent delete + insert (or insert + delete) at one point form a replacement
    merged: list[Op] = []
    for op in out:
        if merged and {merged[-1][0], op[0]} == {"delete", "insert"} and merged[-1][2] == op[1] and merged[-1][4] == op[3]:
            prev = merged.pop()
            merged.append(("replace", prev[1], op[2], prev[3], op[4]))
        else:
            merged.append(op)
    return merged


def matched(ops: list[Op]) -> int:
    """Characters of the base found in the witness."""
    return sum(b1 - b0 for tag, b0, b1, _, _ in ops if tag == "equal")


__all__ = ["Op", "WitnessText", "align", "matched"]
