"""Evaluation layer 3 — research value: the time-machine views of the store and the benchmark's rankings and statistics."""

from __future__ import annotations

from pathlib import Path

import pytest

from taochronos.evals.base import EvalContext
from taochronos.evals.research_value import average_precision, ranking, research_value, sign_test, summarise, topic_row
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import ingest_kanripo, load_catalog
from taochronos.plugins.classics.store import CorpusStore, StoreCorpus
from taochronos.science import CooccurrenceGraph

HOME = Path(__file__).resolve().parents[1]
FIXTURES = HOME / "tests" / "fixtures" / "kanripo"


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> StoreCorpus:
    pack = DomainPack(HOME / "domains" / "classics")
    path = tmp_path_factory.mktemp("rv-store") / "corpus" / "tcm.sqlite"
    db = CorpusStore(path, create=True)
    ingest_kanripo(db, load_catalog(FIXTURES / "catalog.yaml"), FIXTURES, pack.variants.normalize_text, pack.variants.fingerprint,
                   log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    db.optimize()
    db.close()
    return StoreCorpus(CorpusStore(path), pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)


# ------------------------------------------------------------------ the views
def test_a_view_on_one_side_of_a_cutoff_holds_only_the_passages_wholly_on_it(store):
    everything = store.passages()
    sides = {p.id: store.year_range(p).side_of(700) for p in everything}
    assert set(sides.values()) == {"before", "after"}  # the fixture's main texts are Han, its notes Tang and Song
    for side in ("before", "after"):
        view = store.on_side(700, side)
        expected = {pid for pid, where in sides.items() if where == side}
        assert {p.id for p in view.passages()} == set(view.passage_ids()) == expected and len(view) == len(expected)
        other = next(p for p in everything if sides[p.id] != side)
        assert not view.has_passage(other.id) and view.passages_by_id([other.id]) == []
        with pytest.raises(KeyError):
            view.passage(other.id)
        han = "".join(ch for ch in store.normalize(other.text) if "一" <= ch <= "鿿")
        word = han[:2]
        assert set(view.contains(word)) <= expected and {pid for pid, _ in view.search([word])} <= expected
        assert set(store.contains(word)) - set(view.contains(word)) <= set(sides) - expected
        assert set(view.books) <= set(store.books)
    straddle = store.on_side(210, "before")  # 200–219 straddles 210: that text is in neither the past nor the future
    assert not any(p.book_id == "ceshi_fangshu" and store.year_range(p).start == 200 for p in straddle.passages())
    assert not any(p.book_id == "ceshi_fangshu" and store.year_range(p).start == 200 for p in store.on_side(210, "after").passages())
    with pytest.raises(ValueError):
        store.on_side(700, "during")


def test_the_study_layers_own_queries_of_the_store_keep_to_the_view(store):
    from taochronos.plugins.classics.study.base import StudyBase

    pack = DomainPack(HOME / "domains" / "classics")
    whole, past = StudyBase(pack, store), StudyBase(pack, store.on_side(700, "before"))
    sides = {p.id: store.year_range(p).side_of(700) for p in store.passages()}
    early = {store.normalize(p.text) for p in store.passages() if sides[p.id] == "before" and p.book_id == "ceshi_neijing"}
    texts = {store.normalize(t) for t in past.book_texts("ceshi_neijing")}
    assert texts and texts <= early < {store.normalize(t) for t in whole.book_texts("ceshi_neijing")}
    count = lambda b: sum(v["passages"] for v in b.period_totals().values())  # noqa: E731
    assert 0 < count(past) < count(whole)  # the denominators of a past-only study count the past only
    assert store.on_side(700, "before").row_filter("") == (" AND y_end < ?", [700.0])


def test_the_in_memory_corpus_splits_the_same_way(harness):
    corpus = harness.corpus
    before, after = corpus.on_side(618, "before"), corpus.on_side(618, "after")
    assert before.passage_ids() and after.passage_ids()
    assert not set(before.passage_ids()) & set(after.passage_ids())
    assert all((corpus.year_range(p) is None or corpus.year_range(p).side_of(618) == "before") for p in before.passages())
    assert all(corpus.year_range(p).side_of(618) == "after" for p in after.passages())


# ------------------------------------------------------------------ rankings and statistics
def _graph() -> CooccurrenceGraph:
    # 消渴 is linked to 天花粉 and 麦冬; 黄连 shares both neighbours with it (two paths), 甘草 is everywhere but shares one
    return CooccurrenceGraph([["disease:消渴", "herb:天花粉"], ["disease:消渴", "herb:麦冬"], ["herb:黄连", "herb:天花粉"],
                              ["herb:黄连", "herb:麦冬"], ["herb:甘草", "herb:麦冬"], ["herb:甘草", "symptom:咳"],
                              ["herb:甘草", "symptom:喘"], ["herb:甘草", "symptom:呕吐"], ["herb:甘草", "disease:疟"]])


def test_rankings_order_every_candidate_and_the_scores_are_exact():
    g = _graph()
    candidates = {n for n in g.nodes() if n.startswith("herb:") and not g.linked("disease:消渴", n)}
    assert candidates == {"herb:黄连", "herb:甘草"}
    assert ranking(g, "disease:消渴", candidates, "adamic_adar")[0] == "herb:黄连"  # two shared neighbours
    assert ranking(g, "disease:消渴", candidates, "popularity")[0] == "herb:甘草"  # the best connected
    for method in ("adamic_adar", "resource_allocation", "common_neighbors", "popularity", "random"):
        assert sorted(ranking(g, "disease:消渴", candidates, method, seed=3)) == sorted(candidates)
    assert average_precision(["a", "b", "c"], {"a", "c"}) == pytest.approx((1 + 2 / 3) / 2)
    assert average_precision(["a"], set()) == 0.0
    assert sign_test(9, 1) == pytest.approx(0.0215, abs=1e-4) and sign_test(5, 5) == 1.0 and sign_test(0, 0) == 1.0
    assert 0 < sign_test(156, 45) < 1e-4  # a tiny p is kept, in two significant figures, not rounded to 0


class _Reader:
    """Past and future claims as (relation, book, terms), keyed by side."""

    def __init__(self, past: list, future: list) -> None:
        self.side = {"past": past, "future": future}

    @staticmethod
    def is_remedy(term_id: str) -> bool:
        return term_id.startswith(("herb:", "formula:")) and term_id != "herb:药"

    def ids(self, view: str, topic: str) -> set[str]:
        return {f"{view}{i}" for i in range(len(self.side[view]))}

    def links(self, view: str, ids) -> list:
        return [self.side[view][int(pid[len(view):])] for pid in ids]


def test_a_topic_row_counts_what_came_true_in_two_books_and_scores_each_ranker():
    past = [("indicated_for", "b1", frozenset(m)) for m in (
        {"disease:消渴", "herb:天花粉"}, {"disease:消渴", "herb:麦冬"}, {"herb:黄连", "herb:天花粉"}, {"herb:黄连", "herb:麦冬"},
        {"herb:甘草", "herb:麦冬"}, {"herb:甘草", "symptom:咳"}, {"herb:甘草", "symptom:喘"}, {"herb:甘草", "disease:疟"},
        {"herb:药", "herb:麦冬"})]  # a weak entry: in the graph, never a candidate
    future = [("indicated_for", "b2", frozenset({"disease:消渴", "herb:黄连"})),
              ("indicated_for", "b3", frozenset({"disease:消渴", "herb:黄连"})),
              ("indicated_for", "b3", frozenset({"disease:消渴", "herb:甘草"})),  # one book only: not come true
              ("contraindicated", "b4", frozenset({"disease:消渴", "herb:甘草"}))]  # not a positive link
    rules = {"topics": {"min_past": 1, "max_past": 100, "min_future": 1, "future_cap": 100}, "truth": {"min_books": 2},
             "ks": [1], "random_seeds": 4}
    row = topic_row(_Reader(past, future), "past", "future", "disease:消渴", rules)
    assert row["candidates"] == 2 and row["came_true"] == 1 and row["came_true_one_book"] == 2 and row["base_rate"] == 0.5
    assert row["adamic_adar"]["hits@1"] == 1 and row["popularity"]["hits@1"] == 0
    assert row["examples"] == [{"remedy": "herb:黄连", "rank": 1, "future_books": 2}]
    summary = summarise([{"cutoff": 1, **row}, {"cutoff": 1, "topic": "x", "skipped": "past_too_few"}], [1])
    assert summary["topics_with_links_come_true"] == 1 and summary["skipped"] == {"past_too_few": 1}
    assert summary["adamic_adar"]["precision@1"] == 1.0 and summary["popularity"]["precision@1"] == 0.0
    assert summary["adamic_adar_vs_popularity"] == {"wins": 1, "losses": 0, "ties": 0, "sign_test_p": 1.0}
    assert topic_row(_Reader(past[:1], future), "past", "future", "disease:消渴",
                     {**rules, "topics": {**rules["topics"], "min_past": 5}})["skipped"] == "past_too_few"


def test_the_suite_is_skipped_in_quick_runs_and_without_the_store(tmp_path):
    assert research_value(EvalContext(home=HOME, data_dir=tmp_path, quick=True)).metrics == {"skipped": "quick run"}
    ctx = EvalContext(home=HOME, data_dir=tmp_path)
    ctx._corpus = None  # as when no store is found
    assert research_value(ctx).metrics == {"skipped": "no full-corpus store"}


# ------------------------------------------------------------------ arguments from silence, tested beyond the sample
def _skeptic_review(harness, session_id: str, kind: str, data: dict):
    from types import SimpleNamespace

    from taochronos.agents.procedures import skeptic
    from taochronos.agents.runtime import AgentContext
    from taochronos.kernel.policy import Actor
    from taochronos.protocol import EventType as E
    from taochronos.protocol.hypothesis import Hypothesis, Observation
    from taochronos.protocol.research import GoalSpec, TaskNode

    s = harness.engine().start(GoalSpec(question="q"), session_id=session_id)
    obs = Observation(id=f"obs_{session_id}", kind=kind, title="t", summary="s", detector="test", data=data)
    s.emit(E.OBSERVATION_RECORDED, {"observations": [obs.to_dict()]}, generated=[obs.id])
    hyp = Hypothesis(id=f"hyp_{session_id}", statement="s", kind=kind, observation_ids=[obs.id], terms=[data["left"], data["right"]])
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    actor = Actor(id="agent:skeptic", role="skeptic", principal="agent", permissions=frozenset(harness.specs["skeptic"].permissions))
    task = TaskNode(id="t", kind="falsify", role="skeptic", round=1)
    ctx = AgentContext(harness.runtime, s.view(actor), task, harness.specs["skeptic"], SimpleNamespace(model="m", mode="procedure"),
                       actor, s.transaction(actor, task.id), harness.new_budget())
    h = s.state.hypotheses[hyp.id]
    review = skeptic._review(ctx, h)
    return review, skeptic.verdict(review["objections"], h)


def test_an_association_called_hidden_is_rejected_when_the_scope_states_it(harness):
    # 头痛 ⇢ 桂枝汤 is written in the 伤寒论: 「太阳病，头痛，发热，汗出，恶风，桂枝汤主之」
    review, verdict = _skeptic_review(harness, "attested", "hidden_association",
                                      {"left": "symptom:头痛", "right": "formula:桂枝汤", "via": []})
    attested = [o for o in review["objections"] if o["check"] == "attested"]
    assert attested and attested[0]["severity"] == "critical" and attested[0]["counter"] and verdict == "reject"
    review, _ = _skeptic_review(harness, "unstated", "hidden_association", {"left": "disease:消渴", "right": "formula:麻黄汤", "via": []})
    assert not [o for o in review["objections"] if o["check"] == "attested"]  # a pair the scope never states


def test_a_lost_association_restated_after_its_pivot_is_refuted(harness):
    from taochronos.protocol.hypothesis import objection_kind

    review, verdict = _skeptic_review(harness, "restated", "lost_knowledge",
                                      {"left": "formula:桂枝汤", "right": "symptom:头痛", "kind": "indication", "pivot_year": 100})
    restated = [o for o in review["objections"] if o["check"] == "restated_after"]
    # "no longer stated" is a universal negative: one verified later statement refutes it — critical, and hard
    assert restated and restated[0]["severity"] == "critical" and restated[0]["counter"] and verdict == "reject"
    assert restated[0]["method"] == "falsification:restatement" and objection_kind("restated_after") == "hard"


def test_a_pathogenesis_is_read_where_it_is_stated_not_across_a_drug_entry(harness):
    import dataclasses

    from taochronos.protocol.claims import ClaimRelation

    extractor = harness.capabilities.get("extractor")
    base = harness.corpus.passage("shanghanlun.c071")

    def patho(text: str) -> list:
        claims = extractor.extract(dataclasses.replace(base, id="probe", text=text, variants=[]))
        return [set(c.terms()) for c in claims if c.relation == ClaimRelation.PATHOGENESIS]

    # 白文 of a drug entry: 寒 is the drug's nature and 消渴 what it treats — neither is in the 热毒所生 statement
    assert not any({"etiology:寒", "disease:消渴"} & terms for terms in patho("寒润五脏治消渴开关节服丹石人食之使人免有疮肿及热毒所生也"))
    assert any({"symptom:半身不遂", "pathogenesis:元气亏损"} <= terms for terms in patho("半身不遂，亏损元气，是其本源。"))
