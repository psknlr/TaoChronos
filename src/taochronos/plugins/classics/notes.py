"""Interlinear notes (夹注) in a text: the stretches in brackets, a note inside a note included."""

from __future__ import annotations

import re

# an interlinear note, and one with the editors' square brackets too (what a collation leaves out)
NOTE = re.compile(r"（[^（）]*）|\([^()]*\)|〔[^〔〕]*〕|【[^【】]*】")
NOTE_OR_SQUARE = re.compile(r"（[^（）]*）|\([^()]*\)|〔[^〔〕]*〕|【[^【】]*】|\[[^\[\]]*\]")
# how deep notes are read inside notes.  The classics nest them two or three deep; the text is a caller's too, and each
# level is a pass over the whole of it: brackets nested tens of thousands deep (a text of nothing else, within what the
# site takes) cost the square of the text — minutes of one call — before the levels had a bound
DEPTH = 32


def note_spans(text: str, pattern: re.Pattern[str] = NOTE, depth: int = DEPTH) -> tuple[str, list[tuple[int, int]]]:
    """``text`` with its notes blanked out — as long as it was, so that offsets into it stay valid — and the stretches
    blanked, ``(start, end)``: the innermost notes first, then what encloses them once they are blank (so a later
    stretch holds the earlier ones inside it), to ``depth`` levels."""
    spans: list[tuple[int, int]] = []
    for _ in range(depth):
        found = [m.span() for m in pattern.finditer(text)]
        if not found:
            break
        parts: list[str] = []
        at = 0
        for start, end in found:
            parts.append(text[at:start])
            parts.append(" " * (end - start))
            at = end
        parts.append(text[at:])
        text = "".join(parts)
        spans += found
    return text, spans


def blank_notes(text: str, pattern: re.Pattern[str] = NOTE) -> str:
    """``text`` with its notes blanked out (as long as it was)."""
    return note_spans(text, pattern)[0]


def note_mask(text: str, pattern: re.Pattern[str] = NOTE) -> bytearray:
    """1 for every character inside a note (the brackets, and nested notes, included)."""
    mask = bytearray(len(text))
    for start, end in note_spans(text, pattern)[1]:
        mask[start:end] = b"\x01" * (end - start)
    return mask
