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
        assert {"G0", "G4", "G5", "G6", "G8"} <= set(state.gates[hid])
        # no machine ever writes the expert gate: G7 exists only once a human decided, and here none did
        assert "G7" not in state.gates[hid] and state.gate_status(hid, "G7") == "pending"
        assert all(r.subject_version == state.hypotheses[hid].version() for g, r in state.gates[hid].items() if g != "G7")
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
    assert len(titles) == 14 and titles[0].startswith("1. 研究问题") and titles[12].startswith("12. 建议人工核验")
    assert titles[1].startswith("研究合同评估")  # the verdict comes right after the question: execution is not acceptance
    assert "消渴=糖尿病" in md and "不构成医学结论" in md


def test_a_ledger_notes_labels_and_the_evidence_tables_note_column(research):
    """note_labels: the labels of a search hit's note (agents/procedures/evidence.py hit_note) — the parts after
    ``routes: …`` — and none of any other note.  The evidence table keeps its columns and adds each record's note last,
    a note that would start a spreadsheet formula kept text."""
    import csv
    import io
    from dataclasses import replace
    from types import SimpleNamespace

    from taochronos.engine.report import evidence_table, note_labels

    assert note_labels("routes: bm25,dense") == [] and note_labels("") == [] and note_labels(None) == []
    assert note_labels("routes: alias; via 国老→甘草（别名录（中醫笈成））; 年代存疑（甘草约 1180 年后才通行；或经后世刊本改字）") == [
        "via 国老→甘草（别名录（中醫笈成））", "年代存疑（甘草约 1180 年后才通行；或经后世刊本改字）"]
    assert note_labels("early attestation") == [] and note_labels("same findings, same formula; via 国老→甘草") == []
    assert note_labels("routes: bm25; ; via 国老→甘草（词表）\n; routes: alias") == ["via 国老→甘草（词表）"]
    h, session = research
    rows = list(csv.reader(io.StringIO(evidence_table(h, session.state))))
    assert rows[0] == ["evidence_id", "hypothesis_id", "stance", "book", "passage_id", "locator", "start", "end", "quote", "year",
                       "retrieval_method", "evidence_domain", "textual", "philological", "gates", "note"]
    notes = {r[0]: r[-1] for r in rows[1:]}
    assert notes == {e.id: e.note for e in session.state.evidence.values()} and any(notes.values())
    rec = next(iter(session.state.evidence.values()))
    for note, cell in (("=HYPERLINK(1)", "'=HYPERLINK(1)"), ("-1", "'-1"), ("routes: bm25", "routes: bm25")):
        one = SimpleNamespace(evidence={rec.id: replace(rec, note=note)}, gates={})
        assert list(csv.reader(io.StringIO(evidence_table(h, one))))[1][-1] == cell


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
