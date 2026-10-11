"""方药研究 — the herb and formula studies over a synthetic corpus (tests/fixtures/formulas) read with the lexicons the
browser's corpus loads (curated, the supplement and the core of the harvest): formulas compared, the formulas made from a
base, a drug's use through the periods, the natures and channels of several drugs, the 十八反 in the texts, a research
protocol from a question, and the charts of each — valid specifications, drawn as SVG, written as CSV."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService, charts, svg, tablefmt, tables
from taochronos.plugins.classics.study.herbs import channel_tokens
from taochronos.plugins.classics.study.metrology import cn_number
from taochronos.plugins.classics.study.render import markdown
from taochronos.plugins.classics.study.usage import prepared_form

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics", extra_lexicons=("lexicon-supplement", "lexicon-core"))
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "formulas")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def pair_of(r: dict, a: str, b: str) -> dict:
    return next(p for p in r["pairs"] if {p["a"], p["b"]} == {a, b})


# ------------------------------------------------------------------ 方剂比较 · 类方
def test_compare_reads_shared_drugs_doses_and_a_verdict_per_pair(study):
    r = study.compare(["桂枝汤", "麻黄汤", "葛根汤"])
    assert r["summary"]["found"] == 3 and all(f["witness"]["years"] == [200, 219] for f in r["formulas"])  # 原方: the earliest
    gz = pair_of(r, "桂枝汤", "葛根汤")
    assert gz["verdict"] == "加减化裁" and gz["only_a"] == [] and gz["only_b"] == ["葛根", "麻黄"]
    assert {"drug": "桂", "a": "三两", "b": "二两", "fold": 0.667} in gz["dose_changes"]  # drugs compared by family (桂枝 → 桂)
    gm = pair_of(r, "桂枝汤", "麻黄汤")
    assert gm["verdict"] == "异方" and gm["shared"] == ["桂", "甘草"] and gm["jaccard"] == 0.286
    guizhi = next(f for f in r["formulas"] if f["name"] == "桂枝汤")
    ratios = {d["drug"]: d["ratio"] for d in guizhi["drugs"]}
    assert ratios["桂"] == ratios["芍药"] == 1.0 and ratios["甘草"] == 0.667 and ratios["大枣"] is None  # 枚: no weight
    kinds = {c["id"]: c for c in r["charts"]}
    assert kinds["compare-similarity"]["type"] == "heatmap" and len(kinds["compare-similarity"]["rows"]) == 9
    assert "不构成任何用药剂量建议" in kinds["compare-ratios"]["note"] and kinds["compare-ratios"]["note"].startswith("图中剂量")
    baihu = pair_of(study.compare(["白虎汤", "白虎加人参汤"]), "白虎汤", "白虎加人参汤")
    assert baihu["verdict"] == "加减化裁" and baihu["only_b"] == ["人参"] and baihu["dose_changes"] == []
    with pytest.raises(ValueError):
        study.compare(["桂枝汤", "桂枝汤"])


def test_family_finds_the_formulas_made_from_a_base(study):
    r = study.family("白虎汤")
    assert r["formula"]["core"] == ["甘草", "知母", "石膏", "粳米"]
    member = r["members"][0]
    assert (member["formula"], member["relation"], member["added"], member["removed"]) == ("白虎加人参汤", "加味", ["人参"], [])
    assert member["works"] == 4 and member["earliest"]["book_id"] in ("shl", "jk")  # 伤寒论, 金匮, 千金, 医宗金鉴: one each
    g = study.family("桂枝汤")
    assert set(g["formula"]["core"]) == {"大枣", "桂", "甘草", "芍药", "生姜"} and g["formula"]["works"] == 4  # 局方 writes 3 of them
    gegen = next(m for m in g["members"] if m["formula"] == "葛根汤")
    assert gegen["relation"] == "加味" and gegen["added"] == ["葛根", "麻黄"] and gegen["works"] == 2
    timeline, network = (next(c for c in g["charts"] if c["type"] == t) for t in ("timeline", "network"))
    assert timeline["groups"] == network["groups"] == charts.RELATIONS  # one colour per relation in every chart
    assert {n["group"] for n in network["nodes"]} >= {"本方", "加味"}
    assert study.family("四逆汤")["members"] == []  # its core is written out; nothing is made from it here
    with pytest.raises(ValueError):
        study.family("五味消毒饮")  # no written-out composition


# ------------------------------------------------------------------ 用药谱 · 药性谱
def test_prepared_form_reads_the_preparation_after_the_drugs():
    assert prepared_form("右为粗末，每服三钱，生姜三片，枣一枚，同煎。") == "煮散"  # a 宋 汤 boiled by the spoonful
    assert prepared_form("右为细末，炼蜜为圆，如鸡子黄大。") == "丸剂"
    assert prepared_form("右五味，捣为散，以白饮和服方寸匕") == "散剂"
    assert prepared_form("右五味，以水七升，微火煮取三升") == "汤剂"
    assert prepared_form("") == ""


def test_usage_counts_per_work_and_compares_the_doses_of_decoctions(study):
    r = study.usage("甘草")
    assert r["with"] == r["compositions"] - 1  # 五苓散 alone writes no 甘草
    han = next(p for p in r["by_period"] if p["period"] == "先秦两汉")
    assert (han["with"], han["compositions"]) == (10, 11) and han["ci"][0] < 0.9 < han["ci"][1]
    doses = r["doses"]
    assert doses["form"] == "汤剂" and [p["period"] for p in doses["by_period"]] == ["先秦两汉", "隋唐五代", "清"]
    assert doses["by_period"][0]["liang"]["median"] == 2.0 and doses["by_period"][0]["common"][0] == {"dose": "二两", "count": 7}
    forms = {f["form"]: f["n"] for f in doses["by_form"]}
    assert forms.get("煮散") == 1 and forms.get("丸剂") == 1  # 局方's 桂枝汤 (为粗末，每服) and 理中丸: their batch, apart
    assert r["processing"]["top"][0]["note"] == "炙"
    assert {p["with"] for p in r["partners"]} >= {"大枣", "生姜", "人参"}
    assert {c["type"] for c in r["charts"]} == {"line", "box", "scatter", "stack", "hbar"}
    with pytest.raises(ValueError):
        study.usage("不是药")


def test_properties_profile_natures_flavours_and_channels(study):
    r = study.properties(["黄连", "黄芩", "甘草"])
    d = {x["drug"]: x for x in r["drugs"]}
    assert d["黄连"]["natures"] == {"寒": 1.0} and d["黄连"]["channels"] == {"心": 0.5}
    assert d["黄连"]["first"]["归经"]["passage_id"] == "tyb.huanglian" and d["黄连"]["first"]["归经"]["value"] == "手少阴"
    assert d["黄芩"]["flavors"] == {"苦": 1.0, "甘": 0.5}  # 味微苦而甘
    assert set(d["甘草"]["channels"]) == {"肝", "脾", "肾"}  # 入足厥阴、太阴、少阴经: the foot carries over
    assert {c["type"] for c in r["charts"]} == {"heatmap", "stack"}
    f = study.properties(formula="小柴胡汤")
    assert f["formula"] == "小柴胡汤" and {x["drug"] for x in f["drugs"]} >= {"柴胡", "黄芩", "人参", "半夏", "甘草"}


def test_channel_statements_and_formal_numerals():
    assert channel_tokens("足厥阴、太阴、少阴") == ["足厥阴", "足太阴", "足少阴"]
    assert channel_tokens("手足太阴") == ["手太阴", "足太阴"]
    assert channel_tokens("太阴、肺") == ["肺"]  # a bare 太阴 with no hand or foot before it says nothing
    assert (cn_number("陆"), cn_number("拾伍"), cn_number("叁"), cn_number("乙")) == (6, 15, 3, 1)


# ------------------------------------------------------------------ 配伍禁忌
def test_incompat_reads_statements_verses_and_formulas_that_write_a_pair(study):
    r = study.incompat("甘草")
    stated = {s["pair"]: s for s in r["statements"]["pairs"]}
    assert set(stated) == {"甘草反大戟", "甘草反芫花", "甘草反甘遂", "甘草反海藻"}
    first = stated["甘草反甘遂"]["earliest"]
    assert first["passage_id"] == "zl.gancao" and first["quote"] == "术、干漆、苦参为之使，恶远志，反大戟、芫花、甘遂、海藻。"
    together = next(f for f in r["formulas"]["pairs"] if f["pair"] == "甘草反甘遂")
    assert together["works"] == 1 and together["formulas"] == [{"formula": "甘遂半夏汤", "works": 1}]  # read with lexicon-core
    assert r["verses"] == []  # the verses are for the rules as a whole
    whole = study.incompat()
    shibafan = next(v for v in whole["verses"] if v["rule"] == "十八反")
    assert shibafan["works"] == 1 and shibafan["earliest"]["passage_id"] == "rm.1"
    assert "藜芦反人参" in {s["pair"] for s in whole["statements"]["pairs"]}  # 人参……反藜芦: the entry's drug is the subject
    check = study.incompat(drugs=["甘草", "甘遂", "人参", "藜芦"])["check"]
    assert {f["pair"] for f in check["flagged"]} == {"甘草反甘遂", "藜芦反人参"}
    lizhong = study.incompat("理中丸")["check"]
    assert lizhong["found"] and lizhong["flagged"] == [] and lizhong["drugs"] == ["人参", "干姜", "甘草", "白术"]
    with pytest.raises(ValueError):
        study.incompat("不是药")


# ------------------------------------------------------------------ 研究方案
def test_protocol_turns_a_question_into_a_protocol_with_testable_hypotheses(study):
    r = study.protocol("白虎汤与白虎加人参汤的组成和剂量在宋代以前与以后有何不同？")
    assert [k["id"] for k in r["kinds"]][:2] == ["origin", "compare"]
    assert r["entities"]["formulas"] == ["白虎汤", "白虎加人参汤"] and r["entities"]["period"]["split"] == 960
    ids = [h["id"] for h in r["hypotheses"]]
    assert ids == [f"H{i}" for i in range(1, len(ids) + 1)]
    for h in r["hypotheses"]:
        assert h["statement"] and h["prediction"] and h["test"] and h["falsified_if"] and h["alternatives"]
    assert any(h["statement"] == "白虎加人参汤即白虎汤加人参（加味），其余药味与白虎汤相同" for h in r["hypotheses"])  # read off the names
    assert all(m["tool"].startswith("study.") or m["tool"].startswith("taochronos") for m in r["methods"])
    assert all(m["command"].startswith("taochronos ") for m in r["methods"])
    assert set(r["contract"]["focus_terms"]) >= {"白虎汤", "白虎加人参汤"}
    assert r["pilot"]["ran"] and r["pilot"]["findings"] and r["charts"]
    background = [b for b in r["background"] if b.get("passage_id")]
    assert background and all(study.corpus.has_passage(b["passage_id"]) for b in background)  # cites witnesses, never memory
    page = markdown("protocol", r, study.signature())
    assert page.startswith("# 白虎汤") and "证伪条件" in page and "taochronos study compare 白虎汤 白虎加人参汤" in page
    doc = r["document"]  # the protocol as a file to download: the page, its sections numbered as they come
    assert doc["name"] == f"{r['title']}.md" and doc["format"] == "markdown" and doc["text"].startswith("# 白虎汤")
    assert "## 一、研究背景" in doc["text"] and "## 二、研究目标" in doc["text"]
    raised = study.protocol("桂枝汤与桂枝加桂汤的组成与剂量有何异同？", pilot=False)  # 加 the drug the base is named after
    assert "桂枝加桂汤即桂枝汤加重桂之量（同药异量），药味与桂枝汤相同" in [h["statement"] for h in raised["hypotheses"]]
    quiet = study.protocol("半夏的用量与炮制历代如何变化？", pilot=False)
    assert [k["id"] for k in quiet["kinds"]][0] == "usage" and not quiet["pilot"]["ran"] and "charts" not in quiet
    assert "## 一、研究目标" in quiet["document"]["text"]  # no background without a pilot: the numbering does not skip


# ------------------------------------------------------------------ charts
def _all_charts(study) -> list[dict]:
    out = []
    for r in (study.compare(["桂枝汤", "葛根汤"]), study.family("白虎汤"), study.usage("甘草"), study.properties(["黄连", "甘草"]),
              study.incompat("甘草"), study.formula("桂枝汤"), study.herb("甘草")):
        out += r.get("charts", [])
    return out


def test_every_chart_is_a_valid_specification_with_a_plain_source(study):
    found = _all_charts(study)
    assert {c["type"] for c in found} >= {"bar", "heatmap", "timeline", "network", "line", "box", "scatter", "stack", "hbar"}
    for c in found:
        assert c["version"] == charts.SPEC_VERSION and c["type"] in charts.TYPES and c["title"] and c["id"]
        rows = c.get("rows") or []
        assert rows or c.get("nodes"), c["id"]
        keys = set().union(*(r.keys() for r in rows)) if rows else set()
        assert {col["key"] for col in c["columns"]} <= keys, c["id"]
        for s in c.get("series", []):
            assert s["key"] in keys and s["label"], c["id"]
        # a figure leaves the platform: its source names the study in plain words, no inside name
        assert c["source"].startswith("道乃久（TaoChronos）· ") and not any(w in c["source"] for w in ("usage", "compare", "study"))
        assert len([s for s in c.get("series", []) if s["label"] != "其他"]) <= charts.MAX_SERIES


def test_charts_are_drawn_as_svg_and_written_as_csv_and_json(study, tmp_path):
    found = _all_charts(study)
    written = svg.write(found, tmp_path, "t")
    assert len(written) == 3 * len(found) + 1  # and all of them as one figure in panels
    for path in map(Path, written):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".svg":
            root = ET.fromstring(text)
            assert root.tag.endswith("svg") and "var(--" not in text  # standalone: colours inline
        elif path.suffix == ".csv":
            assert text.startswith("﻿") and "\n" in text  # a byte-order mark for spreadsheet programs
        else:
            assert json.loads(text)["type"] in charts.TYPES
    # a group keeps its colour whichever groups a chart shows
    spec = {"groups": charts.RELATIONS}
    assert svg.group_colors(spec, ["加减"])["加减"] == svg.group_colors(spec, ["加味", "加减"])["加减"] == svg.PALETTE[2]
    # axes: counts have whole ticks, the top is never far above the data
    assert svg.ticks(0, 10, 4, integer=True) == [0, 5, 10] and svg.ticks(0, 2, integer=True) == [0, 1, 2]
    assert [svg.nice_max(v) for v in (7, 11, 55, 295)] == [8, 15, 60, 300]


def test_the_model_reads_which_charts_the_page_shows_never_their_data():
    from taochronos.chat.results import for_interface, for_model

    result = {"x": 1, "charts": [{"type": "bar", "title": "甲", "rows": [{"a": 1}] * 50}, {"type": "line", "title": "乙"}]}
    assert for_model(result) == {"x": 1, "charts_shown": ["甲", "乙"]}
    table = {"title": "丙", "columns": [{"key": "a", "label": "甲"}], "rows": [{"a": "1"}] * 50}
    assert for_model({"x": 1, "tables": [table], "_raw": {"grams": [1.0] * 900}}) == {"x": 1, "tables_shown": ["丙"]}  # never the raw values
    assert for_model({"x": 1}) == {"x": 1}
    document = {"name": "方案.md", "format": "markdown", "text": "# 方案\n" + "正文" * 3000}
    assert for_model({"x": 1, "document": document}) == {"x": 1}  # the document is for the page: the model has its result
    big = {"rows": ["长" * 500] * 400, "charts": result["charts"], "document": document}
    shown = for_interface(big, max_chars=30000)
    assert shown["charts"] == result["charts"] and shown["document"] == document and len(shown["rows"]) < 400  # trimmed, but not these


# ------------------------------------------------------------------ tools and CLI (the demonstration corpus)
def test_the_new_studies_through_the_scheduler(harness):
    call = lambda tool, **a: harness.scheduler.execute(ToolCall(tool, a), actor=Actor.kernel())  # noqa: E731
    out = call("study.compare", formulas=["桂枝汤", "麻黄汤"])
    assert out.ok and out.result["summary"]["found"] == 2 and out.result["charts"]  # 伤寒论's entries headed 桂枝汤方
    out = call("study.usage", herb="甘草")
    assert out.ok and out.result["with"] > 0
    out = call("study.properties", herbs=["黄连", "人参"])
    assert out.ok and len(out.result["drugs"]) == 2
    out = call("study.incompat", herbs=["甘草", "海藻"])
    assert out.ok and out.result["check"]["flagged"][0]["pair"] == "甘草反海藻"
    out = call("study.protocol", question="桂枝汤的组成在宋代以前与以后有何变化？", pilot=False)
    assert out.ok and out.result["hypotheses"] and out.result["contract"]["focus_terms"]
    assert out.result["document"]["text"].startswith("# 桂枝汤") and len(out.result["document"]["text"]) > 2000  # never shortened
    out = call("study.protocol", question="桂枝汤与桂枝加桂汤的组成与剂量有何异同？", pilot=False)  # a name the lexicon lacks
    ent = out.result["entities"]
    assert (ent["formulas"], ent["unlisted"], ent["herbs"]) == (["桂枝汤", "桂枝加桂汤"], ["桂枝加桂汤"], [])  # not 桂枝 the drug
    assert out.result["limitations"][0].startswith("桂枝加桂汤不在本系统词表中")
    assert not call("study.compare", formulas=["桂枝汤"]).ok


def test_cli_compare_writes_its_figures(capsys, tmp_path):
    figures = tmp_path / "figures"
    assert main(["--data", str(tmp_path), "study", "compare", "桂枝汤", "麻黄汤", "--charts", str(figures)]) == 0
    out = capsys.readouterr()
    suffixes = sorted(p.suffix for p in figures.iterdir())
    assert out.out.startswith("# 方剂比较") and suffixes.count(".svg") == 3 and suffixes.count(".docx") == 1 and ".tex" in suffixes
    assert main(["--data", str(tmp_path), "study", "protocol", "桂枝汤的源流", "--no-pilot"]) == 0
    assert capsys.readouterr().out.startswith("# 桂枝汤")


# ------------------------------------------------------------------ figures and tables for a paper
def test_the_studies_print_three_line_tables_with_their_statistics(study):
    u = study.usage("甘草")
    assert "_raw" not in u  # the doses the figures draw one by one are taken out once drawn
    t = {x["id"]: x for x in u["tables"]}
    assert list(t) == ["usage-periods", "usage-doses", "usage-forms", "usage-partners"]
    first = t["usage-periods"]["rows"][0]
    assert first["period"] == "先秦两汉" and first["with"] == "10 (90.9)" and first["ci"] == "62.3–98.4"  # n (%), the Wilson CI
    doses = t["usage-doses"]
    assert [c.get("group") for c in doses["columns"]][2:6] == ["原书剂量（两）", "折合克数（g）", "折合克数（g）", "折合克数（g）"]
    assert doses["rows"][0]["grams"] == "29.4 (29.4, 29.4)" and doses["rows"][0]["mean"] == "29.4 ± 7.3"  # M (P25, P75); x̄ ± s
    assert any("Kruskal–Wallis" in n and "H = " in n for n in doses["notes"]) and any("Spearman" in n for n in doses["notes"])
    assert u["doses"]["test"]["name"] == "Kruskal–Wallis" and u["doses"]["trend"]["n"] == 14
    assert all(x["source"].startswith("道乃久（TaoChronos）· ") for x in u["tables"])
    p = study.pairs("甘草")
    partner = p["partners"][0]
    assert partner["or"] == 2.43 and partner["or_ci"] == [0.0873, 67.6]  # the odds ratio with its Woolf interval
    row = p["tables"][0]["rows"][0]
    assert row["or"] == "2.43 (0.09–67.6)" and row["p"] == "0.58"  # not significant: no star
    corpus = study.pairs(min_support=2)
    ids = [x["id"] for x in corpus["tables"]]
    assert ids == ["pairs-frequency", "pairs-rules", "pairs-top", "pairs-clusters"]
    assert corpus["frequency"][0] == {"drug": "甘草", "compositions": 18, "share": 0.9474}
    assert {"if": "知母", "then": "石膏", "support": 5, "support_share": 0.2632, "confidence": 1.0, "lift": 3.8} in corpus["rules"]
    groups = [set(c["drugs"]) for c in corpus["clusters"]]
    assert {"石膏", "粳米", "知母"} <= groups[0] and {"半夏", "黄芩", "柴胡"} in groups  # 白虎汤's drugs hold together, and 小柴胡汤's
    for r in (study.compare(["桂枝汤", "麻黄汤"]), study.family("桂枝汤"), study.term("伤寒"), study.herb("甘草"),
              study.properties(["黄连", "黄芩"]), study.incompat(), study.formula("桂枝汤")):
        assert r["tables"] and all(x["version"] == tables.TABLE_VERSION and x["rows"] and x["columns"] for x in r["tables"])


def test_the_new_figures_box_forest_scatter_and_dendrogram(study):
    u = study.usage("甘草")
    box = next(c for c in u["charts"] if c["type"] == "box")
    assert box["rows"][0]["median"] == 29.4 and box["rows"][0]["lo"] == 29.4 and set(box["points"]["先秦两汉"]) >= {14.7, 44.1}  # the outliers kept
    scatter = next(c for c in u["charts"] if c["type"] == "scatter")
    assert len(scatter["rows"]) == 14 and scatter["fit"]["label"] == "LOESS" and "Spearman ρ = 0.54" in scatter["subtitle"]
    forest = next(c for c in study.pairs("甘草")["charts"] if c["type"] == "forest")
    assert forest["x"] == {"label": "OR（95% CI）", "log": True, "ref": 1} and forest["rows"][0]["lo"] == 0.0873
    tree = next(c for c in study.pairs(min_support=2)["charts"] if c["type"] == "dendrogram")
    n = len(tree["labels"])
    assert len(tree["merges"]) == n - 1 and sorted(tree["order"]) == list(range(n)) and tree["groups"][0] == "第 1 类"
    # a box from its values alone (as a model may write one), drawn in both styles
    spec = {"type": "box", "title": "甲", "x": {"key": "期", "label": "时期"}, "y": {"label": "克"}, "rows": [{"期": "汉", "values": [1, 2, 3, 4, 50]}]}
    assert svg.box_rows(spec)[0]["hi"] == 4  # 50 is past the whisker
    for c in (spec, box, scatter, forest, tree):
        for style in ("journal", "screen"):
            ET.fromstring(svg.to_svg(c, style=style, number=3))


def test_journal_figures_and_a_figure_in_panels(study):
    found = study.usage("甘草")["charts"]
    paper = svg.to_svg(found[0], number=2, width="single")
    root = ET.fromstring(paper)
    assert root.get("width") == "85mm" and root.get("height").endswith("mm") and "var(--" not in paper
    assert "图2" in paper and "甘草：含此药的组成占比" in paper and "#ffffff" in paper  # its number and caption under it, on white
    assert "图2" not in svg.to_svg(found[0], caption=False)  # for a journal's own caption
    screen = svg.to_svg(found[0], style="screen")
    assert ET.fromstring(screen).get("width") == "760" and "图" not in screen.split("</title>")[1][:200]  # the page's figure: its title above
    panels = svg.to_panels(found, number=1)
    assert ET.fromstring(panels).get("width") == "175mm" and "（A）含此药的组成占比" in panels and "（E）" in panels
    assert panels.count("图中剂量为历史计量换算的学术估值") == 1  # a note the panels share, once


def test_tables_as_word_latex_html_markdown_and_csv(study, tmp_path):
    import zipfile

    found = study.usage("甘草")["tables"]
    doses = next(t for t in found if t["id"] == "usage-doses")
    with zipfile.ZipFile(__import__("io").BytesIO(tablefmt.to_docx(found))) as z:
        assert set(z.namelist()) >= {"[Content_Types].xml", "word/document.xml", "word/styles.xml"}
        root = ET.fromstring(z.read("word/document.xml"))
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    assert len(root.findall(f".//{w}tbl")) == 4
    first = root.find(f".//{w}tbl")
    borders = first.find(f"{w}tblPr/{w}tblBorders")
    assert borders.find(f"{w}top").get(f"{w}sz") == "12" and borders.find(f"{w}insideV").get(f"{w}val") == "nil"  # three lines, no grid
    text = "".join(t.text or "" for t in root.iter(f"{w}t"))
    assert "表1　各时期写出组成中含甘草的比例" in text and "注：CI：置信区间" in text
    grouped = root.findall(f".//{w}tbl")[1]
    assert grouped.find(f".//{w}gridSpan") is not None and grouped.find(f".//{w}vMerge") is not None and grouped.find(f".//{w}tblHeader") is not None
    assert any(r.find(f"{w}rPr/{w}i") is not None and r.find(f"{w}t").text == "P" for r in root.iter(f"{w}r"))  # P in italics
    latex = tablefmt.to_latex(doses, 2)
    for piece in (r"\caption{历代汤剂中甘草的用量}", r"\toprule", r"\cmidrule(lr){4-6}", r"\multirow{2}{*}{时期}", r"$\bar{x}$", r"\bottomrule"):
        assert piece in latex, piece
    assert tablefmt.tex("50% & a_b ~") == r"50\% \& a\_b \textasciitilde{}"
    html = tablefmt.to_html(doses, 2)
    assert "border-top:1.5pt solid #000" in html and 'colspan="3"' in html and "<i>P</i>" in html
    md = tablefmt.to_markdown(doses, 2)
    assert md.startswith("**表2　历代汤剂中甘草的用量**") and "| 时期 | n | 原书剂量（两） · M (P25, P75) |" in md
    csv_text = tablefmt.to_csv(doses)
    assert csv_text.startswith("\ufeff时期,n,") and '"29.4 (29.4, 29.4)"' in csv_text
    formulas = {"id": "x", "title": "甲", "columns": [{"key": "a", "label": "a", "align": "left"}],
                "rows": [{"a": "=HYPERLINK(1)"}, {"a": "-0.5"}, {"a": "@SUM(1)"}]}
    assert tablefmt.to_csv(formulas, bom=False) == "a\r\n'=HYPERLINK(1)\r\n-0.5\r\n'@SUM(1)\r\n"  # a formula stays text, a number a number
    quoted = {"type": "bar", "title": '他说"好"', "x": {"key": "a"}, "series": [{"key": "b", "label": "b"}], "rows": [{"a": "=1", "b": 2}]}
    assert ET.fromstring(svg.to_svg(quoted)).get("aria-label") == '他说"好"' and "'=1" in svg.to_csv(quoted)
    written = tablefmt.write(found, tmp_path, "t")
    assert sorted(Path(x).suffix for x in written).count(".tex") == 4 and (tmp_path / "t-tables.docx").exists()


def test_the_protocol_plans_its_figures_and_its_table_shells(study):
    r = study.protocol("半夏的用量与配伍历代如何变化？", pilot=False)
    forms = {f["chart"]: f["form"] for f in r["figures"]}
    assert forms["usage-doses"] == "Tukey 箱线图" and forms["pairs-forest"] == "森林图" and r["figures"][0]["number"] == 1
    shells = r["table_shells"]
    assert [t["number"] for t in shells] == [1, 2, 3] and shells[2]["cells"][5] == "×.×× (×.××–×.××)"
    assert [t["title"] for t in r["tables"]] == [f"{t['title']}（模板）" for t in shells]  # the page prints them, to download as Word
    assert r["tables"][1]["columns"][2]["group"] == "折合克数（g）"
    doc = r["document"]["text"]
    assert "图表计划" in doc and "**图2**　半夏历代汤剂用量（Tukey 箱线图；study.usage）" in doc
    assert "**表1　各时期写出组成中含半夏的比例（模板）**" in doc and "| 先秦两汉 | ×× | ×× (××.×) | ××.×–××.× |" in doc
