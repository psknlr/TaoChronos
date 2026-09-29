"""Fig. 4 | Graph rankings computed from the past anticipate the links later physicians wrote (research value)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

from nature_style import C, Canvas, pval, tint, wilson

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"


def box(ax, x, y, w, h, text, *, fc=None, ec=None, fs=5.5, weight="normal", ha="center"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8", facecolor=fc or "white",
                                edgecolor=ec or C["black"], lw=0.5))
    tx = x + w / 2 if ha == "center" else x + 1.2
    ax.text(tx, y + h / 2, text, ha=ha, va="center", fontsize=fs, fontweight=weight, linespacing=1.25)


def arrow(ax, x0, y0, x1, y1, color=None):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>,head_length=1.6,head_width=0.9",
                                 mutation_scale=1, lw=0.6, color=color or C["black"], shrinkA=0, shrinkB=0))


def main() -> dict:
    rv = json.loads((SD / "fig4_research_value_full_corpus.json").read_text(encoding="utf-8"))
    cv = Canvas("double", 96)

    # a — the protocol -------------------------------------------------------------------------------------------------
    W, H = 92.0, 44.0
    ax = cv.blank(4, 5, W, H)
    cut = 47.0
    ax.add_patch(FancyBboxPatch((0.5, 5.0), cut - 3.5, 37.5, boxstyle="round,pad=0,rounding_size=1.2",
                                facecolor=tint(C["blue"], 0.08), edgecolor="none"))
    ax.add_patch(FancyBboxPatch((cut + 3.0, 5.0), W - cut - 3.5, 37.5, boxstyle="round,pad=0,rounding_size=1.2",
                                facecolor=tint(C["vermillion"], 0.08), edgecolor="none"))
    ax.plot([cut, cut], [2.6, 42.5], color=C["black"], lw=0.7, ls=(0, (3, 1.5)))
    ax.text(cut, 1.2, "Cutoff year: 1127 or 1368", ha="center", va="center", fontsize=5.5)
    ax.text(2.0, 7.4, "Past view: wholly before the cutoff", ha="left", va="center", fontsize=5.5,
            color=C["blue"], fontweight="bold")
    ax.text(W - 1.2, 7.4, "Future: wholly after", ha="right", va="center", fontsize=5.5, color=C["vermillion"],
            fontweight="bold")
    box(ax, 2.5, 10.6, 41.0, 7.2, "Topic graph from rule-extracted claims:\ndiseases, symptoms, formulas, drugs")
    arrow(ax, 23.0, 17.8, 23.0, 20.2)
    box(ax, 2.5, 20.2, 41.0, 7.2, f"Candidates: the topic's past formulas and\n"
                                  f"drugs not yet linked to it (n = {rv['candidates']:,})")
    arrow(ax, 23.0, 27.4, 23.0, 29.8)
    box(ax, 2.5, 29.8, 41.0, 9.6, "Rank the candidates: Adamic–Adar (D4),\ncommon neighbours, resource allocation,\n"
                                  "popularity or chance")
    rx, rw = cut + 5.0, W - cut - 7.5
    box(ax, rx, 11.5, rw, 12.5, "A candidate comes true\nwhen claims in two or\nmore later books link\nit to the topic",
        fc="white")
    arrow(ax, 43.5, 34.6, rx, 21.0)
    ax.text(rx + rw / 2, 30.4, f"{rv['came_true']:,} of {rv['candidates']:,} came true\n(base rate {rv['base_rate'] * 100:.1f}%)",
            ha="center", va="center", fontsize=5.5)
    ax.text(rx + rw / 2, 37.6, f"{rv['topic_cutoff_pairs_scored']} topic–cutoff pairs\nleakage 0",
            ha="center", va="center", fontsize=5.5)
    ax.text(cut, 44.2, "Passages that straddle the cutoff belong to neither side", ha="center", va="center", fontsize=5,
            color=C["dark"])
    cv.label(2, 3, "a")

    # b — precision and average precision of the rankers ----------------------------------------------------------------
    rankers = rv["rankers"]
    names = [r["ranker"] for r in rankers]
    colors = [C["blue"], C["dark"], C["dark"], C["grey"], C["grey"]]
    metrics = [("p10", "Precision@10"), ("p20", "Precision@20"), ("map", "Mean average\nprecision")]
    ys = np.arange(len(rankers))[::-1]
    for k, (key, label) in enumerate(metrics):
        axb = cv.ax(130 + k * 17.5, 11, 14, 30)
        for y, r, col in zip(ys, rankers, colors):
            if r[f"{key}_lo"] is not None:
                axb.plot([r[f"{key}_lo"], r[f"{key}_hi"]], [y, y], color=col, lw=0.7, solid_capstyle="butt")
            axb.plot([r[key]], [y], "o" if r[f"{key}_lo"] is not None else "D", ms=3.0 if r[f"{key}_lo"] is not None
                     else 2.6, color=col, mec="none")
        axb.set_ylim(-0.6, len(rankers) - 0.4)
        axb.set_xlim(0, 0.25)
        axb.set_xticks([0, 0.1, 0.2])
        axb.set_xticklabels(["0", "0.1", "0.2"])
        axb.set_title(label, fontsize=5.5, pad=2.5)
        axb.set_yticks(ys)
        if k == 0:
            axb.set_yticklabels(names, fontsize=5.5)
            axb.tick_params(axis="y", length=0)
        else:
            axb.set_yticklabels([])
            axb.tick_params(axis="y", length=0)
        axb.spines["left"].set_visible(False)
        if key != "map":
            axb.axvline(rv["base_rate"], color=C["vermillion"], lw=0.5, ls=(0, (2, 1.5)))
        if key == "p10":
            axb.text(rv["base_rate"] + 0.008, len(rankers) - 0.45, "Base\nrate", fontsize=5, color=C["vermillion"],
                     ha="left", va="top", linespacing=1.0)
    cv.text(130 + 17.5 * 1.5 - 1.7, 46.2, "Score (topic–cutoff pairs, n = 189)", ha="center", va="top", fontsize=5.5)
    cv.label(101, 3, "b")

    # c — paired comparisons over topics ----------------------------------------------------------------------------------
    ax = cv.ax(38, 60, 46, 22)
    rows = [("Adamic–Adar vs popularity, both cutoffs", 149, 39, 1, 2.4e-16),
            ("Adamic–Adar vs popularity, 1127", 73, 21, None, None),
            ("Adamic–Adar vs popularity, 1368", 76, 18, None, None),
            ("Popularity vs chance, both cutoffs", 116, 73, None, 0.002)]
    ys = np.arange(len(rows))[::-1]
    for y, (lab, better, worse, tie, p) in zip(ys, rows):
        ax.barh(y, better, height=0.6, color=C["blue"] if "Adamic" in lab else C["dark"], lw=0)
        ax.barh(y, -worse, height=0.6, color=C["light"], lw=0)
        ax.text(better + 3, y, f"{better}", va="center", ha="left", fontsize=5.5)
        ax.text(-worse - 3, y, f"{worse}", va="center", ha="right", fontsize=5.5)
        if p is not None:
            ax.text(185, y, pval(p), va="center", ha="left", fontsize=5.5)
    ax.axvline(0, color=C["black"], lw=0.6)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=5.5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(-100, 180)
    ax.set_xticks([-100, -50, 0, 50, 100, 150])
    ax.set_xticklabels(["100", "50", "0", "50", "100", "150"])
    ax.set_xlabel("Topic–cutoff pairs where the first ranker is\nworse (left) or better (right) at precision@10")
    ax.set_ylim(-0.6, len(rows) - 0.4)
    cv.text(38 + 46 * (100 + 185) / 280, 57.4, "Two-sided\nsign test", ha="left", va="center", fontsize=5.5,
            color=C["dark"])
    cv.label(2, 55, "c")

    # d — end to end: the pipeline's own predictions on the past alone -------------------------------------------------
    ax = cv.ax(136, 60, 32, 24)
    e2e = rv["end_to_end_heldout"]
    labels = ["Lost association\nstays absent (D1)", "Association rule\nholds", "Hidden association\ncomes true (D4)",
              "Surviving predictions\nthat are discoveries"]
    ys = np.arange(len(e2e))[::-1]
    for y, r in zip(ys, e2e):
        lo, hi = wilson(r["held_after"], r["n_after"])
        ax.plot([lo, hi], [y, y], color=C["blue"], lw=0.7, solid_capstyle="butt")
        ax.plot([r["held_after"] / r["n_after"]], [y], "o", ms=3.2, color=C["blue"], mec="none", zorder=3)
        txt = f"{r['held_after']}/{r['n_after']}"
        if r["n_before"] != r["n_after"]:
            ax.plot([r["held_before"] / r["n_before"]], [y], "o", ms=3.2, mfc="white", mec=C["dark"], mew=0.6, zorder=4)
            txt = f"{r['held_before']}/{r['n_before']} → {r['held_after']}/{r['n_after']}"
        ax.text(1.03, y, txt, va="center", ha="left", fontsize=5.5)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=5.5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xticklabels(["0", "0.5", "1"])
    ax.set_ylim(-0.6, len(e2e) - 0.4)
    ax.set_xlabel("Proportion held (held-out topics, 1368)")
    ax.plot([], [], "o", ms=3.2, mfc="white", mec=C["dark"], mew=0.6, label="Before the absence checks")
    ax.plot([], [], "o", ms=3.2, color=C["blue"], mec="none", label="After (95% CI)")
    ax.legend(loc="lower left", bbox_to_anchor=(-0.85, 1.0), ncol=2, handletextpad=0.1, columnspacing=0.8)
    cv.label(103, 55, "d")

    rep = cv.save("fig4_research_value", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
