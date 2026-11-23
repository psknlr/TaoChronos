"""Case 3 | Acupuncture: what the agent released, and what it withheld, for recurrent low back pain.

The figure draws the answer 道乃久 (Tao-R1) gave on 2026-11-23 to the question in panel a (a 45-year-old desk worker,
low back pain for eight months, worse with sitting).  The case review found the information insufficient for a
prescription, so the answer gives the tradition's framework with its witnesses and assigns neither supplementing nor
draining.  Every value, quotation and passage identifier comes from ``source_data/case3_*`` (``make_case_data.py``) and
is checked against the answer here; the English renderings, the romanised names and the placing of the points on the
schematic body (by the surface landmarks the cited texts and the standard locations name) are the figure's.
"""

from __future__ import annotations

import re

from body_map import LUMBAR_STEP, MALLEOLUS, POPLITEAL, VERTEBRAE, Body
from case_style import (
    BLUE,
    DARK,
    GREEN,
    GREY,
    LIGHT,
    ORANGE,
    OUT,
    PALE,
    VERM,
    Canvas,
    answer,
    arrow,
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
from matplotlib.patches import Ellipse

D = load("case3_low_back_pain.json")
T = D["tables"]
REPORT = answer(3)
ORANGE_T = "#A86A00"  # the orange of the palette, darkened for text on white
LAYER = {"A": BLUE, "B": ORANGE, "C": GREEN, "T": DARK}
LAYER_T = {"A": BLUE, "B": ORANGE_T, "C": GREEN, "T": DARK}
G = {"color": GREY}
IT = {"style": "italic", "color": GREY}


def table(k: int) -> list[dict]:
    t = T[str(k)]
    return [dict(zip(t["columns"], r)) for r in t["rows"]]


def said(*phrases: str) -> None:
    for p in phrases:
        assert p in REPORT, p


# the points of the answer's three layers, and the one point only the rule table names
POINTS = [
    # layer, code, name, class, witness line (verbatim excerpt, work, date, passage) or None, rule table, works
    ("A", "A-shi", "阿是穴", "tender points at the site: the pain marks the point 以痛为输", None, "", None),
    ("A", "GV3", "Yaoyangguan 腰阳关", "Governor Vessel, on the lumbar spine at L4", None, "main", None),
    ("A", "BL23", "Shenshu 肾俞", "back-shu of the kidney; below the 14th vertebra, 1.5 cun to each side",
     ("療腰痛不可俛仰轉側難", "Zhenjiu zisheng jing", "针灸资生经, 1220", "zhenjiu_zisheng.005.00824"), "main", 4),
    ("A", "BL25", "Dachangshu 大肠俞", "back-shu of the large intestine; below the 16th vertebra",
     ("大腸俞治腰痛", "Zhenjiu zisheng jing", "针灸资生经, 1220", "zhenjiu_zisheng.005.00823"), "main", 1),
    ("B", "BL40", "Weizhong 委中", "he-sea and lower he-sea of the bladder; command point of lumbar region and back",
     ("腰痛俠脊至頭…委中主之", "Zhenjiu jiayi jing", "针灸甲乙经, 256–282", "jc_k000.01056"), "adjunct", 4),
    ("B", "BL60", "Kunlun 昆仑", "jing-river point of the bladder channel",
     ("腰痛不能俯仰…昆侖主之", "Zhenjiu jiayi jing", "针灸甲乙经, 256–282", "jc_k000.00958"), "", 9),
    ("C", "SI3", "Houxi 后溪", "confluent point of the Governor Vessel; with BL62 it governs neck, shoulder, "
     "lumbar region and back", None, "adjunct", None),
    ("C", "BL62", "Shenmai 申脉", "confluent point of the Yangqiao vessel", None, "", 3),
    ("T", "EX-UE7", "Yaotongdian 腰痛点", "extra point on the back of the hand: distal selection", None, "adjunct", None),
]
LAYER_OF = {p[1]: p[0] for p in POINTS}
METHODS = [  # the tool's 表11: method, the two sides of the pairing, the figure's English
    ("近远配穴", "local", "distal"), ("上下配穴", "upper", "lower"), ("左右配穴", "left with right, both sides", ""),
    ("本经配穴", "same channel: the bladder", ""), ("同名经配穴", "foot", "hand Taiyang")]
MATRIX_POINTS = ["GV3", "BL23", "BL25", "BL40", "EX-UE7", "SI3"]
RULES_EN = {"近部选穴": "local selection", "远部选穴": "distal selection", "近远配穴": "local with distal",
            "上下配穴": "upper with lower", "左右配穴": "left with right", "八脉交会配穴": "confluent-point pairing",
            "四总穴": "four command points"}
SHU = [("井", "Well"), ("荥", "Spring"), ("输", "Stream"), ("经", "River"), ("合", "Sea")]
PHASE = {"金": "metal", "水": "water", "木": "wood", "火": "fire", "土": "earth"}
RELATION = {"母": "mother", "同气": "own phase", "子": "child", "所胜": "controlled by water",
            "所不胜": "controls water"}


def body_panel(cv, ax, x0, y0, w, y1):
    """c — the points on a schematic figure seen from behind."""
    cv.label(x0, y0, "c")
    title(ax, x0 + 4.6, y0 + 0.35, "The points, seen from behind")
    h = y1 - y0 - 14.6
    b = Body(ax, x0 + w / 2 - 0.5, y0 + 5.4, h).draw()
    y_l2, y_l4 = VERTEBRAE["L2"] + LUMBAR_STEP / 2, VERTEBRAE["L4"] + LUMBAR_STEP / 2
    # the site of pain, where the tender points are sought
    cx, cy = b.at(0, (y_l2 + y_l4) / 2 + 0.004)
    ax.add_patch(Ellipse((cx, cy), 0.156 * h, 0.094 * h, facecolor=tint(VERM, 0.24), edgecolor="none", lw=0,
                         zorder=1.3))
    # channels, schematic
    for side in (1, -1):
        b.channel([(0.014, 0.060), (0.016, 0.120), (0.020, 0.170), (0.020, 0.300), (0.020, 0.440), (0.028, 0.500),
                   (0.050, 0.548), (0.050, 0.630), (0.048, POPLITEAL), (0.049, 0.800), (0.055, 0.880),
                   (0.055, MALLEOLUS - 0.004), (0.064, MALLEOLUS + 0.016), (0.067, 0.986)], side, edgecolor="#8A8A8A",
                  lw=0.6)
        b.channel([(0.172, 0.626), (0.1645, 0.572), (0.1605, 0.527), (0.150, 0.470), (0.128, 0.378), (0.114, 0.300),
                   (0.100, 0.248), (0.070, 0.240), (0.078, 0.202), (0.040, 0.176)], side, edgecolor="#8A8A8A", lw=0.5,
                  ls=(0, (2.4, 1.4)))
    ax.plot(*zip(b.at(0, 0.004), b.at(0, 0.500)), color="#6E6E6E", lw=0.5, zorder=2.1)
    # the points
    pos = {"GV3": [(0.0, y_l4)], "BL23": [(0.020, y_l2), (-0.020, y_l2)], "BL25": [(0.020, y_l4), (-0.020, y_l4)],
           "BL40": [(0.048, POPLITEAL), (-0.048, POPLITEAL)],
           "BL60": [(0.055, MALLEOLUS - 0.004), (-0.055, MALLEOLUS - 0.004)],
           "BL62": [(0.064, MALLEOLUS + 0.016), (-0.064, MALLEOLUS + 0.016)],
           "SI3": [(0.1645, 0.572), (-0.1645, 0.572)],
           "EX-UE7": [(0.172, 0.552), (0.188, 0.552), (-0.172, 0.552), (-0.188, 0.552)]}
    for code, pts in pos.items():
        for x, y in pts:
            px, py = b.at(x, y)
            if code == "EX-UE7":
                dot(ax, px, py, 0.5, fc=DARK, ec="white", lw=0.3, z=4)
            else:
                dot(ax, px, py, 0.82, fc=LAYER[LAYER_OF[code]], ec="white", lw=0.4, z=4)

    def tag(code, x, y, ha="left", dx=0.0, dy=0.0, lead=None):
        px, py = b.at(x, y)
        col = LAYER_T[LAYER_OF[code]]
        if lead:
            lx, ly = b.at(*lead)
            line(ax, [lx, px + dx], [ly, py + dy], color=col, lw=0.4, z=3.5)
        ax.text(px + dx, py + dy, code, ha=ha, va="center_baseline", fontsize=5.5, fontweight="bold", color=col,
                zorder=6)

    tag("BL23", 0.020, y_l2, dx=1.6)
    tag("BL25", 0.020, y_l4, dx=1.6)
    tag("GV3", -0.050, y_l4 + 0.036, ha="right", lead=(-0.004, y_l4 + 0.006))
    tag("BL40", 0.048, POPLITEAL, dx=5.2)
    tag("BL60", 0.055, MALLEOLUS - 0.004, dx=3.4, dy=-0.9)
    tag("BL62", 0.064, MALLEOLUS + 0.016, dx=2.4, dy=1.2)
    tag("SI3", 0.1645, 0.572, ha="right", dx=-1.6)
    tag("EX-UE7", 0.180, 0.552, ha="center", dy=12.6, lead=(0.180, 0.560))
    # the site, the vertebrae, the channels
    px, py = b.at(-0.083, y_l2 - 0.046)
    ax.text(px, py, "A-shi", ha="left", va="center_baseline", fontsize=5.5, fontweight="bold", color=BLUE, zorder=6)
    for name in ("L2", "L4"):
        px, py = b.at(-0.034, VERTEBRAE[name])
        ax.text(px, py, name, ha="right", va="center_baseline", fontsize=5, color=DARK, zorder=6)
    px, py = b.at(0.062, 0.022)
    ax.text(px, py, "Governor Vessel\n督脉", ha="left", va="center", fontsize=5, color=DARK, linespacing=1.1)
    line(ax, [b.at(0.003, 0.022)[0], px - 0.8], [py, py], color="#8A8A8A", lw=0.4)
    px, py = b.at(-0.062, 0.128)
    ax.text(px, py, "Small intestine channel\nhand Taiyang 手太阳", ha="right", va="center", fontsize=5, color=DARK,
            linespacing=1.1)
    line(ax, [px + 0.6, b.at(-0.058, 0.186)[0]], [py + 1.4, b.at(-0.058, 0.186)[1]], color="#8A8A8A", lw=0.4)
    px, py = b.at(-0.094, 0.800)
    ax.text(px, py, "Bladder channel\nfoot Taiyang 足太阳", ha="right", va="center", fontsize=5, color=DARK,
            linespacing=1.1)
    line(ax, [px + 0.6, b.at(-0.049, 0.800)[0]], [py, py], color="#8A8A8A", lw=0.4)
    # key
    yk = y1 - 6.8
    xk = x0 + 0.9
    for lab, lay, txt in (("A", "A", "local, at the site"), ("B", "B", "distal, on the channel"),
                          ("C", "C", "upper with lower: confluent pair")):
        dot(ax, xk, yk, 0.82, fc=LAYER[lay])
        rich(ax, xk + 1.8, yk, [(lab + "  ", {"weight": "bold", "color": LAYER_T[lay]}), (txt, {})], 5,
             va="center_baseline")
        yk += 2.35
    dot(ax, x0 + 33.2, y1 - 6.8, 0.5, fc=DARK)
    ax.text(x0 + 34.8, y1 - 6.8, "rule table only", ha="left", va="center_baseline", fontsize=5)
    ax.add_patch(Ellipse((x0 + 33.2, y1 - 4.45), 2.4, 1.6, facecolor=tint(VERM, 0.24), edgecolor="none", lw=0,
                         zorder=3))
    ax.text(x0 + 34.8, y1 - 4.45, "site of pain", ha="left", va="center_baseline", fontsize=5)


def main() -> dict:
    cv = Canvas("double", 170)
    ax = cv.blank(0, 0, cv.w, cv.h)

    # a — the question ---------------------------------------------------------------------------------------------------
    cv.label(2, 1.2, "a")
    query_strip(cv, ax, D, case="Case 3", domain="Acupuncture",
                topic="Pattern differentiation and point selection for chronic low back pain", y=5.0, h=13.8)

    # b — the review -------------------------------------------------------------------------------------------------------
    said("information insufficient", "Candidate points may only be released against a **reviewed** premise",
         "不实不虚，以经取之", "unknown is not read as negative", "The kidney state came back *unknown*",
         "tongue, pulse, associated symptoms", "acute neurological signs", "aetiological work-up",
         "not yet his prescription", "no supplementation/draining intention has been assigned")
    yb = 20.6
    cv.label(2, yb, "b")
    title(ax, 6.6, yb + 0.35, "The case review comes first, and it withholds a prescription")
    y0, bh = yb + 4.5, 17.2
    boxes = [(2.0, 37.0), (41.5, 40.5), (88.0, 56.5), (150.5, 30.5)]
    # what the question gives
    x, w = boxes[0]
    rbox(ax, x, y0, w, bh, fc=PALE, r=0.8)
    ax.text(x + 1.6, y0 + 1.3, "Given in the question", ha="left", va="top", fontsize=5.5, fontweight="bold")
    para(ax, x + 1.6, y0 + 4.9, "Man, 45; long hours at a desk\nLow back pain, recurrent, 8 months\n"
         "Worse with prolonged sitting", w - 3.0, 5.5, lh=1.36)
    # what was never collected
    x, w = boxes[1]
    rbox(ax, x, y0, w, bh, fc="white", ec=GREY, lw=0.5, r=0.8, ls=(0, (2.4, 1.6)))
    ax.text(x + 1.6, y0 + 1.3, "Not collected: unknown", ha="left", va="top", fontsize=5.5, fontweight="bold",
            color=DARK)
    para(ax, x + 1.6, y0 + 4.9, "Excess or deficiency 虚实; kidney state\nTongue, pulse, associated symptoms\n"
         "Neurological signs; cause of the pain", w - 3.0, 5.5, lh=1.36, color=DARK)
    ax.text((boxes[0][0] + boxes[0][1] + boxes[1][0]) / 2, y0 + bh / 2, "+", ha="center", va="center", fontsize=7,
            color=DARK)
    arrow(ax, boxes[1][0] + boxes[1][1] + 0.9, y0 + bh / 2, boxes[2][0] - 0.9, y0 + bh / 2, color=DARK, lw=0.7,
          head=3.4)
    # the review and its two findings
    x, w = boxes[2]
    rbox(ax, x, y0, w, bh, fc="white", ec=VERM, lw=0.7, r=0.8)
    xe = rich(ax, x + 1.6, y0 + 1.3, [("Acupuncture case review:", {"weight": "bold"})], 5.5, va="top")
    tw = width_mm("information insufficient", 5.5, "bold") + 2.0
    rbox(ax, xe + 1.2, y0 + 0.95, tw, 2.9, fc=VERM, r=0.6, z=2)
    ax.text(xe + 1.2 + tw / 2, y0 + 2.4, "information insufficient", ha="center", va="center_baseline", fontsize=5.5,
            fontweight="bold", color="white", zorder=5)
    yy = y0 + 5.0
    for k, s in enumerate(("Points are released only against a reviewed premise that matches the organ, the aspect "
                           "and excess or deficiency.",
                           "‘Take the channel itself’ 以经取之 needs 实, 虚 or 不实不虚 established. Unknown is none of "
                           "these, and is not read as negative.")):
        ax.text(x + 1.6, yy, f"{k + 1}", ha="left", va="top", fontsize=5, fontweight="bold", color=VERM)
        yy = para(ax, x + 4.0, yy, s, w - 5.4, 5, lh=1.13, max_lines=3) + 0.55
    arrow(ax, x + w + 0.9, y0 + bh / 2, boxes[3][0] - 0.9, y0 + bh / 2, color=DARK, lw=0.7, head=3.4)
    # what follows
    x, w = boxes[3]
    hh = (bh - 0.9) / 2
    rbox(ax, x, y0, w, hh, fc=tint(VERM, 0.12), r=0.8)
    ax.text(x + 1.6, y0 + 0.9, "Withheld", ha="left", va="top", fontsize=5.5, fontweight="bold", color=VERM)
    para(ax, x + 1.6, y0 + 3.4, "a prescription for him; supplementing or draining", w - 2.6, 5, lh=1.12, max_lines=2)
    rbox(ax, x, y0 + hh + 0.9, w, hh, fc=tint(BLUE, 0.12), r=0.8)
    ax.text(x + 1.6, y0 + hh + 1.8, "Released", ha="left", va="top", fontsize=5.5, fontweight="bold", color=BLUE)
    para(ax, x + 1.6, y0 + hh + 4.3, "the tradition’s framework, with its witnesses (c–h)", w - 2.6, 5, lh=1.12,
         max_lines=2)

    # c — the body ---------------------------------------------------------------------------------------------------------
    y_row = y0 + bh + 2.4
    said("Layer A — local", "阿是穴 (pain-as-needle, 以痛为输) + 腰阳关 GV3", "肾俞 BL23", "大肠俞 BL25",
         "委中 BL40 (bilateral) + 昆仑 BL60", "后溪 SI3 with 申脉 BL62", "在第十四椎下，兩傍各一寸五分",
         "在第十六椎下，兩傍各一寸五分", "中央約文中動脈")
    body_panel(cv, ax, 2.0, y_row, 58.0, cv.h - 1.0)

    # d — the evidence for each point ------------------------------------------------------------------------------------
    xd, wd = 64.0, cv.w - 2.0 - 64.0
    cv.label(xd, y_row, "d")
    title(ax, xd + 4.6, y_row + 0.35, "Why each point: its class, and the works that give it for lumbar pain 腰痛")
    works = {r["穴位"].split()[-1]: (int(r["著作（部）"]), r["最早见证"], r["成书年代"]) for r in table(12)}
    rule = {r["穴位"].split()[-1]: {"主穴": "main", "配穴": "adjunct"}[r["主配"]] for r in table(10)}
    assert rule == {"BL23": "main", "BL25": "main", "GV3": "main", "BL40": "adjunct", "EX-UE7": "adjunct",
                    "SI3": "adjunct"}
    assert "1 部著作言其主「腰痛」" in T["10"]["rows"][1][5]
    assert works["BL23"][1:] == ("《针灸资生经》", "1220") and works["BL40"][1:] == ("《针灸甲乙经》", "256–282")
    x_pt, x_cl, x_rule, x_bar = xd + 3.2, xd + 34.5, xd + 93.0, xd + 104.0
    w_cl = x_rule - x_cl - 2.0
    yh = y_row + 4.4
    for xx, s in ((x_pt, "Point"), (x_cl, "Class and classical statement"), (x_rule, "Rule table"),
                  (x_bar, "Works")):
        ax.text(xx, yh, s, ha="left", va="top", fontsize=5, fontweight="bold", color=DARK)
    y = yh + 3.1
    lead = 2.14
    prev = None
    for lay, code, name, cls, wit, rl, n in POINTS:
        if code in works:
            assert works[code][0] == n, code
        elif n is not None:
            assert code == "BL25" and n == 1
        assert rule.get(code, "") == rl, code
        if prev is not None and lay != prev:
            line(ax, [xd, xd + wd], [y - 0.5] * 2, color=LIGHT, lw=0.4)
            y += 0.6
        prev = lay
        if code == "A-shi":
            ax.add_patch(Ellipse((xd + 1.0, y + 1.05), 2.4, 1.6, facecolor=tint(VERM, 0.24), edgecolor="none", lw=0,
                                 zorder=3))
        else:
            dot(ax, xd + 1.0, y + 1.05, 0.5 if lay == "T" else 0.82, fc=LAYER[lay])
        rich(ax, x_pt, y, [(code, {"weight": "bold", "color": LAYER_T[lay]}), (f"  {name}", {})], 5, va="top")
        y_cl = para(ax, x_cl, y, cls, w_cl, 5, lh=1.12, max_lines=2)
        if wit:
            quote, work, rest, pid = wit
            assert all(q in REPORT for q in quote.split("…")) and pid in REPORT, quote
            xe = rich(ax, x_cl, y_cl + 0.1, [(f"「{quote}」", {}), (f" {work}", IT), (f" {rest}", G)], 5, va="top")
            assert xe < x_rule - 1.0, (code, xe - x_rule)
            y_cl += lead + 0.1
        ax.text(x_rule, y, rl or "–", ha="left", va="top", fontsize=5, color="black" if rl else GREY)
        if n:
            rect(ax, x_bar, y + 0.35, n * 1.05, 1.5, fc=LAYER[lay])
            ax.text(x_bar + n * 1.05 + 0.7, y, f"{n}", ha="left", va="top", fontsize=5)
        else:
            ax.text(x_bar, y, "–", ha="left", va="top", fontsize=5, color=GREY)
        y = y_cl + 1.5
    others = [r for r in table(12) if not r["规则亦取"]]
    assert [r["穴位"] for r in others] == ["太白 SP3", "阴陵泉 SP9"] and all(r["著作（部）"] == "2" for r in others)
    line(ax, [xd, xd + wd], [y - 0.5] * 2, color=LIGHT, lw=0.4)
    ax.text(xd, y + 0.2, "Also given for lumbar pain in two works each, and not selected: SP3 Taibai 太白, SP9 "
            "Yinlingquan 阴陵泉 (from 256–282).", ha="left", va="top", fontsize=5, color=DARK)
    y_d_end = y + 2.6

    # e — pairing ----------------------------------------------------------------------------------------------------------
    ye = y_d_end + 2.8
    cv.label(xd, ye, "e")
    title(ax, xd + 4.6, ye + 0.35, "How the points pair")
    pairs = {r["方法"]: r for r in table(11)}
    code_of = {r["穴位"].split()[0]: r["穴位"].split()[-1] for r in table(10)}
    x_m, cw = xd + 37.5, 5.4
    y_m = ye + 7.6
    rp = 4.0
    for j, code in enumerate(MATRIX_POINTS):
        ax.text(x_m + (j + 0.5) * cw, y_m - 1.3, code.replace("EX-UE7", "EX-\nUE7"), ha="center", va="bottom",
                fontsize=5, fontweight="bold", color=LAYER_T[LAYER_OF[code]], linespacing=0.95)
    for i, (han, g1, g2) in enumerate(METHODS):
        yy = y_m + (i + 0.5) * rp
        txt = pairs[han]["说明"]
        rect(ax, xd, yy - 0.8, 1.6, 1.6, fc=DARK)
        xk = rich(ax, xd + 2.3, yy, [(g1[0].upper() + g1[1:], {})], 5, va="center_baseline")
        if g2:
            xk = rich(ax, xk, yy, [(" with ", {})], 5, va="center_baseline")
            rect(ax, xk + 0.2, yy - 0.8, 1.6, 1.6, fc=tint(DARK, 0.3))
            rich(ax, xk + 2.5, yy, [(g2, {})], 5, va="center_baseline")
        first, second = txt.split("配", 1) if g2 else (txt, "")
        for j, code in enumerate(MATRIX_POINTS):
            name = next(k for k, v in code_of.items() if v == code)
            assert (name in txt) == (code in pairs[han]["穴位"]), (han, code)
            cx = x_m + (j + 0.5) * cw
            if name in first:
                rect(ax, cx - 2.0, yy - 1.2, 4.0, 2.4, fc=DARK)
            elif name in second:
                rect(ax, cx - 2.0, yy - 1.2, 4.0, 2.4, fc=tint(DARK, 0.3))
            else:
                line(ax, [cx - 0.5, cx + 0.5], [yy, yy], color=LIGHT, lw=0.5)
    y_e_end = y_m + len(METHODS) * rp

    # f — where the rules come from ---------------------------------------------------------------------------------------
    xf = 138.0
    wf = cv.w - 2.0 - xf
    cv.label(xf, ye, "f")
    title(ax, xf + 4.6, ye + 0.35, "Where the rules are first written")
    said("病在腰者，取之膕", "jc_a100.00065", "此遠取之法也", "jc_a402a.10486", "未在本语料检得")
    rules = D["from_charts"]["rule_earliest_witness"]
    by_year: dict[int, list[str]] = {}
    for r in rules:
        by_year.setdefault(r["earliest_year"], []).append(RULES_EN[r["rule"]])
    assert sorted(by_year) == [25, 1388, 1439]
    yy = ye + 5.0
    ys = []
    for year, head in ((25, "By 25 CE: the Inner Classic 内经"), (1388, "1388"), (1439, "1439")):
        ys.append(yy + 1.0)
        ax.text(xf + 3.0, yy, head, ha="left", va="top", fontsize=5, fontweight="bold")
        if year == 25:
            rich(ax, xf + 3.0, yy + 2.2, [("「病在腰者，取之膕」", {}), (" Lingshu", IT), (" 灵枢 9", G)], 5, va="top")
            yy = para(ax, xf + 3.0, yy + 4.4, "; ".join(by_year[year]), wf - 3.0, 5, lh=1.12, color=DARK) + 1.0
        else:
            rich(ax, xf + 3.0 + width_mm(head, 5, "bold") + 1.2, yy, [("; ".join(by_year[year]), {"color": DARK})], 5,
                 va="top")
            yy += 3.2
    line(ax, [xf + 1.0] * 2, [ys[0], ys[-1]], color=GREY, lw=0.5, z=2)
    for y_ in ys:
        dot(ax, xf + 1.0, y_, 0.75, fc=DARK)
    yy = para(ax, xf, yy + 0.3, "Not found in the corpus, so not cited: the Suwen chapter on needling lumbar pain "
              "刺腰痛篇.", wf, 5, lh=1.12, color=DARK, max_lines=3)

    # g — supplement or drain? ------------------------------------------------------------------------------------------
    yg = max(y_e_end, yy) + 3.0
    cv.label(xd, yg, "g")
    title(ax, xd + 4.6, yg + 0.35, "Supplement or drain? Unassigned until he is examined")
    said("虚则补其母", "实则泻其子", "不实不虚，以经取之", "an \"Earth\" point is not Spleen tonification",
         "cannot be manufactured from the name of a point")
    mc = {r["经脉"]: r for r in table(8)}
    bl, ki = mc["足太阳膀胱经"], mc["足少阴肾经"]
    assert bl["五行"] == ki["五行"] == "水"
    assert (bl["本经母穴（补）"], bl["本经子穴（泻）"], bl["本穴"]) == ("至阴 BL67", "束骨 BL65", "足通谷 BL66")
    assert (ki["本经母穴（补）"], ki["本经子穴（泻）"], ki["本穴"]) == ("复溜 KI7", "涌泉 KI1", "阴谷 KI10")
    shu = next(r for r in T["2"]["rows"] if r[0] == "足太阳膀胱经")[1:]
    rel = next(r for r in T["9"]["rows"] if r[0].startswith("足太阳膀胱经"))[1:]
    wg = 76.0
    cwg = (wg - 4 * 0.8) / 5
    y1g = yg + 4.6
    ax.text(xd, y1g, "Five shu points of the bladder channel (water), from the toe to the knee", ha="left", va="top",
            fontsize=5, fontweight="bold", color=DARK)
    yc_ = y1g + 2.8
    hc = 10.6
    role = {"母": "the mother", "同气": "its own point", "子": "the child"}
    col_of = {"母": "本经母穴（补）", "同气": "本穴", "子": "本经子穴（泻）"}
    for k, ((han, en), s_, r) in enumerate(zip(SHU, shu, rel)):
        name, code, ph = re.match(r"(\S+) (BL\d+)（(.)）", s_).groups()
        kind = re.search(r"；(.+?)：", r).group(1)
        assert name in r and kind in RELATION
        x = xd + k * (cwg + 0.8)
        used = code in LAYER_OF
        rbox(ax, x, yc_, cwg, hc, fc=tint(ORANGE, 0.16) if used else tint(BLUE, 0.11), r=0.7)
        rich(ax, x + 1.0, yc_ + 0.9, [(f"{en} {han}", {"weight": "bold"})], 5, va="top")
        rich(ax, x + 1.0, yc_ + 3.2, [(code, {"weight": "bold", "color": ORANGE_T if used else "black"}),
                                      (f" {name}", {})], 5, va="top")
        ax.text(x + 1.0, yc_ + 5.5, PHASE[ph], ha="left", va="top", fontsize=5, color=DARK)
        if kind in role:
            # the cell the five-phase table calls mother, own phase or child is the point the rule table names for it
            assert bl[col_of[kind]].endswith(code), (code, kind)
            ax.text(x + 1.0, yc_ + 7.8, role[kind], ha="left", va="top", fontsize=5, fontweight="bold", color=BLUE)
        else:
            ax.text(x + 1.0, yc_ + 7.8, "in layer B", ha="left", va="top", fontsize=5, fontweight="bold",
                    color=ORANGE_T)
    # the three rules, and the state of this case
    yr = yc_ + hc + 1.5
    rows_ = [("Deficient 虚", "supplement the mother 补其母", f"BL67, or kidney {ki['本经母穴（补）'].split()[1]}", "black"),
             ("Excess 实", "drain the child 泻其子", f"BL65, or kidney {ki['本经子穴（泻）'].split()[1]}", "black"),
             ("Neither 不实不虚", "take the channel itself 以经取之", f"BL66, or kidney {ki['本穴'].split()[1]}", "black"),
             ("Unknown: this case", "no intention is assigned", "none", VERM)]
    rpg = (cv.h - 1.2 - 2.5 - yr) / len(rows_)
    assert 2.5 < rpg < 3.6, rpg
    for k, (state, act, pts, col) in enumerate(rows_):
        yy2 = yr + (k + 0.5) * rpg
        if col == VERM:
            rbox(ax, xd, yy2 - rpg / 2 + 0.15, wg, rpg - 0.3, fc=tint(VERM, 0.12), r=0.6)
        ax.text(xd + 1.0, yy2, state, ha="left", va="center_baseline", fontsize=5, fontweight="bold", color=col)
        ax.text(xd + 22.5, yy2, act, ha="left", va="center_baseline", fontsize=5, color=col)
        ax.text(xd + wg - 1.0, yy2, pts, ha="right", va="center_baseline", fontsize=5, color=col)
        if k and col != VERM:
            line(ax, [xd, xd + wg], [yy2 - rpg / 2] * 2, color=LIGHT, lw=0.3)
    ax.text(xd, cv.h - 1.2 - 1.9, "An earth point is not spleen tonification: no deficiency is read from a point’s "
            "name.", ha="left", va="top", fontsize=5, color=DARK)

    # h — safety -----------------------------------------------------------------------------------------------------------
    xh = xd + wg + 4.0
    wh = cv.w - 3.0 - xh
    cv.label(xh, yg, "h")
    title(ax, xh + 4.6, yg + 0.35, "Before any needling", color=VERM)
    said("pain radiating below the knee", "saddle/perineal numbness", "bladder or bowel dysfunction",
         "unexplained weight loss", "history of cancer, steroid use, or trauma", "禁灸", "jc_k008.00953",
         "not these points, not this method, not this case")
    yy = para(ax, xh, y1g, "Eight months of recurrent pain: medical assessment first.", wh, 5, lh=1.12,
              weight="bold", max_lines=2)
    yy = para(ax, xh, yy + 0.7, "Urgent if there is pain below the knee, numbness or weakness of a leg, saddle "
              "numbness, bladder or bowel change, fever, weight loss, cancer, steroid use or trauma.", wh, 5,
              lh=1.12, max_lines=5)
    yy = para(ax, xh, yy + 0.7, "BL40 lies by an artery; one source forbids moxa there (Zhenjiu fengyuan 针灸逢源, "
              "1822).", wh, 5, lh=1.12, max_lines=3)
    para(ax, xh, yy + 0.7, "The modern evidence attached is for acupuncture in general, not for these points.", wh, 5,
         lh=1.12, color=DARK, max_lines=3)

    return cv.save("Case3_acupuncture_low_back_pain", OUT)


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt")})
    print("\n".join(r["warnings"]) or "no warnings")
