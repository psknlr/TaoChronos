"""Figures whose labels keep apart: crowded specifications — a family of formulas most of whose members share one year, a
timeline crowding the right edge, bubbles at the top of a scatter, long names in narrow columns, more categories than a
column can label, lines ending at one value, values past a box plot's axis, a ring of thirty — drawn by both renderers
(study/svg.py and web/js/chart.js) at a screen's widths and a journal's, and checked in Chromium for labels over labels,
labels over marks and labels off the figure (tests/collisions.js); and the layout's pieces on their own."""

from __future__ import annotations

import functools
import http.server
import json
import math
import shutil
import threading
from pathlib import Path

import pytest

from taochronos.plugins.classics.study import charts, svg

ROOT = Path(__file__).resolve().parents[1]

FAMILY = ["葛根汤", "大青龙汤", "小建中汤", "桂枝加葛根汤", "桂枝二麻黄一汤", "桂枝加桂汤", "桂枝加附子汤", "桂枝附子汤", "茯苓白术汤",
          "黄芩加半夏生姜汤", "栝楼桂枝汤", "桂枝二越婢一汤", "桂枝加黄芪汤", "桂枝去芍药加附子汤", "桂枝救逆汤", "龙骨汤", "泽兰汤", "干地黄汤",
          "栝楼汤", "生地黄汤", "芍药汤", "乌头汤", "四逆汤", "葵子汤", "青龙汤", "桂枝葛根汤", "葛根加半夏汤", "当归芍药汤", "当归四逆汤",
          "桂枝加芍药汤"]
YEARS = [209.5] * 16 + [654.5] * 3 + [682, 752, 752, 752, 752, 752, 1180, 1398, 1652, 1685, 1732]
HERBS = ["甘草", "人参", "茯苓", "白术", "陈皮", "当归", "芍药", "川芎", "地黄", "干姜", "附子", "防风", "细辛", "麦冬", "黄芪", "桔梗",
         "生姜", "大枣", "半夏", "桂枝", "麻黄", "杏仁", "石膏", "黄芩", "柴胡", "升麻", "黄连", "大黄", "枳实", "木香"]
PERIODS = ["先秦两汉", "魏晋南北朝", "隋唐五代", "宋金元", "明", "清", "民国"]
GROUPS = ["加味", "减味", "加减"]


def wave(i: int, lo: float, hi: float) -> float:
    """A number in [lo, hi] that looks scattered and is the same every run."""
    return lo + (hi - lo) * (math.sin(i * 12.9898) * 43758.5453 % 1)


def crowded() -> list[dict]:
    c = charts.chart
    names = ["白虎汤", "白虎加人参汤", "白虎加桂枝汤", "竹叶石膏汤", "化斑汤（加减）"]
    out = [
        c("timeline", "桂枝汤 · 类方的最早见", [{"label": f, "start": y, "group": GROUPS[i % 3]} for i, (f, y) in enumerate(zip(FAMILY, YEARS))],
          [("label", "方"), ("start", "年代"), ("group", "关系")], x={"key": "start", "label": "年代"}, groups=GROUPS),
        c("timeline", "右端拥挤的时间线", [{"label": f + "（加减方）", "start": 1500 + 11 * i, "group": GROUPS[i % 3]} for i, f in enumerate(FAMILY[:14])],
          [("label", "方"), ("start", "年代")], x={"key": "start", "label": "年代"}),
        c("scatter", "药物关联规则", [{"rule": f"{a} → {b}", "support": wave(i, 0, 0.06), "confidence": wave(i + 50, 0.6, 1.0), "lift": wave(i + 99, 1, 100)}
                                    for i, (a, b) in enumerate(zip(HERBS, HERBS[1:]))] + [{"rule": "人参 → 甘草", "support": 0.002, "confidence": 1.0, "lift": 100}],
          [("rule", "规则"), ("support", "支持度"), ("confidence", "置信度"), ("lift", "提升度")],
          x={"key": "support", "label": "支持度", "percent": True, "min": 0}, y={"key": "confidence", "label": "置信度", "percent": True},
          size={"key": "lift", "label": "提升度"}, label="rule"),
        c("heatmap", "反、畏之药同见", [{"pair": p, "period": q, "works": int(wave(i * 7 + j, 0, 9))} for i, p in enumerate(["甘草反海藻", "乌头反半夏", "藜芦反人参"])
                                     for j, q in enumerate(PERIODS)], [("pair", "药对"), ("period", "时期"), ("works", "著作数")],
          x={"key": "period", "label": "时期", "order": PERIODS}, y={"key": "pair", "label": "药对"}, value={"key": "works", "label": "言此经的著作数"}),
        c("heatmap", "方剂相似度", [{"a": a, "b": b, "s": 1.0 if a == b else round(wave(i * 5 + j, 0.2, 0.9), 3)}
                                    for i, a in enumerate(names)
                                    for j, b in enumerate(names)], [("a", "方"), ("b", "方"), ("s", "相似度")],
          x={"key": "a", "label": "方", "order": names}, y={"key": "b", "label": "方", "order": names}, value={"key": "s", "label": "相似度", "max": 1}),
        c("bar", "二十六类", [{"drug": h + "（炙）", "n": int(wave(i, 1, 60))} for i, h in enumerate(HERBS[:26])], [("drug", "药"), ("n", "次")],
          x={"key": "drug", "label": "药"}, y={"label": "次", "min": 0}, series=[{"key": "n", "label": "次"}]),
        c("line", "终点相近的四条线", [{"period": p, **{f"s{k}": 0.3 + 0.02 * k + (wave(j * 4 + k, -0.1, 0.1) if j < 6 else 0) for k in range(4)}}
                                     for j, p in enumerate(PERIODS)], [("period", "时期")] + [(f"s{k}", f"药{k}") for k in range(4)],
          x={"key": "period", "label": "时期"}, y={"label": "占比", "percent": True, "min": 0}, series=[{"key": f"s{k}", "label": f"药{k}"} for k in range(4)]),
        c("hbar", "长名的横条", [{"f": f"加味{h}汤（出《太平惠民和剂局方》卷三）", "n": int(wave(i, 1, 200))} for i, h in enumerate(HERBS[:10])],
          [("f", "方"), ("n", "次")], x={"key": "f", "label": "方"}, y={"label": "次数"}, series=[{"key": "n", "label": "次"}]),
        c("box", "历代汤剂用量", [{"period": p} for p in PERIODS], [("period", "时期")], x={"key": "period", "label": "时期"},
          y={"label": "折合克数（g，按各期计量）", "min": 0},
          points={p: [round(math.exp(3 + wave(i * 40 + k, -1, 1)), 1) for k in range(40)] + ([900, 1200] if i in (0, 6) else []) for i, p in enumerate(PERIODS)}),
        c("network", "三十味药的环", [{"h": h} for h in HERBS], [("h", "药")],
          nodes=[{"id": h, "label": h, "group": GROUPS[i % 3], "size": int(wave(i, 1, 20))} for i, h in enumerate(HERBS)],
          edges=[{"source": a, "target": b, "weight": 1 + i % 9} for i, (a, b) in enumerate(zip(HERBS, HERBS[3:]))]),
        c("network", "长名的中心", [{"f": f} for f in FAMILY[:12]], [("f", "方")],
          nodes=[{"id": "base", "label": "白虎加人参汤（原方）", "group": "本方", "size": 30}]
          + [{"id": f"m{i}", "label": f, "group": GROUPS[i % 3], "size": i + 1} for i, f in enumerate(FAMILY[:12])],
          edges=[{"source": "base", "target": f"m{i}", "weight": i + 1, "label": "＋人参、粳米－知母"} for i in range(12)]),
    ]
    return out


# ------------------------------------------------------------------ the layout's pieces
def test_a_timeline_never_draws_a_stem_through_a_label():
    """Labels in lanes overlap no other label; a stem that would still cross one (in a crowded narrow figure) is broken
    around it — and the lanes stay near the compact layout's count."""
    width = 304.0
    xs = [30 + (y - 200) / (1740 - 200) * (width - 60) for y in YEARS]
    widths = [svg.text_width(f, 10.5) + 14 for f in FAMILY]
    lanes, flips = svg.timeline_lanes(xs, widths, width)
    rooms = [(x - w, x + 6) if f else (x - 6, x + w) for x, w, f in zip(xs, widths, flips)]
    for i in range(len(xs)):
        for j in range(i):
            assert lanes[i] != lanes[j] or rooms[i][1] + 2 <= rooms[j][0] or rooms[j][1] + 2 <= rooms[i][0], (FAMILY[i], FAMILY[j])
    assert max(lanes) + 1 <= 16 + 2  # sixteen members of one year need sixteen lanes; two more at most
    assert [f for f, flip in zip(FAMILY, flips) if flip] == ["当归芍药汤", "当归四逆汤", "桂枝加芍药汤"]  # turned at the right edge
    assert svg.stem_gaps(100, 0, 100, [(90, 20, 120, 30), (0, 40, 50, 50), (95, 60, 99, 70)]) == [(0, 18), (32, 58), (72, 100)]
    assert svg.stem_gaps(100, 0, 100, []) == [(0, 100)]


def test_a_legend_never_names_two_series_alike():
    w = [{"locator": "《新编金匮要略方论》卷1·烏頭·桂枝湯方（001-41a）", "years": [200, 219]},
         {"locator": "《新编金匮要略方论》卷2·○嘔吐噦下利病脉證治第十七·桂枝湯（002-31b）", "years": [200, 219]},
         {"locator": "《伤寒论》卷2·辨太阳病脉证并治中", "years": [200, 219]}]
    assert charts.witness_labels(w) == ["新编金匮要略方论·卷1（219）", "新编金匮要略方论·卷2（219）", "伤寒论（219）"]
    twins = [{"locator": "《千金方》卷9·甲", "years": [650, 682]}, {"locator": "《千金方》卷9·乙", "years": [650, 682]}]
    assert charts.witness_labels(twins) == ["千金方·卷9（682）甲", "千金方·卷9（682）乙"]


def test_a_long_name_is_cut_to_its_room():
    s = svg.clip_text("加味甘草汤（出《太平惠民和剂局方》卷三）", 11, 60)
    assert s.endswith("…") and svg.text_width(s, 11) <= 60 and s.startswith("加味甘草")
    assert svg.clip_text("甘草", 11, 60) == "甘草"


# ------------------------------------------------------------------ both renderers, in a browser
def _chromium():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return None
    from test_web_client import _chromium as find

    return find()


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="css/app.css"></head>
<body style="margin:0"><div id="h"></div><script type="module">
import { plot, figureNode } from "./js/chart.js";
import { collisions } from "./collisions.js";
const SVG = "http://www.w3.org/2000/svg";
const host = document.getElementById("h");
const found = [];
const check = (label, node) => { host.replaceChildren(node); const svg = node.tagName === "svg" ? node : node.querySelector("svg");
  for (const c of collisions(svg)) found.push(`${label}: ${c}`); };
const specs = await (await fetch("crowded.json")).json();
specs.forEach((spec, n) => {
  for (const w of [660, 340]) {
    const p = plot(spec, w), svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${Math.ceil(p.height)}`); svg.setAttribute("width", w); svg.setAttribute("height", Math.ceil(p.height));
    svg.append(p.svg);
    check(`page ${spec.title} ${w}`, svg);
  }
  for (const width of ["single", "double"]) check(`page ${spec.title} ${width}`, figureNode(spec, { style: "journal", number: n + 1, width }));
});
for (const [label, text] of await (await fetch("python.json")).json()) { const d = document.createElement("div"); d.innerHTML = text; check(label, d.firstElementChild); }
window.found = found;
document.body.dataset.done = "1";
</script></body></html>
"""


def test_crowded_figures_keep_their_labels_apart(tmp_path):
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    specs = crowded()
    shutil.copytree(ROOT / "web" / "js", tmp_path / "js")
    shutil.copytree(ROOT / "web" / "css", tmp_path / "css")
    shutil.copy(ROOT / "tests" / "collisions.js", tmp_path / "collisions.js")
    (tmp_path / "crowded.json").write_text(json.dumps(specs, ensure_ascii=False), encoding="utf-8")
    python = [(f"python {s['title']} {w}", svg.to_svg(s, number=1, width=w)) for s in specs for w in ("single", "double")]
    python += [(f"python {s['title']} screen", svg.to_svg(s, style="screen")) for s in specs]
    python.append(("python panels", svg.to_panels(specs[:4], number=1)))
    (tmp_path / "python.json").write_text(json.dumps(python, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
            page.wait_for_selector("body[data-done='1']", state="attached", timeout=120000)
            found = page.evaluate("window.found")
            browser.close()
    finally:
        srv.shutdown()
    assert not errors, errors
    assert not found, found[:20]
