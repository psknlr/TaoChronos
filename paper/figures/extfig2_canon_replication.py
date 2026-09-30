"""Extended Data Fig. 2 | The research-value benchmark re-run on the openly distributed canon corpus (348 works, 8.5 M
characters): the ranking still beats popularity, but with 56 links that come true it cannot be told from chance.

Panel a shows every topic–cutoff pair behind the pooled numbers (`details` of the research_value run); the paired sign
tests of panel c compare average precision pair by pair, as `evals/research_value.py` does."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from nature_style import C, Canvas, pval

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"

RANKERS = [("adamic_adar", "Adamic–Adar (D4)"), ("common_neighbors", "Common neighbours"),
           ("resource_allocation", "Resource allocation"), ("popularity", "Popularity"), ("random", "Chance")]


TOPIC_EN = {"中风": "zhongfeng", "伤寒": "shanghan", "疮": "sores", "下利": "diarrhoea", "下血": "bleeding below",
            "发热": "fever", "呕吐": "vomiting", "咳": "cough", "喘": "panting", "头痛": "headache",
            "寒热": "chills and fever", "小便不利": "difficult urination", "心烦": "vexation", "无汗": "no sweating",
            "汗出": "sweating", "浊": "turbid urine", "渴": "thirst", "腹满": "abdominal fullness", "谵语": "delirium",
            "淋": "strangury"}


def main() -> dict:
    data = json.loads((SD / "extfig_research_value_canon.json").read_text(encoding="utf-8"))["research_value"]
    rv = data["metrics"]
    pooled = rv["link_anticipation"]["pooled"]
    pairs = [r for r in data["details"] if r["part"] == "link_anticipation" and not r.get("skipped")
             and r.get("came_true")]
    cv = Canvas("double", 80)

    # a — every topic–cutoff pair with a link that came true: average precision of three rankers --------------------------
    pairs.sort(key=lambda r: (r["cutoff"], -(r["adamic_adar"]["ap"] - r["popularity"]["ap"])))
    n = len(pairs)
    rh = 2.0
    y0 = 11.0
    ax = cv.ax(40, y0, 50, n * rh)
    for i, r in enumerate(pairs):
        aa, pop, rnd = r["adamic_adar"]["ap"], r["popularity"]["ap"], r["random"]["ap"]
        ax.plot([pop, aa], [i, i], color=C["blue"] if aa > pop else C["grey"], lw=0.6, zorder=1)
        ax.plot([rnd], [i], "o", ms=2.6, mfc="white", mec=C["dark"], mew=0.5, zorder=2)
        ax.plot([pop], [i], "o", ms=2.6, color=C["grey"], mec="none", zorder=3)
        ax.plot([aa], [i], "o", ms=2.6, color=C["blue"], mec="none", zorder=4)
    ax.set_xscale("log")
    ax.set_xlim(0.002, 0.5)
    ax.set_xticks([0.003, 0.01, 0.03, 0.1, 0.3])
    ax.set_xticklabels(["0.003", "0.01", "0.03", "0.1", "0.3"])
    ax.minorticks_off()
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_yticks(range(n))
    ax.set_yticklabels([f"{r['topic'].split(':')[1]} {TOPIC_EN[r['topic'].split(':')[1]]}" for r in pairs],
                       fontsize=5)
    ax.tick_params(axis="y", length=0, pad=1.2)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Average precision (log scale)")
    k1127 = sum(1 for r in pairs if r["cutoff"] == 1127)
    ax.axhline(k1127 - 0.5, color=C["black"], lw=0.4)
    for lab, lo, hi in (("before 1127", 0, k1127), ("before 1368", k1127, n)):
        ax.text(0.47, (lo + hi - 1) / 2, lab, rotation=-90, ha="left", va="center", fontsize=5, color=C["dark"])
    # the links that came true in each pair
    axn = cv.ax(92, y0, 5, n * rh)
    axn.set_xlim(0, 1)
    axn.set_ylim(n - 0.5, -0.5)
    axn.axis("off")
    for i, r in enumerate(pairs):
        axn.text(0.5, i, str(r["came_true"]), ha="center", va="center", fontsize=5)
    axn.text(0.5, -1.3, "True\nlinks", ha="center", va="bottom", fontsize=5, linespacing=1.05)
    from matplotlib.lines import Line2D

    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=2.6, color=C["blue"], mec="none", label="Adamic–Adar"),
                       Line2D([], [], ls="", marker="o", ms=2.6, color=C["grey"], mec="none", label="Popularity"),
                       Line2D([], [], ls="", marker="o", ms=2.6, mfc="white", mec=C["dark"], mew=0.5,
                              label="Chance (expected)")],
              loc="lower left", bbox_to_anchor=(-0.02, 1.0), ncol=3, fontsize=5, handletextpad=0.1, columnspacing=0.8,
              borderaxespad=0.2)
    cv.label(2, 3, "a")

    # b — the rankers on the open corpus ---------------------------------------------------------------------------------
    for k, (key, title) in enumerate((("precision@10", "Precision@10"), ("mean_ap", "Mean average precision"))):
        axb = cv.ax(128 + k * 27, 11, 22, 26)
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
    cv.text(153.5, 44.5, f"Both cutoffs pooled (n = {pooled['topics_with_links_come_true']} topic–cutoff pairs); "
                         "95% CI", ha="center", va="center", fontsize=5)
    cv.label(104, 3, "b")

    # c — paired comparisons ---------------------------------------------------------------------------------------------
    ax = cv.ax(146, 52, 33, 18)
    rows = [("AA vs popularity", pooled["adamic_adar_vs_popularity"]), ("AA vs chance", pooled["adamic_adar_vs_random"]),
            ("Popularity vs chance", pooled["popularity_vs_random"])]
    ys = np.arange(len(rows))[::-1]
    for y, (lab, d) in zip(ys, rows):
        ax.barh(y, d["wins"], height=0.55, color=C["blue"] if lab.startswith("AA") else C["dark"], lw=0)
        ax.barh(y, -d["losses"], height=0.55, color=C["light"], lw=0)
    ax.axvline(0, color=C["black"], lw=0.6)
    ax.set_xlim(-26, 26)
    ax.set_xticks([-20, -10, 0, 10, 20])
    ax.set_xticklabels(["20", "10", "0", "10", "20"])
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{lab}\n{d['wins']} better, {d['losses']} worse\n{pval(d['sign_test_p'])}" for lab, d in rows],
                       fontsize=5, linespacing=1.1)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("Pairs: worse | better average precision")
    cv.label(104, 49, "c")

    rep = cv.save("extfig2_canon_replication", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
