"""Extended Data Fig. 2 | The research-value benchmark re-run on the openly distributed canon corpus (348 works, 8.5 M
characters): the ranking still beats popularity, but with 56 links that come true it cannot be told from chance."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from nature_style import C, Canvas, pval

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"

RANKERS = [("adamic_adar", "Adamic–Adar (D4)"), ("common_neighbors", "Common neighbours"),
           ("resource_allocation", "Resource allocation"), ("popularity", "Popularity"), ("random", "Chance")]


def main() -> dict:
    full = json.loads((SD / "fig4_research_value_full_corpus.json").read_text(encoding="utf-8"))
    rv = json.loads((SD / "extfig_research_value_canon.json").read_text(encoding="utf-8"))["research_value"]["metrics"]
    pooled = rv["link_anticipation"]["pooled"]
    cv = Canvas("double", 62)

    # a — how much the two corpora can test ----------------------------------------------------------------------------
    ax = cv.ax(38, 12, 34, 34)
    items = [("Topic–cutoff pairs\nwith a true link", full["topic_cutoff_pairs_scored"], pooled["topics_with_links_come_true"]),
             ("Candidate links", full["candidates"], pooled["candidates"]),
             ("Links that came true", full["came_true"], pooled["came_true"])]
    ys = np.arange(len(items))[::-1]
    h = 0.36
    for y, (lab, f, o) in zip(ys, items):
        ax.barh(y + h / 2, f, height=h, color=C["dark"], lw=0)
        ax.barh(y - h / 2, o, height=h, color=C["blue"], lw=0)
        ax.text(f * 1.15, y + h / 2, f"{f:,}", va="center", ha="left", fontsize=5)
        ax.text(o * 1.15, y - h / 2, f"{o:,}", va="center", ha="left", fontsize=5)
    ax.set_xscale("log")
    ax.set_xlim(10, 3e5)
    ax.set_xticks([10, 100, 1000, 10000, 100000])
    ax.set_xticklabels(["10", "10$^2$", "10$^3$", "10$^4$", "10$^5$"])
    ax.minorticks_off()
    ax.set_yticks(ys)
    ax.set_yticklabels([i[0] for i in items], fontsize=5.5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Count (log scale)")
    ax.barh([], [], color=C["dark"])
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(facecolor=C["dark"], edgecolor="none", label=f"Full corpus (base rate {full['base_rate']:.1%})"),
                       Patch(facecolor=C["blue"], edgecolor="none",
                             label=f"Open canon corpus (base rate {pooled['base_rate']:.1%})")],
              loc="lower left", bbox_to_anchor=(-0.95, 1.0), ncol=2, fontsize=5.5, handlelength=1.0)
    cv.label(2, 3, "a")

    # b — the rankers on the open corpus ---------------------------------------------------------------------------------
    for k, (key, title) in enumerate((("precision@10", "Precision@10"), ("mean_ap", "Mean average precision"))):
        axb = cv.ax(108 + k * 20, 12, 16, 34)
        ys = np.arange(len(RANKERS))[::-1]
        for y, (rk, lab) in zip(ys, RANKERS):
            d = pooled[rk]
            col = C["blue"] if rk == "adamic_adar" else C["grey"] if rk in ("popularity", "random") else C["dark"]
            ci = d.get(f"{key}_ci")
            if ci:
                axb.plot(ci, [y, y], color=col, lw=0.7, solid_capstyle="butt")
            axb.plot([d[key]], [y], "o" if ci else "D", ms=3.0 if ci else 2.6, color=col, mec="none")
        axb.set_ylim(-0.6, len(RANKERS) - 0.4)
        axb.set_yticks(ys)
        axb.set_yticklabels([lab for _, lab in RANKERS] if k == 0 else [], fontsize=5.5)
        axb.tick_params(axis="y", length=0)
        axb.spines["left"].set_visible(False)
        lim = 0.08 if key == "precision@10" else 0.2
        axb.set_xlim(0, lim)
        axb.set_xticks([0, lim / 2, lim])
        axb.set_xticklabels(["0", f"{lim / 2:g}", f"{lim:g}"])
        axb.set_title(title, fontsize=5.5, pad=2.5)
        if key == "precision@10":
            axb.axvline(pooled["base_rate"], color=C["vermillion"], lw=0.5, ls=(0, (2, 1.5)))
    cv.text(126, 55.5, f"Open canon corpus, both cutoffs pooled (n = {pooled['topics_with_links_come_true']} "
                       "topic–cutoff pairs); 95% CI", ha="center", va="center", fontsize=5)
    cv.label(80, 3, "b")

    # c — paired comparisons ---------------------------------------------------------------------------------------------
    ax = cv.ax(165, 12, 14, 34)
    rows = [("AA vs popularity", pooled["adamic_adar_vs_popularity"]), ("AA vs chance", pooled["adamic_adar_vs_random"]),
            ("Popularity vs chance", pooled["popularity_vs_random"])]
    ys = np.arange(len(rows))[::-1]
    for y, (lab, d) in zip(ys, rows):
        ax.barh(y, d["wins"], height=0.55, color=C["blue"] if lab.startswith("AA") else C["dark"], lw=0)
        ax.barh(y, -d["losses"], height=0.55, color=C["light"], lw=0)
    ax.axvline(0, color=C["black"], lw=0.6)
    ax.set_xlim(-26, 26)
    ax.set_xticks([-20, 0, 20])
    ax.set_xticklabels(["20", "0", "20"])
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{lab}\n{d['wins']} better, {d['losses']} worse\n{pval(d['sign_test_p'])}" for lab, d in rows],
                       fontsize=5, linespacing=1.1)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("Pairs worse | better")
    cv.label(146, 3, "c")

    rep = cv.save("extfig2_canon_replication", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
