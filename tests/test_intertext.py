"""语义复用与思想传播 — the reuse-type rules, the features of reuse pairs, a passage's typed reuses across the study
fixture, a work's reception network, the tool, and the reuse type on lineage edges."""

from __future__ import annotations

from pathlib import Path

import pytest

from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack, IntertextAnalyzer
from taochronos.plugins.classics.study import StudyService
from taochronos.science.semantic_reuse import ReuseFeatures, classify, intermediaries, order_concordance, transmission_network

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "study")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


@pytest.fixture(scope="module")
def analyzer(study) -> IntertextAnalyzer:
    return IntertextAnalyzer(study.pack, study.corpus)


# ------------------------------------------------------------------ the rules
def _f(**kw) -> ReuseFeatures:
    base = dict(source_chars=20, target_chars=20, specificity=5.0, distinctive=1.0, order=1.0, length_ratio=1.0)
    return ReuseFeatures(**(base | kw))


def test_rules_reach_every_type_and_say_why():
    cases = {
        "verbatim_quote": _f(cov_source=1.0, cov_target=0.95, concept_cov=1.0),
        "near_verbatim": _f(cov_source=0.85, cov_target=0.8, concept_cov=0.9, length_ratio=1.1),
        "abridgement": _f(cov_source=0.5, cov_target=0.95, concept_cov=0.6, length_ratio=0.5, mean_block=8, longest_block=8),
        "summary": _f(cov_source=0.2, cov_target=0.5, concept_cov=0.3, concept_prec=0.7, length_ratio=0.3),
        "paraphrase": _f(cov_source=0.4, cov_target=0.35, concept_cov=0.75, length_ratio=1.2),
        "reinterpretation": _f(cov_source=0.3, cov_target=0.2, concept_cov=0.6, length_ratio=2.5, interpretation=["盖"]),
        "oppositional_reuse": _f(cov_source=0.9, cov_target=0.9, concept_cov=0.9, opposition=["殊不知"]),
        "formulaic_similarity": _f(cov_source=0.4, cov_target=0.4, concept_cov=0.1, formulaic_share=0.8),
        "uncertain": _f(cov_source=0.1, cov_target=0.1, concept_cov=0.2),
    }
    for label, f in cases.items():
        r = classify(f)
        assert r["label"] == label, (label, r)
        assert r["label_zh"] and r["rule"] and r["reasons"]
    assert classify(_f(cov_source=1.0, cov_target=1.0, concept_cov=1.0, attribution="经曰"))["citation"] == "明引"


def test_shared_genre_concepts_are_not_reuse_unless_specific():
    # content in common but not specific (an E-value above one): not a paraphrase, whatever the coverage
    generic = _f(cov_source=0.4, cov_target=0.2, concept_cov=0.7, length_ratio=1.0, specificity=0.1)
    assert classify(generic)["label"] == "uncertain" and classify(generic)["rule"] == "shared content not specific"
    assert classify(_f(cov_source=0.4, cov_target=0.2, concept_cov=0.7, specificity=0.1, attributed_to_source=True))["label"] == "paraphrase"
    assert classify(_f(cov_source=0.4, cov_target=0.2, concept_cov=0.7, distinctive=0.2))["label"] == "uncertain"
    assert order_concordance([(0, 0), (1, 1), (2, 2)]) == 1.0 and order_concordance([(0, 2), (1, 1), (2, 0)]) == 0.0


# ------------------------------------------------------------------ the features of real pairs
def test_the_paraphrase_the_review_asked_about(analyzer):
    r = analyzer.label("太阳之为病，脉浮，头项强痛而恶寒。", "仲景言太阳受邪，见脉浮而项背强痛者，以恶寒为常。")
    assert r["label"] == "paraphrase" and r["citation"] == "明引" and r["features"]["attribution"] == "仲景言"
    f = r["features"]
    assert set(f["concepts_shared"]) >= {"pulse:浮", "symptom:恶寒"} and "symptom:头项强痛" in f["concepts_partial"]
    assert f["cov_source"] < 0.8  # the characters alone would call it unrelated or at most a loose match


def test_quotations_notes_refutations_and_stock_phrasing(analyzer):
    source = "阴平阳秘，精神乃治；阴阳离决，精气乃绝。"
    noted = analyzer.label(source, "阴平阳秘，精神乃治，（阴气和平，阳气闭密，则精神日益治也。）阴阳离决，精气乃绝。")
    assert noted["label"] == "verbatim_quote" and noted["features"]["notes"] > 10  # 夹注 are commentary, not changes
    assert analyzer.label("邪之所凑，其气必虚。", "或谓邪之所凑，其气必虚，殊不知实邪亦能凑之，非尽虚也。")["label"] == "oppositional_reuse"
    stock = analyzer.label("桂枝三两，去皮，芍药三两，甘草二两。右三味，以水七升，煮取三升，去滓，温服一升。",
                           "麻黄三两，杏仁七十个。右二味，以水九升，先煮麻黄，去上沫，内诸药，煮取三升，去滓，温服一升。")
    assert stock["label"] == "formulaic_similarity"
    explained = analyzer.label(source, "所谓阴平阳秘者，盖言阴气平和，阳气固密，则精神内守而治；若阴阳相离而决，则精气竭绝。")
    assert explained["label"] == "reinterpretation" and "盖" in explained["features"]["interpretation"]


# ------------------------------------------------------------------ across the corpus
def test_reuse_across_the_fixture_finds_restatements_by_their_concepts(study):
    r = study.reuse("太阳病，头痛，发热，汗出，恶风，桂枝汤主之。")
    by_book = {h["book_id"]: h for h in r["hits"]}
    assert {"shl", "shl_b", "qjy", "yz"} <= set(by_book)
    assert by_book["qjy"]["label"] == "verbatim_quote" and by_book["qjy"]["relation"] == "引文"
    assert by_book["yz"]["label"] == "near_verbatim" and by_book["yz"]["found_by"] == ["concepts"]  # 宜桂枝汤: no shared 4-gram run
    assert r["summary"]["by_label"]["verbatim_quote"] >= 2 and r["summary"]["first_of_each_type"]["verbatim_quote"]["passage_id"] == "shl.13"


def test_transmission_of_a_work(study):
    r = study.transmission("伤寒论", clauses=10)
    assert r["base"] == ["shl"] and r["edges"] >= 4
    works = {w["work"]: w for w in r["works"]}
    assert "qjy" in works and "yz" in works and works["yz"]["dominant"] == "near_verbatim"
    assert {p["period"] for p in r["periods"]} >= {"隋唐五代", "清"}
    assert r["same_work_witnesses"] == {"伤寒论（别本）": 1}


def test_intermediaries_find_the_route_of_a_reading():
    sim = lambda a, b: len(set(a) & set(b)) / len(set(a) | set(b))  # noqa: E731
    clauses = [{"source": "ABCDEFGH", "targets": [{"work": "t1", "year": 600, "text": "ABCDXYGH"},
                                                   {"work": "t2", "year": 900, "text": "ABCDXYGH"},
                                                   {"work": "t3", "year": 950, "text": "ABCDEFGH"}]}] * 2
    routes = intermediaries(clauses, sim)
    assert routes == [{"via": "t1", "via_title": "", "work": "t2", "title": "", "clauses": 2, "closer_by": 0.4}]
    net = transmission_network([{"clause": 0, "target_work": "t1", "year": 600, "period": "唐", "label": "paraphrase", "passage_id": "p1"},
                                {"clause": 1, "target_work": "t1", "year": 600, "period": "唐", "label": "verbatim_quote", "passage_id": "p2"}])
    assert net["works"][0]["clauses"] == 2 and net["periods"][0]["retained"] == 0.5


# ------------------------------------------------------------------ tool and lineage
def test_reuse_tool_and_typed_lineage_edges(harness):
    call = lambda tool, **a: harness.scheduler.execute(ToolCall(tool, a), actor=Actor.kernel())  # noqa: E731
    out = call("study.reuse", text="太阳之为病，脉浮，头项强痛而恶寒。", target="太阳病，脉浮，头项强痛而恶寒。")
    assert out.ok and out.result["label"] == "near_verbatim"
    typed = {e.source_id: e.evidence.get("reuse_type") for e in harness.capabilities.get("knowledge").lineage()
             if e.relation in ("transcribes", "rephrases")}
    assert typed["yizong_jinjian.yongju"] == "verbatim_quote" and typed["zhubing.01.fengshibi"] == "abridgement"
