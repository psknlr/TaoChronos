"""Capability interfaces. Business code depends on these, never on concrete providers.

``llm``         LLMProvider (neutral messages, tool use, usage)
``embedding``   objects with ``embed(text) -> list[float]``
``retriever``   objects with ``search(query, k, after, before, routes, books)``
``sandbox``     objects with ``run(code, inputs, ...)``
``subagent``    objects with ``spawn(spec, task, parent) -> result``
``storage``     objects with ``put(key, data) / get(key)``
"""

from .llm import (
    TIER_RANK,
    TIERS,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    ModelInfo,
    ToolResultBlock,
    ToolSchema,
    ToolUse,
    Usage,
)

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "ModelInfo",
    "TIERS",
    "TIER_RANK",
    "ToolResultBlock",
    "ToolSchema",
    "ToolUse",
    "Usage",
]
