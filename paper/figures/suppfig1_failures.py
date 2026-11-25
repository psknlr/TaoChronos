"""Supplementary Fig. 1 | Where the end-to-end run of Fig. 3 went wrong, and why.

From the run's own state (``e2e_case.py``): the independent source families each hypothesis rests on under three rules
for merging books, and the failure modes found by reading every surviving hypothesis against its evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from matplotlib.lines import Line2D

from nature_style import C, Canvas, wrap_mm

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"
PT = 0.3528
RULES = [("harness", "Harness: same work or author, or any transcription or rephrasing link, closed transitively",
          C["vermillion"]),
         ("transcription_only", "Same work or author, or a transcription link", C["blue"]),
         ("work_author_only", "Same work or author only", C["grey"])]
# failure modes read off the run, each with where it was seen, what it did and what would catch it
MODES = [
    ("Source families over-merged", "H5, H7, H12, H13 (Fig. 3d)",
     "the transitive closure chains 233 of 553 books into one family; with transcription links only, the four "
     "would rest on two or three families, but H5 and H13 rest on copies of one Jingui clause each, so one family is "
     "right for them",
     "judge independence per claim, from the passages that support it, not per book"),
    ("Co-listing read as association", "R1; H8",
     "R1: 口熱 and 上氣 are two items of the kidney channel's list of illnesses, which later books copy; H8: 小腹痛 "
     "belongs to the 尺脈伏 sentence, which gives 大平胃丸, not to 肾气丸",
     "require the relation to be stated (indication, cause), not co-mention, before a lost or restated link counts"),
    ("Concept drift on loose evidence", "H2–H4",
     "the evidence includes passages that do not name 中风 (迎風, 風氣百疾) and one Shanghan lun clause (傷寒中風) in "
     "four witnesses; the drifts' own permutation tests fail (P = 0.66, 0.89, 0.98), yet narrowing to 'exploratory' "
     "closes the objection and all three reach the expert",
     "take drift evidence only from passages naming the term, copies once; make a failed test of the hypothesis's own "
     "statistic a hard objection"),
    ("Case records read as doctrine", "H9–H11",
     "the 内科摘要 sentence and the 外科精要 passage are Xue Ji's records of treatments that failed (不應; 愈甚), not "
     "views; the 外科精要 and 校注妇人良方 witnesses are Xue Ji's editions (1547), whose notes and cases take the dates of "
     "the base texts (1263, 1248), so H9 sets Xue Ji against himself",
     "read case records as records of practice; date editors' notes and cases as a later layer"),
    ("Overlapping hypotheses", "H2–H4; H9–H11",
     "three drifts share the four witnesses of one clause, and three contradictions share one 内科摘要 passage",
     "group hypotheses whose evidence overlaps before they are reviewed"),
    ("Coverage of the open corpus", "sources dossier",
     "the open corpus keeps 8 of 24 chapters of 小儿药证直诀 (1119), none with 地黄丸, so the earliest composition of "
     "六味地黄丸 found is of 1564; the 地黄丸 of 978–992 is another formula of the same name",
     "state the sampled share beside every earliest attestation; rerun on the full store"),
]


def main() -> dict:
    fam = pd.read_csv(SD / "fig3_e2e_families.csv", keep_default_na=False)
    comp = json.loads((SD / "fig3_e2e_family_components.json").read_text(encoding="utf-8"))
    cv = Canvas("double", 122)

    # a — how many families the evidence books form under each rule ----------------------------------------------------
    ax = cv.ax(8, 12, 50, 26)
    labels = [f"Families among the\n{comp['evidence_books']} evidence books", "Largest family\n(books)",
              f"Families in the\ncorpus ({comp['corpus_books']} books)", "Largest family in\nthe corpus (books)"]
    keys = ["families_among_evidence_books", "largest_among_evidence_books", "families_in_corpus", "largest_in_corpus"]
    h = 0.24
    for j, (rule, _, col) in enumerate(RULES):
        vals = [comp["rules"][rule][k] for k in keys]
        ys = [i + (j - 1) * h for i in range(len(keys))]
        ax.barh(ys, vals, height=h * 0.9, color=col, lw=0)
        for y, v in zip(ys, vals):
            ax.text(v + 4, y, str(v), va="center", ha="left", fontsize=5)
    ax.set_yticks(range(len(keys)), labels, fontsize=5)
    ax.set_ylim(len(keys) - 0.5, -0.5)
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 100, 200, 300, 400])
    ax.set_xlabel("Count")
    ax.tick_params(axis="y", length=0, pad=1.5)
    ax.spines["left"].set_visible(False)
    ax.set_position(cv.rect(34, 21, 34, 27))
    cv.label(2, 3, "a")
    handles = [Line2D([], [], ls="", marker="s", ms=3.2, color=col, label=lab) for _, lab, col in RULES]
    cv.fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(4 / 183, 1 - 7.5 / 122), fontsize=5,
                  handletextpad=0.3, labelspacing=0.35, borderaxespad=0, frameon=False, title="Books merged into one "
                  "source family when they share", title_fontsize=5, alignment="left")

    # b — the families each final hypothesis rests on --------------------------------------------------------------------
    rows = fam.copy()
    rows["k"] = rows.label.map(lambda s: (s[0] == "R", int(s[1:])))
    rows = rows.sort_values("k").reset_index(drop=True)
    ax = cv.ax(118, 12, 60, 38)
    for i, r in rows.iterrows():
        for j, (k, _, col) in enumerate(RULES):
            ax.plot([r[k]], [i + (j - 1) * 0.26], "o", ms=2.3, color=col, mec="none", zorder=2 + j)
    ax.axvline(2, color=C["black"], lw=0.5, ls=(0, (2, 1.5)))
    ax.text(2.08, -1.0, "G5 needs 2", ha="left", va="bottom", fontsize=5)
    ax.set_yticks(range(len(rows)), [f"{r.label} ({r.books} book{'s' if r.books > 1 else ''})"
                                     for r in rows.itertuples()], fontsize=5)
    for i in range(len(rows) - 1):
        ax.axhline(i + 0.5, color=C["light"], lw=0.3, zorder=0)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xlim(0.5, 5.5)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.set_xlabel("Independent source families")
    ax.tick_params(axis="y", length=0, pad=1.5)
    ax.spines["left"].set_visible(False)
    passing = [r.label for r in rows.itertuples() if r.transcription_only >= 2 and r.harness < 2]
    ax.text(5.4, len(rows) - 0.6, "reach 2 without the\nrephrasing links: " + ", ".join(passing), ha="right",
            va="bottom", fontsize=5, color=C["blue"], linespacing=1.1)
    cv.label(100, 3, "b")

    # c — the failure modes -----------------------------------------------------------------------------------------------
    ax = cv.blank(2, 60, 179, 61)
    cols = [(0, 30, "Failure"), (31, 26, "Where"), (58, 70, "What it did"), (130, 49, "What would catch it")]
    for x, w, t in cols:
        ax.text(x, 0.5, t, ha="left", va="top", fontsize=5.5, fontweight="bold")
    ax.plot([0, 179], [3.2, 3.2], color="black", lw=0.5)
    y = 4.2
    for mode in MODES:
        heights = []
        for (x, w, _), text in zip(cols, mode):
            lines = wrap_mm(text, w - 2.0, 5.0, "bold" if x == 0 else "normal")
            ax.text(x, y, "\n".join(lines), ha="left", va="top", fontsize=5, linespacing=1.2,
                    fontweight="bold" if x == 0 else "normal")
            heights.append(len(lines) * 5.0 * PT * 1.2)
        y += max(heights) + 1.3
        ax.plot([0, 179], [y - 0.65, y - 0.65], color=C["light"], lw=0.3)
    ax.text(0, y + 0.6, "Also reported, not repaired: the two unsafe readings of the held-out interpretive cases "
            "(Fig. 4c) and the open-corpus benchmark, too small to separate the ranking from chance (its "
            "replication of Fig. 5).", ha="left", va="top", fontsize=5, color=C["dark"])
    cv.label(2, 56, "c")
    return cv.save("suppfig1_failures", HERE / "out")


if __name__ == "__main__":
    rep = main()
    print(json.dumps({k: rep[k] for k in ("width_mm", "height_mm", "warnings")}, ensure_ascii=False, indent=1))
