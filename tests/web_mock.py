"""A scripted OpenAI-compatible provider for the web client's end-to-end tests, streaming the way MiniMax does.

MiniMax (with ``reasoning_split``) streams its thinking in ``delta.reasoning_details`` and, in its own examples, both that
and ``delta.content`` as cumulative text; tool-call arguments arrive in pieces.  The first reply of a turn asks for
``classics__search``; once the turn holds a tool result, the reply is an answer with four citations — one quoted
verbatim, one misquoted, one to a passage that does not exist and one quoted in the traditional script — and, as a model
forgetting its instructions would, the names of the tools and fields it worked with, which the page tells in plain words
(web/js/redact.js).  A message carrying the user's data (我的资料: the page's note on it) is answered by analysing its
prescriptions (``mydata__prescriptions``) and citing its first row.  A question asking for 长篇 is answered at the
output limit (``finish_reason: length``) part-way, and the rest when the page asks it to write on; one asking it to
想得很久 spends the limit on its thinking, and answers when asked again without.  Every request is recorded for the test
to inspect.
"""

from __future__ import annotations

import codecs
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = ("## 结论\n\n《伤寒论》以桂枝汤治太阳中风。\n\n"
          "- 原文：「太阳病，头痛，发热，汗出，恶风，桂枝汤主之」[[shanghanlun.c013]]\n"
          "- 节引：「太阳中风，阳浮而阴弱，桂枝汤主之」[[shanghanlun.c012]]\n"
          "- 一个不存在的出处[[fake.999]]\n"
          "- 繁体引文：「太陽病，頭痛，發熱」[[shanghanlun.c013]]\n\n"
          "| 书 | 朝代 |\n|---|---|\n| 伤寒论 | 东汉 |\n\n"
          "以上经 classics__search 检得，可用 `validation__verify_quote` 复核，出处附 passage_id。\n\n"
          "这是计算与文献检索的结果，不构成医疗建议。")
THINKING = ["用户问桂枝汤", "用户问桂枝汤的主治，先检索原文。"]
# a question asking for 图表: the model compares two formulas (a study whose result carries charts and tables), then
# draws a chart of its own in a ```chart block and writes a table with its caption and notes
CHART_ANSWER = ("两方的对照见上方图表。合两方的共有药味作图如下：\n\n```chart\n"
                '{"type":"hbar","title":"桂枝汤与麻黄汤共有之药","x":{"key":"药"},"series":[{"key":"方数","label":"方数"}],'
                '"rows":[{"药":"桂","方数":2},{"药":"甘草","方数":2}],"source":"演示语料"}'
                "\n```\n\n以上数字出自方剂比较的结果。\n\n表1　两方共有之药的剂量\n\n"
                "| 药 | 桂枝汤 | 麻黄汤 |\n|:---|:---:|:---:|\n| 桂 | 三两 | 二两 |\n| 甘草 | 二两 | 一两 |\n\n"
                "注：剂量照原书所写；n = 2。")


# a message carrying the user's data: its prescriptions analysed by diagnosis, its first row quoted
DATA_ANSWER = ("## 用药规律\n\n高频药物、药对与各组用药见上方图表。\n\n"
               "- 第一张处方：「处方：柴胡12g 黄芩9g」[[mine:{id}.r1]]\n\n统计只描述这份资料，不构成诊疗建议。")
DATA_ID = re.compile(r"资料（已在本机脱敏）：(d[0-9a-z]+)「")
# the page's note asking the model to write on an answer cut at the output limit (web/js/agent.js), and where the long
# answer is cut: in the middle of a line
WRITE_ON = "［提示：上面的回答在输出上限处被截断了"
LONG_CUT = ANSWER.index("节引") + 1
USAGE = {"prompt_tokens": 1200, "completion_tokens": 180}


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
        said = [m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"), ensure_ascii=False)
                for m in messages]
        # the question: the last user message that is not the page's note
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user" and not said[i].startswith(WRITE_ON)), default=-1)
        answered = any(m.get("role") == "tool" for m in messages[last_user + 1:])
        asked = said[last_user] if last_user >= 0 else ""
        mine = DATA_ID.search(asked)
        charting = mine.group(1) if mine else "图表" in asked
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if body.get("tools") and answered and "长篇" in asked:
            chunks = self._long(said[-1].startswith(WRITE_ON))
        elif body.get("tools") and answered and "想得很久" in asked:
            chunks = self._answer() if body.get("thinking") == {"type": "disabled"} else self._overthought()
        else:
            chunks = (self._answer(charting) if answered else self._tool_call(charting)) if body.get("tools") else self._answer()
        for chunk in chunks:
            chunk = {"id": "mock-1", "object": "chat.completion.chunk", "model": body.get("model") or "", **chunk}
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

    def _tool_call(self, charting: bool | str = False):
        yield {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}
        for t in THINKING:  # cumulative
            yield self._reasoning(t)
        name, pieces = ("mydata__prescriptions", ('{"group": ', '"诊断"}')) if isinstance(charting, str) else \
            ("study__compare", ('{"formulas": ["桂枝汤",', ' "麻黄汤"]}')) if charting else \
            ("classics__search", ('{"query": "桂枝汤', ' 主之", "k": 3}'))
        yield {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": ""}}]}}]}
        for piece in pieces:  # incremental
            yield {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}}]}
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}

    def _answer(self, charting: bool | str = False):
        yield self._reasoning("classics__search 检索到了原文，整理作答。")
        text = DATA_ANSWER.format(id=charting) if isinstance(charting, str) else CHART_ANSWER if charting else ANSWER
        for cut in (8, 40, 90, 160, len(text)):  # cumulative, as in MiniMax's own streaming example
            yield {"choices": [{"index": 0, "delta": {"content": text[:cut]}}]}
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": USAGE}

    def _long(self, writing_on: bool):
        """The answer cut at the output limit part-way; asked to write on, the rest."""
        if not writing_on:
            yield self._reasoning("长篇作答，先写结论。")
        yield {"choices": [{"index": 0, "delta": {"content": ANSWER[LONG_CUT:] if writing_on else ANSWER[:LONG_CUT]}}]}
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if writing_on else "length"}], "usage": USAGE}

    def _overthought(self):
        """All of the output limit spent on thinking: no answer."""
        yield self._reasoning("想了又想，还没想完……")
        yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}], "usage": USAGE}


class MockAnthropic(ThreadingHTTPServer):
    """The same two replies in the Anthropic Messages stream: thinking (with a signature), a tool_use, then text.  As the
    OpenAI-compatible one does, it cuts a 长篇 answer at ``max_tokens`` and spends the limit on thinking for 想得很久
    (answering when asked again at low effort); asked to 断流, its stream ends part-way the first time, and the second
    stops without saying why (``message_stop`` with no ``message_delta``)."""

    daemon_threads = True

    def __init__(self, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _AnthropicHandler)
        self.requests: list[dict] = []
        self.broken = 0  # the 断流 answers sent so far

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
        messages = body["messages"]
        last = messages[-1]
        answered = isinstance(last.get("content"), list) and any(b.get("type") == "tool_result" for b in last["content"])
        writing_on = isinstance(last.get("content"), str) and last["content"].startswith(WRITE_ON)
        # the question: the last user message in words, not the page's note
        asked = next((m["content"] for m in reversed(messages) if m["role"] == "user" and isinstance(m["content"], str)
                      and not m["content"].startswith(WRITE_ON)), "")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if (answered or writing_on) and "长篇" in asked:
            events = self._long(writing_on)
        elif answered and "想得很久" in asked:
            events = self._text() if (body.get("output_config") or {}).get("effort") == "low" else self._overthought()
        elif answered and "断流" in asked and self.server.broken < 2:
            self.server.broken += 1
            events = self._text(broken="early" if self.server.broken == 1 else "unsaid")
        else:
            events = self._text() if answered else self._tool()
        for event in events:
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

    def _text(self, broken: str = ""):
        """The answer; ``broken``: "early", the stream ends part-way; "unsaid", it stops without a stop reason."""
        yield self._start()
        yield {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
        for piece in (ANSWER[:30],) if broken else (ANSWER[:30], ANSWER[30:]):
            yield {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}}
        if broken == "early":
            return
        yield {"type": "content_block_stop", "index": 0}
        if not broken:
            yield {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 120}}
        yield {"type": "message_stop"}

    def _long(self, writing_on: bool):
        """The answer cut at max_tokens part-way; asked to write on, the rest."""
        yield self._start()
        yield {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
        piece = ANSWER[LONG_CUT:] if writing_on else ANSWER[:LONG_CUT]
        yield {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}}
        yield {"type": "content_block_stop", "index": 0}
        yield {"type": "message_delta", "delta": {"stop_reason": "end_turn" if writing_on else "max_tokens", "stop_sequence": None},
               "usage": {"output_tokens": 120}}
        yield {"type": "message_stop"}

    def _overthought(self):
        """All of max_tokens spent on thinking: no answer."""
        yield self._start()
        yield {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}
        yield {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "想了又想，还没想完……"}}
        yield {"type": "content_block_stop", "index": 0}
        yield {"type": "message_delta", "delta": {"stop_reason": "max_tokens", "stop_sequence": None}, "usage": {"output_tokens": 64000}}
        yield {"type": "message_stop"}


PUBLIC_MODEL = "Tao-R1"          # the default service's model, as the page knows it (relay/src/relay.js: PUBLIC_MODEL)
UPSTREAM_MODEL = "MiniMax-M3"    # the model behind it (relay.js: MODELS)
_MODEL_FIELD = re.compile(r'"model"\s*:\s*"(?:[^"\\]|\\.)*"')
_FORMAT_FIELD = re.compile(r'"format"\s*:\s*"MiniMax-')


def _upstream_request(raw: bytes) -> bytes:
    """The page's request in the upstream's own terms, as the relay sends it: its model, its parameters, its formats."""
    body = json.loads(raw or b"{}")
    if body.get("model") in (None, "", PUBLIC_MODEL):
        body["model"] = UPSTREAM_MODEL
    body.setdefault("reasoning_split", True)
    for m in body.get("messages") or []:
        for d in (m.get("reasoning_details") or []) if isinstance(m, dict) else []:
            if isinstance(d, dict) and str(d.get("format", "")).startswith("Tao-"):
                d["format"] = "MiniMax-" + d["format"][len("Tao-"):]
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _public_event(text: str) -> str:
    """One event of the reply as a visitor sees it (relay.js: publicText): the public model name and formats."""
    return _FORMAT_FIELD.sub('"format":"Tao-', _MODEL_FIELD.sub(f'"model":"{PUBLIC_MODEL}"', text))


class MockRelay(ThreadingHTTPServer):
    """道乃久默认服务 as the page sees it (relay/src/relay.js): health, the model calls forwarded to ``upstream`` with the
    relay's own key (in the upstream's terms, the reply in the service's own), and the conversation records.  Records
    what the browser sent — the page never sends a key."""

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
            self._json(200, {"ok": True, "service": "taochronos-relay", "model": PUBLIC_MODEL, "models": [PUBLIC_MODEL],
                             "logs": self.server.logs, "max_output_tokens": 32768, "limits": {"per_minute": 30, "per_day": 600}})
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

        req = urllib.request.Request(f"{self.server.upstream}/chat/completions", data=_upstream_request(raw), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {MockRelay.SECRET}"})
        with urllib.request.urlopen(req, timeout=30) as up:  # noqa: S310 — the test's own mock
            self.send_response(up.status)
            self._cors()
            self.send_header("Content-Type", up.headers.get("Content-Type", "text/event-stream"))
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            decoder, buffer = codecs.getincrementaldecoder("utf-8")(), ""

            def send(text: str) -> None:
                data = text.encode("utf-8")
                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            while True:
                data = up.read1(65536) if hasattr(up, "read1") else up.read(65536)
                buffer += decoder.decode(data, final=not data)
                while "\n\n" in buffer:  # an event is read whole
                    event, buffer = buffer.split("\n\n", 1)
                    send(_public_event(event) + "\n\n")
                if not data:
                    break
            if buffer:
                send(_public_event(buffer))
            self.wfile.write(b"0\r\n\r\n")
