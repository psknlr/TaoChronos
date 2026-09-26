"""OpenAI-compatible chat-completions providers (OpenAI, DeepSeek, xAI Grok, Gemini's
compatibility endpoint, local vLLM/Ollama servers).

Model names are *configured*, never assumed: add them in a profile, e.g.

    models:
      openai_compat:
        providers:
          deepseek:
            models:
              - {name: <model-id>, tier: medium, classical_chinese: 0.8}
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from ...capabilities.llm import LLMError, LLMRequest, LLMResponse, Message, ModelInfo, ToolUse, Usage

PRESETS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "grok": {"base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
    "local": {"base_url": "http://localhost:8000/v1", "api_key_env": None},
}


class OpenAICompatibleProvider:
    deterministic = False

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        preset = PRESETS.get(config.get("preset", name), {})
        self.name = name
        self.base_url = config.get("base_url", preset.get("base_url", "")).rstrip("/")
        self.api_key_env = config.get("api_key_env", preset.get("api_key_env"))
        self.timeout = float(config.get("timeout", 120))
        self._models = [
            ModelInfo(
                name=m["name"], provider=name, tier=m.get("tier", "medium"), context_window=int(m.get("context_window", 128_000)),
                input_cost_per_mtok=float(m.get("input_cost_per_mtok", 0.0)), output_cost_per_mtok=float(m.get("output_cost_per_mtok", 0.0)),
                classical_chinese=float(m.get("classical_chinese", 0.5)), reasoning=bool(m.get("reasoning", False)),
                modalities=tuple(m.get("modalities", ["text"])),
            )
            for m in config.get("models", [])
        ]

    def models(self) -> list[ModelInfo]:
        return list(self._models)

    def available(self) -> bool:
        if not self._models or not self.base_url:
            return False
        return self.api_key_env is None or bool(os.environ.get(self.api_key_env))

    @staticmethod
    def to_wire(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.text or None}
                if m.tool_uses:
                    msg["tool_calls"] = [
                        {"id": t.id, "type": "function", "function": {"name": t.name, "arguments": json.dumps(t.input, ensure_ascii=False)}}
                        for t in m.tool_uses
                    ]
                wire.append(msg)
            else:
                for r in m.tool_results:
                    wire.append({"role": "tool", "tool_call_id": r.tool_use_id, "content": r.content})
                if m.text:
                    wire.append({"role": "user", "content": m.text})
        return wire

    def complete(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {"model": request.model, "messages": self.to_wire(request.system, request.messages),
                                "max_tokens": request.max_tokens}
        if request.tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                             for t in request.tools]
        headers = {"Content-Type": "application/json"}
        if self.api_key_env:
            headers["Authorization"] = f"Bearer {os.environ.get(self.api_key_env, '')}"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(f"{self.base_url}/chat/completions", data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"{self.name} HTTP {exc.code}: {exc.read()[:300]!r}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"{self.name} connection error: {exc}") from exc
        else:  # pragma: no cover
            raise LLMError(f"{self.name} failed: {last_error}")
        choice = payload["choices"][0]
        msg = choice.get("message", {})
        uses = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"].get("arguments")}
            uses.append(ToolUse(id=tc["id"], name=tc["function"]["name"], input=args))
        finish = choice.get("finish_reason")
        stop = {"tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}.get(finish, "tool_use" if uses else "end_turn")
        u = payload.get("usage", {})
        usage = Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))
        info = next((m for m in self._models if m.name == request.model), None)
        if info is not None:
            usage.cost_usd = info.cost(usage)
        return LLMResponse(text=msg.get("content") or "", tool_uses=uses, stop_reason=stop, usage=usage, model=payload.get("model", request.model))


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    for name, cfg in (config.get("providers") or {}).items():
        registry.register("llm", name, OpenAICompatibleProvider(name, cfg or {}))
