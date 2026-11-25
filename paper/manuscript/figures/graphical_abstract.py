"""Fig. 1 | Graphical abstract — the paper as one flowchart.

    python paper/manuscript/figures/graphical_abstract.py

Two inputs (a scientist's question, fixed as a research contract, and the dated corpus) meet in the agents, which may
only propose; commit hooks refuse, validators grade and a human expert alone decides, every step a typed event in an
append-only log.  Below the pipeline, what was measured with rules alone.  The figure is 183 mm wide at 5:2, the
proportion Engineering asks of a graphical abstract (at least 1328 × 531 px), so one artwork serves as Fig. 1 of both
manuscripts and as Engineering's separate file.

Nothing is drawn from memory.  The histogram of the corpus, the sixteen agents (filled: may consult a model), the
grid of 240 quotation decisions, the 19 × 7 matrix of invariants, the 84 held-out readings and the three bars of the
temporal benchmark are read from ``paper/figures/source_data``, the files the paper's own figures are drawn from, and
every number in a label is asserted against them and against the manuscript's text.

Outputs, beside this script: ``graphical_abstract.pdf`` (vector, live text, TrueType fonts), ``graphical_abstract.svg``
(text as outlines, so that it looks the same wherever it is shown, the repository's README included) and
``graphical_abstract.png`` (600 dpi, 4322 × 1729 px).  The legend is ``graphical_abstract.md``; ``build.py`` one
directory up sets the figure and its legend first in both manuscripts.  ``--draft`` reports a line that does not fit
its place instead of stopping.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import matplotlib as mpl
import numpy as np
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, Polygon, Rectangle

HERE = Path(__file__).resolve().parent
PAPER = HERE.parents[1]
SD = PAPER / "figures" / "source_data"
sys.path.insert(0, str(PAPER / "cases"))

import cjk_truetype  # noqa: E402

cjk_truetype.EXTRA_SOURCES.append(Path(__file__))  # the Chinese characters this file draws (道乃久)

from case_style import (BLUE, DARK, GREY, LIGHT, ORANGE, PALE, VERM, Canvas, dot, line, rbox, rich,  # noqa: E402
                        tint, width_mm)
from nature_style import measure_pdf, qc_figure  # noqa: E402

W, H = 183.0, 73.2  # mm: 5:2
INK = "#1A1A1A"
ORANGE_T = "#A86A00"  # the palette's orange, darkened for text on white
TEXT_PT = (6.0, 12.5)  # a graphical abstract is read small: nothing under 6 pt, numbers up to 12 pt
MANUSCRIPTS = [HERE.parent / "manuscript.md", HERE.parent / "engineering.md"]
PERIODS = (-475, 1949)  # the span of the paper's periods (paper/figures/fig2_corpus.py), as the manuscript states it


def stated(*phrases: str) -> None:
    """Every phrase is in both manuscripts as written."""
    for path in MANUSCRIPTS:
        text = " ".join(path.read_text(encoding="utf-8").split())
        for p in phrases:
            assert p in text, f"{p!r} is not in {path.name}"


def table(name: str) -> list[dict]:
    with open(SD / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --- the numbers, from the paper's source data ------------------------------------------------------------------------
def numbers() -> dict:
    arch = json.loads((SD / "fig1_architecture.json").read_text(encoding="utf-8"))
    wit = table("fig2_corpus_witnesses.csv")
    probes = table("fig4_hallucination.csv")
    inv = table("fig4_invariants.csv")
    mut = json.loads((SD / "extfig_mutation_matrix.json").read_text(encoding="utf-8"))
    cases = table("fig4_interpretive_cases.csv")
    rv = json.loads((SD / "fig5_research_value_full_corpus.json").read_text(encoding="utf-8"))
    n = {}
    # the corpus, as the paper's corpus figure draws it: every witness counts once, its weight spread evenly over
    # its composition range; the axis runs over the paper's periods, 475 BCE to 1949 (three witnesses have a bound
    # outside them, and that part of their weight falls off the axis)
    edges = np.arange(-500, 2000, 50)
    hist = np.zeros(len(edges) - 1)
    for r in wit:
        lo, hi = float(r["comp_lo"]), float(r["comp_hi"])
        if hi <= lo:
            hist[int(np.clip(np.searchsorted(edges, lo, side="right") - 1, 0, len(hist) - 1))] += 1
        else:
            hist += np.clip(np.minimum(edges[1:], hi) - np.maximum(edges[:-1], lo), 0, None) / (hi - lo)
    n["hist"], n["edges"] = hist, edges
    n["witnesses"], n["works"] = len(wit), len({r["work"] for r in wit})
    n["first"], n["last"] = PERIODS[0], PERIODS[1]
    outside = sum(float(r["comp_lo"]) < edges[0] or float(r["comp_hi"]) > edges[-1] for r in wit)
    assert (n["witnesses"], n["works"]) == (966, 761) and outside <= 3 and 964 < hist.sum() <= 966, (n, outside)
    # the agent
    agents = arch["agents"]
    n["director"] = next(a for a in agents if a["role"] == "director")["mode"] == "hybrid"
    n["specialists"] = [a["mode"] == "hybrid" for a in agents if a["role"] != "director"]
    n["tools"], n["events"], n["gates"] = len(arch["tools"]), len(arch["authority"]), list(arch["gates"])
    assert (len(agents), len(n["specialists"]), n["tools"], n["events"]) == (16, 15, 85, 61)
    assert n["gates"] == [f"G{i}" for i in range(9)] and arch["gates"]["G7"] == "Expert"
    assert set(arch["hooks"]["BeforeClaimCommit"]) == {"provenance_validator", "semantic_support", "anachronism_guard"}
    # quotations: four probes on 60 passages
    n["accepted"] = sum(int(p["passed"]) for p in probes if p["probe"].startswith("Verbatim quotation"))
    n["refused"] = sum(int(p["passed"]) for p in probes if not p["probe"].startswith("Verbatim quotation"))
    assert (n["accepted"], n["refused"]) == (60, 180) and all(p["passed"] == p["n"] for p in probes)
    # invariants: intact, then one boundary removed at a time
    ids = [r["id"] for r in inv]
    assert len(ids) == 19 and all(r["held"] == "True" for r in inv)
    n["matrix"] = [[i in v["broken"] for i in ids] for v in mut["variants"]]
    assert mut["variants"][0]["name"] == "intact" and len(mut["variants"]) == 7
    assert all(v["broken"] == ([v["target"]] if v["target"] else []) and not v["off_target"] for v in mut["variants"])
    n["cells_held"] = sum(v["held"] for v in mut["variants"])
    assert n["cells_held"] == 127
    # hard readings
    held = [c for c in cases if c["split"] == "heldout"]
    n["readings"] = [c["correct"] == "True" for c in held]
    assert (len(held), sum(n["readings"])) == (84, 82)
    assert all(c["unsafe"] == "True" for c in held if c["correct"] != "True")
    # research value
    by = {r["ranker"]: r for r in rv["rankers"]}
    n["p10"] = [(by[k]["p10"], by[k]["p10_lo"], by[k]["p10_hi"]) for k in
                ("Adamic–Adar (D4)", "Popularity", "Chance (20 draws)")]
    assert [v[0] for v in n["p10"]] == [0.168, 0.134, 0.054] and rv["leakage"] == 0
    assert rv["paired"][0]["p"] == 2.4e-16
    stated("966 witnesses", "123 million characters", "475 BCE–1949", "180 of 180 corrupted quotations",
           "19 of 19 safety invariants", "82 of 84 held-out hard", "precision@10 0.168", "0.054 for chance",
           "deterministic harness, stochastic intelligence", "85 tools", "61 event types")
    return n


# --- pictograms: white on a disc of the principal's colour ------------------------------------------------------------
def glyph_agents(ax, cx, cy, n):
    """The Director and its fifteen specialists: filled, may consult a model; open, rules only."""
    ring = 4.05
    pts = [(cx + ring * math.sin(2 * math.pi * k / 15), cy - ring * math.cos(2 * math.pi * k / 15)) for k in range(15)]
    for x, y in pts:
        ax.plot([cx, x], [cy, y], color="white", lw=0.35, alpha=0.75, zorder=5, solid_capstyle="round")
    for (x, y), model in zip(pts, n["specialists"]):
        ax.add_patch(Circle((x, y), 0.62, facecolor="white" if model else BLUE, edgecolor="white", lw=0.5, zorder=6))
    ax.add_patch(Circle((cx, cy), 1.15, facecolor="white" if n["director"] else BLUE, edgecolor="white", lw=0.5,
                        zorder=6))


def glyph_refuse(ax, cx, cy, n):
    """A cross: the commit is refused."""
    half, t = 3.5, 0.72
    for sign in (1, -1):
        c = [(-half, -t), (half, -t), (half, t), (-half, t)]
        a = sign * math.pi / 4
        ax.add_patch(Polygon([(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a))
                              for x, y in c], closed=True, facecolor="white", edgecolor="none", zorder=6))


def glyph_gates(ax, cx, cy, n):
    """Nine gates; the eighth, G7, is not the validators' to set."""
    side, gap = 2.25, 0.65
    x0, y0 = cx - 1.5 * side - gap, cy - 1.5 * side - gap
    for k, g in enumerate(n["gates"]):
        x, y = x0 + (k % 3) * (side + gap), y0 + (k // 3) * (side + gap)
        if g == "G7":
            ax.add_patch(Rectangle((x + 0.22, y + 0.22), side - 0.44, side - 0.44, facecolor="none", edgecolor=ORANGE,
                                   lw=0.9, zorder=6))
        else:
            ax.add_patch(Rectangle((x, y), side, side, facecolor="white", edgecolor="none", zorder=6))


def glyph_person(ax, cx, cy, n):
    clip = Circle((cx, cy), 5.7, transform=ax.transData)  # the shoulders stop short of the disc's edge
    ax.add_patch(Circle((cx, cy - 1.75), 1.95, facecolor="white", edgecolor="none", zorder=6))
    body = Ellipse((cx, cy + 5.1), 8.4, 7.8, facecolor="white", edgecolor="none", zorder=6)
    ax.add_patch(body)
    body.set_clip_path(clip)


def node(ax, cx, cy, colour, glyph, n, r=6.3):
    ax.add_patch(Circle((cx, cy), r, facecolor=colour, edgecolor="none", zorder=4))
    glyph(ax, cx, cy, n)


def flow(ax, x0, y0, x1, y1, rad=0.0, colour=DARK):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>,head_length=1.9,head_width=1.15",
                                 mutation_scale=1.0, lw=1.0, color=colour, shrinkA=0, shrinkB=0, zorder=3,
                                 connectionstyle=f"arc3,rad={rad}", joinstyle="miter", capstyle="butt"))


STRICT = "--draft" not in sys.argv  # a line that does not fit its place stops the build, unless drafting


def fits(s: str, w: float, fs: float = 6.5, weight: str = "normal") -> None:
    over = width_mm(s, fs, weight) - w
    if over > 0:
        if STRICT:
            raise AssertionError(f"{over:.1f} mm too wide: {s}")
        print(f"  {over:.1f} mm too wide: {s}")


def caption(ax, cx, y, head, colour, actor, lines, w=28.0):
    ax.text(cx, y, head, ha="center", va="top", fontsize=8.5, fontweight="bold", color=colour)
    ax.text(cx, y + 3.75, actor, ha="center", va="top", fontsize=6.5, fontweight="bold", color=INK)
    for k, s in enumerate(lines):
        fits(s, w)
        ax.text(cx, y + 6.5 + k * 2.55, s, ha="center", va="top", fontsize=6.5, color=DARK)


# --- thumbnails: the data of each result, cell by cell ---------------------------------------------------------------
def thumb_quotations(ax, x, y, n, size=10.6):
    """Four probes on 60 passages, a band each: the verbatim quotations, accepted (light), then the three kinds of
    corrupted quotation, refused (dark)."""
    cols, rows, gap = 15, 4, 0.42
    assert cols * rows == n["accepted"] and 3 * cols * rows == n["refused"]
    pw, ph = size / cols, (size - 3 * gap) / (4 * rows)
    for band in range(4):
        for k in range(cols * rows):
            ax.add_patch(Rectangle((x + (k % cols) * pw, y + band * (rows * ph + gap) + (k // cols) * ph), pw * 0.76,
                                   ph * 0.76, facecolor=tint(BLUE, 0.42) if band == 0 else BLUE, edgecolor="none",
                                   zorder=4))


def thumb_invariants(ax, x, y, n, size=10.6):
    """19 invariants (columns) on the intact agent (top row) and with each of six safeguards removed."""
    m = n["matrix"]
    pw, ph = size / 19, size / len(m)
    for i, row in enumerate(m):
        for j, broken in enumerate(row):
            ax.add_patch(Rectangle((x + j * pw, y + i * ph), pw * 0.78, ph * 0.8,
                                   facecolor=VERM if broken else (INK if i == 0 else tint(INK, 0.5)),
                                   edgecolor="none", zorder=4))


def thumb_readings(ax, x, y, n, size=10.6):
    """84 held-out hard cases in rows of ten: the two unsafe errors last."""
    cols, rows = 10, 9
    pw, ph = size / cols, size / rows
    for k, ok in enumerate(sorted(n["readings"], reverse=True)):
        ax.add_patch(Circle((x + (k % cols + 0.5) * pw, y + (k // cols + 0.5) * ph), 0.38,
                            facecolor=BLUE if ok else VERM, edgecolor="none", zorder=4))


def thumb_ranking(ax, x, y, n, size=10.6):
    """Precision at 10 of the ranking from the past, of popularity and of chance; whiskers, 95% intervals."""
    top = 0.20
    bw, gap = 2.6, 1.3
    line(ax, [x - 0.3, x + 3 * bw + 2 * gap + 0.3], [y + size] * 2, color=INK, lw=0.5)
    for k, ((v, lo, hi), col) in enumerate(zip(n["p10"], (BLUE, GREY, LIGHT))):
        bx = x + k * (bw + gap)
        ax.add_patch(Rectangle((bx, y + size - v / top * size), bw, v / top * size, facecolor=col, edgecolor="none",
                               zorder=4))
        if lo is not None:
            line(ax, [bx + bw / 2] * 2, [y + size - hi / top * size, y + size - lo / top * size], color=INK, lw=0.5,
                 z=5)


def kpi(ax, x, y, thumb, n, number, lines, w):
    thumb(ax, x, y + 0.9, n)
    tx = x + 12.6
    ax.text(tx, y - 0.35, number, ha="left", va="top", fontsize=12, fontweight="bold", color=INK)
    for k, s in enumerate(lines):
        fits(s, w - 12.6)
        ax.text(tx, y + 4.75 + k * 2.5, s, ha="left", va="top", fontsize=6.5, color=DARK)


def main() -> dict:
    n = numbers()
    cv = Canvas(W, H)
    ax = cv.blank(0, 0, W, H)

    # the name, the three verbs and the principle ---------------------------------------------------------------------
    x = rich(ax, 2.0, 2.0, [("TaoChronos", {"weight": "bold", "color": INK})], 10, va="top")
    x = rich(ax, x + 1.2, 2.35, [("道乃久", {"color": DARK})], 8.5, va="top")
    line(ax, [x + 2.6] * 2, [2.3, 5.6], color=GREY, lw=0.5)
    rich(ax, x + 5.0, 2.4, [("Agents propose", {"weight": "bold", "color": BLUE}), ("  ·  ", {"color": GREY}),
                           ("validators grade", {"weight": "bold", "color": INK}), ("  ·  ", {"color": GREY}),
                           ("experts decide", {"weight": "bold", "color": ORANGE_T})], 8.5, va="top")
    ax.text(W - 2.0, 2.75, "Deterministic harness, stochastic intelligence", ha="right", va="top", fontsize=7,
            fontstyle="italic", color=DARK)

    # two inputs ---------------------------------------------------------------------------------------------------
    xl, wl = 2.0, 44.0
    ya, ha_ = 9.2, 12.6
    rbox(ax, xl, ya, wl, ha_, fc=tint(ORANGE, 0.16), r=1.2)
    ax.add_patch(Circle((xl + 5.6, ya + ha_ / 2), 3.5, facecolor=ORANGE, edgecolor="none", zorder=4))
    ax.text(xl + 5.6, ya + ha_ / 2 + 0.15, "?", ha="center", va="center", fontsize=11, fontweight="bold",
            color="white", zorder=6)
    ax.text(xl + 11.0, ya + 1.2, "Ask", ha="left", va="top", fontsize=8.5, fontweight="bold", color=ORANGE_T)
    for k, s in enumerate(("a scientist’s question,", "fixed as a research contract", "before the first task")):
        fits(s, wl - 12.0)
        ax.text(xl + 11.0, ya + 4.85 + k * 2.5, s, ha="left", va="top", fontsize=6.5, color=DARK)

    yc, hc = 24.6, 27.0  # the corpus
    rbox(ax, xl, yc, wl, hc, fc=PALE, r=1.2)
    ax.text(xl + 2.2, yc + 1.4, "Read", ha="left", va="top", fontsize=8.5, fontweight="bold", color=INK)
    ax.text(xl + 2.2, yc + 5.2, f"{n['witnesses']}", ha="left", va="top", fontsize=12, fontweight="bold", color=BLUE)
    for k, s in enumerate((f"dated witnesses of {n['works']} works,", "123 million characters")):
        fits(s, wl - 13.0)
        ax.text(xl + 11.4, yc + 5.35 + k * 2.5, s, ha="left", va="top", fontsize=6.5, color=INK if k == 0 else DARK)
    # witnesses by composition date
    hx, hw, hy, hh = xl + 2.4, wl - 4.8, yc + 11.9, 10.4
    edges, hist = n["edges"], n["hist"]
    sx = lambda yr: hx + (yr - edges[0]) / (edges[-1] - edges[0]) * hw  # noqa: E731
    for (a, b), v in zip(pairwise(edges), hist):
        if v > 0:
            ax.add_patch(Rectangle((sx(a) + 0.07, hy + hh - v / hist.max() * hh), sx(b) - sx(a) - 0.14,
                                   v / hist.max() * hh, facecolor=BLUE, edgecolor="none", zorder=4))
    line(ax, [hx, hx + hw], [hy + hh] * 2, color=INK, lw=0.5)
    ax.text(hx, hy + 2.2, "by date of composition", ha="left", va="top", fontsize=6, color=DARK)
    assert hist[: np.searchsorted(edges, 1100)].max() / hist.max() * hh < hh - 5.0  # the label stands clear of the bars
    for yr, lab, ha in ((n["first"], "475 BCE", "left"), (1000, "1000", "center"), (n["last"], "1949", "right")):
        line(ax, [sx(yr)] * 2, [hy + hh, hy + hh + 0.8], color=INK, lw=0.5)
        ax.text(sx(yr), hy + hh + 1.2, lab, ha=ha, va="top", fontsize=6, color=DARK)

    # the pipeline -------------------------------------------------------------------------------------------------
    yp = 21.6
    xs = [61.0, 90.5, 120.0, 149.5]
    xf, wf = 164.0, W - 2.0 - 164.0
    r = 6.3
    flow(ax, xl + wl + 0.8, ya + ha_ / 2, xs[0] - r * 0.9, yp - r * 0.6, rad=-0.2)
    flow(ax, xl + wl + 0.8, yc + 4.4, xs[0] - r * 0.9, yp + r * 0.6, rad=0.2)
    for a, b in pairwise(xs):
        flow(ax, a + r + 1.4, yp, b - r - 1.4, yp)
    flow(ax, xs[-1] + r + 1.4, yp, xf - 1.2, yp)
    node(ax, xs[0], yp, BLUE, glyph_agents, n)
    node(ax, xs[1], yp, VERM, glyph_refuse, n)
    node(ax, xs[2], yp, INK, glyph_gates, n)
    node(ax, xs[3], yp, ORANGE, glyph_person, n)
    ycap = yp + r + 1.6
    wc = xs[1] - xs[0] - 1.6
    caption(ax, xs[0], ycap, "Propose", BLUE, f"16 agents, {n['tools']} tools",
            ["rules or language models", "draft claims, hypotheses;", "never a verdict"], wc)
    caption(ax, xs[1], ycap, "Refuse", VERM, "hooks at every commit",
            ["a quote not verbatim,", "or not stating its claim;", "an anachronism"], wc)
    caption(ax, xs[2], ycap, "Grade", INK, "validators",
            ["nine gates, G0 to G8,", "from source to falsification;", "then the research contract"], wc)
    caption(ax, xs[3], ycap, "Decide", ORANGE_T, "a human expert",
            ["alone approves", "or rejects a hypothesis", "(gate G7)"], wc)
    # what leaves the pipeline: a finding that can be walked back to its witness
    yf0, hf0 = yp - 9.6, 33.0
    rbox(ax, xf, yf0, wf, hf0, fc="white", ec=BLUE, lw=0.8, r=1.2, z=2)
    ax.text(xf + wf / 2, yf0 + 1.5, "Finding", ha="center", va="top", fontsize=8.5, fontweight="bold", color=BLUE)
    chain = ["claim", "quote", "passage", "witness", "edition", "date", "licence"]
    ys = [yf0 + 7.4 + k * 3.85 for k in range(len(chain))]
    line(ax, [xf + 3.0] * 2, [ys[0], ys[-1]], color=BLUE, lw=0.7, z=3)
    for yy, s in zip(ys, chain):
        dot(ax, xf + 3.0, yy, 0.72, fc=BLUE, z=4)
        fits(s, wf - 6.2)
        ax.text(xf + 5.0, yy, s, ha="left", va="center_baseline", fontsize=6.5, color=INK)

    # the harness beneath every step ---------------------------------------------------------------------------------
    xr = xl + wl + 3.0
    wr = W - 2.0 - xr
    yr_ = 47.3
    rbox(ax, xr, yr_, wr, 4.3, fc=INK, r=1.0, z=2)
    rule = "   every change is a typed event in an append-only log, refused if its principal may not emit it"
    xe = rich(ax, xr + 2.2, yr_ + 2.15, [("Deterministic harness", {"weight": "bold", "color": "white"}),
                                        (rule, {"color": "white"})], 6.5, va="center_baseline", z=6)
    if xe > xr + wr - 1.5:
        fits("the harness line", width_mm("the harness line", 6.5) - (xe - xr - wr + 1.5))

    # what was measured ----------------------------------------------------------------------------------------------
    ym = 54.6
    ax.text(xl, ym, "Measured with rules alone: no language model was called", ha="left", va="top", fontsize=7,
            fontweight="bold", color=INK)
    wk = (W - 4.0) / 4
    yk = ym + 4.4
    kpi(ax, xl, yk, thumb_quotations, n, f"{n['refused']}/180", ["corrupted quotations refused;",
                                                                 "all 60 verbatim ones accepted"], wk - 1.5)
    kpi(ax, xl + wk, yk, thumb_invariants, n, "19/19", ["safety invariants hold; each of", "six safeguards, removed,",
                                                        "breaks only its own"], wk - 1.5)
    kpi(ax, xl + 2 * wk, yk, thumb_readings, n, f"{sum(n['readings'])}/84", ["held-out hard cases read",
                                                                            "correctly; 2 unsafe errors,",
                                                                            "reported, not patched"], wk - 1.5)
    kpi(ax, xl + 3 * wk, yk, thumb_ranking, n, f"{n['p10'][0][0]:.3f}", ["precision@10: earlier texts",
                                                                        "anticipate later links;",
                                                                        "popularity 0.134, chance 0.054"], wk)
    return save(cv)


def save(cv: Canvas) -> dict:
    fig = cv.fig
    fig.canvas.draw()
    rep = qc_figure(fig)
    sizes = rep["text_sizes_pt"]
    rep["warnings"] = [w for w in rep["warnings"] if " pt (5–7 pt)" not in w and "stroke of" not in w]
    if min(sizes) < TEXT_PT[0] or max(sizes) > TEXT_PT[1]:
        rep["warnings"].append(f"text of {min(sizes)}–{max(sizes)} pt, outside {TEXT_PT[0]}–{TEXT_PT[1]} pt")
    pdf, svg, png = (HERE / f"graphical_abstract.{e}" for e in ("pdf", "svg", "png"))
    fig.savefig(pdf, metadata={"Title": "TaoChronos: graphical abstract", "Creator": "TaoChronos paper figures (matplotlib)",
                               "CreationDate": None})  # no date: the same bytes on every run
    with mpl.rc_context({"svg.fonttype": "path", "svg.hashsalt": "taochronos"}):
        fig.savefig(svg, metadata={"Date": None})
    fig.savefig(png, dpi=600)
    from PIL import Image

    with Image.open(png) as im:
        rgb = Image.new("RGB", im.size, "white")
        rgb.paste(im, mask=im.getchannel("A") if im.mode == "RGBA" else None)
    rgb.save(png, dpi=(600, 600), optimize=True)
    rep.update(measure_pdf(pdf))
    rep["png_px"] = list(rgb.size)
    other = [f for f in rep["fonts"] if not any(k in f for k in ("Arial", "Helvetica", "NotoSansCJK"))]
    if other:  # as the package's figures report it: the fallback was used on a machine without Arial
        rep["warnings"].append(f"fonts other than Arial / Noto Sans CJK embedded: {other}")
    if abs(rep["width_mm"] / rep["height_mm"] - 2.5) > 0.01 or rgb.size[0] < 1328 or rgb.size[1] < 531:
        rep["warnings"].append(f"not 5:2 at 1328 × 531 px or more: {rep['width_mm']} × {rep['height_mm']} mm, {rgb.size}")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "png_px", "fonts", "text_sizes_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
