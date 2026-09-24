"""Subagent providers: where a spawned agent actually runs (in-process or an external command)."""

from __future__ import annotations

from typing import Any

from .command import CommandSubagentProvider, SubagentError
from .local import LocalSubagentProvider


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("subagent", "local", LocalSubagentProvider(), default=True)
    for name, cfg in ((config.get("command") or {}).get("providers") or {}).items():
        registry.register("subagent", name, CommandSubagentProvider(name, list(cfg.get("command", [])),
                                                                    timeout=float(cfg.get("timeout", 600))))


__all__ = ["CommandSubagentProvider", "LocalSubagentProvider", "SubagentError", "register"]
