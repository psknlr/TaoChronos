"""LiteLLM provider: one adapter for the hundred-odd back ends LiteLLM speaks to.

Two ways in:

* the ``litellm`` Python package (``pip install taochronos[litellm]``): model names are LiteLLM's
  ``<provider>/<model>`` strings (``minimax/MiniMax-M2.7``, ``deepseek/deepseek-chat``,
  ``dashscope/qwen-max`` …), credentials are the variables LiteLLM reads for each back end;
* a LiteLLM proxy server (``base_url: http://localhost:4000/v1``): the OpenAI-compatible wire, model
  names as the proxy's ``model_list`` names them — used whenever ``base_url`` is configured.

Configure in a profile::

    models:
      litellm:
        models:
          - {name: minimax/MiniMax-M2.7, tier: medium, classical_chinese: 0.8}
        # base_url: http://localhost:4000/v1     # to go through a proxy instead of the package

or on the command line (``--llm litellm:deepseek/deepseek-chat``).  Unsupported OpenAI parameters are
dropped (``drop_params``) rather than failing; costs come from LiteLLM's price table when it knows
the model, else from the configured per-million prices.
"""

from __future__ import annotations

import json
from typing import Any

from ...capabilities.llm import LLMError, LLMRequest, LLMResponse, ModelInfo, ToolUse, Usage
from .openai_compat import OpenAICompatibleProvider, model_info, strip_think


class LiteLLMProvider:
    name = "litellm"
    deterministic = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.timeout = float(self.config.get("timeout", 120))
        self.max_retries = int(self.config.get("max_retries", 3))
        self._models = [model_info(self.name, m) for m in self.config.get("models", [])]
        self._proxy: OpenAICompatibleProvider | None = None
        if self.config.get("base_url"):
            self._proxy = OpenAICompatibleProvider(self.name, {**self.config, "preset": "litellm-proxy", "models": []})

    def models(self) -> list[ModelInfo]:
        return list(self._models)

    def add_model(self, name: str, **fields: Any) -> ModelInfo:
        for m in self._models:
            if m.name == name:
                return m
        info = model_info(self.name, {"name": name, **fields})
        self._models.append(info)
        return info

    @staticmethod
    def package() -> Any:
        try:
            import litellm
        except ImportError:
            return None
        return litellm

    def available(self) -> bool:
        if not self._models or self.config.get("enabled") is False:
            return False
        if self._proxy is not None:
            return self._proxy.has_key()
        return self.package() is not None

    def complete(self, request: LLMRequest) -> LLMResponse:
        info = next((m for m in self._models if m.name == request.model), None)
        if self._proxy is not None:
            self._proxy._models = self._models
            return self._proxy.complete(request)
        litellm = self.package()
        if litellm is None:
            raise LLMError("the litellm package is not installed (pip install taochronos[litellm]) and no proxy base_url is set")
        params: dict[str, Any] = {
            "model": request.model,
            "messages": OpenAICompatibleProvider.to_wire(request.system, request.messages),
            "max_tokens": request.max_tokens,
            "timeout": self.timeout,
            "num_retries": self.max_retries,
            "drop_params": True,
        }
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.tools:
            params["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                               for t in request.tools]
        elif request.json and self.config.get("response_format", True):
            params["response_format"] = {"type": "json_object"}
        for key in ("api_base", "api_key", "custom_llm_provider"):
            if self.config.get(key):
                params[key] = self.config[key]
        try:
            response = litellm.completion(**params)
        except Exception as exc:  # LiteLLM maps every back end's errors onto its own exception types
            raise LLMError(f"litellm {request.model}: {type(exc).__name__}: {exc}") from exc
        choice = response.choices[0]
        msg = choice.message
        uses = []
        for tc in getattr(msg, "tool_calls", None) or []:
            fn = tc.function
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.arguments}
            uses.append(ToolUse(id=tc.id or f"call_{len(uses)}", name=fn.name, input=args))
        text, reasoning = strip_think(getattr(msg, "content", None) or "")
        u = getattr(response, "usage", None)
        usage = Usage(input_tokens=int(getattr(u, "prompt_tokens", 0) or 0), output_tokens=int(getattr(u, "completion_tokens", 0) or 0))
        cost = (getattr(response, "_hidden_params", None) or {}).get("response_cost")
        if cost is None and info is not None:
            cost = info.cost(usage)
        usage.cost_usd = float(cost or 0.0)
        finish = getattr(choice, "finish_reason", None)
        stop = {"tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}.get(finish, "tool_use" if uses else "end_turn")
        return LLMResponse(text=text, tool_uses=uses, stop_reason=stop, usage=usage, model=getattr(response, "model", request.model),
                           note="reasoning returned separately" if reasoning else "")


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("llm", "litellm", LiteLLMProvider(config))
