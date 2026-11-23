"""Case 1 | Herbal formulas: from the features of a case to a pattern, a formula, its rationale and its modifications.

The figure draws the answer 道乃久 (Tao-R1) gave on 2026-11-23 to the question in panel a (bilateral knee pain for
three years in a 58-year-old woman, worse with cold, with soreness and weakness of the low back and knees).  Every
value, quotation and passage identifier comes from ``source_data/case1_knee_formula.json`` (``make_case_data.py``)
and is checked against it here; the English renderings and the romanised names are the figure's.
"""

from __future__ import annotations

from case_style import (
    BLUE,
    DARK,
    GREY,
    LIGHT,
    ORANGE,
    OUT,
    PALE,
    VERM,
    Canvas,
    answer,
    arrow,
    band,
    dot,
    line,
    load,
    para,
    query_strip,
    rbox,
    rect,
    rich,
    tint,
    title,
    width_mm,
)
from matplotlib.patches import Circle

D = load("case1_knee_formula.json")
T = D["tables"]

# --- the answer's own wording, with the figure's English and romanisation ----------------------------------------------
# rows of the answer's table 1, ordered by the part of the pattern each supports
FEATURES = [
    # (row of 表1, feature as in the answer, reading, verbatim excerpt of the witness, source, part of the pattern)
    (0, "Bilateral knee pain, 3 years, lower body", "Chronic bi 久痹 of the legs, moving from the waist into the knees",
     "若不速治流入脚膝乃為偏枯冷痺緩弱疼重", ("Shiyi dexiao fang", "世医得效方", "1328–1345", "shiyi_dexiao.009.01625"),
     "disease"),
    (4, "Lumbar pain with knee signs", "Lumbar pain of the kidney-channel (Shaoyin 少阴) type",
     "腰痛引脊內廉，少陰經痛也", ("Zhengyin maizhi", "症因脉治", "1641–1706", "jc_m107.00826"), "disease"),
    (1, "Worse with cold", "Cold the dominant qi: painful bi 痛痹, the yin pathogen prevails",
     "寒氣勝者為痛痺", ("Lantai guifan", "兰台轨范", "1764 (citing the Suwen)", "lantai_guifan.002.00277"), "branch"),
    (2, "Soreness and weakness of low back and knees", "Liver–kidney deficiency 肝肾亏虚: the root",
     "肝主筋，腎主骨", ("Yifang jijie", "医方集解", "1682", "jc_d075.00613"), "root"),
    (3, "58-year-old woman", "Past 七七: kidney essence waned, Chong and Ren depleted",
     "至七七則任脉虛，太衝脉衰少", ("Yifang leiju", "医方类聚", "1443–1445 (citing the Suwen)", "ws_e965e3774c.00593"),
     "root"),
]
COMP = {"disease": DARK, "branch": ORANGE, "root": BLUE}
PATTERN = [("disease", "Disease and site", ["Chronic bi 久痹,", "with lumbar pain 兼腰痛"]),
           ("branch", "Branch 标 · in excess", ["Cold–damp obstruction", "寒湿痹阻"]),
           ("root", "Root 本 · deficient", ["Liver–kidney deficiency", "肝肾两虚"])]

HERB = {"独活": "Duhuo", "细辛": "Xixin", "秦艽": "Qinjiao", "防风": "Fangfeng", "桂": "Gui", "桑寄生": "Sangjisheng",
        "杜仲": "Duzhong", "牛膝": "Niuxi", "当归": "Danggui", "川芎": "Chuanxiong", "芍药": "Shaoyao", "地黄": "Dihuang",
        "人参": "Renshen", "茯苓": "Fuling", "甘草": "Gancao", "续断": "Xuduan", "黄芪": "Huangqi", "羌活": "Qianghuo",
        "姜黄": "Jianghuang", "术": "Zhu", "干姜": "Ganjiang"}
# the answer's five clusters (its §4), in the tool's drug names (桂心 → 桂, 熟地黄 → 地黄)
CLUSTERS = [
    ("expel", "Expel wind–damp, free the channels, stop bi pain", "祛风湿、通经络、止痹痛", ["独活", "细辛", "秦艽", "防风"]),
    ("expel", "Warm the channels, disperse cold", "温经散寒", ["桂"]),
    ("support", "Tonify liver and kidney, strengthen sinew and bone", "补肝肾、强筋骨", ["桑寄生", "杜仲", "牛膝"]),
    ("support", "Nourish and move the blood", "养血活血", ["当归", "川芎", "芍药", "地黄"]),
    ("support", "Boost qi, fortify the spleen", "益气健脾", ["人参", "茯苓", "甘草"]),
]
OTHERS = ["续断", "黄芪", "羌活", "姜黄", "术", "干姜"]
ARM = {"expel": ORANGE, "support": BLUE}
FORMULAS = [("独活寄生汤", ["Duhuo", "jisheng tang"]), ("三痹汤", ["Sanbi tang"]), ("蠲痹汤", ["Juanbi tang"]),
            ("甘姜苓术汤", ["Ganjiang", "lingzhu tang"])]

CARDS = [
    ("独活寄生汤", "Duhuo jisheng tang", "治肝腎虛熱，風濕內攻，腰膝作痛，冷痹無力，屈伸不便",
     ("Yifang jijie", "医方集解", "1682", "jc_d075a.00357"),
     "Fits on all three counts: cold–damp bi, liver–kidney deficiency, lumbar and knee pain with weakness."),
    ("三痹汤", "Sanbi tang", "治血气凝滞，手足拘挛、风痹、气痹等疾皆疗",
     ("Furen daquan liangfang", "妇人大全良方", "1237", "jc_g005.00602"),
     "The same formula modified: chosen instead if qi–blood deficiency dominates (fatigue, pallor, sweating)."),
    ("蠲痹汤", "Juanbi tang", "治風濕相搏，身體煩疼，項臂痛重，舉動艱難…",
     ("Yangshi jiacang fang", "杨氏家藏方", "1178", "jc_d014.00450"),
     "Expels only: wind–damp bi without liver–kidney deficiency; cannot reach the root."),
    ("甘姜苓术汤", "Ganjiang lingzhu tang", "…腰以下冷痛腹重如帶五千錢甘薑苓术湯主之",
     ("Yimen falü", "医门法律", "1658", "yimen_falv.005.01040"),
     "Warms only: cold–damp lumbar pain with heaviness; treats neither the joint bi nor the deficiency."),
]

LINEAGE = [
    # (date, work, what the witness shows, passage, phrase of the answer or of its quotation that carries it)
    ("752", "Waitai miyao 外台秘要", "the Tang ancestor, Duhuo xuduan tang 独活续断汤", "jc_d004a.01483", "獨活續斷湯方"),
    ("1174", "Sanyin fang 三因方", "earliest witness of the name; all drugs at 3 liang", "sanyin_fang.003.00216",
     "各三兩"),
    ("1237", "Furen daquan liangfang 妇人大全良方", "lumbar pain in women; Duhuo 3 liang, the rest 2", "jc_g005.00820",
     "各二兩"),
    ("1264", "Renzhai zhizhi 仁斋直指", "lumbar pain; 「下利者去地黄」", "renzhai_zhizhi.018.01971", "下利者去地黄"),
    ("1328–1345", "Shiyi dexiao fang 世医得效方", "leg qi; Sangjisheng 「無真者續斷代」", "shiyi_dexiao.009.01625",
     "無真者續斷代"),
    ("1682", "Yifang jijie 医方集解", "rationale; credits the Qianjin (not confirmed)", "jc_d075a.00357", "出處：千金"),
]

MODS = [
    # (situation, modification, second line: name of the result and source, kind)
    ("Wind predominant, no heat", [("+", "Chenpi 陈皮")], "Renzhai zhizhi, 1264", "tune"),
    ("Qi deficiency with loose stools", [("−", "Dihuang")], "Renzhai zhizhi, 1264; Shiyi dexiao fang, 1328–1345",
     "tune"),
    ("Marked qi–blood deficiency, chronic bi not recovering", [("+", "Xuduan, Huangqi"), ("−", "Sangjisheng")],
     "= Sanbi tang 三痹汤 · Furen daquan liangfang, 1237", "tune"),
    ("Wind–damp pain seated in the lumbar region", [("−", "Duhuo, Sangjisheng"), ("+", "Qianghuo, Xuduan")],
     "= Qianghuo xuduan tang 羌活续断汤 · Yifang jijie, 1682", "tune"),
    ("Upper-body bi with numbness", [("=", "Sanbi tang"), ("−", "Wutou 乌头"), ("+", "Qianghuo, Mahuang 麻黄")],
     "Zhangshi yitong 张氏医通, 1695", "tune"),
    ("Bi entering the bone; bone wilting from kidney deficiency", [("+", "Hugu 虎骨 (sijin wan), Gusuibu 骨碎补")],
     "Bencao gangmu 本草纲目, 1552–1578; Puji fang, 1390–1406", "deep"),
    ("Disease in the viscera: kidney bi", [("=", "Wubi tang 五痹汤"), ("+", "Duhuo, Guangui, Duzhong, Niuxi, …")],
     "Zhengzhi zhunsheng 证治准绳, 1602 (two drug names lost)", "deep"),
    ("Severe cold: yang deficient, yin exuberant", [("=", "Fuzi 附子 forms: Zhouhou variant, Fuzi wan 附子丸")],
     "Waitai miyao, 752; Xuanming lunfang 宣明论方, 1172 · aconite", "warn"),
    ("Red, hot, swollen joints: damp–heat bi", [("=", "Not this formula (acrid–warm): a damp–heat method")],
     "Yishu 医述, 1826; Linzheng zhinan yi’an 临证指南医案, 1746", "warn"),
]

FINDING = {"痹": "Bi 痹", "腰痛": "Lumbar pain 腰痛", "痿": "Wilting 痿", "气虚": "Qi deficiency 气虚", "疮": "Sores 疮"}


def table(k: int) -> list[dict]:
    t = T[str(k)]
    return [dict(zip(t["columns"], r)) for r in t["rows"]]


def source_line(ax, x, y, src, fs=5.0, color=GREY):
    """A source: romanised title in italics, the title in characters, the date and the passage identifier."""
    name, han, date, pid = src
    return rich(ax, x, y, [(name, {"style": "italic", "color": color}), (f" {han}, {date} · {pid}", {"color": color})],
                fs, va="top")


def main() -> dict:
    cv = Canvas("double", 170)
    ax = cv.blank(0, 0, cv.w, cv.h)
    report = answer(1)

    # a — the question ---------------------------------------------------------------------------------------------------
    cv.label(2, 1.2, "a")
    query_strip(cv, ax, D, case="Case 1", domain="Herbal formulas",
                topic="Pattern differentiation and formula selection for bilateral knee pain", y=5.0, h=13.8)

    # b — features → readings → pattern ----------------------------------------------------------------------------------
    yb = 20.6
    cv.label(2, yb, "b")
    title(ax, 6.6, yb + 0.35, "Pattern differentiation: each feature of the case is read through a dated witness")
    xf, wf, xr, wr, xw, ww, xp, wp = 2.0, 33.0, 40.0, 41.0, 84.0, 62.0, 151.0, 30.0
    yh = yb + 4.1
    for x, s in ((xf, "Case feature"), (xr, "Classical reading"), (xw, "Witness, quoted verbatim, and its source"),
                 (xp, "Pattern 本虚标实")):
        ax.text(x, yh, s, ha="left", va="top", fontsize=5, fontweight="bold", color=DARK)
    y0, pitch, bh = yh + 2.5, 5.9, 5.3
    rows_y = [y0 + i * pitch for i in range(len(FEATURES))]
    assert [r["Case feature"].replace("‑", "-") for r in table(1)] == [
        "Bilateral knee pain, 3 years, lower body", "Worse with cold", "Soreness and weakness of low back and knees",
        "58-year-old woman", "Lumbar pain with knee signs"]
    for (k, feat, reading, quote, src, comp), y in zip(FEATURES, rows_y):
        col = COMP[comp]
        assert quote in T["1"]["rows"][k][2] and src[3] in report, quote
        rbox(ax, xf, y, wf, bh, fc=PALE, r=0.7)
        rect(ax, xf, y, 0.9, bh, fc=col)
        two = width_mm(feat, 5.5) > wf - 3.0
        para(ax, xf + 2.0, y + (bh - (4.5 if two else 2.3)) / 2 - 0.05, feat, wf - 3.0, 5.5, lh=1.15, max_lines=2)
        arrow(ax, xf + wf + 0.9, y + bh / 2, xr - 1.0, y + bh / 2, color=GREY, lw=0.5, head=2.6)
        para(ax, xr, y + 0.25, reading, wr, 5.5, lh=1.15, max_lines=2)
        ax.text(xw, y + 0.25, f"「{quote}」", ha="left", va="top", fontsize=5.5)
        xe = source_line(ax, xw + 0.9, y + 2.95, src)
        assert xe < xw + ww, (src, xe - xw - ww)
        if y is not rows_y[-1]:
            line(ax, [xr, xw + ww], [y + bh + 0.3] * 2, color=LIGHT, lw=0.3, z=1)
    # the three parts of the pattern
    top, bottom, gap = rows_y[0], rows_y[-1] + bh, 0.8
    ph = (bottom - top - 2 * gap) / 3
    slot = {}
    for k, (comp, head, lines_) in enumerate(PATTERN):
        col = COMP[comp]
        ya = top + k * (ph + gap)
        rbox(ax, xp, ya, wp, ph, fc=tint(col, 0.13), ec=col, lw=0.6, r=0.8)
        ax.text(xp + 1.6, ya + 1.0, head, ha="left", va="top", fontsize=5, fontweight="bold", color=DARK)
        ax.text(xp + 1.6, ya + 3.55, "\n".join(lines_), ha="left", va="top", fontsize=5.5, fontweight="bold",
                linespacing=1.2)
        n = sum(f[5] == comp for f in FEATURES)
        slot[comp] = [ya + ph * (i + 1) / (n + 1) for i in range(n)]
    seen = dict.fromkeys(slot, 0)
    for (_, _, _, _, _, comp), y in zip(FEATURES, rows_y):
        yt = slot[comp][seen[comp]]
        seen[comp] += 1
        band(ax, xw + ww + 0.6, y + bh / 2 - 0.55, y + bh / 2 + 0.55, xp - 0.35, yt - 0.55, yt + 0.55,
             tint(COMP[comp], 0.5))
    assert D["from_report"]["pattern"] == "痹证·久痹，肝肾两虚，寒湿痹阻；兼腰痛" and "本虚标实" in report

    # c — the formula in two arms, and its neighbours ----------------------------------------------------------------------
    yc = bottom + 2.5
    cv.label(2, yc, "c")
    title(ax, 6.6, yc + 0.35, "The formula the record pairs with this pattern, drug by drug, against three neighbours")
    drugs = {r["药物"]: r for r in table(21)}
    present = {f: {d for d, r in drugs.items() if r[f] != "—"} for f, _ in FORMULAS}
    huangqi = {"三痹汤": sum(v not in ("—", "") for v in T["10"]["rows"][15][1:]),
               "蠲痹汤": sum(v not in ("—", "") for v in T["13"]["rows"][6][1:])}
    assert T["10"]["rows"][15][0] == "黄芪类" and T["13"]["rows"][6][0] == "黄芪类" and huangqi == {"三痹汤": 2, "蠲痹汤": 1}
    order = [h for _, _, _, hs in CLUSTERS for h in hs] + OTHERS
    assert set(order) - {"黄芪"} == set(drugs), set(drugs) ^ set(order)
    assert [h.replace("桂", "桂心").replace("地黄", "熟地黄") for _, _, _, hs in CLUSTERS for h in hs] == [
        h for c in D["from_report"]["clusters"] for h in c["herbs"]]
    x_arm, x_cl, x_h, x_m, cw = 2.0, 6.2, 48.8, 69.2, 11.3
    y_head = yc + 4.5
    y_m = y_head + 6.9
    rp = 2.28
    for j, (han, py) in enumerate(FORMULAS):
        cx = x_m + (j + 0.5) * cw
        ax.text(cx, y_head, han, ha="center", va="top", fontsize=5.5, fontweight="bold",
                color=BLUE if j == 0 else "black")
        ax.text(cx, y_head + 2.35, "\n".join(py), ha="center", va="top", fontsize=5, fontstyle="italic",
                color=BLUE if j == 0 else DARK, linespacing=1.05)
    rbox(ax, x_m + 0.5, y_m - 0.5, cw - 1.0, len(order) * rp + 1.0, fc=tint(BLUE, 0.08), ec=BLUE, lw=0.5, r=0.9, z=0.5)
    i = 0
    arms: dict[str, list[float]] = {}
    for arm, func, han, hs in CLUSTERS:
        ya, yb2 = y_m + i * rp, y_m + (i + len(hs)) * rp
        col = ARM[arm]
        rect(ax, x_cl, ya + 0.15, x_m - x_cl - 0.6, yb2 - ya - 0.3, fc=tint(col, 0.13), z=0.4)
        arms.setdefault(arm, []).extend([ya, yb2])
        mid = (ya + yb2) / 2
        if len(hs) == 1:
            rich(ax, x_cl + 1.0, mid, [(func, {}), (f"  {han}", {"color": DARK})], 5, va="center_baseline")
        else:
            ax.text(x_cl + 1.0, mid - 1.25, func, ha="left", va="center_baseline", fontsize=5)
            ax.text(x_cl + 1.0, mid + 1.25, han, ha="left", va="center_baseline", fontsize=5, color=DARK)
        i += len(hs)
    for arm, lab in (("expel", "Expel"), ("support", "Support")):
        ya, yb2 = min(arms[arm]), max(arms[arm])
        n = sum(len(hs) for a, _, _, hs in CLUSTERS if a == arm)
        rect(ax, x_arm, ya + 0.15, 3.4, yb2 - ya - 0.3, fc=ARM[arm], z=0.4)
        ax.text(x_arm + 1.7, (ya + yb2) / 2, f"{lab} · {n}", ha="center", va="center", rotation=90, fontsize=5.5,
                fontweight="bold", color="black" if arm == "expel" else "white", zorder=5)
    y_other = y_m + 15 * rp
    rect(ax, x_arm, y_other + 0.15, x_m - x_arm - 0.6, len(OTHERS) * rp - 0.3, fc=PALE, z=0.4)
    ax.text(x_cl + 1.0, y_other + 2.5 * rp, "Drugs of the neighbours,", ha="left", va="center_baseline", fontsize=5,
            color=DARK)
    ax.text(x_cl + 1.0, y_other + 3.5 * rp, "or of some witnesses only (open)", ha="left", va="center_baseline",
            fontsize=5, color=DARK)
    arm_of = {h: arm for arm, _, _, hs in CLUSTERS for h in hs}
    for i, h in enumerate(order):
        yy = y_m + (i + 0.5) * rp
        mark = "†" if h == "续断" else "‡" if h == "黄芪" else ""
        rich(ax, x_h, yy, [(HERB[h], {}), (f" {h}", {}), (mark, {"color": DARK})], 5, va="center_baseline")
        if i:
            line(ax, [x_m, x_m + 4 * cw], [y_m + i * rp] * 2, color=LIGHT, lw=0.25, z=0.6)
        for j, (f, _) in enumerate(FORMULAS):
            cx = x_m + (j + 0.5) * cw
            if h in present[f]:
                col = ARM.get(arm_of.get(h), DARK) if j == 0 else DARK
                ax.add_patch(Circle((cx, yy), 0.72, facecolor=col, edgecolor="none", zorder=3))
            elif h == "黄芪" and f in huangqi:
                ax.add_patch(Circle((cx, yy), 0.6, facecolor="white", edgecolor=DARK, lw=0.5, zorder=3))
    y_end = y_m + len(order) * rp
    line(ax, [x_m, x_m + 4 * cw], [y_m, y_m], color=GREY, lw=0.4)
    line(ax, [x_m, x_m + 4 * cw], [y_end, y_end], color=GREY, lw=0.4)
    # the neighbours in words: indication, similarity, verdict
    pair = {r["方 B"]: r for r in table(22) if r["方 A"] == "独活寄生汤"}
    sim = dict(zip(D["from_charts"]["similarity"]["formulas"], D["from_charts"]["similarity"]["matrix"][0]))
    xk, wk = 117.6, 63.4
    ch = (y_end - y_head - 3 * 0.9) / 4
    for j, (han, py, quote, src, verdict) in enumerate(CARDS):
        yk = y_head + j * (ch + 0.9)
        first = j == 0
        rbox(ax, xk, yk, wk, ch, fc="white", ec=BLUE if first else GREY, lw=0.7 if first else 0.4, r=0.8)
        xe = rich(ax, xk + 1.6, yk + 1.1, [(han, {"weight": "bold", "color": BLUE if first else "black"}),
                                           (f"  {py}", {"style": "italic", "color": BLUE if first else DARK})], 6,
                  va="top")
        if first:
            tag = "selected"
        else:
            shared = len(pair[han]["共有药物"].split("、"))
            assert abs(float(pair[han]["Jaccard"]) - sim[han]) < 0.006
            tag = f"{shared} drugs shared · Jaccard {sim[han]:.2f}"
        tw = width_mm(tag, 5, "bold") + 1.8
        rbox(ax, xk + wk - tw - 1.2, yk + 0.85, tw, 2.5, fc=BLUE if first else tint(DARK, 0.14), r=0.6, z=2)
        ax.text(xk + wk - tw / 2 - 1.2, yk + 2.1, tag, ha="center", va="center_baseline", fontsize=5,
                fontweight="bold", color="white" if first else DARK, zorder=5)
        assert xe < xk + wk - tw - 1.6
        assert quote.replace("…", "") in "".join(T["2"]["rows"][j][1].split()) and src[3] in report, quote
        ax.text(xk + 1.6, yk + 3.95, f"「{quote}」", ha="left", va="top", fontsize=5)
        source_line(ax, xk + 2.5, yk + 6.1, src)
        para(ax, xk + 1.6, yk + 8.35, verdict, wk - 3.0, 5.5, lh=1.13, max_lines=2)

    # d — lineage ----------------------------------------------------------------------------------------------------------
    yd = y_end + 2.6
    cv.label(2, yd, "d")
    title(ax, 6.6, yd + 0.35, "Lineage in the corpus")
    xl, wl = 2.0, 50.0
    y = yd + 4.6
    ys_ = []
    for date, work, note, pid, phrase in LINEAGE:
        assert pid in report and phrase in report, (pid, phrase)
        ys_.append(y + 1.0)
        name, han = work.rsplit(" ", 1)
        xe = rich(ax, xl + 3.2, y, [(date, {"weight": "bold"}), (f"  {name}", {"style": "italic"}), (f" {han}", {})], 5,
                  va="top")
        ax.text(xl + 3.2, y + 2.15, note, ha="left", va="top", fontsize=5, color=DARK)
        assert max(xe, xl + 3.2 + width_mm(note, 5)) < xl + wl + 1.0, (note, width_mm(note, 5))
        y += 5.15
    line(ax, [xl + 1.0, xl + 1.0], [ys_[0], ys_[-1]], color=GREY, lw=0.5, z=2)
    for k, yy in enumerate(ys_):
        dot(ax, xl + 1.0, yy, 0.75, fc=DARK if k else "white", ec=DARK, lw=0.5)
    # the written compositions under this name, by period (the answer's 表5)
    per = [r for r in table(5) if r["时期"] != "合计"]
    total = sum(int(r["合计（处）"]) for r in per)
    std = sum(int(r["组成类别（处） · 原方·通行方"]) for r in per)
    assert (total, std) == (41, 28)
    y += 0.9
    ax.text(xl, y, f"{total} compositions written out under the name", ha="left", va="top", fontsize=5)
    ax.text(xl, y + 2.15, f"(dark, the {std} of the standard formula), by period:", ha="left", va="top", fontsize=5)
    y += 5.0
    xx = xl
    names = {"宋金元": "Song–Jin–Yuan", "明": "Ming", "清": "Qing", "民国": "Republican"}
    for r in per:
        n, s = int(r["合计（处）"]), int(r["组成类别（处） · 原方·通行方"])
        w = n / total * wl
        if s:
            rect(ax, xx, y, w * s / n - 0.15, 1.9, fc=BLUE)
        rect(ax, xx + w * s / n, y, w * (n - s) / n - 0.6, 1.9, fc=tint(BLUE, 0.35))
        xx += w
    ax.text(xl, y + 2.5, " · ".join(f"{names[r['时期']]} {r['合计（处）']}" for r in per), ha="left", va="top",
            fontsize=5)

    # e — modifications ----------------------------------------------------------------------------------------------------
    xe0, we = 55.0, 78.5
    cv.label(xe0, yd, "e")
    title(ax, xe0 + 4.6, yd + 0.35, "Modifications on record, and when not to use it")
    y = yd + 4.6
    pitch_e = (cv.h - 0.9 - y) / len(MODS)
    xs_, xm_ = xe0 + 2.6, xe0 + 30.0
    kcol = {"tune": BLUE, "deep": DARK, "warn": VERM}
    ym = []
    for sit, mods, src, kind in MODS:
        yy = y + 0.2
        ym.append(yy + 1.0)
        para(ax, xs_, yy, sit, 26.2, 5, lh=1.12, max_lines=2)
        parts_ = []
        for sign, txt in mods:
            if sign == "=":
                parts_.append((txt + "  ", {"weight": "bold" if kind == "warn" else "normal",
                                            "color": VERM if kind == "warn" else "black"}))
            else:
                parts_.append((f"{sign} ", {"weight": "bold", "color": BLUE if sign == "+" else DARK}))
                parts_.append((txt + "   ", {}))
        xend = rich(ax, xm_, yy, parts_, 5, va="top")
        ax.text(xm_, yy + 2.1, src, ha="left", va="top", fontsize=5, color=GREY)
        over = max(xend - 1.5, xm_ + width_mm(src, 5)) - (xe0 + we + 0.5)
        assert over < 0, f"{over:.1f} mm too wide: {sit}"
        y += pitch_e
    line(ax, [xe0 + 1.0, xe0 + 1.0], [ym[0], ym[-1]], color=GREY, lw=0.5, z=2)
    for (_, _, _, kind), yy in zip(MODS, ym):
        dot(ax, xe0 + 1.0, yy, 0.75, fc=kcol[kind])

    # f — the association the answer computed ---------------------------------------------------------------------------
    xf0 = 136.0
    wf0 = cv.w - 2.0 - xf0
    cv.label(xf0, yd, "f")
    title(ax, xf0 + 4.6, yd + 0.35, "Findings written before its name")
    lift = table(14)
    assert D["from_report"]["finding_works"] == 9
    vals = [float(r["提升度"]) for r in lift]
    x_bar, w_bar = xf0 + 24.8, 14.5
    ax.text(xf0 + 23.4, yd + 4.1, "of 9 works", ha="right", va="top", fontsize=5, color=DARK)
    ax.text(x_bar, yd + 4.1, "lift", ha="left", va="top", fontsize=5, color=DARK)
    for k, r in enumerate(lift):
        yy = yd + 7.6 + k * 2.3
        rich(ax, xf0 + 23.4, yy, [(FINDING[r["所见"]], {}), (f"   {r['次数']}", {"color": DARK})], 5,
             va="center_baseline", ha="right")
        rect(ax, x_bar, yy - 0.8, vals[k] / 40 * w_bar, 1.6, fc=BLUE)
        ax.text(x_bar + vals[k] / 40 * w_bar + 0.7, yy, f"{vals[k]:.1f}", ha="left", va="center_baseline", fontsize=5)
    line(ax, [x_bar, x_bar], [yd + 6.4, yd + 7.6 + 4 * 2.3 + 1.2], color="black", lw=0.5)

    # g — case records ---------------------------------------------------------------------------------------------------
    yg = yd + 19.8
    cv.label(xf0, yg, "g")
    title(ax, xf0 + 4.6, yg + 0.35, "Case records naming it")
    rec = D["from_report"]["case_records"]
    out = D["from_charts"]["case_outcomes_by_period"]
    seq = (["improved"] * (out["明"].get("improved", 0) + out["清"]["improved"]) + ["died"] * out["清"]["died"]
           + ["not recorded"] * out["清"]["not recorded"])
    assert len(seq) == rec["naming_formula"] == 11 and seq.count("improved") == rec["improved"] == 9
    yy = yg + 5.7
    for k, o in enumerate(seq):
        cx = xf0 + 1.0 + k * 2.25
        if o == "improved":
            dot(ax, cx, yy, 0.82, fc=BLUE)
        elif o == "died":
            dot(ax, cx, yy, 0.82, fc=VERM)
        else:
            dot(ax, cx, yy, 0.68, fc="white", ec=DARK, lw=0.5)
    ax.text(xf0 + 26.2, yy, "9 improved, 1 died,", ha="left", va="center_baseline", fontsize=5)
    ax.text(xf0, yy + 1.8, "1 without outcome; 1 Ming, 10 Qing; 7 women.", ha="left", va="top", fontsize=5)
    ax.text(xf0, yy + 3.95, "Records editors chose to keep: not efficacy.", ha="left", va="top", fontsize=5,
            color=DARK)

    # h — what the answer leaves open ------------------------------------------------------------------------------------
    yh2 = yg + 13.2
    cv.label(xf0, yh2, "h")
    title(ax, xf0 + 4.6, yh2 + 0.35, "Left to the examining clinician", color=VERM)
    para(ax, xf0, yh2 + 4.4, "Tongue and pulse, absent from the case: damp–heat, yin deficiency with heat or blood "
         "stasis would overturn the pattern. Deficiency, or disuse? Effusion, stiffness, deformity; imaging and "
         "bone density in parallel. Watch Xixin 细辛 and Gancao 甘草.", wf0, 5, lh=1.13, max_lines=6)

    return cv.save("Case1_herbal_formula_knee_pain", OUT)


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
