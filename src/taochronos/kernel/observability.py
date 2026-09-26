"""Observability: research-level metrics and traces, not just tokens and latency."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from ..protocol.events import Event, EventType
from ..protocol.evidence import Stance
from ..protocol.research import ResearchObject

SURVIVING = ("survived", "expert_approved")
JUDGED = SURVIVING + ("rejected", "superseded", "expert_rejected", "needs_revision")


def _entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0 or len(counts) < 2:
        return 0.0
    h = -sum((c / total) * math.log(c / total) for c in counts.values() if c)
    return round(h / math.log(len(counts)), 4)


def research_metrics(state: ResearchObject) -> dict[str, Any]:
    evidence = list(state.evidence.values())
    books = Counter(e.book_id for e in evidence)
    hypotheses = list(state.hypotheses.values())
    judged = [h for h in hypotheses if h.status in JUDGED]
    survived = [h for h in hypotheses if h.status in SURVIVING]
    gate_counts: dict[str, Counter] = defaultdict(Counter)
    for results in state.gates.values():
        for gate, result in results.items():
            gate_counts[gate][result.status] += 1
    ctx = state.metrics.get("context_tokens", [])
    m = state.metrics
    return {
        "status": state.status,
        "round": state.round,
        "claims": len(state.claims),
        "rejected_claims": len(state.rejected_claims),
        "evidence_count": len(evidence),
        "counter_evidence": sum(1 for e in evidence if e.stance == Stance.CONTRADICTS),
        "observations": len(state.observations),
        "contradictions": len(state.contradictions),
        "lineage_edges": len(state.lineage),
        "hypotheses": len(hypotheses),
        "hypothesis_survival": round(len(survived) / len(judged), 4) if judged else None,
        "source_diversity": {"books": len(books), "normalised_entropy": _entropy(books)},
        "knowledge_gain": {r: {k: v for k, v in s.items() if k.startswith("new_")} for r, s in sorted(state.rounds.items())},
        "gates": {g: dict(c) for g, c in sorted(gate_counts.items())},
        "agents_spawned": m.get("agents_spawned", 0),
        "context_tokens_mean": round(sum(ctx) / len(ctx), 1) if ctx else None,
        "llm_calls": m.get("llm_calls", 0),
        "input_tokens": m.get("input_tokens", 0),
        "output_tokens": m.get("output_tokens", 0),
        "cost_usd": round(m.get("cost_usd", 0.0), 6),
        "tool_calls": m.get("tool_calls", 0),
        "tool_errors": m.get("tool_errors", 0),
        "tool_denials": m.get("tool_denials", 0),
        "hook_blocks": m.get("hook_blocks", 0),
        "tool_calls_by_tool": dict(sorted(m.get("tool_calls_by_tool", {}).items())),
        "changes_proposed": len(state.changes),
        "artifacts": len(state.artifacts),
    }


def agent_tree(events: list[Event]) -> str:
    """Render round → task → agent → tool-call counts from the event log."""
    tasks: dict[str, dict[str, Any]] = {}
    agent_of_task: dict[str, str] = {}
    tools_by_agent: dict[str, Counter] = defaultdict(Counter)
    models: dict[str, str] = {}
    order: list[str] = []
    for ev in events:
        if ev.type == EventType.TASK_PLANNED.value:
            for t in ev.payload["tasks"]:
                if t["id"] not in tasks:
                    tasks[t["id"]] = {"kind": t["kind"], "role": t["role"], "round": t.get("round", 0), "status": "pending"}
                    order.append(t["id"])
        elif ev.type == EventType.AGENT_SPAWNED.value:
            agent = ev.payload["agent"]
            if agent.get("task_id"):
                agent_of_task[agent["task_id"]] = agent["id"]
            models[agent["id"]] = f"{agent.get('provider') or '?'}:{agent.get('model') or '?'}"
        elif ev.type == EventType.TOOL_CALLED.value:
            tools_by_agent[ev.actor][ev.payload["tool"]] += 1
        elif ev.type in (EventType.TASK_COMPLETED.value, EventType.TASK_FAILED.value, EventType.TASK_SKIPPED.value):
            tid = ev.payload.get("task_id") or ev.task_id
            if tid in tasks:
                tasks[tid]["status"] = {"TaskCompleted": "done", "TaskFailed": "failed", "TaskSkipped": "skipped"}[ev.type]
    lines: list[str] = []
    by_round: dict[int, list[str]] = defaultdict(list)
    for tid in order:
        by_round[tasks[tid]["round"]].append(tid)
    for rnd in sorted(by_round):
        lines.append(f"round {rnd}")
        for tid in by_round[rnd]:
            t = tasks[tid]
            agent = agent_of_task.get(tid)
            lines.append(f"  ├─ {tid} [{t['status']}] {t['kind']} ← {t['role']}")
            if agent:
                tools = ", ".join(f"{name}×{n}" for name, n in sorted(tools_by_agent.get(agent, {}).items()))
                lines.append(f"  │   └─ {agent} ({models.get(agent, '?')}){' · ' + tools if tools else ''}")
    return "\n".join(lines)


def research_tree(state: ResearchObject) -> str:
    """Hypothesis genealogy: generations, revisions, verdicts and Elo."""
    children: dict[str | None, list[str]] = defaultdict(list)
    for h in state.hypotheses.values():
        children[h.parent_id].append(h.id)
    lines: list[str] = []

    def walk(hid: str, depth: int) -> None:
        h = state.hypotheses[hid]
        score = f" D={h.discovery_score:.3f}" if h.discovery_score is not None else ""
        lines.append(f"{'  ' * depth}• {h.id} [{h.status}] gen{h.generation} elo={h.elo:.0f}{score} — {h.statement[:60]}")
        for child in sorted(children.get(hid, [])):
            walk(child, depth + 1)

    for root in sorted(children.get(None, [])):
        walk(root, 0)
    return "\n".join(lines) if lines else "(no hypotheses)"
