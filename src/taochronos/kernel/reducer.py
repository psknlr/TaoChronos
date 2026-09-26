"""Events → Reducer → State.

The reducer is the *only* code path that mutates a ResearchObject.  It is
deterministic, and it enforces the invariants that must hold no matter which
model or agent produced an event (goal immutability, commit-only-by-humans…).
"""

from __future__ import annotations

from typing import Callable, Iterable

from ..protocol.artifacts import Artifact
from ..protocol.base import stable_id
from ..protocol.claims import Claim
from ..protocol.confidence import ConfidenceVector
from ..protocol.events import Event, EventType
from ..protocol.evidence import EvidenceRecord, Stance
from ..protocol.hypothesis import Hypothesis, HypothesisReview, Observation, ScoreCard
from ..protocol.outputs import PhilologyAssessment, TermResolution
from ..protocol.research import (
    AgentInstance,
    BranchInfo,
    Contradiction,
    CorpusManifest,
    Decision,
    GateResult,
    GoalSpec,
    LineageEdge,
    ProposedChange,
    ResearchObject,
    TaskNode,
)

T = EventType


class InvalidEvent(ValueError):
    """An event that would violate a harness invariant. It is never persisted."""


def _count(metrics: dict, key: str, amount: float = 1) -> None:
    metrics[key] = metrics.get(key, 0) + amount


class Reducer:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[ResearchObject, Event], None]] = {
            T.RESEARCH_CREATED.value: self._research_created,
            T.PROFILE_LOADED.value: self._profile_loaded,
            T.CORPUS_SCOPED.value: self._corpus_scoped,
            T.ROUND_STARTED.value: self._round_started,
            T.ROUND_COMPLETED.value: self._round_completed,
            T.STOP_CONDITION_MET.value: self._stop_condition_met,
            T.RESEARCH_COMPLETED.value: self._research_completed,
            T.RESEARCH_STOPPED.value: self._research_stopped,
            T.TASK_PLANNED.value: self._task_planned,
            T.TASK_STARTED.value: self._task_started,
            T.TASK_COMPLETED.value: self._task_completed,
            T.TASK_FAILED.value: self._task_failed,
            T.TASK_SKIPPED.value: self._task_skipped,
            T.AGENT_SPAWNED.value: self._agent_spawned,
            T.AGENT_RELEASED.value: self._agent_released,
            T.MODEL_ROUTED.value: self._model_routed,
            T.LLM_CALLED.value: self._llm_called,
            T.TOOL_CALLED.value: self._tool_called,
            T.TOOL_RESULT.value: self._tool_result,
            T.TOOL_DENIED.value: self._tool_denied,
            T.HOOK_BLOCKED.value: self._hook_blocked,
            T.BUDGET_EXCEEDED.value: self._budget_exceeded,
            T.PASSAGE_ASSESSED.value: self._passage_assessed,
            T.TERM_RESOLVED.value: self._term_resolved,
            T.EVIDENCE_RETRIEVED.value: self._evidence_retrieved,
            T.CLAIM_EXTRACTED.value: self._claim_extracted,
            T.CLAIM_REJECTED.value: self._claim_rejected,
            T.LINEAGE_DETECTED.value: self._lineage_detected,
            T.CONTRADICTION_FOUND.value: self._contradiction_found,
            T.OBSERVATION_RECORDED.value: self._observation_recorded,
            T.ANALYSIS_RECORDED.value: self._analysis_recorded,
            T.HYPOTHESIS_GENERATED.value: self._hypothesis_generated,
            T.COUNTER_EVIDENCE_FOUND.value: self._counter_evidence_found,
            T.HYPOTHESIS_REVIEWED.value: self._hypothesis_reviewed,
            T.HYPOTHESIS_REVISED.value: self._hypothesis_revised,
            T.HYPOTHESIS_REJECTED.value: self._hypothesis_rejected,
            T.HYPOTHESIS_SCORED.value: self._hypothesis_scored,
            T.HYPOTHESIS_RANKED.value: self._hypothesis_ranked,
            T.GATE_EVALUATED.value: self._gate_evaluated,
            T.CHANGE_PROPOSED.value: self._change_proposed,
            T.CHANGE_APPROVED.value: self._change_approved,
            T.CHANGE_REJECTED.value: self._change_rejected,
            T.EXPERT_APPROVED.value: self._expert_approved,
            T.EXPERT_REJECTED.value: self._expert_rejected,
            T.EXPERT_STEERED.value: self._expert_steered,
            T.DECISION_RECORDED.value: self._decision_recorded,
            T.MEMORY_WRITTEN.value: self._memory_written,
            T.BRANCH_FORKED.value: self._branch_forked,
            T.BRANCH_MERGED.value: self._branch_merged,
            T.CHECKPOINT_CREATED.value: self._checkpoint_created,
            T.ARTIFACT_PUBLISHED.value: self._artifact_published,
            T.TRANSACTION_COMMITTED.value: lambda s, e: None,
        }

    # ------------------------------------------------------------------ public
    def apply(self, state: ResearchObject, event: Event) -> None:
        handler = self._handlers.get(event.type)
        if handler is None:
            raise InvalidEvent(f"unknown event type {event.type!r}")
        handler(state, event)

    def replay(self, session_id: str, events: Iterable[Event]) -> ResearchObject:
        state = ResearchObject(session_id=session_id)
        for event in events:
            self.apply(state, event)
        return state

    def validate(self, state: ResearchObject, event: Event, pending_ids: set[str] | None = None) -> None:
        """Check invariants against committed state plus ids created earlier in the same transaction."""
        pending = pending_ids or set()
        p = event.payload
        if event.type not in self._handlers:
            raise InvalidEvent(f"unknown event type {event.type!r}")
        if event.type == T.RESEARCH_CREATED.value:
            if state.goal is not None:
                raise InvalidEvent("GoalSpec is immutable: the session already has a goal contract")
            if "goal" not in p:
                raise InvalidEvent("ResearchCreated requires a goal")
        elif "goal" in p:
            raise InvalidEvent("GoalSpec is immutable: only ResearchCreated may carry a goal")

        def need_hypothesis(hid: str | None) -> None:
            if not hid or (hid not in state.hypotheses and hid not in pending):
                raise InvalidEvent(f"{event.type}: unknown hypothesis {hid!r}")

        if event.type in (T.TASK_STARTED.value, T.TASK_COMPLETED.value, T.TASK_FAILED.value, T.TASK_SKIPPED.value):
            tid = p.get("task_id") or event.task_id
            if tid not in state.task_graph and tid not in pending:
                raise InvalidEvent(f"{event.type}: unknown task {tid!r}")
        elif event.type == T.HYPOTHESIS_REVIEWED.value:
            need_hypothesis(p.get("review", {}).get("hypothesis_id"))
        elif event.type in (T.HYPOTHESIS_REJECTED.value, T.HYPOTHESIS_SCORED.value, T.COUNTER_EVIDENCE_FOUND.value):
            need_hypothesis(p.get("hypothesis_id"))
        elif event.type == T.HYPOTHESIS_REVISED.value:
            need_hypothesis(p.get("hypothesis", {}).get("parent_id"))
        elif event.type in (T.EXPERT_APPROVED.value, T.EXPERT_REJECTED.value):
            if not event.actor.startswith("human:"):
                raise InvalidEvent("only a human expert may approve or reject a hypothesis (Gate G7)")
            need_hypothesis(p.get("hypothesis_id"))
        elif event.type in (T.CHANGE_APPROVED.value, T.CHANGE_REJECTED.value):
            if event.actor.startswith("agent:"):
                raise InvalidEvent("agents may only propose changes; a validator or human must decide")
            cid = p.get("change_id")
            if cid not in state.changes and cid not in pending:
                raise InvalidEvent(f"{event.type}: unknown change {cid!r}")
        elif event.type == T.HYPOTHESIS_RANKED.value:
            for hid in p.get("elo", {}):
                need_hypothesis(hid)

    # --------------------------------------------------------------- lifecycle
    def _research_created(self, s: ResearchObject, e: Event) -> None:
        s.goal = GoalSpec.from_dict(e.payload["goal"])
        s.goal_digest = s.goal.digest()
        declared = e.payload.get("goal_digest")
        if declared and declared != s.goal_digest:
            raise InvalidEvent("goal digest mismatch: GoalSpec was altered")
        s.profile = e.payload.get("profile")
        s.status = "created"

    def _profile_loaded(self, s: ResearchObject, e: Event) -> None:
        s.profile = e.payload.get("profile", s.profile)
        s.metrics["profile"] = e.payload

    def _corpus_scoped(self, s: ResearchObject, e: Event) -> None:
        s.corpus = CorpusManifest.from_dict(e.payload["manifest"])

    def _round_started(self, s: ResearchObject, e: Event) -> None:
        s.round = int(e.payload["round"])
        s.status = "running"

    def _round_completed(self, s: ResearchObject, e: Event) -> None:
        s.rounds[str(e.payload["round"])] = dict(e.payload)

    def _stop_condition_met(self, s: ResearchObject, e: Event) -> None:
        s.stop = dict(e.payload)

    def _research_completed(self, s: ResearchObject, e: Event) -> None:
        s.status = e.payload.get("status", "completed")

    def _research_stopped(self, s: ResearchObject, e: Event) -> None:
        s.status = "stopped"
        s.stop = dict(e.payload)

    # ------------------------------------------------------------ operational
    def _task_planned(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["tasks"]:
            node = TaskNode.from_dict(raw)
            existing = s.task_graph.get(node.id)
            if existing is None or existing.status == "pending":
                s.task_graph[node.id] = node

    def _task(self, s: ResearchObject, e: Event) -> TaskNode:
        return s.task_graph[e.payload.get("task_id") or e.task_id]

    def _task_started(self, s: ResearchObject, e: Event) -> None:
        task = self._task(s, e)
        task.status = "running"
        attempts = s.metrics.setdefault("task_attempts", {})
        attempts[task.id] = attempts.get(task.id, 0) + 1

    def _task_completed(self, s: ResearchObject, e: Event) -> None:
        task = self._task(s, e)
        task.status = "done"
        task.summary = e.payload.get("summary", "")
        task.outputs = list(e.payload.get("outputs", []))

    def _task_failed(self, s: ResearchObject, e: Event) -> None:
        task = self._task(s, e)
        task.status = "failed"
        task.summary = e.payload.get("error", "")

    def _task_skipped(self, s: ResearchObject, e: Event) -> None:
        task = self._task(s, e)
        task.status = "skipped"
        task.summary = e.payload.get("reason", "")

    def _agent_spawned(self, s: ResearchObject, e: Event) -> None:
        agent = AgentInstance.from_dict(e.payload["agent"])
        s.agents[agent.id] = agent
        _count(s.metrics, "agents_spawned")

    def _agent_released(self, s: ResearchObject, e: Event) -> None:
        agent = s.agents.get(e.payload["agent_id"])
        if agent is not None:
            agent.status = "released"
            agent.usage = dict(e.payload.get("usage", {}))
        ctx = e.payload.get("usage", {}).get("context_tokens")
        if ctx:
            s.metrics.setdefault("context_tokens", []).append(ctx)

    def _model_routed(self, s: ResearchObject, e: Event) -> None:
        s.metrics.setdefault("routes", {})[e.payload.get("agent_id", "?")] = e.payload.get("route", {})

    def _llm_called(self, s: ResearchObject, e: Event) -> None:
        m = s.metrics
        _count(m, "llm_calls")
        usage = e.payload.get("usage", {})
        _count(m, "input_tokens", usage.get("input_tokens", 0))
        _count(m, "output_tokens", usage.get("output_tokens", 0))
        _count(m, "cost_usd", usage.get("cost_usd", 0.0))

    def _tool_called(self, s: ResearchObject, e: Event) -> None:
        _count(s.metrics, "tool_calls")
        by_tool = s.metrics.setdefault("tool_calls_by_tool", {})
        by_tool[e.payload["tool"]] = by_tool.get(e.payload["tool"], 0) + 1

    def _tool_result(self, s: ResearchObject, e: Event) -> None:
        if not e.payload.get("ok", True):
            _count(s.metrics, "tool_errors")

    def _tool_denied(self, s: ResearchObject, e: Event) -> None:
        _count(s.metrics, "tool_denials")

    def _hook_blocked(self, s: ResearchObject, e: Event) -> None:
        _count(s.metrics, "hook_blocks")
        by_hook = s.metrics.setdefault("hook_blocks_by_hook", {})
        by_hook[e.payload.get("hook", "?")] = by_hook.get(e.payload.get("hook", "?"), 0) + 1

    def _budget_exceeded(self, s: ResearchObject, e: Event) -> None:
        s.metrics["budget_exceeded"] = dict(e.payload)

    def _checkpoint_created(self, s: ResearchObject, e: Event) -> None:
        s.metrics["last_checkpoint"] = dict(e.payload)

    def _memory_written(self, s: ResearchObject, e: Event) -> None:
        _count(s.metrics, "memory_writes")

    # -------------------------------------------------------------- knowledge
    def _passage_assessed(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["assessments"]:
            assessment = PhilologyAssessment.from_dict(raw)
            s.philology[assessment.passage_id] = assessment

    def _term_resolved(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["resolutions"]:
            res = TermResolution.from_dict(raw)
            s.term_resolutions[res.id] = res

    def _attach_evidence(self, s: ResearchObject, rec: EvidenceRecord) -> None:
        h = s.hypotheses.get(rec.hypothesis_id or "")
        if h is None:
            return
        target = h.contradictory_evidence if rec.stance == Stance.CONTRADICTS else h.supporting_evidence
        if rec.stance in (Stance.SUPPORTS, Stance.CONTRADICTS) and rec.id not in target:
            target.append(rec.id)

    def _evidence_retrieved(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["records"]:
            rec = EvidenceRecord.from_dict(raw)
            if rec.id not in s.evidence:
                s.evidence[rec.id] = rec
            self._attach_evidence(s, s.evidence[rec.id])

    def _claim_extracted(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["claims"]:
            claim = Claim.from_dict(raw)
            claim.status = "committed"
            s.claims[claim.id] = claim

    def _claim_rejected(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["rejections"]:
            s.rejected_claims[raw["claim_id"]] = dict(raw)

    def _lineage_detected(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["edges"]:
            edge = LineageEdge.from_dict(raw)
            s.lineage[edge.id] = edge

    def _contradiction_found(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["contradictions"]:
            c = Contradiction.from_dict(raw)
            s.contradictions[c.id] = c

    def _observation_recorded(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["observations"]:
            obs = Observation.from_dict(raw)
            s.observations[obs.id] = obs

    def _analysis_recorded(self, s: ResearchObject, e: Event) -> None:
        aid = e.payload["analysis_id"]
        s.analyses[aid] = dict(e.payload)
        target = e.payload.get("target_id")
        stats = e.payload.get("result", {}).get("statistics")
        if target in s.observations and isinstance(stats, dict):
            s.observations[target].statistics.update(stats)

    # ------------------------------------------------------------- hypotheses
    def _hypothesis_generated(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["hypotheses"]:
            h = Hypothesis.from_dict(raw)
            s.hypotheses[h.id] = h
            for rec in s.evidence.values():
                if rec.hypothesis_id == h.id:
                    self._attach_evidence(s, rec)

    def _counter_evidence_found(self, s: ResearchObject, e: Event) -> None:
        h = s.hypotheses[e.payload["hypothesis_id"]]
        for raw in e.payload["records"]:
            rec = EvidenceRecord.from_dict(raw)
            rec.stance = Stance.CONTRADICTS
            rec.hypothesis_id = h.id
            s.evidence.setdefault(rec.id, rec)
            if rec.id not in h.contradictory_evidence:
                h.contradictory_evidence.append(rec.id)

    def _hypothesis_reviewed(self, s: ResearchObject, e: Event) -> None:
        review = HypothesisReview.from_dict(e.payload["review"])
        s.reviews[review.id] = review
        h = s.hypotheses[review.hypothesis_id]
        if h.status not in ("expert_approved", "expert_rejected", "superseded"):
            h.status = {"survives": "survived", "revise": "needs_revision", "reject": "rejected"}.get(
                review.verdict, h.status
            )

    def _hypothesis_revised(self, s: ResearchObject, e: Event) -> None:
        new = Hypothesis.from_dict(e.payload["hypothesis"])
        parent = s.hypotheses[new.parent_id]  # type: ignore[index]
        parent.status = "superseded"
        s.hypotheses[new.id] = new
        for rec in s.evidence.values():
            if rec.hypothesis_id == new.id:
                self._attach_evidence(s, rec)

    def _hypothesis_rejected(self, s: ResearchObject, e: Event) -> None:
        s.hypotheses[e.payload["hypothesis_id"]].status = "rejected"

    def _hypothesis_scored(self, s: ResearchObject, e: Event) -> None:
        h = s.hypotheses[e.payload["hypothesis_id"]]
        if "scores" in e.payload:
            h.scores = ScoreCard.from_dict(e.payload["scores"])
        if "discovery_score" in e.payload:
            h.discovery_score = e.payload["discovery_score"]
            h.discovery_components = dict(e.payload.get("components", {}))
        if "confidence" in e.payload:
            h.confidence = ConfidenceVector.from_dict(e.payload["confidence"])
        if "novelty" in e.payload:
            h.novelty = e.payload["novelty"]
            h.novelty_rationale = e.payload.get("novelty_rationale", h.novelty_rationale)

    def _hypothesis_ranked(self, s: ResearchObject, e: Event) -> None:
        for hid, elo in e.payload["elo"].items():
            s.hypotheses[hid].elo = float(elo)
        s.analyses[f"tournament:r{e.payload.get('round', 0)}"] = {
            "kind": "tournament",
            "matches": e.payload.get("matches", []),
            "elo": dict(e.payload["elo"]),
        }

    def _gate_evaluated(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["results"]:
            result = GateResult.from_dict(raw)
            s.gates.setdefault(result.subject_id, {})[result.gate] = result

    # ------------------------------------------------------------- governance
    def _change_proposed(self, s: ResearchObject, e: Event) -> None:
        change = ProposedChange.from_dict(e.payload["change"])
        s.changes[change.id] = change

    def _change_approved(self, s: ResearchObject, e: Event) -> None:
        change = s.changes[e.payload["change_id"]]
        change.status = "approved"
        change.decided_by = e.actor
        change.note = e.payload.get("note", change.note)

    def _change_rejected(self, s: ResearchObject, e: Event) -> None:
        change = s.changes[e.payload["change_id"]]
        change.status = "rejected"
        change.decided_by = e.actor
        change.note = e.payload.get("note", change.note)

    def _expert_approved(self, s: ResearchObject, e: Event) -> None:
        hid = e.payload["hypothesis_id"]
        s.hypotheses[hid].status = "expert_approved"
        s.expert_actions[f"{hid}:approve"] = {"actor": e.actor, **e.payload}
        s.gates.setdefault(hid, {})["G7"] = GateResult(
            gate="G7", subject_id=hid, status="pass", score=1.0, details=f"approved by {e.actor}"
        )

    def _expert_rejected(self, s: ResearchObject, e: Event) -> None:
        hid = e.payload["hypothesis_id"]
        s.hypotheses[hid].status = "expert_rejected"
        s.expert_actions[f"{hid}:reject"] = {"actor": e.actor, **e.payload}
        s.gates.setdefault(hid, {})["G7"] = GateResult(
            gate="G7", subject_id=hid, status="fail", score=0.0, details=f"rejected by {e.actor}"
        )

    def _expert_steered(self, s: ResearchObject, e: Event) -> None:
        key = stable_id("steer", e.actor, e.payload)
        s.expert_actions[key] = {"actor": e.actor, "kind": "steer", **e.payload}

    def _decision_recorded(self, s: ResearchObject, e: Event) -> None:
        for raw in e.payload["decisions"]:
            d = Decision.from_dict(raw)
            s.decisions[d.id] = d

    # ------------------------------------------------------------- durability
    def _branch_forked(self, s: ResearchObject, e: Event) -> None:
        p = e.payload
        if p.get("role") == "child":
            d = Decision(
                id=stable_id("dec", "fork-origin", p["parent_session"], p["at_seq"]),
                kind="fork_origin",
                summary=f"forked from {p['parent_session']} at seq {p['at_seq']}",
                rationale=p.get("purpose", ""),
                made_by=e.actor,
                refs=[p["parent_session"]] + ([p["hypothesis_id"]] if p.get("hypothesis_id") else []),
            )
            s.decisions[d.id] = d
        else:
            s.branches[p["branch_id"]] = BranchInfo(
                id=p["branch_id"],
                parent_session=p["parent_session"],
                at_seq=int(p["at_seq"]),
                purpose=p.get("purpose", ""),
                hypothesis_id=p.get("hypothesis_id"),
            )

    def _branch_merged(self, s: ResearchObject, e: Event) -> None:
        branch = s.branches.get(e.payload["branch_id"])
        if branch is not None:
            branch.status = "merged"
            branch.outcome = dict(e.payload.get("outcome", {}))

    def _artifact_published(self, s: ResearchObject, e: Event) -> None:
        artifact = Artifact.from_dict(e.payload["artifact"])
        s.artifacts[artifact.id] = artifact
