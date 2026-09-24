"""Provider-neutral LLM capability.

Agents never import a vendor SDK.  They receive an ``LLMProvider`` from the
capability registry (via the Cognitive Router) and speak this neutral message
format; each provider plugin translates it to its own wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

TIERS = ("deterministic", "small", "medium", "frontier")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: str  # user | assistant
    text: str = ""
    tool_uses: list[ToolUse] = field(default_factory=list)
    tool_results: list[ToolResultBlock] = field(default_factory=list)
    raw: Any = None  # provider-native content to replay unchanged (e.g. thinking blocks)


@dataclass
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class LLMRequest:
    model: str
    system: str
    messages: list[Message]
    tools: list[ToolSchema] = field(default_factory=list)
    max_tokens: int = 16000
    effort: str | None = None  # low | medium | high | xhigh | max
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "cost_usd": round(self.cost_usd, 6)}


@dataclass
class LLMResponse:
    text: str
    tool_uses: list[ToolUse]
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal | error
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: Any = None
    note: str = ""


@dataclass
class ModelInfo:
    name: str
    provider: str
    tier: str
    context_window: int = 200_000
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    modalities: tuple[str, ...] = ("text",)
    supports_tools: bool = True
    classical_chinese: float = 0.5  # configured prior, not a benchmark claim
    reasoning: bool = False
    deterministic: bool = False

    def cost(self, usage: Usage) -> float:
        return (usage.input_tokens * self.input_cost_per_mtok + usage.output_tokens * self.output_cost_per_mtok) / 1_000_000


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    deterministic: bool

    def models(self) -> list[ModelInfo]: ...

    def available(self) -> bool: ...

    def complete(self, request: LLMRequest) -> LLMResponse: ...
