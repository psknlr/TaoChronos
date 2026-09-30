"""Extended Data Fig. 1 | Where the rules transfer and where they do not: development against held-out or real-corpus
scores, learned punctuation against the rule baseline, and ablations."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from matplotlib.patches import Patch

from nature_style import C, Canvas, tint

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"


def main() -> dict:
    g = pd.read_csv(SD / "extfig_generalization.csv")
    pu = pd.read_csv(SD / "extfig_punctuation.csv")
    ab = pd.read_csv(SD / "extfig_ablations.csv")
    cv = Canvas("double", 92)

    # a — development against held-out ----------------------------------------------------------------------------------
    ax = cv.ax(49, 10, 38, 70)
    ys = np.arange(len(g))[::-1]
    for y, (_, r) in zip(ys, g.iterrows()):
        ax.plot([r.dev_value, r.test_value], [y, y], color=C["grey"], lw=0.8, solid_capstyle="butt", zorder=1)
        ax.plot([r.dev_value], [y], "o", ms=3.4, mfc="white", mec=C["dark"], mew=0.6, zorder=3, clip_on=False)
        ax.plot([r.test_value], [y], "o", ms=3.4, color=C["blue"], mec="none", zorder=4, clip_on=False)
        full = "full corpus" in r.test_source
        ax.text(1.04, y, f"{r.dev_value:.2f} → {r.test_value:.2f}{' †' if full else ''}", va="center", ha="left",
                fontsize=5)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r.capability}\n({r.metric})" for _, r in g.iterrows()], fontsize=5, linespacing=1.05)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0", "0.25", "0.5", "0.75", "1"])
    ax.set_ylim(-0.6, len(g) - 0.4)
    ax.set_xlabel("Score (metric as labelled)")
    ax.plot([], [], "o", ms=3.4, mfc="white", mec=C["dark"], mew=0.6, label="Development or constructed data")
    ax.plot([], [], "o", ms=3.4, color=C["blue"], mec="none", label="Held-out or real-corpus data")
    ax.legend(loc="lower left", bbox_to_anchor=(-1.12, 1.0), ncol=2, handletextpad=0.2, columnspacing=1.0,
              fontsize=5.5)
    cv.label(2, 3, "a")

    # b — learned punctuation against the rules ---------------------------------------------------------------------------
    ax = cv.ax(143, 10, 36, 26)
    ys = np.arange(len(pu))[::-1]
    h = 0.34
    for y, (_, r) in zip(ys, pu.iterrows()):
        ax.barh(y + h / 2, r.model, height=h, color=C["blue"], lw=0)
        ax.barh(y - h / 2, r.rules, height=h, color=C["grey"], lw=0)
        ax.text(r.model + 0.02, y + h / 2, f"{r.model:.2f}", va="center", ha="left", fontsize=5)
        ax.text(r.rules + 0.02, y - h / 2, f"{r.rules:.2f}", va="center", ha="left", fontsize=5)
    ax.set_yticks(ys)
    ax.set_yticklabels([s + (" †" if "full corpus" in src else "") for s, src in zip(pu.setting, pu.source)],
                       fontsize=5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xticklabels(["0", "0.5", "1"])
    ax.set_xlabel("Sentence-boundary F1")
    ax.legend(handles=[Patch(facecolor=C["blue"], edgecolor="none", label="Learned model"),
                       Patch(facecolor=C["grey"], edgecolor="none", label="Rules")],
              loc="lower right", bbox_to_anchor=(1.02, -0.02), fontsize=5, handlelength=1.0)
    cv.label(105, 3, "b")

    # c — ablations -------------------------------------------------------------------------------------------------------
    sub = ab[ab.test == "Earliest attestation"]
    ax = cv.ax(143, 50, 36, 13)
    ys = np.arange(len(sub))[::-1]
    for y, (_, r) in zip(ys, sub.iterrows()):
        k = int(round(r.value * r.n))
        ax.barh(y, r.value, height=0.6, color=C["blue"] if r.condition.startswith("all") else tint(C["blue"], 0.45),
                lw=0)
        ax.text(r.value + 0.02, y, f"{k}/{int(r.n)}", va="center", ha="left", fontsize=5)
    ax.set_yticks(ys)
    ax.set_yticklabels(sub.condition, fontsize=5)
    ax.set_xlim(0, 1.15)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_title("Earliest attestation found", fontsize=5.5, loc="left", pad=1.5)
    sub = ab[ab.test == "Contradiction typing"]
    ax = cv.ax(143, 69.5, 36, 8)
    ys = np.arange(len(sub))[::-1]
    for y, (_, r) in zip(ys, sub.iterrows()):
        k = int(round(r.value * r.n))
        ax.barh(y, r.value, height=0.6, color=C["blue"] if r.condition.startswith("full") else tint(C["blue"], 0.45),
                lw=0)
        ax.text(r.value + 0.02, y, f"{k}/{int(r.n)}", va="center", ha="left", fontsize=5)
    ax.set_yticks(ys)
    ax.set_yticklabels(sub.condition, fontsize=5)
    ax.set_xlim(0, 1.15)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xticklabels(["0", "0.5", "1"])
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_title("Contradictions typed right", fontsize=5.5, loc="left", pad=1.5)
    ax.set_xlabel("Proportion correct")
    tok = ab[ab.test == "Context tokens"].set_index("condition").value
    sk = ab[ab.test == "Hypotheses surviving review"].set_index("condition").value
    cv.text(107, 88.0, f"Context OS view: {int(tok['Context OS view']):,} tokens against {int(tok['naive dump']):,} "
                       f"for a naive dump (−{1 - tok['Context OS view'] / tok['naive dump']:.0%}).\nWithout the Skeptic, "
                       f"{int(sk['without the Skeptic'] - sk['with the Skeptic'])} rejected hypothesis survives review.",
            ha="left", va="center", fontsize=5, linespacing=1.2)
    cv.label(105, 44, "c")

    rep = cv.save("extfig1_generalization", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
