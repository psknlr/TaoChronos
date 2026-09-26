"""In-process subagents: a spawned task runs through the same AgentRuntime (same gates, same log)."""

from __future__ import annotations

from typing import Any


class LocalSubagentProvider:
    name = "local"

    def available(self) -> bool:
        return True

    def run_task(self, runtime: Any, session: Any, task: Any, *, budget: Any = None) -> Any:
        return runtime.run_task(session, task, budget=budget)

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - local runs tasks, not payloads
        raise NotImplementedError("the local provider runs tasks through the AgentRuntime; use run_task()")
