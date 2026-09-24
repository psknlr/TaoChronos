"""Claude provider (official ``anthropic`` Python SDK; install with ``pip install taochronos[anthropic]``).

* Default frontier model ``claude-opus-5``; ``claude-sonnet-5`` and ``claude-haiku-4-5``
  serve the Cognitive Router's medium and small tiers.
* Adaptive thinking + ``output_config.effort`` on models that support them
  (Haiku 4.5 takes neither).
* Server-side refusal fallbacks (``fallbacks="default"``) are enabled by default on
  Opus 5 / Fable 5.1 requests.
* ``stop_reason == "refusal"`` is checked before content is read; assistant turns
  are replayed verbatim (``raw``) so thinking blocks round-trip unchanged.

Credentials are resolved by the SDK (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN``
or an ``ant auth login`` profile).
"""

from __future__ import annotations

import os
from typing import Any

from ...capabilities.llm import LLMError, LLMRequest, LLMResponse, Message, ModelInfo, ToolUse, Usage

DEFAULT_MODELS = [
    ModelInfo(name="claude-opus-5", provider="anthropic", tier="frontier", context_window=1_000_000,
              input_cost_per_mtok=5.0, output_cost_per_mtok=25.0, reasoning=True, classical_chinese=0.8),
    ModelInfo(name="claude-sonnet-5", provider="anthropic", tier="medium", context_window=1_000_000,
              input_cost_per_mtok=2.0, output_cost_per_mtok=10.0, reasoning=True, classical_chinese=0.75),
    ModelInfo(name="claude-haiku-4-5", provider="anthropic", tier="small", context_window=200_000,
              input_cost_per_mtok=1.0, output_cost_per_mtok=5.0, reasoning=False, classical_chinese=0.6),
]
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
NO_EFFORT_MODELS = {"claude-haiku-4-5"}


class AnthropicProvider:
    name = "anthropic"
    deterministic = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._models = [
            ModelInfo(**{**m.__dict__, **override}) if (override := self.config.get("overrides", {}).get(m.name)) else m
            for m in DEFAULT_MODELS
        ]
        extra = self.config.get("models") or []
        for m in extra:
            self._models.append(ModelInfo(provider="anthropic", **m))
        self._client: Any = None

    def models(self) -> list[ModelInfo]:
        return list(self._models)

    def available(self) -> bool:
        if self.config.get("enabled") is False:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        creds = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")
        return bool(self.config.get("enabled")) or any(os.environ.get(k) for k in creds)

    def _client_(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    @staticmethod
    def to_wire(messages: list[Message]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "assistant":
                if m.raw is not None:
                    content = m.raw
                else:
                    content = ([{"type": "text", "text": m.text}] if m.text else []) + [
                        {"type": "tool_use", "id": t.id, "name": t.name, "input": t.input} for t in m.tool_uses
                    ]
                wire.append({"role": "assistant", "content": content})
            else:
                if m.tool_results:
                    blocks: list[dict[str, Any]] = [
                        {"type": "tool_result", "tool_use_id": r.tool_use_id, "content": r.content, "is_error": r.is_error}
                        for r in m.tool_results
                    ]
                    if m.text:
                        blocks.append({"type": "text", "text": m.text})
                    wire.append({"role": "user", "content": blocks})
                else:
                    wire.append({"role": "user", "content": m.text})
        return wire

    def complete(self, request: LLMRequest) -> LLMResponse:
        import anthropic

        info = next((m for m in self._models if m.name == request.model), None)
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": self.to_wire(request.messages),
        }
        if request.tools:
            params["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in request.tools]
        if info is not None and info.reasoning and request.model not in NO_EFFORT_MODELS:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": request.effort or "high"}
        client = self._client_()
        try:
            if request.model in FALLBACK_MODELS and self.config.get("fallbacks", True):
                response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                response = client.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise LLMError(f"rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"network error contacting the Claude API: {exc}") from exc
        usage = Usage(input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
                      output_tokens=getattr(response.usage, "output_tokens", 0) or 0)
        if info is not None:
            usage.cost_usd = info.cost(usage)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            note = f"category={getattr(details, 'category', None)}" if details else ""
            return LLMResponse(text="", tool_uses=[], stop_reason="refusal", usage=usage, model=response.model, note=note)
        text = "".join(b.text for b in response.content if b.type == "text")
        uses = [ToolUse(id=b.id, name=b.name, input=dict(b.input)) for b in response.content if b.type == "tool_use"]
        raw = response.to_dict().get("content")
        return LLMResponse(text=text, tool_uses=uses, stop_reason=response.stop_reason or "end_turn", usage=usage,
                           model=response.model, raw=raw)


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("llm", "anthropic", AnthropicProvider(config))
