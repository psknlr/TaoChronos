"""版本谱系 — multi-witness collation, variant units, the stemma and contamination: on constructed witnesses, on an
artificial tradition with a known history, and on a passage's copies and quotations in the study fixture."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from taochronos.evals.base import EvalContext
from taochronos.evals.textual import collation as collation_eval
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.collation import (
    WitnessText,
    align,
    apparatus,
    build_units,
    load_equivalents,
    matched,
    neighbour_joining,
    project,
    robinson_foulds,
    root,
    splits,
)
from taochronos.plugins.classics.study import StudyService
from taochronos.protocol.textual_criticism import Witness

HOME = Path(__file__).resolve().parents[1]
BASE = ("太阳之为病脉浮头项强痛而恶寒太阳病发热汗出恶风脉缓者名为中风太阳病或已发热或未发热必恶寒体痛呕逆脉阴阳俱紧者名为伤寒"
        "伤寒一日太阳受之脉若静者为不传颇欲吐若躁烦脉数急者为传也伤寒二三日阳明少阳证不见者为不传也太阳病发热而渴不恶寒者为温病")


def _w(siglum: str, text: str) -> WitnessText:
    return WitnessText.build(siglum, siglum, [(siglum, siglum, "", text)], lambda t: t)


def _units(texts: dict[str, str], equivalents: dict[str, str] | None = None):
    base = _w("A", texts["A"])
    projections = {s: project(len(base.text), align(base.text, _w(s, t).text), _w(s, t)) for s, t in texts.items() if s != "A"}
    return base, projections, build_units(base, projections, equivalents=equivalents)


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "study")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def test_alignment_recovers_every_edit_as_a_unit_of_its_kind():
    b = BASE
    witnesses = {"A": b,
                 "B": b.replace("名为中风", "名曰中风", 1),  # substitution
                 "C": b.replace("头项强痛", "项强痛", 1),  # omission
                 "D": b.replace("脉缓者", "脉缓者也", 1),  # addition (of a function word)
                 "E": b.replace("体痛呕逆", "体痛逆呕", 1)}  # transposition
    base, projections, units = _units(witnesses)
    assert matched(align(b, witnesses["B"])) == len(b) - 1
    kinds = {u.readings[1].witnesses[0]: u.kind for u in units if len(u.readings) == 2}
    assert kinds == {"B": "substitution", "C": "omission", "D": "addition", "E": "transposition"}
    assert all(u.readings[0].witnesses[0] == "A" for u in units)  # the lemma (the base's reading) comes first
    assert next(u for u in units if u.kind == "addition").weight == 0.5  # a function word added


def test_lacunae_and_structural_additions_are_not_variants():
    b = BASE
    missing = b[:40] + b[40 + 45:]  # 45 characters lost
    commentary = b[:30] + "此言太阳中风之证也以其汗出恶风故名中风非伤寒之无汗恶寒可比学者当细辨之勿以为一证也" + b[30:]
    _, projections, units = _units({"A": b, "B": missing, "C": commentary})
    assert projections["B"].lacunae == [(40, 85)] and projections["B"].carried == len(b) - 45
    assert projections["C"].structural >= 40
    assert [u.structural for u in units] == [True]  # B is silent where it lacks the text, not in disagreement


def test_orthographic_equivalents_do_not_count():
    eq = load_equivalents([["沉", "沈"], ["脏", "藏"]])
    b = "脉沉而紧者五脏皆虚当温之" * 4
    _, _, units = _units({"A": b, "B": b.replace("沉", "沈"), "C": b.replace("紧", "弦", 1)}, eq)
    ortho = [u for u in units if u.kind == "orthographic"]
    assert ortho and all(u.weight == 0.1 for u in ortho) and {u.lemma for u in ortho} == {"沉"}
    assert [u.kind for u in units if u.kind != "orthographic"] == ["substitution"]


def test_neighbour_joining_recovers_a_known_tree():
    # the path lengths of the unrooted tree A,B — x —6— z — y — C,D, with E on z (an additive metric)
    leaves = ["A", "B", "C", "D", "E"]
    pairs = {"AB": 5, "AC": 12, "AD": 14, "AE": 13, "BC": 13, "BD": 15, "BE": 14, "CD": 6, "CE": 9, "DE": 11}
    d = {(k[0], k[1]): float(v) for k, v in pairs.items()} | {(k[1], k[0]): float(v) for k, v in pairs.items()}
    inferred = splits(neighbour_joining(leaves, d), leaves)
    assert inferred == {frozenset("CDE"), frozenset("CD")}  # each split written as the side without A
    assert robinson_foulds(inferred, {frozenset("CDE"), frozenset("DE")}) == 0.5
    rooted, name = root(neighbour_joining(leaves, d), leaves)
    assert name == "α" and {e.child for e in rooted} >= set(leaves)


def test_artificial_traditions_are_recovered():
    ctx = EvalContext(home=HOME, data_dir=None, quick=True)
    m = collation_eval(ctx).metrics
    assert m["unit_recall"] >= 0.97 and m["unit_precision"] >= 0.97
    assert m["split_recall"] == 1.0 and m["group_precision_top3"] >= 0.9
    assert m["contamination_precision"] == 1.0 and m["contamination_recall"] == 1.0


def test_passage_collation_of_copies_and_quotations(study):
    r = study.variants(text="太阳病，头痛，发热，汗出，恶风，桂枝汤主之。")
    books = {w["book_id"]: w for w in r["witnesses"][1:]}
    assert set(books) == {"shl", "shl_b", "qjy"} and books["qjy"]["kind"] == "quotation"
    (unit,) = r["units"]
    assert unit["kind"] == "addition" and unit["readings"][1]["text"] == "者"
    assert unit["readings"][1]["witnesses"] == [books["shl_b"]["id"]] and books["shl_b"]["singular_readings"] == 1
    assert r["relations"][books["qjy"]["id"]] == "引文" and r["newick"].endswith(";")


def test_tei_apparatus_is_well_formed():
    base, projections, units = _units({"A": BASE, "B": BASE.replace("头项强痛", "头项强疼", 1), "C": BASE[:2] + BASE[2 + 45:]})
    tei = apparatus(base, units, [Witness(id=s, title=s) for s in "ABC"], title="测试")
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    (app,) = ET.fromstring(tei).findall(".//t:app", ns)
    assert app.find("t:lem", ns).text == "痛" and app.find("t:lem", ns).get("wit") == "#A"
    rdgs = app.findall("t:rdg", ns)
    assert [(r.text, r.get("wit"), r.get("type")) for r in rdgs] == [("疼", "#B", None), (None, "#C", "lacuna")]
