"""The repository's side of the sentinels (security/collect.py) against two stand-in Workers: events pulled after the
committed cursor into one file per source and day, deleted only once held; a Worker that archives its events in its own
bucket (docs/adr/0023-workers-paid.md) gives the repository none, refuses the acknowledgement, and reads a day back."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("security_collect", ROOT / "security" / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

TOKEN = "collector-token-0123456789"


class FakeWorker(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, prefix: str) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.prefix = prefix
        self.rows: list[dict] = []
        self.next_id = 1
        self.archived: list[dict] | None = None

    def add(self, received: str, kind: str) -> None:
        self.rows.append({"id": self.next_id, "received": received, "event": {"v": 1, "kind": kind}})
        self.next_id += 1

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeWorker

    def log_message(self, *a) -> None:
        pass

    def _json(self, status: int, data) -> None:
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._json(401, {})
        q = parse_qs(url.query)
        if url.path == f"{self.server.prefix}/export":
            after = int(q.get("after", ["0"])[0])
            items = [r for r in self.server.rows if r["id"] > after]
            page = {"items": items, "last": items[-1]["id"] if items else after, "more": False}
            return self._json(200, {**page, "archive": "r2"} if self.server.archived is not None else page)
        if url.path == f"{self.server.prefix}/archive":
            if self.server.archived is None:
                return self._json(404, {})
            return self._json(200, {"items": [e for e in self.server.archived if e["received"].startswith(q["day"][0])], "cursor": None, "more": False})
        return self._json(404, {})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == f"{self.server.prefix}/ack":
            if self.server.archived is not None:
                return self._json(409, {"error": {"type": "archived"}})
            self.server.rows = [r for r in self.server.rows if r["id"] > body["through"]]
            return self._json(200, {"remaining": len(self.server.rows)})
        return self._json(404, {})


@pytest.fixture()
def workers(monkeypatch):
    relay, site = FakeWorker("/v1/security"), FakeWorker("/api/security")
    for w in (relay, site):
        threading.Thread(target=w.serve_forever, daemon=True).start()
    monkeypatch.setenv("LOG_EXPORT_TOKEN", TOKEN)
    yield relay, site
    for w in (relay, site):
        w.shutdown()


def test_events_are_pulled_by_source_and_day_and_deleted_only_once_held(workers, tmp_path):
    relay, site = workers
    relay.add("2026-10-14T01:00:00Z", "honeypot")
    site.add("2026-10-14T02:00:00Z", "flag")
    site.add("2026-10-15T02:00:00Z", "block")
    got = collect.pull({"relay": relay.url, "site": site.url}, tmp_path)
    assert got == {"new": 3, "relay_last": 1, "relay_new": 1, "site_last": 2, "site_new": 2}
    assert [json.loads(x)["kind"] for x in (tmp_path / "site" / "2026" / "10" / "14.jsonl").read_text().splitlines()] == ["flag"]
    assert collect.ack({"relay": relay.url, "site": site.url}, tmp_path) == {"relay_acked": 1, "relay_remaining": 0, "site_acked": 2, "site_remaining": 0}


def test_a_worker_that_archives_gives_the_repository_none_while_the_other_still_does(workers, tmp_path):
    relay, site = workers
    relay.add("2026-10-14T01:00:00Z", "honeypot")
    site.add("2026-10-14T02:00:00Z", "flag")
    site.archived = [{"n": 1, "received": "2026-10-14T02:00:00Z", "source": "site", "kind": "flag"}]
    got = collect.pull({"relay": relay.url, "site": site.url}, tmp_path)
    assert (got["relay_new"], got["site_new"]) == (1, 0)
    assert not (tmp_path / "site").exists()
    assert collect.ack({"relay": relay.url, "site": site.url}, tmp_path)["site_acked"] == 0  # nothing pulled from it: not asked
    # an archive bound between the pull and the acknowledgement: the 409 is told, not an error
    relay.add("2026-10-14T03:00:00Z", "flag")
    collect.pull({"relay": relay.url}, tmp_path)
    relay.archived = []
    assert collect.ack({"relay": relay.url}, tmp_path) == {"relay_acked": 0}
    assert [r["id"] for r in relay.rows] == [2]  # left for the archive
    out = collect.archive({"relay": relay.url, "site": site.url}, "2026-10-14", tmp_path / ".archive")
    assert out == {"day": "2026-10-14", "relay": 0, "site": 1}
    assert json.loads((tmp_path / ".archive" / "site" / "2026" / "10" / "14.jsonl").read_text())["kind"] == "flag"
