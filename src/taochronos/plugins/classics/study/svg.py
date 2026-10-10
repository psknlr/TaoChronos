"""Chart specifications (``charts.py``) as standalone SVG figures and CSV tables — ``taochronos study … --charts <dir>``.

The web client draws the same specifications with hover, a table view and downloads (``web/js/chart.js``); this module
writes them as static files for papers and notes: SVG with its colours and fonts inline (it opens anywhere and scales
without loss), and the table behind it as CSV (UTF-8 with a byte-order mark, so that spreadsheet programs read the
Chinese).  The marks follow one specification: hairline, solid, recessive grid and axes; bars at most 24 px thick with a
4 px rounded data end; 2 px lines; 8 px markers with a 2 px ring of the surface; a 2 px surface gap between stacked
segments; a legend whenever there are two series or more; text in ink, never in a series colour.  The categorical colours
are a validated colour-vision-safe order (eight at most: the builders fold the rest into 其他); magnitudes in heatmaps are
one blue from light to dark.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any
from xml.sax.saxutils import escape

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95",
        "#104281", "#0d366b"]
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
OTHER = "#b3b1aa"  # 其他: the folded tail, in the de-emphasis grey (never a ninth hue)


def series_colors(labels: list[str]) -> list[str]:
    """The categorical slots in order; 其他 in grey."""
    out, k = [], 0
    for label in labels:
        if label == "其他":
            out.append(OTHER)
        else:
            out.append(PALETTE[k] if k < len(PALETTE) else OTHER)
            k += 1
    return out


def group_colors(spec: dict[str, Any], seen: list[str]) -> dict[str, str]:
    """Colours by group: by its place in the order the specification gives (``groups``), so that a category keeps its
    colour in every chart of a result whichever groups each one shows; groups it does not list follow, in the order they
    appear.  The groups seen, in that order."""
    listed = [str(g) for g in spec.get("groups") or []]
    order = listed + [g for g in seen if g not in listed]
    colors = dict(zip(order, series_colors(order)))
    return {g: colors[g] for g in order if g in seen}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif"
WIDTH = 760


def text_width(text: str, size: float) -> float:
    """Estimated width: a CJK character is as wide as the font size, others about 0.58 of it."""
    return sum(size if ord(ch) > 0x2e80 else size * 0.58 for ch in str(text))


def nice_max(v: float) -> float:
    """The top of an axis: the next of 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8 (× a power of ten) — never far above the data."""
    if v <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(v))
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= step * mag + 1e-12:
            return step * mag
    return 10 * mag


def ticks(lo: float, hi: float, n: int = 5, integer: bool = False) -> list[float]:
    """Round ticks over [lo, hi]; ``integer``: no fractions (counts)."""
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    steps = [s * max(1, mag) for s in (1, 2, 5, 10)] if integer else [s * mag for s in (1, 2, 2.5, 5, 10)]
    step = next((s for s in steps if raw <= s + 1e-12), steps[-1])
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + step * 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def fmt(v: Any, percent: bool = False) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        if percent:
            return f"{v * 100:.0f}%" if abs(v) >= 0.1 or v == 0 else f"{v * 100:.1f}%"
        if abs(v) >= 1000:
            return f"{v / 1000:.1f}K".replace(".0K", "K")
        if float(v).is_integer():
            return str(int(v))
        return f"{v:.3g}"
    return str(v)


def _t(x: float, y: float, s: str, *, size: float = 11, fill: str = INK2, anchor: str = "start", weight: str = "normal",
       baseline: str = "auto") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"'
            f' dominant-baseline="{baseline}">{escape(str(s))}</text>')


def _legend(items: list[tuple[str, str]], x: float, y: float, width: float, kind: str = "rect") -> tuple[list[str], float]:
    out, cx, cy = [], x, y
    for label, color in items:
        w = 18 + text_width(label, 11) + 16
        if cx + w > x + width and cx > x:
            cx, cy = x, cy + 18
        mark = (f'<rect x="{cx:.1f}" y="{cy - 9:.1f}" width="10" height="10" rx="2" fill="{color}"/>' if kind == "rect" else
                f'<line x1="{cx:.1f}" y1="{cy - 4:.1f}" x2="{cx + 12:.1f}" y2="{cy - 4:.1f}" stroke="{color}" stroke-width="2"/>')
        out += [mark, _t(cx + 16, cy, label, size=11, fill=INK2)]
        cx += w
    return out, cy + 10


def _rounded_bar(x: float, y: float, w: float, h: float, *, up: bool = True, r: float = 4) -> str:
    """A bar with its data end rounded (4 px) and its baseline end square."""
    r = min(r, w / 2, abs(h))
    if h <= 0 or w <= 0:
        return ""
    if up:  # vertical, data end at the top
        return (f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} "
                f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h:.1f} Z")
    # horizontal, data end at the right: x is the baseline, w the length, h the thickness
    return (f"M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h - r:.1f} "
            f"Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} L{x:.1f},{y + h:.1f} Z")


class _Frame:
    """The title, subtitle and footer around a plot, and the plot's box."""

    def __init__(self, spec: dict[str, Any], height: int) -> None:
        self.spec = spec
        self.parts: list[str] = []
        self.top = 24
        title = spec.get("title", "")
        self.parts.append(_t(20, self.top, title, size=15, fill=INK, weight="600"))
        self.top += 8
        if spec.get("subtitle"):
            for line in _wrap(spec["subtitle"], WIDTH - 40, 11.5):
                self.top += 16
                self.parts.append(_t(20, self.top, line, size=11.5, fill=INK2))
        self.top += 18
        self.height = height

    def legend(self, items: list[tuple[str, str]], kind: str = "rect") -> None:
        if len(items) >= 2:
            parts, bottom = _legend(items, 20, self.top + 2, WIDTH - 40, kind)
            self.parts += parts
            self.top = bottom + 10

    def finish(self, plot_bottom: float) -> str:
        y = plot_bottom + 8
        for line in [x for x in (self.spec.get("note"), self.spec.get("source")) if x]:
            for part in _wrap(line, WIDTH - 40, 10):
                y += 14
                self.parts.append(_t(20, y, part, size=10, fill=MUTED))
        h = int(y + 16)
        body = "\n".join(self.parts)
        title = escape(self.spec.get("title", "chart"))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {h}" width="{WIDTH}" height="{h}" '
                f'font-family="{escape(FONT)}" role="img" aria-label="{title}">\n<title>{title}</title>\n'
                f'<rect width="100%" height="100%" fill="{SURFACE}"/>\n{body}\n</svg>\n')


def _wrap(text: str, width: float, size: float) -> list[str]:
    lines, cur = [], ""
    for ch in str(text):
        if text_width(cur + ch, size) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def _whole(values: list[Any]) -> bool:
    """Are these counts (whole numbers)?  Their axis then has no fractions."""
    return all(float(v).is_integer() for v in values if v is not None and v != "")


def _y_axis(parts: list[str], left: float, right: float, top: float, bottom: float, lo: float, hi: float, percent: bool,
            label: str, integer: bool = False) -> Any:
    scale = (lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)) if hi > lo else (lambda v: bottom)
    for t in ticks(lo, hi, integer=integer and not percent):
        y = scale(t)
        parts.append(f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{right:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(_t(left - 6, y + 4, fmt(t, percent), size=10.5, fill=MUTED, anchor="end"))
    parts.append(f'<line x1="{left:.1f}" y1="{bottom:.1f}" x2="{right:.1f}" y2="{bottom:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    if label:
        parts.append(_t(left, top - 8, label, size=10.5, fill=MUTED))
    return scale


def _x_labels(parts: list[str], cats: list[str], xs: list[float], bottom: float, band: float) -> float:
    """Category labels under the axis, rotated when they do not fit their band."""
    longest = max((text_width(c, 10.5) for c in cats), default=0)
    if longest <= band - 4:
        for c, x in zip(cats, xs):
            parts.append(_t(x, bottom + 16, c, size=10.5, fill=INK2, anchor="middle"))
        return bottom + 22
    for c, x in zip(cats, xs):
        parts.append(f'<text x="{x:.1f}" y="{bottom + 12:.1f}" font-size="10.5" fill="{INK2}" text-anchor="end" '
                     f'transform="rotate(-40 {x:.1f} {bottom + 12:.1f})">{escape(str(c))}</text>')
    return bottom + 12 + longest * 0.7


# ------------------------------------------------------------------ chart types
def _series_chart(spec: dict[str, Any]) -> str:
    kind = spec["type"]
    rows = spec.get("rows", [])
    xkey = spec["x"]["key"]
    series = spec.get("series", [])[:8]
    y = spec.get("y", {})
    percent = bool(y.get("percent")) or (kind == "stack" and spec.get("percent"))
    colors = series_colors([s["label"] for s in series])
    frame = _Frame(spec, 0)
    frame.legend([(s["label"], colors[i]) for i, s in enumerate(series)], "line" if kind == "line" else "rect")
    left, right = 60, WIDTH - 24
    top, bottom = frame.top + 14, frame.top + 14 + 260
    cats = [str(r.get(xkey, "")) for r in rows]
    if kind == "stack":
        totals = [sum(float(r.get(s["key"]) or 0) for s in series) for r in rows]
        hi = 1.0 if spec.get("percent") else nice_max(max(totals or [0]))
        lo = 0.0
        whole = _whole(totals)
    else:
        vals = [float(r[k]) for r in rows for s in series for k in (s["key"], s.get("hi")) if k and r.get(k) is not None]
        hi = y.get("max") or nice_max(max(vals or [0]))
        lo = y.get("min", 0) if y.get("min") is not None else min(0.0, min(vals or [0]))
        whole = _whole(vals)
    scale = _y_axis(frame.parts, left, right, top, bottom, lo, hi, percent, y.get("label", ""), whole)
    band = (right - left) / max(len(rows), 1)
    xs = [left + band * (i + 0.5) for i in range(len(rows))]
    p = frame.parts
    if kind == "line":
        for i, s in enumerate(series):
            color = colors[i]
            if s.get("lo") and s.get("hi"):
                pts = [(x, r.get(s["hi"])) for x, r in zip(xs, rows) if r.get(s["hi"]) is not None]
                low = [(x, r.get(s["lo"])) for x, r in zip(xs, rows) if r.get(s["lo"]) is not None]
                if pts and low:
                    path = " ".join(f"{x:.1f},{scale(float(v)):.1f}" for x, v in pts + low[::-1])
                    p.append(f'<polygon points="{path}" fill="{color}" fill-opacity="0.1"/>')
            pts = [(x, r.get(s["key"])) for x, r in zip(xs, rows) if r.get(s["key"]) is not None]
            if len(pts) >= 2:
                p.append(f'<polyline points="{" ".join(f"{x:.1f},{scale(float(v)):.1f}" for x, v in pts)}" fill="none" '
                         f'stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            for x, v in pts:
                p.append(f'<circle cx="{x:.1f}" cy="{scale(float(v)):.1f}" r="4" fill="{color}" stroke="{SURFACE}" stroke-width="2"/>')
            if pts:  # the end value, labelled
                x, v = pts[-1]
                p.append(_t(x, scale(float(v)) - 9, fmt(v, percent), size=10.5, fill=INK, anchor="middle"))
    elif kind == "bar":
        n = max(len(series), 1)
        bw = min(24.0, (band - 8) / n - 2)
        for j, r in enumerate(rows):
            x0 = xs[j] - (bw + 2) * n / 2 + 1
            for i, s in enumerate(series):
                v = r.get(s["key"])
                if v is None:
                    continue
                yv = scale(float(v))
                p.append(f'<path d="{_rounded_bar(x0 + i * (bw + 2), yv, bw, scale(lo) - yv)}" fill="{colors[i]}"/>')
                if s.get("lo") and r.get(s["lo"]) is not None and r.get(s.get("hi")) is not None:
                    cx = x0 + i * (bw + 2) + bw / 2
                    p.append(f'<line x1="{cx:.1f}" y1="{scale(float(r[s["lo"]])):.1f}" x2="{cx:.1f}" y2="{scale(float(r[s["hi"]])):.1f}" '
                             f'stroke="{INK2}" stroke-width="1"/>')
                if n == 1 and len(rows) <= 14:
                    p.append(_t(x0 + bw / 2, yv - 5, fmt(v, percent), size=10, fill=INK2, anchor="middle"))
    else:  # stack
        bw = min(24.0, band - 8)
        for j, r in enumerate(rows):
            total = sum(float(r.get(s["key"]) or 0) for s in series) or 1.0
            acc = 0.0
            for i, s in enumerate(series):
                v = float(r.get(s["key"]) or 0)
                if spec.get("percent"):
                    v /= total
                if v <= 0:
                    continue
                y1, y2 = scale(acc + v), scale(acc)
                h = max(y2 - y1 - 2, 0.5)  # the 2 px surface gap between segments
                p.append(f'<rect x="{xs[j] - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{colors[i]}"/>')
                acc += v
    end = _x_labels(p, cats, xs, bottom, band)
    return frame.finish(end)


def _hbar(spec: dict[str, Any]) -> str:
    rows = spec.get("rows", [])
    xkey = spec["x"]["key"]
    s = (spec.get("series") or [{}])[0]
    percent = bool(spec.get("y", {}).get("percent"))
    frame = _Frame(spec, 0)
    label_w = min(220.0, max((text_width(r.get(xkey, ""), 11) for r in rows), default=40) + 12)
    left, right = 20 + label_w, WIDTH - 70
    top = frame.top + 6
    step = 24
    vals = [float(r.get(s["key"]) or 0) for r in rows]
    lo = min(0.0, min(vals or [0]))
    hi = nice_max(max(vals or [0]))
    scale = (lambda v: left + (v - lo) / (hi - lo) * (right - left)) if hi > lo else (lambda v: left)
    p = frame.parts
    bottom = top + step * len(rows)
    for t in ticks(lo, hi, 4, integer=_whole(vals) and not percent):
        x = scale(t)
        p.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{bottom:.1f}" stroke="{GRID}" stroke-width="1"/>')
        p.append(_t(x, bottom + 14, fmt(t, percent), size=10.5, fill=MUTED, anchor="middle"))
    for i, r in enumerate(rows):
        v = float(r.get(s["key"]) or 0)
        y = top + i * step + 4
        p.append(_t(left - 8, y + 12, r.get(xkey, ""), size=11, fill=INK2, anchor="end"))
        x0, x1 = scale(0), scale(v)
        if x1 >= x0:
            p.append(f'<path d="{_rounded_bar(x0, y, x1 - x0, 16, up=False)}" fill="{PALETTE[0]}"/>')
        else:
            p.append(f'<rect x="{x1:.1f}" y="{y:.1f}" width="{x0 - x1:.1f}" height="16" fill="{PALETTE[0]}"/>')
        p.append(_t(max(x0, x1) + 6, y + 12, fmt(v, percent), size=10.5, fill=INK))
    p.append(f'<line x1="{scale(0):.1f}" y1="{top:.1f}" x2="{scale(0):.1f}" y2="{bottom:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    return frame.finish(bottom + 20)


def _heatmap(spec: dict[str, Any]) -> str:
    rows = spec.get("rows", [])
    xk, yk, vk = spec["x"]["key"], spec["y"]["key"], spec["value"]["key"]
    xs = spec["x"].get("order") or list(dict.fromkeys(r[xk] for r in rows))
    ys = spec["y"].get("order") or list(dict.fromkeys(r[yk] for r in rows))
    percent = bool(spec["value"].get("percent"))
    cell = {(r[xk], r[yk]): r.get(vk) for r in rows}
    vmax = spec["value"].get("max") or max([float(v) for v in cell.values() if v is not None] or [1]) or 1
    frame = _Frame(spec, 0)
    label_w = min(200.0, max((text_width(y, 11) for y in ys), default=30) + 12)
    left = 20 + label_w
    cw = min(64.0, (WIDTH - 24 - left) / max(len(xs), 1))
    ch = 24.0
    top = frame.top + 34
    p = frame.parts
    for i, x in enumerate(xs):
        cx = left + cw * (i + 0.5)
        label = str(x)
        if text_width(label, 10.5) <= cw - 2:
            p.append(_t(cx, top - 8, label, size=10.5, fill=INK2, anchor="middle"))
        else:
            p.append(f'<text x="{cx:.1f}" y="{top - 6:.1f}" font-size="10.5" fill="{INK2}" text-anchor="start" '
                     f'transform="rotate(-40 {cx:.1f} {top - 6:.1f})">{escape(label)}</text>')
    for j, y in enumerate(ys):
        cy = top + ch * j
        p.append(_t(left - 8, cy + ch / 2 + 4, y, size=11, fill=INK2, anchor="end"))
        for i, x in enumerate(xs):
            v = cell.get((x, y))
            if v is None:
                fill = "#f0efec"
            else:
                k = min(len(RAMP) - 1, int(float(v) / vmax * (len(RAMP) - 1) + 0.5)) if vmax else 0
                fill = RAMP[k] if float(v) > 0 else "#f0efec"
            p.append(f'<rect x="{left + cw * i + 1:.1f}" y="{cy + 1:.1f}" width="{cw - 2:.1f}" height="{ch - 2:.1f}" rx="2" fill="{fill}"/>')
            if v is not None and float(v) > 0:
                k = int(float(v) / vmax * (len(RAMP) - 1) + 0.5) if vmax else 0
                txt = fmt(v, percent)
                if text_width(txt, 10) <= cw - 6:
                    p.append(_t(left + cw * (i + 0.5), cy + ch / 2 + 4, txt, size=10, fill="#ffffff" if k >= 6 else INK, anchor="middle"))
    bottom = top + ch * len(ys)
    # the scale
    sx = left
    for k, color in enumerate(RAMP):
        p.append(f'<rect x="{sx + k * 14:.1f}" y="{bottom + 12:.1f}" width="14" height="8" fill="{color}"/>')
    p.append(_t(sx, bottom + 34, "0", size=10, fill=MUTED))
    p.append(_t(sx + 14 * len(RAMP), bottom + 34, fmt(vmax, percent), size=10, fill=MUTED, anchor="end"))
    p.append(_t(sx + 14 * len(RAMP) + 10, bottom + 20, spec["value"].get("label", ""), size=10.5, fill=MUTED))
    return frame.finish(bottom + 40)


def _range(spec: dict[str, Any]) -> str:
    rows = spec.get("rows", [])
    keys = spec["range"]
    xkey = spec["x"]["key"]
    frame = _Frame(spec, 0)
    left, right = 60, WIDTH - 24
    top, bottom = frame.top + 14, frame.top + 14 + 240
    vals = [float(r[keys[k]]) for r in rows for k in ("min", "max") if r.get(keys[k]) is not None]
    boxes = [float(r[keys[k]]) for r in rows for k in ("q3", "median") if r.get(keys[k]) is not None]
    # the axis reads the boxes: a few very large values (a whole batch) would flatten them, so it stops at 2.5× the largest
    # upper quartile and longer whiskers are cut there, their value written at the top (the table has every number)
    hi = nice_max(min(max(vals or [1]), max(boxes or [1]) * 2.5))
    scale = _y_axis(frame.parts, left, right, top, bottom, 0.0, hi, False, spec.get("y", {}).get("label", ""))
    clip = lambda v: min(float(v), hi)
    band = (right - left) / max(len(rows), 1)
    xs = [left + band * (i + 0.5) for i in range(len(rows))]
    p = frame.parts
    for x, r in zip(xs, rows):
        lo_, q1, med, q3, hi_ = (r.get(keys[k]) for k in ("min", "q1", "median", "q3", "max"))
        if lo_ is not None and hi_ is not None:
            p.append(f'<line x1="{x:.1f}" y1="{scale(clip(lo_)):.1f}" x2="{x:.1f}" y2="{scale(clip(hi_)):.1f}" stroke="{PALETTE[0]}" stroke-width="1"/>')
            if float(hi_) > hi:
                p.append(f'<path d="M{x - 4:.1f},{top + 6:.1f} L{x:.1f},{top:.1f} L{x + 4:.1f},{top + 6:.1f}" fill="none" stroke="{PALETTE[0]}" stroke-width="1"/>')
                p.append(_t(x + 6, top + 6, f"↑{fmt(hi_)}", size=10, fill=MUTED))
        if q1 is not None and q3 is not None:
            y1, y3 = scale(clip(q3)), scale(clip(q1))
            p.append(f'<rect x="{x - 10:.1f}" y="{y1:.1f}" width="20" height="{max(y3 - y1, 1):.1f}" rx="3" fill="{PALETTE[0]}" fill-opacity="0.25" '
                     f'stroke="{PALETTE[0]}" stroke-width="1"/>')
        if med is not None:
            p.append(f'<circle cx="{x:.1f}" cy="{scale(float(med)):.1f}" r="4.5" fill="{PALETTE[0]}" stroke="{SURFACE}" stroke-width="2"/>')
            p.append(_t(x + 14, scale(float(med)) + 4, fmt(med), size=10.5, fill=INK))
    end = _x_labels(p, [str(r.get(xkey, "")) for r in rows], xs, bottom, band)
    return frame.finish(end)


def _timeline(spec: dict[str, Any]) -> str:
    rows = sorted((r for r in spec.get("rows", []) if r.get("start") is not None), key=lambda r: float(r["start"]))
    color = group_colors(spec, list(dict.fromkeys(str(r.get("group", "")) for r in rows)))
    frame = _Frame(spec, 0)
    frame.legend([(g, c) for g, c in color.items() if g])
    left, right = 40, WIDTH - 40
    years = [float(r["start"]) for r in rows] or [0.0, 1.0]
    lo, hi = min(years), max(years)
    if hi - lo < 50:
        lo, hi = lo - 25, hi + 25
    pad = (hi - lo) * 0.04
    lo, hi = lo - pad, hi + pad
    scale = lambda v: left + (v - lo) / (hi - lo) * (right - left)
    lanes: list[tuple[float, float]] = []  # each lane's occupied span
    placed = []
    for r in rows:
        x = scale(float(r["start"]))
        w = text_width(r.get("label", ""), 10.5) + 14
        flip = x + w > WIDTH - 8  # near the right edge the label goes to the left of its dot
        span = (x - w, x + 6) if flip else (x - 6, x + w)
        lane = next((i for i, (a, b) in enumerate(lanes) if b < span[0] - 2 or a > span[1] + 2), None)
        if lane is None:
            lanes.append(span)
            lane = len(lanes) - 1
        else:
            a, b = lanes[lane]
            lanes[lane] = (min(a, span[0]), max(b, span[1]))
        placed.append((r, x, lane, flip))
    top = frame.top + 12
    axis = top + 22 * max(len(lanes), 1) + 10
    p = frame.parts
    for t in ticks(lo, hi, 6):
        x = scale(t)
        p.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{axis:.1f}" stroke="{GRID}" stroke-width="1"/>')
        p.append(_t(x, axis + 16, f"{int(t)}" if t >= 0 else f"前{int(-t)}", size=10.5, fill=MUTED, anchor="middle"))
    p.append(f'<line x1="{left}" y1="{axis:.1f}" x2="{right}" y2="{axis:.1f}" stroke="{AXIS}" stroke-width="1"/>')
    for r, x, lane, flip in placed:
        y = top + 22 * lane + 8
        c = color[str(r.get("group", ""))]
        p.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{axis:.1f}" stroke="{c}" stroke-width="1" stroke-opacity="0.35"/>')
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{c}" stroke="{SURFACE}" stroke-width="2"/>')
        p.append(_t(x - 7 if flip else x + 7, y + 4, r.get("label", ""), size=10.5, fill=INK, anchor="end" if flip else "start"))
    return frame.finish(axis + 22)


def hub_of(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str | None:
    """The node every edge touches, when the graph is a hub with spokes (a formula and the formulas built on it)."""
    if not edges:
        return None
    ends = [{e["source"], e["target"]} for e in edges]
    common = set.intersection(*ends)
    return next(iter(common)) if len(common) == 1 and len(edges) == len(nodes) - 1 else None


def _network(spec: dict[str, Any]) -> str:
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])
    color = group_colors(spec, list(dict.fromkeys(str(n.get("group", "")) for n in nodes)))
    frame = _Frame(spec, 0)
    frame.legend([(g, c) for g, c in color.items() if g])
    hub = hub_of(nodes, edges)
    if hub is not None:
        return _star(spec, frame, nodes, edges, hub, color)
    cx, cy = WIDTH / 2, frame.top + 200
    radius = 160
    centre = next((n for n in nodes if n["id"] == "base"), None)
    ring = [n for n in nodes if n is not centre]
    pos = {}
    if centre is not None:
        pos[centre["id"]] = (cx, cy)
    for i, n in enumerate(ring):
        a = -math.pi / 2 + 2 * math.pi * i / max(len(ring), 1)
        pos[n["id"]] = (cx + radius * math.cos(a), cy + radius * math.sin(a))
    sizes = [float(n.get("size") or 1) for n in nodes] or [1]
    smax = max(sizes)
    rad = lambda n: 5 + 9 * math.sqrt(float(n.get("size") or 1) / smax)
    wmax = max([float(e.get("weight") or 1) for e in edges] or [1])
    p = frame.parts
    for e in edges:
        if e["source"] in pos and e["target"] in pos:
            (x1, y1), (x2, y2) = pos[e["source"]], pos[e["target"]]
            p.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{AXIS}" '
                     f'stroke-width="{1 + 2 * float(e.get("weight") or 1) / wmax:.1f}"/>')
    for n in nodes:
        x, y = pos[n["id"]]
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad(n):.1f}" fill="{color.get(str(n.get("group", "")), OTHER)}" stroke="{SURFACE}" stroke-width="2"/>')
        if n is centre:
            p.append(_t(x, y - rad(n) - 6, n.get("label", ""), size=12, fill=INK, anchor="middle", weight="600"))
        else:
            right = x >= cx
            p.append(_t(x + (rad(n) + 4) * (1 if right else -1), y + 4, n.get("label", ""), size=10.5, fill=INK,
                        anchor="start" if right else "end"))
    return frame.finish(cy + radius + 30)


def _star(spec: dict[str, Any], frame: _Frame, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], hub: str,
          color: dict[str, str]) -> str:
    """A hub and its spokes: the hub on the left, the others in a column on the right (in the order given), each edge
    with its label — no label crosses another."""
    centre = next(n for n in nodes if n["id"] == hub)
    others = [n for n in nodes if n["id"] != hub]
    by_target = {e["target"] if e["source"] == hub else e["source"]: e for e in edges}
    step = 22
    top = frame.top + 10
    height = step * max(len(others), 1)
    hx, hy = 140, top + height / 2
    col = 360
    sizes = [float(n.get("size") or 1) for n in nodes]
    smax = max(sizes) if sizes else 1
    rad = lambda n: 4 + 7 * math.sqrt(float(n.get("size") or 1) / smax)
    p = frame.parts
    for i, n in enumerate(others):
        y = top + step * i + step / 2
        e = by_target.get(n["id"], {})
        p.append(f'<path d="M{hx:.1f},{hy:.1f} C{(hx + col) / 2:.1f},{hy:.1f} {(hx + col) / 2:.1f},{y:.1f} {col:.1f},{y:.1f}" '
                 f'fill="none" stroke="{AXIS}" stroke-width="1"/>')
        p.append(f'<circle cx="{col:.1f}" cy="{y:.1f}" r="{rad(n):.1f}" fill="{color.get(str(n.get("group", "")), OTHER)}" '
                 f'stroke="{SURFACE}" stroke-width="2"/>')
        p.append(_t(col + 14, y + 4, n.get("label", ""), size=11, fill=INK))
        if e.get("label"):
            p.append(_t(col + 24 + text_width(n.get("label", ""), 11), y + 4, e["label"], size=10, fill=MUTED))
    p.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{rad(centre) + 2:.1f}" fill="{color.get(str(centre.get("group", "")), OTHER)}" '
             f'stroke="{SURFACE}" stroke-width="2"/>')
    p.append(_t(hx - rad(centre) - 8, hy + 5, centre.get("label", ""), size=13, fill=INK, anchor="end", weight="600"))
    return frame.finish(top + height + 10)


def to_svg(spec: dict[str, Any]) -> str:
    """A chart specification as a standalone SVG document."""
    kind = spec.get("type")
    if kind in ("line", "bar", "stack"):
        return _series_chart(spec)
    return {"hbar": _hbar, "heatmap": _heatmap, "range": _range, "timeline": _timeline, "network": _network}[kind](spec)


def to_csv(spec: dict[str, Any], *, bom: bool = True) -> str:
    """The table behind a chart (its rows, in its columns' order and labels); a network's edges."""
    buf = io.StringIO()
    w = csv.writer(buf)
    if spec.get("type") == "network" and spec.get("edges"):
        label = {n["id"]: n.get("label", n["id"]) for n in spec.get("nodes", [])}
        w.writerow(["来源", "目标", "权重", "说明"])
        for e in spec["edges"]:
            w.writerow([label.get(e["source"], e["source"]), label.get(e["target"], e["target"]), e.get("weight", ""), e.get("label", "")])
    else:
        cols = spec.get("columns") or [{"key": k, "label": k} for k in (spec.get("rows") or [{}])[0]]
        w.writerow([c["label"] for c in cols])
        for r in spec.get("rows", []):
            w.writerow(["" if r.get(c["key"]) is None else r.get(c["key"]) for c in cols])
    return ("﻿" if bom else "") + buf.getvalue()


def write(charts: list[dict[str, Any]], out_dir: Any, stem: str) -> list[str]:
    """Each chart as <stem>-<id>.svg, .csv and .json in ``out_dir``; the paths written."""
    import json
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, c in enumerate(charts, 1):
        name = f"{stem}-{c.get('id') or i}"
        for ext, text in (("svg", to_svg(c)), ("csv", to_csv(c)), ("json", json.dumps(c, ensure_ascii=False, indent=1))):
            path = out / f"{name}.{ext}"
            path.write_text(text, encoding="utf-8")
            written.append(str(path))
    return written


__all__ = ["PALETTE", "RAMP", "to_csv", "to_svg", "write"]
