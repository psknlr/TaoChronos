"""Deterministic offline provider.

Selecting it means “run the agent's deterministic procedure”: the harness stays
fully functional (and reproducible) without any model API.  It never generates
free text.
"""

from __future__ import annotations

from typing import Any

from ...capabilities.llm import LLMError, LLMRequest, LLMResponse, ModelInfo

OFFLINE_MODEL = "taochronos-offline"


class OfflineProvider:
    name = "offline"
    deterministic = True

    def models(self) -> list[ModelInfo]:
        return [ModelInfo(name=OFFLINE_MODEL, provider=self.name, tier="deterministic", context_window=10**9,
                          supports_tools=True, deterministic=True, classical_chinese=0.0)]

    def available(self) -> bool:
        return True

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMError("the offline provider runs deterministic procedures and does not generate text")


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("llm", "offline", OfflineProvider())
