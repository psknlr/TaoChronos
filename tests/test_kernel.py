import pytest

from taochronos.kernel import (
    Actor,
    Budget,
    BudgetExceeded,
    BudgetLimits,
    ContextManager,
    ContextSection,
    FaultInjectingStore,
    HookContext,
    HookPoint,
    HookRegistry,
    HookResult,
    JsonlEventStore,
    MemoryEventStore,
    MemoryLayer,
    MemoryStore,
    PolicyEngine,
    PolicyViolation,
    Session,
    SimulatedCrash,
    SqliteEventStore,
    ToolCall,
    ToolRegistry,
    ToolScheduler,
    ToolSpec,
    deep_merge,
)
from taochronos.kernel.reducer import InvalidEvent
from taochronos.protocol import EventType, GoalSpec, TaskNode


def new_session(store=None, sid="s"):
    s = Session.create(store or MemoryEventStore(), sid)
    goal = GoalSpec(question="q")
    s.emit(EventType.RESEARCH_CREATED, {"goal": goal.to_dict(), "goal_digest": goal.digest()})
    s.emit(EventType.TASK_PLANNED, {"tasks": [TaskNode(id="t1", kind="plan", role="director").to_dict()]})
    return s


@pytest.mark.parametrize("kind", ["memory", "jsonl", "sqlite"])
def test_event_stores_round_trip(tmp_path, kind):
    store = {"memory": MemoryEventStore, "jsonl": lambda: JsonlEventStore(tmp_path), "sqlite": lambda: SqliteEventStore(tmp_path / "e.db")}[kind]()
    s = new_session(store)
    reopened = Session.open(store, "s")
    assert reopened.state.state_hash() == s.state.state_hash()
    assert reopened.seq == s.seq


def test_goal_contract_is_immutable():
    s = new_session()
    with pytest.raises(InvalidEvent):
        s.emit(EventType.RESEARCH_CREATED, {"goal": GoalSpec(question="other").to_dict()})
    with pytest.raises(InvalidEvent):
        s.emit(EventType.DECISION_RECORDED, {"decisions": [], "goal": {}})


def test_only_humans_approve_and_agents_cannot_decide_changes():
    s = new_session()
    s.emit(EventType.CHANGE_PROPOSED, {"change": {"id": "chg_1", "target": "terminology", "op": "add", "payload": {},
                                                   "rationale": "", "proposer": "agent:ontologist"}})
    with pytest.raises(InvalidEvent):
        s.emit(EventType.CHANGE_APPROVED, {"change_id": "chg_1"}, actor="agent:ontologist@r0")
    s.emit(EventType.CHANGE_APPROVED, {"change_id": "chg_1"}, actor="human:expert")
    assert s.state.changes["chg_1"].status == "approved"
    with pytest.raises(InvalidEvent):
        s.emit(EventType.EXPERT_APPROVED, {"hypothesis_id": "h"}, actor="validator:gates")


def test_transactions_are_atomic_and_torn_writes_are_recovered():
    inner = MemoryEventStore()
    s = new_session(FaultInjectingStore(inner, crash_on_batch=1))
    tx = s.transaction("agent:x", "t1")
    tx.emit(EventType.DECISION_RECORDED, {"decisions": [{"id": "d1", "kind": "k", "summary": "", "rationale": "", "made_by": "x"}]})
    tx.emit(EventType.TASK_COMPLETED, {"task_id": "t1"})
    with pytest.raises(SimulatedCrash):
        tx.commit()
    recovered = Session.open(inner, "s")
    assert recovered.recovery.discarded_events >= 1
    assert "d1" not in recovered.state.decisions
    assert recovered.state.task_graph["t1"].status == "pending"


def test_fork_and_verify():
    s = new_session()
    s.checkpoint()
    child = s.fork(purpose="branch", hypothesis_id=None)
    assert child.id.startswith("s.b")
    assert s.state.branches
    assert s.verify()["consistent"]


def test_policy_refuses_commit_permissions_to_agents():
    engine = PolicyEngine(deny=["codemode:exec"])
    assert engine.check_grant("agent", ["kg:read", "ontology:write"])
    assert not engine.check_grant("human", ["ontology:write"])
    agent = Actor(id="agent:a", role="a", permissions=frozenset({"kg:*", "codemode:exec"}))
    assert engine.allowed(agent, "kg:read")
    assert not engine.allowed(agent, "kg:commit")
    assert not engine.allowed(agent, "codemode:exec")
    with pytest.raises(PolicyViolation):
        engine.require(agent, "gold:write")


def test_budgets_are_hierarchical():
    parent = Budget(BudgetLimits(max_tool_calls=3))
    child = parent.child(BudgetLimits(max_tool_calls=10))
    child.charge(tool_calls=3)
    with pytest.raises(BudgetExceeded):
        child.charge(tool_calls=1)
    assert parent.exhausted()


def test_hooks_run_in_priority_order_and_can_block():
    hooks = HookRegistry()
    seen = []
    hooks.register(HookPoint.BEFORE_TOOL_CALL, "late", lambda ctx: seen.append("late") or HookResult(allow=False, reason="no"), 50)
    hooks.register(HookPoint.BEFORE_TOOL_CALL, "early", lambda ctx: seen.append("early") or None, 10)
    result = hooks.run(HookContext(HookPoint.BEFORE_TOOL_CALL, subject={}))
    assert seen == ["early", "late"] and not result.allow and result.hook == "late"


def test_tool_scheduler_gauntlet():
    reg = ToolRegistry()
    reg.register(ToolSpec("t.echo", "echo", {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
                          lambda ctx, a: a["x"], permission="t:read"))
    reg.register(ToolSpec("t.write", "write", {"type": "object", "properties": {}}, lambda ctx, a: 1, permission="t:write",
                          exclusive=True, parallel_safe=False))
    sched = ToolScheduler(reg, PolicyEngine(), HookRegistry(), capabilities=None)
    actor = Actor(id="agent:a", role="a", permissions=frozenset({"t:read"}))
    assert sched.execute(ToolCall("t.echo", {"x": 2}), actor=actor).result == 2
    assert not sched.execute(ToolCall("t.echo", {"x": "no"}), actor=actor).ok
    assert "lacks permission" in sched.execute(ToolCall("t.write", {}), actor=actor).error
    assert sched.plan_batches([ToolCall("t.echo"), ToolCall("t.echo"), ToolCall("t.write"), ToolCall("t.echo")]) == [[0, 1], [2], [3]]
    budget = Budget(BudgetLimits(max_tool_calls=1))
    sched.execute(ToolCall("t.echo", {"x": 1}), actor=actor, budget=budget)
    assert "budget" in sched.execute(ToolCall("t.echo", {"x": 1}), actor=actor, budget=budget).error


def test_context_manager_keeps_pinned_sections_and_compacts():
    cm = ContextManager(max_tokens=60)
    view = cm.build([
        ContextSection("Goal", "g" * 40, pinned=True),
        ContextSection("Items", "", priority=10, items=[f"item {i} " + "x" * 30 for i in range(20)]),
    ])
    assert view.get("Goal") is not None
    assert "Items" in view.compacted or "Items" in view.omitted


def test_domain_memory_commits_only_by_humans(tmp_path):
    mem = MemoryStore(tmp_path)
    item = mem.propose(MemoryLayer.M3_DOMAIN, "消渴 —partially_overlapping→ 糖尿病", {}, actor=Actor(id="agent:o", role="o"))
    with pytest.raises(PolicyViolation):
        mem.commit(item.id, actor=Actor(id="agent:o", role="o"))
    mem.commit(item.id, actor=Actor.human("expert"))
    assert MemoryStore(tmp_path).recall(MemoryLayer.M3_DOMAIN, "消渴")[0].status == "active"


def test_profile_merge_appends_with_plus_keys():
    merged = deep_merge({"agents": ["a"], "stop": {"max_rounds": 1, "x": 1}}, {"agents+": ["b"], "stop": {"max_rounds": 2}})
    assert merged == {"agents": ["a", "b"], "stop": {"max_rounds": 2, "x": 1}}
