"""Fig. 1 | TaoChronos (道乃久): a dated corpus, a research cycle whose boundaries decide, and claims that resolve to a
verbatim witness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

from nature_style import C, Canvas, tint

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"
ACCENT = C["blue"]
FILL = tint(C["blue"], 0.10)
PT = 0.3528  # mm per point


def box(ax, x, y, w, h, title=None, body=None, *, fc="white", ec=None, lw=0.5, title_fs=6, body_fs=5,
        align="center", r=0.9, valign="center"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", facecolor=fc,
                                edgecolor=ec or C["black"], lw=lw))
    tx = x + w / 2 if align == "center" else x + 1.3
    if title and body:
        lines = body.count("\n") + 1
        block = title_fs * PT * 1.35 + lines * body_fs * PT * 1.2
        top = y + (h - block) / 2 if valign == "center" else y + 1.3
        ax.text(tx, top, title, ha=align, va="top", fontsize=title_fs, fontweight="bold")
        ax.text(tx, top + title_fs * PT * 1.35, body, ha=align, va="top", fontsize=body_fs, linespacing=1.2)
    elif title:
        ax.text(tx, y + h / 2, title, ha=align, va="center", fontsize=title_fs, fontweight="bold", linespacing=1.15)
    elif body:
        ax.text(tx, y + h / 2, body, ha=align, va="center", fontsize=body_fs, linespacing=1.2)


def arrow(ax, p0, p1, color=None, lw=0.6):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>,head_length=1.5,head_width=0.8", mutation_scale=1, lw=lw,
                                 color=color or C["black"], shrinkA=0, shrinkB=0))


def main() -> dict:
    wit = pd.read_csv(SD / "fig2_corpus_witnesses.csv")
    web = pd.read_csv(SD / "extfig_web_canon_witnesses.csv")
    cv = Canvas("double", 116)

    # a — from witnesses to a dated corpus ------------------------------------------------------------------------------
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
    arrow(ax, (x - gap + 0.5, by + bh / 2), (x - 0.4, by + bh / 2), color=ACCENT)
    ox, ow = x, 179 - x - 0.5
    box(ax, ox, by, ow, bh, fc=FILL, ec=ACCENT, lw=0.6)
    ax.text(ox + ow / 2, by + 1.3, "Corpus store", ha="center", va="top", fontsize=6, fontweight="bold")
    ax.text(ox + ow / 2, by + 4.2, f"{len(wit)} witnesses · {wit.work.nunique()} works\n123 M characters\n"
                                   "2.05 M passages; periods 475 BCE–1949", ha="center", va="top", fontsize=5,
            linespacing=1.2)
    ax.plot([ox + 3, ox + ow - 3], [by + 11.9, by + 11.9], color=ACCENT, lw=0.4)
    ax.text(ox + ow / 2, by + 12.8, f"canon of 350 works → open\nweb corpus of {web.work.nunique()} works,\n"
                                    f"{web.chars_kept.sum() / 1e6:.1f} M characters, in the browser", ha="center",
            va="top", fontsize=5, linespacing=1.2)
    ax.text(0.5, by + bh + 3.3, "Every passage keeps its book, edition, volume · chapter · page, date range, textual "
                                "layer, transcription source and licence", ha="left", va="center", fontsize=5.5,
            color=C["dark"])
    cv.label(2, 3, "a")

    # b — the research cycle ------------------------------------------------------------------------------------------
    ax = cv.blank(2, 41, 97, 74)
    r1, hh, ww = 1.0, 14.5, 22.0
    xs = [0.5, 25.0, 49.5, 74.0]
    row1 = [("Question", "a scholar's question,\nscoped in time, with\nforbidden\nequivalences"),
            ("Research contract", "criteria fixed before\nwork begins; each\ncriterion names\nits judge"),
            ("Evidence base", "verbatim witnesses,\ndated and layered,\nread through\nscoped views"),
            ("Discovery tracks", "D1 lost knowledge\nD2 concept evolution\nD3 formula evolution\nD4 hidden · D5 conflict")]
    for i, (t, b) in enumerate(row1):
        box(ax, xs[i], r1, ww, hh, t, b)
        if i:
            arrow(ax, (xs[i] - 2.3, r1 + hh / 2), (xs[i] - 0.2, r1 + hh / 2))
    r2 = r1 + hh + 6.0
    row2 = [("Verdict", "accepted · needs\nexpert · inconclusive\n· budget exhausted"),
            ("Expert review", "G7 is set by a\nnamed expert and\nby no one else"),
            ("Gates G0–G8", "source · verbatim ·\ncollation · sense ·\nextraction · sources\n· time · expert · modern"),
            ("Skeptic", "falsification and\nabsence checks over\nthe whole scope;\nnarrow or reject")]
    for i, (t, b) in enumerate(row2):
        verdict = t == "Verdict"
        box(ax, xs[i], r2, ww, hh, t, b, fc=FILL if verdict else "white", ec=ACCENT if verdict else None)
        if i < 3:
            arrow(ax, (xs[i + 1] - 0.2, r2 + hh / 2), (xs[i] + ww + 0.2, r2 + hh / 2))
    arrow(ax, (xs[3] + ww / 2, r1 + hh + 0.2), (xs[3] + ww / 2, r2 - 0.2))
    ax.text(xs[3] + ww / 2 - 1.0, r1 + hh + 3.0, "hypotheses\nwith warrants", ha="right", va="center", fontsize=5,
            color=C["dark"])
    ay = r2 + hh + 4.0
    box(ax, 0.5, ay, 95.5, 30.5, fc="white", ec=C["grey"], lw=0.4)
    ax.text(2.0, ay + 1.4, "Who may decide what", ha="left", va="top", fontsize=6, fontweight="bold")
    rows = [("Agents and models", "16 agents read through scoped views and propose; a model"),
            ("", "judges only what the rules leave uncertain, and in several"),
            ("", "places may lower a verdict but never raise it"),
            ("Validators", "re-run the checks; only a passing re-run closes a hard"),
            ("", "objection"),
            ("Experts", "alone set G7; the contract, not finished tasks, decides"),
            ("", "whether research is accepted"),
            ("Kernel", "event-sourced log; each event carries its principal;"),
            ("", "state replayed and hashed every round")]
    yy = ay + 5.4
    for k, v in rows:
        ax.text(2.0, yy, k, ha="left", va="center", fontsize=5.5, fontweight="bold")
        ax.text(24.0, yy, v, ha="left", va="center", fontsize=5.5)
        yy += 2.75
    cv.label(2, 38, "b")

    # c — one clause, three witnesses ----------------------------------------------------------------------------------
    ax = cv.blank(103, 41, 78, 74)
    deng = "男子消渴小便反多以飲一斗小便一斗腎氣丸主之"
    wuq = "男子消渴小便反多以飲一斗" + "    " + "腎氣丸主之"
    maij = "男子消渴小便反多以飲一斗小便一斗腎氣圎主之"
    cols = len(deng)
    cw, rh = 2.6, 3.5
    gx, gy = 23.0, 8.0
    wits = [("Deng Zhen print, 1340", deng), ("Wu Qian manuscript, 1395", wuq), ("Maijing, Yuan print, 1330", maij)]
    var_cols = [j for j in range(cols) if len({w[1][j] for w in wits}) > 1]
    for j in var_cols:
        ax.add_patch(Rectangle((gx + j * cw, gy - 0.4), cw, rh * 3 + 0.8, facecolor=tint(C["vermillion"], 0.18),
                               edgecolor="none"))
    for i, (name, text) in enumerate(wits):
        yc = gy + i * rh + rh / 2
        ax.text(gx - 1.0, yc, name, ha="right", va="center", fontsize=5)
        for j, ch in enumerate(text):
            if ch == " ":
                ax.plot([gx + j * cw + 0.6, gx + (j + 1) * cw - 0.6], [yc, yc], color=C["dark"], lw=0.5)
            else:
                ax.text(gx + j * cw + cw / 2, yc, ch, ha="center", va="center", fontsize=6.5)
    ax.text(gx + 14 * cw, gy - 1.4, "omission (脱)", ha="center", va="bottom", fontsize=5)
    ax.text(gx + 18 * cw + cw / 2, gy - 1.4, "丸 → 圎", ha="center", va="bottom", fontsize=5)
    ax.text(0.5, 1.4, "Jingui yaolüe ch. 13, a clause on xiaoke 消渴 in three witnesses (punctuation removed)",
            ha="left", va="center", fontsize=5.5)
    gb = gy + 3 * rh + 1.0
    ax.text(gx + cols * cw, gb + 0.3, "圎 (圓) for 丸 avoids the name of Emperor Qinzong (桓, from 1126):\n"
                                     "that witness descends from an edition made after 1126", ha="right", va="top",
            fontsize=5, color=C["dark"], linespacing=1.15)
    chain = [("Claim", "Shenqi wan 肾气丸 indicated for 消渴 with polyuria"),
             ("Quote", "男子消渴，小便反多，以飲一斗，小便一斗，腎氣丸主之"),
             ("Passage", "cm_jingui_dengzhen.00712"),
             ("Locator", "卷中 · 消渴小便利淋病脉證并治第十三 · p. 100"),
             ("Witness", "Deng Zhen print, 1340; Peking University Library"),
             ("Work · layer", "Jingui yaolüe, 200–219 · main text"),
             ("Source · licence", "CMETA, collated page by page · CC BY 4.0"),
             ("Check in chat", "✓ verbatim    ≠ quote differs    × no such passage")]
    cy, step = gb + 7.2, 4.5
    ax.plot([2.2, 2.2], [cy, cy + (len(chain) - 1) * step], color=ACCENT, lw=0.6)
    for k, (key, val) in enumerate(chain):
        yk = cy + k * step
        ax.add_patch(Circle((2.2, yk), 0.7, facecolor=ACCENT, edgecolor="none", zorder=3))
        ax.text(4.2, yk, key, ha="left", va="center", fontsize=5.5, fontweight="bold")
        ax.text(22.5, yk, val, ha="left", va="center", fontsize=5.5)
    cv.label(101, 38, "c")

    rep = cv.save("fig1_overview", HERE / "out")
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
