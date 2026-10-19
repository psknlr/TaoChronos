"""医案探索 — the case records of many collections searched, matched, compared and read (tests/fixtures/cases, a
synthetic corpus): earlier physicians' treatment read apart, the physician of a compilation's case, 医案检索 with its
facets, 类案, 医案详解, 医家与时代比较, 随证加减, 同病异治 · 异病同治, the cases as a data package, the science underneath,
and the tools and commands that offer them."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.dataset import write_datapackage
from taochronos.plugins.classics.study.render import markdown
from taochronos.science.trajectories import cross_associations, group_contrasts, idf_weights, weighted_cosine

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "cases")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def _case(study: StudyService, **patient: str):
    return next(c for c in study._cases.pool() if all(c.patient.get(k) == v for k, v in patient.items()))


# ------------------------------------------------------------------ reading: earlier physicians, physicians, names
def test_an_earlier_physicians_treatment_is_read_apart(study):
    cs = study._cases
    rows = [("p1", "咳嗽", "郑　七十岁　咳嗽，喘，脉微。前医作伤寒治，用麻黄汤，汗出不止，病势危笃。予以独参汤，不应，遂死。"),
            ("p2", "腹胀", "一男子年三十，腹胀，医以大黄、巴豆下之，增剧。脉沉细，予以理中汤，连进二帖而安。")]
    zheng, man = cs.parse_rows(rows, "demo")
    v = zheng.visits[0]
    assert v.formulas == ["独参汤"] and v.prior == {"diagnosis": ["伤寒"], "formulas": ["麻黄汤"]}
    assert v.prior_response == "worse" and v.response == "died" and "伤寒" not in v.diagnosis  # the earlier diagnosis is not this one
    assert v.prior_words == ["前医作"] and v.prior_quote.startswith("前医作伤寒治")
    w = man.visits[0]
    assert w.formulas == ["理中汤"] and w.prior["herbs"] == ["大黄", "巴豆"] and w.prior_response == "worse" and w.response == "improved"


def test_warnings_maxims_and_the_patients_own_course_are_no_accounts(study):
    cs = study._cases
    texts = ["某　中风，脉弦。若误作中风治之立毙。用参附汤，服之而安。",  # a warning
             "某　咳嗽，脉数。误治杀人多矣。用银翘散，服之而安。",  # a maxim, naming nothing
             "某　咳嗽，脉数。用银翘散。已服二剂，热退。",  # the patient's course under this physician
             "钱医治一人，疟，寒热往来，脉弦。用小柴胡汤，服三剂而愈。"]  # a compilation's own physician
    for text in texts:
        case = cs.parse_rows([("p", "x", text)], "demo")[0]
        assert not any(v.prior_words for v in case.visits), text
    qian = cs.parse_rows([("p", "x", texts[3])], "demo")[0]
    assert qian.physician == "钱医" and qian.visits[0].diagnosis == ["疟"] and not qian.patient.get("name")


def test_an_account_without_punctuation_ends_where_the_recording_physician_turns_back(study):
    text = "一妇或时遍身麻痹医作风治用乌药顺气散又用小续命汤病益甚邀予诊之脉濡缓用四君子汤而愈"
    v = study._cases.parse_rows([("p", "身麻", text)], "demo")[0].visits[0]
    assert set(v.prior["formulas"]) == {"乌药顺气散", "小续命汤"} and v.prior_response == "worse"
    assert v.formulas == ["四君子汤"] and v.response == "improved"


def test_the_physician_of_a_compilation_is_not_its_patient(study):
    ding = next(c for c in study._cases.pool() if c.physician == "丁翁" and c.patient.get("sex") == "female")
    assert ding.patient == {"sex": "female", "age": "四十"}  # 丁翁治一妇，年四十: 丁翁 treated, the woman was treated
    wu = [c for c in study._cases.pool() if c.physician == "武医"]
    assert len(wu) == 2 and not any(v.prior for c in wu for v in c.visits)  # 武医治… opens the case, not an account
    danxi = study._cases.parse_rows([("p", "恶阻", "丹溪治一妇，孕两月，呕吐，脉弦。以茯苓汤，五服而安。")], "demo")[0]
    assert danxi.physician == "丹溪" and study._explore.summary(danxi)["physician"] == "朱震亨"  # one physician, his names
    assert study._explore.person("叶天士") == study._explore.person("叶桂") == "叶桂"


def test_formula_names_are_read_whole_and_without_what_runs_into_them(study):
    cs = study._cases
    cases = cs.parse_rows([("a", "x", "某　发热，脉虚数。治宜甘寒，用竹叶石膏汤。"),
                           ("b", "y", "某　热成疳以大芦荟丸主之。仍用前方煎服而安。")], "demo")
    assert cases[0].visits[0].formulas == ["竹叶石膏汤"]  # 膏 is a suffix too; the name runs on to 汤
    assert cases[1].visits[0].formulas == ["大芦荟丸"]  # after the verb of giving; 前方煎 is no name


def test_each_book_is_read_once_and_a_case_keeps_its_id(study):
    pool = study._cases.pool()
    assert len(pool) == 18 and {c.book_id for c in pool} == {"jia", "yi", "bing"}  # the 方书 is no case collection
    by_disease = study._cases.cases(disease="咳嗽", limit=100)
    assert {c.id for c in by_disease} <= {c.id for c in pool} and len(by_disease) == 11
    assert study._cases.book_cases("jia") is study._cases.book_cases("jia")
    assert study._cases.find_case(pool[0].id) is pool[0] and study._cases.find_case("case_none") is None


# ------------------------------------------------------------------ 医案检索
def test_casefind_filters_every_facet_oldest_first(study):
    count = lambda **kw: study.casefind(**kw)["count"]  # noqa: E731
    assert count(disease="咳嗽") == 11 and count(findings=["脉浮数"]) == 6 and count(findings=["浮数"]) == 6
    assert count(findings=["咳嗽"]) == count(findings=["咳"])  # 咳嗽 is the lexicon's 咳, as the visits store it
    assert count(formula="理中汤") == count(formula="理中丸") == 3  # one formula under its other name
    assert count(outcome="死") == count(outcome="died") == 2 and count(disease="咳嗽", outcome="died") == 2
    assert count(sex="女") == 5 and count(age_min=60) == 2 and count(period="明") == 6 and count(after=1700) == 12
    assert count(prior=True) == 3 and count(physician="丁翁") == 2 and count(text="常山") == 1
    assert count(books=["丙编类案"]) == 5 and count(herb="杏仁") == 4 and count(principle="养阴") == 4
    r = study.casefind(disease="咳嗽", findings=["脉浮数"])
    assert [c["year"] for c in r["cases"]] == sorted(c["year"] for c in r["cases"])
    assert all("finding:脉浮数" in c["matched"] for c in r["cases"]) and r["scanned"] == 11
    facets = study.casefind(disease="咳嗽")["facets"]
    assert facets["formulas"][0] == ["银翘散", 6] and facets["periods"] == {"明": 4, "清": 7} and facets["prior"] == 1
    assert facets["period_outcomes"]["清"]["died"] == 1
    with pytest.raises(ValueError):
        study.casefind(period="汉魏")
    with pytest.raises(ValueError):
        study.casefind(books=["没有这部书"])


def test_casefind_draws_its_matches_by_period(study):
    r = study.casefind(disease="咳嗽")
    chart = next(c for c in r["charts"] if c["id"] == "casefind-periods")
    assert chart["type"] == "stack" and [row["group"] for row in chart["rows"]] == ["明", "清"]


# ------------------------------------------------------------------ 类案 and 医案详解
def test_similar_cases_share_the_rarest_findings_and_say_what_was_done(study):
    r = study.similar("发热，咳嗽，口渴，脉浮数")
    assert set(r["query"]["features"]) == {"症:发热", "症:咳", "症:渴", "脉:浮", "脉:数"}
    top = r["results"][0]
    assert set(top["shared"]) == set(r["query"]["features"]) and top["formulas"] == ["银翘散"]
    assert [x["score"] for x in r["results"]] == sorted((x["score"] for x in r["results"]), reverse=True)
    assert all(x["formulas"][:1] == ["银翘散"] for x in r["results"][:4])
    assert r["practice"]["formulas"][0]["name"] == "银翘散" and r["practice"]["formulas"][0]["outcomes"] == {"improved": 6}
    first = study.similar(case_id=top["id"])
    assert top["id"] not in {x["id"] for x in first["results"]}  # a case is not its own like case
    with pytest.raises(ValueError):
        study.similar()
    with pytest.raises(ValueError):
        study.similar(case_id="case_none")


def test_a_case_in_full_with_its_changes_as_stated_and_as_computed(study):
    qian = _case(study, name="钱")
    r = study.case(qian.id)
    assert [v["label"] for v in r["course"]] == ["第1诊", "第2诊"]
    assert r["course"][1]["computed_changes"] == {"added": ["杏仁"], "removed": ["薄荷"]}  # the drugs listed, compared
    assert [w["passage_id"] for w in r["witnesses"]] == ["yi.07", "yi.08"] and r["witnesses"][0]["license"] == "CC0-1.0"
    assert r["formulas_named"] == [{"name": "银翘散", "lexicon": "银翘散"}] and len(r["similar"]) == 5
    zheng = study.case(_case(study, name="郑").id)
    assert zheng["prior"] == {"diagnosis": ["伤寒"], "formulas": ["麻黄汤"]} and zheng["prior_response"] == "worse"
    with pytest.raises(ValueError):
        study.case("case_none")


# ------------------------------------------------------------------ 医家与时代比较
def test_groups_of_cases_compared_by_period_collection_and_physician(study):
    by_period = study.casecompare(by="period", min_cases=1)
    assert [(g["group"], g["cases"]) for g in by_period["groups"]] == [("明", 6), ("清", 12)]
    ming = by_period["groups"][0]
    assert ming["outcomes"] == {"improved": 5, "died": 1} and ming["improved_rate"] == round(5 / 6, 3)
    assert ming["improved_ci"][0] < ming["improved_rate"] < ming["improved_ci"][1]
    assert by_period["tests"]["outcome"]["df"] == 1 and by_period["tests"]["visits"] is not None
    qing = by_period["groups"][1]
    assert qing["distinctive"][0]["item"] == "方:小柴胡汤" and qing["distinctive"][0]["share"] == round(4 / 12, 3)
    assert {c["id"] for c in by_period["charts"]} >= {"casecompare-outcomes", "casecompare-improved"}
    assert by_period["tables"][0]["id"] == "casecompare-profile"
    by_book = study.casecompare(by="book", min_cases=1)
    assert [g["group"] for g in by_book["groups"]] == ["甲氏医案", "乙氏医案", "丙编类案"] and by_book["distances"]
    by_physician = study.casecompare(by="physician", min_cases=2)
    assert {g["group"]: g["cases"] for g in by_physician["groups"]} == {"甲医": 6, "乙医": 7, "丁翁": 2, "武医": 2}
    assert by_physician["left_out"] == {"纪生": 1}
    assert [g["group"] for g in study.casecompare(by="book", groups=["丙编类案"], min_cases=1)["groups"]] == ["丙编类案"]
    with pytest.raises(ValueError):
        study.casecompare(by="dynasty")


# ------------------------------------------------------------------ 随证加减
def test_modifications_tie_findings_to_the_drugs_added(study):
    r = study.modifications()
    assert r["visits"] == 5 and r["cases"] == 4 and r["added"][0] == ("杏仁", 3) and r["removed"] == [("薄荷", 1)]
    base = r["bases"][0]
    assert base["formula"] == "银翘散" and base["visits"] == 4 and base["added"][0] == ("杏仁", 3)
    assert any(a["left"] == "症:咳" and a["right"] == "杏仁" and a["count"] == 3 for a in r["finding_added"])
    assert study.modifications(formula="银翘散")["visits"] == 4 and study.modifications(formula="小柴胡汤")["visits"] == 1
    assert all(e["passage_id"] for e in r["examples"])


# ------------------------------------------------------------------ 同病异治 · 异病同治
def test_one_disease_treated_two_ways_and_what_sets_the_groups_apart(study):
    r = study.treatments("咳嗽")
    assert r["mode"] == "disease" and r["label"] == "同病异治" and r["left_out"] == 1  # 郑's 独参汤 — not 前医's 麻黄汤
    groups = {g["group"]: g for g in r["groups"]}
    assert {k: g["cases"] for k, g in groups.items()} == {"方:银翘散": 6, "方:沙参麦冬汤": 4}
    hot = {x["item"]: x for x in groups["方:银翘散"]["findings"]}
    dry = {x["item"]: x for x in groups["方:沙参麦冬汤"]["findings"]}
    assert hot["症:发热"]["significant"] and hot["脉:浮"]["significant"] and "症:口干" not in hot
    assert dry["症:口干"]["significant"] and dry["脉:细"]["significant"]
    assert {c["id"] for c in r["charts"]} == {"treatments-outcomes"}
    by_principle = study.treatments("咳嗽", by="principle", min_cases=2)
    assert by_principle["groups"][0]["group"] == "治法:养阴" and by_principle["groups"][0]["cases"] == 4


def test_one_formula_for_two_diseases_and_the_findings_they_share(study):
    r = study.treatments("小柴胡汤", min_cases=1)
    assert r["mode"] == "formula" and r["label"] == "异病同治"
    assert [(g["group"], g["cases"]) for g in r["groups"]] == [("证:疟", 3), ("证:伤寒", 1)]
    shared = {s["feature"]: s for s in r["shared"]}
    assert shared["症:口苦"]["groups"] == 2 and shared["脉:弦"]["share"] == 1.0 and shared["脉:弦"]["lift"] > 1
    with pytest.raises(ValueError):
        study.treatments("咳嗽", mode="herb")


# ------------------------------------------------------------------ 研究数据集
def test_cases_as_a_data_package(study, tmp_path):
    d = study.case_dataset(query={"disease": "咳嗽"})
    assert {k: len(v) for k, v in d["tables"].items()} == {"cases": 11, "case_visits": 17, "case_items": 93}
    kinds = {r["kind"] for r in d["tables"]["case_items"]}
    assert {"symptom", "pulse", "formula", "herb", "added", "removed", "prior_diagnosis", "prior_formula"} <= kinds
    zheng = next(r for r in d["tables"]["cases"] if r["patient_name"] == "郑")
    assert zheng["prior"] is True and zheng["age_years"] == 70 and zheng["outcome"] == "died" and zheng["physician"] == "乙医"
    pkg = write_datapackage(tmp_path / "ds", d["tables"], name="cases", title="cases", signature=d["signature"],
                            licenses=d["licenses"], notice=d["notice"])
    assert [r["name"] for r in pkg["resources"]] == ["cases", "case_visits", "case_items"]
    with open(tmp_path / "ds" / "cases.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 11 and rows[0]["case_id"].startswith("case_")
    assert len(study.case_dataset(book="bing")["tables"]["cases"]) == 5


# ------------------------------------------------------------------ pages
def test_every_exploration_has_its_page(study):
    sig = study.signature()
    zheng = _case(study, name="郑").id
    pages = {"casefind": study.casefind(disease="咳嗽", prior=True), "similar": study.similar("发热，咳嗽，脉浮数"),
             "case": study.case(zheng), "casecompare": study.casecompare(by="period", min_cases=1),
             "modifications": study.modifications(), "treatments": study.treatments("咳嗽")}
    heads = {"casefind": "# 医案检索", "similar": "# 类案", "case": "# 医案详解", "casecompare": "# 医家与时代比较",
             "modifications": "# 随证加减", "treatments": "# 同病异治"}
    for kind, result in pages.items():
        text = markdown(kind, result, sig)
        assert text.startswith(heads[kind]) and "语料指纹" in text, kind
    assert "前医所为：伤寒；麻黄汤（加重）" in markdown("case", pages["case"], sig)
    assert "| 清 | 乙医 | 乙氏医案·咳嗽 | 郑七十岁 |" in markdown("casefind", pages["casefind"], sig)


# ------------------------------------------------------------------ the science underneath
def test_rarity_weighted_similarity():
    sets = [{"a", "b"}, {"a", "c"}, {"a", "d"}, {"b", "x"}]
    idf = idf_weights(sets)
    assert idf["a"] < idf["b"] < idf["x"]
    assert weighted_cosine({"a", "x"}, {"b", "x"}, idf) > weighted_cosine({"a", "x"}, {"a", "b"}, idf)  # the rare one counts
    assert weighted_cosine({"a"}, {"a"}, idf) == pytest.approx(1.0) and weighted_cosine(set(), {"a"}, idf) == 0.0


def test_cross_associations_and_group_contrasts():
    units = [({"咳"}, {"杏仁"})] * 6 + [({"渴"}, {"麦冬"})] * 6 + [({"咳"}, set())]
    rows = {(r["left"], r["right"]): r for r in cross_associations(units, min_count=3)}
    assert rows[("咳", "杏仁")]["count"] == 6 and rows[("咳", "杏仁")]["significant"] and ("咳", "麦冬") not in rows
    groups = {"a": [{"x", "y"}] * 6, "b": [{"z"}] * 6}
    out = group_contrasts(groups, min_cases=3)
    assert [r["item"] for r in out["a"]] == ["x", "y"] and out["a"][0]["significant"] and out["a"][0]["share_elsewhere"] == 0.0
    assert [r["item"] for r in out["b"]] == ["z"]


# ------------------------------------------------------------------ tools and commands
def test_the_case_tools_run_on_a_corpus_without_case_collections(harness):
    run = lambda name, args: harness.scheduler.execute(ToolCall(name, args), actor=Actor.kernel())  # noqa: E731
    for name, args in (("study.casefind", {"findings": ["咳嗽", "发热"], "outcome": "improved", "prior": True}),
                       ("study.similar", {"text": "发热，咳嗽，脉浮数"}), ("study.casecompare", {"by": "period"}),
                       ("study.modifications", {}), ("study.treatments", {"target": "咳嗽"})):
        out = run(name, args)
        assert out.ok, (name, out.error)
    assert run("study.casefind", {"disease": "咳嗽"}).result["count"] == 0  # the demo corpus has no case collections
    assert not run("study.case", {"case_id": "case_none"}).ok


def test_the_case_commands(capsys, tmp_path):
    data = ["--data", str(tmp_path), "study"]
    assert main(data + ["casefind", "咳嗽", "--outcome", "died", "--finding", "脉浮数"]) == 0
    assert capsys.readouterr().out.startswith("# 医案检索：disease=咳嗽")
    assert main(data + ["similar", "发热，咳嗽，脉浮数"]) == 0
    assert capsys.readouterr().out.startswith("# 类案")
    assert main(data + ["casecompare", "--by", "period"]) == 0 and capsys.readouterr().out.startswith("# 医家与时代比较（按时期）")
    assert main(data + ["modifications"]) == 0 and capsys.readouterr().out.startswith("# 随证加减")
    assert main(data + ["treatments", "小柴胡汤"]) == 0 and capsys.readouterr().out.startswith("# 异病同治")
    with pytest.raises(SystemExit, match="no case of the case collections"):
        main(data + ["case", "case_none"])
    with pytest.raises(SystemExit, match="by: book, physician, period or author"):
        main(data + ["casecompare", "--by", "dynasty"])
    assert main(data + ["casefind", "咳嗽", "--dataset", str(tmp_path / "ds")]) == 0
    assert json.loads(capsys.readouterr().out)["resources"] == {"cases": 0, "case_visits": 0, "case_items": 0}
    assert (tmp_path / "ds" / "datapackage.json").exists()
