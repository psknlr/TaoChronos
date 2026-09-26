"""语义演变 and 佚书辑佚 — sense labelling, change points and discovery on synthetic occurrences and on the demo 消渴;
a lost work reconstructed from the books that quote it (FragmentEval's constructed corpus)."""

from __future__ import annotations

from pathlib import Path

from taochronos.evals.base import EvalContext
from taochronos.evals.textual import fragments as fragments_eval
from taochronos.evals.textual import senses as senses_eval
from taochronos.plugins.classics.study.fragments import cn_number
from taochronos.science.sense_evolution import assign, change_point

HOME = Path(__file__).resolve().parents[1]


def test_senses_change_and_hidden_sense():
    m = senses_eval(EvalContext(home=HOME, quick=True)).metrics
    assert m["change_detected"] == 1.0 and m["change_year_error"] <= 50
    assert m["labelling_accuracy"] >= 0.85 and m["hidden_sense_found"] == 1.0
    agree, checked = map(int, m["exemplars"].split("/"))
    assert checked >= 6 and agree / checked >= 0.7


def test_assignment_uses_cues_and_anti_cues():
    senses = [{"id": "病", "cues": ["小便多"], "anti_cues": []}, {"id": "症", "cues": ["口渴"], "anti_cues": ["小便多"]}]
    assert assign([{"text": "口渴引饮"}, {"text": "口渴而小便多"}, {"text": "其人烦"}], senses) == ["症", "病", None]
    years = [float(y) for y in range(40)]
    labels = ["A"] * 20 + ["B"] * 20
    cp = change_point(years, labels, permutations=49)
    assert cp is not None and 18 <= cp["year"] <= 21 and cp["p"] < 0.05


def test_lost_work_reconstruction(harness):
    m = fragments_eval(EvalContext(home=HOME, quick=True)).metrics
    assert m["decoy_leaks"] == 0 and m["volume_accuracy"] == 1.0 and m["coverage"] == 1.0
    assert m["precision"] >= 0.8 and m["merged"] >= 1
    assert cn_number("二十八") == 28 and cn_number("十") == 10 and cn_number("三") == 3
    study = harness.capabilities.get("study")
    assert study.senses("消渴")["occurrences"] > 0
    assert study.fragments("小品方")["count"] >= 0  # the demo corpus quotes no 小品方: an empty reconstruction, no error
