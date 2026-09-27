"""OpenAI-compatible chat-completions providers: OpenAI, DeepSeek, xAI Grok, Gemini's compatibility
endpoint, MiniMax (mainland ``api.minimax.cn`` or global ``api.minimax.io``), Poe, Qwen (DashScope),
Moonshot / Kimi, Zhipu GLM, SiliconFlow, Volcengine Ark, OpenRouter, a LiteLLM proxy and local
vLLM / Ollama servers.

Model names are *configured*, never assumed: add them in a profile, e.g.

    models:
      openai_compat:
        providers:
          minimax:
            preset: minimax           # base URL, key variable and wire quirks
            models:
              - {name: MiniMax-M2.7, tier: medium, classical_chinese: 0.8}

or name one on the command line (``--llm minimax:MiniMax-M2.7``).  ``PRESETS[...]["examples"]``
lists model names the vendors documented when this preset was written, for the CLI to suggest;
they are not registered.

Wire quirks handled per preset: MiniMax returns its reasoning inside ``<think>…</think>`` unless
``reasoning_split`` is set (it is), and takes ``max_completion_tokens``; Poe rejects
``response_format`` (JSON is then asked for in the prompt only); every reply is stripped of a
leading ``<think>`` block before it is read.  Retries honour ``Retry-After`` on 429 and back off
on 5xx and timeouts.  Credentials come from the environment variable the preset names; they are
never logged.
"""

from __future__ import annotations

import json
import os
import random
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from ...capabilities.llm import LLMError, LLMRequest, LLMResponse, Message, ModelInfo, ToolUse, Usage

PRESETS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY",
               "max_tokens_param": "max_completion_tokens", "response_format": True},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY", "response_format": True,
                 "examples": ["deepseek-chat", "deepseek-reasoner"]},
    "grok": {"base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
    # MiniMax: the mainland platform (platform.minimax.cn); api.minimaxi.com is its older host and still answers
    "minimax": {"base_url": "https://api.minimax.cn/v1", "api_key_env": "MINIMAX_API_KEY",
                "max_tokens_param": "max_completion_tokens", "extra_body": {"reasoning_split": True}, "vision": True,
                "examples": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5"]},
    "minimax-global": {"base_url": "https://api.minimax.io/v1", "api_key_env": "MINIMAX_API_KEY",
                       "max_tokens_param": "max_completion_tokens", "extra_body": {"reasoning_split": True}, "vision": True,
                       "examples": ["MiniMax-M3", "MiniMax-M2.7"]},
    # Poe: model names are Poe bot names (GET https://api.poe.com/v1/models lists them); no response_format
    "poe": {"base_url": "https://api.poe.com/v1", "api_key_env": "POE_API_KEY", "response_format": False, "vision": True,
            "examples": ["claude-opus-4.8", "claude-sonnet-4.6", "gpt-5.4", "gemini-3.1-pro", "kimi-k3", "qwen3-max-n"]},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "DASHSCOPE_API_KEY",
             "response_format": True},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "api_key_env": "MOONSHOT_API_KEY", "response_format": True},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPUAI_API_KEY", "response_format": True},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "api_key_env": "SILICONFLOW_API_KEY"},
    "ark": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "api_key_env": "ARK_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY", "response_format": True},
    # a LiteLLM proxy (`litellm --config …`, port 4000 by default); its master key if one is set
    "litellm-proxy": {"base_url": "http://localhost:4000/v1", "api_key_env": "LITELLM_API_KEY", "key_optional": True,
                      "response_format": True},
    "local": {"base_url": "http://localhost:8000/v1", "api_key_env": None},
}

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)


def strip_think(text: str) -> tuple[str, str]:
    """(answer, reasoning): a leading ``<think>…</think>`` block taken out of a reply."""
    m = THINK.match(text or "")
    if not m:
        return text or "", ""
    return text[m.end():], m.group(0).strip()[7:-8].strip()


def model_info(provider: str, m: dict[str, Any] | str) -> ModelInfo:
    if isinstance(m, str):
        m = {"name": m}
    return ModelInfo(
        name=m["name"], provider=provider, tier=m.get("tier", "medium"), context_window=int(m.get("context_window", 128_000)),
        input_cost_per_mtok=float(m.get("input_cost_per_mtok", 0.0)), output_cost_per_mtok=float(m.get("output_cost_per_mtok", 0.0)),
        classical_chinese=float(m.get("classical_chinese", 0.5)), reasoning=bool(m.get("reasoning", False)),
        modalities=tuple(m.get("modalities", ["text"])), supports_tools=bool(m.get("supports_tools", True)),
    )


class OpenAICompatibleProvider:
    deterministic = False

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        preset = PRESETS.get(config.get("preset", name), {})
        self.name = name
        self.preset = config.get("preset", name if name in PRESETS else None)
        env_base = os.environ.get(f"{name.upper().replace('-', '_')}_BASE_URL")
        self.base_url = (config.get("base_url") or env_base or preset.get("base_url", "")).rstrip("/")
        self.api_key_env = config.get("api_key_env", preset.get("api_key_env"))
        self.key_optional = bool(config.get("key_optional", preset.get("key_optional", False)))
        self.timeout = float(config.get("timeout", 120))
        self.max_retries = int(config.get("max_retries", 3))
        self.max_tokens_param = config.get("max_tokens_param", preset.get("max_tokens_param", "max_tokens"))
        self.response_format = bool(config.get("response_format", preset.get("response_format", False)))
        self.extra_body = {**(preset.get("extra_body") or {}), **(config.get("extra_body") or {})}
        self.headers = dict(config.get("headers") or {})
        self.examples = list(preset.get("examples") or [])
        self._models = [model_info(name, m) for m in config.get("models", [])]

    # -------------------------------------------------------------- models
    def models(self) -> list[ModelInfo]:
        return list(self._models)

    def add_model(self, name: str, **fields: Any) -> ModelInfo:
        """Register a model named on the command line (``--llm provider:model``)."""
        for m in self._models:
            if m.name == name:
                return m
        info = model_info(self.name, {"name": name, **fields})
        self._models.append(info)
        return info

    def has_key(self) -> bool:
        return self.api_key_env is None or self.key_optional or bool(os.environ.get(self.api_key_env))

    def available(self) -> bool:
        return bool(self._models and self.base_url and self.has_key())

    # ---------------------------------------------------------------- wire
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
                if m.images:
                    parts: list[dict[str, Any]] = [{"type": "image_url", "image_url": {"url": img.data_url()}} for img in m.images]
                    if m.text:
                        parts.append({"type": "text", "text": m.text})
                    wire.append({"role": "user", "content": parts})
                elif m.text:
                    wire.append({"role": "user", "content": m.text})
        return wire

    def body(self, request: LLMRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"model": request.model, "messages": self.to_wire(request.system, request.messages),
                                self.max_tokens_param: request.max_tokens}
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                             for t in request.tools]
        if request.json and self.response_format and not request.tools:
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra_body)
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", **self.headers}
        key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        if key:
            headers["Authorization"] = f"Bearer {key}"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        attempt = 0
        while True:
            try:
                req = urllib.request.Request(f"{self.base_url}/chat/completions", data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:400].decode("utf-8", "replace")
                if exc.code in RETRY_STATUS and attempt < self.max_retries:
                    time.sleep(self._delay(attempt, exc.headers.get("Retry-After") if exc.headers else None))
                    attempt += 1
                    continue
                raise LLMError(f"{self.name} HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                if attempt < self.max_retries:
                    time.sleep(self._delay(attempt, None))
                    attempt += 1
                    continue
                raise LLMError(f"{self.name} connection error: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise LLMError(f"{self.name} returned a body that is not JSON: {exc}") from exc

    @staticmethod
    def _delay(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(60.0, float(retry_after))
            except ValueError:
                pass
        return min(30.0, 2 ** attempt) + random.uniform(0, 0.5)

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._post(self.body(request))
        if "error" in payload and not payload.get("choices"):
            err = payload["error"]
            raise LLMError(f"{self.name} error: {err.get('message', err) if isinstance(err, dict) else err}")
        base = payload.get("base_resp") or {}
        if base.get("status_code"):  # MiniMax reports some errors in a 200 body
            raise LLMError(f"{self.name} error {base.get('status_code')}: {base.get('status_msg', '')}")
        if not payload.get("choices"):
            raise LLMError(f"{self.name} returned no choices")
        choice = payload["choices"][0]
        msg = choice.get("message", {}) or {}
        uses = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"].get("arguments")}
            uses.append(ToolUse(id=tc.get("id") or f"call_{len(uses)}", name=tc["function"]["name"], input=args))
        text, reasoning = strip_think(msg.get("content") or "")
        finish = choice.get("finish_reason")
        stop = {"tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}.get(finish, "tool_use" if uses else "end_turn")
        u = payload.get("usage") or {}
        usage = Usage(input_tokens=int(u.get("prompt_tokens", 0) or 0), output_tokens=int(u.get("completion_tokens", 0) or 0))
        info = next((m for m in self._models if m.name == request.model), None)
        if info is not None:
            usage.cost_usd = info.cost(usage)
        note = "reasoning returned separately" if (reasoning or msg.get("reasoning_details") or msg.get("reasoning_content")) else ""
        return LLMResponse(text=text, tool_uses=uses, stop_reason=stop, usage=usage, model=payload.get("model", request.model), note=note)


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    for name, cfg in (config.get("providers") or {}).items():
        registry.register("llm", name, OpenAICompatibleProvider(name, cfg or {}))
