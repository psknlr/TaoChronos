"""Fig. 2 | A dated, layered corpus spanning two millennia, and the canon its citations define."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from nature_style import C, Canvas, tint

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"

PERIODS = [("Qin–Han", -475, 220), ("Wei–Jin", 220, 581), ("Sui–Tang", 581, 960), ("Song–Jin–Yuan", 960, 1368),
           ("Ming", 1368, 1644), ("Qing", 1644, 1912), ("R", 1912, 1950)]
X0, X1 = -500, 1960
DY = 36.0  # the construction pipeline (a) sits above the four data panels
PT = 0.3528  # mm per point


def box(ax, x, y, w, h, title=None, body=None, *, fc="white", ec=None, lw=0.5, title_fs=6, body_fs=5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.9", facecolor=fc,
                                edgecolor=ec or C["black"], lw=lw))
    if title and body:
        lines = body.count("\n") + 1
        block = title_fs * PT * 1.35 + lines * body_fs * PT * 1.2
        top = y + (h - block) / 2
        ax.text(x + w / 2, top, title, ha="center", va="top", fontsize=title_fs, fontweight="bold")
        ax.text(x + w / 2, top + title_fs * PT * 1.35, body, ha="center", va="top", fontsize=body_fs, linespacing=1.2)


def arrow(ax, p0, p1, color=None, lw=0.6):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>,head_length=1.5,head_width=0.8", mutation_scale=1, lw=lw,
                                 color=color or C["black"], shrinkA=0, shrinkB=0))


def pipeline(cv, wit, web) -> None:
    """a — from ten sources to a dated corpus (the steps of `taochronos corpus build`)."""
    ax = cv.blank(2, 6, 179, 28)
    by, bh = 1.0, 20.0
    src = wit.source.value_counts()
    named = ["kanripo", "jicheng", "cmeta", "wikisource", "aeam", "mcgill"]
    other = int(len(wit) - sum(src.get(k, 0) for k in named))
    sw = 36.0
    box(ax, 0.5, by, sw, bh)
    ax.text(1.8, by + 1.3, "Ten sources", ha="left", va="top", fontsize=6, fontweight="bold")
    rows = [("Siku quanshu (Kanripo)", src["kanripo"]), ("JiCheng editions", src["jicheng"]),
            ("CMETA collated editions", src["cmeta"]), ("Wikisource", src["wikisource"]),
            ("AEAM · McGill · other", f"{src['aeam']} · {src['mcgill']} · {other}")]
    for k, (lab, n) in enumerate(rows):
        yy = by + 5.0 + k * 2.35
        ax.text(1.8, yy, lab, ha="left", va="center", fontsize=5)
        ax.text(sw - 1.2, yy, f"{n}", ha="right", va="center", fontsize=5)
    ax.text(1.8, by + 5.0 + 5 * 2.35 + 0.6, "+ image catalogues: 10,001 records", ha="left", va="center", fontsize=5,
            color=C["dark"])
    steps = [("Admission", "historical texts only;\ncontemporary works\nremoved by review;\npseudepigrapha dated\n"
                           "by first appearance"),
             ("De-duplication", "12-character shingles\nagainst trusted sources;\nindependent witnesses\n"
                                "kept, never merged"),
             ("Layered dating", "text, commentary and\nlater additions dated\napart; undated → Qing,\nnever earlier"),
             ("Normalization", "variant and simplified\nforms unified for\nmatching only; the\ntranscription is\n"
                               "never altered")]
    x, w, gap = 0.5 + sw + 4.0, 21.0, 3.8
    for t, b in steps:
        arrow(ax, (x - gap + 0.5, by + bh / 2), (x - 0.4, by + bh / 2))
        box(ax, x, by, w, bh, t, b)
        x += w + gap
    arrow(ax, (x - gap + 0.5, by + bh / 2), (x - 0.4, by + bh / 2), color=C["blue"])
    ox, ow = x, 179 - x - 0.5
    box(ax, ox, by, ow, bh, fc=tint(C["blue"], 0.10), ec=C["blue"], lw=0.6)
    ax.text(ox + ow / 2, by + 1.3, "Corpus store", ha="center", va="top", fontsize=6, fontweight="bold")
    ax.text(ox + ow / 2, by + 4.2, f"{len(wit)} witnesses · {wit.work.nunique()} works\n123 M characters\n"
                                   "2.05 M passages; periods 475 BCE–1949", ha="center", va="top", fontsize=5,
            linespacing=1.2)
    ax.plot([ox + 3, ox + ow - 3], [by + 11.9, by + 11.9], color=C["blue"], lw=0.4)
    ax.text(ox + ow / 2, by + 12.8, f"canon of {web['rank'].max()} works → open\nweb corpus of {web.work.nunique()} works,\n"
                                    f"{web.chars_kept.sum() / 1e6:.1f} M characters, in the browser", ha="center",
            va="top", fontsize=5, linespacing=1.2)
    ax.text(0.5, by + bh + 3.3, "Every passage keeps its book, edition, volume · chapter · page, date range, textual "
                                "layer, transcription source and licence", ha="left", va="center", fontsize=5.5,
            color=C["dark"])
    cv.label(2, 3, "a")


def spread(lo: np.ndarray, hi: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Each witness counted once, its weight spread evenly over its composition range (a year when the range is one)."""
    out = np.zeros(len(edges) - 1)
    for a, b in zip(lo, hi):
        if b <= a:
            i = np.clip(np.searchsorted(edges, a, side="right") - 1, 0, len(out) - 1)
            out[i] += 1
            continue
        left, right = np.maximum(edges[:-1], a), np.minimum(edges[1:], b)
        out += np.clip(right - left, 0, None) / (b - a)
    return out


def period_bands(ax, ymax: float, labels: bool = True) -> None:
    for i, (name, a, b) in enumerate(PERIODS):
        if i % 2 == 0:
            ax.axvspan(max(a, X0), b, color=tint(C["grey"], 0.16), lw=0, zorder=0)
        if labels and name != "R":
            ax.text((max(a, X0) + b) / 2, ymax, name, ha="center", va="bottom", fontsize=5.5, color=C["dark"])


def main() -> dict:
    wit = pd.read_csv(SD / "fig2_corpus_witnesses.csv")
    canon = pd.read_csv(SD / "fig2_canon.csv")
    web = pd.read_csv(SD / "extfig_web_canon_witnesses.csv")
    wit["in_canon"] = wit.work.isin(set(canon.work))

    cv = Canvas("double", 122 + DY)
    pipeline(cv, wit, web)

    # b — witnesses through time ------------------------------------------------------------------------------------------
    ax = cv.ax(11, 9 + DY, 103, 44)
    edges = np.arange(X0, X1 + 25, 25)
    allw = spread(wit.comp_lo.values, wit.comp_hi.values, edges)
    canw = spread(wit[wit.in_canon].comp_lo.values, wit[wit.in_canon].comp_hi.values, edges)
    width = edges[1] - edges[0]
    ymax = 70
    period_bands(ax, ymax * 1.005)
    ax.bar(edges[:-1], allw, width=width, align="edge", color=C["grey"], lw=0, label=f"All witnesses (n = {len(wit)})",
           zorder=2)
    ax.bar(edges[:-1], canw, width=width, align="edge", color=C["blue"], lw=0,
           label=f"Witnesses of the {len(canon)} canon works (n = {int(wit.in_canon.sum())})", zorder=3)
    ax.set_xlim(X0, X1)
    ax.set_ylim(0, ymax)
    ax.set_xticks([-400, 0, 400, 800, 1200, 1600, 1900])
    ax.set_xticklabels(["400 BCE", "1 CE", "400", "800", "1200", "1600", "1900"])
    ax.set_ylabel("Witnesses per 25 years")
    ax.set_xlabel("Composition date (year)")
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.93), handlelength=1.0)
    cv.label(2, 3 + DY, "b")

    # c — how the witnesses were dated -------------------------------------------------------------------------------------
    order = [("curated", "Curated by the editors"), ("western", "Year in the book record"),
             ("preface", "Signed preface or colophon"), ("author", "Author's life or other works"),
             ("witness", "Another witness of the work"), ("dynasty", "Dynasty only"),
             ("undated", "Undated (counted as Qing)")]
    counts = wit.dating_class.value_counts()
    ax = cv.ax(151, 9 + DY, 27, 36)
    ys = np.arange(len(order))[::-1]
    vals = [int(counts.get(k, 0)) for k, _ in order]
    cols = [C["vermillion"] if k == "undated" else C["dark"] for k, _ in order]
    ax.barh(ys, vals, height=0.62, color=cols, lw=0)
    for y, v in zip(ys, vals):
        ax.text(v + 8, y, f"{v}", va="center", ha="left", fontsize=5.5)
    ax.set_yticks(ys)
    ax.set_yticklabels([lab for _, lab in order], fontsize=5.5)
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 200, 400])
    ax.set_xlabel("Witnesses")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    exact = int((wit.comp_hi == wit.comp_lo).sum())
    cv.text(118, 52.5 + DY, f"Dated to a single year: {exact} of {len(wit)}; median range 0 years,\n"
                       f"upper quartile {int(np.percentile(wit.comp_hi - wit.comp_lo, 75))} years", fontsize=5.5,
            va="top", color=C["dark"])
    cv.label(117, 3 + DY, "c")

    # d — the canon: influence against date -------------------------------------------------------------------------------
    ax = cv.ax(11, 70 + DY, 103, 42)
    period_bands(ax, 160, labels=False)
    size = 3 + 1.6 * canon.witnesses.clip(upper=10)
    top = canon["rank"] <= 10
    ax.scatter(canon[~top].year_mid, canon[~top].score, s=size[~top], color=C["grey"], alpha=0.75, lw=0, zorder=2)
    ax.scatter(canon[top].year_mid, canon[top].score, s=size[top], color=C["blue"], lw=0, zorder=3)
    # rank numbers beside the ten most influential works, keyed in the empty lower left of the panel
    place = {1: (-38, 0, "right"), 2: (-38, 0, "right"), 3: (22, 3.2, "left"), 4: (-30, 4.0, "right"),
             5: (22, -3.4, "left"), 6: (22, -4.2, "left"), 7: (26, 0, "left"), 8: (22, 3.0, "left"),
             9: (-26, -3.0, "right"), 10: (26, 0, "left")}
    for _, r in canon[top].iterrows():
        dx, dy, ha = place[int(r["rank"])]
        ax.text(r.year_mid + dx, r.score + dy, str(int(r["rank"])), fontsize=5.5, ha=ha, va="center",
                color=C["blue"], fontweight="bold")
    key = canon[top].sort_values("rank")
    for j, (x_num, rows) in enumerate(((-420, key.iloc[:5]), (-20, key.iloc[5:]))):
        nums = "\n".join(str(int(r["rank"])) for _, r in rows.iterrows())
        names = "\n".join(r.title_en for _, r in rows.iterrows())
        ax.text(x_num, 95, nums, fontsize=5.5, va="top", ha="right", linespacing=1.35, color=C["blue"], fontweight="bold")
        ax.text(x_num + 25, 95, names, fontsize=5.5, va="top", ha="left", linespacing=1.35)
    ax.set_xlim(X0, X1)
    ax.set_ylim(0, 160)
    ax.set_yticks([0, 40, 80, 120, 160])
    ax.set_xticks([-400, 0, 400, 800, 1200, 1600, 1900])
    ax.set_xticklabels(["400 BCE", "1 CE", "400", "800", "1200", "1600", "1900"])
    ax.set_xlabel("Composition date (year; midpoint of range)")
    ax.set_ylabel("Influence score")
    for s_, lab in ((1, "1"), (5, "5"), (10, "≥10")):
        ax.scatter([], [], s=3 + 1.6 * s_, color=C["grey"], lw=0, label=lab)
    ax.legend(title="Witnesses in the corpus", loc="upper right", ncol=3, handletextpad=0.2, columnspacing=0.8,
              bbox_to_anchor=(1.0, 1.02))
    cv.label(2, 64 + DY, "d")

    # e — the 要籍语料 carried by the web client --------------------------------------------------------------------------
    ax = cv.ax(133, 70 + DY, 46, 42)
    first = web[web.witness_no == 1]
    rest = web[web.witness_no > 1]
    for sub, col, lab in ((first[~first.whole], C["grey"], "Chapters sampled"), (first[first.whole], C["blue"], "Whole text")):
        ax.scatter(sub["rank"], sub.chars_kept / 1000, s=4, color=col, lw=0, label=lab, zorder=3)
    ax.scatter(rest["rank"], rest.chars_kept / 1000, s=6, marker="^", facecolor="none", edgecolor=C["dark"], lw=0.4,
               label="Further witness (top 10)", zorder=3)
    last = int(web["rank"].max())
    budget_x = [1, 10, 10, 40, 40, 120, 120, last]
    budget_y = [350, 350, 50, 50, 25, 25, 12, 12]
    ax.plot(budget_x, budget_y, color=C["vermillion"], lw=0.7, ls=(0, (3, 1.5)), label="Budget per first witness", zorder=2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.8, last * 1.2)
    ax.set_ylim(0.8, 700)
    ax.set_xticks([1, 10, 100, last])
    ax.set_xticklabels(["1", "10", "100", str(last)])
    ax.set_yticks([1, 10, 100])
    ax.set_yticklabels(["1", "10", "100"])
    ax.minorticks_off()
    ax.set_xlabel("Canon rank")
    ax.set_ylabel("Characters kept (×10$^3$)")
    ax.legend(loc="lower left", handletextpad=0.2, borderaxespad=0.1, labelspacing=0.2, fontsize=5.5)
    ax.text(last * 1.2, 700, f"{web.work.nunique()} works · {len(web)} witnesses\n{web.chars_kept.sum() / 1e6:.2f} M characters",
            ha="right", va="top", fontsize=5.5)
    cv.label(121, 64 + DY, "e")

    rep = cv.save("fig2_corpus", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
