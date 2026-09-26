"""医案轨迹 — case records cut into cases and visits and read field by field (CaseEval's constructed records), and the
trajectory algorithms: sequential patterns, transitions, outcome associations."""

from __future__ import annotations

from pathlib import Path

from taochronos.evals.base import EvalContext
from taochronos.evals.textual import cases as cases_eval
from taochronos.kernel import Actor, ToolCall
from taochronos.science.trajectories import outcome_associations, prefixspan, transitions

HOME = Path(__file__).resolve().parents[1]


def test_constructed_records_are_read_visit_by_visit():
    m = cases_eval(EvalContext(home=HOME, quick=True)).metrics
    assert m["case_segmentation"] == 1.0 and m["visit_segmentation"] == 1.0
    assert m["response_accuracy"] >= 0.9 and m["outcome_accuracy"] >= 0.9 and m["patient_accuracy"] >= 0.9
    assert all(f["f1"] >= 0.9 for f in m["fields"].values())


def test_a_record_of_successive_visits(harness):
    cs = harness.capabilities.get("study")._cases
    rows = [("p1", "风温", "王　十岁　风温发热，脉浮数。治宜辛凉解表，银翘散主之。"),
            ("p2", "风温", "初三日　热已减，脉数。即于前方内去薄荷，加杏仁（三钱）。服二帖。"),
            ("p3", "风温", "某氏　痢下赤白，脉弦数。用白头翁汤。服二剂，痛不减，更甚。次日，与独参汤，不应，遂死。")]
    first, second = cs.parse_rows(rows, "demo")
    assert first.patient == {"name": "王", "age": "十"} and [v.marker for v in first.visits] == ["", "初三日"]
    v0, v1 = first.visits
    assert v0.formulas == ["银翘散"] and v0.principles == ["辛凉解表"] and v0.response == "improved"  # 热已减 answers it
    assert v1.removed == ["薄荷"] and v1.added == ["杏仁"] and v1.doses == "服二帖"
    assert second.patient["sex"] == "female" and [v.response for v in second.visits] == ["worse", "died"]
    assert second.outcome == "died"
    warning = cs.parse_rows([("p4", "中风", "某　脉弦。急宜用参附汤，不然子丑时脱阳而死矣。服之而安。")], "demo")[0]
    assert warning.outcome == "improved"  # 不然…而死矣 is a warning, not the outcome


def test_trajectory_mining():
    seqs = [[{"a"}, {"b"}, {"c"}], [{"a"}, {"x"}, {"b"}], [{"a"}, {"b"}], [{"y"}, {"a"}]]
    pats = {tuple(p["pattern"]): p["cases"] for p in prefixspan(seqs, min_support=2)}
    assert pats[("a", "b")] == 3 and ("a", "a") not in pats
    trans = transitions(seqs, min_count=2)
    assert trans[0]["from"] == "a" and trans[0]["to"] == "b" and trans[0]["count"] == 2
    cases = [({"x"}, "improved")] * 8 + [({"y"}, "died")] * 8 + [({"x", "y"}, "improved")] * 2
    rows = {r["item"]: r for r in outcome_associations(cases, min_cases=5)}
    assert rows["x"]["direction"] == "more" and rows["y"]["direction"] == "less" and rows["y"]["significant"]


def test_case_tools_run_without_case_collections(harness):
    out = harness.scheduler.execute(ToolCall("study.trajectories", {"disease": "消渴"}), actor=Actor.kernel())
    assert out.ok and out.result["cases"] == 0  # the demo corpus has no case collections
