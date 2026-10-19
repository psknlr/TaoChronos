"""Extended Data Fig. 3 | The witnesses behind the texts: image catalogues of eleven collections linked to the corpus,
and the sources and licences of the open web corpus (all but four of its 553 witnesses openly licensed)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from nature_style import C, Canvas

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"

HOLDER_EN = {
    "nijl:kyoto-fujikawa": "Kyoto University Library, Fujikawa collection",
    "sbb:unschuld": "Staatsbibliothek zu Berlin, Unschuld collection",
    "nijl:kyushu-medlib": "Kyushu University Medical Library",
    "nijl:keio-fujikawa": "Keio University, Fujikawa collection",
    "nijl:utokyo-medicine": "University of Tokyo General Library",
    "nijl:knik": "Kenikai Library",
    "waseda:ya09": "Waseda University Library",
    "ndl": "National Diet Library",
    "nijl:tohoku-medlib": "Tohoku University Medical Library",
    "loc:chinese-rare-books": "Library of Congress, Chinese rare books",
    "nijl:utokyo-medlib": "University of Tokyo Medical Library",
}
# open: the transcriptions' own licence allows reuse (JiCheng: CC0 1.0 for its editorial work, https://jicheng.tw/tcm/
# copyright.html); TCM-Ancient-Books, copies of JiCheng texts whose repository declares no licence, keeps the four texts
# that match no JiCheng text
SOURCE_EN = {"jicheng": ("JiCheng editions", True), "kanripo": ("Siku quanshu (Kanripo)", True),
             "cmeta": ("CMETA collated editions", True), "wikisource": ("Wikisource", True),
             "tcm-ancient-books": ("TCM-Ancient-Books", False), "mcgill": ("McGill rare books", True)}


def main() -> dict:
    im = pd.read_csv(SD / "extfig_image_collections.csv")
    web = pd.read_csv(SD / "extfig_web_canon_witnesses.csv")
    cv = Canvas("double", 58)

    # a — image catalogues -------------------------------------------------------------------------------------------------
    ax = cv.ax(52, 8, 50, 40)
    ys = np.arange(len(im))[::-1]
    for y, (_, r) in zip(ys, im.iterrows()):
        ax.barh(y, r.records, height=0.62, color=C["grey"], lw=0, left=0)
        if r.linked_to_corpus:
            ax.barh(y, r.linked_to_corpus, height=0.62, color=C["blue"], lw=0, left=0)
        ax.text(r.records + 60, y, f"{int(r.linked_to_corpus):,} / {int(r.records):,}", va="center", ha="left",
                fontsize=5)
    ax.set_xlim(0, 5000)
    ax.set_xticks([0, 1000, 2000, 3000, 4000, 5000])
    ax.set_xticklabels(["0", "1,000", "2,000", "3,000", "4,000", "5,000"])
    ax.set_yticks(ys)
    ax.set_yticklabels([HOLDER_EN[s] for s in im.source], fontsize=5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Catalogue records (linked / all)")
    tot, linked = int(im.records.sum()), int(im.linked_to_corpus.sum())
    ax.legend(handles=[Patch(facecolor=C["grey"], edgecolor="none", label=f"All records ({tot:,})"),
                       Patch(facecolor=C["blue"], edgecolor="none",
                             label=f"Linked to a work in the corpus ({linked:,})")],
              loc="lower left", bbox_to_anchor=(-0.78, 1.0), ncol=2, fontsize=5.5, handlelength=1.0)
    cv.label(2, 3, "a")

    # b — the open web corpus by source ---------------------------------------------------------------------------------
    g = web.groupby("source").agg(witnesses=("witness", "count"), works=("work", "nunique"),
                                  chars=("chars_kept", "sum")).sort_values("chars", ascending=False)
    ax = cv.ax(145, 8, 34, 26)
    ys = np.arange(len(g))[::-1]
    for y, (src, r) in zip(ys, g.iterrows()):
        name, open_ = SOURCE_EN[src]
        ax.barh(y, r.chars / 1e6, height=0.62, color=C["blue"] if open_ else C["grey"], lw=0)
        ax.text(r.chars / 1e6 + 0.08, y, f"{r.chars / 1e6:.2f} M · {int(r.witnesses)}", va="center", ha="left",
                fontsize=5)
    ax.set_yticks(ys)
    ax.set_yticklabels([SOURCE_EN[s][0] for s in g.index], fontsize=5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    lim = 2 * math.ceil(g.chars.max() / 1e6 / 0.68 / 2)  # room after the longest bar for its label
    ax.set_xlim(0, lim)
    ax.set_xticks(list(range(0, lim + 1, 2)))
    ax.set_xlabel("Characters in the web corpus (millions)")
    ax.legend(handles=[Patch(facecolor=C["blue"], edgecolor="none",
                             label="Open licence (CC0, CC BY, CC BY-SA, public domain)"),
                       Patch(facecolor=C["grey"], edgecolor="none", label="Repository declares no licence")],
              loc="lower left", bbox_to_anchor=(-0.95, 1.0), ncol=1, fontsize=5, handlelength=1.0)
    cv.text(179, 54.5, f"After each bar: characters · witnesses. Total {web.chars_kept.sum() / 1e6:.2f} M characters,\n"
                       f"{len(web)} witnesses of {web.work.nunique()} works", ha="right", va="center", fontsize=5,
            linespacing=1.15)
    cv.label(108, 3, "b")

    rep = cv.save("extfig3_resources", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
