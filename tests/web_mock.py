"""A scripted OpenAI-compatible provider for the web client's end-to-end tests, streaming the way MiniMax does.

MiniMax (with ``reasoning_split``) streams its thinking in ``delta.reasoning_details`` and, in its own examples, both that
and ``delta.content`` as cumulative text; tool-call arguments arrive in pieces.  The first reply of a turn asks for
``classics__search``; once the turn holds a tool result, the reply is an answer with four citations — one quoted
verbatim, one misquoted, one to a passage that does not exist and one quoted in the traditional script.  Every request is recorded for the test to inspect.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = ("## 结论\n\n《伤寒论》以桂枝汤治太阳中风。\n\n"
          "- 原文：「太阳病，头痛，发热，汗出，恶风，桂枝汤主之」[[shanghanlun.c013]]\n"
          "- 节引：「太阳中风，阳浮而阴弱，桂枝汤主之」[[shanghanlun.c012]]\n"
          "- 一个不存在的出处[[fake.999]]\n"
          "- 繁体引文：「太陽病，頭痛，發熱」[[shanghanlun.c013]]\n\n"
          "| 书 | 朝代 |\n|---|---|\n| 伤寒论 | 东汉 |\n\n这是计算与文献检索的结果，不构成医疗建议。")
THINKING = ["用户问桂枝汤", "用户问桂枝汤的主治，先检索原文。"]


class MockProvider(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.requests: list[dict] = []

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    def start(self) -> "MockProvider":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


class _Handler(BaseHTTPRequestHandler):
    server: MockProvider
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # quiet
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        messages = body.get("messages", [])
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        answered = any(m.get("role") == "tool" for m in messages[last_user + 1:])
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for chunk in (self._answer() if answered else self._tool_call()) if body.get("tools") else self._answer():
            self._write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n")
        self._write("data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")

    def _write(self, text: str) -> None:
        data = text.encode("utf-8")
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    @staticmethod
    def _reasoning(text: str) -> dict:
        return {"choices": [{"index": 0, "delta": {"reasoning_details": [
            {"type": "reasoning.text", "id": "rd-1", "format": "MiniMax-response-v1", "index": 0, "text": text}]}}]}

    def _tool_call(self):
        yield {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}
        for t in THINKING:  # cumulative
            yield self._reasoning(t)
        yield {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "classics__search", "arguments": ""}}]}}]}
        for piece in ('{"query": "桂枝汤', ' 主之", "k": 3}'):  # incremental
            yield {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}}]}
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}

    def _answer(self):
        yield self._reasoning("检索到了原文，整理作答。")
        for cut in (8, 40, 90, len(ANSWER)):  # cumulative, as in MiniMax's own streaming example
            yield {"choices": [{"index": 0, "delta": {"content": ANSWER[:cut]}}]}
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 1200, "completion_tokens": 180}}


class MockAnthropic(ThreadingHTTPServer):
    """The same two replies in the Anthropic Messages stream: thinking (with a signature), a tool_use, then text."""

    daemon_threads = True

    def __init__(self, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _AnthropicHandler)
        self.requests: list[dict] = []

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    def start(self) -> "MockAnthropic":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


class _AnthropicHandler(_Handler):
    server: MockAnthropic

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        last = body["messages"][-1]
        answered = isinstance(last.get("content"), list) and any(b.get("type") == "tool_result" for b in last["content"])
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for event in (self._text() if answered else self._tool()):
            self._write(f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
        self.wfile.write(b"0\r\n\r\n")

    @staticmethod
    def _start(stop=None):
        return {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
                                                      "content": [], "stop_reason": stop, "stop_sequence": None,
                                                      "usage": {"input_tokens": 900, "output_tokens": 1}}}

    def _tool(self):
        yield self._start()
        yield {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}
        yield {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "先检索原文。"}}
        yield {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig-abc"}}
        yield {"type": "content_block_stop", "index": 0}
        yield {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "classics__search", "input": {}}}
        yield {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"query": "桂枝汤'}}
        yield {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ' 主之", "k": 3}'}}
        yield {"type": "content_block_stop", "index": 1}
        yield {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 40}}
        yield {"type": "message_stop"}

    def _text(self):
        yield self._start()
        yield {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
        for piece in (ANSWER[:30], ANSWER[30:]):
            yield {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}}
        yield {"type": "content_block_stop", "index": 0}
        yield {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 120}}
        yield {"type": "message_stop"}


class MockRelay(ThreadingHTTPServer):
    """道乃久默认服务 as the page sees it (relay/src/relay.js): health, the model calls forwarded to ``upstream`` with the
    relay's own key, and the conversation records.  Records what the browser sent — the page never sends a key."""

    daemon_threads = True
    SECRET = "relay-held-secret"

    def __init__(self, upstream: str, port: int = 0, logs: bool = True) -> None:
        super().__init__(("127.0.0.1", port), _RelayHandler)
        self.upstream = upstream.rstrip("/")
        self.logs = logs
        self.chat: list[dict] = []     # the browser's requests to the relay
        self.records: list[dict] = []  # the records the page sent
        self.record_types: list[str] = []
        self.health_delay = 0.0        # seconds before /v1/health answers: a slow link

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> "MockRelay":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


class _RelayHandler(BaseHTTPRequestHandler):
    server: MockRelay
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def _json(self, status: int, data) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/v1/health":
            time.sleep(self.server.health_delay)
            self._json(200, {"ok": True, "service": "taochronos-relay", "model": "MiniMax-M3", "models": ["MiniMax-M3"],
                             "logs": self.server.logs, "max_output_tokens": 8192, "limits": {"per_minute": 30, "per_day": 600}})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/v1/logs":
            self.server.records.append(json.loads(raw or b"{}"))
            self.server.record_types.append(self.headers.get("Content-Type", ""))
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        self.server.chat.append({"headers": dict(self.headers), "body": json.loads(raw or b"{}")})
        import urllib.request

        req = urllib.request.Request(f"{self.server.upstream}/chat/completions", data=raw, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {MockRelay.SECRET}"})
        with urllib.request.urlopen(req, timeout=30) as up:  # noqa: S310 — the test's own mock
            self.send_response(up.status)
            self._cors()
            self.send_header("Content-Type", up.headers.get("Content-Type", "text/event-stream"))
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                data = up.read1(65536) if hasattr(up, "read1") else up.read(65536)
                if not data:
                    break
                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
