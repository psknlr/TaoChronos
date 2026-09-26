"""Model providers are tested offline: fake clients stand in for the network."""

import io
import json

import pytest

from taochronos.capabilities.llm import LLMRequest, Message, ToolResultBlock, ToolSchema, ToolUse
from taochronos.plugins.models.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from taochronos.plugins.models.openai_compat import OpenAICompatibleProvider


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Response:
    def __init__(self, content, stop_reason="end_turn", model="claude-opus-5"):
        self.content = [_Block(**c) for c in content]
        self.stop_reason = stop_reason
        self.stop_details = _Block(category="cyber") if stop_reason == "refusal" else None
        self.usage = _Block(input_tokens=1000, output_tokens=200)
        self.model = model
        self._raw = content

    def to_dict(self):
        return {"content": self._raw}


class _Messages:
    def __init__(self, response, log):
        self.response, self.log = response, log

    def create(self, **kw):
        self.log.append(kw)
        return self.response


class _Client:
    def __init__(self, response):
        self.calls = []
        self.messages = _Messages(response, self.calls)
        self.beta = _Block(messages=_Messages(response, self.calls))


def _request(model="claude-opus-5"):
    return LLMRequest(model=model, system="You are TaoChronos.", effort="high",
                      messages=[Message("user", "question"),
                                Message("assistant", "", tool_uses=[ToolUse("tu1", "classics__search", {"query": "消渴"})],
                                        raw=[{"type": "thinking", "thinking": "…", "signature": "s"},
                                             {"type": "tool_use", "id": "tu1", "name": "classics__search", "input": {"query": "消渴"}}]),
                                Message("user", tool_results=[ToolResultBlock("tu1", "{}")])],
                      tools=[ToolSchema("classics__search", "search", {"type": "object", "properties": {}})])


def test_anthropic_request_shape_with_fallbacks_and_adaptive_thinking(monkeypatch):
    pytest.importorskip("anthropic")
    provider = AnthropicProvider({"enabled": True})
    client = _Client(_Response([{"type": "text", "text": '{"ok": true}'}]))
    monkeypatch.setattr(provider, "_client_", lambda: client)
    response = provider.complete(_request())
    call = client.calls[0]
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["thinking"] == {"type": "adaptive"} and call["output_config"] == {"effort": "high"}
    assert call["messages"][1]["content"][0]["type"] == "thinking"  # assistant turn replayed verbatim
    assert call["messages"][2]["content"][0]["type"] == "tool_result"
    assert response.text == '{"ok": true}' and response.usage.cost_usd > 0


def test_anthropic_small_model_takes_no_effort_and_refusal_is_reported(monkeypatch):
    pytest.importorskip("anthropic")
    provider = AnthropicProvider({"enabled": True})
    client = _Client(_Response([], stop_reason="refusal", model="claude-haiku-4-5"))
    monkeypatch.setattr(provider, "_client_", lambda: client)
    response = provider.complete(_request("claude-haiku-4-5"))
    call = client.calls[0]
    assert "betas" not in call and "thinking" not in call and "output_config" not in call
    assert response.stop_reason == "refusal" and "cyber" in response.note


def test_openai_compatible_provider_wire_format(monkeypatch):
    provider = OpenAICompatibleProvider("local", {"base_url": "http://localhost:8000/v1", "api_key_env": None,
                                                  "models": [{"name": "local-model", "tier": "medium"}]})
    assert provider.available()
    seen = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["body"] = json.loads(req.data)
        payload = {"model": "local-model", "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "kg__claims", "arguments": '{"terms": ["消渴"]}'}}]}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        return _Resp(json.dumps(payload).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    response = provider.complete(_request("local-model"))
    assert seen["body"]["messages"][0] == {"role": "system", "content": "You are TaoChronos."}
    assert any(m["role"] == "tool" for m in seen["body"]["messages"])
    assert response.stop_reason == "tool_use" and response.tool_uses[0].input == {"terms": ["消渴"]}


def test_providers_without_credentials_are_unavailable(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert not AnthropicProvider({}).available()
    assert not OpenAICompatibleProvider("deepseek", {"models": [{"name": "m"}]}).available()  # no key
    assert not OpenAICompatibleProvider("openai", {}).available()  # no configured models → never routed
