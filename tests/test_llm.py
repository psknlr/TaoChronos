"""Model providers on the wire (a local OpenAI-compatible server) and the rule-then-model judge."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from taochronos.capabilities.judge import Judge, JudgeBudget, adjudicate, extract_json, synthesize
from taochronos.capabilities.llm import ImageBlock, LLMError, LLMRequest, Message
from taochronos.plugins.models.openai_compat import OpenAICompatibleProvider, strip_think
from taochronos.plugins.models.scripted import ScriptedProvider


class _Server:
    """A chat-completions endpoint that answers from a queue and records every request body."""

    def __init__(self) -> None:
        self.replies: list[tuple[int, dict, dict]] = []  # (status, body, headers)
        self.requests: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                server.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                        "body": json.loads(self.rfile.read(length))})
                status, body, headers = server.replies.pop(0) if server.replies else (500, {"error": "empty"}, {})
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def reply(self, content: str = "", *, status: int = 200, headers: dict | None = None, usage: dict | None = None,
              body: dict | None = None) -> None:
        payload = body or {"model": "m", "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                           "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}
        self.replies.append((status, payload, headers or {}))

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


def _provider(server: _Server, preset: str, monkeypatch, **cfg) -> OpenAICompatibleProvider:
    env = {"minimax": "MINIMAX_API_KEY", "poe": "POE_API_KEY"}.get(preset)
    if env:
        monkeypatch.setenv(env, "test-key")
    return OpenAICompatibleProvider(preset, {"preset": preset, "base_url": server.url, "max_retries": 2,
                                             "models": [{"name": "m", "input_cost_per_mtok": 1.0, "output_cost_per_mtok": 2.0}], **cfg})


def test_minimax_preset_sends_its_parameters_and_strips_reasoning(server, monkeypatch):
    p = _provider(server, "minimax", monkeypatch)
    server.reply("<think>先想一想</think>\n{\"pulse\": \"浮\"}")
    res = p.complete(LLMRequest(model="m", system="s", messages=[Message("user", "q")], max_tokens=300, json=True, temperature=0))
    body = server.requests[0]["body"]
    assert server.requests[0]["path"] == "/v1/chat/completions" and server.requests[0]["auth"] == "Bearer test-key"
    assert body["max_completion_tokens"] == 300 and "max_tokens" not in body
    assert body["reasoning_split"] is True and body["temperature"] == 0
    assert "response_format" not in body  # not claimed for MiniMax
    assert res.text == '{"pulse": "浮"}' and res.note
    assert res.usage.cost_usd == pytest.approx((10 * 1.0 + 5 * 2.0) / 1e6)


def test_poe_never_sends_response_format_and_images_go_as_data_urls(server, monkeypatch):
    p = _provider(server, "poe", monkeypatch)
    server.reply('{"text": "太阳"}')
    p.complete(LLMRequest(model="m", system="s", json=True,
                          messages=[Message("user", "读这一页", images=[ImageBlock(b"\x89PNG", "image/png")])]))
    body = server.requests[0]["body"]
    assert "response_format" not in body and body["max_tokens"] == 16000
    parts = body["messages"][1]["content"]
    assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": "读这一页"}


def test_retries_honour_retry_after_then_raise_on_client_errors(server, monkeypatch):
    p = _provider(server, "poe", monkeypatch)
    server.reply(status=429, headers={"Retry-After": "0"}, body={"error": {"message": "slow down"}})
    server.reply("ok")
    assert p.complete(LLMRequest(model="m", system="s", messages=[Message("user", "q")])).text == "ok"
    assert len(server.requests) == 2
    server.reply(status=401, body={"error": {"message": "Invalid API key"}})
    with pytest.raises(LLMError, match="HTTP 401"):
        p.complete(LLMRequest(model="m", system="s", messages=[Message("user", "q")]))


def test_minimax_error_in_a_200_body_is_an_error(server, monkeypatch):
    p = _provider(server, "minimax", monkeypatch)
    server.reply(body={"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}})
    with pytest.raises(LLMError, match="1008"):
        p.complete(LLMRequest(model="m", system="s", messages=[Message("user", "q")]))


def test_provider_availability_needs_a_key_and_a_model(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    p = OpenAICompatibleProvider("minimax", {"preset": "minimax"})
    assert not p.available()
    p.add_model("MiniMax-M2.7")
    assert not p.available()
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    assert p.available() and p.base_url == "https://api.minimax.cn/v1"


def test_strip_think_and_extract_json():
    assert strip_think("<think>a\nb</think>答") == ("答", "a\nb")
    assert extract_json('说明……```json\n{"a": [1, 2]}\n```') == ({"a": [1, 2]}, None)
    assert extract_json("<think>{x}</think> [1, 2]") == ([1, 2], None)
    assert extract_json("没有")[1] == "no JSON object found"


# ------------------------------------------------------------------ the judge
SCHEMA = {"type": "object", "required": ["label"], "properties": {"label": {"enum": ["驳", "从"]}}}


def test_judge_validates_repairs_caches_and_counts(tmp_path):
    scripted = ScriptedProvider([{"text": '{"label": "否"}'}, {"text": '{"label": "驳"}'}])
    judge = Judge(scripted, "scripted-model", cache_dir=tmp_path / "cache", log_path=tmp_path / "log.jsonl")
    res = judge.ask("disputes.stance", "sys", "prompt", schema=SCHEMA)
    assert res.ok and res.data == {"label": "驳"} and res.attempts == 2  # one repair turn
    assert "does not pass the checks" in scripted.requests[1].messages[-1].text
    again = judge.ask("disputes.stance", "sys", "prompt", schema=SCHEMA)
    assert again.ok and again.cached and len(scripted.requests) == 2  # served from the cache
    assert judge.stats["disputes.stance"]["cached"] == 1
    log = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert log[0]["ok"] and log[0]["attempts"] == 2 and "prompt" not in log[0]


def test_judge_gives_up_after_one_repair_and_respects_its_budget():
    scripted = ScriptedProvider([{"text": "不是 JSON"}, {"text": "还不是"}])
    judge = Judge(scripted, "m")
    res = judge.ask("t", "s", "p", schema=SCHEMA)
    assert not res.ok and res.attempts == 2
    capped = Judge(ScriptedProvider([{"text": '{"label": "从"}'}]), "m", budget=JudgeBudget(max_calls=0))
    res = capped.ask("t", "s", "p", schema=SCHEMA)
    assert not res.ok and res.error.startswith("budget")


def test_adjudicate_keeps_rules_when_the_model_is_absent_invalid_or_off_list():
    items = [{"id": "a", "rule": "驳", "text": "…非也"}, {"id": "b", "rule": "从", "text": "…当从"},
             {"id": "c", "rule": "驳", "text": "…"}, {"id": "d", "rule": "从", "text": "…"}]
    decisions, summary = adjudicate(None, items, task="t", system="s", render=lambda g: "", allowed=["驳", "从"])
    assert all(d.final == d.rule and d.decided_by == "rule" for d in decisions) and summary["note"].startswith("no model")
    reply = {"decisions": [{"id": "a", "label": "驳"}, {"id": "b", "label": "驳", "reason": "反语"}, {"id": "c", "label": "从"}]}
    judge = Judge(ScriptedProvider([{"text": json.dumps(reply, ensure_ascii=False)}]), "m")
    decisions, summary = adjudicate(judge, items, task="t", system="s", render=lambda g: json.dumps(g, ensure_ascii=False),
                                    allowed=["驳", "从"], select=lambda it: it["id"] != "d",
                                    item_check=lambda it, d: ["引文不在原句"] if it["id"] == "c" else [])
    by = {d.id: d for d in decisions}
    assert by["a"].decided_by == "both" and by["b"].final == "驳" and by["b"].decided_by == "model" and by["b"].reason == "反语"
    assert by["c"].final == "驳" and by["c"].note == "引文不在原句"  # the check rejected the model's answer
    assert not by["d"].asked and by["d"].final == "从"
    assert summary["asked"] == 3 and summary["answered"] == 2 and summary["changed"] == 1 and summary["agreement"] == 0.5


def test_synthesis_drops_uncited_sentences_and_misquotes():
    evidence = [{"id": "E1", "text": "太阳之为病，脉浮，头项强痛而恶寒。"}, {"id": "E2", "text": "伤寒一日，太阳受之。"}]
    reply = {"sentences": [{"text": "太阳病以「脉浮」为纲。", "cites": ["E1"]},
                           {"text": "太阳病必发热。", "cites": []},
                           {"text": "「头痛发热」是太阳病。", "cites": ["E1"]},
                           {"text": "伤寒首日在太阳。", "cites": ["E2", "E9"]}]}
    judge = Judge(ScriptedProvider([{"text": json.dumps(reply, ensure_ascii=False)}]), "m")
    out = synthesize(judge, task="t", system="s", question="太阳病的提纲是什么？", evidence=evidence)
    assert out.ok and [s["text"] for s in out.sentences] == ["太阳病以「脉浮」为纲。", "伤寒首日在太阳。"]
    assert out.sentences[1]["cites"] == ["E2"]
    assert {d["why"].split(":")[0].split(" (")[0] for d in out.dropped} == {"cites no known evidence", "quotes not found in the cited evidence"}
    assert out.text.endswith("[E2]")


def test_litellm_provider_maps_its_parameters(monkeypatch):
    import sys
    import types

    from taochronos.plugins.models.litellm_provider import LiteLLMProvider

    calls = []

    def completion(**params):
        calls.append(params)
        msg = types.SimpleNamespace(content="<think>…</think>{\"ok\": true}", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")],
                                     usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=3),
                                     model="minimax/MiniMax-M2.7", _hidden_params={"response_cost": 0.0001})

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=completion))
    p = LiteLLMProvider({"models": [{"name": "minimax/MiniMax-M2.7"}]})
    assert p.available()
    res = p.complete(LLMRequest(model="minimax/MiniMax-M2.7", system="s", messages=[Message("user", "q")], json=True, temperature=0))
    assert res.text == '{"ok": true}' and res.usage.cost_usd == 0.0001 and res.usage.input_tokens == 7
    assert calls[0]["drop_params"] is True and calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["messages"][0] == {"role": "system", "content": "s"}


def test_harness_makes_a_judge_from_a_preset_on_the_fly(server, monkeypatch, tmp_path):
    from taochronos.bootstrap import Harness

    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    monkeypatch.setenv("MINIMAX_BASE_URL", server.url)
    harness = Harness.from_profile("full-discovery", data_dir=tmp_path, ephemeral=True)
    judge = harness.judge("minimax:MiniMax-M2.7", max_calls=5)
    assert judge.label == "minimax:MiniMax-M2.7" and judge.budget.max_calls == 5
    server.reply('{"pulse": "浮"}')
    res = judge.ask("llm.test", "s", "q", schema={"type": "object", "required": ["pulse"]})
    assert res.ok and res.data == {"pulse": "浮"} and server.requests[0]["body"]["model"] == "MiniMax-M2.7"
    assert (tmp_path / "llm-cache").exists() and list((tmp_path / "llm-log").glob("*.jsonl"))
    with pytest.raises(ValueError, match="name a model"):
        harness.judge("poe")
    assert harness.judge(None) is None and harness.judge("rules") is None
