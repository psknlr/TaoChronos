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
        self.heaviest: int | None = None  # the most events it can hand out in a page (none: any number): more is a 500

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
            after, limit = int(q.get("after", ["0"])[0]), int(q.get("limit", ["500"])[0])
            if self.server.heaviest is not None and limit > self.server.heaviest:
                return self._json(500, {"error": {"type": "relay_error"}})
            rows = [r for r in self.server.rows if r["id"] > after]
            items = rows[:limit]
            page = {"items": items, "last": items[-1]["id"] if items else after, "more": len(rows) > limit}
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


def test_an_event_holding_what_no_file_of_lines_takes_is_pulled_all_the_same(workers, tmp_path):
    """A report's strings are the sender's, and anyone can send one.  JSON carries a lone surrogate (half a character)
    and the three characters ``str.splitlines`` takes for ends of lines; the pull once stopped on the first before its
    cursor moved — at every run, the same event first in what it was given — and wrote the others as they were, one
    event as several lines to its readers."""
    relay, site = workers
    lone, ends = "\ud800", "\u0085\u2028\u2029"
    site.rows.append({"id": 1, "received": "2026-10-14T02:00:00Z",
                      "event": {"v": 1, "kind": "csp", "reports": [{"directive": "script-src", "blocked": f"x{lone}y", f"k{lone}": f"a{ends}123{ends}b"}]}})
    site.rows.append({"id": 2, "received": "2026-10-14T03:00:00Z", "event": {"v": 1, "kind": "flag"}})
    site.next_id = 3
    got = collect.pull({"site": site.url}, tmp_path)
    assert (got["site_new"], got["site_last"]) == (2, 2)
    text = (tmp_path / "site" / "2026" / "10" / "14.jsonl").read_text(encoding="utf-8")
    assert [json.loads(x)["n"] for x in text.splitlines()] == [1, 2]  # two events, two lines — to a reader that splits as Python does
    assert text.count("\n") == 2 and not any(c in text for c in ends)
    first = json.loads(text.splitlines()[0])
    assert first["reports"] == [{"directive": "script-src", "blocked": "x\ufffdy", "k\ufffd": f"a{ends}123{ends}b"}]  # the half is U+FFFD, the rest as sent
    assert json.loads((tmp_path / "cursor.json").read_text())["site"]["last"] == 2  # the cursor moved: the next run begins after them
    assert collect.ack({"site": site.url}, tmp_path)["site_acked"] == 2
    # a day read back from a Worker's archive is written the same way
    site.archived = [{"n": 9, "received": "2026-10-14T05:00:00Z", "source": "site", "kind": "csp", "reports": [{"directive": f"d{lone}{ends}"}]}]
    assert collect.archive({"site": site.url}, "2026-10-14", tmp_path / ".archive")["site"] == 1
    back = (tmp_path / ".archive" / "site" / "2026" / "10" / "14.jsonl").read_text(encoding="utf-8")
    assert [json.loads(x)["reports"][0]["directive"] for x in back.splitlines()] == [f"d\ufffd{ends}"]


def test_an_answer_that_is_not_what_a_worker_keeps_ends_the_run_in_words(workers, tmp_path, monkeypatch):
    """Nested deeper than the parser goes: told as an answer that cannot be read, not as a traceback."""
    relay, site = workers

    class Deep:  # json, but what it is given to read is nested deeper than it goes
        JSONDecodeError = json.JSONDecodeError
        dumps = staticmethod(json.dumps)
        loads = staticmethod(lambda raw: json.loads("[" * 100_000 + "]" * 100_000))

    monkeypatch.setattr(collect, "json", Deep)
    site.add("2026-10-14T02:00:00Z", "flag")
    with pytest.raises(SystemExit, match="refused the export"):
        collect.pull({"site": site.url}, tmp_path)


def test_a_page_a_worker_cannot_hand_out_is_asked_for_again_smaller(workers, tmp_path):
    """A page too heavy for the Worker to hand out failed the export at every run: the collector asks for a smaller one."""
    relay, site = workers
    for k in range(7):
        site.add(f"2026-10-14T02:0{k}:00Z", "flag")
    relay.add("2026-10-14T01:00:00Z", "honeypot")
    site.heaviest = 3
    got = collect.pull({"relay": relay.url, "site": site.url}, tmp_path, limit=40)
    assert (got["relay_new"], got["site_new"], got["site_last"]) == (1, 7, 7)
    assert [json.loads(x)["n"] for x in (tmp_path / "site" / "2026" / "10" / "14.jsonl").read_text().splitlines()] == list(range(1, 8))


def test_a_days_events_are_kept_under_what_github_takes(workers, tmp_path, monkeypatch):
    """A day's events go on in further parts past PART_BYTES (a push holding a file over 100 MiB is refused)."""
    relay, site = workers
    monkeypatch.setattr(collect, "PART_BYTES", 300)
    for k in range(9):
        site.add(f"2026-10-14T02:0{k}:00Z", "flag")
    assert collect.pull({"site": site.url}, tmp_path)["site_new"] == 9
    parts = sorted((tmp_path / "site" / "2026" / "10").glob("14*.jsonl"))
    assert [p.name for p in parts][:2] == ["14.jsonl", "14.p02.jsonl"] and all(p.stat().st_size <= 300 for p in parts)
    assert [json.loads(x)["n"] for p in parts for x in p.read_text().splitlines()] == list(range(1, 10))
    assert collect.ack({"site": site.url}, tmp_path)["site_acked"] == 9


def test_the_door_walks_what_is_nested_deeper_than_the_interpreters_stack():
    """What a Worker kept may be nested deeper than Python's own stack goes (a report kept before its fields were
    checked): a walk that called itself for each level stopped the run there, on what the parser had read."""
    lone = "\ud800"
    deep = inner = []
    for k in range(50_000):
        box = {f"k{lone}": [f"x{lone}"]} if k % 2 else [f"y{lone}"]
        inner.append(box)
        inner = box[f"k{lone}"] if isinstance(box, dict) else box
    out = collect._text(deep)
    levels, node = 0, out
    while True:
        strings = [v for v in (node if isinstance(node, list) else list(node) + list(node.values())) if isinstance(v, str)]
        assert all(lone not in v for v in strings)
        below = [v for v in (node if isinstance(node, list) else node.values()) if isinstance(v, (list, dict))]
        if not below:
            break
        node, levels = below[0], levels + 1
    assert levels == 75_000
    plain = {"a": [1, "二", {"b": None, "c": True, "d": 1.5}], "e": "x"}
    assert collect._text(plain) == {"a": [1, "二", {"b": None, "c": True, "d": 1.5}], "e": "x"} and collect._text(f"a{lone}") == "a\ufffd" and collect._text(7) == 7
