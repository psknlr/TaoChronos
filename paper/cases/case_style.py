"""Drawing helpers shared by the three case figures.

The figures use the display-item style of the paper (``paper/figures/nature_style.py``: millimetre layout at the final
print size, Arial with Noto Sans CJK for Chinese characters, text of 5–7 pt, strokes of 0.25–1 pt, the Okabe–Ito
palette, a vector PDF with live text) and its per-figure check.  Everything here is geometry: boxes, wrapped and mixed
text, arrows, flow bands, and the strip that opens each figure with the question as it was put to the agent and the
passages the answer cites.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, PathPatch, Rectangle
from matplotlib.path import Path as MPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "figures"))

from cjk_truetype import use_truetype_cjk  # noqa: E402

use_truetype_cjk()  # before any text is measured or drawn: Chinese characters from TrueType outlines (see the module)

from nature_style import C, Canvas, apply_style, text_width_mm, tint, wrap_mm  # noqa: E402

warnings.filterwarnings("error", message="Glyph .* missing from font")  # a character no font has stops the build

SD = HERE / "source_data"
OUT = HERE / "out"
PT = 0.3528  # mm per point

INK, DARK, GREY, LIGHT, PALE = C["black"], C["dark"], C["grey"], C["light"], "#F3F3F3"
BLUE, ORANGE, SKY, GREEN, VERM, PURPLE, YELLOW = (C["blue"], C["orange"], C["sky"], C["green"], C["vermillion"],
                                                  C["purple"], C["yellow"])

PERIOD_EN = {"先秦两汉": "Qin–Han", "魏晋南北朝": "Wei–Jin", "隋唐五代": "Sui–Tang", "宋金元": "Song–Jin–Yuan",
             "明": "Ming", "清": "Qing", "民国": "Republican"}


def load(name: str) -> dict:
    return json.loads((SD / name).read_text(encoding="utf-8"))


def answer(n: int) -> str:
    """The agent's answer to case ``n``, verbatim (no-break hyphens read as hyphens)."""
    return (SD / f"case{n}_answer.md").read_text(encoding="utf-8").replace("\u2011", "-")


# --- measuring -----------------------------------------------------------------------------------------------------------
_R = None


def width_mm(s: str, fs: float, weight: str = "normal", style: str = "normal") -> float:
    """Printed width of ``s`` in millimetres in the figure fonts (as ``text_width_mm``, with italics)."""
    global _R
    if style == "normal":
        return text_width_mm(s, fs, weight)
    from matplotlib.backends.backend_agg import RendererAgg

    if _R is None:
        apply_style()
        _R = RendererAgg(100, 100, 72)
    prop = font_manager.FontProperties(family=mpl.rcParams["font.family"], size=fs, weight=weight, style=style)
    w, _, _ = _R.get_text_width_height_descent(s, prop, ismath=False)
    return w / 72 * 25.4


def line_h(fs: float, lh: float = 1.22) -> float:
    return fs * PT * lh


# --- boxes, text ---------------------------------------------------------------------------------------------------------
def rbox(ax: Any, x: float, y: float, w: float, h: float, *, fc: str = "white", ec: str | None = None, lw: float = 0.5,
         r: float = 0.8, z: float = 1, **kw: Any) -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", facecolor=fc,
                                edgecolor=ec if ec is not None else "none", lw=lw if ec is not None else 0, zorder=z,
                                **kw))


def rect(ax: Any, x: float, y: float, w: float, h: float, *, fc: str = "white", ec: str | None = None, lw: float = 0.4,
         z: float = 1, **kw: Any) -> None:
    ax.add_patch(Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec if ec is not None else "none",
                           lw=lw if ec is not None else 0, zorder=z, **kw))


def para(ax: Any, x: float, y: float, s: str, width: float, fs: float = 5.5, *, weight: str = "normal",
         color: str = "black", lh: float = 1.22, ha: str = "left", style: str = "normal", z: float = 5,
         max_lines: int | None = None) -> float:
    """Wrapped text from its top edge; returns the y below it (mm)."""
    lines = wrap_mm(s, width, fs, weight)
    if max_lines is not None and len(lines) > max_lines:
        raise ValueError(f"{len(lines)} lines for {max_lines}: {s[:50]!r}")
    xx = x if ha == "left" else x + width / 2 if ha == "center" else x + width
    ax.text(xx, y, "\n".join(lines), ha=ha, va="top", fontsize=fs, fontweight=weight, color=color, linespacing=lh,
            fontstyle=style, zorder=z)
    return y + len(lines) * line_h(fs, lh)


def n_lines(s: str, width: float, fs: float, weight: str = "normal") -> int:
    return len(wrap_mm(s, width, fs, weight))


def rich(ax: Any, x: float, y: float, parts: list[tuple], fs: float = 5.5, *, va: str = "baseline", z: float = 5,
         ha: str = "left") -> float:
    """Text on one line in several styles: parts are (string, {weight, color, style}); returns the x after it."""
    widths = [width_mm(s, fs, o.get("weight", "normal"), o.get("style", "normal")) for s, o in parts]
    total = sum(widths)
    xx = x if ha == "left" else x - total / 2 if ha == "center" else x - total
    for (s, o), w in zip(parts, widths):
        if s.strip():
            ax.text(xx + (width_mm(s[:len(s) - len(s.lstrip())], fs) if s[0] == " " else 0), y, s.strip(), ha="left",
                    va=va, fontsize=fs, fontweight=o.get("weight", "normal"), color=o.get("color", "black"),
                    fontstyle=o.get("style", "normal"), zorder=z)
        xx += w
    return xx


def chip(ax: Any, x: float, y: float, s: str, fs: float = 5.5, *, fc: str = PALE, ec: str | None = None,
         color: str = "black", weight: str = "normal", padx: float = 0.9, h: float | None = None, r: float = 0.7,
         lw: float = 0.4, z: float = 3, w: float | None = None) -> float:
    """A rounded label sized to its text, its left edge at x and its vertical centre at y; returns its width."""
    hh = h if h is not None else fs * PT * 1.55
    ww = w if w is not None else width_mm(s, fs, weight) + 2 * padx
    rbox(ax, x, y - hh / 2, ww, hh, fc=fc, ec=ec, lw=lw, r=r, z=z)
    ax.text(x + ww / 2, y, s, ha="center", va="center_baseline", fontsize=fs, color=color, fontweight=weight,
            zorder=z + 1)
    return ww


def title(ax: Any, x: float, y: float, s: str, fs: float = 6.5, color: str = "black") -> None:
    ax.text(x, y, s, ha="left", va="top", fontsize=fs, fontweight="bold", color=color, zorder=5)


# --- lines, arrows, bands ------------------------------------------------------------------------------------------------
def line(ax: Any, xs: list[float], ys: list[float], *, color: str = INK, lw: float = 0.5, ls: Any = "-", z: float = 2,
         cap: str = "butt", **kw: Any) -> None:
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=z, solid_capstyle=cap, **kw)


def arrow(ax: Any, x0: float, y0: float, x1: float, y1: float, *, color: str = INK, lw: float = 0.6, head: float = 3.2,
          rad: float = 0.0, z: float = 4, style: str = "-|>", ls: Any = "-") -> None:
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1),
                                 arrowstyle=f"{style},head_length={head * 0.5},head_width={head * 0.3}",
                                 mutation_scale=1.0, lw=lw, color=color, shrinkA=0, shrinkB=0, zorder=z, ls=ls,
                                 connectionstyle=f"arc3,rad={rad}", joinstyle="miter", capstyle="butt"))


def band(ax: Any, x0: float, y0a: float, y0b: float, x1: float, y1a: float, y1b: float, color: str,
         alpha: float = 1.0, z: float = 1) -> None:
    """A flow band from the segment (x0, y0a–y0b) to (x1, y1a–y1b), with S-shaped edges."""
    xm = (x0 + x1) / 2
    verts = [(x0, y0a), (xm, y0a), (xm, y1a), (x1, y1a), (x1, y1b), (xm, y1b), (xm, y0b), (x0, y0b), (x0, y0a)]
    codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4, MPath.LINETO, MPath.CURVE4, MPath.CURVE4,
             MPath.CURVE4, MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(verts, codes), facecolor=color, edgecolor="none", lw=0, alpha=alpha, zorder=z))


def s_curve(ax: Any, x0: float, y0: float, x1: float, y1: float, *, color: str = GREY, lw: float = 0.5,
            z: float = 2, ls: Any = "-") -> None:
    """A thin S-shaped connector between two points (horizontal tangents at both ends)."""
    xm = (x0 + x1) / 2
    ax.add_patch(PathPatch(MPath([(x0, y0), (xm, y0), (xm, y1), (x1, y1)],
                                 [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4]), facecolor="none",
                           edgecolor=color, lw=lw, zorder=z, ls=ls, capstyle="butt"))


def dot(ax: Any, x: float, y: float, r: float = 0.7, *, fc: str = BLUE, ec: str | None = None, lw: float = 0.5,
        z: float = 4, alpha: float = 1.0) -> None:
    from matplotlib.patches import Circle

    ax.add_patch(Circle((x, y), r, facecolor=fc, edgecolor=ec if ec is not None else "none",
                        lw=lw if ec is not None else 0, zorder=z, alpha=alpha))


# --- the strip that opens each figure ------------------------------------------------------------------------------------
def year_label(y: float) -> str:
    return f"{abs(int(y))} BCE" if y < 0 else f"{int(y)}"


def query_strip(cv: Canvas, ax: Any, data: dict, *, case: str, domain: str, topic: str, y: float = 4.0,
                h: float = 14.6, colour: str = BLUE) -> float:
    """Panel a of each figure: the case, the question as put to the agent, and what the answer cites.

    The rug marks every witness the answer cites at the midpoint of its composition range (a bar spans a range longer
    than 60 years); the area of a mark grows with the passages cited from it.  Returns the y below the strip.
    """
    x0, w = 2.0, cv.w - 4.0
    rbox(ax, x0, y, w, h, fc=PALE, r=1.0, z=0)
    rect(ax, x0, y, 1.1, h, fc=colour, z=1)
    ax.text(x0 + 3.0, y + 1.5, case, ha="left", va="top", fontsize=7, fontweight="bold", color=colour, zorder=5)
    ax.text(x0 + 3.0, y + 4.7, domain, ha="left", va="top", fontsize=6, fontweight="bold", zorder=5)
    para(ax, x0 + 3.0, y + 7.6, topic, 29.5, 5.5, color=DARK, lh=1.15)
    # the question, verbatim
    qx, qw = x0 + 35.5, 91.5
    ax.text(qx, y + 1.5, "Question put to the agent", ha="left", va="top", fontsize=5.5, fontweight="bold",
            color=DARK, zorder=5)
    para(ax, qx, y + 4.2, "“" + data["header"]["query"].replace("’", "'") + "”", qw, 5.5, lh=1.18)
    # what the answer rests on
    ev = data["evidence"]
    ex = x0 + 131.5
    ew = x0 + w - 2.5 - ex
    ax.text(ex, y + 1.5, "Answer of 道乃久 (Tao-R1), full corpus", ha="left", va="top", fontsize=5.5,
            fontweight="bold", color=DARK, zorder=5)
    ax.text(ex, y + 4.2, f"{ev['passages']} passages quoted verbatim from {ev['witnesses']} witnesses",
            ha="left", va="top", fontsize=5.5, zorder=5)
    wd = ev["witness_dates"]
    lo = min(-300.0, min(v[2] for v in wd))
    hi = 1950.0
    ry = y + 9.5
    sx = lambda yr: ex + (yr - lo) / (hi - lo) * ew  # noqa: E731
    line(ax, [ex, ex + ew], [ry, ry], color=GREY, lw=0.4, z=2)
    for _, _, a, b, n in wd:
        mid = (a + b) / 2
        if b - a > 60:
            line(ax, [sx(a), sx(b)], [ry, ry], color=tint(colour, 0.55), lw=1.0, z=3)
        dot(ax, sx(mid), ry, 0.42 + 0.22 * (n ** 0.5), fc=colour, z=4, alpha=0.55)
    for yr in (lo, 1, 500, 1000, 1500, hi):
        line(ax, [sx(yr), sx(yr)], [ry + 1.3, ry + 1.9], color=GREY, lw=0.4, z=2)
        if yr == 1:
            continue  # the tick alone: its label would run into the first
        lab = f"{int(-yr)} BCE" if yr < 0 else f"{int(yr)}"
        ax.text(sx(yr), ry + 2.3, lab, ha="left" if yr == lo else "right" if yr == hi else "center", va="top",
                fontsize=5, color=DARK, zorder=5)
    return y + h


__all__ = ["BLUE", "C", "Canvas", "DARK", "GREEN", "GREY", "INK", "LIGHT", "ORANGE", "OUT", "PALE", "PERIOD_EN", "PT",
           "PURPLE", "SD", "SKY", "VERM", "YELLOW", "answer", "arrow", "band", "chip", "dot", "line", "line_h", "load",
           "n_lines", "para", "query_strip", "rbox", "rect", "rich", "s_curve", "tint", "title", "width_mm",
           "wrap_mm", "year_label"]
