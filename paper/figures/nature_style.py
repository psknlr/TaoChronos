"""Nature Portfolio display-item style for the TaoChronos (道乃久) figures.

Every figure is laid out in millimetres at its final print size (89 mm single column, 183 mm double column, at most
170 mm tall), set in Arial (Noto Sans CJK for Chinese characters, glyph by glyph), with text of 5–7 pt, panel labels of
8 pt bold lower case, strokes of 0.25–1 pt and the Okabe–Ito colour-blind-safe palette.  ``Canvas.save`` writes a vector
PDF (fonts embedded as TrueType, text left live), an SVG (text as text) and a 600 dpi PNG, then checks the saved figure:
its physical size, the embedded fonts, every text size and stroke width, text that leaves the page and text that
collides with other text.  An empty ``warnings`` list is the pass signal.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from cycler import cycler  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import Collection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.text import Text  # noqa: E402

MM = 1 / 25.4
WIDTH = {"single": 89.0, "onehalf": 120.0, "onehalf_max": 136.0, "double": 183.0}
MAX_HEIGHT = 170.0
TEXT_MIN, TEXT_MAX, LABEL_PT = 5.0, 7.0, 8.0
LINE_MIN, LINE_MAX = 0.25, 1.0

# Okabe–Ito, as the Nature figure guide publishes it
C = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "grey": "#999999",
    "dark": "#4D4D4D",
    "light": "#D9D9D9",
}


def tint(color: str, f: float) -> str:
    """``color`` mixed with white: f = 0 white, f = 1 the colour itself (flat fills for schematic boxes)."""
    color = color.lstrip("#")
    rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(255 - (255 - v) * f):02X}" for v in rgb)


def _first_font(names: list[str]) -> str:
    have = {f.name for f in font_manager.fontManager.ttflist}
    for n in names:
        if n in have:
            return n
    return "DejaVu Sans"


LATIN = _first_font(["Arial", "Helvetica", "Liberation Sans"])
CJK = _first_font(["Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei"])


def apply_style() -> dict[str, str]:
    mpl.rcParams.update({
        "font.family": [LATIN, CJK],
        "font.size": 6,
        "axes.titlesize": 6.5,
        "axes.labelsize": 6.5,
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "legend.fontsize": 6,
        "legend.title_fontsize": 6,
        "axes.linewidth": 0.6,
        "axes.edgecolor": "black",
        "axes.labelcolor": "black",
        "text.color": "black",
        "xtick.color": "black",
        "ytick.color": "black",
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.minor.width": 0.4,
        "ytick.minor.width": 0.4,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "xtick.minor.size": 1.5,
        "ytick.minor.size": 1.5,
        "xtick.major.pad": 1.8,
        "ytick.major.pad": 1.8,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "axes.facecolor": "white",
        "axes.labelpad": 2.0,
        "axes.titlepad": 3.0,
        "axes.unicode_minus": True,
        "axes.prop_cycle": cycler(color=[C["blue"], C["vermillion"], C["grey"], C["sky"], C["orange"], C["green"],
                                         C["purple"]]),
        "lines.linewidth": 1.0,
        "lines.markersize": 3,
        "lines.markeredgewidth": 0.5,
        "patch.linewidth": 0.6,
        "errorbar.capsize": 0,
        "legend.frameon": False,
        "legend.handlelength": 1.4,
        "legend.handletextpad": 0.4,
        "legend.borderaxespad": 0.2,
        "legend.borderpad": 0.2,
        "legend.columnspacing": 1.0,
        "legend.labelspacing": 0.3,
        "mathtext.default": "regular",
        "mathtext.fontset": "custom",
        "mathtext.rm": LATIN,
        "mathtext.it": f"{LATIN}:italic",
        "mathtext.bf": f"{LATIN}:bold",
        "mathtext.sf": LATIN,
        "mathtext.tt": LATIN,
        "mathtext.cal": LATIN,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.bbox": "standard",  # "tight" would change the physical width
        "savefig.pad_inches": 0,
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
    })
    return {"latin": LATIN, "cjk": CJK}


class Canvas:
    """A figure laid out in millimetres from its top-left corner."""

    def __init__(self, width: str | float = "double", height_mm: float = 120.0) -> None:
        apply_style()
        self.w = WIDTH[width] if isinstance(width, str) else float(width)
        self.h = float(height_mm)
        self.fig = plt.figure(figsize=(self.w * MM, self.h * MM))
        self.labels: list[Text] = []

    # geometry -------------------------------------------------------------------------------------------------------
    def rect(self, x: float, y: float, w: float, h: float) -> list[float]:
        return [x / self.w, 1 - (y + h) / self.h, w / self.w, h / self.h]

    def ax(self, x: float, y: float, w: float, h: float, **kw: Any) -> Any:
        """Axes whose plotting area spans (x, y) → (x + w, y + h) mm, measured from the top-left corner."""
        return self.fig.add_axes(self.rect(x, y, w, h), **kw)

    def blank(self, x: float, y: float, w: float, h: float) -> Any:
        """Axes in millimetre data coordinates (origin top-left, y downwards) for schematics."""
        a = self.ax(x, y, w, h)
        a.set_xlim(0, w)
        a.set_ylim(h, 0)
        a.axis("off")
        return a

    def label(self, x: float, y: float, s: str) -> Text:
        """A panel label: 8 pt bold lower case, its top-left corner at (x, y) mm."""
        t = self.fig.text(x / self.w, 1 - y / self.h, s, fontsize=LABEL_PT, fontweight="bold", ha="left", va="top")
        t.set_gid("panel-label")
        self.labels.append(t)
        return t

    def text(self, x: float, y: float, s: str, **kw: Any) -> Text:
        return self.fig.text(x / self.w, 1 - y / self.h, s, **kw)

    # output ---------------------------------------------------------------------------------------------------------
    def save(self, name: str, outdir: str | Path, *, png_dpi: int = 600, overlap_ok: tuple[str, ...] = ()) -> dict[str, Any]:
        out = Path(outdir)
        out.mkdir(parents=True, exist_ok=True)
        self.fig.canvas.draw()
        report = qc_figure(self.fig, overlap_ok=overlap_ok)
        pdf, svg, png = out / f"{name}.pdf", out / f"{name}.svg", out / f"{name}.png"
        self.fig.savefig(pdf, metadata={"Title": name, "Creator": "TaoChronos paper figures (matplotlib)"})
        self.fig.savefig(svg)
        self.fig.savefig(png, dpi=png_dpi)
        from PIL import Image

        with Image.open(png) as im:  # Nature asks for RGB: flatten the alpha channel matplotlib writes onto white
            rgb = Image.new("RGB", im.size, "white")
            rgb.paste(im, mask=im.getchannel("A") if im.mode == "RGBA" else None)
        rgb.save(png, dpi=(png_dpi, png_dpi), optimize=True)
        report.update(measure_pdf(pdf))
        report["files"] = [str(p) for p in (pdf, svg, png)]
        w, h = report["width_mm"], report["height_mm"]
        if not any(abs(w - t) <= 0.5 for t in (89.0, 183.0)) and not (120.0 <= w <= 136.0):
            report["warnings"].append(f"width {w:.1f} mm is not 89, 120–136 or 183 mm")
        if h > MAX_HEIGHT + 0.5:
            report["warnings"].append(f"height {h:.1f} mm exceeds {MAX_HEIGHT:.0f} mm")
        bad_fonts = [f for f in report["fonts"] if not any(k in f for k in ("Arial", "Helvetica", "NotoSansCJK"))]
        if bad_fonts:
            report["warnings"].append(f"fonts other than Arial / Noto Sans CJK embedded: {bad_fonts}")
        qc_dir = out / "qc"
        qc_dir.mkdir(exist_ok=True)
        (qc_dir / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        plt.close(self.fig)
        return report


def _visible_texts(fig: Any) -> list[Text]:
    out = []
    for t in fig.findobj(Text):
        if not t.get_visible() or not t.get_text().strip():
            continue
        ax = t.axes
        if ax is not None and not ax.get_visible():
            continue
        out.append(t)
    return out


def qc_figure(fig: Any, *, overlap_ok: tuple[str, ...] = ()) -> dict[str, Any]:
    """Text sizes, stroke widths, text outside the page and text colliding with text."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    warnings: list[str] = []
    texts = _visible_texts(fig)
    sizes = []
    for t in texts:
        s = round(t.get_fontsize(), 2)
        sizes.append(s)
        if t.get_gid() == "panel-label":
            if abs(s - LABEL_PT) > 0.01 or t.get_fontweight() not in ("bold", 700):
                warnings.append(f"panel label {t.get_text()!r} is {s} pt / {t.get_fontweight()}")
        elif not (TEXT_MIN - 1e-6 <= s <= TEXT_MAX + 1e-6):
            warnings.append(f"text {t.get_text()[:40]!r} is {s} pt (5–7 pt)")
    widths = []
    for a in fig.findobj(lambda o: isinstance(o, (Line2D, Patch, Collection))):
        if not a.get_visible():
            continue
        if isinstance(a, Collection):
            lws = [float(v) for v in a.get_linewidths()] if len(a.get_edgecolors()) else []
        elif isinstance(a, Patch):
            ec = a.get_edgecolor()
            lws = [a.get_linewidth()] if ec is not None and ec[3] > 0 else []
        else:
            lws = [a.get_linewidth()] if a.get_linestyle() not in ("None", "none", "") else []
        for lw in lws:
            if lw <= 0:
                continue
            if a is fig.patch or (hasattr(a, "axes") and a.axes is not None and a is a.axes.patch):
                continue
            widths.append(round(lw, 3))
            if not (LINE_MIN - 1e-6 <= lw <= LINE_MAX + 1e-6):
                warnings.append(f"stroke of {lw:.2f} pt on {type(a).__name__} (0.25–1 pt)")
    fb = fig.bbox
    boxes = []
    for t in texts:
        bb = t.get_window_extent(renderer)
        if bb.width == 0 or bb.height == 0:
            continue
        if bb.x0 < fb.x0 - 1 or bb.y0 < fb.y0 - 1 or bb.x1 > fb.x1 + 1 or bb.y1 > fb.y1 + 1:
            warnings.append(f"text {t.get_text()[:40]!r} leaves the page")
        boxes.append((t, bb))
    pad = 0.3 * fig.dpi / 72  # 0.3 pt of tolerance
    for (t1, b1), (t2, b2) in combinations(boxes, 2):
        if b1.x0 + pad < b2.x1 and b2.x0 + pad < b1.x1 and b1.y0 + pad < b2.y1 and b2.y0 + pad < b1.y1:
            pair = f"{t1.get_text()[:30]!r} × {t2.get_text()[:30]!r}"
            if any(k in pair for k in overlap_ok):
                continue
            warnings.append(f"text overlaps: {pair}")
    return {"warnings": warnings, "text_sizes_pt": sorted(set(sizes)), "stroke_widths_pt": sorted(set(widths)),
            "n_texts": len(texts)}


def measure_pdf(path: Path) -> dict[str, Any]:
    import pymupdf

    doc = pymupdf.open(path)
    page = doc[0]
    w_mm, h_mm = page.rect.width / 72 * 25.4, page.rect.height / 72 * 25.4
    fonts = sorted({f[3].split("+")[-1] for f in page.get_fonts()})
    live_chars = len(page.get_text().strip())
    doc.close()
    return {"width_mm": round(w_mm, 2), "height_mm": round(h_mm, 2), "fonts": fonts, "live_text_chars": live_chars}


# small helpers used by several figures -----------------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def despine(ax: Any, left: bool = False, bottom: bool = False) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if left:
        ax.spines["left"].set_visible(False)
        ax.tick_params(left=False)
    if bottom:
        ax.spines["bottom"].set_visible(False)
        ax.tick_params(bottom=False)


def pval(p: float) -> str:
    """Exact P values as Nature asks, italic P: P = 0.032, P = 0.002, P = 2.4 × 10⁻¹⁶ (mathtext exponent)."""
    import math

    if p >= 0.001:
        return f"$\\mathit{{P}}$ = {p:.2g}"
    e = math.floor(math.log10(p))
    m = p / 10 ** e
    return f"$\\mathit{{P}}$ = {m:.1f} × 10$^{{{e}}}$"


_RENDERER = None
_NO_LINE_START = set("，。、；：？！」』）》〉,.;:?!)]…")


def text_width_mm(s: str, fontsize: float, weight: str = "normal") -> float:
    """Printed width of ``s`` in millimetres, with the figure fonts (Arial, then Noto Sans CJK glyph by glyph)."""
    global _RENDERER
    from matplotlib.backends.backend_agg import RendererAgg

    if _RENDERER is None:
        apply_style()
        _RENDERER = RendererAgg(100, 100, 72)
    prop = font_manager.FontProperties(family=mpl.rcParams["font.family"], size=fontsize, weight=weight)
    w, _, _ = _RENDERER.get_text_width_height_descent(s, prop, ismath=False)
    return w / 72 * 25.4


def wrap_mm(s: str, width_mm: float, fontsize: float, weight: str = "normal") -> list[str]:
    """Break mixed Chinese and Latin text into lines no wider than ``width_mm``: Latin words stay whole (a no-break
    space joins two), Chinese breaks between characters, and closing punctuation never starts a line.  Explicit
    newlines are kept."""
    import re

    lines: list[str] = []
    for para in s.split("\n"):
        tokens = []
        for tok in re.findall(r"[A-Za-z0-9_#\u00A0\u00C0-\u024F'’.,;:()\[\]%=<>≥≤±×+/\-–—·]+[ \t]*|[\u3400-\u9FFF]+\s*|\s+|.",
                              para):
            # a short run of Chinese characters (a name) stays whole; a long one (a quotation) breaks anywhere
            tokens.extend([tok] if len(tok.strip()) <= 8 or not "\u3400" <= tok[0] <= "\u9FFF" else list(tok))
        line = ""
        for tok in tokens:
            trial = line + tok
            if line and text_width_mm(trial.rstrip(), fontsize, weight) > width_mm and tok[0] not in _NO_LINE_START:
                lines.append(line.rstrip())
                line = tok.lstrip()
            else:
                line = trial
        lines.append(line.rstrip())
    return lines


__all__ = ["C", "CJK", "LATIN", "MM", "Canvas", "apply_style", "despine", "measure_pdf", "pval", "qc_figure",
           "text_width_mm", "tint", "wilson", "wrap_mm"]
