"""古今桥接 (AMBE): ancient findings → HPO → modern disease profiles, explainably and never as a diagnosis; and back."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from taochronos.capabilities.judge import Judge
from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics.bridge import BridgeData
from taochronos.plugins.classics.bridge.data import read_obo, verify, write_closure
from taochronos.plugins.models.scripted import ScriptedProvider
from taochronos.protocol.bridge import RELATION_WEIGHT, BridgeRelation

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture()
def bridge(harness):
    b = harness.capabilities.get("bridge")
    b.study.judge = None
    yield b
    b.study.judge = None


def _by(packet, surface):
    return [f for f in packet["findings"] if f["surface"] == surface]


def test_a_passage_becomes_a_packet_whose_findings_carry_their_bounds(bridge):
    text = ("伤寒五六日，往来寒热，胸胁苦满，嘿嘿不欲饮食，心烦喜呕，或胸中烦而不呕，或渴，或心下悸、小便不利，或不渴、身有微热，"
            "小柴胡汤主之。若脉微弱，汗出恶风者，不可服之。服之则厥逆，筋惕肉瞤。小便自利者，不可与之。")
    p = bridge.phenotype(text)
    assert _by(p, "往来寒热")[0]["hpo"]["label"] == "Periodic fever" and not _by(p, "往来寒热")[0]["optional"]
    assert _by(p, "呕")[-1]["negated"] and _by(p, "呕")[-1]["optional"]  # 或胸中烦而不呕
    assert _by(p, "小便不利")[0]["optional"]  # 或心下悸、小便不利: the 或 list goes on after 、
    thirst = _by(p, "渴")
    assert [f["negated"] for f in thirst] == [False, True] and all(f["optional"] for f in thirst)
    assert _by(p, "汗出")[0]["conditional"] and _by(p, "汗出")[0]["weight"] == 0.4
    tremor = next(f for f in p["findings"] if f["phenotype"] == "tremor")  # 瞤 is normalised: the form still matches
    assert tremor["status"] == "after_treatment"
    assert not any(f["phenotype"] == "diarrhea" for f in p["findings"])  # 小便自利 is blocked, not 自利 (diarrhea)
    assert _by(p, "胸胁苦满")[0]["hpo"] is None and _by(p, "胸胁苦满")[0]["relation"] == "NO_MODERN_EQUIVALENT"
    assert _by(p, "嘿嘿")[0]["relation"] == "CONTEXT_DEPENDENT" and _by(p, "嘿嘿")[0]["review"]
    assert "acute" in p["context"]["course"]  # counted in days (五六日)
    assert all(f["quote"].count("【") == 1 for f in p["findings"])


def test_a_form_read_two_ways_takes_the_reading_its_sentence_supports(bridge):
    assert _by(bridge.phenotype("咳逆上气，喘而不得卧。"), "不得卧")[0]["phenotype"] == "orthopnea"
    assert _by(bridge.phenotype("心中烦，不得卧。"), "不得卧")[0]["phenotype"] == "insomnia"
    alone = _by(bridge.phenotype("不得卧。"), "不得卧")[0]
    assert alone["phenotype"] == "insomnia" and alone["review"]  # the default, marked for review
    # one-character forms only at a clause boundary: 利 in 利其小便 is not diarrhea
    assert not any(f["phenotype"] == "diarrhea" for f in bridge.phenotype("当利其小便。")["findings"])
    assert _by(bridge.phenotype("发热而渴，不恶寒者，为温病。"), "恶寒")[0]["negated"]


def test_a_mapping_is_explainable_and_never_a_probability(bridge, harness):
    r = bridge.map(passage_id="jinkui.13.xiaoke1")
    top = {c["disease"]: c for c in r["candidates"]}
    assert top["diabetes_insipidus"]["level"] == top["diabetes_mellitus"]["level"] == "moderate"
    dm = top["diabetes_mellitus"]
    assert {m["feature_label"] for m in dm["matched"]} == {"Polydipsia", "Polyuria"}
    assert {m["label"] for m in dm["missing_typical"]} == {"Polyphagia", "Weight loss"}
    assert all(c["calibrated"] is False and c["relation"] == "PHENOTYPIC_SIMILARITY" for c in r["candidates"][:2])
    sweet = next(d for d in r["discriminators"] if d.get("label") == "Glycosuria")
    assert "尿甜" in sweet["ancient_forms"] and "尿崩症" in sweet["against"]
    assert "不是回溯诊断" in r["statement"] and r["guard"] == []
    t = r["terms"][0]
    assert t["term"] == "消渴" and {x["relation"] for x in t["relations"]} == {"PARTIAL_OVERLAP"}
    assert any("不可接受的等同" in w for x in t["relations"] for w in x["why"])
    from taochronos.protocol.schema import validate
    from taochronos.plugins.classics.study.schemas import STUDY_SCHEMAS

    assert validate(r, STUDY_SCHEMAS["bridge_map"]) == []


def test_levels_follow_rules_a_reader_can_check(bridge):
    # the three polys and wasting: high
    sanxiao = bridge.map(passage_id="jingyue.sanxiao")["candidates"][0]
    assert sanxiao["disease"] == "diabetes_mellitus" and sanxiao["level"] == "high"
    # one finding stated: at most low
    one = bridge.map("口渴引饮。")["candidates"]
    assert one and all(c["level"] in ("low", "insufficient") for c in one)
    # plague without buboes stays low, however the fever, chills and headache fit
    s43 = bridge.map(passage_id="wenbing_tiaobian.s43")
    plague = next(c for c in s43["candidates"] if c["disease"] == "plague")
    assert plague["level"] == "low" and not plague["required_met"] and any("Lymphadenopathy" in cap for cap in plague["caps"])
    assert s43["candidates"][0]["level"] == "moderate"  # the strongest level comes first
    # a denied cardinal finding is a conflict
    denied = bridge.map("小便多，消瘦，善饥，不渴。")
    dm = next(c for c in denied["candidates"] if c["disease"] == "diabetes_mellitus")
    assert any(x["kind"] == "denied_typical" and x["feature_label"] == "Polydipsia" for x in dm["conflicts"])
    # a drug's indications are not one patient's picture
    assert bridge.phenotype(passage_id="shennong.gualougen")["kind"] == "indication"


def test_historical_names_are_related_by_the_sense_the_passage_selects(bridge):
    c002 = bridge.map(passage_id="shanghanlun.c002")["terms"]
    zhongfeng = next(t for t in c002 if t["term"] == "中风")
    assert zhongfeng["sense"] == "中风#外感"
    assert {x["relation"] for x in zhongfeng["relations"]} == {"NO_MODERN_EQUIVALENT"}  # a pattern, not a disease
    stroke = next(t for t in bridge.map(passage_id="jinkui.05.zhongfeng")["terms"] if t["term"] == "中风")
    assert stroke["sense"] == "中风#卒中"
    assert {x["relation"] for x in stroke["relations"]} <= {"PARTIAL_OVERLAP", "UNCERTAIN"}
    huoluan = bridge.map(passage_id="shanghanlun.c382")
    assert any("1817" in w for t in huoluan["terms"] for x in t["relations"] for w in x["why"])
    # what the name implies by its sense counts at half weight and never alone lifts a level to high
    implied = bridge.phenotype(passage_id="shanghanlun.c386")["implied"]
    assert {f["phenotype"] for f in implied} >= {"vomiting", "diarrhea"} and all(f["weight"] == 0.5 for f in implied)
    assert RELATION_WEIGHT[BridgeRelation.NO_MODERN_EQUIVALENT] == 0.0


def test_the_hpo_identifiers_are_checked_against_a_release(tmp_path):
    root = tmp_path / "bridge"
    shutil.copytree(HOME / "domains" / "bridge", root)
    data = BridgeData(root)
    ids = data.hpo_ids()
    assert len(ids) > 150 and all(h.startswith("HP:") and len(h) == 10 for h in ids)
    terms = []
    for h, label in ids.items():
        if h == "HP:0001959":
            terms.append(f"[Term]\nid: {h}\nname: Excessive thirst\nsynonym: \"{label}\" EXACT []\n")
        elif h == "HP:0000103":
            terms.append(f"[Term]\nid: {h}\nname: {label}\nis_obsolete: true\nreplaced_by: HP:9999999\n")
        elif h == "HP:0003419":
            terms.append(f"[Term]\nid: {h}\nname: {label}\nis_a: HP:0003418 ! Back pain\n")
        elif h != "HP:0002315":
            terms.append(f"[Term]\nid: {h}\nname: {label}\n")
    obo = tmp_path / "hp.obo"
    obo.write_text("format-version: 1.2\ndata-version: hp/releases/test\n\n" + "\n".join(terms), encoding="utf-8")
    release = read_obo(obo)
    report = verify(data, release)
    problems = {p["id"]: p["problem"] for p in report["problems"]}
    assert problems == {"HP:0001959": "synonym", "HP:0000103": "obsolete", "HP:0002315": "missing"}
    assert report["release"] == "hp/releases/test"
    path = write_closure(data, release)
    assert BridgeData(root).ancestors == {"HP:0003419": {"HP:0003418"}} and path.name == "hpo_closure.yaml"
    shipped = BridgeData(HOME / "domains" / "bridge")
    assert shipped.match("HP:0003419", "HP:0003418") == 0.8 and shipped.match("HP:0000969", "HP:0010741") == 0.5


def test_a_modern_disease_is_traced_back_to_passages_and_names(bridge):
    r = bridge.reverse("E11")  # an ICD-10 code inside the profile's range
    assert r["disease"]["id"] == "diabetes_mellitus"
    ids = [p["passage_id"] for p in r["passages"]]
    assert ids[0] == "jingyue.sanxiao" and "jinkui.13.xiaoke1" in ids
    assert all(p["level"] != "insufficient" for p in r["passages"])
    assert r["names"][0]["term"] == "消渴" and "Hyperglycemia" in r["unobservable"]
    assert "尿甜" in r["forms"]["Glycosuria"]
    with pytest.raises(ValueError, match="several profiles"):
        bridge.reverse("stroke")


def test_a_model_reviews_what_the_rules_leave_open_and_can_only_lower_a_level(bridge):
    steps = [
        {"text": json.dumps({"decisions": [{"id": "F1", "reading": "thirst_drinking", "reason": "消渴此处为病名而兼渴"}]}, ensure_ascii=False)},
        {"text": json.dumps({"findings": [{"text": "饮一斗", "phenotype": "thirst_drinking"}, {"text": "不在原文", "phenotype": "fever"}]},
                            ensure_ascii=False)},
        {"text": json.dumps({"decisions": [{"id": "D1", "verdict": "doubtful", "reason": "原文未言尿甜，难与尿崩症相区别"},
                                           {"id": "D2", "verdict": "compatible", "reason": "多饮多尿"}]}, ensure_ascii=False)},
        {"text": "not json"},  # the check fails once: the judge asks again (a repair turn)
        {"text": json.dumps({"sentences": [
            {"text": "「小便反多」与多尿在表型上相近，但强度未经校准。", "cites": ["F2", "D2"]},
            {"text": "消渴即糖尿病。", "cites": ["T1"]}]}, ensure_ascii=False)},
    ]
    bridge.study.judge = Judge(ScriptedProvider(steps), "m")
    r = bridge.map(passage_id="jinkui.13.xiaoke1")
    p = r["packet"]
    # the proposals are checked: one repeats a span the rules read, the other is not in the text — both dropped
    assert p["findings"][0]["decided_by"] == "both" and p["review"]["recall"] == {"ok": True, "added": 0, "dropped": 2}
    d1 = next(c for c in r["candidates"] if c["id"] == "D1")
    assert d1["model_verdict"] == "doubtful" and d1["level"] == "low"  # moderate → low; a model never raises
    assert next(c for c in r["candidates"] if c["id"] == "D2")["level"] == "moderate"
    summary = r["summary"]
    assert [s["text"] for s in summary["sentences"]] == ["「小便反多」与多尿在表型上相近，但强度未经校准。"]
    assert summary["guard_dropped"][0]["text"] == "消渴即糖尿病。"  # the guard drops an equation


def test_the_bridge_through_the_tools_and_the_cli(harness, capsys, tmp_path, bridge):
    out = harness.scheduler.execute(ToolCall("bridge.map", {"passage_id": "jinkui.09.xiongbi"}), actor=Actor.kernel())
    assert out.ok and out.result["candidates"][0]["disease"] == "angina_pectoris"
    rev = harness.scheduler.execute(ToolCall("bridge.reverse", {"disease": "心绞痛"}), actor=Actor.kernel())
    assert rev.ok and rev.result["passages"][0]["passage_id"] == "jinkui.09.xiongbi"
    assert main(["--data", str(tmp_path), "bridge", "map", "--passage", "jinkui.18.changyong2", "--profile", "full-discovery"]) == 0
    page = capsys.readouterr().out
    assert page.startswith("# 古今映射") and "阑尾炎" in page and "不是回溯诊断" in page
    assert main(["--data", str(tmp_path), "bridge", "diseases", "--profile", "full-discovery"]) == 0
    assert "diabetes_insipidus" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no HPO release"):
        main(["--data", str(tmp_path), "bridge", "verify", "--profile", "full-discovery"])
