"""The architecture audit's counterexamples, as regression tests.

Each test names the probe it answers (P01–P10 of the audit reproduction package).  The invariant is the same every
time: an error is refused at the right boundary, and nothing of it reaches the state or the log.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from taochronos.agents.procedures import extractor, skeptic
from taochronos.agents.runtime import AgentContext
from taochronos.engine.validation import VALIDATOR, adjudicate_objections
from taochronos.kernel import MemoryEventStore, Session
from taochronos.kernel.hooks import HookPoint, HookRegistry, HookResult
from taochronos.kernel.policy import Actor, PolicyEngine
from taochronos.kernel.reducer import InvalidEvent
from taochronos.kernel.session import SessionView, StateView
from taochronos.kernel.tools import ToolCall, ToolRegistry, ToolScheduler, ToolSpec
from taochronos.plugins.sandbox import isolation
from taochronos.plugins.sandbox.subprocess_sandbox import NamespaceSandbox, SandboxRouter, SandboxUnavailable, SubprocessSandbox
from taochronos.protocol import EventType as E
from taochronos.protocol.claims import ClaimRelation
from taochronos.protocol.concepts import EvidenceDomain, KnowledgeSpace
from taochronos.protocol.evidence import EvidenceRecord, Stance
from taochronos.protocol.hypothesis import Hypothesis
from taochronos.protocol.research import CorpusManifest, GoalSpec, TaskNode
from taochronos.verification.provenance import verify_claim, verify_evidence
from taochronos.verification.scope import ScopedCorpusView, scope_for

AGENT = Actor(id="agent:probe", role="scholar", principal="agent", permissions=frozenset({"classics:read", "kg:read", "analysis:run"}))


def _session(h, sid: str, keep: int | None = None) -> Session:
    ps = list(h.corpus.passages())
    s = h.engine().start(GoalSpec(question="边界回归测试"), session_id=sid)
    chosen = ps if keep is None else ps[:keep]
    ids = {p.id for p in chosen}
    manifest = CorpusManifest(book_ids=sorted({p.book_id for p in chosen}), passage_ids=sorted(ids),
                              holdout_passage_ids=[p.id for p in ps if p.id not in ids])
    s.emit(E.CORPUS_SCOPED, {"manifest": manifest.to_dict()})
    return s


def _ctx(h, s: Session, role: str) -> AgentContext:
    task = TaskNode(id=f"probe.{role}", kind="probe", role=role, round=1)
    actor = Actor(id=f"agent:probe-{role}", role=role, principal="agent", permissions=frozenset(h.specs[role].permissions))
    route = SimpleNamespace(model="offline-probe", mode="hybrid")
    return AgentContext(h.runtime, s.view(actor), task, h.specs[role], route, actor, s.transaction(actor, task.id), h.new_budget())


# --------------------------------------------------------------------- P01
def test_p01_withheld_passages_are_unreachable_through_every_read_path(harness):
    h = harness
    s = _session(h, "p01", keep=1)
    held = list(h.corpus.passages())[-1]
    assert held.id in s.state.corpus.holdout_passage_ids
    run = lambda name, **a: h.scheduler.execute(ToolCall(name, a), actor=AGENT, session=s.view(AGENT))  # noqa: E731
    # the audit's route: provenance inspection returned the held-out text — now refused before it runs
    for name, args in [("philology.inspect_page", {"object_id": held.id}), ("classics.get_passage", {"passage_id": held.id}),
                       ("philology.assess_passage", {"passage_id": held.id}),
                       ("philology.collate", {"passage_a": held.id, "passage_b": held.id})]:
        out = run(name, **args)
        assert not out.ok and out.result is None, name
    # a search cannot surface it, and a quote check cannot confirm it
    out = run("classics.search", query=held.text[:6], k=50)
    assert out.ok and held.id not in {x["passage_id"] for x in out.result["hits"]}
    out = run("validation.verify_quote", quote=held.text[:8])
    assert out.ok and all(x["passage_id"] != held.id for x in out.result)
    # the data layer itself: a withheld passage does not exist from the reader's view
    view = ScopedCorpusView(h.corpus, scope_for(s.state, "agent"))
    assert not view.has_passage(held.id) and held.id not in {p.id for p in view.passages()}
    with pytest.raises(PermissionError):
        view.passage(held.id)
    # humans and the kernel see everything; validators see confirmation material, never the hold-out's future
    assert scope_for(s.state, "human").permits(held.id) and not scope_for(s.state, "validator").permits(held.id)


def test_p01_reading_on_names_no_passage_the_reader_may_not_read(harness):
    """get_passage's prev and next name only passages the reader may read: a neighbour held out is None, and the passage
    is read — the result firewall finds nothing to withhold."""
    h = harness
    s = _session(h, "p01-reading-on", keep=1)
    seen = list(h.corpus.passages())[0]
    before, _, after = h.corpus.around(seen.id)
    assert {before, after} - {None} and {before, after} - {None} <= set(s.state.corpus.holdout_passage_ids)
    out = h.scheduler.execute(ToolCall("classics.get_passage", {"passage_id": seen.id}), actor=AGENT, session=s.view(AGENT))
    assert out.ok and (out.result["prev"], out.result["next"]) == (None, None)


def test_p01_the_result_firewall_withholds_any_tool_output_naming_withheld_material(harness):
    h = harness
    s = _session(h, "p01b", keep=1)
    held = list(h.corpus.passages())[-1]
    reg = ToolRegistry()
    reg.register(ToolSpec("leaky.echo", "returns a withheld id from somewhere", {"type": "object"},
                          lambda ctx, a: {"hits": [{"passage_id": held.id, "text": held.text}]}, permission="classics:read"))
    sched = ToolScheduler(reg, PolicyEngine(), h.hooks, h.capabilities, views=h.scheduler.views)
    out = sched.execute(ToolCall("leaky.echo", {}), actor=AGENT, session=s.view(AGENT))
    assert not out.ok and out.result is None and out.quarantine and out.quarantine["hook"] == "scope_firewall"
    assert out.receipt["quarantined"] is True
    assert any(e.type == E.HOOK_BLOCKED.value and e.payload.get("point") == "AfterToolCall" for e in s.events())


def test_p01_a_later_manifest_cannot_release_withheld_material(harness):
    s = _session(harness, "p01c", keep=1)
    released = s.state.corpus.to_dict()
    released["passage_ids"] = sorted(set(released["passage_ids"]) | set(released["holdout_passage_ids"]))
    released["holdout_passage_ids"] = []
    before = s.seq
    with pytest.raises(InvalidEvent):
        s.emit(E.CORPUS_SCOPED, {"manifest": released})
    assert s.seq == before and s.state.corpus.holdout_passage_ids


# --------------------------------------------------------------------- P02
def test_p02_a_true_quote_with_a_false_relation_is_refused_at_commit(harness):
    h = harness
    s = _session(h, "p02")
    passage = h.corpus.passage("shanghanlun.c013")
    original = next(c for c in h.capabilities.get("extractor").extract(passage, h.philology.assess(passage))
                    if c.relation == ClaimRelation.INDICATED_FOR and len(c.arguments) >= 2 and not verify_claim(c, h.corpus, h.pack.variants.normalize_text))
    proposal = {"passage_id": original.passage_id, "quote": original.quote, "relation": "contraindicated",
                "arguments": [{"role": a.role.value, "surface": a.surface, "negated": a.negated} for a in original.arguments if a.start is not None]}
    ctx = _ctx(h, s, "extractor")
    summary = extractor.commit(ctx, {"claims": [proposal]})
    ctx.tx.commit()
    assert "0 claims committed" in summary and not s.state.claims
    rejection = next(iter(s.state.rejected_claims.values()))
    assert "semantic_support" in rejection["reason"] and "indicated" in rejection["reason"]
    # and the gate says so on its own, layer by layer: authentic quote, contradicted relation
    false = original.replace(relation=ClaimRelation.CONTRAINDICATED)
    g4 = h.gates(s.state).g4(false)
    assert g4.status == "fail" and g4.layers["authenticity"] == "pass" and g4.layers["support"] == "contradicts"
    assert h.gates(s.state).g4(original).layers["support"] == "supports"


def test_p02_committed_claims_carry_their_statement_frame(research):
    _, session = research
    claims = list(session.state.claims.values())
    assert claims and all(c.support.get("verdict") in ("supports", "insufficient", "ambiguous") for c in claims)
    assert all(c.stance in ("asserted", "reported", "rejected") for c in claims)
    assert any(c.conditions for c in claims) and any(c.temporal_scope for c in claims)


# --------------------------------------------------------------------- P03
def _reviewed(h, sid: str, check: str = "provenance", severity: str = "critical"):
    s = _session(h, sid)
    hyp = Hypothesis(id=f"hyp_{sid}", statement="审计用候选假说", kind="hidden_association")
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    ctx = _ctx(h, s, "skeptic")
    objection = {"check": check, "detail": "deterministic check failed", "severity": severity}
    ctx.draft = {"reviews": [{"hypothesis_id": hyp.id, "verdict": "reject", "objections": [objection], "checks_run": [check]}]}
    return s, hyp, ctx, objection


def test_p03_a_model_cannot_close_a_critical_objection(harness):
    h = harness
    s, hyp, ctx, objection = _reviewed(h, "p03")
    # the untrusted model echoes the objection as resolved, softened, and says the hypothesis survives
    output = {"reviews": [{"hypothesis_id": hyp.id, "verdict": "survives",
                           "objections": [{**objection, "severity": "minor", "resolved": True, "resolution": "model says resolved"}],
                           "checks_run": ["provenance"]}]}
    skeptic.commit(ctx, output)
    ctx.tx.commit()
    review = s.state.reviews_for(hyp.id)[0]
    o = review.objections[0]
    assert review.verdict == "reject" and o.severity == "critical" and o.status == "resolution_proposed" and not o.resolved
    assert o.proposal["rationale"] == "model says resolved"
    g6 = next(g for g in h.gates(s.state).evaluate_hypothesis(s.state.hypotheses[hyp.id], s.state) if g.gate == "G6")
    assert g6.status == "fail"


def test_p03_only_a_validator_rerun_closes_a_hard_objection(harness):
    h = harness
    s, hyp, ctx, _ = _reviewed(h, "p03b")
    skeptic.commit(ctx, ctx.draft)
    ctx.tx.commit()
    review = s.state.reviews_for(hyp.id)[0]
    base = {"hypothesis_id": hyp.id, "review_id": review.id, "objection_id": review.objections[0].id}
    # an agent may not close it, an expert may not close a hard one, a validator may not close it without a passing re-run
    with pytest.raises(InvalidEvent):
        s.emit(E.OBJECTION_CLOSED, {**base, "method": "validator_rerun", "rerun": {"status": "pass"}}, actor=AGENT)
    with pytest.raises(InvalidEvent):
        s.emit(E.OBJECTION_CLOSED, {**base, "method": "expert"}, actor=Actor.human("expert"))
    with pytest.raises(InvalidEvent):
        s.emit(E.OBJECTION_CLOSED, {**base, "method": "validator_rerun", "rerun": {"status": "fail"}}, actor=VALIDATOR)
    # the adjudicating validator re-runs provenance: the hypothesis has no verifiable support, so it stays open
    tx = s.transaction(VALIDATOR, "adjudicate")
    summary = adjudicate_objections(h, s.state, tx)
    tx.commit()
    assert "0 closed" in summary and s.state.reviews_for(hyp.id)[0].objections[0].is_open


def test_p03_an_interpretive_objection_closes_by_a_verified_narrowing_or_an_expert(harness):
    h = harness
    s, hyp, ctx, _ = _reviewed(h, "p03c", check="single_source", severity="major")
    child = hyp.replace(id="hyp_p03c_child", parent_id=hyp.id, generation=1, qualifiers={"scope": "surveyed_corpus"},
                        revision_kind="restricting")
    s.emit(E.HYPOTHESIS_REVISED, {"hypothesis": child.to_dict()}, generated=[child.id])
    ctx.draft = {"reviews": [{"hypothesis_id": child.id, "verdict": "survives", "checks_run": ["single_source"],
                              "objections": [{"check": "single_source", "detail": "仅有 1 个独立来源", "severity": "major"}]}]}
    skeptic.commit(ctx, ctx.draft)
    ctx.tx.commit()
    o = s.state.reviews_for(child.id)[0].objections[0]
    assert o.status == "resolution_proposed" and o.proposal["basis"] == "qualifier" and not o.resolved
    tx = s.transaction(VALIDATOR, "adjudicate")
    adjudicate_objections(h, s.state, tx)
    tx.commit()
    o = s.state.reviews_for(child.id)[0].objections[0]
    assert o.resolved and o.closure == "scope_restriction" and o.closed_by == VALIDATOR.id


# --------------------------------------------------------------------- P04
def test_p04_an_after_tool_call_denial_withholds_the_result():
    reg, hooks = ToolRegistry(), HookRegistry()
    reg.register(ToolSpec("audit.read", "canary", {"type": "object"}, lambda ctx, a: {"canary": "not_allowed"}, permission="research:read"))
    hooks.register(HookPoint.AFTER_TOOL_CALL, "reject_result", lambda ctx: HookResult(allow=False, reason="artificial output rejection"))
    s = Session.create(MemoryEventStore(), "p04")
    out = ToolScheduler(reg, PolicyEngine(), hooks, None).execute(ToolCall("audit.read", {}), actor=Actor.kernel(), session=s)
    assert not out.ok and out.result is None and "reject_result" in out.error
    assert out.quarantine["result_sha256"] and out.receipt["result_sha256"] is None
    results = [e for e in s.events() if e.type == E.TOOL_RESULT.value]
    assert results and results[-1].payload["ok"] is False and results[-1].payload["receipt"]["quarantined"] is True


def test_every_tool_call_leaves_a_receipt(harness):
    s = _session(harness, "receipts")
    out = harness.scheduler.execute(ToolCall("classics.list_books", {}), actor=AGENT, session=s.view(AGENT))
    r = out.receipt
    assert out.ok and r["tool"] == "classics.list_books" and r["arguments_sha256"] and r["result_sha256"] and r["principal"] == "agent"


# --------------------------------------------------------------------- P05
needs_namespaces = pytest.mark.skipif(not isolation.namespace_available(), reason="unprivileged user namespaces unavailable")


@needs_namespaces
def test_p05_model_code_cannot_touch_the_filesystem_outside_its_workspace(tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text("AUDIT_CANARY")
    router = SandboxRouter([SubprocessSandbox(tmp_path / "sbx"), NamespaceSandbox(tmp_path / "sbx")])
    code = (f"import socket\nout = {{}}\n"
            f"try:\n    out['read'] = open({str(canary)!r}).read()\nexcept Exception as e:\n    out['read'] = type(e).__name__\n"
            f"try:\n    open({str(canary)!r}, 'w').write('CHANGED')\n    out['write'] = 'ok'\nexcept Exception as e:\n    out['write'] = type(e).__name__\n"
            "try:\n    open('/work/mine.txt', 'w').write('x')\n    out['workspace'] = 'ok'\nexcept Exception as e:\n    out['workspace'] = type(e).__name__\n"
            "try:\n    open('/usr/probe', 'w').write('x')\n    out['usr'] = 'ok'\nexcept Exception as e:\n    out['usr'] = type(e).__name__\n"
            "try:\n    socket.create_connection(('1.1.1.1', 80), timeout=2)\n    out['net'] = 'ok'\nexcept Exception as e:\n    out['net'] = type(e).__name__\n"
            "result = out")
    run = router.run(code, origin="model", session_id="p05", timeout=30)
    assert run["tier"] == "namespace" and run["ok"], run["stderr"]
    r = run["result"]
    assert r["read"] == "FileNotFoundError" and r["write"] == "FileNotFoundError" and r["workspace"] == "ok"
    assert r["usr"] != "ok" and r["net"] != "ok"
    assert canary.read_text() == "AUDIT_CANARY"


def test_p05_untrusted_code_is_refused_when_no_isolating_tier_exists(tmp_path, monkeypatch):
    monkeypatch.setitem(isolation._NS_CACHE, "ok", False)
    router = SandboxRouter([SubprocessSandbox(tmp_path), NamespaceSandbox(tmp_path)])
    with pytest.raises(SandboxUnavailable):
        router.run("result = 1", origin="model")
    assert router.run("result = 41 + 1", origin="trusted")["result"] == 42  # the system's own snippet: process tier
    assert {t["tier"]: t["available"] for t in router.tiers()} == {"namespace": False, "process": True}


@needs_namespaces
def test_p05_code_mode_runs_isolated_and_calls_tools_through_the_scheduler(harness):
    actor = Actor(id="agent:cm", role="director", principal="agent", permissions=frozenset({"classics:read", "codemode:exec"}))
    code = "hits = classics.search(query='消渴', k=2)\nreturn [h['passage_id'] for h in hits['hits']]"
    out = harness.scheduler.execute(ToolCall("research.run_code", {"code": code}), actor=actor)
    assert out.ok and out.result["tier"] == "namespace" and len(out.result["result"]) == 2
    assert out.result["tool_calls"][0]["tool"] == "classics.search"
    denied = harness.scheduler.execute(ToolCall("research.run_code", {"code": "return kg.propose_change(target='x', op='add', payload={})"}),
                                       actor=actor)
    assert not denied.ok  # the RPC goes through the same permission check: the agent lacks kg:propose


# --------------------------------------------------------------------- P06 / P07
def test_p06_a_second_goal_in_one_transaction_is_refused():
    s = Session.create(MemoryEventStore(), "p06")
    tx = s.transaction("kernel")
    goal = GoalSpec(question="immutable goal A")
    tx.emit(E.RESEARCH_CREATED, {"goal": goal.to_dict(), "goal_digest": goal.digest()})
    with pytest.raises(InvalidEvent):  # the early check sees the goal already buffered in this transaction
        tx.emit(E.RESEARCH_CREATED, {"goal": GoalSpec(question="replacement goal B").to_dict()})
    tx.commit()
    assert s.state.goal.question == "immutable goal A"
    assert sum(e.type == E.RESEARCH_CREATED.value for e in s.events()) == 1


def test_p06_commit_revalidates_the_whole_batch_on_the_state_it_builds():
    s = Session.create(MemoryEventStore(), "p06c")
    tx = s.transaction("kernel")
    first = tx.emit(E.RESEARCH_CREATED, {"goal": GoalSpec(question="A").to_dict()})
    # bypass the early check by hand: the commit is the check that counts
    tx.pending.append(first.replace(payload={"goal": GoalSpec(question="B").to_dict()}))
    with pytest.raises(InvalidEvent):
        tx.commit()
    assert s.state.goal is None and s.seq == 0 and not s.store.read("p06c")


def test_p07_a_rejected_event_never_reaches_the_log():
    store = MemoryEventStore()
    s = Session.create(store, "p07")
    with pytest.raises(InvalidEvent):
        s.emit(E.RESEARCH_CREATED, {"goal": GoalSpec(question="own goal").to_dict(), "goal_digest": "intentionally-invalid"})
    assert not store.read("p07") and s.state.goal is None
    s.emit(E.RESEARCH_CREATED, {"goal": GoalSpec(question="own goal").to_dict()})
    assert Session.open(store, "p07").state.goal.question == "own goal"


def test_a_failed_persist_leaves_the_live_state_as_the_log_says(tmp_path):
    class Flaky(MemoryEventStore):
        fail = False

        def append(self, events):
            if self.fail:
                raise OSError("disk full")
            super().append(events)

    store = Flaky()
    s = Session.create(store, "flaky")
    s.emit(E.RESEARCH_CREATED, {"goal": GoalSpec(question="q").to_dict()})
    store.fail = True
    with pytest.raises(OSError):
        s.emit(E.TASK_PLANNED, {"tasks": [TaskNode(id="t1", kind="plan", role="director").to_dict()]})
    assert "t1" not in s.state.task_graph and s.seq == 1


def test_an_old_poisoned_log_reopens_with_repair():
    from taochronos.protocol.events import Event

    store = MemoryEventStore()
    goal = GoalSpec(question="q")
    store.append([Event(session_id="old", seq=1, type=E.RESEARCH_CREATED.value, actor="kernel",
                        payload={"goal": goal.to_dict(), "goal_digest": "bad"})])
    with pytest.raises(InvalidEvent):
        Session.open(store, "old")
    s = Session.open(store, "old", repair=True)
    assert s.recovery.rejected_events == [1] and s.seq == 0 and not store.read("old")


# --------------------------------------------------------------------- P08
def test_p08_an_agent_cannot_grade_and_nobody_but_an_expert_sets_g7(harness):
    h = harness
    s = _session(h, "p08")
    hyp = Hypothesis(id="hyp_gate", statement="audit gate authority", kind="hidden_association")
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    forged = {"results": [{"gate": "G7", "subject_id": hyp.id, "status": "pass", "details": "not approved by any human"}]}
    tx = s.transaction("agent:audit-unprivileged")
    with pytest.raises(InvalidEvent):
        tx.emit(E.GATE_EVALUATED, forged)
    with pytest.raises(InvalidEvent):  # not even a validator writes G7
        s.emit(E.GATE_EVALUATED, forged, actor=VALIDATOR)
    with pytest.raises(InvalidEvent):  # nor a string that says "human"
        s.emit(E.EXPERT_APPROVED, {"hypothesis_id": hyp.id}, actor="human:forged")
    assert h.gates(s.state).evaluate_hypothesis(s.state.hypotheses[hyp.id], s.state)[-2].status == "pending"
    h.engine().expert_review(s, hyp.id, approve=True, expert="审稿专家")
    assert s.state.gates[hyp.id]["G7"].status == "pass" and s.events()[-1].principal == "human"


def test_agents_see_a_read_only_state_and_cannot_emit_above_themselves(harness):
    s = _session(harness, "views")
    view = s.view(AGENT)
    assert isinstance(view, SessionView) and isinstance(view.state, StateView)
    with pytest.raises(AttributeError):
        view.state.goal = None
    with pytest.raises(TypeError):
        view.state.hypotheses["x"] = None
    with pytest.raises(InvalidEvent):
        view.emit(E.ROUND_STARTED, {"round": 9})  # the view's identity is the agent's, not the kernel's
    with pytest.raises(InvalidEvent):
        view.emit(E.HOOK_BLOCKED, {"hook": "x"}, actor=VALIDATOR)
    assert view.emit(E.HOOK_BLOCKED, {"hook": "x", "point": "test", "reason": ""}).principal == "agent"


def test_state_changed_behind_the_log_is_restored_from_the_log(harness):
    s = _session(harness, "tamper")
    hyp = Hypothesis(id="hyp_t", statement="s", kind="hidden_association")
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    s.state.hypotheses[hyp.id].status = "expert_approved"  # a mutation that bypasses the events
    assert not s.verify()["consistent"]
    harness.engine()._verify_integrity(s)
    assert s.state.hypotheses[hyp.id].status == "proposed" and s.verify()["consistent"]
    assert any(d.kind == "integrity_restored" for d in s.state.decisions.values())


# --------------------------------------------------------------------- P09
def test_p09_empty_quotes_and_impossible_spans_do_not_verify(harness):
    p = next(iter(harness.corpus.passages()))
    base = dict(passage_id=p.id, book_id=p.book_id, locator=p.locator, agent="probe", retrieval_method="probe")
    for quote, start, end in [("", 999999, 999999), ("", 0, 0), (p.text[:2], 2, 2), (p.text[:2], -1, 1), (p.text[:3], 0, len(p.text) + 5)]:
        assert verify_evidence(EvidenceRecord(id="ev", quote=quote, start=start, end=end, **base), harness.corpus), (quote, start, end)
    assert not verify_evidence(EvidenceRecord(id="ev", quote=p.text[:4], start=0, end=4, **base), harness.corpus)


# --------------------------------------------------------------------- P10
@pytest.mark.parametrize("stance,evidence_type,population,expected", [
    (Stance.CONTRADICTS, "rct", "human", "fail"),
    (Stance.CONTEXT, "guideline", "human", "warn"),
    (Stance.SUPPORTS, "animal", "animal", "warn"),
    (Stance.SUPPORTS, "rct", "human", "pass"),
])
def test_p10_g8_reads_stance_and_level_not_mere_existence(harness, stance, evidence_type, population, expected):
    s = _session(harness, f"p10-{stance.value}-{evidence_type}")
    hyp = Hypothesis(id="hyp_modern", statement="audit biomedical assertion", kind="hidden_association", space=KnowledgeSpace.BIOMEDICAL)
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    p = next(iter(harness.corpus.passages()))
    rec = EvidenceRecord(id="ev_modern", passage_id=p.id, book_id=p.book_id, locator=p.locator, quote=p.text, start=0, end=len(p.text),
                         agent="probe", retrieval_method="probe", hypothesis_id=hyp.id, stance=stance,
                         evidence_domain=EvidenceDomain.MODERN_CLINICAL, evidence_type=evidence_type, population=population)
    s.emit(E.EVIDENCE_RETRIEVED, {"records": [rec.to_dict()]}, generated=[rec.id])
    g8 = harness.gates(s.state).g8(s.state.hypotheses[hyp.id], s.state)
    assert g8.status == expected and g8.layers["exists"] == 1


# --------------------------------------------------------------------- retraction
def test_retracting_evidence_invalidates_what_rested_on_it(harness):
    s = _session(harness, "retract")
    p = next(iter(harness.corpus.passages()))
    rec = EvidenceRecord(id="ev_r", passage_id=p.id, book_id=p.book_id, locator=p.locator, quote=p.text[:4], start=0, end=4,
                         agent="probe", retrieval_method="probe", hypothesis_id="hyp_r", stance=Stance.SUPPORTS)
    hyp = Hypothesis(id="hyp_r", statement="s", kind="hidden_association", supporting_evidence=["ev_r"])
    s.emit(E.EVIDENCE_RETRIEVED, {"records": [rec.to_dict()]}, generated=[rec.id])
    s.emit(E.HYPOTHESIS_GENERATED, {"hypotheses": [hyp.to_dict()]}, generated=[hyp.id])
    s.emit(E.GATE_EVALUATED, {"results": [{"gate": "G5", "subject_id": "hyp_r", "status": "pass"}]}, actor=VALIDATOR)
    with pytest.raises(InvalidEvent):
        s.emit(E.EVIDENCE_RETRACTED, {"evidence_ids": ["ev_r"], "reason": "misread"}, actor=AGENT)
    s.emit(E.EVIDENCE_RETRACTED, {"evidence_ids": ["ev_r"], "reason": "misread witness"}, actor=VALIDATOR)
    assert "ev_r" not in s.state.hypotheses["hyp_r"].supporting_evidence and "G5" not in s.state.gates.get("hyp_r", {})
    assert s.state.retractions["ev_r"]["hypotheses"] == ["hyp_r"]
