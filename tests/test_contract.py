"""The executable research contract: execution is not acceptance; warrants; confirmation on withheld material."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from conftest import make_harness, run_research
from taochronos.agents.procedures import curator
from taochronos.agents.runtime import AgentContext
from taochronos.engine.confirmation import check_prediction
from taochronos.kernel.policy import Actor
from taochronos.protocol import EventType as E
from taochronos.protocol.contract import AcceptanceSpec, ConfirmationSpec
from taochronos.protocol.hypothesis import Prediction
from taochronos.protocol.research import GoalSpec, TaskNode
from taochronos.protocol.warrant import ALTERNATIVES, DISCOVERY_TYPE
from taochronos.verification.contract import evaluate_contract, judge_hypothesis


def test_execution_is_not_acceptance(research):
    h, session = research
    state = session.state
    acc = state.acceptance
    assert acc["execution"] == state.stop["status"] and acc["status"] in ("needs_expert", "inconclusive", "research_accepted")
    assert acc["status"] != "research_accepted"  # nobody approved anything (G7) in the reference run
    live = [x for x in state.hypotheses.values() if x.status != "superseded"]
    assert {j["hypothesis_id"] for j in acc["hypotheses"]} == {x.id for x in live}
    for j in acc["hypotheses"]:
        assert j["version"] == state.hypotheses[j["hypothesis_id"]].version()
        assert all(c["judge"] in ("validator:contract", "human") and c["failure_state"] for c in j["criteria"])
    assert all(acc["outputs"].values()) and state.run_manifest["phase"] == "end"
    report = next(a for a in state.artifacts.values() if a.kind == "discovery_report" and a.path.endswith(".md"))
    text = h.artifacts.read(report).decode("utf-8")
    assert "研究合同评估" in text and "研究结论" in text and "探索优先级" in text


def test_an_expert_turns_needs_expert_into_acceptance(research):
    h, session = research
    state = session.state
    waiting = [j for j in state.acceptance["hypotheses"] if j["status"] == "needs_expert"
               and all(c["status"] == "pass" for c in j["criteria"] if c["id"] != "expert_review")]
    assert waiting, "the reference run has hypotheses that meet every machine criterion"
    child = session.fork(purpose="expert review", record_in_parent=False, new_session_id="ref.expert-probe")
    h.engine().expert_review(child, waiting[0]["hypothesis_id"], approve=True, expert="审稿专家")
    again = evaluate_contract(child.state, execution="completed")
    assert again.status == "research_accepted" and waiting[0]["hypothesis_id"] in again.accepted()


def test_a_gate_computed_on_an_earlier_version_does_not_count(research):
    _, session = research
    state = session.state
    hid = next(j["hypothesis_id"] for j in state.acceptance["hypotheses"] if j["status"] == "needs_expert")
    hyp = state.hypotheses[hid]
    stale = hyp.replace(statement=hyp.statement + "（改）")  # the same id, a different version
    judged = judge_hypothesis(SimpleNamespace(**{**state.__dict__, "hypotheses": {**state.hypotheses, hid: stale}},
                                              reviews_for=state.reviews_for), stale)
    crit = {c.id: c for c in judged.criteria}
    assert crit["current_version_gates"].status == "fail" and "stale" in crit["current_version_gates"].observed
    assert crit["alternatives_addressed"].status == "fail"  # the warrant, too, was built on the earlier version


def test_a_foundation_only_run_is_formally_inconclusive(tmp_path):
    h = make_harness(tmp_path)
    s = run_research(h, "foundation", stop={"max_rounds": 0})
    assert s.state.stop["status"] == "completed" and s.state.acceptance["status"] == "inconclusive"
    reasons = " ".join(s.state.acceptance["reasons"])
    assert "no hypothesis was produced" in reasons and "candidate_hypotheses" in reasons


def test_every_hypothesis_has_a_warrant_with_its_types_rivals(research):
    _, session = research
    state = session.state
    for hyp in (x for x in state.hypotheses.values() if x.status != "superseded"):
        w = state.warrants[hyp.warrant_id]
        assert w["hypothesis_version"] == hyp.version() and w["inference"] and w["strength"] in ("consistent_with", "supported", "robust")
        dtype = DISCOVERY_TYPE.get(hyp.kind, "new_use")
        assert [c["id"] for c in w["competing"]] == [a["id"] for a in ALTERNATIVES[dtype]]
        assert all(c["status"] in ("excluded", "open", "not_applicable", "unaddressed") and c["basis"] for c in w["competing"])
        assert set(w["supporting"]) <= set(hyp.supporting_evidence)
    decline = [state.warrants[x.warrant_id] for x in state.hypotheses.values() if x.kind == "lost_knowledge" and x.warrant_id]
    assert decline and {c["id"] for c in decline[0]["competing"]} == {"coverage", "genre", "renaming", "transcription_omission", "survival_bias"}


def test_confirmation_material_is_withheld_and_used_to_retest(tmp_path):
    h = make_harness(tmp_path)
    s = run_research(h, "confirm", confirmation=ConfirmationSpec(fraction=0.3, seed=7))
    manifest = s.state.corpus
    held = set(manifest.confirmation_passage_ids)
    assert held and not held & set(manifest.passage_ids)
    assert not [e for e in s.state.evidence.values() if e.passage_id in held]  # exploration never cited it
    confirmed = [x for x in s.state.hypotheses.values() if x.confirmation]
    assert confirmed and all(x.confirmation["status"] in ("confirmed", "refuted", "untestable") for x in confirmed)
    for j in s.state.acceptance["hypotheses"]:
        conf = next((c for c in j["criteria"] if c["id"] == "confirmation"), None)
        if conf is not None and "fails" in conf["observed"]:
            assert j["status"] in ("inconclusive", "rejected")
    # the families are independent: no family is on both sides
    from taochronos.tools.adapters import author_clusters

    cluster = author_clusters(h.corpus)
    side = lambda ids: {cluster(h.corpus.passage(p).book_id) for p in ids}  # noqa: E731
    assert not side(held) & side(manifest.passage_ids)


def test_check_prediction_says_when_material_cannot_decide(harness):
    claims = [c for p in harness.corpus.passages() for c in harness.capabilities.get("extractor").extract(p, harness.philology.assess(p))]
    hyp = SimpleNamespace(terms=[])
    silent = Prediction(kind="absent_after", subject="herb:不存在的药", object="symptom:渴", description="")
    assert check_prediction(silent, hyp, claims, harness, []) is None
    present = next(c for c in claims if len({a.term_id for a in c.arguments if a.term_id}) >= 2)
    a, b = sorted({x.term_id for x in present.arguments if x.term_id and not x.negated})[:2]
    assert check_prediction(Prediction(kind="absent_after", subject=a, object=b, description=""), hyp, claims, harness, []) is False
    assert check_prediction(Prediction(kind="link_appears", subject=a, object=b, description=""), hyp, claims, harness, []) is True


def test_the_curator_cannot_release_what_the_contract_withholds(harness):
    h = harness
    goal = GoalSpec(question="q", holdout_after=1000, confirmation=ConfirmationSpec(fraction=0.3))
    s = h.engine().start(goal, session_id="curator-probe")
    s.emit(E.TASK_PLANNED, {"tasks": [TaskNode(id="r0.scope_corpus", kind="scope_corpus", role="curator").to_dict()]})
    actor = Actor(id="agent:curator", role="curator", principal="agent", permissions=frozenset({"classics:read"}))
    task = TaskNode(id="r0.scope_corpus", kind="scope_corpus", role="curator")
    ctx = AgentContext(h.runtime, s.view(actor), task, h.specs["curator"], SimpleNamespace(model="m", mode="llm"), actor,
                       s.transaction(actor, task.id), h.new_budget())
    honest = curator.draft(ctx)
    # a model returns every passage as exploration material and nothing withheld
    greedy = {**honest, "passage_ids": sorted(set(honest["passage_ids"]) | set(honest["holdout_passage_ids"])), "holdout_passage_ids": []}
    curator.commit(ctx, greedy)
    ctx.tx.commit()
    m = s.state.corpus
    assert set(m.holdout_passage_ids) == set(honest["holdout_passage_ids"]) and not set(m.passage_ids) & m.withheld()
    assert m.confirmation_passage_ids  # the contract's confirmation split happened regardless


def test_a_report_cannot_present_hypotheses_judged_on_another_version(research):
    h, session = research
    child = session.fork(purpose="publish probe", record_in_parent=False, new_session_id="ref.publish-probe")
    hid = next(iter(x.id for x in child.state.hypotheses.values() if x.status == "survived"))
    ev = child.state.hypotheses[hid].supporting_evidence[0]
    child.emit(E.EVIDENCE_RETRACTED, {"evidence_ids": [ev], "reason": "probe"}, actor=Actor.validator("probe"))  # the version changes
    from taochronos.kernel.artifacts import ArtifactBlocked

    with pytest.raises(ArtifactBlocked):
        h.artifacts.publish(child, kind="discovery_report", title="Stale", content="x", filename="r.md", media_type="text/markdown",
                            generator="probe", evidence_refs=[e for e in child.state.evidence if e not in child.state.retractions][:1],
                            hypothesis_refs=[hid])


def test_contract_criteria_are_switchable_but_never_silent(research):
    _, session = research
    state = session.state
    lenient = SimpleNamespace(**{**state.__dict__, "goal": state.goal.replace(acceptance=AcceptanceSpec(
        semantic_support_checked=False, alternatives_required=False, expert_review_required_for_publication=False))},
        reviews_for=state.reviews_for)
    judged = judge_hypothesis(lenient, next(x for x in state.hypotheses.values() if x.status == "survived"))
    ids = {c.id for c in judged.criteria}
    assert "semantic_support" not in ids and "expert_review" not in ids and "unresolved_hard_objections" in ids
