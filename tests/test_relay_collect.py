"""The repository's side of 道乃久默认服务 (relay/collect.py) against a stand-in relay: records pulled after the committed
cursor into one file per day, never twice; the relay deletes only what the repository holds; a deployment checked."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collect", ROOT / "relay" / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

TOKEN = "collector-token-0123456789"


class FakeRelay(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.rows: list[dict] = []   # {id, received, record}
        self.next_id = 1
        self.chat_status = 200
        self.chat_error = {}
        self.archived: list[dict] | None = None  # the archive's bucket, when the relay has one: its items

    def add(self, received: str, question: str) -> None:
        self.rows.append({"id": self.next_id, "received": received, "record": {"v": 1, "question": question}})
        self.next_id += 1

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeRelay

    def log_message(self, *a) -> None:
        pass

    def _json(self, status: int, data) -> None:
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/v1/health":
            return self._json(200, {"ok": True, "model": "Tao-R1", "logs": True, "limits": {"per_day": 600}})
        if url.path in ("/v1/logs/export", "/v1/logs/archive"):
            if not self._authorized():
                return self._json(401, {"error": {"message": "需要收集令牌"}})
        q = parse_qs(url.query)
        if url.path == "/v1/logs/archive":
            if self.server.archived is None:
                return self._json(404, {"error": {"message": "没有归档"}})
            day = [i for i in self.server.archived if i["received"].startswith(q["day"][0])]
            start = int(q.get("cursor", ["0"])[0])
            page = day[start:start + 2]  # two a page, to page
            more = start + 2 < len(day)
            return self._json(200, {"day": q["day"][0], "items": page, "cursor": str(start + 2) if more else None, "more": more})
        after, limit = int(q.get("after", ["0"])[0]), int(q.get("limit", ["500"])[0])
        rows = [r for r in self.server.rows if r["id"] > after]
        items = rows[:limit]
        page = {"items": items, "last": items[-1]["id"] if items else after, "more": len(rows) > limit}
        return self._json(200, {**page, "archive": "r2"} if self.server.archived is not None else page)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/v1/logs/ack":
            if not self._authorized():
                return self._json(401, {"error": {"message": "需要收集令牌"}})
            if self.server.archived is not None:
                return self._json(409, {"error": {"message": "记录由归档取走", "type": "archived"}})
            self.server.rows = [r for r in self.server.rows if r["id"] > body["through"]]
            return self._json(200, {"remaining": len(self.server.rows)})
        if self.path == "/v1/chat/completions":
            assert self.headers.get("Origin") == "https://chat.impf.ai"
            if self.server.chat_status != 200:
                return self._json(self.server.chat_status, {"error": self.server.chat_error})
            return self._json(200, {"choices": [{"message": {"content": "可以"}}]})
        return self._json(404, {})


@pytest.fixture()
def relay(monkeypatch):
    server = FakeRelay()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LOG_EXPORT_TOKEN", TOKEN)
    yield server
    server.shutdown()


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_records_are_pulled_once_by_day_and_deleted_only_once_held(relay, tmp_path):
    out = tmp_path / "data" / "chat-logs"
    relay.add("2026-09-27T23:59:58Z", "桂枝汤主治什么？")
    relay.add("2026-09-28T00:00:02Z", "消渴是什么？")
    relay.add("2026-09-28T08:15:00Z", "它的剂量出自哪里？")
    got = collect.pull(relay.url, out, limit=2)  # two pages
    assert got == {"new": 3, "last": 3}
    assert [r["question"] for r in _lines(out / "2026" / "09" / "27.jsonl")] == ["桂枝汤主治什么？"]
    day = _lines(out / "2026" / "09" / "28.jsonl")
    assert [r["n"] for r in day] == [2, 3] and day[0]["received"] == "2026-09-28T00:00:02Z"
    assert json.loads((out / "cursor.json").read_text())["last"] == 3
    assert collect.pull(relay.url, out) == {"new": 0, "last": 3}  # nothing twice
    relay.add("2026-09-28T09:00:00Z", "再问一次。")
    assert collect.pull(relay.url, out) == {"new": 1, "last": 4}
    assert [r["n"] for r in _lines(out / "2026" / "09" / "28.jsonl")] == [2, 3, 4]
    assert json.loads((out / "cursor.json").read_text())["total"] == 4
    assert collect.ack(relay.url, 3) == {"acked": 3, "remaining": 1}  # only what the repository holds
    assert [r["id"] for r in relay.rows] == [4]


def test_the_collector_needs_its_token(relay, tmp_path, monkeypatch):
    relay.add("2026-09-28T00:00:00Z", "问")
    monkeypatch.setenv("LOG_EXPORT_TOKEN", "a-wrong-token-0123456789")
    with pytest.raises(SystemExit, match="401"):
        collect.pull(relay.url, tmp_path / "logs")
    assert not (tmp_path / "logs").exists()
    monkeypatch.setenv("LOG_EXPORT_TOKEN", f" {TOKEN}\n")  # pasted with a space and a line break
    assert collect.pull(relay.url, tmp_path / "logs")["new"] == 1
    monkeypatch.setenv("LOG_EXPORT_TOKEN", "short")
    with pytest.raises(SystemExit, match="LOG_EXPORT_TOKEN"):
        collect.ack(relay.url, 1)


def test_a_deployment_is_checked_and_a_refused_key_explained(relay):
    assert collect.check(relay.url, "https://chat.impf.ai", wait=5)["call"] == "ok"
    relay.chat_status, relay.chat_error = 503, {"message": "默认服务暂时不可用", "type": "upstream_auth"}
    with pytest.raises(SystemExit, match="api.minimax.io"):
        collect.check(relay.url, "https://chat.impf.ai", wait=5)


def test_a_relay_that_archives_its_records_gives_the_repository_none_and_reads_a_day_back(relay, tmp_path):
    out = tmp_path / "data" / "chat-logs"
    relay.add("2026-10-14T01:00:00Z", "桂枝汤主治什么？")
    relay.archived = [{"n": k, "received": f"2026-10-14T0{k}:00:00Z", "question": f"问{k}"} for k in range(1, 4)]
    assert collect.pull(relay.url, out) == {"new": 0, "last": 0}  # the archive collects: nothing into the repository
    assert not (out / "2026").exists()
    assert collect.ack(relay.url, 1) == {"acked": 0, "remaining": None}  # refused (409), told, not an error
    assert [r["id"] for r in relay.rows] == [1]  # still there, for the archive to drain
    got = collect.archive(relay.url, "2026-10-14", tmp_path / ".archive")
    assert got["records"] == 3
    assert [r["question"] for r in _lines(tmp_path / ".archive" / "2026" / "10" / "14.jsonl")] == ["问1", "问2", "问3"]
    relay.archived = None
    with pytest.raises(SystemExit, match="no archive"):
        collect.archive(relay.url, "2026-10-14", tmp_path / ".archive")
