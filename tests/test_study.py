"""治学 — the study layer over a synthetic corpus (tests/fixtures/study): concordance with a collation apparatus,
formula provenance (heading-only entries, taboo forms, shared doses, verses), materia-medica histories, term
histories, taboo dating, citations, learning cards, reading paths, datasets, the study tools, the CLI and the Scholar."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from conftest import make_harness, run_research

from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.base import dated, wilson
from taochronos.plugins.classics.study.dataset import write_datapackage
from taochronos.plugins.classics.study.render import markdown

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "study")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


# ------------------------------------------------------------------ helpers
def test_dating_prefers_the_latest_possible_date():
    # a book dated only by its dynasty (宋 960–1279) does not come before one dated to a reign (1107–1151)
    assert sorted([[960, 1279], [1107, 1151], None], key=dated) == [[1107, 1151], [960, 1279], None]
    lo, hi = wilson(5, 100)
    assert 0 < lo < 0.05 < hi < 0.12


# ------------------------------------------------------------------ 经文互见·集注
def test_concordance_separates_copies_quotations_and_collates(study):
    r = study.concordance("太阳病，头痛，发热，汗出，恶风，桂枝汤主之。")
    relations = {h["book_id"]: h["relation"] for h in r["hits"]}
    assert relations["shl"] == relations["shl_b"] == "同书异本" and relations["qjy"] == "引文"
    assert r["base"]["book_id"] in ("shl", "shl_b") and r["summary"]["works"] == 2
    extra = [a for a in r["apparatus"] if a["kind"] == "衍"]
    assert extra and extra[0]["reading"] == "者" and extra[0]["witnesses"] == ["伤寒论（别本）"]


# ------------------------------------------------------------------ 方源考
def test_formula_provenance_groups_witnesses_and_reads_doses(study):
    r = study.formula("桂枝汤")
    assert r["earliest"]["passage_id"] == "shl.12f"
    main_group = r["groups"][0]
    assert main_group["relation"] == "原方·通行方" and main_group["witnesses"] == 2  # 伤寒论 and 千金翼方 (各三两)
    assert any(g["relation"] == "孤例" for g in r["groups"])  # 局方's three-drug 桂枝汤
    first = {i["surface"]: i for i in r["earliest"]["ingredients"]}
    assert first["桂枝"]["dose"] == "三两" and first["桂枝"]["processing"] == "去皮" and "秦汉制" in first["桂枝"]["reading"]
    qjy = next(w for w in r["witnesses"] if w["book_id"] == "qjy")
    assert {i["surface"]: i["dose"] for i in qjy["ingredients"]}["芍药"] == "三两"  # the shared dose (各三两) is distributed
    assert r["songs"] and r["songs"][0]["book_id"] == "tt" and "芍药甘草姜枣同" in r["songs"][0]["quote"]
    assert "不构成任何用药剂量建议" in r["metrology_notice"]


def test_formula_notes_without_brackets_share_the_dose(study):
    r = study.formula("小柴胡汤")
    items = {i["surface"]: i for i in r["earliest"]["ingredients"]}
    assert items["甘草"]["dose"] == items["生姜"]["dose"] == "三两"  # 甘草炙　生姜切，各三两
    assert items["甘草"]["processing"] == "炙" and items["半夏"]["processing"] == "洗"
    assert r["ratios"][0]["ratio"]["柴胡"] == 1.0 and r["ratios"][0]["ratio"]["黄芩"] == 0.375


def test_formula_found_under_its_taboo_form_and_as_an_entry_heading(study):
    lizhong = study.formula("理中丸")
    assert lizhong["earliest"]["passage_id"] == "jf.1" and lizhong["earliest"]["name_form"] == "理中圆"
    assert any(f["form"] == "理中圆" and "丸→圆" in f["kind"] for f in lizhong["formula"]["forms"])
    liuwei = study.formula("六味地黄丸")  # 笈成 style: 地黄丸 / 治…… / 熟地黄八钱…… / 上为末……
    w = liuwei["earliest"]
    assert w["passage_id"] == "xe.2" and w["quote"].startswith("〔地黄丸〕")
    assert [i["surface"] for i in w["ingredients"]][:3] == ["熟地黄", "山萸肉", "干山药"]
    assert w["indication"].startswith("治肾怯失音") and w["preparation"].startswith("上为末")


# ------------------------------------------------------------------ 药性源流
def test_herb_history_finds_the_first_statement_of_each_property(study):
    r = study.herb("附子")
    assert [e["book_id"] for e in r["entries"]] == ["bj", "tyb"]
    firsts = {(f["field"], f["value"]): f["passage_id"] for f in r["firsts"]}
    assert firsts[("药性", "温")] == "bj.fuzi" and firsts[("毒性", "大毒")] == "tyb.fuzi"
    assert firsts[("归经", "手少阳")] == "tyb.fuzi"  # 归经 is a Jin–Yuan doctrine: absent from the 本经
    shanyao = study.herb("山药")  # 署豫 (本经) → 山药 (汤液本草): the names change, the drug is one
    assert [e["book_id"] for e in shanyao["entries"]] == ["bj", "tyb"]


# ------------------------------------------------------------------ 术语源流
def test_term_history_counts_shares_by_period(study):
    r = study.term("消渴")
    rows = {row["id"]: row for row in r["periods"]}
    assert all(row["total"] >= row["passages"] for row in rows.values())
    early = next(row for row in r["periods"] if row["passages"])
    assert early["ci_per_10k"][0] <= early["per_10k"] <= early["ci_per_10k"][1]
    assert r["earliest"][0]["passage_id"] == "shl.71"
    assert "比例而非绝对数" in r["notice"]


# ------------------------------------------------------------------ 避讳断代
def test_taboo_dates_editions(study):
    tang = {v["rule"]: v for v in study.taboo("qjy")["rules"]}
    assert tang["tang_gaozong_zhi"]["verdict"] == "避讳" and tang["tang_gaozong_zhi"]["substitute"] == 4
    song = study.taboo("jf")
    assert {v["rule"]: v["verdict"] for v in song["rules"]}["song_yingzong_shu"] == "避讳" and song["edition_floor"] == 1063
    qing = {v["rule"]: v["verdict"] for v in study.taboo("yz")["rules"]}
    assert qing["qing_kangxi_xuan"] == "避讳"  # 元参 for 玄参
    survey = study.taboo(min_chars=10)
    assert {b["book_id"] for b in survey["books"]} >= {"qjy", "jf", "yz"}


# ------------------------------------------------------------------ 引书与引人
def test_citations_resolve_books_and_physicians(study, tmp_path):
    r = study.citations()
    tang = next(p for p in r["periods"] if p["period"] == "隋唐五代")
    assert tang["books"][0]["title"] == "伤寒论" and tang["persons"][0]["name"] == "张机"
    reception = study.citations("张仲景")
    assert reception["person"]["id"] == "zhang_ji" and set(reception["by_period"]) == {"隋唐五代", "清"}
    assert reception["first"]["book_id"] == "qjy"


# ------------------------------------------------------------------ 学习
def test_cards_reading_path_and_anki(study):
    r = study.cards(book="伤寒论", formulas=["桂枝汤"], herbs=["附子"], term="消渴", limit=10)
    kinds = {c["type"] for c in r["cards"]}
    assert kinds == {"方证", "组成", "药性", "经文"}
    clause = next(c for c in r["cards"] if c["type"] == "方证")
    assert "〔　　〕主之" in clause["front"] and clause["back"] == "桂枝汤" and clause["passage_id"] == "shl.12"
    composition = next(c for c in r["cards"] if c["type"] == "组成")
    assert "桂枝三两（去皮）" in composition["back"] and "方歌" in composition["back"]
    assert r["anki_tsv"].startswith("#separator:tab\n#html:true\n#tags column:3\n") and r["anki_tsv"].count("\n") == r["count"] + 3
    path = study.reading("消渴")
    assert path["stages"][0]["stage"] == "源头经典" and path["stages"][0]["books"][0]["book_id"] == "shl"


# ------------------------------------------------------------------ 数据集
def test_dataset_is_a_frictionless_package_with_provenance(study, tmp_path):
    d = study.dataset(formulas=["桂枝汤"], herbs=["附子"], terms=["消渴"], citations=True)
    assert set(d["tables"]) == {"formula_witnesses", "formula_ingredients", "herb_entries", "term_periods", "citation_edges"}
    groups = {row["passage_id"]: row["group"] for row in d["tables"]["formula_witnesses"]}
    assert groups["shl.12f"] == groups["qjy.2"] == "原方·通行方"  # every witness carries its group
    pkg = write_datapackage(tmp_path / "ds", d["tables"], name="t", title="t", signature=d["signature"], licenses=d["licenses"],
                            notice=d["notice"])
    assert pkg["profile"] == "tabular-data-package" and json.loads((tmp_path / "ds" / "datapackage.json").read_text())["name"] == "t"
    with open(tmp_path / "ds" / "formula_ingredients.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    gz = next(r for r in rows if r["passage_id"] == "shl.12f" and r["herb"] == "桂枝")
    assert gz["dose"] == "三两" and float(gz["grams_low"]) == 41.4
    assert all(len(r["quote"]) <= 120 for r in d["tables"]["formula_witnesses"])  # short quotes, never the texts


def test_markdown_pages_carry_sources_and_notices(study):
    page = markdown("formula", study.formula("桂枝汤"), study.signature(), "剂量说明")
    assert page.startswith("# 方源考：桂枝汤") and "`shl.12f`" in page and "> 剂量说明" in page and "规则抽取属机器阅读" in page
    for kind, result in (("herb", study.herb("附子")), ("term", study.term("消渴")), ("taboo", study.taboo("qjy")),
                         ("citations", study.citations()), ("reading", study.reading("消渴"))):
        assert markdown(kind, result, study.signature()).startswith("# ")


# ------------------------------------------------------------------ tools, CLI, agent
def test_study_tools_through_the_scheduler(harness):
    call = lambda tool, **a: harness.scheduler.execute(ToolCall(tool, a), actor=Actor.kernel())  # noqa: E731
    out = call("study.metrology", dose="三两", year=200)
    assert out.ok and out.result["reading"]["grams"] == [41.4, 46.8]
    out = call("study.formula", name="六味地黄丸")
    assert out.ok and out.result["earliest"]["book_id"] == "xiaoer"
    out = call("study.term", term="消渴", items=3)
    assert out.ok and len(out.result["periods"]) <= 4  # three rows and the count of the rest


def test_cli_study(capsys, tmp_path):
    assert main(["--data", str(tmp_path), "study", "metrology", "三两", "--year", "200"]) == 0
    assert "41.4–46.8克" in capsys.readouterr().out
    assert main(["--data", str(tmp_path), "study", "formula", "六味地黄丸"]) == 0
    assert capsys.readouterr().out.startswith("# 方源考：六味地黄丸")
    anki = tmp_path / "cards.tsv"
    assert main(["--data", str(tmp_path), "study", "cards", "--herb", "黄连", "--anki", str(anki)]) == 0
    assert anki.read_text(encoding="utf-8").startswith("#separator:tab")
    capsys.readouterr()
    assert main(["--data", str(tmp_path), "study", "dataset", "--term", "消渴", "-o", str(tmp_path / "ds")]) == 0
    assert json.loads(capsys.readouterr().out)["resources"]["term_periods"] == 7


def test_scholar_writes_a_sources_dossier(tmp_path):
    h = make_harness(tmp_path, overrides={"discovery": {"sources_dossier": {"max_targets": 3}}})
    session = run_research(h, "scholar", focus_terms=["消渴", "六味地黄丸", "黄连"], stop={"max_rounds": 1})
    dossiers = {a["result"]["target"]: a["result"] for a in session.state.analyses.values() if a.get("kind") == "sources_dossier"}
    assert set(dossiers) == {"消渴", "六味地黄丸", "黄连"}  # a term, a formula and a drug
    assert {d["kind"] for d in dossiers.values()} == {"term", "formula", "herb"}
    assert dossiers["六味地黄丸"]["witnesses"][0]["role"] == "原方"
    assert all(h.corpus.has_passage(w["passage_id"]) for d in dossiers.values() for w in d["witnesses"])
    from taochronos.engine.report import build

    _, md, _ = build(h, session.state, session.id)
    assert "附录 · 源流考证" in md
