"""OCR outputs read into layout tokens: ALTO XML, hOCR, PAGE XML, PaddleOCR results and a plain JSON list.

Every engine reports text with boxes in its own format; the layout module wants ``Token(text, x, y, w, h)``.  A line
(``TextLine``, ``ocr_line``) is one token — for vertical text, one column or part of one.  Words and characters inside a
line are joined; if an engine gives only characters, the layout merges them into columns itself.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .layout import Token

FORMATS = ("alto", "hocr", "page", "paddle", "tokens")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_alto(text: str) -> list[Token]:
    root = ET.fromstring(text)
    out: list[Token] = []
    for line in (e for e in root.iter() if _local(e.tag) == "TextLine"):
        strings = [s for s in line if _local(s.tag) == "String"]
        content = "".join(s.get("CONTENT", "") for s in strings)
        box = [line.get(k) for k in ("HPOS", "VPOS", "WIDTH", "HEIGHT")]
        if not content or None in box:
            continue
        conf = [float(s.get("WC")) for s in strings if s.get("WC")]
        out.append(Token(content, *(float(v) for v in box), conf=sum(conf) / len(conf) if conf else None,
                         id=line.get("ID", "")))
    return out


def read_hocr(text: str) -> list[Token]:
    out: list[Token] = []
    for m in re.finditer(r"<(\w+)[^>]*class=['\"](?:ocr_line|ocrx_line|ocr_textfloat)['\"][^>]*title=['\"]([^'\"]*)['\"][^>]*>(.*?)</\1>",
                         text, re.S):
        bbox = re.search(r"bbox (\d+) (\d+) (\d+) (\d+)", m.group(2))
        content = re.sub(r"<[^>]+>", "", m.group(3))
        content = re.sub(r"\s+", "", content)
        if bbox and content:
            x0, y0, x1, y1 = (float(v) for v in bbox.groups())
            conf = re.search(r"x_wconf (\d+)", m.group(3))
            out.append(Token(content, x0, y0, x1 - x0, y1 - y0, conf=float(conf.group(1)) / 100 if conf else None))
    return out


def read_page(text: str) -> list[Token]:
    root = ET.fromstring(text)
    out: list[Token] = []
    for line in (e for e in root.iter() if _local(e.tag) == "TextLine"):
        coords = next((c for c in line if _local(c.tag) == "Coords"), None)
        unicode_ = [u.text or "" for u in line.iter() if _local(u.tag) == "Unicode"]
        if coords is None or not unicode_:
            continue
        pts = [tuple(float(v) for v in p.split(",")) for p in (coords.get("points") or "").split()]
        if not pts:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append(Token(unicode_[-1].strip(), min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), id=line.get("id", "")))
    return out


def read_paddle(data: Any) -> list[Token]:
    """PaddleOCR: [[points, [text, confidence]], …] (one list per page, or the page itself)."""
    if data and isinstance(data[0], list) and data[0] and isinstance(data[0][0], list) and len(data[0]) == 2 \
            and isinstance(data[0][1], (list, tuple)) and isinstance(data[0][1][0], str):
        rows = data
    else:
        rows = [r for page in data for r in (page or [])]
    out: list[Token] = []
    for points, (content, conf) in rows:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        out.append(Token(content, min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), conf=float(conf)))
    return out


def read_tokens(data: Any) -> list[Token]:
    """[{"text": …, "bbox": [x, y, w, h]} …] (or "box": [x0, y0, x1, y1])."""
    out: list[Token] = []
    for i, row in enumerate(data):
        if "bbox" in row:
            x, y, w, h = row["bbox"]
        else:
            x0, y0, x1, y1 = row["box"]
            x, y, w, h = x0, y0, x1 - x0, y1 - y0
        out.append(Token(row["text"], float(x), float(y), float(w), float(h), conf=row.get("conf"), kind=row.get("kind"),
                         id=row.get("id", f"t{i + 1}")))
    return out


def read_file(path: str | Path, fmt: str | None = None) -> list[Token]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    fmt = fmt or _guess(p, text)
    if fmt == "alto":
        return read_alto(text)
    if fmt == "hocr":
        return read_hocr(text)
    if fmt == "page":
        return read_page(text)
    data = json.loads(text)
    return read_paddle(data) if fmt == "paddle" else read_tokens(data)


def _guess(path: Path, text: str) -> str:
    head = text[:2000]
    if "<alto" in head:
        return "alto"
    if "PcGts" in head:
        return "page"
    if "ocr_line" in text[:20000] or "ocr_page" in head:
        return "hocr"
    stripped = head.lstrip()
    if stripped.startswith("[") and ("[[" in stripped[:6] or stripped.startswith("[[[")):
        return "paddle"
    return "tokens"


__all__ = ["FORMATS", "read_alto", "read_file", "read_hocr", "read_page", "read_paddle", "read_tokens"]
