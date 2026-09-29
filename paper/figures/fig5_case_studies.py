"""Fig. 5 | On the open canon corpus, the deterministic study layer recovers history written into the texts: taboo
renamings, the rise of 温病, the cores of classical formulas and the ancestors the tradition cited."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from matplotlib import cm
from matplotlib import colors as mcolors
from matplotlib.lines import Line2D
from matplotlib.patches import Arc, Patch, Rectangle
from scipy.stats import norm

from nature_style import C, Canvas, pval, tint

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"

HERB = {"地黄": "Dihuang", "山茱萸": "Shanzhuyu", "山药": "Shanyao", "泽泻": "Zexie", "牡丹皮": "Mudanpi",
        "茯苓": "Fuling", "桂": "Gui", "芍药": "Shaoyao", "生姜": "Shengjiang", "大枣": "Dazao", "麻黄": "Mahuang",
        "杏仁": "Xingren", "葛根": "Gegen", "柴胡": "Chaihu", "黄芩": "Huangqin", "人参": "Renshen", "知母": "Zhimu",
        "石膏": "Shigao", "粳米": "Jingmi"}
GROUP_FORMULA = ["Liuwei dihuang wan\n六味地黄丸", "Guizhi tang\n桂枝汤", "Mahuang tang\nfamily 麻黄汤类",
                 "Xiao chaihu tang\n小柴胡汤", "Baihu tang\n白虎汤"]
PHYS = {"扁鹊": "Bian Que", "张机": "Zhang Ji", "陶弘景": "Tao Hongjing", "孙思邈": "Sun Simiao", "许叔微": "Xu Shuwei",
        "李杲": "Li Gao", "朱震亨": "Zhu Zhenheng", "李时珍": "Li Shizhen", "吴谦": "Wu Qian"}
PERIOD_EN = {"先秦两汉": "Qin–Han", "魏晋南北朝": "Wei–Jin", "隋唐五代": "Sui–Tang", "宋金元": "Song–Jin–Yuan",
             "明": "Ming", "清": "Qing", "民国": "Republican"}
MIN_WORKS = 3  # a century is drawn as a solid point, and joined to its neighbours, from this many works


def rename_panel(ax, data: dict, old: str, new: str, events: list[tuple[int, str, str]],
                 labels: list[tuple[float, float, str]]) -> None:
    bins = [b for b in data["bins"] if b["works"] > 0]
    mids = np.array([(b["from"] + b["to"]) / 2 for b in bins])
    works = np.array([b["works"] for b in bins])
    for sw in data["switches"]:
        if sw["from"] == old and sw["to"] == new:
            ax.axvspan(*sw["between"], color=tint(C["grey"], 0.25), lw=0, zorder=0)
    for year, label, ha in events:
        ax.axvline(year, color=C["black"], lw=0.5, ls=(0, (2, 1.5)), zorder=1)
        ax.text(year + (-20 if ha == "right" else 20), 1.1, label, ha=ha, va="bottom", fontsize=5)
    # the 1900s hold only undated front matter, dated conservatively to 1911: drawn open, never joined
    solid = (works >= MIN_WORKS) & (mids < 1900)
    for name, col in ((old, C["blue"]), (new, C["vermillion"])):
        share = np.array([b["shares"].get(name, 0.0) for b in bins])
        for i in range(len(bins) - 1):
            if solid[i] and solid[i + 1] and bins[i + 1]["from"] == bins[i]["to"]:
                ax.plot(mids[i:i + 2], share[i:i + 2], color=col, lw=0.9, zorder=3, solid_capstyle="round")
        ax.scatter(mids[solid], share[solid], s=2.0 + 1.6 * np.sqrt(works[solid]), color=col, lw=0, zorder=4,
                   clip_on=False)
        ax.scatter(mids[~solid], share[~solid], s=6, facecolor="white", edgecolor=col, lw=0.5, zorder=4, clip_on=False)
    for x, y, text in labels:
        ax.text(x, y, text, ha="center", va="center", fontsize=5)
    ax.set_xlim(0, 2000)
    ax.set_ylim(-0.03, 1.06)
    ax.set_yticks([0, 0.5, 1])
    ax.set_yticklabels(["0", "0.5", "1"])
    ax.set_xticks([0, 500, 1000, 1500, 2000])
    ax.set_xlabel("Year (CE; centuries)")


def main() -> dict:
    cv = Canvas("double", 128)

    # a, b — taboo renamings dated in the texts -------------------------------------------------------------------------
    sy = json.loads((SD / "names_shanyao.json").read_text(encoding="utf-8"))
    xs = json.loads((SD / "names_xuanshen.json").read_text(encoding="utf-8"))
    ax = cv.ax(12, 16, 45, 26)
    rename_panel(ax, sy, "薯蓣", "山药", [(762, "Daizong 762", "right"), (1063, "Yingzong 1063", "left")],
                 [(1480, 0.69, "Shanyao 山药"), (1480, 0.29, "Shuyu 薯蓣")])
    ax.set_ylabel("Share of works writing the name")
    cv.label(2, 3, "a")
    ax = cv.ax(70, 16, 45, 26)
    rename_panel(ax, xs, "玄参", "元参", [(1012, "Song Shengzu 1012", "right"), (1662, "Kangxi 1662", "right")],
                 [(1310, 0.70, "Xuanshen 玄参"), (1310, 0.36, "Yuanshen 元参")])
    cv.label(60, 3, "b")
    handles = [Line2D([], [], color=C["blue"], lw=0.9, marker="o", ms=2.5, mec="none", label="Original name"),
               Line2D([], [], color=C["vermillion"], lw=0.9, marker="o", ms=2.5, mec="none",
                      label="Name the taboo imposed"),
               Line2D([], [], ls="none", marker="o", ms=2.6, mfc="white", mec=C["dark"], mew=0.5,
                      label=f"Century with < {MIN_WORKS} works, or front matter only"),
               Patch(facecolor=tint(C["grey"], 0.25), edgecolor="none", label="Switch detected")]
    cv.fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(9 / cv.w, 1 - 6.6 / cv.h), ncol=4,
                  handlelength=1.4, columnspacing=1.2, fontsize=5.5, frameon=False)

    # c — 温病 through the periods ----------------------------------------------------------------------------------------
    tw = json.loads((SD / "term_wenbing.json").read_text(encoding="utf-8"))
    per = tw["periods"]
    ax = cv.ax(137, 16, 42, 26)
    x = np.arange(len(per))
    for i, p in enumerate(per):
        lo, hi = p["ci_per_10k"]
        col = C["vermillion"] if p["period"] == "清" else C["blue"]
        ax.plot([i, i], [lo, hi], color=col, lw=0.7, solid_capstyle="butt", clip_on=False)
        ax.plot([i], [p["per_10k"]], "o", ms=3.0, color=col, mec="none", zorder=3, clip_on=False)
        ax.text(i, 11.2, f"{p['passages']}", ha="center", va="bottom", fontsize=5)
    ks = [(p["passages"], p["total"]) for p in per if p["total"] > 0]
    # the Cochran–Armitage trend over the ordered periods, as study.term computes it; the exact two-sided P from z
    big_n, big_k = sum(n for _, n in ks), sum(k for k, _ in ks)
    pr = big_k / big_n
    t = sum(s * (k - n * pr) for s, (k, n) in enumerate(ks))
    mean = sum(s * n for s, (_, n) in enumerate(ks)) / big_n
    var = pr * (1 - pr) * sum(n * (s - mean) ** 2 for s, (_, n) in enumerate(ks))
    z = t / math.sqrt(var)
    ax.text(0.03, 1.0, f"Trend: z = {z:.2f}, {pval(2 * norm.sf(abs(z)))}", transform=ax.transAxes, ha="left", va="top",
            fontsize=5)
    ax.set_yscale("log")
    ax.set_ylim(10, 500)
    ax.set_yticks([10, 30, 100, 300])
    ax.set_yticklabels(["10", "30", "100", "300"])
    ax.minorticks_off()
    ax.set_xlim(-0.6, len(per) - 0.4)
    ax.set_xticks(x)
    ax.set_xticklabels([PERIOD_EN[p["period"]] for p in per], rotation=90, ha="center", fontsize=5)
    ax.tick_params(axis="x", pad=1.0)
    ax.set_ylabel("Passages with 温病 per 10,000")
    cv.label(125, 3, "c")

    # d — co-occurrence recovers the cores of classical formulas ----------------------------------------------------------
    pr_ = json.loads((SD / "pairs.json").read_text(encoding="utf-8"))
    groups = [g["drugs"] for g in pr_["groups"] if g["size"] >= 3]
    order = [h for g in groups for h in g]
    idx = {h: i for i, h in enumerate(order)}
    n = len(order)
    M = np.full((n, n), np.nan)
    for p in pr_["pairs"]:
        a, b = p["a_name"], p["b_name"]
        if a in idx and b in idx and p["significant"]:
            M[idx[a], idx[b]] = M[idx[b], idx[a]] = p["npmi"]
    cell = 2.5
    X0, Y0 = 33.0, 63.0
    axm = cv.blank(X0, Y0, cell * n, cell * n)
    vmax = 0.9
    cmap = mcolors.LinearSegmentedColormap.from_list("w2b", ["#FFFFFF", tint(C["blue"], 0.35), C["blue"], "#023858"])
    for i in range(n):
        for j in range(n):
            if i == j:
                axm.add_patch(Rectangle((j * cell, i * cell), cell, cell, facecolor=C["light"], edgecolor="none"))
            elif not np.isnan(M[i, j]):
                axm.add_patch(Rectangle((j * cell, i * cell), cell, cell, facecolor=cmap(M[i, j] / vmax),
                                        edgecolor="white", lw=0.25))
    axm.add_patch(Rectangle((0, 0), n * cell, n * cell, facecolor="none", edgecolor=C["grey"], lw=0.4))
    start = 0
    for g, fname in zip(groups, GROUP_FORMULA):
        k = len(g)
        axm.add_patch(Rectangle((start * cell, start * cell), k * cell, k * cell, facecolor="none",
                                edgecolor=C["black"], lw=0.6))
        cv.text(X0 + n * cell + 1.5, Y0 + (start + k / 2) * cell, fname, ha="left", va="center", fontsize=5,
                linespacing=1.1)
        start += k
    for h, i in idx.items():
        cv.text(X0 - 0.8, Y0 + (i + 0.5) * cell, f"{HERB[h]} {h}", ha="right", va="center", fontsize=5)
    cax = cv.ax(X0, Y0 + n * cell + 2.2, 18.0, 1.6)
    cb = cv.fig.colorbar(cm.ScalarMappable(norm=mcolors.Normalize(0, vmax), cmap=cmap), cax=cax,
                         orientation="horizontal")
    cb.outline.set_linewidth(0.4)
    cb.set_ticks([0, 0.3, 0.6, 0.9])
    cb.ax.tick_params(labelsize=5, width=0.4, length=1.5, pad=1.0)
    cv.text(X0 + 19.5, Y0 + n * cell + 3.0, "NPMI of significant pairs\n(white: not significant)", ha="left",
            va="center", fontsize=5, linespacing=1.1)
    cv.label(2, 56, "d")

    # e — who the tradition cited -------------------------------------------------------------------------------------
    ct = json.loads((SD / "citations.json").read_text(encoding="utf-8"))
    edges = [e for e in ct["lineage"] if e["to_dates"][0] <= e["from_dates"][1]]
    dropped = len(ct["lineage"]) - len(edges)
    pos, strength = {}, {}
    for e in edges:
        pos[e["from"]] = sum(e["from_dates"]) / 2
        pos[e["to"]] = sum(e["to_dates"]) / 2
        strength[e["from"]] = strength.get(e["from"], 0) + e["citations"]
        strength[e["to"]] = strength.get(e["to"], 0) + e["citations"]
    total = sum(e["citations"] for e in edges)
    to_zhang = sum(e["citations"] for e in edges if e["to"] == "张机")
    ax = cv.ax(116, 66, 63, 30)
    wmax = max(e["citations"] for e in edges)
    for e in sorted(edges, key=lambda e: (e["to"] == "张机", e["citations"])):
        x1, x2 = pos[e["from"]], pos[e["to"]]
        c, w = (x1 + x2) / 2, abs(x1 - x2)
        if w == 0:
            continue
        lw = 0.25 + 0.75 * math.sqrt(e["citations"] / wmax)
        zhang = e["to"] == "张机"
        ax.add_patch(Arc((c, 0), w, w * 0.9, theta1=0, theta2=180, color=C["blue"] if zhang else C["grey"], lw=lw,
                         alpha=0.9 if zhang else 0.55, zorder=3 if zhang else 2))
    xs_ = np.array(list(pos.values()))
    ss = np.array([strength[k] for k in pos])
    ax.scatter(xs_, np.zeros_like(xs_), s=1.2 + 9 * np.sqrt(ss / ss.max()), color=C["black"], lw=0, zorder=4,
               clip_on=False)
    ax.set_xlim(-500, 1900)
    ax.set_ylim(0, 1150)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.set_xticks([])
    ax.axhline(0, color=C["black"], lw=0.6, zorder=1)
    for k, name in PHYS.items():
        ax.text(pos[k], -45, f"{name} {k}", rotation=90, ha="center", va="top", fontsize=5)
    # a time axis under the names
    axt = cv.ax(116, 115.5, 63, 0.01)
    axt.set_xlim(-500, 1900)
    axt.set_yticks([])
    axt.spines["left"].set_visible(False)
    axt.set_xticks([-400, 0, 400, 800, 1200, 1600])
    axt.set_xticklabels(["400 BCE", "1 CE", "400", "800", "1200", "1600"], fontsize=5)
    axt.set_xlabel("Physician's dates (midpoint, year)", fontsize=5.5)
    ax.text(-480, 1150, f"{len(edges)} links, {len(pos)} physicians, {total:,} citations;\n"
                        f"into Zhang Ji (blue): {to_zhang} ({to_zhang / total:.0%})", ha="left", va="top", fontsize=5)
    cv.label(107, 56, "e")

    rep = cv.save("fig5_case_studies", HERE / "out")
    rep["dropped_anachronistic_edges"] = dropped
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt",
                             "dropped_anachronistic_edges")})
    print("\n".join(r["warnings"]) or "no warnings")
