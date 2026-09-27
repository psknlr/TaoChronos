"""Long runs: a budget ledger that survives crashes, paged tool results and per-turn compaction, exact replay of model
responses, retraction that invalidates what rested on it, cancel and retry — tested by injecting faults."""

from __future__ import annotations

import json

import pytest

from conftest import make_harness, run_research
from taochronos.agents.paging import PAGE_TOOL, ResultPager, compile_messages
from taochronos.capabilities.llm import LLMError, LLMRequest, Message, ToolResultBlock
from taochronos.capabilities.recording import RecordingProvider
from taochronos.kernel.budget import Budget, BudgetExceeded, BudgetLimits
from taochronos.kernel.policy import Actor
from taochronos.plugins.models.scripted import ScriptedProvider


def test_reservations_hold_budget_until_settled_and_a_resume_starts_from_the_log(research):
    b = Budget(BudgetLimits(max_llm_calls=2, max_cost_usd=1.0))
    agent = b.child(BudgetLimits(), name="agent")
    r1 = agent.reserve(llm_calls=1, cost_usd=0.6)
    with pytest.raises(BudgetExceeded):  # a concurrent call cannot spend what the first one holds
        agent.reserve(llm_calls=1, cost_usd=0.6)
    agent.settle(r1, llm_calls=1, cost_usd=0.2)
    assert b.used["cost_usd"] == 0.2 and b.held["cost_usd"] == 0.0
    h, session = research
    spent = h.engine().spent(session.state)
    assert spent["agents"] > 0 and spent["tool_calls"] > 0
    fresh = h.new_budget()
    fresh.seed(**spent)
    assert fresh.used["tool_calls"] == spent["tool_calls"]


def test_an_unsettled_reservation_counts_as_spent(research):
    h, session = research
    state = session.state
    before = h.engine().spent(state)
    state.metrics.setdefault("budget_ledger", {})["probe#r1"] = {"status": "reserved", "estimate": {"tokens": 500, "cost_usd": 0.25}}
    try:
        after = h.engine().spent(state)
        assert after["llm_calls"] == before["llm_calls"] + 1 and after["cost_usd"] == pytest.approx(before["cost_usd"] + 0.25)
    finally:
        state.metrics["budget_ledger"].pop("probe#r1")


def test_long_results_are_paged_not_cut():
    pager = ResultPager(page_chars=200)
    result = {"hits": [{"passage_id": f"p{i}", "text": "消渴" * 20} for i in range(30)], "query": {"terms": ["消渴"]}}
    first = json.loads(pager.render("tu1", "classics.search", True, result, None))
    assert first["pages"] > 1 and first["page_id"] == "res:tu1"
    seen = []
    for n in range(1, first["pages"] + 1):
        body, error = pager.page({"page_id": "res:tu1", "page": n})
        assert not error
        seen += json.loads(json.loads(body)["content"])["hits"]
    assert [x["passage_id"] for x in seen] == [f"p{i}" for i in range(30)]  # every item, in order, nothing lost
    assert pager.page({"page_id": "res:nope"})[1] and pager.page({"page_id": "res:tu1", "page": 99})[1]


def test_older_turns_are_compacted_to_their_page_handles():
    msgs = [Message("user", "view")]
    for i in range(6):
        msgs.append(Message("assistant", text=f"call {i}"))
        msgs.append(Message("user", tool_results=[ToolResultBlock(f"tu{i}", "x" * 1000)]))
    compiled = compile_messages(msgs, keep_recent=2)
    assert compiled[0].text == "view" and len(compiled) == len(msgs)
    old = compiled[2].tool_results[0].content
    assert len(old) < 400 and "res:tu0" in old and PAGE_TOOL in old
    assert compiled[-1].tool_results[0].content == "x" * 1000  # recent turns stay whole


def test_model_responses_replay_exactly_without_calling_the_model(tmp_path):
    live = ScriptedProvider([{"text": "第一次回答"}], name="scripted")
    request = LLMRequest(model="scripted-model", system="s", messages=[Message("user", "问")])
    recorder = RecordingProvider(live, tmp_path / "rec", "record")
    assert recorder.complete(request).text == "第一次回答"
    replayer = RecordingProvider(ScriptedProvider([], name="scripted"), tmp_path / "rec", "replay")
    again = replayer.complete(request)
    assert again.text == "第一次回答" and replayer.hits == 1 and "replayed" in again.note
    with pytest.raises(LLMError):
        replayer.complete(LLMRequest(model="scripted-model", system="s", messages=[Message("user", "另一个问题")]))


def test_the_model_loop_reads_pages_and_keeps_a_balanced_ledger(tmp_path):
    steps = [
        {"tool_uses": [{"id": "tu_s", "name": "classics__search", "input": {"query": "消渴", "k": 40}}]},
        {"tool_uses": [{"id": "tu_p", "name": PAGE_TOOL, "input": {"page_id": "res:tu_s", "page": 2}}]},
    ]

    def fail_after(request):  # the third call fails: the reservation must be released, the procedure takes over
        raise LLMError("provider down")

    scripted = ScriptedProvider(steps + [fail_after], name="scripted")
    h = make_harness(tmp_path, providers={"scripted": scripted},
                     overrides={"routing": {"roles": {"hypothesis": {"provider": "scripted"}}}, "stop": {"max_rounds": 1}})
    h.runtime.recording = (str(tmp_path / "rec"), "record")
    h.runtime.config["page_chars"] = 600
    session = run_research(h, "paged")
    page_reply = next(r for req in scripted.requests for m in req.messages for r in m.tool_results if r.tool_use_id == "tu_p")
    assert '"page": 2' in page_reply.content
    ledger = session.state.metrics["budget_ledger"]
    assert ledger and all(e["status"] == "settled" for e in ledger.values())
    assert any(e.get("outcome") == "failed" for e in ledger.values())
    assert "fallback" in session.state.task_graph["r1.generate_hypotheses"].summary
    assert len(list((tmp_path / "rec" / "scripted").glob("*.json"))) == 2  # the two answered calls were recorded


def test_retraction_invalidates_and_the_contract_is_judged_again(research):
    h, session = research
    child = session.fork(purpose="retraction probe", record_in_parent=False, new_session_id="ref.retract-probe")
    target = next(x for x in child.state.hypotheses.values() if x.status == "survived" and x.supporting_evidence)
    passage = child.state.evidence[target.supporting_evidence[0]].passage_id
    out = h.engine().retract(child, reason="witness found to be a later interpolation", actor=Actor.human("校勘者"), passage_id=passage)
    assert out["retracted"] >= 1 and target.id in out["hypotheses"]
    state = child.state
    assert not any(state.evidence[e].passage_id == passage for e in state.hypotheses[target.id].supporting_evidence)
    judged = {j["hypothesis_id"]: j for j in state.acceptance["hypotheses"]}
    assert judged[target.id]["version"] == state.hypotheses[target.id].version()  # re-judged on the version it now has
    assert any(d.kind == "reevaluated" for d in state.decisions.values())
    from taochronos.engine.report import publish_report

    assert publish_report(h, child)  # the publish check accepts reports judged on current versions


def test_cancel_and_retry(tmp_path):
    h = make_harness(tmp_path)
    engine = h.engine()
    s = engine.start(h.make_goal("消渴", focus_terms=["消渴"], stop={"max_rounds": 1}), session_id="ops")
    from taochronos.protocol import EventType as E
    from taochronos.protocol.research import TaskNode

    s.emit(E.TASK_PLANNED, {"tasks": [TaskNode(id="x.extra", kind="trace_sources", role="scholar", round=0).to_dict()]})
    engine.cancel(s, "x.extra", reason="not needed", actor=Actor.human("operator"))
    assert s.state.task_graph["x.extra"].status == "skipped" and "operator" in s.state.task_graph["x.extra"].summary
    new = engine.retry(s, "x.extra", run=True)
    assert new == "x.extra.retry1" and s.state.task_graph[new].status == "done"
    with pytest.raises(ValueError):
        engine.retry(s, new)  # only a failed or skipped task can be retried


def test_a_crash_mid_run_resumes_to_the_same_contract_verdict(tmp_path):
    from taochronos.kernel import FaultInjectingStore, MemoryEventStore, SimulatedCrash

    reference = run_research(make_harness(tmp_path / "a"), "ref")
    inner = MemoryEventStore()
    h = make_harness(tmp_path / "b", store=FaultInjectingStore(inner, crash_on_batch=9))
    with pytest.raises(SimulatedCrash):
        run_research(h, "ref")
    h2 = make_harness(tmp_path / "b", store=inner)
    engine = h2.engine()
    resumed = engine.open("ref")
    engine.run(resumed)
    assert resumed.state.state_hash() == reference.state.state_hash()
    assert resumed.state.acceptance["status"] == reference.state.acceptance["status"]
