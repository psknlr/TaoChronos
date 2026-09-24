"""Lifecycle hooks: deterministic guards the harness runs around agent actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class HookPoint(str, Enum):
    RESEARCH_START = "ResearchStart"
    BEFORE_TOOL_CALL = "BeforeToolCall"
    AFTER_TOOL_CALL = "AfterToolCall"
    BEFORE_LLM_CALL = "BeforeLLMCall"
    BEFORE_CLAIM_COMMIT = "BeforeClaimCommit"
    AFTER_HYPOTHESIS = "AfterHypothesis"
    BEFORE_GRAPH_WRITE = "BeforeGraphWrite"
    BEFORE_ARTIFACT_PUBLISH = "BeforeArtifactPublish"
    RESEARCH_END = "ResearchEnd"


@dataclass
class HookContext:
    point: HookPoint
    subject: Any = None
    actor: Any = None
    session: Any = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    allow: bool = True
    reason: str = ""
    subject: Any = None  # a hook may return a modified subject
    annotations: dict[str, Any] = field(default_factory=dict)
    hook: str = ""


HookFn = Callable[[HookContext], "HookResult | None"]


@dataclass
class _Registered:
    name: str
    fn: HookFn
    priority: int


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[_Registered]] = {}

    def register(self, point: HookPoint | str, name: str, fn: HookFn, priority: int = 100) -> None:
        point = HookPoint(point)
        hooks = self._hooks.setdefault(point, [])
        hooks[:] = [h for h in hooks if h.name != name]
        hooks.append(_Registered(name, fn, priority))
        hooks.sort(key=lambda h: (h.priority, h.name))

    def unregister(self, name: str) -> None:
        for hooks in self._hooks.values():
            hooks[:] = [h for h in hooks if h.name != name]

    def names(self, point: HookPoint | str | None = None) -> list[str]:
        if point is None:
            return sorted({h.name for hooks in self._hooks.values() for h in hooks})
        return [h.name for h in self._hooks.get(HookPoint(point), [])]

    def run(self, ctx: HookContext) -> HookResult:
        """Run hooks in priority order. The first blocking hook wins; modifications chain."""
        annotations: dict[str, Any] = {}
        for hook in self._hooks.get(ctx.point, []):
            result = hook.fn(ctx)
            if result is None:
                continue
            annotations.update(result.annotations)
            if result.subject is not None:
                ctx.subject = result.subject
            if not result.allow:
                return HookResult(
                    allow=False, reason=result.reason, subject=ctx.subject, annotations=annotations, hook=hook.name
                )
        return HookResult(allow=True, subject=ctx.subject, annotations=annotations)
