"""医理论证 — argument graphs from discourse markers: ArgumentEval's annotated passages, clause cutting before an inner
则 / 故, topics against conditions, the profile and the comparison of works."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from taochronos.evals.base import EvalContext
from taochronos.evals.textual import argument as argument_eval
from taochronos.kernel import Actor, ToolCall
from taochronos.science.argumentation import build_graph, chains, compare, log_odds

HOME = Path(__file__).resolve().parents[1]
TABLE = {"condition": {"lead": ["若"], "tail": ["者"], "direction": "to_next"},
         "consequence": {"lead": ["则"], "direction": "from_previous"},
         "treatment": {"lead": ["宜"], "tail": ["主之"], "direction": "from_previous"},
         "analogy": {"lead": ["犹"], "direction": "to_previous"}}


def _clauses(*texts: str, sentence: int = 0) -> list[dict]:
    return [{"text": t, "sentence": sentence, "concepts": []} for t in texts]


def test_annotated_passages():
    m = argument_eval(EvalContext(home=HOME, quick=True)).metrics
    assert m["edges"]["f1"] >= 0.9 and m["unlabelled"]["f1"] >= 0.9 and m["clause_segmentation"] >= 0.9


def test_conditions_topics_and_the_most_specific_relation():
    edges = build_graph(_clauses("若脉浮，", "小便不利，", "微热消渴者，", "五苓散主之。"), TABLE)
    assert {(e["source"], e["target"], e["relation"]) for e in edges} == {(0, 3, "condition"), (2, 3, "treatment")}
    topic = build_graph(_clauses("夫中风者，", "外感风邪，", "犹树之根本先伤。"), TABLE)
    assert {(e["source"], e["target"], e["relation"]) for e in topic} == {(1, 0, "define"), (2, 1, "analogy")}
    path = [{"source": 0, "target": 1, "relation": "condition"}, {"source": 1, "target": 2, "relation": "treatment"}]
    assert chains(3, path) == Counter({("condition", "treatment"): 1})


def test_inner_markers_and_study_functions(harness):
    study = harness.capabilities.get("study")
    g = study.argument("阳胜则热，阴胜则寒。此法则可用。")
    assert [c["text"] for c in g["clauses"]][:4] == ["阳胜", "则热，", "阴胜", "则寒。"]
    assert "此法则可用。" in [c["text"] for c in g["clauses"]]  # 法则 is a word, not a step
    profile = study.argument(work="伤寒论")
    assert profile["clauses"] > 0 and profile["per_1000_clauses"].get("treatment", 0) > 0
    both = study.argument(work="伤寒论", against="温病条辨")
    assert 0 <= both["comparison"]["relations_jsd"] <= 1
    out = harness.scheduler.execute(ToolCall("study.argument", {"text": "若脉浮者，宜麻黄汤。"}), actor=Actor.kernel())
    assert out.ok and out.result["edges"]


def test_log_odds_marks_what_sets_a_work_apart():
    a, b = Counter({"treatment": 50, "analogy": 2}), Counter({"treatment": 20, "analogy": 30})
    rows = {r["item"]: r["z"] for r in log_odds(a, b)}
    assert rows["treatment"] > 0 > rows["analogy"]
    assert compare({"relations": a, "triples": Counter()}, {"relations": a, "triples": Counter()})["relations_jsd"] == 0.0
