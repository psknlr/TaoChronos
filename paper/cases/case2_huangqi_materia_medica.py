"""Case 2 | Chinese herbal medicine: Huangqi through the materia medica — a stable core, a growing repertoire.

The figure draws the answer 道乃久 (Tao-R1) gave on 2026-11-23 to the question in panel a (nature and flavour,
tropism, actions, indications, combinations and contraindications of Huangqi across the periods).  Every value,
quotation and passage identifier comes from ``source_data/case2_*`` (``make_case_data.py``) and is checked against the
answer here; the English renderings and the romanised names are the figure's.
"""

from __future__ import annotations

import csv
import re

import numpy as np
from case_style import (
    BLUE,
    DARK,
    GREY,
    LIGHT,
    OUT,
    PALE,
    PERIOD_EN,
    SD,
    VERM,
    Canvas,
    answer,
    arrow,
    line,
    load,
    para,
    query_strip,
    rbox,
    rect,
    rich,
    tint,
    title,
)

D = load("case2_huangqi.json")
T = D["tables"]
REPORT = answer(2)
B, G, N = {"weight": "bold", "color": BLUE}, {"color": GREY}, {}
IT = {"style": "italic", "color": GREY}


def table(k: int) -> list[dict]:
    t = T[str(k)]
    return [dict(zip(t["columns"], r)) for r in t["rows"]]


def said(*phrases: str) -> None:
    """Every phrase is in the answer as written (its tables included)."""
    for p in phrases:
        assert p in REPORT, p


# --- b: what the answer reports, by period -----------------------------------------------------------------------------
COLS = [("Han to Tang", "before 960", 31.0), ("Song–Jin–Yuan", "960–1368", 37.0), ("Ming", "1368–1644", 41.0),
        ("Qing", "1644–1911", 45.0)]
STAGES = [(0, 0, "a drug for sores and ‘deficiency’"), (1, 2, "the materia medica re-organised around qi"),
          (3, 3, "raw against honey-fried becomes the rule")]
# a lane: label, sub-label, first column of its band (None: no band), cells {column: [lines of (text, style) parts]}
LANES = [
    ("Flavour, nature", ["13 works: all sweet,", "12 warm"], 0, {
        0: [[("sweet 甘, slightly warm 微温", N)], [("Shennong bencao jing", IT), (" 神农本草经", G)],
            [("non-toxic 无毒", N), (" · by c. 500", G)]],
        1: [[("‘warm’ 温", N)], [("Tangye bencao", IT), (" 汤液本草, 1289–1308", G)]]}),
    ("Direction", [], 2, {
        2: [[("rises and falls 可升可降, yang in yin 阴中阳也", N)], [("Bencao mengquan", IT), (" 本草蒙筌", G)]]}),
    ("Channel tropism", ["stated in 4 of 13", "works; no consensus"], None, {
        1: [[("exterior, middle and interior:", N)], [("a drug of the three burners 三焦之药", N)],
            [("Wang Haogu*", G)]],
        2: [[("hand Shaoyang, foot Taiyin", N), (" · ", G), ("Bencao mengquan", IT)],
            [("hand Yangming and Taiyin", N), (" · Miao Xiyong, 1625", G)]],
        3: [[("gallbladder and sanjiao; lung and spleen", N)], [("Shennong bencao jing bing zhu", IT)],
            [("sanjiao", N), (" · ", G), ("Benjing shuzheng", IT), (" 本经疏证, 1840", G)],
            [("stomach to lung; foot Taiyang, hand Taiyin", N)],
            [("Zhou Yan, ", G), ("Bencao sibian lu", IT), (", 1904", G)]]}),
    ("Sores", ["expel pus, grow flesh"], 0, {
        0: [[("「主癰疽、久敗創、排膿止痛」", N)], [("Shennong bencao jing", IT)]],
        2: [[("sweet resolves toxin; yang moves it out", N)], [("Miao Xiyong, 1625", G)]],
        3: [[("‘sage drug for sores’ 痈疮圣药", N)], [("Wang Ang, ", G), ("Bencao beiyao", IT), (" 本草备要, 1694", G)]]}),
    ("Wind–damp", ["and blood bi"], 0, {
        0: [[("Fangji huangqi tang 防己黄芪汤", B), ("   ", N), ("Wutou tang 乌头汤", B)],
            [("Huangqi guizhi wuwu tang 黄芪桂枝五物汤", B), (" · ", G), ("Jingui yaolüe", IT), (" 金匮要略, 200–219", G)]]}),
    ("Exterior", ["secure it, stop sweating"], 1, {
        1: [[("Muli san 牡蛎散", B), (" · ", G), ("Jufang", IT), (" 局方, 1107–1110", G)],
            [("Danggui liuhuang tang 当归六黄汤", B), (" · 1264", G)]],
        2: [[("Yupingfeng san 玉屏风散", B), (" · 1443", G)], [("restrained by Fangfeng, yet stronger for it", N)],
            [("相畏而相使 · Li Gao*", G)]],
        3: [[("raw: secures the exterior 生用固表", N)], [("Wang Ang, 1694", G)]]}),
    ("Deficiency", ["tonify the middle,", "raise yang"], 0, {
        0: [[("‘tonifies deficiency’ 补虚", N)], [("Shennong bencao jing", IT)]],
        1: [[("Buzhong yiqi tang 补中益气汤", B), (" · 1247", G)], [("‘warmth removes great heat’ 温能除大热", N)],
            [("Li Gao, ", G), ("Piwei lun", IT), (" 脾胃论, 1249", G)]],
        2: [[("‘chief of the tonics’ 补药之长", N)], [("Li Shizhen, ", G), ("Bencao gangmu", IT), (", 1552–1578", G)]],
        3: [[("honey-fried: tonifies the middle 炙用补中", N)], [("‘deficiency’: of spleen and stomach", N)],
            [("Wang Ang, 1694; Xu Dachun, 1736", G)]]}),
    ("Stasis", ["with qi deficiency"], 3, {
        3: [[("Buyang huanwu tang 补阳还五汤", B), (" · f", G)],
            [("Wang Qingren, ", G), ("Yilin gaicuo", IT), (" 医林改错, 1848", G)]]}),
]
GROUPS = [("Properties", 0, 3), ("Roles and formulas", 3, 8)]

# the ten partners of the answer's own table of combinations, with Gancao (the most frequent) and Fangfeng (the pair of
# Yupingfeng san)
HERB = {"龙眼肉": "Longyanrou", "麻黄根": "Mahuanggen", "人参": "Renshen", "当归": "Danggui", "五味子": "Wuweizi",
        "地黄": "Dihuang", "麦冬": "Maidong", "芍药": "Shaoyao", "甘草": "Gancao", "川芎": "Chuanxiong", "升麻": "Shengma",
        "防风": "Fangfeng"}
BYHW = [("黄芪类", "Huangqi 黄芪, raw", "4 liang 四两"), ("当归类", "Danggui wei 归尾", "2 qian"),
        ("芍药类", "Chishao 赤芍", "1.5 qian"), ("川芎类", "Chuanxiong 川芎", "1 qian"), ("地龙", "Dilong 地龙", "1 qian"),
        ("桃仁", "Taoren 桃仁", "1 qian"), ("红花", "Honghua 红花", "1 qian")]
CAUTIONS = [
    ("secures the exterior 實表", "no", "a pathogen still in the exterior", "有表邪者勿用"),
    ("assists qi 助氣", "no", "qi already in excess", "氣實者勿用"),
    ("fills and blocks within 内塞", "no", "chest oppressed, food stagnant", "胸膈氣閉悶腸胃有積滯者勿用"),
    ("tonifies yang 補陽", "avoid", "yang exuberant, yin deficient", "陽盛隂虚者忌之"),
    (None, "avoid", "heat above, deficiency-cold below", "上焦熱甚下焦虚寒者忌之"),
    (None, "no", "much anger, liver qi unsettled", "病人多怒肝氣不和者勿服"),
    (None, "prohibited", "pox with heat in the blood", "痘瘡血分熱盛者禁用"),
]


def cochran_armitage(rows: list[tuple[int, int]]) -> float:
    """z of the Cochran–Armitage test for a trend in k/n over ordered groups (the test the study layer runs)."""
    big_n, big_k = sum(n for _, n in rows), sum(k for k, _ in rows)
    p = big_k / big_n
    t = sum(s * (k - n * p) for s, (k, n) in enumerate(rows))
    mean = sum(s * n for s, (_, n) in enumerate(rows)) / big_n
    return t / (p * (1 - p) * sum(n * (s - mean) ** 2 for s, (_, n) in enumerate(rows))) ** 0.5


def cell(ax, x, y, w, lines_, fs=5.0, lead=2.18):
    for k, parts in enumerate(lines_):
        xe = rich(ax, x, y + k * lead, parts, fs, va="top")
        assert xe - x <= w + 0.05, f"{xe - x - w:.1f} mm too wide: {''.join(p[0] for p in parts)}"


def main() -> dict:
    cv = Canvas("double", 170)
    ax = cv.blank(0, 0, cv.w, cv.h)

    # a — the question ---------------------------------------------------------------------------------------------------
    cv.label(2, 1.2, "a")
    query_strip(cv, ax, D, case="Case 2", domain="Chinese herbal medicine",
                topic="Materia medica analysis and applications of Huangqi 黄芪", y=5.0, h=13.8)

    # b — the genealogy ----------------------------------------------------------------------------------------------------
    said("味甘微溫。主癰疽、久敗創、排膿止痛", "可升可降，陰中陽也", "無毒", "三焦之藥", "入手陽明太隂經", "入膽與三焦", "入肺與脾",
         "由胃達肺", "足太陽手太陰", "故能解毒陽能達表故能運毒走表", "癰瘡聖藥", "生用固表", "炙用補中", "補脾胃之虛",
         "為補藥之長", "相畏而相使", "温能除大熱", "補虛", "jc_c000b.00065", "jc_c012.00116", "bencao_jingshu.007.01404",
         "jc_c000c.00003", "jc_c045.00061", "jc_c018a.00028", "jc_c044.00075", "bencao_gangmu_skqs.036.01516",
         "jc_f009.00036", "piweilun.002.00081", "jc_f022.01352", "jc_d010a.00637", "renzhai_zhizhi.009.01264",
         "jc_b100.00059", "jc_b100.00143", "jc_b100.00134", "jc_o001a.00109", "(1247)", "(1443)", "(1264)", "(1848)")
    first = {(r["项目"], r["所言"]): (r["首见"], r["成书年代"]) for r in table(5)}
    assert first[("性味", "甘")] == ("《神农本草经》", "25–220") and first[("药性", "温")] == ("《汤液本草》", "1289–1308")
    assert first[("毒性", "无毒")][1] == "500" and first[("升降浮沉", "可升可降")][0] == "《本草蒙筌》"
    assert first[("归经", "手少阳")][0] == first[("归经", "足太阴")][0] == "《本草蒙筌》"
    assert first[("归经", "三焦")] == ("《本经疏证》", "1840") and first[("归经", "胆")][0] == "《神农本草经并注》"
    works = sum(int(r["本草著作（部）"]) for r in table(4))
    warm = sum(int(r["言其性为（部） · 温"]) for r in table(4))
    sweet = sum(int(re.search(r"甘 (\d+)", r["味（部）"]).group(1)) for r in table(4))
    assert (works, warm, sweet) == (13, 12, 13) and D["from_report"]["tropism_works_stating"] == 4

    yb = 20.6
    cv.label(2, yb, "b")
    title(ax, 6.6, yb + 0.35, "What the materia medica say of Huangqi, period by period: a stable core, a growing "
          "repertoire")
    ax.text(cv.w - 2.0, yb + 0.75, "* as quoted in the Bencao gangmu 本草纲目, 1552–1578", ha="right", va="top", fontsize=5,
            color=DARK)
    x_grp, x_lab, x0 = 2.0, 6.4, 27.0
    xs = [x0]
    for _, _, w in COLS:
        xs.append(xs[-1] + w)
    y_head = yb + 4.3
    for k, (name, dates, w) in enumerate(COLS):
        rich(ax, xs[k] + 1.0, y_head, [(name, {"weight": "bold"}), (f"  {dates}", G)], 5.5, va="top")
    for a, b, s in STAGES:
        ax.text(xs[a] + 1.0, y_head + 2.55, s, ha="left", va="top", fontsize=5, fontstyle="italic", color=DARK)
        line(ax, [xs[a] + 0.6, xs[b + 1] - 0.6], [y_head + 5.0] * 2, color=GREY, lw=0.4)
    y = y_head + 5.6
    lead, pad = 2.18, 0.8
    tops = []
    for label, sub, start, cells in LANES:
        n = max(max(len(v) for v in cells.values()), 1 + len(sub))
        h = n * lead + 2 * pad
        tops.append((y, h))
        if start is not None:
            rbox(ax, xs[start] + 0.3, y + 0.25, xs[-1] - xs[start] - 0.3, h - 0.5, fc=tint(BLUE, 0.11), r=0.6, z=0.4)
        else:
            for c in cells:
                rbox(ax, xs[c] + 0.3, y + 0.25, COLS[c][2] - 0.6, h - 0.5, fc=PALE, r=0.6, z=0.4)
        ax.text(x_lab, y + pad, label, ha="left", va="top", fontsize=5.5, fontweight="bold")
        for k, s in enumerate(sub):
            ax.text(x_lab, y + pad + (k + 1) * lead + 0.15, s, ha="left", va="top", fontsize=5, color=DARK)
        for c, lines_ in cells.items():
            span = COLS[c][2] - 2.0
            if label == "Wind–damp":
                span += COLS[1][2]
            cell(ax, xs[c] + 1.2, y + pad, span, lines_)
        y += h
    y_end = y
    for name, a, b in GROUPS:
        ya, yb2 = tops[a][0], tops[b - 1][0] + tops[b - 1][1]
        rect(ax, x_grp, ya + 0.25, 3.3, yb2 - ya - 0.5, fc=DARK if a == 0 else BLUE, z=0.4)
        ax.text(x_grp + 1.65, (ya + yb2) / 2, name, ha="center", va="center", rotation=90, fontsize=5.5,
                fontweight="bold", color="white", zorder=5)
    for k in range(1, len(COLS)):
        line(ax, [xs[k]] * 2, [y_head + 5.4, y_end], color="white", lw=0.8, z=0.5)

    # c, d — what the corpus counts, by period ---------------------------------------------------------------------------
    yc = y_end + 1.9
    cv.label(2, yc, "c")
    title(ax, 6.6, yc + 0.35, "Compositions that contain it")
    share = [r for r in table(6) if r["时期"] in PERIOD_EN]
    rows_y0, rp = yc + 7.6, 3.75
    y_ax = rows_y0 + len(share) * rp
    xa, wa = 24.0, 19.0
    xmax = 7.0
    sx = lambda v: xa + v / xmax * wa  # noqa: E731
    k_all = sum(int(r["含黄芪，n (%)"].split()[0]) for r in share)
    n_all = sum(int(r["写出组成（首）"]) for r in table(6))
    assert (k_all, n_all) == (2693, 69744) == (D["from_report"]["with_huangqi"], D["from_report"]["compositions"])
    ax.text(xa + wa + 1.6, yc + 4.7, "with Huangqi / all", ha="left", va="top", fontsize=5, color=DARK)
    line(ax, [sx(100 * k_all / n_all)] * 2, [rows_y0 - 0.4, y_ax], color=GREY, lw=0.4, ls=(0, (2, 1.5)))
    ax.text(sx(100 * k_all / n_all), rows_y0 - 0.8, f"all periods {100 * k_all / n_all:.2f}%", ha="center", va="bottom",
            fontsize=5, color=DARK)
    for i, r in enumerate(share):
        yy = rows_y0 + (i + 0.5) * rp
        k_, pct = re.match(r"(\d+) \(([\d.]+)\)", r["含黄芪，n (%)"]).groups()
        lo, hi = (float(v) for v in r["95% CI（%）"].split("–"))
        ax.text(xa - 1.4, yy, PERIOD_EN[r["时期"]], ha="right", va="center_baseline", fontsize=5.5)
        line(ax, [sx(lo), sx(hi)], [yy, yy], color=BLUE, lw=0.7, z=3)
        ax.plot([sx(float(pct))], [yy], "o", ms=2.6, color=BLUE, mec="none", zorder=4)
        ax.text(xa + wa + 1.6, yy, f"{int(k_):,} / {int(r['写出组成（首）']):,}", ha="left", va="center_baseline",
                fontsize=5)
    line(ax, [xa, xa + wa], [y_ax, y_ax], color="black", lw=0.6)
    line(ax, [xa, xa], [rows_y0 - 0.4, y_ax], color="black", lw=0.6)
    for v in (0, 2, 4, 6):
        line(ax, [sx(v)] * 2, [y_ax, y_ax + 0.9], color="black", lw=0.6)
        ax.text(sx(v), y_ax + 1.3, f"{v}", ha="center", va="top", fontsize=5)
    ax.text(xa + wa / 2, y_ax + 3.4, "Share (%)", ha="center", va="top", fontsize=5.5)
    st = D["from_report"]["share_trend"]
    assert abs(st["z"] - D["from_charts"]["statistics"]["share_trend_z"]) < 0.01 and st["p"] == 0.000031
    assert abs(cochran_armitage([(int(r["含黄芪，n (%)"].split()[0]), int(r["写出组成（首）"])) for r in share]) - st["z"]) < 0.001
    ax.text(xa + wa + 1.6, y_ax + 1.3, "Trend z = 4.16,", ha="left", va="top", fontsize=5)
    ax.text(xa + wa + 1.6, y_ax + 3.4, "$\\mathit{P}$ = 3.1 × 10$^{-5}$", ha="left", va="top", fontsize=5)

    # d — written doses
    xd = 62.0
    cv.label(xd, yc, "d")
    title(ax, xd + 4.6, yc + 0.35, "Dose written for it in decoctions")
    doses = list(csv.DictReader(open(SD / "case2_decoction_doses.csv", encoding="utf-8")))
    assert len(doses) == 991 == D["from_report"]["dose_spearman"]["n"]
    xg, wg = xd + 1.0, 33.0
    lo_, hi_ = np.log10(0.1), np.log10(400)
    gx = lambda g: xg + (np.log10(g) - lo_) / (hi_ - lo_) * wg  # noqa: E731
    rng = np.random.RandomState(7)
    t7 = {r["时期"]: r for r in table(7)}
    xt = xg + wg + 1.6
    for xx, s, ha in ((xt + 3.6, "n", "right"), (xt + 12.4, "median", "right"), (xt + 19.6, "most often", "center")):
        ax.text(xx, yc + 4.7, s, ha=ha, va="top", fontsize=5, color=DARK)
    for i, r in enumerate(share):
        yy = rows_y0 + (i + 0.5) * rp
        per = r["时期"]
        if per not in t7:
            ax.text(xg + 0.8, yy, "no composition contains it", ha="left", va="center_baseline", fontsize=5,
                    color=GREY)
            continue
        g = np.array([float(d["grams"]) for d in doses if d["period"] == per])
        assert len(g) == int(t7[per]["n"])
        ax.scatter(gx(np.clip(g, 0.1, None)), yy + rng.uniform(-1.05, 1.05, len(g)), s=1.7, color=BLUE, alpha=0.3,
                   lw=0, zorder=2)
        med, q1, q3 = (float(v) for v in re.match(r"([\d.]+) \(([\d.]+), ([\d.]+)\)",
                                                   t7[per]["折合克数（g） · M (P25, P75)"]).groups())
        rect(ax, gx(q1), yy - 1.2, gx(q3) - gx(q1), 2.4, fc="none", ec="black", lw=0.5, z=3)
        line(ax, [gx(med)] * 2, [yy - 1.2, yy + 1.2], color="black", lw=1.0, z=4)
        ax.text(xt + 3.6, yy, t7[per]["n"], ha="right", va="center_baseline", fontsize=5)
        ax.text(xt + 12.4, yy, f"{med:.1f} g", ha="right", va="center_baseline", fontsize=5)
        ax.text(xt + 19.6, yy, t7[per]["常见写法"].split("、")[0], ha="center", va="center_baseline", fontsize=5)
    line(ax, [xg, xg + wg], [y_ax, y_ax], color="black", lw=0.6)
    for v in (0.1, 1, 10, 100):
        line(ax, [gx(v)] * 2, [y_ax, y_ax + 0.9], color="black", lw=0.6)
        ax.text(gx(v), y_ax + 1.3, f"{v:g}", ha="center", va="top", fontsize=5)
    ax.text(xg + wg / 2, y_ax + 3.4, "Converted dose (g, log scale)", ha="center", va="top", fontsize=5.5)
    sp = D["from_report"]["dose_spearman"]
    assert abs(sp["rho"] - D["from_charts"]["statistics"]["dose_spearman_rho_chart"]) < 0.006 and sp["p"] == 8.0e-28
    ax.text(xt, y_ax + 1.3, "Spearman ρ = −0.34,", ha="left", va="top", fontsize=5)
    ax.text(xt, y_ax + 3.4, "$\\mathit{P}$ = 8.0 × 10$^{-28}$", ha="left", va="top", fontsize=5)

    # e — partners --------------------------------------------------------------------------------------------------------
    xe = 124.5
    cv.label(xe, yc, "e")
    title(ax, xe + 4.6, yc + 0.35, "Drugs written with it")
    assoc = {r["药物"]: r for r in table(22)}
    frequent = {r["药物"] for r in table(9)}
    rows_ = sorted(HERB, key=lambda h: -float(assoc[h]["OR (95% CI)"].split()[0]))
    xo, wo = xe + 29.0, 26.5
    lo_o, hi_o = np.log10(1.0), np.log10(60.0)
    ox = lambda v: xo + (np.log10(v) - lo_o) / (hi_o - lo_o) * wo  # noqa: E731
    rpe = (y_ax - rows_y0 + 2.2) / len(rows_)
    ye0 = rows_y0 - 2.2
    ax.text(xe + 27.2, yc + 4.7 - 2.2, "n", ha="right", va="top", fontsize=5, color=DARK)
    ax.text(xo + wo / 2, yc + 4.7 - 2.2, "Odds ratio (95% CI)", ha="center", va="top", fontsize=5, color=DARK)
    for i, h in enumerate(rows_):
        yy = ye0 + (i + 0.5) * rpe
        r = assoc[h]
        m = re.match(r"([\d.]+) \(([\d.]+)–([\d.]+)\)", r["OR (95% CI)"])
        o, lo, hi = (float(v) for v in m.groups())
        col = BLUE if h in frequent else DARK
        rich(ax, xe, yy, [(HERB[h], {}), (f" {h}", {})], 5, va="center_baseline")
        ax.text(xe + 27.2, yy, f"{int(r['同方（首）']):,}", ha="right", va="center_baseline", fontsize=5)
        line(ax, [ox(lo), ox(min(hi, 60))], [yy, yy], color=col, lw=0.7, z=3)
        ax.plot([ox(o)], [yy], "o" if h in frequent else "D", ms=2.4 if h in frequent else 2.0, color=col, mec="none",
                zorder=4)
    line(ax, [xo, xo + wo], [y_ax, y_ax], color="black", lw=0.6)
    line(ax, [ox(1)] * 2, [ye0, y_ax], color=GREY, lw=0.4, ls=(0, (2, 1.5)))
    for v in (1, 3, 10, 30):
        line(ax, [ox(v)] * 2, [y_ax, y_ax + 0.9], color="black", lw=0.6)
        ax.text(ox(v), y_ax + 1.3, f"{v}", ha="center", va="top", fontsize=5)
    ax.plot([xe + 0.8], [y_ax + 2.25], "o", ms=2.4, color=BLUE, mec="none")
    ax.text(xe + 2.0, y_ax + 1.3, "among the 20 most frequent", ha="left", va="top", fontsize=5)
    ax.plot([xe + 0.8], [y_ax + 4.35], "D", ms=2.0, color=DARK, mec="none")
    ax.text(xe + 2.0, y_ax + 3.4, "rarer, more specific", ha="left", va="top", fontsize=5)

    # f — sovereign by weight ---------------------------------------------------------------------------------------------
    yf = y_ax + 6.6
    cv.label(2, yf, "f")
    title(ax, 6.6, yf + 0.35, "Sovereign by weight: Buyang huanwu tang")
    said("黃耆四兩生 歸尾二錢 赤芍一錢半地龍一錢去土  川芎一錢 桃仁一錢 紅花一錢", "50.7%")
    ratio = {r["药物"]: r["医林改错（1848）"] for r in table(21)}
    xb, wb = 27.5, 14.0
    yy = yf + 5.6
    for key, lab, dose in BYHW:
        v = float(re.search(r"（([\d.]+)）", ratio[key]).group(1))
        ax.text(xb - 1.2, yy, lab, ha="right", va="center_baseline", fontsize=5,
                fontweight="bold" if key == "黄芪类" else "normal")
        rect(ax, xb, yy - 0.85, max(v * wb, 0.3), 1.7, fc=BLUE if key == "黄芪类" else GREY)
        ax.text(xb + max(v * wb, 0.3) + 0.8, yy, dose, ha="left", va="center_baseline", fontsize=5)
        yy += 2.45
    para(ax, 2.0, yy - 0.3, "Yilin gaicuo 医林改错, 1848: 4 liang of Huangqi against 1–2 qian of each other drug "
         "(1 liang = 10 qian). It carries the largest dose in 50.7% of the 2,693 compositions that contain it.", 52.5,
         5, lh=1.13, max_lines=4)

    # g — contraindications -----------------------------------------------------------------------------------------------
    xg0 = 58.5
    cv.label(xg0, yf, "g")
    title(ax, xg0 + 4.6, yf + 0.35, "When not to use it", color=VERM)
    said("黄耆功能實表有表邪者勿用能助氣氣實者勿用能内塞補不足胸膈氣閉悶腸胃有積滯者勿用能補陽陽盛隂虚者忌之"
         "上焦熱甚下焦虚寒者忌之病人多怒肝氣不和者勿服痘瘡血分熱盛者禁用", "bencao_jingshu.007.01406",
         "表旺者不宜用，陰虛者宜少用", "肥白而多汗者為宜若面黒形實而瘦者服之令人胸滿", "肺虛忌用",
         "茯苓為使，惡龜甲、白蘚皮，畏防風", "no pair in which Huangqi appears")
    assert len(T["23"]["rows"]) == 23 and not any("黄芪" in r[0] or "黄耆" in r[0] for r in T["23"]["rows"])
    rich(ax, xg0, yf + 4.6, [("Miao Xiyong, 1625", {"weight": "bold"}), (": each caution follows from an action",
                                                                         {}),
                             ("  ·  bencao_jingshu.007.01406", G)], 5, va="top")
    yy = yf + 8.3
    rpg = 3.5
    xc, wc, xt2 = xg0, 29.0, xg0 + 33.6
    for act, grade, en, han in CAUTIONS:
        if act:
            rbox(ax, xc, yy - 1.45, wc, 2.9, fc=tint(BLUE, 0.13), r=0.6)
            ax.text(xc + 1.0, yy, act, ha="left", va="center_baseline", fontsize=5)
            arrow(ax, xc + wc + 0.6, yy, xt2 - 1.0, yy, color=GREY, lw=0.5, head=2.4)
        xe2 = rich(ax, xt2, yy, [(grade + ": ", {"weight": "bold", "color": VERM}), (en, {}), (f"  {han}", G)], 5,
                   va="center_baseline")
        assert xe2 < 146.2, (en, xe2)
        yy += rpg
    ax.text(xc + 1.0, yf + 8.3 + 5 * rpg, "three more, with no action named", ha="left", va="center_baseline",
            fontsize=5, fontstyle="italic", color=GREY)
    # later voices
    xv, wv = 148.0, cv.w - 2.0 - 148.0
    line(ax, [xv - 1.6] * 2, [yf + 4.6, cv.h - 1.2], color=LIGHT, lw=0.4)
    yv = yf + 4.6
    for head, body in (("Zhu Danxi*", "suits the fat, pale and sweating; chest fullness in the dark, solid and thin."),
                       ("Wang Ang, 1694", "not if the exterior is exuberant; little if yin is deficient. Fuling its "
                                          "envoy; averse to Guijia and Baixianpi; ‘fears’ Fangfeng."),
                       ("Peng Ziyi, 1939", "not in lung deficiency: Huangqi rises, lung qi descends."),
                       ("Incompatibility lists", "none of the 23 pairs on record names Huangqi: a negative finding, "
                                                 "not a clearance.")):
        ax.text(xv, yv, head, ha="left", va="top", fontsize=5, fontweight="bold")
        yv = para(ax, xv, yv + 2.1, body, wv, 5, lh=1.12, color=DARK) + 0.75
    if yv > cv.h - 0.3:
        print(f"later voices run {yv - cv.h + 0.3:.1f} mm past the page")

    return cv.save("Case2_materia_medica_huangqi", OUT)


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
