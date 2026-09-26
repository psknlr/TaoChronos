"""The research engine: an operational loop (tasks, agents, commits) inside a scientific loop (rounds).

    round 0   foundation: scope → philology → semantics → claims (+gates) → lineage → evidence
    round 1   discovery : mine → statistics → evolution → hypotheses → falsify → revise → re-falsify
                          → modern bridges → gates → scores + Elo → meta-review
    round 2+  deepening : whatever the Director (TaoChronos) plans from the meta-review — or nothing

After every round the harness (never a model) evaluates the stop conditions.
Everything is an event: the run can be replayed, verified, resumed after a
crash, or forked into hypothesis branches.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..agents.planning import KERNEL_ROLES, ORDER, plan_task, task_id, wire
from ..agents.runtime import TaskResult
from ..kernel.budget import Budget
from ..kernel.hooks import HookContext, HookPoint
from ..kernel.memory import MemoryLayer
from ..kernel.observability import research_metrics
from ..kernel.policy import Actor
from ..kernel.session import Session
from ..kernel.stop import RoundStats, StopDecision, StopEvaluator
from ..kernel.store import SimulatedCrash
from ..protocol.base import stable_id
from ..protocol.events import EventType
from ..protocol.research import Decision, GoalSpec, TaskNode
from ..verification.hooks import anachronism_guard
from .report import publish_report
from .validation import VALIDATOR, score_hypotheses, validate_claims, validate_hypotheses

TERMINAL = ("done", "failed", "skipped")
ALWAYS_RUN = {"validate_claims", "validate", "score", "meta_review"}
FINAL = ("completed", "stopped", "awaiting_expert", "budget_exhausted", "max_rounds")


@dataclass
class RunResult:
    session_id: str
    status: str
    rounds: int
    stop: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)


class ResearchEngine:
    def __init__(self, harness: Any) -> None:
        self.h = harness
        self.runtime = harness.runtime

    # ================================================================ lifecycle
    def start(self, goal: GoalSpec, *, session_id: str | None = None) -> Session:
        session = Session.create(self.h.store, session_id)
        self._install_goal_hooks(goal)
        session.emit(EventType.RESEARCH_CREATED, {"goal": goal.to_dict(), "goal_digest": goal.digest(), "profile": self.h.profile.name})
        session.emit(EventType.PROFILE_LOADED, {
            "profile": self.h.profile.name,
            "plugins": list(self.h.capabilities.loaded_plugins),
            "agents": {role: spec.name for role, spec in sorted(self.h.specs.items())},
            "skills": self.h.skills.names(),
            "hooks": self.h.hooks.names(),
            "tools": len(self.h.tools.names()),
            "routing": self.h.profile.routing,
        })
        self.h.hooks.run(HookContext(HookPoint.RESEARCH_START, subject=goal, session=session))
        return session

    def open(self, session_id: str) -> Session:
        session = Session.open(self.h.store, session_id)
        if session.state.goal is not None:
            self._install_goal_hooks(session.state.goal)
        return session

    def research(self, goal: GoalSpec, *, session_id: str | None = None) -> RunResult:
        return self.run(self.start(goal, session_id=session_id))

    def resume(self, session_id: str) -> RunResult:
        return self.run(self.open(session_id))

    def _install_goal_hooks(self, goal: GoalSpec) -> None:
        """The contract's forbidden assumptions become part of the anachronism guard for this session."""
        if "anachronism_guard" not in self.h.hooks.names():
            return
        labels = [c.label for c in self.h.pack.terminology.concepts.values()]
        guard = anachronism_guard(labels, list(goal.forbidden_assumptions))
        for point in (HookPoint.BEFORE_CLAIM_COMMIT, HookPoint.AFTER_HYPOTHESIS, HookPoint.BEFORE_GRAPH_WRITE):
            self.h.hooks.register(point, "anachronism_guard", guard, 20)

    # ================================================================ main loop
    def run(self, session: Session, *, budget: Budget | None = None) -> RunResult:
        state = session.state
        if state.goal is None:
            raise ValueError("session has no research contract")
        budget = budget or self.h.new_budget()
        evaluator = StopEvaluator(state.goal.stop, list(state.goal.required_validation))
        while state.status not in FINAL:
            self._drain(session, budget)
            r = self._open_round(state)
            if r is None:
                self._begin_round(session, 0)
                continue
            if str(r) in state.rounds:  # resumed after the round closed but before the next began
                self._after_round(session, r, evaluator, budget, closed=True)
                continue
            stats = self._round_stats(state, r)
            session.emit(EventType.ROUND_COMPLETED, {"round": r, **stats})
            session.checkpoint()
            self._after_round(session, r, evaluator, budget, closed=False)
        return self._result(session)

    def _after_round(self, session: Session, r: int, evaluator: StopEvaluator, budget: Budget, *, closed: bool) -> None:
        state = session.state
        goal = state.goal
        if r == 0:
            if goal.stop.max_rounds <= 0:
                self._finish(session, StopDecision(True, "completed", ["foundation-only contract (max_rounds = 0)"], {}))
            elif self._open_round(state) == 0:
                self._begin_round(session, 1)
            return
        rec = state.rounds[str(r)]
        stats = RoundStats(round=r, new_evidence=rec["new_evidence"], total_evidence=rec["total_evidence"],
                           new_sources=rec["new_sources"], new_hypotheses=rec["new_hypotheses"], surviving=rec["surviving"])
        decision = evaluator.evaluate(state, stats, budget)
        if rec.get("planned_tasks", 1) == 0:
            decision = StopDecision(True, "completed", ["TaoChronos (director) found no productive next step"] + decision.reasons,
                                    decision.signals)
        if decision.stop:
            self._finish(session, decision)
        elif self._open_round(state) == r:
            self._begin_round(session, r + 1)

    def _begin_round(self, session: Session, r: int) -> None:
        session.emit(EventType.ROUND_STARTED, {"round": r})
        session.emit(EventType.TASK_PLANNED, {"tasks": [plan_task(r).to_dict()]})

    @staticmethod
    def _open_round(state: Any) -> int | None:
        rounds = [t.round for t in state.task_graph.values() if "/" not in t.id]
        return max(rounds) if rounds else None

    # ================================================================ tasks
    def _ready(self, session: Session) -> list[TaskNode]:
        state = session.state
        ready = []
        for t in sorted(state.task_graph.values(), key=lambda t: (t.round, ORDER.get(t.kind, 99), t.priority, t.id)):
            if t.status not in ("pending", "running"):
                continue
            deps = [state.task_graph.get(d) for d in t.depends_on]
            if any(d is None or d.status not in TERMINAL for d in deps):
                continue
            broken = [d.id for d in deps if d.status != "done"]
            if broken and t.kind not in ALWAYS_RUN:
                session.emit(EventType.TASK_SKIPPED, {"task_id": t.id, "reason": f"upstream task(s) did not complete: {', '.join(broken)}"},
                             task_id=t.id)
                continue
            ready.append(t)
        return ready

    def _drain(self, session: Session, budget: Budget) -> None:
        parallel = int(self.h.profile.context.get("max_parallel_agents", 1))
        while True:
            if budget.exhausted():
                return
            ready = self._ready(session)
            if not ready:
                return
            if parallel > 1 and len(ready) > 1:
                self._run_parallel(session, ready[:parallel], budget)
            else:
                self.run_task(session, ready[0], budget)

    def _run_parallel(self, session: Session, tasks: list[TaskNode], budget: Budget) -> None:
        """Run independent tasks concurrently, but commit their transactions in a deterministic order."""
        agent_tasks = [t for t in tasks if t.role not in KERNEL_ROLES]
        for t in tasks:
            if t.role in KERNEL_ROLES:
                self.run_task(session, t, budget)
        if not agent_tasks:
            return
        with ThreadPoolExecutor(max_workers=len(agent_tasks)) as pool:
            futures = [pool.submit(self.runtime.run_task, session, t, budget=budget, defer_commit=True) for t in agent_tasks]
            results = [f.result() for f in futures]
        for result in results:  # agent_tasks are already in scheduling order
            result.commit()

    def run_task(self, session: Session, task: TaskNode, budget: Budget) -> TaskResult:
        if task.role in KERNEL_ROLES:
            return self._run_kernel(session, task)
        return self.runtime.run_task(session, task, budget=budget)

    def _run_kernel(self, session: Session, task: TaskNode) -> TaskResult:
        session.emit(EventType.TASK_STARTED, {"task_id": task.id, "agent_id": VALIDATOR.id}, actor=VALIDATOR.id, task_id=task.id)
        tx = session.transaction(VALIDATOR.id, task.id)
        try:
            state = session.state
            if task.kind == "validate_claims":
                summary = validate_claims(self.h, state, tx)
            elif task.kind == "validate":
                summary = validate_hypotheses(self.h, state, tx)
            elif task.kind == "score":
                summary = score_hypotheses(self.h, state, tx, task.round)
            else:
                raise ValueError(f"unknown kernel task kind {task.kind!r}")
            tx.emit(EventType.TASK_COMPLETED, {"task_id": task.id, "summary": summary, "outputs": [], "mode": "validator"})
            tx.commit()
            return TaskResult(task.id, task.role, VALIDATOR.id, "done", summary)
        except SimulatedCrash:
            raise
        except Exception as exc:
            tx.abort()
            error = f"{type(exc).__name__}: {exc}"
            session.emit(EventType.TASK_FAILED, {"task_id": task.id, "error": error[:500]}, actor=VALIDATOR.id, task_id=task.id)
            return TaskResult(task.id, task.role, VALIDATOR.id, "failed", error=error)

    # ================================================================ rounds
    @staticmethod
    def _round_stats(state: Any, r: int) -> dict[str, Any]:
        prev = state.rounds.get(str(r - 1), {})
        books = sorted({e.book_id for e in state.evidence.values()})
        total = len(state.evidence)
        planned = sum(1 for t in state.task_graph.values() if t.round == r and t.kind != "plan" and "/" not in t.id)
        return {
            "new_evidence": total - int(prev.get("total_evidence", 0)),
            "total_evidence": total,
            "new_sources": len(set(books) - set(prev.get("evidence_books", []))),
            "evidence_books": books,
            "new_hypotheses": len(state.hypotheses) - int(prev.get("hypotheses_total", 0)),
            "hypotheses_total": len(state.hypotheses),
            "surviving": sum(1 for h in state.hypotheses.values() if h.status in ("survived", "expert_approved")),
            "planned_tasks": planned,
            "failed_tasks": sum(1 for t in state.task_graph.values() if t.round == r and t.status == "failed"),
        }

    def _finish(self, session: Session, decision: StopDecision) -> None:
        session.emit(EventType.STOP_CONDITION_MET, {"status": decision.status, "reasons": decision.reasons,
                                                    "signals": _jsonable(decision.signals)})
        try:
            publish_report(self.h, session)
        except Exception as exc:  # a report failure must not lose the research
            session.emit(EventType.DECISION_RECORDED, {"decisions": [Decision(
                id=stable_id("dec", "report-failed", session.seq), kind="report_failed", summary="report publication failed",
                rationale=f"{type(exc).__name__}: {exc}", made_by="kernel").to_dict()]})
        session.emit(EventType.RESEARCH_COMPLETED, {"status": decision.status})
        self.h.hooks.run(HookContext(HookPoint.RESEARCH_END, subject=decision, session=session))
        session.checkpoint()

    def _result(self, session: Session) -> RunResult:
        state = session.state
        return RunResult(session_id=session.id, status=state.status, rounds=state.round, stop=dict(state.stop or {}),
                         metrics=research_metrics(state), artifacts=sorted(state.artifacts))

    # ================================================================ branches
    def branch(self, session: Session, hypothesis_id: str, *, purpose: str = "", merge: bool = True) -> tuple[Session, dict[str, Any]]:
        """Fork a hypothesis branch: re-examine one hypothesis in isolation, then merge the outcome back."""
        if hypothesis_id not in session.state.hypotheses:
            raise KeyError(f"unknown hypothesis {hypothesis_id}")
        child = session.fork(purpose=purpose or f"re-examine {hypothesis_id}", hypothesis_id=hypothesis_id)
        r = max(child.state.round, 0) + 1
        items = [
            {"kind": "gather_evidence", "inputs": {"hypothesis_ids": [hypothesis_id]}, "reason": "branch: seek independent witnesses"},
            {"kind": "falsify", "inputs": {"hypothesis_ids": [hypothesis_id], "rereview": True}, "reason": "branch: re-review"},
            {"kind": "revise_hypotheses", "inputs": {"hypothesis_ids": [hypothesis_id]}, "reason": "branch: narrow if sent back"},
        ]
        child.emit(EventType.ROUND_STARTED, {"round": r, "branch": True})
        nodes = wire(r, items)
        plan = TaskNode(id=task_id(r, "plan"), kind="plan", role="director", round=r, inputs={"round": r, "branch": True},
                        status="done", summary="branch plan (harness)")
        child.emit(EventType.TASK_PLANNED, {"tasks": [plan.to_dict()] + [n.to_dict() for n in nodes]})
        budget = self.h.new_budget()
        self._drain(child, budget)
        stats = self._round_stats(child.state, r)
        child.emit(EventType.ROUND_COMPLETED, {"round": r, **stats})
        h = child.state.hypotheses[hypothesis_id]
        latest = [x for x in child.state.hypotheses.values() if x.parent_id == hypothesis_id]
        subject = latest[0] if latest else h
        outcome = {
            "hypothesis_id": hypothesis_id,
            "final_hypothesis": subject.id,
            "status": subject.status,
            "discovery_score": subject.discovery_score,
            "gates": {g: r_.status for g, r_ in child.state.gates.get(subject.id, {}).items()},
            "new_evidence": stats["new_evidence"],
        }
        child.emit(EventType.RESEARCH_COMPLETED, {"status": "completed"})
        if merge:
            session.emit(EventType.BRANCH_MERGED, {"branch_id": child.id, "outcome": outcome})
        return child, outcome

    # ================================================================ humans
    def expert_review(self, session: Session, hypothesis_id: str, *, approve: bool, expert: str, note: str = "") -> None:
        """Gate G7: only a human expert can approve or reject a hypothesis."""
        actor = Actor.human(expert)
        etype = EventType.EXPERT_APPROVED if approve else EventType.EXPERT_REJECTED
        session.emit(etype, {"hypothesis_id": hypothesis_id, "note": note}, actor=actor.id)

    def decide_change(self, session: Session, change_id: str, *, approve: bool, actor: Actor, note: str = "") -> None:
        """Canonical knowledge changes are decided by validators or humans; approved ones enter M3 domain memory."""
        etype = EventType.CHANGE_APPROVED if approve else EventType.CHANGE_REJECTED
        session.emit(etype, {"change_id": change_id, "note": note}, actor=actor.id)
        change = session.state.changes[change_id]
        if approve:
            summary = _change_summary(change)
            item = self.h.memory.propose(MemoryLayer.M3_DOMAIN, summary, dict(change.payload), actor=actor,
                                         terms=[str(v) for k, v in change.payload.items() if k in ("sense_id", "concept_id")],
                                         provenance={"change_id": change.id, "session": session.id})
            self.h.memory.commit(item.id, actor=actor)
            session.emit(EventType.MEMORY_WRITTEN, {"memory_id": item.id, "layer": "M3", "change_id": change.id}, actor=actor.id)

    def steer(self, session: Session, *, expert: str, note: str, focus: list[str] | None = None) -> None:
        """Human steering is recorded (it never edits the immutable contract)."""
        session.emit(EventType.EXPERT_STEERED, {"note": note, "focus": focus or []}, actor=Actor.human(expert).id)


def _change_summary(change: Any) -> str:
    p = change.payload
    if p.get("kind") == "concept_mapping":
        return f"{p.get('historical_label', p.get('sense_id'))} —{p.get('relation')}→ {p.get('modern_label', p.get('concept_id'))}"
    return f"{change.target}:{change.op} {change.id}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value
