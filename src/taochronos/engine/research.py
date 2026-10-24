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
from typing import Any, Callable

from ..agents.planning import KERNEL_ROLES, ORDER, plan_task, task_id, wire
from ..agents.runtime import TaskResult
from ..kernel.budget import Budget
from ..kernel.hooks import HookContext, HookPoint
from ..kernel.memory import MemoryLayer
from ..kernel.observability import research_metrics
from ..kernel.policy import Actor
from ..kernel.reducer import InvalidEvent
from ..kernel.session import Session
from ..kernel.stop import RoundStats, StopDecision, StopEvaluator
from ..kernel.store import SimulatedCrash
from ..protocol.base import stable_id
from ..protocol.events import EventType
from ..protocol.research import Decision, GoalSpec, TaskNode
from ..verification.hooks import anachronism_guard
from ..verification.contract import evaluate_contract
from .confirmation import confirm_hypotheses
from .manifest import run_manifest
from .report import publish_report
from .validation import VALIDATOR, adjudicate_objections, score_hypotheses, validate_claims, validate_hypotheses

TERMINAL = ("done", "failed", "skipped")
CONTRACT_JUDGE = Actor.validator("contract")
ALWAYS_RUN = {"validate_claims", "adjudicate_objections", "validate", "confirm", "score", "meta_review"}
FINAL = ("completed", "stopped", "awaiting_expert", "budget_exhausted", "max_rounds")


@dataclass
class RunResult:
    session_id: str
    status: str
    rounds: int
    stop: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    acceptance: dict[str, Any] = field(default_factory=dict)  # the contract's verdict: execution is not acceptance

    @property
    def verdict(self) -> str:
        return self.acceptance.get("status", "execution_finished")


class ResearchEngine:
    def __init__(self, harness: Any) -> None:
        self.h = harness
        self.runtime = harness.runtime

    # ================================================================ lifecycle
    def start(self, goal: GoalSpec, *, session_id: str | None = None) -> Session:
        session = Session.create(self.h.store, session_id)
        self._install_goal_hooks(goal)
        session.emit(EventType.RESEARCH_CREATED, {"goal": goal.to_dict(), "goal_digest": goal.digest(), "profile": self.h.profile.name})
        session.emit(EventType.RUN_MANIFEST_RECORDED, {"manifest": run_manifest(self.h, session, phase="start")})
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
    @staticmethod
    def spent(state: Any) -> dict[str, float]:
        """What the log says was spent: settled usage, plus reservations never settled (a crash mid-call — counted as
        spent, conservatively), plus tool calls and agents.  A resumed session starts its budget from here."""
        m = state.metrics
        used = {"llm_calls": float(m.get("llm_calls", 0)), "tokens": float(m.get("input_tokens", 0) + m.get("output_tokens", 0)),
                "cost_usd": float(m.get("cost_usd", 0.0)), "tool_calls": float(m.get("tool_calls", 0)),
                "agents": float(m.get("agents_spawned", 0))}
        for entry in (m.get("budget_ledger") or {}).values():
            if entry.get("status") == "reserved":
                est = entry.get("estimate") or {}
                used["llm_calls"] += 1
                used["tokens"] += float(est.get("tokens", 0))
                used["cost_usd"] += float(est.get("cost_usd", 0.0))
        return used

    def run(self, session: Session, *, budget: Budget | None = None, stop: Callable[[], str | None] | None = None) -> RunResult:
        """Run the session until it ends.  `stop`, asked before each task: a reason to stop (a person asked to), and
        then the task running ends the run — its round closes with what it has, as when the budget runs out, and the
        session finishes ``stopped`` with that reason (its report and the contract's evaluation of what it found)."""
        state = session.state
        if state.goal is None:
            raise ValueError("session has no research contract")
        if budget is None:
            budget = self.h.new_budget()
            budget.seed(**self.spent(state))  # a resumed run does not get its budget back
        evaluator = StopEvaluator(state.goal.stop, list(state.goal.required_validation))
        while state.status not in FINAL:
            self._drain(session, budget, stop)
            r = self._open_round(state)
            if r is None:
                self._begin_round(session, 0)
                continue
            if str(r) in state.rounds:  # resumed after the round closed but before the next began
                self._after_round(session, r, evaluator, budget, closed=True, stop=stop)
                continue
            stats = self._round_stats(state, r)
            session.emit(EventType.ROUND_COMPLETED, {"round": r, **stats})
            self._verify_integrity(session)
            session.checkpoint()
            self._after_round(session, r, evaluator, budget, closed=False, stop=stop)
        return self._result(session)

    def _after_round(self, session: Session, r: int, evaluator: StopEvaluator, budget: Budget, *, closed: bool,
                     stop: Callable[[], str | None] | None = None) -> None:
        state = session.state
        goal = state.goal
        why = stop() if stop else None
        if why:
            self._finish(session, StopDecision(True, "stopped", [why], {}))
            return
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

    @staticmethod
    def _verify_integrity(session: Session) -> None:
        """The log is the truth: if the live state differs from a replay of the log (something changed the state
        without an event), the live state is rebuilt from the log and the incident is recorded.  The replay is kept
        between rounds and advanced by the new events (Session.verify_incremental)."""
        report = session.verify_incremental()
        if report["consistent"]:
            return
        session.restore()
        session.emit(EventType.DECISION_RECORDED, {"decisions": [Decision(
            id=stable_id("dec", "integrity", session.seq), kind="integrity_restored",
            summary="live state differed from the event log; rebuilt from the log",
            rationale=f"live {report['live_hash'][:12]} ≠ replayed {report['replayed_hash'][:12]}", made_by="kernel").to_dict()]})

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

    def _drain(self, session: Session, budget: Budget, stop: Callable[[], str | None] | None = None) -> None:
        parallel = int(self.h.profile.context.get("max_parallel_agents", 1))
        while True:
            if budget.exhausted() or (stop is not None and stop()):
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
            try:
                result.commit()
            except InvalidEvent as exc:  # the whole batch is refused and nothing of it is written; the task failed
                session.emit(EventType.TASK_FAILED, {"task_id": result.task_id, "error": f"commit refused: {exc}"[:500]},
                             task_id=result.task_id)

    def run_task(self, session: Session, task: TaskNode, budget: Budget) -> TaskResult:
        if task.role in KERNEL_ROLES:
            return self._run_kernel(session, task)
        return self.runtime.run_task(session, task, budget=budget)

    def _run_kernel(self, session: Session, task: TaskNode) -> TaskResult:
        session.emit(EventType.TASK_STARTED, {"task_id": task.id, "agent_id": VALIDATOR.id}, actor=VALIDATOR, task_id=task.id)
        tx = session.transaction(VALIDATOR, task.id)
        try:
            state = session.state
            if task.kind == "validate_claims":
                summary = validate_claims(self.h, state, tx)
            elif task.kind == "adjudicate_objections":
                summary = adjudicate_objections(self.h, state, tx)
            elif task.kind == "validate":
                summary = validate_hypotheses(self.h, state, tx)
            elif task.kind == "confirm":
                summary = confirm_hypotheses(self.h, state, tx)
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
            session.emit(EventType.TASK_FAILED, {"task_id": task.id, "error": error[:500]}, actor=VALIDATOR, task_id=task.id)
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
        # execution is not acceptance: record what was used, then let a validator judge the research against its contract
        session.emit(EventType.RUN_MANIFEST_RECORDED, {"manifest": run_manifest(self.h, session, phase="end")})
        evaluation = evaluate_contract(session.state, execution=decision.status)
        session.emit(EventType.CONTRACT_EVALUATED, {"evaluation": evaluation.to_dict()}, actor=CONTRACT_JUDGE)
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
                         metrics=research_metrics(state), artifacts=sorted(state.artifacts),
                         acceptance=dict(state.acceptance or {}))

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
        session.emit(etype, {"hypothesis_id": hypothesis_id, "note": note}, actor=actor)

    def decide_change(self, session: Session, change_id: str, *, approve: bool, actor: Actor, note: str = "") -> None:
        """Canonical knowledge changes are decided by validators or humans; approved ones enter M3 domain memory."""
        etype = EventType.CHANGE_APPROVED if approve else EventType.CHANGE_REJECTED
        session.emit(etype, {"change_id": change_id, "note": note}, actor=actor)
        change = session.state.changes[change_id]
        if approve:
            summary = _change_summary(change)
            item = self.h.memory.propose(MemoryLayer.M3_DOMAIN, summary, dict(change.payload), actor=actor,
                                         terms=[str(v) for k, v in change.payload.items() if k in ("sense_id", "concept_id")],
                                         provenance={"change_id": change.id, "session": session.id})
            self.h.memory.commit(item.id, actor=actor)
            session.emit(EventType.MEMORY_WRITTEN, {"memory_id": item.id, "layer": "M3", "change_id": change.id}, actor=actor)

    def steer(self, session: Session, *, expert: str, note: str, focus: list[str] | None = None) -> None:
        """Human steering is recorded (it never edits the immutable contract)."""
        session.emit(EventType.EXPERT_STEERED, {"note": note, "focus": focus or []}, actor=Actor.human(expert))

    def close_objection(self, session: Session, hypothesis_id: str, objection_id: str, *, expert: str, note: str) -> None:
        """An expert closes an interpretive objection (hard ones close only by a validator's passing re-run)."""
        reviews = session.state.reviews_for(hypothesis_id)
        review = next((r for r in sorted(reviews, key=lambda r: (r.round, r.id), reverse=True) if r.objection(objection_id)), None)
        if review is None:
            raise KeyError(f"no objection {objection_id} on {hypothesis_id}")
        session.emit(EventType.OBJECTION_CLOSED, {"hypothesis_id": hypothesis_id, "review_id": review.id, "objection_id": objection_id,
                                                  "method": "expert", "resolution": note}, actor=Actor.human(expert))

    # ================================================================ retraction, cancel, retry
    def retract(self, session: Session, *, reason: str, actor: Actor, evidence_ids: list[str] | None = None,
                passage_id: str | None = None, reevaluate: bool = True) -> dict[str, Any]:
        """Retract evidence — named records, or every record on a passage (a witness found to be a later interpolation,
        a misread, a misattribution).  Everything computed on it is invalidated by the reducer (hypotheses lose it,
        their gates are void, objections closed with it re-open); then the hypotheses are re-validated, re-scored and
        the contract re-evaluated, so no report can present what rested on it."""
        ids = list(evidence_ids or [])
        if passage_id:
            ids += [e.id for e in session.state.evidence.values() if e.passage_id == passage_id]
        ids = sorted({e for e in ids if e in session.state.evidence and e not in session.state.retractions})
        if not ids:
            return {"retracted": 0}
        session.emit(EventType.EVIDENCE_RETRACTED, {"evidence_ids": ids, "reason": reason}, actor=actor)
        touched = sorted({h for e in ids for h in session.state.retractions[e]["hypotheses"]})
        if reevaluate:
            self.reevaluate(session, reason=f"evidence retracted: {reason}")
        return {"retracted": len(ids), "hypotheses": touched, "acceptance": (session.state.acceptance or {}).get("status")}

    def reevaluate(self, session: Session, *, reason: str = "") -> None:
        """Re-run the validators on the state as it is (objections, gates, confirmation, warrants and scores, contract)."""
        for kind, fn in (("adjudicate_objections", adjudicate_objections), ("validate", validate_hypotheses),
                         ("confirm", confirm_hypotheses)):
            tx = session.transaction(VALIDATOR, f"reevaluate.{kind}")
            fn(self.h, session.state, tx)
            tx.commit()
        tx = session.transaction(VALIDATOR, "reevaluate.score")
        score_hypotheses(self.h, session.state, tx, session.state.round)
        tx.commit()
        evaluation = evaluate_contract(session.state, execution=(session.state.stop or {}).get("status", session.state.status))
        session.emit(EventType.CONTRACT_EVALUATED, {"evaluation": evaluation.to_dict()}, actor=CONTRACT_JUDGE)
        if reason:
            session.emit(EventType.DECISION_RECORDED, {"decisions": [Decision(
                id=stable_id("dec", "reevaluate", session.seq), kind="reevaluated", summary="validators re-run and contract re-evaluated",
                rationale=reason, made_by="kernel").to_dict()]})

    def cancel(self, session: Session, task_id: str, *, reason: str, actor: Actor) -> None:
        """Cancel a pending task (recorded; its dependents are skipped by the scheduler as for any task not done)."""
        task = session.state.task_graph.get(task_id)
        if task is None or task.status not in ("pending", "running"):
            raise ValueError(f"task {task_id} is not pending")
        session.emit(EventType.TASK_SKIPPED, {"task_id": task_id, "reason": f"cancelled by {actor.id}: {reason}"}, actor=actor
                     if actor.principal != "human" else None)

    def retry(self, session: Session, task_id: str, *, run: bool = True) -> str:
        """Plan a failed or skipped task again (a new node with the same kind, role, inputs and dependencies) and, by
        default, run it — and, for a research already finished, re-run the validators and the contract after it."""
        task = session.state.task_graph.get(task_id)
        if task is None or task.status not in ("failed", "skipped"):
            raise ValueError(f"task {task_id} has not failed")
        n = sum(1 for t in session.state.task_graph if t.startswith(task_id + ".retry")) + 1
        node = task.replace(id=f"{task_id}.retry{n}", status="pending", summary="", outputs=[],
                            inputs={**task.inputs, "retry_of": task_id})
        session.emit(EventType.TASK_PLANNED, {"tasks": [node.to_dict()]})
        if run:
            budget = self.h.new_budget()
            budget.seed(**self.spent(session.state))
            self._drain(session, budget)
            if session.state.status in FINAL:
                self.reevaluate(session, reason=f"retried {task_id}")
        return node.id


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
