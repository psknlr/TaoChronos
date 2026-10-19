"""Statistics that say what they test: selection-aware drift, source-family sensitivity, layered absence, scoped
novelty, exploration priority (not credibility), typed revisions."""

from __future__ import annotations

from types import SimpleNamespace

from taochronos.agents.procedures.hypothesis import revision_kind
from taochronos.protocol.hypothesis import Hypothesis
from taochronos.science.scoring import explanatory_comparison, novelty_profile, pairwise_tournament
from taochronos.science.stats import (average_linkage, chi2_sf, cluster_bootstrap, context_jsd, cut_tree, kruskal_wallis, largest_gap,
                                      leaf_order, leave_one_cluster_out, max_statistic_permutation, odds_ratio, permutation_test,
                                      spearman, t_two_sided)


def _periods(k: int, n: int, *, shift_at: int | None = None) -> list[list[list[str]]]:
    """k periods of n context samples; with ``shift_at`` the vocabulary changes from that period on."""
    import random

    r = random.Random(5)
    out = []
    for i in range(k):
        vocab = ["a", "b", "c", "d"] if shift_at is None or i < shift_at else ["w", "x", "y", "z"]
        out.append([[r.choice(vocab), r.choice(vocab)] for _ in range(n)])
    return out


def test_the_maximum_over_boundaries_is_tested_as_a_maximum():
    noise = _periods(8, 6)  # no change anywhere: the largest boundary is the largest of seven chance differences
    observed, where, p_max, series = max_statistic_permutation(noise, context_jsd, n=299, seed=1)
    _, p_naive = permutation_test(noise[where], noise[where + 1], context_jsd, n=299, seed=1)
    assert observed == max(series) and len(series) == 7
    assert p_max > p_naive  # the naive test of the chosen boundary overstates it
    real = _periods(6, 12, shift_at=3)
    _, where, p, _ = max_statistic_permutation(real, context_jsd, n=299, seed=1)
    assert where == 2 and p < 0.01


def test_source_family_sensitivity():
    by_family = {"f1": [1, 1, 1, 1], "f2": [1, 0, 1, 0], "f3": [0, 0, 0, 0]}
    rate = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    lofo = leave_one_cluster_out(by_family, rate)
    assert lofo["clusters"] == 3 and lofo["without"]["f1"] < lofo["full"] < lofo["without"]["f3"]
    lo, hi = cluster_bootstrap(by_family, rate, n=199, seed=2)
    assert 0.0 <= lo <= lofo["full"] <= hi <= 1.0


def test_hypotheses_carry_a_statistics_record_and_no_one_minus_p(research):
    _, session = research
    hyps = [h for h in session.state.hypotheses.values() if h.status != "superseded"]
    assert all(h.confidence.statistical is None for h in hyps)
    drift = [h for h in hyps if h.kind == "concept_drift"]
    assert drift and "max-statistic" in drift[0].statistics["method"] and "p_value_naive_chosen_boundary" in drift[0].statistics["sensitivity"]
    lost = [h for h in hyps if h.kind == "lost_knowledge"]
    assert lost and lost[0].statistics["absence"]["level"] in (1, 2, 3)
    assert "leave_one_family_out_p_absence" in lost[0].statistics["sensitivity"] and lost[0].statistics["null"]


def test_novelty_is_scoped_and_never_first_discovery(research):
    _, session = research
    for h in session.state.hypotheses.values():
        if h.novelty_profile:
            assert h.novelty_profile["never_claimed"] == "first discovery"
            assert h.novelty_profile["statement"].startswith(("未在指定范围内发现", "与既有认识"))
    profile = novelty_profile(["disease:消渴", "formula:肾气丸"], [], stated_in_corpus=True)
    assert profile["corpus"].startswith("stated") and "重叠" in profile["statement"]


def test_exploration_priority_compares_explanations_not_scores():
    strong = {"defeaters": 0, "confirmation": 1, "families": 3, "rivals": 2, "assumptions": 1}
    weak = {"defeaters": 1, "confirmation": 0, "families": 5, "rivals": 4, "assumptions": 0}
    assert explanatory_comparison(strong, weak) == 1.0  # a live defeater outweighs anything else
    assert explanatory_comparison(dict(strong, confirmation=-1), dict(strong)) == 0.0
    assert explanatory_comparison(strong, dict(strong)) == 0.5
    elo, matches = pairwise_tournament({"s": strong, "w": weak, "m": dict(strong, families=1)}, rounds=2, seed=0)
    assert elo["s"] > elo["m"] > elo["w"] and len(matches) == 6


def test_the_ranking_event_says_what_the_rating_means(research):
    _, session = research
    ranked = [e for e in session.events() if e.type == "HypothesisRanked"]
    assert ranked and all("not credibility" in e.payload["meaning"] for e in ranked)


def test_revisions_are_typed():
    parent = Hypothesis(id="hyp_p", statement="A 与 B 相关", kind="hidden_association", terms=["symptom:A", "formula:B"])
    kind, changed = revision_kind(parent, "在所考察的语料范围内，A 与 B 相关", parent.terms, parent.kind, {"scope": "surveyed_corpus"})
    assert kind == "restricting" and set(changed) == {"statement", "qualifiers"}
    kind, _ = revision_kind(parent, "A 与 C 相关", ["symptom:A", "formula:C"], parent.kind, {"scope": "surveyed_corpus"})
    assert kind == "substantive"
    kind, _ = revision_kind(parent, "A 与 B 相关，且 C 亦然", parent.terms, parent.kind, {})
    assert kind == "substantive"  # a new statement with no narrowing qualifier is a new claim
    kind, _ = revision_kind(parent, parent.statement, parent.terms, parent.kind, {"mechanism": "x"})
    assert kind == "substantive"  # "mechanism" is not a narrowing axis


def test_revised_children_record_what_changed_and_what_is_void(research):
    _, session = research
    children = [h for h in session.state.hypotheses.values() if h.parent_id]
    assert children
    for c in children:
        assert c.revision_kind in ("restricting", "substantive") and c.changed_fields and c.invalidated
        parent = session.state.hypotheses[c.parent_id]
        assert parent.status == "superseded" and c.id != parent.id
        if c.revision_kind == "restricting":
            assert set(c.supporting_evidence) >= set(parent.supporting_evidence) and c.qualifiers
    # the child's id depends on its content: another statement gives another id
    from taochronos.protocol.base import stable_id

    c = children[0]
    assert stable_id("hyp", c.parent_id, "rev", c.generation, c.qualifiers, c.statement + "!", sorted(c.terms)) != c.id


def test_skeptic_flags_an_absence_resting_on_one_family(harness):
    from taochronos.agents.procedures import skeptic
    from taochronos.agents.runtime import AgentContext
    from taochronos.kernel.policy import Actor
    from taochronos.protocol import EventType as E
    from taochronos.protocol.hypothesis import Observation
    from taochronos.protocol.research import GoalSpec, TaskNode

    s = harness.engine().start(GoalSpec(question="q"), session_id="lofo")
    stats = {"p_absence": 0.01, "sensitivity": {"leave_one_family_out_p_absence": {"max": 0.2, "clusters": 2}}}
    obs = Observation(id="obs_lofo", kind="lost_knowledge", title="t", summary="s", detector="test",
                      data={"left": "disease:消渴", "right": "herb:黄连", "pivot_year": 960}, statistics=stats)
    s.emit(E.OBSERVATION_RECORDED, {"observations": [obs.to_dict()]}, generated=[obs.id])
    hyp = Hypothesis(id="hyp_lofo", statement="s", kind="lost_knowledge", observation_ids=[obs.id], terms=["disease:消渴", "herb:黄连"])
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    actor = Actor(id="agent:skeptic", role="skeptic", principal="agent", permissions=frozenset(harness.specs["skeptic"].permissions))
    task = TaskNode(id="t", kind="falsify", role="skeptic", round=1)
    ctx = AgentContext(harness.runtime, s.view(actor), task, harness.specs["skeptic"], SimpleNamespace(model="m", mode="procedure"),
                       actor, s.transaction(actor, task.id), harness.new_budget())
    review = skeptic._review(ctx, s.state.hypotheses[hyp.id])
    flagged = [o for o in review["objections"] if o["check"] == "transcription_dependence" and "单一来源家族" in o["detail"]]
    assert flagged and flagged[0]["severity"] == "major"


# ------------------------------------------------------------------ the tests the figures and tables report
def test_the_distributions_give_the_textbook_critical_values():
    assert abs(chi2_sf(3.841458820694124, 1) - 0.05) < 1e-12 and abs(chi2_sf(11.070497693516351, 5) - 0.05) < 1e-12
    assert chi2_sf(0, 3) == 1.0 and chi2_sf(100, 2) < 1e-20
    assert abs(t_two_sided(2.228138851986274, 10) - 0.05) < 1e-12 and abs(t_two_sided(2.0, 10) - 0.073388) < 1e-6


def test_kruskal_wallis_as_r_computes_it():
    # R: kruskal.test(list(x, y, z)) of its documentation — chi-squared = 0.77143, df = 2, p-value = 0.68
    kw = kruskal_wallis([[2.9, 3.0, 2.5, 2.6, 3.2], [3.8, 2.7, 4.0, 2.4], [2.8, 3.4, 3.7, 2.2, 2.0]])
    assert kw["h"] == 0.771 and kw["df"] == 2 and abs(kw["p"] - 0.68) < 0.001 and kw["n"] == 14
    assert kruskal_wallis([[1, 1, 2], [2, 3, 3], [1, 3]])["h"] == 3.111  # ties corrected
    assert kruskal_wallis([[1, 1], [1]]) is None and kruskal_wallis([[1, 2, 3]]) is None


def test_spearman_and_the_odds_ratio():
    s = spearman(list(range(1, 11)), [2, 1, 4, 3, 6, 5, 8, 7, 10, 9])
    assert s["rho"] == 0.9394 and s["p"] < 1e-4 and s["n"] == 10
    assert spearman([1, 2, 3], [1, 2, 3]) is None and spearman([1, 2, 3, 4], [5, 5, 5, 5]) is None
    o = odds_ratio(10, 20, 30, 40)
    assert abs(o["or"] - 2 / 3) < 1e-12 and abs(o["lo"] - 0.2725) < 1e-4 and abs(o["hi"] - 1.6309) < 1e-4 and not o["corrected"]
    assert odds_ratio(0, 5, 5, 5)["corrected"]  # a zero cell: 0.5 added to every cell


def test_average_linkage_its_order_and_its_cut():
    pts = [0, 1, 5, 6, 20]
    merges = average_linkage([[abs(a - b) for b in pts] for a in pts])
    assert merges == [[0, 1, 1.0, 2], [2, 3, 1.0, 2], [5, 6, 5.0, 4], [4, 7, 17.0, 5]]  # {0,1}–{5,6}: (5+6+4+5)/4
    assert leaf_order(merges, 5) == [0, 1, 2, 3, 4]  # the cluster holding the first item first
    assert cut_tree(merges, 5, 2) == [0, 0, 0, 0, 1] and cut_tree(merges, 5, 3) == [0, 0, 1, 1, 2]
    assert largest_gap(merges, 5) == 2  # 5 → 17 is the longest branch


def test_fisher_stops_where_the_terms_no_longer_change_the_sum():
    """The one-sided Fisher test stops once a term past the mode is below 1e-17 of the sum: the value is the full sum's,
    bit for bit (each later term is under half the sum's last place)."""
    import math
    import random

    from taochronos.science.stats import fisher_exact_greater

    def full(a: int, b: int, c: int, d: int) -> float:  # every term, added in order (as the test always added them)
        row1, col1, n = a + b, a + c, a + b + c + d
        lc = lambda m, k: math.lgamma(m + 1) - math.lgamma(k + 1) - math.lgamma(m - k + 1)  # noqa: E731
        p = 0.0
        for x in range(a, min(row1, col1) + 1):
            p += math.exp(lc(row1, x) + lc(n - row1, col1 - x) - lc(n, col1))
        return min(1.0, p)

    rnd = random.Random(3)
    tables = [tuple(rnd.randint(0, rnd.choice([4, 40, 400, 4000])) for _ in range(4)) for _ in range(3000)]
    assert all(fisher_exact_greater(*t) == full(*t) for t in tables)
