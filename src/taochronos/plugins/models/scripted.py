"""Scripted provider: replays queued responses (tests, demos, regression fixtures).

Each scripted step is either an ``LLMResponse`` or a mapping such as
``{"tool_uses": [{"name": "classics__search", "input": {...}}]}`` /
``{"text": "{...json...}"}``.  Requests are recorded for assertions.
"""

from __future__ import annotations

from typing import Any

from ...capabilities.llm import LLMError, LLMRequest, LLMResponse, ModelInfo, ToolUse, Usage


class ScriptedProvider:
    deterministic = False

    def __init__(self, steps: list[Any] | None = None, *, name: str = "scripted", tier: str = "frontier") -> None:
        self.name = name
        self.tier = tier
        self.steps = list(steps or [])
        self.requests: list[LLMRequest] = []

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(name=f"{self.name}-model", provider=self.name, tier=self.tier, input_cost_per_mtok=1.0,
                          output_cost_per_mtok=2.0, reasoning=True, classical_chinese=0.9)]

    def available(self) -> bool:
        return True

    def push(self, *steps: Any) -> None:
        self.steps.extend(steps)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self.steps:
            raise LLMError("scripted provider exhausted")
        step = self.steps.pop(0)
        if isinstance(step, LLMResponse):
            return step
        if callable(step):
            return step(request)
        uses = [ToolUse(id=u.get("id", f"tu_{len(self.requests)}_{i}"), name=u["name"], input=u.get("input", {}))
                for i, u in enumerate(step.get("tool_uses", []))]
        return LLMResponse(
            text=step.get("text", ""),
            tool_uses=uses,
            stop_reason=step.get("stop_reason", "tool_use" if uses else "end_turn"),
            usage=Usage(input_tokens=step.get("input_tokens", 100), output_tokens=step.get("output_tokens", 50)),
            model=request.model,
        )


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("llm", config.get("name", "scripted"), ScriptedProvider(config.get("steps", []), name=config.get("name", "scripted")))
