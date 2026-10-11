"""Chart specifications (``charts.py``) as standalone SVG figures and CSV tables — ``taochronos study … --charts <dir>``.

The web client draws the same specifications with hover, a table view and downloads (``web/js/chart.js``, whose layout
this module follows); this module writes them as static files for papers and notes, in one of two styles:

* **journal** (the default for files): a figure as a journal prints it — white, black L-shaped axes with outward ticks,
  no grid, the y-axis title turned along its axis, square bars, error bars with caps, sans-serif text whose sizes are a
  journal's (8 pt ticks and labels at the printed width), the figure's number and caption under it (图 1　…, then its
  notes and source), and a physical size (85 mm a single column, 120 mm one and a half, 175 mm two) — and several
  charts as one figure in panels (A, B …) with one caption;
* **screen**: the page's look — the title above, a recessive grid, 4 px rounded data ends.

The marks follow one specification in both: hairline axes, 2 px lines, 8 px markers ringed with the surface, a 2 px
surface gap between stacked segments, a legend whenever there are two series or more, text in ink, never in a series
colour.  The categorical colours are a validated colour-vision-safe order (eight at most: the builders fold the rest into
其他); magnitudes in heatmaps are one blue from light to dark.  The table behind each chart is written as CSV (UTF-8 with
a byte-order mark, so that spreadsheet programs read the Chinese).
"""

from __future__ import annotations

import contextlib
import csv
import io
import math
from dataclasses import dataclass
from typing import Any, Iterator
from xml.sax.saxutils import escape

from ....science.stats import tukey

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95",
        "#104281", "#0d366b"]
OTHER = "#b3b1aa"  # 其他: the folded tail, in the de-emphasis grey (never a ninth hue)
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif"
FONT_JOURNAL = "Arial, Helvetica, 'Noto Sans CJK SC', 'Source Han Sans SC', 'PingFang SC', 'Microsoft YaHei', SimHei, sans-serif"
WIDTH = 760  # the screen figure, px
WIDTHS_MM = {"single": 85, "onehalf": 120, "double": 175}  # a journal's column widths
PX_PER_MM = 72 / 25.4 / (8 / 10.5)  # a journal figure's units: 10.5 of them print as 8 pt


@dataclass(frozen=True)
class Style:
    name: str
    surface: str
    ink: str
    ink2: str
    muted: str
    grid: str | None  # None: no grid (the journal's)
    axis: str
    empty: str
    font: str
    journal: bool
    radius: float  # the rounded data end of a bar


SCREEN = Style("screen", "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#f0efec", FONT, False, 4)
JOURNAL = Style("journal", "#ffffff", "#000000", "#1a1a1a", "#4d4d4d", None, "#000000", "#f2f2f2", FONT_JOURNAL, True, 0)
S = SCREEN


@contextlib.contextmanager
def _style(style: Style) -> Iterator[None]:
    global S
    old, S = S, style
    try:
        yield
    finally:
        S = old


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


WIDE = set("…—")  # as wide as a CJK character in the fonts a figure names


def text_width(text: str, size: float) -> float:
    """Estimated width: a CJK character (and an ellipsis or a dash) is as wide as the font size, others about 0.58 of it."""
    return sum(size if ord(ch) > 0x2e80 or ch in WIDE else size * 0.58 for ch in str(text))


def clip_text(text: Any, size: float, room: float) -> str:
    """A label cut to the room it has, with an ellipsis (the table and the hover keep it whole)."""
    s = str(text)
    if text_width(s, size) <= room:
        return s
    out = ""
    for ch in s:
        if text_width(out + ch + "…", size) > room:
            break
        out += ch
    return (out or s[:1]) + "…"


def _box_of(x: float, y: float, w: float, size: float, anchor: str = "start") -> tuple[float, float, float, float]:
    """The ink of a label set at (x, y): (x0, y0, x1, y1) — its width by ``text_width``, its height the em box."""
    x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
    return x0, y - 0.84 * size, x0 + w, y + 0.16 * size


def _clash(a: tuple[float, float, float, float], b: tuple[float, float, float, float], gap: float = 1.0) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


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


def log_ticks(lo: float, hi: float) -> list[float]:
    """Ticks of a log axis over [lo, hi]: the powers of ten, with 2 and 5 between them when the axis spans little."""
    a, b = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    mults = (1, 2, 5) if b - a <= 2 else (1,)
    out = [m * 10 ** e for e in range(a, b + 1) for m in mults if lo * 0.999 <= m * 10 ** e <= hi * 1.001]
    return out or [lo, hi]


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


def fmt_est(x: Any) -> str:
    """An estimate (an odds ratio) to the precision its size deserves, as the tables print it: 67.6, 2.43, 0.09."""
    v = _num(x)
    if v is None:
        return ""
    a = abs(v)
    return f"{v:.0f}" if a >= 100 else f"{v:.1f}" if a >= 10 else f"{v:.2f}" if a >= 0.01 or a == 0 else f"{v:.3f}"


def year_text(t: float) -> str:
    return f"前{int(round(-t))}" if t < 0 else str(int(round(t)))


def _num(x: Any) -> float | None:
    if x is None or x == "" or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ------------------------------------------------------------------ SVG pieces
def _t(x: float, y: float, s: Any, *, size: float = 11, fill: str | None = None, anchor: str = "start", weight: str | None = None,
       rotate: float | None = None) -> str:
    attrs = f'x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill or S.ink2}" text-anchor="{anchor}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if rotate is not None:
        attrs += f' transform="rotate({rotate:g} {x:.1f} {y:.1f})"'
    return f"<text {attrs}>{escape(str(s))}</text>"


def _line(x1: float, y1: float, x2: float, y2: float, stroke: str, width: float = 1, extra: str = "") -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width:g}"{extra}/>'


def _bar(x: float, y: float, w: float, h: float, fill: str, *, up: bool = True) -> str:
    """A bar with its data end rounded (the screen's 4 px; square in a journal) and its baseline end square."""
    if h <= 0 or w <= 0:
        return ""
    r = min(S.radius, w / 2, h / 2 if not up else h, (h if up else w))
    if r <= 0:
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"/>'
    if up:
        d = (f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} "
             f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h:.1f} Z")
    else:
        d = (f"M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h - r:.1f} "
             f"Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} L{x:.1f},{y + h:.1f} Z")
    return f'<path d="{d}" fill="{fill}"/>'


def _whisker(x: float, y1: float, y2: float, color: str, cap: float = 4) -> list[str]:
    """An interval as a vertical line, with caps in a journal."""
    out = [_line(x, y1, x, y2, color, 1)]
    if S.journal:
        out += [_line(x - cap, y1, x + cap, y1, color, 1), _line(x - cap, y2, x + cap, y2, color, 1)]
    return out


def _legend(items: list[tuple[str, str]], width: float, kind: str = "rect") -> tuple[list[str], float]:
    if len(items) < 2:
        return [], 0.0
    out, x, y = [], 0.0, 12.0
    for label, color in items:
        label = clip_text(label, 11, width - 20)
        w = 18 + text_width(label, 11) + 16
        if x + w > width and x > 0:
            x, y = 0.0, y + 18
        out.append(_line(x, y - 4, x + 12, y - 4, color, 2) if kind == "line" else
                   f'<rect x="{x:.1f}" y="{y - 9:.1f}" width="10" height="10" rx="{2 if not S.journal else 0}" fill="{color}"/>')
        out.append(_t(x + 16, y, label, size=11))
        x += w
    return out, y + 10


def _whole(values: list[Any]) -> bool:
    """Are these counts (whole numbers)?  Their axis then has no fractions."""
    return all(float(v).is_integer() for v in values if v is not None and v != "")


def _left(tks: list[str], label: str | None) -> float:
    """The room an axis on the left needs: its tick labels, and in a journal its title turned along it."""
    widest = max((text_width(t, 10.5) for t in tks), default=0)
    return max(40.0, widest + 18 + (20 if label else 0)) if S.journal else 52.0


def _y_axis(p: list[str], left: float, right: float, top: float, bottom: float, lo: float, hi: float, percent: bool, label: str,
            integer: bool = False, head: float = 8) -> Any:
    """A y axis; on screen its title above it, ``head`` over the plot's top."""
    scale = (lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)) if hi > lo else (lambda v: bottom)
    tks = ticks(lo, hi, integer=integer and not percent)
    if S.journal:
        p.append(_line(left, top, left, bottom, S.axis))
        for t in tks:
            y = scale(t)
            p.append(_line(left - 4, y, left, y, S.axis))
            p.append(_t(left - 7, y + 3.5, fmt(t, percent), size=10.5, fill=S.ink2, anchor="end"))
        p.append(_line(left, bottom, right, bottom, S.axis))
        if label:
            widest = max((text_width(fmt(t, percent), 10.5) for t in tks), default=0)
            p.append(_t(left - 7 - widest - 9, (top + bottom) / 2, label, size=11, fill=S.ink, anchor="middle", rotate=-90))
        return scale
    for t in tks:
        y = scale(t)
        p.append(_line(left, y, right, y, S.grid or S.axis))
        p.append(_t(left - 6, y + 4, fmt(t, percent), size=10.5, fill=S.muted, anchor="end"))
    p.append(_line(left, bottom, right, bottom, S.axis))
    if label:
        p.append(_t(left, top - head, label, size=10.5, fill=S.muted))
    return scale


TURNED = 112.0  # the longest a turned category label runs before it is cut


def _x_labels(p: list[str], cats: list[str], xs: list[float], bottom: float, band: float, label: str | None = None) -> float:
    """Category labels under the axis (ticks above them in a journal); when they do not fit their band, turned — at 40°
    while neighbours clear each other, upright (reading upwards) in a narrower band, and only every k-th of them in a
    band narrower than a line of text; in a journal the axis title under them."""
    if S.journal:
        for x in xs:
            p.append(_line(x, bottom, x, bottom + 4, S.axis))
    longest = max((text_width(c, 10.5) for c in cats), default=0)
    if longest <= band - 4:
        for c, x in zip(cats, xs):
            p.append(_t(x, bottom + 16, c, size=10.5, fill=S.ink2, anchor="middle"))
        end = bottom + 22
    elif band >= 19:  # at 40° two neighbours are band × sin 40° apart: a line of text needs 12
        shown = [clip_text(c, 10.5, min(TURNED, (x - 8) / 0.77)) for c, x in zip(cats, xs)]  # the first ones: not past the left edge
        for c, x in zip(shown, xs):
            p.append(_t(x, bottom + 12, c, size=10.5, fill=S.ink2, anchor="end", rotate=-40))
        end = bottom + 16 + max(text_width(c, 10.5) for c in shown) * 0.65
    else:
        every = max(1, math.ceil(12.5 / max(band, 1e-9)))
        shown = [clip_text(c, 10.5, TURNED) for c in cats]
        for i, (c, x) in enumerate(zip(shown, xs)):
            if i % every == 0:
                p.append(_t(x + 3.6, bottom + 8, c, size=10.5, fill=S.ink2, anchor="end", rotate=-90))
        end = bottom + 14 + max(text_width(c, 10.5) for c in shown)
    if S.journal and label:
        p.append(_t((xs[0] + xs[-1]) / 2 if xs else 0, end + 12, label, size=11, fill=S.ink, anchor="middle"))
        end += 16
    return end


def _x_axis_numeric(p: list[str], left: float, right: float, bottom: float, lo: float, hi: float, *, label: str = "",
                    percent: bool = False, year: bool = False, log: bool = False, grid_top: float | None = None) -> Any:
    """A numeric axis under a plot: its ticks, and in a journal its line and title; on screen a light grid up the plot."""
    if log:
        lo_l, hi_l = math.log10(lo), math.log10(hi)
        scale = lambda v: left + (math.log10(max(v, 1e-12)) - lo_l) / (hi_l - lo_l) * (right - left)  # noqa: E731
        tks = log_ticks(lo, hi)
    else:
        scale = (lambda v: left + (v - lo) / (hi - lo) * (right - left)) if hi > lo else (lambda v: left)  # noqa: E731
        tks = ticks(lo, hi, 5)
    text = (lambda t: year_text(t)) if year else (lambda t: fmt(t, percent) if not log else (f"{t:g}"))  # noqa: E731
    p.append(_line(left, bottom, right, bottom, S.axis))
    for t in tks:
        x = scale(t)
        if S.journal:
            p.append(_line(x, bottom, x, bottom + 4, S.axis))
        elif grid_top is not None:
            p.append(_line(x, grid_top, x, bottom, S.grid or S.axis))
        p.append(_t(x, bottom + 15, text(t), size=10.5, fill=S.ink2 if S.journal else S.muted, anchor="middle"))
    end = bottom + 20
    if label:
        p.append(_t((left + right) / 2, end + 11, label, size=11 if S.journal else 10.5, fill=S.ink if S.journal else S.muted, anchor="middle"))
        end += 16
    return scale, end


# ------------------------------------------------------------------ the plots: (parts, height) at a width, from (0, 0)
def _series(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    kind = spec["type"]
    rows = spec.get("rows", [])
    xkey = spec["x"]["key"]
    series = spec.get("series", [])[:8]
    y = spec.get("y", {})
    percent = bool(y.get("percent")) or (kind == "stack" and bool(spec.get("percent")))
    colors = series_colors([s["label"] for s in series])
    p, lh = _legend([(s["label"], colors[i]) for i, s in enumerate(series)], width, "line" if kind == "line" else "rect")
    if kind == "stack":
        totals = [sum(_num(r.get(s["key"])) or 0 for s in series) for r in rows]
        lo, hi = 0.0, (1.0 if spec.get("percent") else nice_max(max(totals or [0])))
        whole = _whole(totals)
    else:
        vals = [v for r in rows for s in series for k in (s["key"], s.get("hi"), s.get("lo")) if k for v in [_num(r.get(k))] if v is not None]
        hi = _num(y.get("max")) or nice_max(max(vals or [0]))
        lo = _num(y.get("min")) if _num(y.get("min")) is not None else min(0.0, min(vals or [0]))
        whole = _whole(vals)
    tks = [fmt(t, percent) for t in ticks(lo, hi, integer=whole and not percent)]
    left, right = _left(tks, y.get("label")), width - 16
    top = lh + 22
    bottom = top + min(280, max(170 if S.journal else 180, width * (0.5 if S.journal else 0.42)))
    scale = _y_axis(p, left, right, top, bottom, lo, hi, percent, y.get("label", ""), whole)
    band = (right - left) / max(len(rows), 1)
    xs = [left + band * (i + 0.5) for i in range(len(rows))]
    if kind == "line":
        lines, ends = [], []
        for i, s in enumerate(series):
            color = colors[i]
            if s.get("lo") and s.get("hi"):
                up = [(x, _num(r.get(s["hi"]))) for x, r in zip(xs, rows) if _num(r.get(s["hi"])) is not None]
                down = [(x, _num(r.get(s["lo"]))) for x, r in zip(xs, rows) if _num(r.get(s["lo"])) is not None]
                if up and down:
                    pts = " ".join(f"{x:.1f},{scale(v):.1f}" for x, v in up + down[::-1])
                    p.append(f'<polygon points="{pts}" fill="{color}" fill-opacity="0.12"/>')
            pts = [(x, _num(r.get(s["key"]))) for x, r in zip(xs, rows) if _num(r.get(s["key"])) is not None]
            if len(pts) >= 2:
                p.append(f'<polyline points="{" ".join(f"{x:.1f},{scale(v):.1f}" for x, v in pts)}" fill="none" stroke="{color}" '
                         f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            for x, v in pts:
                p.append(f'<circle cx="{x:.1f}" cy="{scale(v):.1f}" r="4" fill="{color}" stroke="{S.surface}" stroke-width="2"/>')
            lines.append([(x, scale(v)) for x, v in pts])
            if pts:
                ends.append(((pts[-1][0], scale(pts[-1][1])), fmt(pts[-1][1], percent)))
        if not S.journal:  # each line's end value, where it clears the other labels, dots and lines
            p += _end_labels(ends, lines, top)
    elif kind == "bar":
        n = max(len(series), 1)
        bw = max(3.0, min(24.0, (band - 8) / n - 2))
        # a value over each bar of a single series — when every one of them fits its band (else none: the table has them)
        labelled = len(series) == 1 and len(rows) <= 14 and all(text_width(fmt(_num(r.get(series[0]["key"])), percent), 10) <= band - 3
                                                      for r in rows if _num(r.get(series[0]["key"])) is not None)
        for j, r in enumerate(rows):
            x0 = xs[j] - (bw + 2) * n / 2 + 1
            for i, s in enumerate(series):
                v = _num(r.get(s["key"]))
                if v is None:
                    continue
                yv, base = scale(max(v, lo)), scale(max(lo, 0))
                if v >= 0:
                    p.append(_bar(x0 + i * (bw + 2), min(yv, base), bw, abs(base - yv), colors[i]))
                if s.get("lo") and _num(r.get(s["lo"])) is not None and _num(r.get(s.get("hi"))) is not None:
                    p += _whisker(x0 + i * (bw + 2) + bw / 2, scale(_num(r[s["lo"]])), scale(_num(r[s["hi"]])), S.ink2, min(4, bw / 2))
                if labelled:
                    p.append(_t(x0 + bw / 2, yv - 5, fmt(v, percent), size=10, fill=S.ink2, anchor="middle"))
    else:  # stack
        bw = min(24.0, band - 8)
        for j, r in enumerate(rows):
            total = sum(_num(r.get(s["key"])) or 0 for s in series) or 1.0
            acc = 0.0
            for i, s in enumerate(series):
                v = _num(r.get(s["key"])) or 0.0
                if spec.get("percent"):
                    v /= total
                if v <= 0:
                    continue
                y1, y2 = scale(acc + v), scale(acc)
                p.append(f'<rect x="{xs[j] - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{max(y2 - y1 - 2, 0.5):.1f}" fill="{colors[i]}"/>')
                acc += v
    end = _x_labels(p, [str(r.get(xkey, "")) for r in rows], xs, bottom, band, spec["x"].get("label"))
    return p, end + 4


def _end_labels(ends: list[tuple[tuple[float, float], str]], lines: list[list[tuple[float, float]]], top: float) -> list[str]:
    """The end value of each line: above its last point, else below it, wherever it clears the labels set before it, every
    dot and every line (sampled along); a value with room in neither place is left to the hover and the table."""
    out: list[str] = []
    placed: list[tuple[float, float, float, float]] = []
    dots = [pt for pts in lines for pt in pts]
    for (x, y), text in ends:
        w = text_width(text, 10.5)
        for by in (y - 9, y + 17):
            box = _box_of(x, by, w, 10.5, "middle")
            if box[1] < top - 18:
                continue
            if any(_clash(box, b) for b in placed) or any(_clash(box, (dx - 6, dy - 6, dx + 6, dy + 6), 0) for dx, dy in dots):
                continue
            if any(_crosses(pts, box) for pts in lines):
                continue
            placed.append(box)
            out.append(_t(x, by, text, size=10.5, fill=S.ink, anchor="middle"))
            break
    return out


def _crosses(pts: list[tuple[float, float]], box: tuple[float, float, float, float]) -> bool:
    """Does the polyline through ``pts`` pass through the box?"""
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        steps = max(2, int(math.hypot(x2 - x1, y2 - y1) / 2))
        for k in range(steps + 1):
            x, y = x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps
            if box[0] - 1 <= x <= box[2] + 1 and box[1] - 1 <= y <= box[3] + 1:
                return True
    return False


def _hbar(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = spec.get("rows", [])
    xkey = spec["x"]["key"]
    s = (spec.get("series") or [{}])[0]
    percent = bool(spec.get("y", {}).get("percent"))
    p: list[str] = []
    label_w = min(width * 0.36, max([text_width(r.get(xkey, ""), 11) for r in rows] + [30]) + 12)
    left, right = label_w, width - 60
    top, step = 8.0, 24.0 if not S.journal else 20.0
    vals = [_num(r.get(s.get("key"))) or 0.0 for r in rows]
    lo, hi = min(0.0, min(vals or [0])), nice_max(max(vals or [0]))
    scale = (lambda v: left + (v - lo) / (hi - lo) * (right - left)) if hi > lo else (lambda v: left)
    bottom = top + step * len(rows)
    bh = 16 if not S.journal else 13
    for t in ticks(lo, hi, 4, integer=_whole(vals) and not percent):
        x = scale(t)
        if S.journal:
            p.append(_line(x, bottom, x, bottom + 4, S.axis))
        else:
            p.append(_line(x, top, x, bottom, S.grid or S.axis))
        p.append(_t(x, bottom + 15, fmt(t, percent), size=10.5, fill=S.ink2 if S.journal else S.muted, anchor="middle"))
    for i, r in enumerate(rows):
        v = _num(r.get(s.get("key"))) or 0.0
        y = top + i * step + (step - bh) / 2
        p.append(_t(left - 8, y + bh - 3.5, clip_text(r.get(xkey, ""), 11, left - 10), size=11, fill=S.ink2, anchor="end"))
        x0, x1 = scale(0), scale(v)
        p.append(_bar(x0, y, x1 - x0, bh, PALETTE[0], up=False) if x1 >= x0 else
                 f'<rect x="{x1:.1f}" y="{y:.1f}" width="{x0 - x1:.1f}" height="{bh}" fill="{PALETTE[0]}"/>')
        p.append(_t(max(x0, x1) + 6, y + bh - 3.5, fmt(v, percent), size=10.5, fill=S.ink))
    p.append(_line(scale(0), top, scale(0), bottom, S.axis))
    end = bottom + 20
    if S.journal:
        p.append(_line(left, bottom, right, bottom, S.axis))
        label = spec.get("y", {}).get("label")
        if label:
            p.append(_t((left + right) / 2, end + 11, label, size=11, fill=S.ink, anchor="middle"))
            end += 16
    return p, end


def _heatmap(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = spec.get("rows", [])
    xk, yk, vk = spec["x"]["key"], spec["y"]["key"], spec["value"]["key"]
    xs = spec["x"].get("order") or list(dict.fromkeys(r[xk] for r in rows))
    ys = spec["y"].get("order") or list(dict.fromkeys(r[yk] for r in rows))
    percent = bool(spec["value"].get("percent"))
    cell = {(r[xk], r[yk]): _num(r.get(vk)) for r in rows}
    vmax = _num(spec["value"].get("max")) or max([v for v in cell.values() if v is not None] + [1e-9])
    p: list[str] = []
    label_w = min(width * 0.32, max([text_width(y, 11) for y in ys] + [24]) + 12)
    left = label_w
    cw = min(64.0, (width - 12 - left) / max(len(xs), 1))
    ch = 24.0 if not S.journal else 20.0
    centre = lambda i: left + cw * (i + 0.5)  # noqa: E731
    if all(text_width(x, 10.5) <= cw - 2 for x in xs):
        top = 22.0
        for i, x in enumerate(xs):
            p.append(_t(centre(i), top - 8, x, size=10.5, fill=S.ink2, anchor="middle"))
    elif cw >= 19:  # turned 40°, each reaching up and to the right: cut where it would leave the figure
        shown = [clip_text(x, 10.5, min(TURNED, (width - 2 - centre(i)) / 0.77)) for i, x in enumerate(xs)]
        top = 14 + max(text_width(x, 10.5) for x in shown) * 0.65
        for i, x in enumerate(shown):
            p.append(_t(centre(i), top - 6, x, size=10.5, fill=S.ink2, anchor="start", rotate=-40))
    else:  # upright, reading upwards: narrow columns
        shown = [clip_text(x, 10.5, TURNED) for x in xs]
        top = 14 + max(text_width(x, 10.5) for x in shown)
        for i, x in enumerate(shown):
            p.append(_t(centre(i) + 3.6, top - 6, x, size=10.5, fill=S.ink2, anchor="start", rotate=-90))
    for j, y in enumerate(ys):
        cy = top + ch * j
        p.append(_t(left - 8, cy + ch / 2 + 4, clip_text(y, 11, left - 10), size=11, fill=S.ink2, anchor="end"))
        for i, x in enumerate(xs):
            v = cell.get((x, y))
            k = -1 if v is None or v <= 0 else min(len(RAMP) - 1, round(v / vmax * (len(RAMP) - 1)))
            p.append(f'<rect x="{left + cw * i + 1:.1f}" y="{cy + 1:.1f}" width="{cw - 2:.1f}" height="{ch - 2:.1f}" '
                     f'rx="{0 if S.journal else 2}" fill="{RAMP[k] if k >= 0 else S.empty}"/>')
            if v is not None and v > 0:
                label = fmt(v, percent)
                if text_width(label, 10) <= cw - 6:
                    p.append(_t(centre(i), cy + ch / 2 + 4, label, size=10, fill="#ffffff" if k >= 6 else S.ink, anchor="middle"))
    bottom = top + ch * len(ys)
    p += _ramp(left, bottom, width, fmt(vmax, percent), spec["value"].get("label", ""))
    return p, bottom + 42


def _ramp(x0: float, bottom: float, width: float, top_label: str, label: str) -> list[str]:
    """A heatmap's colour scale under it: the ramp from 0 to its largest value, and what the colour counts after it — the
    steps narrowed, then the whole moved left, then the label cut, as a narrow figure needs."""
    seg, room = 14.0, width - 2
    lw = text_width(label, 10.5)
    if x0 + 13 * seg + 10 + lw > room:
        seg = max(7.0, (room - x0 - 10 - lw) / 13)
    if x0 + 13 * seg + 10 + lw > room:
        x0 = max(0.0, room - lw - 10 - 13 * seg)
    end = x0 + 13 * seg
    out = [f'<rect x="{x0 + k * seg:.1f}" y="{bottom + 12:.1f}" width="{seg:.1f}" height="8" fill="{color}"/>' for k, color in enumerate(RAMP)]
    out.append(_t(x0, bottom + 34, "0", size=10, fill=S.muted))
    out.append(_t(end, bottom + 34, top_label, size=10, fill=S.muted, anchor="end"))
    out.append(_t(end + 10, bottom + 20, clip_text(label, 10.5, room - end - 10), size=10.5, fill=S.muted))
    return out


def _range(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = spec.get("rows", [])
    keys = spec["range"]
    xkey = spec["x"]["key"]
    vals = [v for r in rows for k in ("min", "max") for v in [_num(r.get(keys[k]))] if v is not None]
    boxes = [v for r in rows for k in ("q3", "median") for v in [_num(r.get(keys[k]))] if v is not None]
    # the axis reads the boxes: a few very large values would flatten them — it stops at 2.5× the largest upper quartile,
    # longer whiskers are cut there with their value at the top (the table has every number)
    hi = nice_max(min(max(vals or [1]), max(boxes or [1]) * 2.5))
    p: list[str] = []
    label = spec.get("y", {}).get("label", "")
    left, right, top = _left([fmt(t) for t in ticks(0, hi)], label), width - 16, 20.0
    bottom = top + min(260, max(170, width * 0.38))
    scale = _y_axis(p, left, right, top, bottom, 0.0, hi, False, label)
    band = (right - left) / max(len(rows), 1)
    xs = [left + band * (i + 0.5) for i in range(len(rows))]
    for x, r in zip(xs, rows):
        lo_, q1, med, q3, hi_ = (_num(r.get(keys[k])) for k in ("min", "q1", "median", "q3", "max"))
        if lo_ is not None and hi_ is not None:
            p += _whisker(x, scale(min(lo_, hi)), scale(min(hi_, hi)), PALETTE[0])
            if hi_ > hi:
                p.append(f'<path d="M{x - 4:.1f},{top + 6:.1f} L{x:.1f},{top:.1f} L{x + 4:.1f},{top + 6:.1f}" fill="none" stroke="{PALETTE[0]}" stroke-width="1"/>')
                if text_width(f"↑{fmt(hi_)}", 10) <= band - 14:  # clear of the next whisker
                    p.append(_t(x + 6, top + 6, f"↑{fmt(hi_)}", size=10, fill=S.muted))
        if q1 is not None and q3 is not None:
            y1, y3 = scale(min(q3, hi)), scale(min(q1, hi))
            p.append(f'<rect x="{x - 10:.1f}" y="{y1:.1f}" width="20" height="{max(y3 - y1, 1):.1f}" rx="{0 if S.journal else 3}" fill="{PALETTE[0]}" '
                     f'fill-opacity="0.25" stroke="{PALETTE[0]}" stroke-width="1"/>')
        if med is not None:
            p.append(f'<circle cx="{x:.1f}" cy="{scale(min(med, hi)):.1f}" r="4.5" fill="{PALETTE[0]}" stroke="{S.surface}" stroke-width="2"/>')
            if text_width(fmt(med), 10.5) <= band - 27:  # beside its box, clear of the next one
                p.append(_t(x + 14, scale(min(med, hi)) + 4, fmt(med), size=10.5, fill=S.ink))
    end = _x_labels(p, [str(r.get(xkey, "")) for r in rows], xs, bottom, band, spec["x"].get("label"))
    return p, end + 4


def box_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """A box plot's rows with their numbers: as the specification gives them, or computed (Tukey) from its points."""
    xkey = spec["x"]["key"]
    points = spec.get("points") or {}
    out = []
    for r in spec.get("rows", []):
        if all(_num(r.get(k)) is not None for k in ("q1", "median", "q3")):
            out.append(r)
            continue
        vals = r.get("values") if isinstance(r.get("values"), list) else points.get(str(r.get(xkey)))
        t = tukey([v for v in (vals or []) if _num(v) is not None])
        if t:
            out.append({**r, **{k: t[k] for k in ("n", "q1", "median", "q3", "lo", "hi", "mean", "min", "max")}})
    return out


def _jitter(i: int) -> float:
    """A spread in [−0.5, 0.5) that is the same every time (the golden-ratio sequence)."""
    return (i * 0.6180339887) % 1 - 0.5


def _box(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = box_rows(spec)
    xkey = spec["x"]["key"]
    points = spec.get("points") or {}
    values_of = lambda r: [v for v in (r.get("values") if isinstance(r.get("values"), list) else points.get(str(r.get(xkey))) or []) if _num(v) is not None]  # noqa: E731
    whisk = [_num(r.get("hi")) or _num(r.get("q3")) or 0 for r in rows]
    tops = [max([_num(v) for v in values_of(r)] + [_num(r.get("hi")) or 0, _num(r.get("max")) or 0]) for r in rows]
    cap = max(whisk or [1])
    clip = max(tops or [1]) > cap * 2.5
    y = spec.get("y", {})
    lo = _num(y.get("min")) if _num(y.get("min")) is not None else min([0.0] + [_num(r.get("lo")) or 0 for r in rows])
    hi = nice_max(cap * 2.5 if clip else max(tops or [1]) * 1.04)
    p: list[str] = []
    left, right = _left([fmt(t) for t in ticks(lo, hi)], y.get("label")), width - 16
    # values past the axis are counted over their box (▲n) in a row of their own, under the axis title and the key to ▲
    over = clip and any(_num(v) > hi for r in rows for v in values_of(r))
    top = 40.0 if over else 20.0
    bottom = top + min(270, max(170, width * (0.5 if S.journal else 0.4)))
    scale = _y_axis(p, left, right, top, bottom, lo, hi, False, y.get("label", ""), head=top - 12 if over else 8)
    band = (right - left) / max(len(rows), 1)
    xs = [left + band * (i + 0.5) for i in range(len(rows))]
    bw = max(8.0, min(28.0, band * 0.42))
    color = PALETTE[0]
    for x, r in zip(xs, rows):
        q1, med, q3, wlo, whi, mean = (_num(r.get(k)) for k in ("q1", "median", "q3", "lo", "hi", "mean"))
        vals = values_of(r)
        inside = [v for v in vals if wlo is not None and whi is not None and wlo <= _num(v) <= whi]
        if len(vals) <= 300:  # the values themselves, spread beside the box
            for i, v in enumerate(inside):
                p.append(f'<circle cx="{x + _jitter(i) * bw * 1.2:.1f}" cy="{scale(min(_num(v), hi)):.1f}" r="1.8" fill="{color}" fill-opacity="0.35"/>')
        if wlo is not None and whi is not None and q1 is not None and q3 is not None:
            p += [_line(x, scale(min(whi, hi)), x, scale(q3), S.ink2), _line(x, scale(q1), x, scale(wlo), S.ink2),
                  _line(x - bw / 4, scale(min(whi, hi)), x + bw / 4, scale(min(whi, hi)), S.ink2), _line(x - bw / 4, scale(wlo), x + bw / 4, scale(wlo), S.ink2)]
        if q1 is not None and q3 is not None:
            y1, y3 = scale(min(q3, hi)), scale(min(q1, hi))
            p.append(f'<rect x="{x - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{max(y3 - y1, 1):.1f}" fill="{color}" fill-opacity="0.22" '
                     f'stroke="{color}" stroke-width="1.2"/>')
        if med is not None:
            p.append(_line(x - bw / 2, scale(min(med, hi)), x + bw / 2, scale(min(med, hi)), S.ink, 2))
        if mean is not None and mean <= hi:
            ym = scale(mean)
            p.append(f'<path d="M{x - 3.5:.1f},{ym:.1f} L{x:.1f},{ym - 3.5:.1f} L{x + 3.5:.1f},{ym:.1f} L{x:.1f},{ym + 3.5:.1f} Z" fill="{S.surface}" '
                     f'stroke="{S.ink}" stroke-width="1"/>')
        above = 0
        for v in vals:
            v = _num(v)
            if (whi is not None and v > whi) or (wlo is not None and v < wlo):
                if v > hi:
                    above += 1
                    continue
                p.append(f'<circle cx="{x:.1f}" cy="{scale(v):.1f}" r="2.8" fill="{S.surface}" stroke="{color}" stroke-width="1.2"/>')
        if above:
            p.append(_t(x, top - 8, f"▲{above}", size=9.5, fill=S.muted, anchor="middle"))
    cats = [str(r.get(xkey, "")) for r in rows]
    end = _x_labels(p, cats, xs, bottom, band, None)
    for x, r in zip(xs, rows):  # n under each category
        if _num(r.get("n")) is not None:
            p.append(_t(x, end + 8, f"n = {int(_num(r['n']))}", size=9.5, fill=S.muted, anchor="middle"))
    end += 12
    if S.journal and spec["x"].get("label"):
        p.append(_t((left + right) / 2, end + 12, spec["x"]["label"], size=11, fill=S.ink, anchor="middle"))
        end += 16
    if over:
        p.append(_t(right, 12, "▲：超出纵轴的值的个数", size=9.5, fill=S.muted, anchor="end"))
    return p, end + 4


def forest_scale(rows: list[dict[str, Any]], est: dict[str, Any], x: dict[str, Any]) -> tuple[float, float, bool]:
    """The domain of a forest plot's axis: every interval and the reference line, with a margin; log when asked and possible."""
    keys = [est.get("key"), est.get("lo"), est.get("hi")]
    vals = [v for r in rows for k in keys if k for v in [_num(r.get(k))] if v is not None]
    ref = _num(x.get("ref"))
    if ref is not None:
        vals.append(ref)
    log = bool(x.get("log")) and all(v > 0 for v in vals)
    if not vals:
        return 0.0, 1.0, False
    lo, hi = min(vals), max(vals)
    if log:
        return lo / 1.3, hi * 1.3, True
    pad = (hi - lo) * 0.06 or 1.0
    return lo - pad, hi + pad, False


def _forest(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = spec.get("rows", [])
    est = spec.get("estimate") or {}
    xs_ = spec.get("x") or {}
    ykey = (spec.get("y") or {}).get("key")
    lo, hi, log = forest_scale(rows, est, xs_)
    text_of = lambda r: (f"{fmt_est(r.get(est['key']))} ({fmt_est(r.get(est['lo']))}–{fmt_est(r.get(est['hi']))})"  # noqa: E731
                         if _num(r.get(est.get("lo"))) is not None and _num(r.get(est.get("hi"))) is not None else fmt_est(r.get(est.get("key"))))
    label_w = min(width * 0.3, max([text_width(r.get(ykey, ""), 11) for r in rows] + [30]) + 12)
    text_w = min(width * 0.4, max([text_width(text_of(r), 10.5) for r in rows] + [text_width(f"{est.get('label', '')} (95% CI)", 10.5), 40]) + 14)
    left, right = label_w, width - text_w
    p: list[str] = []
    has_grey = any(r.get("sig") is False for r in rows) and any(r.get("sig") is not False for r in rows)
    lh = 0.0
    if has_grey:
        p, lh = _legend([("显著", PALETTE[0]), ("未达显著", OTHER)], width)
    top = lh + 22
    step = 20.0
    head = (spec.get("y") or {}).get("label") or ""
    p.append(_t(left - 8, top - 8, clip_text(head, 10.5, left - 10), size=10.5, fill=S.ink if S.journal else S.muted, anchor="end",
                weight="600" if S.journal else None))
    p.append(_t(right + 10, top - 8, f"{est.get('label', '')} (95% CI)", size=10.5, fill=S.ink if S.journal else S.muted, weight="600" if S.journal else None))
    bottom = top + step * len(rows)
    scale, end = _x_axis_numeric(p, left, right, bottom + 4, lo, hi, label=xs_.get("label", ""), log=log, grid_top=top)
    ref = _num(xs_.get("ref"))
    if ref is not None and lo <= ref <= hi:
        p.append(_line(scale(ref), top - 4, scale(ref), bottom + 4, S.ink2 if S.journal else S.axis, 1))
    for i, r in enumerate(rows):
        y = top + step * i + step / 2
        color = OTHER if r.get("sig") is False else PALETTE[0]
        p.append(_t(left - 8, y + 4, clip_text(r.get(ykey, ""), 11, left - 10), size=11, fill=S.ink2, anchor="end"))
        e, a, b = _num(r.get(est.get("key"))), _num(r.get(est.get("lo"))), _num(r.get(est.get("hi")))
        if a is not None and b is not None:
            xa, xb = scale(max(a, lo)), scale(min(b, hi))
            p.append(_line(xa, y, xb, y, S.ink2 if S.journal else color, 1.2))
            for xx, cut in ((xa, a < lo), (xb, b > hi)):
                if cut:  # the interval goes on past the axis
                    d = -1 if xx == xa else 1
                    p.append(f'<path d="M{xx - 5 * d:.1f},{y - 3.5:.1f} L{xx:.1f},{y:.1f} L{xx - 5 * d:.1f},{y + 3.5:.1f}" fill="none" stroke="{S.ink2}" stroke-width="1.2"/>')
                elif S.journal:
                    p.append(_line(xx, y - 3.5, xx, y + 3.5, S.ink2, 1.2))
        if e is not None and lo <= e <= hi:
            p.append(f'<rect x="{scale(e) - 4:.1f}" y="{y - 4:.1f}" width="8" height="8" fill="{color}" stroke="{S.surface}" stroke-width="1"/>')
        p.append(_t(right + 10, y + 4, text_of(r), size=10.5, fill=S.ink))
    return p, end + 4


def _scatter(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = spec.get("rows", [])
    xs_, ys_ = spec.get("x") or {}, spec.get("y") or {}
    xk, yk = xs_.get("key"), ys_.get("key")
    pts = [(r, _num(r.get(xk)), _num(r.get(yk))) for r in rows]
    pts = [(r, a, b) for r, a, b in pts if a is not None and b is not None]
    size = spec.get("size") or {}
    group = (spec.get("group") or {}).get("key")
    groups = list(dict.fromkeys(str(r.get(group, "")) for r, _, _ in pts)) if group else []
    colors = dict(zip(groups, series_colors(groups[:3]) + [OTHER] * max(0, len(groups) - 3)))  # three groups at most
    p, lh = _legend([(g, colors[g]) for g in groups], width) if len(groups) >= 2 else ([], 0.0)
    xv = [a for _, a, _ in pts] or [0.0]
    yv = [b for _, _, b in pts] or [0.0]
    fit = [(float(a), float(b)) for a, b in ((spec.get("fit") or {}).get("points") or []) if _num(a) is not None and _num(b) is not None]
    x_lo = _num(xs_.get("min")) if _num(xs_.get("min")) is not None else min(xv)
    x_hi = max(xv)
    if x_hi - x_lo <= 0:
        x_lo, x_hi = x_lo - 1, x_hi + 1
    pad = (x_hi - x_lo) * 0.04
    if _num(xs_.get("min")) is None:
        x_lo -= pad
    x_hi += pad
    y_lo = _num(ys_.get("min")) if _num(ys_.get("min")) is not None else min(0.0, min(yv))
    percent_y = bool(ys_.get("percent"))
    top_y = max(yv + [b for _, b in fit])
    y_hi = _num(ys_.get("max")) or (1.0 if percent_y and top_y <= 1 else nice_max(top_y))
    tks = [fmt(t, percent_y) for t in ticks(y_lo, y_hi)]
    left, right = _left(tks, ys_.get("label")), width - 16
    sk = size.get("key")
    head = 18.0 if sk else 8.0  # the axis title and the key to the bubbles clear of a bubble at the top (radius 10 at most)
    top = lh + 14 + head
    bottom = top + min(280, max(180, width * (0.55 if S.journal else 0.45)))
    yscale = _y_axis(p, left, right, top, bottom, y_lo, y_hi, percent_y, ys_.get("label", ""), head=head)
    xscale, end = _x_axis_numeric(p, left, right, bottom, x_lo, x_hi, label=xs_.get("label", "") if S.journal else "",
                                  percent=bool(xs_.get("percent")), year=bool(xs_.get("year")), grid_top=top)
    if not S.journal and xs_.get("label"):
        p.append(_t(right, end + 10, xs_["label"], size=10.5, fill=S.muted, anchor="end"))
        end += 14
    smax = max([_num(r.get(sk)) or 0 for r, _, _ in pts] + [1e-9]) if sk else 1
    radius = (lambda r: 3 + 7 * math.sqrt(max(_num(r.get(sk)) or 0, 0) / smax)) if sk else (lambda r: 3.0)  # noqa: E731
    dense = len(pts) > 200
    for r, a, b in pts:
        c = colors.get(str(r.get(group, "")), PALETTE[0]) if group else PALETTE[0]
        p.append(f'<circle cx="{xscale(a):.1f}" cy="{yscale(min(b, y_hi)):.1f}" r="{radius(r):.1f}" fill="{c}" fill-opacity="{0.35 if dense else 0.6}"'
                 + ("" if dense else f' stroke="{S.surface}" stroke-width="1"') + "/>")
    if len(fit) >= 2:
        p.append(f'<polyline points="{" ".join(f"{xscale(a):.1f},{yscale(min(max(b, y_lo), y_hi)):.1f}" for a, b in fit)}" fill="none" '
                 f'stroke="{S.ink}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    if sk and pts:  # a bubble's legend: the largest
        p.append(_t(right, top - head, f"点的大小：{size.get('label', '')}（最大 {fmt(smax)}）", size=10, fill=S.muted, anchor="end"))
    return p, end + 4


def _dendrogram(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    labels = [str(x) for x in spec.get("labels") or []]
    merges = spec.get("merges") or []
    n = len(labels)
    order = [int(i) for i in spec.get("order") or range(n)]
    member = spec.get("member") or [0] * n
    names = [str(g) for g in spec.get("groups") or []]
    colors = group_colors(spec, [names[m] if m < len(names) else str(m) for m in dict.fromkeys(member[i] for i in order)])
    color_of = lambda c: colors.get(names[c] if c < len(names) else str(c), S.ink2)  # noqa: E731
    p, lh = _legend([(g, c) for g, c in colors.items()], width)
    top = lh + 14
    step = 18.0 if not S.journal else 15.0
    label_w = min(width * 0.3, max([text_width(x, 11) for x in labels] + [24]) + 22)
    left, right = label_w, width - 20
    hmax = max([float(m[2]) for m in merges] + [1e-9])
    xscale = lambda h: left + h / (hmax * 1.04) * (right - left)  # noqa: E731
    ypos: dict[int, float] = {item: top + step * k + step / 2 for k, item in enumerate(order)}
    clus: dict[int, int | None] = {i: member[i] for i in range(n)}
    hgt: dict[int, float] = {i: 0.0 for i in range(n)}
    cut = _num(spec.get("cut"))
    for i, (a, b, h, _size) in enumerate(merges):
        a, b, h, node = int(a), int(b), float(h), n + i
        ya, yb = ypos[a], ypos[b]
        ypos[node] = (ya + yb) / 2
        hgt[node] = h
        same = clus.get(a) if clus.get(a) is not None and clus.get(a) == clus.get(b) and (cut is None or h <= cut) else None
        clus[node] = same
        c = color_of(same) if same is not None else S.ink2
        x = xscale(h)
        p.append(f'<path d="M{xscale(hgt[a]):.1f},{ya:.1f} L{x:.1f},{ya:.1f} L{x:.1f},{yb:.1f} L{xscale(hgt[b]):.1f},{yb:.1f}" fill="none" '
                 f'stroke="{c}" stroke-width="{1.6 if same is not None else 1.2}"/>')
    for item in order:
        y = ypos[item]
        p.append(f'<rect x="{left - 13:.1f}" y="{y - 4:.1f}" width="8" height="8" fill="{color_of(member[item])}"/>')
        p.append(_t(left - 18, y + 4, clip_text(labels[item], 11, left - 20), size=11, fill=S.ink2, anchor="end"))
    bottom = top + step * n + 4
    if cut is not None:
        p.append(_line(xscale(cut), top, xscale(cut), bottom, S.muted, 1))
    _, end = _x_axis_numeric(p, left, right, bottom, 0.0, hmax * 1.04, label=(spec.get("x") or {}).get("label", ""), grid_top=None)
    return p, end + 4


def timeline_lanes(xs: list[float], widths: list[float], width: float) -> tuple[list[int], list[bool]]:
    """The lane (0 at the top) of each label of a timeline, and whether it is turned to the left of its dot (at the right
    edge, where it would leave the figure).  ``xs`` the dots in order of time, ``widths`` the room each label takes.

    A label takes the lane, among those where it overlaps no other label, where the fewest stems cross labels — its own
    stem, from its dot down to the axis, through the labels below it, and the stems from above through its text — the
    highest of them when several tie; lanes past the compact layout's (each label in the first lane it fits) and two more
    are taken only when nothing else is free, so that a crowded timeline does not grow into a tall one (the stems that
    still cross a label are broken around it, ``stem_gaps``).  Labels pointing right are placed in order of time, then
    the turned ones from the right edge inwards, so that each meets the stems it could cross already placed."""
    n = len(xs)
    flip = [x + w > width - 6 for x, w in zip(xs, widths)]
    room = [(x - w, x + 6) if f else (x - 6, x + w) for x, w, f in zip(xs, widths, flip)]
    text = [(x - w + 7, x - 7) if f else (x + 7, x + w - 7) for x, w, f in zip(xs, widths, flip)]
    order = [i for i in range(n) if not flip[i]] + [i for i in reversed(range(n)) if flip[i]]

    def free(i: int, k: int, lane: list[int], done: list[int]) -> bool:
        return not any(lane[j] == k and room[j][0] < room[i][1] + 2 and room[i][0] < room[j][1] + 2 for j in done)

    lane = [0] * n
    done: list[int] = []
    for i in order:  # the compact layout: how many lanes the labels need at least
        lane[i] = next(k for k in range(n + 1) if free(i, k, lane, done))
        done.append(i)
    budget = max(lane, default=0) + 1 + 2
    lane, done = [0] * n, []
    for i in order:
        best: tuple[int, int] | None = None
        for k in range(max((lane[j] for j in done), default=-1) + 2):
            if not free(i, k, lane, done):
                continue
            if k >= budget and best is not None:
                break
            cost = sum(1 for j in done if lane[j] > k and text[j][0] - 2 <= xs[i] <= text[j][1] + 2)  # its stem through a label below
            cost += sum(1 for j in done if lane[j] < k and text[i][0] - 2 <= xs[j] <= text[i][1] + 2)  # a stem from above through its text
            if best is None or cost < best[0]:
                best = (cost, k)
                if not cost:
                    break
        lane[i] = best[1] if best else 0
        done.append(i)
    return lane, flip


def stem_gaps(x: float, top: float, bottom: float, boxes: list[tuple[float, float, float, float]]) -> list[tuple[float, float]]:
    """A stem from ``top`` down to ``bottom`` at ``x`` as the pieces that clear the labels' ``boxes`` (x0, y0, x1, y1) it
    would cross, 2 px around each."""
    cuts = sorted((y0 - 2, y1 + 2) for x0, y0, x1, y1 in boxes if x0 - 2 <= x <= x1 + 2 and y1 > top and y0 < bottom)
    out, y = [], top
    for a, b in cuts:
        if a > y:
            out.append((y, a))
        y = max(y, b)
    if y < bottom:
        out.append((y, bottom))
    return out


def _timeline(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    rows = sorted((r for r in spec.get("rows", []) if _num(r.get("start")) is not None), key=lambda r: _num(r["start"]))
    color = group_colors(spec, list(dict.fromkeys(str(r.get("group", "")) for r in rows)))
    p, lh = _legend([(g, c) for g, c in color.items() if g], width)
    left, right = 30.0, width - 30
    years = [_num(r["start"]) for r in rows] or [0.0, 1.0]
    lo, hi = min(years), max(years)
    if hi - lo < 50:
        lo, hi = lo - 25, hi + 25
    pad = (hi - lo) * 0.04
    lo, hi = lo - pad, hi + pad
    scale = lambda v: left + (v - lo) / (hi - lo) * (right - left)  # noqa: E731
    labels = [clip_text(r.get("label", ""), 10.5, width * 0.6) for r in rows]
    xs = [scale(_num(r["start"])) for r in rows]
    lanes, flips = timeline_lanes(xs, [text_width(t, 10.5) + 14 for t in labels], width)
    top = lh + 18
    axis = top + 22 * (max(lanes, default=0) + 1) + 10
    for t in ticks(lo, hi, 6):  # ticks under the axis (no grid: the stems are the guides, and a line through a label is not)
        x = scale(t)
        p.append(_line(x, axis, x, axis + 4, S.axis))
        p.append(_t(x, axis + 16, year_text(t), size=10.5, fill=S.ink2 if S.journal else S.muted, anchor="middle"))
    p.append(_line(left, axis, right, axis, S.axis))
    ys = [top + 22 * lane + 8 for lane in lanes]
    colors = [color[str(r.get("group", ""))] for r in rows]
    boxes = [_box_of(x - 7 if f else x + 7, y + 4, text_width(t, 10.5), 10.5, "end" if f else "start") for x, y, t, f in zip(xs, ys, labels, flips)]
    for i, (x, y, c) in enumerate(zip(xs, ys, colors)):  # the stems first, broken where they would cross a label
        for a, b in stem_gaps(x, y, axis, [bx for j, bx in enumerate(boxes) if j != i]):
            p.append(_line(x, a, x, b, c, 1, ' stroke-opacity="0.35"'))
    for x, y, c in zip(xs, ys, colors):
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{c}" stroke="{S.surface}" stroke-width="2"/>')
    for x, y, label, flip in zip(xs, ys, labels, flips):
        p.append(_t(x - 7 if flip else x + 7, y + 4, label, size=10.5, fill=S.ink, anchor="end" if flip else "start"))
    end = axis + 24
    if S.journal:
        p.append(_t((left + right) / 2, end + 6, (spec.get("x") or {}).get("label") or "年代", size=11, fill=S.ink, anchor="middle"))
        end += 16
    return p, end


def hub_of(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str | None:
    """The node every edge touches, when the graph is a hub with spokes (a formula and the formulas built on it)."""
    if not edges:
        return None
    ends = [{e["source"], e["target"]} for e in edges]
    common = set.intersection(*ends)
    return next(iter(common)) if len(common) == 1 and len(edges) == len(nodes) - 1 else None


def _network(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])
    color = group_colors(spec, list(dict.fromkeys(str(n.get("group", "")) for n in nodes)))
    p, lh = _legend([(g, c) for g, c in color.items() if g], width)
    smax = max([_num(n.get("size")) or 1 for n in nodes] + [1])
    rad = lambda n: 4 + 8 * math.sqrt((_num(n.get("size")) or 1) / smax)  # noqa: E731
    top = lh + 16
    hub = hub_of(nodes, edges)
    if hub is not None:  # a hub and its spokes: the hub on the left, the others in a column
        centre = next(n for n in nodes if n["id"] == hub)
        others = [n for n in nodes if n["id"] != hub]
        by_target = {e["target"] if e["source"] == hub else e["source"]: e for e in edges}
        step = 22.0
        height = step * max(len(others), 1)
        hub_label = clip_text(centre.get("label", centre["id"]), 13, width * 0.3)
        hx = max(min(140.0, width * 0.22), rad(centre) + 2 + 8 + text_width(hub_label, 13) + 4)  # its name to its left, inside
        hy, col = top + height / 2, max(min(360.0, width * 0.48), hx + 60)
        for i, n in enumerate(others):
            y = top + step * i + step / 2
            e = by_target.get(n["id"], {})
            p.append(f'<path d="M{hx:.1f},{hy:.1f} C{(hx + col) / 2:.1f},{hy:.1f} {(hx + col) / 2:.1f},{y:.1f} {col:.1f},{y:.1f}" fill="none" '
                     f'stroke="{S.axis if not S.journal else "#9a9a9a"}" stroke-width="1"/>')
            p.append(f'<circle cx="{col:.1f}" cy="{y:.1f}" r="{rad(n):.1f}" fill="{color.get(str(n.get("group", "")), OTHER)}" stroke="{S.surface}" stroke-width="2"/>')
            name = clip_text(n.get("label", n["id"]), 11, width - col - 16)
            p.append(_t(col + 14, y + 4, name, size=11, fill=S.ink))
            if e.get("label") and col + 24 + text_width(name, 11) + text_width(e["label"], 10) < width:
                p.append(_t(col + 24 + text_width(name, 11), y + 4, e["label"], size=10, fill=S.muted))
        p.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{rad(centre) + 2:.1f}" fill="{color.get(str(centre.get("group", "")), OTHER)}" '
                 f'stroke="{S.surface}" stroke-width="2"/>')
        p.append(_t(hx - rad(centre) - 8, hy + 5, hub_label, size=13, fill=S.ink, anchor="end", weight="600"))
        return p, top + height + 8
    # a ring: each name along its radius, outwards (turned to read left to right on the left half), so that neighbours
    # never sit on one another however many there are
    names = {n["id"]: clip_text(n.get("label", n["id"]), 10.5, 90) for n in nodes}
    reach = max([text_width(t, 10.5) for t in names.values()] + [0]) + 4 + 12  # a name and the largest dot
    cx = width / 2
    radius = max(40.0, min(170.0, width / 2 - reach - 6))
    cy = top + reach + radius + 6
    pos = {}
    for i, n in enumerate(nodes):
        a = -math.pi / 2 + 2 * math.pi * i / max(len(nodes), 1)
        pos[n["id"]] = (cx + radius * math.cos(a), cy + radius * math.sin(a), a)
    wmax = max([_num(e.get("weight")) or 1 for e in edges] + [1])
    for e in edges:
        if e["source"] in pos and e["target"] in pos:
            (x1, y1, _), (x2, y2, _) = pos[e["source"]], pos[e["target"]]
            p.append(_line(x1, y1, x2, y2, S.axis if not S.journal else "#9a9a9a", 1 + 2 * (_num(e.get("weight")) or 1) / wmax))
    for n in nodes:
        x, y, a = pos[n["id"]]
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad(n):.1f}" fill="{color.get(str(n.get("group", "")), OTHER)}" stroke="{S.surface}" stroke-width="2"/>')
        right_half = math.cos(a) >= -1e-9
        d = radius + rad(n) + 4
        # the baseline a third of an em off the radius, so that the glyphs sit on it
        ox, oy = (-math.sin(a), math.cos(a)) if right_half else (math.sin(a), -math.cos(a))
        lx, ly = cx + d * math.cos(a) + 3.6 * ox, cy + d * math.sin(a) + 3.6 * oy
        turn = math.degrees(a) if right_half else math.degrees(a) + 180
        p.append(_t(lx, ly, names[n["id"]], size=10.5, fill=S.ink, anchor="start" if right_half else "end", rotate=round(turn, 2)))
    return p, cy + radius + reach + 8


PLOTS = {"line": _series, "bar": _series, "stack": _series, "hbar": _hbar, "heatmap": _heatmap, "range": _range, "box": _box,
         "forest": _forest, "scatter": _scatter, "dendrogram": _dendrogram, "timeline": _timeline, "network": _network}


def plot(spec: dict[str, Any], width: float) -> tuple[list[str], float]:
    """The plot of a specification at a width (its legend included, its title and caption not): (parts, height)."""
    return PLOTS[spec["type"]](spec, max(280.0, width))


# ------------------------------------------------------------------ figures
CLOSING = set("）」』】〕》〉，。、；：！？’”)].,;:!?")  # never at the start of a line: they hang at the end of the one before


def _wrap(text: str, width: float, size: float) -> list[str]:
    lines, cur = [], ""
    for ch in str(text):
        if text_width(cur + ch, size) > width and cur and ch not in CLOSING:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def caption_text(spec: dict[str, Any]) -> str:
    """A figure's caption after its number: the title and what the subtitle says, as a sentence."""
    title = str(spec.get("title") or "").replace(" · ", "：", 1)
    sub = str(spec.get("subtitle") or "").rstrip("。")
    return title + ("。" + sub + "。" if sub else "")


def _caption(parts: list[str], y: float, width: float, number: Any, body: str, notes: list[str]) -> float:
    """The caption under a journal figure: 图 n (bold) and its text, then the notes; the y under it."""
    head = f"图{number}　" if number not in (None, "") else ""
    lines = _wrap(head + body, width - 12, 11)  # room for punctuation that hangs at a line's end
    for i, line in enumerate(lines):
        y += 15
        if i == 0 and head and line.startswith(head):
            hw = text_width(head, 11)
            parts.append(_t(0, y, head.rstrip("　"), size=11, fill=S.ink, weight="700"))
            parts.append(_t(hw, y, line[len(head):], size=11, fill=S.ink))
        else:
            parts.append(_t(0, y, line, size=11, fill=S.ink))
    for note in notes:
        for line in _wrap(note, width - 11, 10):
            y += 13.5
            parts.append(_t(0, y, line, size=10, fill=S.muted))
    return y


def _root(width: float, height: float, body: str, title: str, *, mm: float | None) -> str:
    size = (f'width="{mm:g}mm" height="{height * mm / width:.1f}mm"' if mm else f'width="{int(width)}" height="{int(height)}"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" {size} font-family="{escape(S.font)}" '
            f'role="img" aria-label="{escape(title, {chr(34): "&quot;"})}">\n<title>{escape(title)}</title>\n<rect width="100%" height="100%" fill="{S.surface}"/>\n'
            f"{body}\n</svg>\n")


def journal_width(width: str | float | None) -> tuple[float, float]:
    """(mm, design units) of a journal figure: single, onehalf or double column, or millimetres."""
    mm = WIDTHS_MM.get(width, None) if isinstance(width, str) else (float(width) if width else WIDTHS_MM["onehalf"])
    mm = mm or WIDTHS_MM["onehalf"]
    return mm, round(mm * PX_PER_MM)


def to_svg(spec: dict[str, Any], *, style: str = "journal", number: Any = None, caption: bool = True, width: str | float | None = None) -> str:
    """A chart specification as a standalone SVG document: in the journal style its plot and, with ``caption``, its
    number and caption under it at a journal's width (``single``, ``onehalf``, ``double`` or millimetres); in the screen
    style its title above and its note and source below."""
    if style != "journal":
        with _style(SCREEN):
            parts: list[str] = []
            y = 24.0
            parts.append(_t(20, y, spec.get("title", ""), size=15, fill=S.ink, weight="600"))
            y += 8
            for line in _wrap(spec.get("subtitle") or "", WIDTH - 40, 11.5):
                y += 16
                parts.append(_t(20, y, line, size=11.5))
            y += 12
            body, h = plot(spec, WIDTH - 40)
            parts.append(f'<g transform="translate(20 {y:.0f})">' + "\n".join(body) + "</g>")
            bottom = y + h + 6
            for line in [x for x in (spec.get("note"), spec.get("source")) if x]:
                for part in _wrap(line, WIDTH - 40, 10):
                    bottom += 14
                    parts.append(_t(20, bottom, part, size=10, fill=S.muted))
            return _root(WIDTH, bottom + 16, "\n".join(parts), spec.get("title") or "chart", mm=None)
    mm, w = journal_width(width)
    with _style(JOURNAL):
        pad = 6.0
        body, h = plot(spec, w - 2 * pad)
        parts = [f'<g transform="translate({pad:g} {pad + 4:g})">' + "\n".join(body) + "</g>"]
        y = pad + 4 + h
        if caption:
            cap: list[str] = []
            bottom = _caption(cap, 4, w - 2 * pad, number, caption_text(spec), [x for x in (spec.get("note"), spec.get("source")) if x])
            parts.append(f'<g transform="translate({pad:g} {y:.0f})">' + "\n".join(cap) + "</g>")
            y += bottom
        return _root(w, y + pad + 4, "\n".join(parts), spec.get("title") or "chart", mm=mm)


def common_title(specs: list[dict[str, Any]]) -> str:
    """What the charts of a result are of: the part of their titles before " · " when they share it."""
    heads = {str(s.get("title", "")).split(" · ")[0] for s in specs if " · " in str(s.get("title", ""))}
    return heads.pop() if len(heads) == 1 and all(" · " in str(s.get("title", "")) for s in specs) else ""


def to_panels(specs: list[dict[str, Any]], *, number: Any = None, caption: bool = True, title: str | None = None,
              columns: int = 2, width: str | float | None = "double") -> str:
    """Several charts as one journal figure: panels A, B … in ``columns`` columns, each with its letter and short title,
    and one caption under them (the figure's title, then (A) …; (B) …, the notes once, the source once)."""
    mm, w = journal_width(width)
    with _style(JOURNAL):
        pad, gap = 6.0, 18.0
        cols = max(1, min(columns, len(specs)))
        pw = (w - 2 * pad - gap * (cols - 1)) / cols
        head = title if title is not None else common_title(specs)
        parts: list[str] = []
        y = pad
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for row in range(0, len(specs), cols):
            cells = []
            for k, spec in enumerate(specs[row: row + cols]):
                i = row + k
                short = str(spec.get("title", ""))
                if head and short.startswith(head + " · "):
                    short = short[len(head) + 3:]
                body, h = plot(spec, pw)
                label = [_t(0, 13, letters[i % 26], size=14, fill=S.ink, weight="700")]
                ty = 13.0
                for line in _wrap(short, pw - 18, 10.5)[:2]:
                    label.append(_t(18, ty, line, size=10.5, fill=S.ink2))
                    ty += 13
                cells.append((label, body, ty + 6 + h))
            rh = max(c[2] for c in cells)
            for k, (label, body, h) in enumerate(cells):
                x = pad + k * (pw + gap)
                ty = 13.0 + 13 * (len(label) - 1)
                parts.append(f'<g transform="translate({x:.1f} {y:.1f})">' + "\n".join(label)
                             + f'<g transform="translate(0 {ty + 6 - 13:.1f})">' + "\n".join(body) + "</g></g>")
            y += rh + 14
        if caption:
            pieces = "；".join(f"（{letters[i % 26]}）{(str(s.get('title', ''))[len(head) + 3:] if head and str(s.get('title', '')).startswith(head + ' · ') else s.get('title', ''))}"
                              for i, s in enumerate(specs))
            notes = list(dict.fromkeys(s.get("note") for s in specs if s.get("note")))
            notes = [x for x in notes if not any(x != y and x in y for y in notes)]  # a note another one already holds
            sources = list(dict.fromkeys(s.get("source") for s in specs if s.get("source")))
            cap: list[str] = []
            bottom = _caption(cap, 0, w - 2 * pad, number, (head + "。" if head else "") + pieces + "。", notes + (["；".join(sources)] if sources else []))
            parts.append(f'<g transform="translate({pad:g} {y - 6:.0f})">' + "\n".join(cap) + "</g>")
            y += bottom
        return _root(w, y + pad, "\n".join(parts), head or "figure", mm=mm)


def to_csv(spec: dict[str, Any], *, bom: bool = True) -> str:
    """The table behind a chart (its rows, in its columns' order and labels); a network's edges — a cell a spreadsheet would
    read as a formula kept as text."""
    from .tablefmt import defuse

    buf = io.StringIO()
    w = csv.writer(buf)
    w = _Defused(w, defuse)
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


class _Defused:
    """A CSV writer whose cells pass through ``defuse`` first."""

    def __init__(self, writer: Any, defuse: Any) -> None:
        self.w, self.defuse = writer, defuse

    def writerow(self, row: list[Any]) -> None:
        self.w.writerow([self.defuse(x) for x in row])


def write(charts: list[dict[str, Any]], out_dir: Any, stem: str, *, style: str = "journal") -> list[str]:
    """Each chart as <stem>-<id>.svg (numbered 图 1, 图 2 … in the journal style), .csv and .json in ``out_dir``, and
    several as one figure in panels (<stem>-figure.svg); the paths written."""
    import json
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, c in enumerate(charts, 1):
        name = f"{stem}-{c.get('id') or i}"
        for ext, text in (("svg", to_svg(c, style=style, number=i)), ("csv", to_csv(c)), ("json", json.dumps(c, ensure_ascii=False, indent=1))):
            path = out / f"{name}.{ext}"
            path.write_text(text, encoding="utf-8")
            written.append(str(path))
    if len(charts) > 1 and style == "journal":
        path = out / f"{stem}-figure.svg"
        path.write_text(to_panels(charts[:8], number=1), encoding="utf-8")
        written.append(str(path))
    return written


__all__ = ["JOURNAL", "PALETTE", "RAMP", "SCREEN", "box_rows", "caption_text", "plot", "to_csv", "to_panels", "to_svg", "write"]
