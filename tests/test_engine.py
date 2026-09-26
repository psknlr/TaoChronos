from conftest import make_harness, run_research
from taochronos.kernel import Actor, FaultInjectingStore, MemoryEventStore, SimulatedCrash
from taochronos.verification.provenance import verify_evidence


def test_research_run_invariants(research):
    h, session = research
    state = session.state
    assert state.status in ("completed", "max_rounds")
    assert state.goal.question and state.corpus and state.claims and state.observations
    kinds = {t.kind for t in state.task_graph.values()}
    assert {"scope_corpus", "extract_claims", "mine_patterns", "generate_hypotheses", "falsify", "validate", "score"} <= kinds
    assert all(t.status in ("done", "skipped") for t in state.task_graph.values())
    for hyp in state.hypotheses.values():
        assert hyp.supporting_evidence, hyp.id  # evidence-first
        for eid in hyp.supporting_evidence:
            rec = state.evidence[eid]
            assert rec.book_id == "modern-literature" or not verify_evidence(rec, h.corpus)
        assert hyp.space.value in ("computational_hypothesis", "modern_tcm")
    reviewed = {r.hypothesis_id for r in state.reviews.values()}
    assert {x.id for x in state.hypotheses.values() if x.status != "superseded"} <= reviewed
    revised = [x for x in state.hypotheses.values() if x.parent_id]
    assert revised and all(state.hypotheses[x.parent_id].status == "superseded" for x in revised)
    assert any(x.status == "rejected" for x in state.hypotheses.values())
    for hid in (x.id for x in state.active_hypotheses()):
        assert {"G0", "G4", "G5", "G6", "G7", "G8"} <= set(state.gates[hid])
        assert state.gates[hid]["G7"].status == "pending"  # no machine ever passes the expert gate
    kinds = {a.kind for a in state.artifacts.values()}
    assert {"discovery_report", "evidence_table", "knowledge_graph", "trace"} <= kinds


def test_the_skeptic_rejects_a_differential_diagnosis_link(research):
    _, session = research
    rejected = [x for x in session.state.hypotheses.values() if x.status == "rejected"]
    reviews = [o for x in rejected for r in session.state.reviews_for(x.id) for o in r.objections]
    assert any(o.check in ("differential", "contraindication", "taxonomy") and o.severity == "critical" and o.evidence_ids for o in reviews)


def test_the_mapping_is_proposed_not_committed(research):
    _, session = research
    changes = list(session.state.changes.values())
    assert changes and all(c.status == "proposed" for c in changes)
    assert all(c.payload["relation"] != "equivalent" for c in changes)


def test_report_sections(research):
    h, session = research
    from taochronos.engine.report import build

    report, md, _ = build(h, session.state, session.id)
    titles = [s.title for s in report.sections]
    assert len(titles) == 13 and titles[0].startswith("1. 研究问题") and titles[11].startswith("12. 建议人工核验")
    assert "消渴=糖尿病" in md and "不构成医学结论" in md


def test_runs_are_deterministic_and_replayable(research, tmp_path):
    _, session = research
    again = run_research(make_harness(tmp_path), "ref")
    assert again.state.state_hash() == session.state.state_hash()
    assert session.verify()["consistent"]


def test_crash_and_resume_reaches_the_same_state(research, tmp_path):
    _, session = research
    inner = MemoryEventStore()
    try:
        run_research(make_harness(tmp_path, store=FaultInjectingStore(inner, crash_on_batch=12)), "ref")
        raise AssertionError("expected a simulated crash")
    except SimulatedCrash:
        pass
    h = make_harness(tmp_path, store=inner)
    engine = h.engine()
    resumed = engine.open("ref")
    assert resumed.recovery.discarded_events > 0
    engine.run(resumed)
    assert resumed.state.state_hash() == session.state.state_hash()


def test_branch_expert_review_and_change_decision(tmp_path):
    h = make_harness(tmp_path, overrides={"stop": {"max_rounds": 1}})
    session = run_research(h, "hb")
    engine = h.engine()
    target = next(x for x in session.state.hypotheses.values() if x.status == "survived")
    child, outcome = engine.branch(session, target.id, purpose="test")
    assert outcome["hypothesis_id"] == target.id and session.state.branches[child.id].status == "merged"
    engine.expert_review(session, target.id, approve=True, expert="张三")
    assert session.state.gates[target.id]["G7"].status == "pass"
    change = next(iter(session.state.changes))
    engine.decide_change(session, change, approve=True, actor=Actor.human("张三"))
    assert session.state.changes[change].decided_by == "human:张三"
    assert h.memory.items()


def test_holdout_is_enforced(tmp_path):
    h = make_harness(tmp_path, overrides={"stop": {"max_rounds": 1}})
    session = run_research(h, "ho", holdout_after=1368)
    state = session.state
    assert state.corpus.holdout_passage_ids
    years = [h.corpus.year(h.corpus.passage(e.passage_id)) for e in state.evidence.values() if h.corpus.has_passage(e.passage_id)]
    assert years and max(years) < 1368
    assert all(c.passage_id not in set(state.corpus.holdout_passage_ids) for c in state.claims.values())
