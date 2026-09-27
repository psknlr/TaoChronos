"""Synthetic pages with a known reading: text laid out as a 刻本 lays it out, then read back as an OCR engine reports it.

``layout_text`` pours a text (notes in （…）) into vertical columns read right to left: a main character takes a row of
its column; a note runs in 双行小注 — two half-width lines down the rest of the column, the right one first — and, when
the column ends, goes on at the top of the next.  A fold column (版心: title, 卷, leaf number) stands beside the frame and
head-notes (书眉) above it.  ``tokens`` then reports the page as an engine does: one box per run of one column (main
text, each half of a note), coordinates jittered, in no particular order.  The truth — the running text and each
token's kind — comes with it, for the ``layout`` suite and the tests.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

from .layout import Token


@dataclass
class Segment:
    text: str
    x: float
    y: float
    w: float
    h: float
    kind: str  # main | commentary | header | page_number | margin


def _pieces(text: str) -> list[tuple[str, bool]]:
    out = []
    for m in re.finditer(r"（([^（）]*)）|([^（）]+)", text):
        if m.group(1) is not None:
            out.append((m.group(1), True))
        elif m.group(2):
            out.append((m.group(2), False))
    return out


def layout_text(text: str, *, rows: int = 20, size: float = 40.0, spacing: float = 1.3, max_cols: int = 12,
                title: str | None = None, leaf: str | None = None, head_note: str | None = None) -> tuple[list[Segment], str]:
    """(segments, the text that fits on the page with its notes)."""
    segs: list[Segment] = []
    right = size * (max_cols * spacing + 2)
    col, row = 0, 0
    top = size * 2
    placed: list[str] = []
    for piece, is_note in _pieces(text):
        if col >= max_cols:
            break
        if not is_note:
            k = 0
            while k < len(piece) and col < max_cols:
                take = min(rows - row, len(piece) - k)
                x = right - (col + 1) * spacing * size
                segs.append(Segment(piece[k: k + take], x, top + row * size, size, take * size, "main"))
                placed.append(piece[k: k + take])
                k += take
                row += take
                if row >= rows:
                    col, row = col + 1, 0
            continue
        k, note = 0, []
        while k < len(piece) and col < max_cols:
            free = rows - row
            chunk = piece[k: k + 2 * free]
            half = (len(chunk) + 1) // 2
            x = right - (col + 1) * spacing * size
            first, second = chunk[:half], chunk[half:]
            segs.append(Segment(first, x + size / 2, top + row * size, size / 2, len(first) * size, "commentary"))
            if second:
                segs.append(Segment(second, x, top + row * size, size / 2, len(second) * size, "commentary"))
            note.append(chunk)
            k += len(chunk)
            row += half
            if row >= rows:
                col, row = col + 1, 0
        placed.append("（" + "".join(note) + "）")
    left = right - (max_cols + 1) * spacing * size
    if title:
        segs.append(Segment(title, left - size * 0.6, top, size / 2, len(title) * size / 2, "header"))
    if leaf:
        segs.append(Segment(leaf, left - size * 0.6, top + rows * size - len(leaf) * size / 2, size / 2, len(leaf) * size / 2,
                            "page_number"))
    if head_note:
        segs.append(Segment(head_note, right - 3 * spacing * size, top - size * 1.4, size / 2, len(head_note) * size / 2 * 0.5,
                            "margin"))
    return segs, re.sub(r"）（", "", "".join(placed))


def tokens(segs: list[Segment], *, jitter: float = 0.05, seed: int = 0) -> tuple[list[Token], dict[str, str]]:
    """The segments as an engine reports them: jittered boxes, shuffled; and each token's true kind."""
    rng = random.Random(seed)
    out, kinds = [], {}
    for i, s in enumerate(segs):
        j = lambda v, scale: v + rng.uniform(-jitter, jitter) * scale  # noqa: E731
        size = s.w
        t = Token(s.text, j(s.x, size), j(s.y, size), max(1.0, j(s.w, size)), max(1.0, j(s.h, size)), id=f"t{i + 1}")
        out.append(t)
        kinds[t.id] = s.kind
    rng.shuffle(out)
    return out, kinds


__all__ = ["Segment", "layout_text", "tokens"]
