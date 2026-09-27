"""证据图谱、证据审计 (S15)、现代证据 (S13) and 真实世界数据 (S14)."""

from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET

import pytest

from taochronos.capabilities.judge import Judge
from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.modern import rwd
from taochronos.plugins.modern.evidence_types import type_record
from taochronos.plugins.models.scripted import ScriptedProvider
from taochronos.protocol.modern import ClaimLevel, EvidenceType, cross_level
from taochronos.verification.audit import decompose
from taochronos.verification.evidence_graph import EvidenceGraph, from_bridge

SUMMARIES = {
    "111": {"title": "Efficacy of berberine in patients with type 2 diabetes mellitus.", "pubtype": ["Journal Article", "Randomized Controlled Trial"],
            "pubdate": "2008 May", "fulljournalname": "Metabolism"},
    "222": {"title": "Berberine improves insulin sensitivity in high-fat diet fed rats.", "pubtype": ["Journal Article"],
            "pubdate": "2012", "fulljournalname": "J Ethnopharmacol"},
    "333": {"title": "Network pharmacology and molecular docking of Coptis against diabetes.", "pubtype": ["Journal Article"],
            "pubdate": "2021", "fulljournalname": "Medicine"},
    "444": {"title": "Berberine for type 2 diabetes: a systematic review and meta-analysis.", "pubtype": ["Journal Article", "Meta-Analysis",
            "Systematic Review"], "pubdate": "2015", "fulljournalname": "Evid Based Complement Alternat Med"},
}


def fake_pubmed(url: str) -> bytes:
    if "esearch" in url:
        return json.dumps({"esearchresult": {"idlist": list(SUMMARIES)}}).encode()
    if "esummary" in url:
        res = {"uids": list(SUMMARIES)}
        for k, v in SUMMARIES.items():
            res[k] = {**v, "articleids": [{"idtype": "doi", "value": f"10.1000/{k}"}]}
        return json.dumps({"result": res}).encode()
    arts = []
    for k in SUMMARIES:
        mesh = "<MeshHeading><DescriptorName>Animals</DescriptorName></MeshHeading><MeshHeading><DescriptorName>Rats</DescriptorName></MeshHeading>" if k == "222" else \
            "<MeshHeading><DescriptorName>Humans</DescriptorName></MeshHeading>"
        arts.append(f"<PubmedArticle><MedlineCitation><PMID>{k}</PMID><Article><Abstract><AbstractText>abstract {k}</AbstractText>"
                    f"</Abstract></Article><MeshHeadingList>{mesh}</MeshHeadingList></MedlineCitation></PubmedArticle>")
    return ("<PubmedArticleSet>" + "".join(arts) + "</PubmedArticleSet>").encode()


@pytest.fixture()
def online_modern(harness):
    m = harness.capabilities.get("modern")
    old = (m.pubmed.opener, m.online)
    m.pubmed.opener, m.online = fake_pubmed, True
    yield m
    m.pubmed.opener, m.online = old


def test_the_design_and_population_of_a_study_are_read_from_its_indexing():
    assert type_record(["Randomized Controlled Trial"], "Berberine in patients with diabetes")[0] == EvidenceType.RCT
    assert type_record(["Randomized Controlled Trial"], "Randomised study in rats", mesh=["Animals"])[0] == EvidenceType.ANIMAL
    assert type_record(["Journal Article"], "Network pharmacology of Huanglian decoction")[0] == EvidenceType.IN_SILICO
    assert type_record(["Meta-Analysis"], "Berberine: a meta-analysis")[:2] == (EvidenceType.SYSTEMATIC_REVIEW, type_record(["Meta-Analysis"], "x")[1])
    assert type_record(["Case Reports"], "Aconite poisoning")[0] == EvidenceType.CASE_REPORT
    assert cross_level(ClaimLevel.HUMAN_EFFICACY, EvidenceType.ANIMAL) == "animal or cell evidence read as a finding in people"
    assert cross_level(ClaimLevel.HUMAN_EFFICACY, EvidenceType.IN_SILICO) == "a computational prediction read as an effect"
    assert cross_level(ClaimLevel.MECHANISM, EvidenceType.ANIMAL) is None


def test_modern_evidence_is_typed_summed_and_guarded(online_modern):
    r = online_modern.search("黄连", "diabetes_mellitus")
    assert r["query"].startswith('("Coptis"[tiab] OR "berberine"[tiab]) AND ("Diabetes mellitus"[tiab])')
    types = {x["pmid"]: x["evidence_type"] for x in r["records"] if x.get("pmid")}
    assert types == {"111": "rct", "222": "animal", "333": "in_silico", "444": "systematic_review"}
    assert r["summary"]["best_human_level"] == 1 and r["summary"]["can_carry_efficacy"] == 2
    g = online_modern.guard("黄连素可降低2型糖尿病患者的血糖", r["records"])
    assert g["claim_level"] == "human_efficacy" and g["carrying"] == 2
    assert online_modern.safety("附子理中丸、细辛")[0]["material"] == "附子"
    offline = online_modern.pubmed
    offline.online, offline.opener = False, None  # cached answers are read offline
    assert len(online_modern.search("黄连", "diabetes_mellitus")["records"]) == 4


def test_claims_are_decomposed_and_audited_atom_by_atom(harness):
    a = harness.capabilities.get("audit")
    assert [c["role"] for c in decompose("《金匮》载「男子消渴」，所以肾气丸可治糖尿病。")] == ["premise", "conclusion"]
    ok = a.audit("《金匮要略》载「男子消渴，小便反多」。", modern=False)
    assert ok["verdict"] == "SUPPORTED" and ok["claims"][0]["passages"] == ["jinkui.13.xiaoke1"]
    fake = a.audit("《金匮要略》载「男子消渴，小便大多」。", modern=False)
    assert fake["verdict"] == "UNSUPPORTED" and "not in the cited work" in fake["claims"][0]["checks"][-1]["detail"]
    assert a.audit("消渴即糖尿病。", modern=False)["claims"][0]["kind"] == "mapping"
    assert a.audit("消渴即糖尿病。", modern=False)["verdict"] == "UNSUPPORTED"
    leap = a.audit("古籍记载黄连治消渴，所以黄连可以治疗2型糖尿病。", modern=False)
    assert [c["kind"] for c in leap["claims"]] == ["historical", "inference"] and leap["verdict"] == "UNSUPPORTED"
    hypo = a.audit("古籍记载黄连治消渴，因此黄连降糖值得作为假设研究。", modern=False)
    assert hypo["verdict"] == "INSUFFICIENT_EVIDENCE"
    dose = a.audit("糖尿病患者每日服附子30克。", modern=False)
    assert dose["claims"][0]["kind"] == "clinical" and dose["verdict"] == "UNSUPPORTED" and dose["safety"][0]["material"] == "附子"
    gloss = a.audit("「几几」者，伸颈之貌也，成无己注。", modern=False)
    assert gloss["claims"][0]["kind"] == "interpretive"
    assert any(ch["check"] == "gloss_found" for ch in gloss["claims"][0]["checks"])


def test_modern_claims_need_evidence_that_can_carry_them(harness, online_modern):
    a = harness.capabilities.get("audit")
    good = a.audit("黄连素可降低2型糖尿病患者的血糖。")
    assert good["claims"][0]["kind"] == "modern" and good["verdict"] == "SUPPORTED"
    mech = a.audit("黄连素通过激活AMPK通路发挥作用。")
    assert mech["claims"][0]["level"] == "mechanism" and mech["verdict"] == "SUPPORTED"
    SUMMARIES_BACKUP = dict(SUMMARIES)
    try:
        for k in ("111", "444"):
            SUMMARIES.pop(k)
        online_modern.pubmed.cache_dir = online_modern.pubmed.cache_dir.parent / "other-cache"
        weak = a.audit("黄连素可改善糖尿病患者的胰岛素抵抗。")
        assert weak["verdict"] == "UNSUPPORTED"
        assert any(ch["check"] == "cross_level" for ch in weak["claims"][0]["checks"])
    finally:
        SUMMARIES.clear()
        SUMMARIES.update(SUMMARIES_BACKUP)


def test_a_critic_may_lower_a_verdict_never_raise_it(harness):
    a = harness.capabilities.get("audit")
    reviews = {"reviews": [{"id": "C1", "verdict": "PARTIALLY_SUPPORTED", "concern": "只核对了原文，未核对版本"},
                           {"id": "C2", "verdict": "SUPPORTED", "concern": "试图抬高"}]}
    a.study.judge = Judge(ScriptedProvider([{"text": json.dumps(reviews, ensure_ascii=False)}]), "m")
    try:
        r = a.audit("《金匮要略》载「男子消渴，小便反多」，所以肾气丸可以治疗糖尿病。", modern=False)
    finally:
        a.study.judge = None
    c1, c2 = r["claims"]
    assert c1["verdict"] == "PARTIALLY_SUPPORTED" and c1["decided_by"] == "model" and c1["concerns"]
    assert c2["verdict"] == "UNSUPPORTED" and r["review"]["lowered"] == 1  # the raise is ignored


def test_the_evidence_graph_has_six_layers_and_a_lineage_back_to_the_witness(harness):
    b = harness.capabilities.get("bridge")
    g = from_bridge(b.map(passage_id="jinkui.13.xiaoke1"))
    stats = g.stats()
    assert {"source", "historical", "tcm_semantic", "mapping", "modern"} <= set(stats["layers"])
    assert {"SOURCE_ASSERTED", "MODEL_EXTRACTED", "SCHOLAR_INTERPRETED", "MODEL_INFERRED"} <= set(stats["assertions"])
    paths = g.lineage("resemblance:jinkui.13.xiaoke1->diabetes_mellitus")
    assert paths and paths[0][0]["source"] == "passage:jinkui.13.xiaoke1"
    assert g.unsupported() == []
    root = ET.fromstring(g.to_graphml())
    assert len(root.findall(".//{http://graphml.graphdrawing.org/xmlns}node")) == stats["nodes"]
    lone = EvidenceGraph()
    from taochronos.protocol.assertions import AssertionType, GraphLayer

    lone.node("h", GraphLayer.MAPPING, "hypothesis", "x")
    lone.node("d", GraphLayer.MODERN, "disease", "y")
    lone.edge("h", "d", "resembles", AssertionType.HYPOTHESIS)
    assert lone.unsupported()[0]["source"] == "h"  # an inference with no path to a source is listed


def test_a_real_world_question_becomes_a_checked_query(tmp_path):
    db_path = tmp_path / "omop.sqlite"
    info = rwd.synthesize(db_path, persons=800, seed=3)
    assert info["counts"]["person"] == 800
    con = sqlite3.connect(db_path)
    spec = rwd.spec_from_question("2型糖尿病患者中，使用黄连素与糖尿病肾病的关系", con)
    assert spec["exposure"]["name"] == "Berberine" and set(spec["exposure"]["concepts"]) == {2_000_000_102, 2_000_000_103}
    assert spec["outcome"]["name"] == "Diabetic nephropathy" and spec["population"]["name"] == "Type 2 diabetes mellitus"
    assert rwd.check_spec(spec, con) == []
    assert "not in the vocabulary" in rwd.check_spec({**spec, "outcome": {"name": "x", "concepts": [42]}}, con)[0]
    con.close()
    sql, params = rwd.compile_spec(spec)
    assert rwd.check_sql(sql, params) == []
    assert rwd.check_sql("DROP TABLE person", []) != []
    assert "tables outside" in rwd.check_sql("SELECT * FROM secrets", [])[0]
    assert any("literal" in e for e in rwd.check_sql("SELECT person_id FROM person WHERE year_of_birth = '1950'", []))
    r = rwd.run(spec, db_path)
    assert r["ok"] and r["synthetic"] and set(r["arms"]) == {"exposed", "unexposed"} and "not medical advice" in r["caveats"]
    raw = sqlite3.connect(db_path)
    exposed = raw.execute("SELECT count(DISTINCT person_id) FROM drug_exposure WHERE drug_concept_id IN (2000000102, 2000000103)").fetchone()[0]
    assert r["arms"]["exposed"]["n"] == exposed  # the compiled cohort is the raw one (no prior outcomes in this design)


def test_a_model_writes_the_spec_never_the_sql(harness, tmp_path):
    db_path = tmp_path / "omop.sqlite"
    rwd.synthesize(db_path, persons=300, seed=1)
    proposal = {"design": "cohort", "exposure": {"name": "Berberine"}, "outcome": {"name": "Diabetic nephropathy"},
                "population": {"name": "Type 2 diabetes mellitus", "sex": "any"}, "time": {"washout_days": 365, "followup_days": 730}}
    judge = Judge(ScriptedProvider([{"text": json.dumps(proposal)}]), "m")
    s = harness.capabilities.get("rwd").spec("黄连素与糖尿病肾病", db_path, judge=judge)
    assert s["by"] == "model" and s["errors"] == [] and s["spec"]["time"]["followup_days"] == 730
    assert "SQL" in judge.provider.requests[0].messages[-1].text  # the prompt forbids SQL; the answer carries none


def test_audit_graph_modern_and_rwd_through_tools_and_cli(harness, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("audit.claim", {"claim": "消渴即糖尿病。", "modern": False}), actor=Actor.kernel())
    assert out.ok and out.result["verdict"] == "UNSUPPORTED"
    g = harness.scheduler.execute(ToolCall("graph.evidence", {"passage_id": "jinkui.09.xiongbi"}), actor=Actor.kernel())
    assert g.ok and g.result["stats"]["nodes"] > 10
    s = harness.scheduler.execute(ToolCall("modern.safety", {"text": "雄黄、朱砂"}), actor=Actor.kernel())
    assert s.ok and {x["material"] for x in s.result} == {"雄黄", "朱砂"}
    assert main(["--data", str(tmp_path), "audit", "《金匮要略》载「男子消渴，小便反多」。", "--no-modern", "--profile", "full-discovery"]) == 0
    assert capsys.readouterr().out.startswith("# 证据审计：SUPPORTED")
    gml = tmp_path / "g.graphml"
    assert main(["--data", str(tmp_path), "graph", "--passage", "jinkui.13.xiaoke1", "--graphml", str(gml), "--profile", "full-discovery"]) == 0
    assert gml.read_text(encoding="utf-8").startswith("<?xml")
    capsys.readouterr()
    assert main(["--data", str(tmp_path), "rwd", "ask", "2型糖尿病患者中，使用黄连素与糖尿病肾病的关系", "--profile", "full-discovery"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
