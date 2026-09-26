"""文本地层 — layers, change points, boundaries, Delta attribution and dating evidence: the algorithms on constructed
profiles, StratigraphyEval's restyled composites, the chapter units of a witness and the study functions on the
fixture corpus."""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from taochronos.evals.base import EvalContext
from taochronos.evals.textual import stratigraphy as stratigraphy_eval
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.stratigraphy import unit_name
from taochronos.science import stratigraphy as st

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "study")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def _blocks(seed: int = 0) -> tuple[list[list[float]], list[int]]:
    """Two styles in blocks of five: profiles around two centres, with noise."""
    rng = random.Random(seed)
    points, truth = [], []
    for block in range(6):
        lab = block % 2
        for _ in range(5):
            points.append([(2.0 if lab else 0.0) + rng.gauss(0, 0.6) for _ in range(8)])
            truth.append(lab)
    return points, truth


def test_layers_are_found_tested_and_numbered_by_mass():
    points, truth = _blocks()
    weights = [1.0] * len(points)
    res = st.layers(points, weights, k=2)
    agree = sum(1 for a, b in zip(res["labels"], truth) if a == b) / len(truth)
    assert max(agree, 1 - agree) == 1.0 and res["supported"] and res["p"] <= 0.05
    assert all(abs(sum(m) - 1) < 1e-9 for m in res["memberships"])
    rng = random.Random(7)
    noise = [[rng.gauss(0, 1) for _ in range(8)] for _ in range(30)]
    assert not st.layers(noise, weights, k=2)["supported"]  # no structure: the split explains no more than chance


def test_change_points_and_boundaries_in_reading_order():
    points, truth = _blocks(1)
    found = [c["at"] for c in st.change_points(points, window=4)]
    assert all(any(abs(f - b) <= 1 for b in (5, 10, 15, 20, 25)) for f in found) and len(found) >= 3
    assert st.boundaries([0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0]) == [6, 9]  # the lone 1 is not a layer
    shift = [[0.0] * 4 for _ in range(10)] + [[3.0] * 4 for _ in range(10)]
    assert [c["at"] for c in st.change_points(shift, method="binary")] == [10]


def test_delta_attribution_and_dating_interval():
    texts = {"甲": "之者也而之者也而其所以" * 30, "乙": "则乃矣焉则乃矣焉若此是" * 30}
    names = st.FUNCTION_CHARS
    cands = {k: st.profile(v, names) for k, v in texts.items()}
    ranked = st.attribute(st.profile("之者也而其所以之者也而" * 5, names), cands)
    assert ranked[0]["candidate"] == "甲" and ranked[0]["margin"] > 0
    span = st.interval([{"kind": "citation", "after": 610, "strength": "hard"},
                        {"kind": "vocabulary", "after": 960, "strength": "soft"}], (-300, 25))
    assert span["after"] == 610 and span["vocabulary_after"] == 960 and span["later_than_nominal"]


def test_restyled_composites():
    m = stratigraphy_eval(EvalContext(home=HOME, quick=True)).metrics
    assert m["layer_accuracy"] >= 0.85 and m["split_supported"] == 1.0
    assert m["boundary_recall"] >= 0.7 and m["change_point_precision"] >= 0.8 and m["attribution_accuracy"] >= 0.75


def test_chapter_units_and_study_functions(study):
    assert unit_name({"chapter": "卷第二", "section": "傷寒例第三"}) == "傷寒例第三"  # 笈成: the 篇 in the section field
    assert unit_name({"chapter": "辨太阳病脉证并治上", "section": "第12条"}) == "辨太阳病脉证并治上"
    chapters = study._strata.chapters(["shl"])
    assert [c["chapter"] for c in chapters] == ["辨太阳病脉证并治上", "辨太阳病脉证并治中"]
    with pytest.raises(ValueError):
        study.layers("伤寒论")  # the fixture is far too short to profile
    dating = study.dating("伤寒论")
    assert dating["nominal"] == [200, 219] and len(dating["chapters"]) == 2
    who = study.authorship("太阳病，头痛发热，汗出恶风，桂枝汤主之。" * 14, candidates=["shl", "qjy", "jf"], min_chars=40)
    assert {c["candidate"] for c in who["candidates"]} <= {"伤寒论", "千金翼方", "太平惠民和剂局方"} and who["candidates"]


def test_chapter_filters_read_either_script(study):
    """A chapter asked for in one script finds it written in the other (辨脉法 · 辨脈法), in stratigraphy and collation."""
    names = list("之其者也而")
    simple = study._strata._profile_of(["shl"], names, "辨太阳病脉证并治上")[1]
    assert simple > 0 and study._strata._profile_of(["shl"], names, "辨太陽病脈證并治上")[1] == simple
    norm = study._stemma.b.normalize  # collate compiles the normalised pattern and matches normalised locators
    rows = study._stemma._rows("shl", re.compile(norm("辨太阳病脉证并治上")))
    assert rows and study._stemma._rows("shl", re.compile(norm("辨太陽病脈證并治上"))) == rows
