"""版面与阅读顺序 — a page of a traditional Chinese book read in its own order (T1).

An OCR or HTR engine (PaddleOCR, Tesseract, Kraken, Transkribus, a vision model …) finds text and its boxes; it does
not know how a 刻本 is laid out.  This module does, from the boxes alone:

* **orientation** — vertical columns read right to left (the default of the classics), or horizontal rows;
* **the size of a character** of the main text (the median width of the columns), and each segment's size against it:
  main text, small text (notes, 版心, 书眉) and large text (titles);
* **双行小注** — two half-width columns side by side in one column slot are one interlinear note, read down the right
  half and then the left; a note may continue into the next column;
* **版心 and 书眉** — small text outside the frame of the main columns: the fold column (title, 卷, leaf number) and
  head-notes above the frame are kept as blocks of their own, out of the running text;
* **reading order** — column slots right to left, each top to bottom, notes where they stand in their column.

The result is a ``PageGraph``: blocks with their kind, box and order, and the running text with notes in （…） as the
transcriptions of the store write them — so an OCR text can be collated with a transcription (``compare``).
Every block keeps the rule that typed it; nothing is invented, only ordered and labelled.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

PAGE_NUMBER = re.compile(r"^[一二三四五六七八九十百〇零]+$")
HEADER_WORDS = re.compile(r"卷|巻|页|葉|叶|第[一二三四五六七八九十百]+")


@dataclass
class Token:
    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float | None = None
    kind: str | None = None  # a kind the engine already knows (seal, figure)
    id: str = ""

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Block:
    id: str
    kind: str  # main | commentary | title | header | page_number | margin | seal | figure
    text: str
    bbox: list[float]
    order: int | None = None
    slot: int | None = None
    rule: str = ""
    parts: list[str] = field(default_factory=list)  # token ids (a note: right half, then left half)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageGraph:
    page: dict[str, Any]
    orientation: str
    char_size: float
    blocks: list[Block]
    text: str  # the running text: main text and notes in （…）, in reading order
    apparatus: list[dict[str, Any]]  # header, page number and margin blocks, out of the running text
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "orientation": self.orientation, "char_size": round(self.char_size, 2),
                "blocks": [b.to_dict() for b in self.blocks], "text": self.text, "apparatus": self.apparatus,
                "reading_order": [b.id for b in sorted((b for b in self.blocks if b.order is not None), key=lambda b: b.order)],
                "notes": self.notes}


def _merge_characters(tokens: list[Token]) -> list[Token]:
    """Single-character boxes (an engine that reads character by character) joined into column segments: characters
    clustered by the centre of their column (a note's two halves are two columns), then split where a column breaks —
    a vertical gap, or a change of size (main text to note)."""
    singles = [t for t in tokens if len(t.text) == 1]
    if len(singles) < 0.6 * len(tokens) or len(singles) < 4:
        return tokens
    ordered = sorted(singles, key=lambda t: t.cx)
    clusters: list[list[Token]] = [[ordered[0]]]
    for t in ordered[1:]:
        last = clusters[-1][-1]
        if t.cx - last.cx <= 0.2 * min(t.w, last.w):
            clusters[-1].append(t)
        else:
            clusters.append([t])
    merged: list[Token] = []
    for cluster in clusters:
        run: list[Token] = []
        for t in sorted(cluster, key=lambda t: t.y):
            if run:
                prev = run[-1]
                if t.y - (prev.y + prev.h) > 0.5 * min(t.h, prev.h) or abs(t.w - prev.w) > 0.25 * max(t.w, prev.w):
                    merged.append(_join(run))
                    run = []
            run.append(t)
        if run:
            merged.append(_join(run))
    return merged + [t for t in tokens if len(t.text) != 1]


def _join(run: list[Token]) -> Token:
    x0, y0 = min(t.x for t in run), min(t.y for t in run)
    x1, y1 = max(t.x + t.w for t in run), max(t.y + t.h for t in run)
    return Token("".join(t.text for t in run), x0, y0, x1 - x0, y1 - y0, id=run[0].id)


def analyse(tokens: Iterable[Token], *, page: dict[str, Any] | None = None) -> PageGraph:
    toks = [t for t in tokens if t.text and t.w > 0 and t.h > 0]
    for i, t in enumerate(toks):
        t.id = t.id or f"t{i + 1}"
    toks = _merge_characters(toks)
    page = dict(page or {})
    if not toks:
        return PageGraph(page, "unknown", 0.0, [], "", [], ["no text on the page"])
    longish = [t for t in toks if len(t.text) >= 3] or toks
    vertical = statistics.median(t.h / t.w for t in longish) >= 1.3
    if not vertical:
        return _horizontal(toks, page)
    # the size of a main-text character: the wide end of the columns (notes, 版心 and 书眉 are half as wide; a page can
    # carry more note than text, so the median width may be a note's) — the 90th percentile by characters, then the
    # median of the columns near it
    widths = sorted((t.w, len(t.text)) for t in toks if t.kind not in ("seal", "figure"))
    total = sum(n for _, n in widths)
    acc, p90 = 0, widths[-1][0]
    for w, n in widths:
        acc += n
        if acc >= total * 0.9:
            p90 = w
            break
    near = [t.w for t in toks if 0.8 * p90 <= t.w <= 1.25 * p90]
    size = statistics.median(near) if near else p90
    main = [t for t in toks if 0.75 * size <= t.w <= 1.35 * size and t.kind not in ("seal", "figure")]
    if len(main) >= 2:
        size = statistics.median(t.w for t in main)
    frame_x0 = min(t.x for t in main) if main else min(t.x for t in toks)
    frame_x1 = max(t.x + t.w for t in main) if main else max(t.x + t.w for t in toks)
    frame_y0 = min(t.y for t in main) if main else min(t.y for t in toks)
    frame_y1 = max(t.y + t.h for t in main) if main else max(t.y + t.h for t in toks)
    blocks: list[Block] = []
    small: list[Token] = []
    for t in toks:
        box = [round(t.x, 1), round(t.y, 1), round(t.w, 1), round(t.h, 1)]
        if t.kind in ("seal", "figure"):
            blocks.append(Block(t.id, t.kind, t.text, box, rule="given by the engine", parts=[t.id]))
        elif t.w > 1.35 * size:
            blocks.append(Block(t.id, "title", t.text, box, rule=f"wider than the main text ({t.w / size:.2f}×)", parts=[t.id]))
        elif t.w >= 0.75 * size:
            blocks.append(Block(t.id, "main", t.text, box, rule="main-text width", parts=[t.id]))
        else:
            small.append(t)
    # small text: first the halves of 双行小注 — two small columns side by side whose heights overlap, wherever they
    # stand (a column that holds only a note lies outside the main columns' frame); then what is left: above or below
    # the frame 书眉 and footers, beside it the 版心, inside it a single-line note
    pairs: list[tuple[Token, Token]] = []
    used: set[str] = set()
    ordered = sorted(small, key=lambda t: (-t.cx, t.y))
    for t in ordered:
        if t.id in used or t.y + t.h <= frame_y0 - 0.1 * size or t.y >= frame_y1 + 0.5 * size:
            continue
        for u in ordered:
            if u.id == t.id or u.id in used or u.cx >= t.cx:
                continue
            gap = t.x - (u.x + u.w)
            overlap = min(t.y + t.h, u.y + u.h) - max(t.y, u.y)
            if -0.3 * size <= gap <= 0.4 * size and overlap >= 0.4 * min(t.h, u.h) and abs(t.y - u.y) <= 0.6 * size:
                pairs.append((t, u))
                used.update((t.id, u.id))
                break
    for t, u in pairs:
        x0, y0 = min(t.x, u.x), min(t.y, u.y)
        x1, y1 = max(t.x + t.w, u.x + u.w), max(t.y + t.h, u.y + u.h)
        blocks.append(Block(f"{t.id}+{u.id}", "commentary", t.text + u.text,
                            [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)],
                            rule="双行小注: two half-width columns side by side, right half first", parts=[t.id, u.id]))
    note_x = [b.bbox for b in blocks if b.kind == "commentary"]
    left_edge = min([frame_x0] + [bx[0] for bx in note_x])
    right_edge = max([frame_x1] + [bx[0] + bx[2] for bx in note_x])
    slots = sorted({round(t.cx / (0.5 * size)) for t in main})
    centers_x = sorted(t.cx for t in main)
    gaps = [b - a for a, b in zip(centers_x, centers_x[1:]) if b - a > 0.6 * size]
    pitch = statistics.median(gaps) if gaps else 1.3 * size
    for t in small:
        if t.id in used:
            continue
        box = [round(t.x, 1), round(t.y, 1), round(t.w, 1), round(t.h, 1)]
        headerish = bool(PAGE_NUMBER.match(t.text) or HEADER_WORDS.search(t.text))
        if t.y + t.h <= frame_y0 - 0.1 * size or t.y >= frame_y1 + 0.5 * size:
            blocks.append(Block(t.id, "margin", t.text, box, rule="small text above or below the frame", parts=[t.id]))
        elif (not headerish and abs(t.y - frame_y0) <= size and slots
              and (0 < left_edge - t.cx <= 1.6 * pitch or 0 < t.cx - right_edge <= 1.6 * pitch)):
            blocks.append(Block(t.id, "commentary", t.text, box, parts=[t.id],
                                rule="a note run on to the top of the next column (one column beside the text)"))
        elif t.x + t.w <= left_edge + 0.1 * size or t.x >= right_edge - 0.1 * size or (
                (PAGE_NUMBER.match(t.text) or HEADER_WORDS.search(t.text))
                and (t.x < frame_x0 + 0.6 * size or t.x + t.w > frame_x1 - 0.6 * size)):
            kind = "page_number" if PAGE_NUMBER.match(t.text) else "header"
            blocks.append(Block(t.id, kind, t.text, box, rule="small text beside the frame (版心)", parts=[t.id]))
        else:
            blocks.append(Block(t.id, "commentary", t.text, box, rule="small text inside the frame (a single-line note)",
                                parts=[t.id]))
    # reading order: column slots right to left, each top to bottom
    flow = [b for b in blocks if b.kind in ("main", "commentary", "title")]
    centers: list[float] = []
    for b in sorted(flow, key=lambda b: -(b.bbox[0] + b.bbox[2] / 2)):
        c = b.bbox[0] + b.bbox[2] / 2
        for k, cc in enumerate(centers):
            if abs(cc - c) < 0.6 * size:
                b.slot = k
                break
        else:
            centers.append(c)
            b.slot = len(centers) - 1
    flow.sort(key=lambda b: (b.slot, b.bbox[1]))
    parts: list[str] = []
    for k, b in enumerate(flow):
        b.order = k
        parts.append(f"（{b.text}）" if b.kind == "commentary" else b.text)
    text = re.sub(r"）（", "", "".join(parts))  # a note running on into the next column is one note
    apparatus = [{"id": b.id, "kind": b.kind, "text": b.text, "bbox": b.bbox} for b in blocks if b.order is None]
    page.setdefault("size", [round(max(t.x + t.w for t in toks), 1), round(max(t.y + t.h for t in toks), 1)])
    return PageGraph(page, "vertical-rtl", size, blocks, text, apparatus,
                     [f"{len(flow)} blocks in {len(centers)} column slots; {sum(1 for b in flow if b.kind == 'commentary')} notes"])


def _horizontal(toks: list[Token], page: dict[str, Any]) -> PageGraph:
    """Rows left to right, top to bottom (modern prints, some manuscripts)."""
    size = statistics.median(t.h for t in toks)
    rows: list[list[Token]] = []
    for t in sorted(toks, key=lambda t: t.cy):
        for row in rows:
            if abs(row[0].cy - t.cy) < 0.5 * size:
                row.append(t)
                break
        else:
            rows.append([t])
    blocks, parts, k = [], [], 0
    for row in rows:
        for t in sorted(row, key=lambda t: t.x):
            kind = "main" if t.h >= 0.75 * size else "commentary"
            blocks.append(Block(t.id, kind, t.text, [round(t.x, 1), round(t.y, 1), round(t.w, 1), round(t.h, 1)], order=k,
                                rule="horizontal rows", parts=[t.id]))
            parts.append(f"（{t.text}）" if kind == "commentary" else t.text)
            k += 1
    return PageGraph(page, "horizontal-ltr", size, blocks, "".join(parts), [], ["horizontal layout: rows left to right"])


__all__ = ["Block", "PageGraph", "Token", "analyse"]
