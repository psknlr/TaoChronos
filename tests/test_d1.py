"""The D1 backup, the Python side (docs/adr/0017-d1-backup.md): the exporter turns the store the site may publish into
statements D1 takes (never a source that may not be passed on; within D1's limits; the same statements every time,
each with the rows it writes), and the import resumes where it stopped — after a slice, a lost answer or a failed
statement — without writing anything twice."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from taochronos.chat import d1
from taochronos.chat.d1 import (MAX_PARAMS, MAX_SQL_BYTES, ApiTarget, SqliteTarget, TargetError, fts_form, fts_phrase, make_plan,
                                run_import, status)
from taochronos.chat.d1results import Precompute, clause_key, pack, unpack
from taochronos.chat.d1tables import module
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import ingest_kanripo, load_catalog
from taochronos.plugins.classics.store import CorpusStore
from taochronos.plugins.classics.webcorpus import NEVER_PACKED, server_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "kanripo"


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Path:
    """A store with two Kanripo books and copies of one under other sources — 笈成 (an open source), 東亜医学協会 and the
    Hugging Face set (whose terms forbid passing them on) — with a second temporal context in one book."""
    pack = DomainPack(ROOT / "domains" / "classics")
    path = tmp_path_factory.mktemp("full") / "tcm.sqlite"
    s = CorpusStore(path, create=True)
    ingest_kanripo(s, load_catalog(FIXTURES / "catalog.yaml"), FIXTURES, pack.variants.normalize_text,
                   pack.variants.fingerprint, log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    raw = json.loads(s.db.execute("SELECT data FROM books WHERE id = 'ceshi_fangshu'").fetchone()[0])
    rows = s.db.execute("SELECT id, seq, kind, locator, temporal, text FROM passages WHERE book_id = 'ceshi_fangshu'").fetchall()
    for bid, source in (("jc_ceshi", "jicheng"), ("ae_ceshi", "aeam"), ("hf_ceshi", "hf-tcm-canon")):
        s.put_book({**raw, "id": bid, "title": f"测试方书（{source}）"}, source)
        s.add_passages(({"id": f"{bid}.{pid.split('.', 1)[1]}", "book_id": bid, "seq": seq, "kind": kind,
                         "locator": {**json.loads(loc), "book_id": bid}, "temporal": json.loads(tmp), "text": text}
                        for pid, seq, kind, loc, tmp, text in rows), pack.variants.normalize_text)
    # a later layer in one book: its passages alternate between two temporal contexts
    s.db.execute("UPDATE passages SET temporal = '{\"dynasty\":\"清\",\"t_composition\":[1700,1700]}', year = 1700 "
                 "WHERE book_id = 'jc_ceshi' AND seq % 2 = 1")
    s.count()
    s.commit()
    s.close()
    return path


@pytest.fixture(scope="module")
def site_store(store, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("site") / "tcm.sqlite"
    server_store(store, out)
    return out


def small(path: Path, **kw):
    return make_plan(path, home=ROOT, version="test", db_bytes=kw.pop("db_bytes", 2_500), db0_reserve=kw.pop("db0_reserve", 500),
                     chunk_passages=kw.pop("chunk_passages", 8), chunk_chars=kw.pop("chunk_chars", 400), **kw)


def test_never_what_may_not_be_passed_on_whatever_store_it_is_given(store, tmp_path):
    plan = small(store)  # the full store itself: the exporter keeps to WEB_SOURCES all the same
    assert set(plan.books) == {"ceshi_fangshu", "ceshi_neijing", "jc_ceshi"}
    assert not {plan.sources[b] for b in plan.books} & set(NEVER_PACKED)
    target = SqliteTarget(tmp_path)
    assert run_import(plan, target, budget=10**9, log=lambda m: None)["complete"]
    for k in range(plan.databases):
        db = sqlite3.connect(target.path(k))
        books = {r[0] for r in db.execute("SELECT DISTINCT book FROM chunks")}
        assert not books & {"ae_ceshi", "hf_ceshi"}
        if k == 0:
            assert {r[0] for r in db.execute("SELECT id FROM books")} == set(plan.books)
        text = " ".join(r[0] for r in db.execute("SELECT body FROM chunks"))
        assert "ae_ceshi" not in text and "hf_ceshi" not in text


def test_statements_are_within_d1s_limits_and_the_same_every_time(site_store):
    a = [(b.db, b.step, b.key, b.sql, b.params, b.rows, b.bound) for b in small(site_store).order()]
    b = [(b.db, b.step, b.key, b.sql, b.params, b.rows, b.bound) for b in small(site_store).order()]
    assert a == b and len(a) > 20
    plan = small(site_store)
    assert plan.databases >= 3, "the small plan spreads over databases as the full corpus does"
    for batch in plan.order():
        assert batch.bytes <= MAX_SQL_BYTES and len(batch.params) <= MAX_PARAMS, (batch.step, batch.key)
        assert batch.sql.count("?") == len(batch.params) or batch.step != "chunks"
        assert batch.bound >= batch.rows >= 0


def test_the_rows_each_statement_writes_are_known(site_store, tmp_path):
    """SQLite counts every row a statement changes, FTS5's own included (D1 reports the table rows and the indexed
    documents): each statement writes at most its bound, and exactly its rows outside the index."""
    plan = small(site_store)
    target = SqliteTarget(tmp_path)
    for batch in plan.order():
        got = target.run(batch)["rows_written"]
        assert got <= batch.bound, (batch.step, batch.key, got, batch.bound)
        if batch.step in ("chunks", "books", "seqmap", "lex", "meta"):
            assert got == batch.rows, (batch.step, batch.key, got, batch.rows)


def test_chunks_follow_the_year_and_find_every_passage_again(site_store, tmp_path):
    plan = small(site_store)
    years = [c.year if c.year is not None else 1e9 for c in plan.chunks]
    assert years == sorted(years)
    target = SqliteTarget(tmp_path)
    run_import(plan, target, budget=10**9, log=lambda m: None)
    src = sqlite3.connect(site_store)
    want = {pid: text for pid, text in src.execute("SELECT id, text FROM passages")}
    got = {}
    for k in range(plan.databases):
        for book, body in sqlite3.connect(target.path(k)).execute("SELECT book, body FROM chunks"):
            for p in json.loads(body)["p"]:
                got[f"{book}.{p['m'] + '.' if 'm' in p else ''}{p['q']:05d}"] = p["t"]
    assert got == want
    # a book whose passages alternate between two temporal contexts has a seqmap
    db0 = sqlite3.connect(target.path(0))
    assert db0.execute("SELECT count(*) FROM seqmap WHERE book = 'jc_ceshi'").fetchone()[0] == 1
    stats = json.loads(db0.execute("SELECT v FROM meta WHERE k = 'stats'").fetchone()[0])
    assert stats["passages"] == len(want) and stats["ranges"][0][0] == 1 and stats["ranges"][-1][1] == len(plan.chunks)


def test_an_import_in_daily_slices_resumes_without_writing_anything_twice(site_store, tmp_path):
    plan = small(site_store)
    whole = SqliteTarget(tmp_path / "whole")
    run_import(plan, whole, budget=10**9, log=lambda m: None)
    sliced = SqliteTarget(tmp_path / "sliced")
    days = 0
    while True:
        days += 1
        # each day's run is a new process: nothing is known but what the databases say (a new day's budget: the record
        # of the day's use is cleared as the date changes)
        for k in range(plan.databases):
            if sliced.path(k).exists():
                sliced._db(k).execute("DELETE FROM progress WHERE k LIKE 'used:%'")
        report = run_import(plan, sliced, budget=500, log=lambda m: None)
        assert report["rows_written"] <= 500, report
        if report["complete"]:
            break
        assert report["stopped"].startswith("the day's budget") and days < 50
    assert days >= 4
    assert dump(whole, plan.databases) == dump(sliced, plan.databases)


class Flaky(SqliteTarget):
    """A target that loses the answer of one statement (it is applied) and refuses another (it is not)."""

    def __init__(self, root, lose: int, refuse: int) -> None:
        super().__init__(root)
        self.n, self.lose, self.refuse = 0, lose, refuse

    def run(self, batch):
        self.n += 1
        if self.n == self.refuse:
            raise TargetError("connection reset", transient=True)
        out = super().run(batch)
        if self.n == self.lose:
            raise TargetError("timed out", transient=True)
        return out


def test_a_lost_answer_or_a_failed_statement_is_not_applied_twice(site_store, tmp_path, monkeypatch):
    monkeypatch.setattr(d1.time, "sleep", lambda s: None)
    plan = small(site_store)
    whole = SqliteTarget(tmp_path / "whole")
    run_import(plan, whole, budget=10**9, log=lambda m: None)
    flaky = Flaky(tmp_path / "flaky", lose=9, refuse=14)
    report = run_import(small(site_store), flaky, budget=10**9, log=lambda m: None)
    assert report["complete"]
    assert dump(whole, plan.databases) == dump(flaky, plan.databases)


def test_a_run_stops_when_the_utc_day_is_over(site_store, tmp_path, monkeypatch):
    """What a run writes after 00:00 UTC would count against the new day's allowance, which the next run counts from
    the start: the run stops at midnight, and the next goes on from where it stopped."""
    monkeypatch.delenv("TAOCHRONOS_D1_DAY", raising=False)
    days = iter(["2026-10-01"] * 6 + ["2026-10-02"] * 10**6)
    monkeypatch.setattr(d1.time, "strftime", lambda fmt, t=None: next(days))
    target = SqliteTarget(tmp_path)
    report = run_import(small(site_store), target, budget=10**9, log=lambda m: None)
    assert report["stopped"].startswith("the UTC day is over") and not report["complete"]
    assert 0 < report["statements"] < 10
    assert run_import(small(site_store), target, budget=10**9, log=lambda m: None)["complete"]


def test_another_store_is_imported_afresh_only_when_asked(site_store, tmp_path):
    target = SqliteTarget(tmp_path)
    run_import(small(site_store), target, budget=10**9, log=lambda m: None)
    other = make_plan(site_store, home=ROOT, version="another", db_bytes=2_500, db0_reserve=500, chunk_passages=8, chunk_chars=400)
    with pytest.raises(SystemExit, match="--reset"):
        run_import(other, target, budget=10**9, log=lambda m: None)
    report = run_import(other, target, budget=10**9, log=lambda m: None, reset=True)
    assert report["complete"] and status(target, 0)["version"] == other.version


class FakeCloudflare:
    """A stand-in for Cloudflare's D1 REST API over local SQLite files: an account's databases listed a page at a time,
    created (with a location hint) and deleted; ``/query``: one statement and its parameters, answered with the rows as
    objects and ``meta.rows_written`` (as SQLite counts it); a statement's own error as HTTP 400 with SQLite's message,
    another token as 403.  ``fail``: what to answer instead to the next write whose SQL starts so — (prefix, HTTP
    status, message, applied first: an answer lost after the statement was applied)."""

    ACCOUNT = "0123abcd"

    def __init__(self, root: Path, token: str, *, others: int = 0) -> None:
        self.root, self.token = root, token
        root.mkdir(parents=True, exist_ok=True)
        self.dbs: dict[str, tuple[str, sqlite3.Connection]] = {}
        self.hints: dict[str, str | None] = {}
        self.calls: list[tuple[str, str, Any, int]] = []  # method, path and query, body, rows written
        self.fail: list[tuple[str, int, str, bool]] = []
        for i in range(others):
            self._create(f"another-app-{i:03d}")
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                fake._handle(self, "GET")

            def do_POST(self) -> None:
                fake._handle(self, "POST")

            def do_DELETE(self) -> None:
                fake._handle(self, "DELETE")

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/client/v4"

    def file(self, uid: str) -> Path:
        return self.root / f"{uid}.sqlite"

    def _create(self, name: str) -> str:
        uid = str(uuid.uuid4())
        self.dbs[uid] = (name, sqlite3.connect(self.file(uid), isolation_level=None, check_same_thread=False))
        return uid

    def _handle(self, h: BaseHTTPRequestHandler, method: str) -> None:
        size = int(h.headers.get("Content-Length") or 0)
        body = json.loads(h.rfile.read(size)) if size else None
        code, answer, rows = self._answer(h.headers.get("Authorization"), method, h.path, body)
        self.calls.append((method, h.path, body, rows))
        data = json.dumps(answer, ensure_ascii=False).encode("utf-8")
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    def _answer(self, auth: str | None, method: str, target: str, body: Any) -> tuple[int, dict[str, Any], int]:
        def ok(result: Any, rows: int = 0, **extra: Any) -> tuple[int, dict[str, Any], int]:
            return 200, {"success": True, "errors": [], "messages": [], "result": result, **extra}, rows

        def err(code: int, number: int, message: str) -> tuple[int, dict[str, Any], int]:
            return code, {"success": False, "errors": [{"code": number, "message": message}], "messages": [], "result": None}, 0

        if auth != f"Bearer {self.token}":
            return err(403, 10000, "Authentication error")
        path, _, query = target.partition("?")
        args = dict(urllib.parse.parse_qsl(query))
        base = f"/client/v4/accounts/{self.ACCOUNT}/d1/database"
        if path == base and method == "GET":
            per, page = int(args.get("per_page", 20)), int(args.get("page", 1))
            listed = [{"uuid": u, "name": n} for u, (n, _) in self.dbs.items()][(page - 1) * per:page * per]
            return ok(listed, result_info={"page": page, "per_page": per, "count": len(listed), "total_count": len(self.dbs)})
        if path == base and method == "POST":
            if any(n == body["name"] for n, _ in self.dbs.values()):
                return err(400, 7502, "A database with that name already exists")
            self.hints[body["name"]] = body.get("primary_location_hint")
            return ok({"uuid": self._create(body["name"]), "name": body["name"]})
        m = re.fullmatch(re.escape(base) + r"/([0-9a-f-]{36})(/query)?", path)
        if not m or m[1] not in self.dbs:
            return err(404, 7404, "The database could not be found")
        if method == "DELETE" and not m[2]:
            self.dbs.pop(m[1])[1].close()
            self.file(m[1]).unlink()
            return ok(None)
        if method != "POST" or not m[2]:
            return err(405, 10405, "Method not allowed")
        fail = None
        if self.fail and not body["sql"].startswith("SELECT") and body["sql"].startswith(self.fail[0][0]):
            fail = self.fail.pop(0)
            if not fail[3]:
                return err(fail[1], 7500, fail[2])
        con = self.dbs[m[1]][1]
        before = con.total_changes
        try:
            cur = con.execute(body["sql"], body["params"])
            names = [d[0] for d in cur.description or []]
            rows = [dict(zip(names, r)) for r in cur.fetchall()]
        except sqlite3.Error as exc:
            return err(400, 7500, f"{exc}: SQLITE_ERROR")
        written = con.total_changes - before
        if fail:  # applied, and the answer lost
            return fail[1], {"success": False, "errors": [{"code": 7500, "message": fail[2]}], "result": None}, written
        return ok([{"results": rows, "success": True, "meta": {"rows_written": written, "rows_read": len(rows), "changes": written}}],
                  written)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        for _, con in self.dbs.values():
            con.close()


def test_the_import_speaks_d1s_rest_api(site_store, tmp_path, monkeypatch):
    """ApiTarget (the daily job's way to D1) against the stand-in: the databases found by name across the account's
    pages and made where missing, near the site's readers; a statement a /query with its parameters; the rows written
    read from the answers; a busy API asked again, an answer lost after the statement was applied not applied twice,
    the daily allowance used up ending the run (the next goes on); a wrong token and a statement's own error told apart;
    another store: the databases deleted and made anew.  The databases end as the import into local files leaves them.
    (The wording of D1's daily-limit error is assumed: 429 and "exceeded", or "daily" and "limit".)"""
    monkeypatch.setattr(d1.time, "sleep", lambda s: None)
    monkeypatch.setenv("TAOCHRONOS_D1_DAY", "2026-10-01")  # both runs count against one day's allowance
    fake = FakeCloudflare(tmp_path / "cloudflare", "the-token", others=120)  # the account's other databases: two pages
    try:
        plan = small(site_store)
        api = ApiTarget(FakeCloudflare.ACCOUNT, "the-token", log=lambda m: None)
        api.API = fake.url
        api.ensure(plan.databases)
        assert [c[1].rsplit("/", 1)[1] for c in fake.calls[:2]] == ["database?per_page=100&page=1", "database?per_page=100&page=2"]
        names = {k: fake.dbs[u][0] for k, u in api.ids.items()}
        assert names == {k: f"taochronos-d1-{k}" for k in range(plan.databases)}
        assert set(fake.hints.values()) == {"apac"}
        fake.fail = [("INSERT INTO chunks(", 503, "Service temporarily unavailable", False),
                     ("INSERT INTO chunks(", 502, "Bad gateway", True),
                     ("INSERT INTO books(", 429, "D1 DB exceeded its daily limit of rows written", False)]
        first = run_import(plan, api, budget=10**9, log=lambda m: None)
        assert not first["complete"] and first["stopped"].startswith("the account's daily allowance is used up"), first
        assert not fake.fail
        second = run_import(plan, api, budget=10**9, log=lambda m: None)
        assert second["complete"] and second["used_before"] == first["rows_written"]
        whole = SqliteTarget(tmp_path / "whole")
        run_import(plan, whole, budget=10**9, log=lambda m: None)

        class Files:
            path = staticmethod(lambda k: fake.file(api.ids[k]))

        assert dump(Files, plan.databases) == dump(whole, plan.databases)
        writes = [(b, rows) for method, path, b, rows in fake.calls if path.endswith("/query") and not b["sql"].startswith("SELECT")]
        assert all(set(b) == {"sql", "params"} and len(b["params"]) <= MAX_PARAMS and len(b["sql"].encode()) <= MAX_SQL_BYTES
                   for b, _ in writes)
        # what the answers said was written is what the runs counted (the records of the day's use apart)
        assert sum(r for b, r in writes if not str((b["params"] or [""])[0]).startswith("used:")) == \
            first["rows_written"] + second["rows_written"]
        # a wrong token, a statement's own error
        wrong = ApiTarget(FakeCloudflare.ACCOUNT, "another-token", log=lambda m: None)
        wrong.API = fake.url
        with pytest.raises(TargetError, match="HTTP 403") as refused:
            wrong.databases()
        assert not refused.value.transient and not refused.value.exhausted
        with pytest.raises(TargetError, match="no such table") as bad:
            api.query(0, "SELECT * FROM missing")
        assert not bad.value.transient and not bad.value.exhausted
        # another store: the backup's databases made anew, the account's others untouched
        before = dict(api.ids)
        api.reset(plan.databases)
        assert sorted(api.ids) == sorted(before) and not set(api.ids.values()) & set(before.values())
        assert sum(1 for n, _ in fake.dbs.values() if n.startswith("another-app-")) == 120
        assert status(api, 0) == {}
    finally:
        fake.close()


def dump(target: Any, databases: int) -> list:
    out = []
    for k in range(databases):
        db = sqlite3.connect(target.path(k))
        for table in ("chunks", "books", "seqmap", "lex", "results", "meta"):
            try:
                out.append((k, table, db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()))
            except sqlite3.OperationalError:
                pass
        # the index answers alike (FTS5's pages depend on the segments: compare what it finds)
        out.append((k, "fts", db.execute("SELECT rowid FROM fts WHERE fts MATCH '\"方\"' ORDER BY rowid").fetchall()))
        out.append((k, "progress", [r for r in db.execute("SELECT k, v FROM progress ORDER BY k") if not r[0].startswith("used:")]))
    return out


def test_the_index_form_and_the_query_phrases():
    assert fts_form("太阳之为病，脉浮, a1 z") == "太 阳 之 为 病 ， 脉 浮 zx zx a 1 zx z"
    assert fts_phrase("桂枝汤") == '"桂 枝 汤"' and fts_phrase("abc") is None
    assert clause_key("太陽之為病，脈浮，頭項強痛而惡寒。", DomainPack(ROOT / "domains" / "classics").variants.normalize_text) == "太阳之为病脉浮头项强痛而恶寒"
    value = {"a": [1, "二"], "b": None}
    assert unpack(pack(value)) == value and pack(value) == pack(value)


def test_a_clause_is_computed_as_its_witness_punctuates_it():
    """The concordance's probes follow a query's punctuation (a clause's bare characters find other witnesses), so the
    commentaries and concordance of a clause are computed for it as its open witness writes it, normalised, and found
    by its bare characters — the key the Worker takes from a call's clause however it is punctuated."""
    norm = DomainPack(ROOT / "domains" / "classics").variants.normalize_text
    written = ["太陽之為病，脈浮，頭項強痛而惡寒。", "太陽病，發熱。", "太陽之為病脈浮頭項強痛而惡寒"]

    class Corpus:
        books = {"sw": {}, "jk": {}}

        def passages(self, book_ids, kinds):
            return [SimpleNamespace(text=t) for t in written] if book_ids == ["sw"] else []

    pre = Precompute(SimpleNamespace(h=SimpleNamespace(corpus=Corpus()), call=None))
    canon = [{"work": "shanghanlun", "open_witness": "sw"}, {"work": "neijing", "open_witness": "jk"},
             {"work": "jinkui", "open_witness": "absent"}]
    key = clause_key(written[0], norm)
    assert pre._clauses(canon, norm) == {key: norm(written[0])}  # 太陽病，發熱: too short; the unpunctuated copy: the first kept
    assert norm(written[0]) == "太阳之为病，脉浮，头项强痛而恶寒。"


def test_the_workers_tables_are_those_of_this_checkout():
    """cloud/site/src/backup/tables.js is generated (python -m taochronos.chat.d1 tables): the Worker must normalise as the
    databases were built, and offer the tools as they are described here."""
    path = ROOT / "cloud" / "site" / "src" / "backup" / "tables.js"
    assert path.read_text(encoding="utf-8") == module(ROOT), "run: python -m taochronos.chat.d1 tables"


def test_writing_the_tables_says_so_where_it_is_told(tmp_path, capsys):
    """`taochronos web canon` writes the tables too, and its stdout is its JSON report (the canon workflow reads it):
    the writer's own line goes where the caller says."""
    from taochronos.chat.d1tables import write_tables

    said: list[str] = []
    assert write_tables(tmp_path / "tables.js", home=ROOT, log=said.append) == 0
    assert said == [f"{tmp_path / 'tables.js'}: {(tmp_path / 'tables.js').stat().st_size:,} bytes"]
    assert capsys.readouterr().out == ""
    assert write_tables(tmp_path / "tables.js", home=ROOT, check=True, log=said.append) == 0 and said[-1].endswith("up to date")


TABLES = ROOT / "cloud" / "site" / "src" / "backup" / "tables.js"


def _exported(name: str) -> Any:
    """One table of tables.js (``export const NAME = <JSON>;``, a line each; a single-quoted string for a table of
    ``d1tables.TEXTS``)."""
    prefix = f"export const {name} = "
    line = next(x for x in TABLES.read_text(encoding="utf-8").split("\n") if x.startswith(prefix))
    value = line[len(prefix):-1]
    return _unquote(value) if value.startswith("'") else json.loads(value)


def _unquote(literal: str) -> str:
    """A single-quoted JS string literal as d1tables writes one: a backslash, the quote and the line terminators
    escaped, nothing else."""
    assert literal[0] == literal[-1] == "'" and "\n" not in literal
    escapes = {"\\\\": "\\", "\\'": "'", "\\n": "\n", "\\r": "\r", "\\u2028": "\u2028", "\\u2029": "\u2029"}
    return re.sub(r"\\(?:u2028|u2029|[\\'nr])", lambda m: escapes[m.group()], literal[1:-1])


def _alias_lines() -> dict[str, dict[str, Any]]:
    """tables.js's ALIASES: a line per record, the surface, a tab, its compact JSON."""
    out = {}
    for line in _exported("ALIASES").split("\n"):
        s, _, rec = line.partition("\t")
        out[s] = json.loads(rec)
    return out


def _full_corpus_classics() -> dict[str, Any]:
    from taochronos.protocol.yamlio import load_yaml

    profile = load_yaml(ROOT / "profiles" / "full-corpus.yaml")
    return next(b.get("config") or {} for b in profile["bundles"] if b["plugin"] == "taochronos.plugins.classics")


def test_the_workers_tables_carry_the_alias_layer_the_full_corpus_reads():
    """tables.js ships the full-corpus profile's alias layer (ADR 0023) as its index holds it: every record, keyed by
    surface in code-point order, in the file's compact form less what no decision reads (raw spellings, the floor's
    basis, a referent's note); the sources a record may credit (shippable, labelled as the layer's header labels them),
    the gates' context and the parameters (DEFAULT_ALIAS under the profile's retrieval.alias)."""
    from taochronos.plugins.classics.aliases import (
        CONTEXT_PATTERNS,
        DEFAULT_ALIAS,
        AliasRecord,
        layout,
    )
    from taochronos.protocol.yamlio import load_yaml

    classics = _full_corpus_classics()
    pack = DomainPack(ROOT / classics.get("domain", "domains/classics"), aliases=classics["aliases"])
    index = pack.aliases
    shipped = _alias_lines()
    assert index.enabled and list(shipped) == sorted(index.records)
    for s, rec in index.records.items():
        back = AliasRecord.from_json({**shipped[s], "s": s}).to_json()
        full = rec.to_json()
        for key in ("raw", "flb"):
            full.pop(key, None)
        back.pop("raw", None)
        for ref in full.get("r") or ():
            ref.pop("nt", None)
        assert back == full, s
    # what the Worker's lookups read without reading a record: the layout of those lines, Python's
    shape = layout([index.records[s] for s in shipped])
    assert _exported("ALIAS_INDEX") == {key: shape[key] for key in ("groups", "headless", "heads", "owners", "terms", "stops")}
    registry = {x["id"]: x for x in load_yaml(ROOT / "domains" / "classics" / "aliases" / "sources.yaml")["sources"]}
    sources = _exported("ALIAS_SOURCES")
    assert [x["id"] for x in sources] == [i for i, x in registry.items() if x["ship"] is True]
    assert all(x["label"] == index.labels[x["id"]] and x["licence"] == registry[x["id"]]["licence"] for x in sources)
    assert {src for rec in index.records.values() for ref in rec.r for src in ref.src} <= {x["id"] for x in sources}
    assert _exported("ALIAS_CONTEXT") == {**CONTEXT_PATTERNS, **index.context}
    profile = load_yaml(ROOT / "profiles" / "full-corpus.yaml")
    retrieval = next(b.get("config") or {} for b in profile["bundles"] if b["plugin"] == "taochronos.plugins.retrieval")
    assert _exported("ALIAS_PARAMS") == {**DEFAULT_ALIAS, **retrieval.get("alias", {})}


def test_a_table_of_text_is_a_single_quoted_js_string_of_the_same_text():
    """ALIASES is text of JSON lines: written single-quoted, its quotes need no escape (a third of its size else);
    a backslash, the quote and the line terminators are escaped, so the literal is one line and reads back as it was.
    A surface with a tab or a line break, which would cut its line, is refused."""
    from taochronos.chat.d1tables import TEXTS, _js_text

    assert "ALIASES" in TEXTS
    for text in ["", '{"h":"甘草"}\t{}', "a\\b'c\nd\re\u2028f\u2029g\"h", "\\'", "𠀀\\\\n"]:
        literal = _js_text(text)
        assert not any(ch in literal for ch in "\n\r\u2028\u2029") and literal.count("'") - literal.count("\\'") == 2
        assert _unquote(literal) == text
    assert '"' in _exported("ALIASES") and '\\"' not in TABLES.read_text(encoding="utf-8").split("export const ALIASES = ")[1][:2000]


def test_the_workers_tables_refuse_a_local_layer_and_a_source_that_may_not_ship(tmp_path):
    """Nothing local reaches the Worker: a full-corpus profile that reads a local layer, or a layer crediting a source
    sources.yaml does not ship, is refused."""
    import shutil

    from taochronos.chat.d1tables import _aliases

    domain = tmp_path / "domains" / "classics" / "aliases"
    shutil.copytree(ROOT / "domains" / "classics" / "aliases", domain)
    (tmp_path / "profiles").mkdir()
    bundle = "  - {plugin: taochronos.plugins.classics, config: {domain: domains/classics, aliases: [aliases]%s}}\n"
    profile = tmp_path / "profiles" / "full-corpus.yaml"
    profile.write_text("name: full-corpus\nbundles:\n" + bundle % "", encoding="utf-8")
    assert _aliases(tmp_path)["ALIASES"] == _exported("ALIASES")
    profile.write_text("name: full-corpus\nbundles:\n" + bundle % ", aliases_local: aliases/local/aliases-local.jsonl",
                       encoding="utf-8")
    with pytest.raises(ValueError, match="local alias layer"):
        _aliases(tmp_path)
    profile.write_text("name: full-corpus\nbundles:\n" + bundle % "", encoding="utf-8")
    sources = domain / "sources.yaml"
    sources.write_text(sources.read_text(encoding="utf-8").replace(
        "licence: project, ship: true", "licence: project, ship: false"), encoding="utf-8")
    with pytest.raises(ValueError, match="may not ship: curated"):
        _aliases(tmp_path)


def test_the_workers_lexicon_matches_names_as_long_as_the_full_corpus_lexicon_holds():
    """lexicon.js matches at most MAX_LEN characters at a time: never fewer than the full-corpus lexicon's longest
    surface, or the Worker would miss names the server finds."""
    text = (ROOT / "cloud" / "site" / "src" / "backup" / "lexicon.js").read_text(encoding="utf-8")
    max_len = int(re.search(r"const MAX_LEN = (\d+);", text).group(1))
    classics = _full_corpus_classics()
    pack = DomainPack(ROOT / classics.get("domain", "domains/classics"), extra_lexicons=classics.get("lexicon_extra", ()))
    assert max_len >= pack.lexicon.max_len


def test_the_workers_tables_stay_small():
    """tables.js is part of the Worker's bundle: gzipped, under 1,320,000 bytes, the alias layer included.  Measured
    985,921 with the NTU table on the web store's layer and the index its lookups read (ALIAS_INDEX, about 90,000 of
    it; 210,074 before the table); the margin follows the layer's own (aliasbuild.BUDGET): the rebuild on the full
    store keeps more of the table's pairs (+25–30 % expected).  The whole Worker (index.js and the modules it imports,
    tables.js among them) stays under Workers Free's 3 MB compressed a script (ADR 0017), measured here as one gzip
    stream of its files (about 1.09 MB today)."""
    import gzip

    assert len(gzip.compress(TABLES.read_bytes())) < 1_320_000
    src = ROOT / "cloud" / "site" / "src"
    files, todo = [], [src / "index.js"]
    while todo:  # the Worker's module graph, by its relative imports
        path = todo.pop().resolve()
        if path in files or not path.is_file():
            continue
        files.append(path)
        text = path.read_text(encoding="utf-8")
        todo += [path.parent / m for m in re.findall(r'^\s*(?:import|export)\b[^;]*?\bfrom\s+"(\.[^"]+)"', text, re.MULTILINE)]
    assert TABLES.resolve() in files and len(gzip.compress(b"".join(p.read_bytes() for p in files))) < 3_000_000


SEARCH = ROOT / "cloud" / "site" / "src" / "backup" / "search.js"


def test_the_full_corpus_searches_with_the_alias_layer_and_the_backup_alike():
    """The full corpus finds a drug under its other names (ADR 0023, phase B), on the server and in the D1 backup at once:
    the profile turns the layer on, tables.js hands the Worker that choice, and the fixture's reference questions — whose
    query blocks the Worker must reproduce (cloud/test/backup.test.js) — ask what the layer reads: an alias and its drug,
    periods, a name of two drugs, stop names, a longer name and a run nobody knows, a quoted alias, an origin question, a
    book filter, the side queue without a place (k, routes; k = 0 too) and the layer turned off — and a variant spelling
    written twice."""
    from taochronos.chat.d1fixture import REFERENCE
    from taochronos.protocol.yamlio import load_yaml

    profile = load_yaml(ROOT / "profiles" / "full-corpus.yaml")
    retrieval = next(b.get("config") or {} for b in profile["bundles"] if b["plugin"] == "taochronos.plugins.retrieval")
    assert retrieval["alias"]["enabled"] is True and _exported("ALIAS_PARAMS")["enabled"] is True
    searches = [args for name, args in REFERENCE if name == "classics.search"]
    asked = {args["query"] for args in searches}
    assert {"国老", "甘草", "唐以前的木通", "清代的通草", "鬼督邮是什么药", "救火是哪味药", "慎火草", "干葛"} <= asked
    assert any(args.get("aliases") == "off" for args in searches)
    assert any(args.get("routes") and "alias" not in args["routes"] for args in searches)
    assert any(args.get("k", 10) * 3 // 10 == 0 for args in searches) and any(args.get("k", 10) < 1 for args in searches)
    assert "人参汤即理中汤" in asked
    assert any(args.get("books") for args in searches) and any("最早" in args["query"] for args in searches)


def test_the_workers_search_reads_a_question_with_the_servers_rules():
    """search.js ports QueryAnalyzer's alias reading and the alias search (hybrid.py) with their constants copied: the
    drug words, the question words a run never takes in, a dose, what a longer name of a drug may add to it, the
    thresholds of a name asked only as a drug, what follows a period's name, the longest question read with the layer,
    the routes, the modes, the mask's bits (the cap's mask_bits) and the labels of a lexicon form's kind."""
    from taochronos.plugins.classics.aliases import DEFAULT_ALIAS
    from taochronos.plugins.retrieval import hybrid
    from taochronos.protocol.concepts import SynonymKind

    text = SEARCH.read_text(encoding="utf-8")

    def const(name: str) -> str:
        return re.search(rf"^(?:export )?const {name} = (.+?);(?: *//[^\n]*)?$", text, re.MULTILINE | re.DOTALL).group(1)

    def strings(source: str) -> list[str]:
        return re.findall(r'"([^"]*)"', source)

    assert tuple(strings(const("DRUG_WORDS"))) == hybrid.DRUG_WORDS
    assert set(strings(const("RUN_STOPS"))[0]) == set(hybrid.RUN_STOPS)
    assert [float(const(n)) for n in ("COMMON_N", "COMMON_SH", "COMMON_CUE_SH")] == [hybrid.COMMON_N, hybrid.COMMON_SH,
                                                                                   hybrid.COMMON_CUE_SH]
    assert const("PERIOD_TAIL") == f"/^{hybrid.PERIOD_TAIL.pattern}/u"
    assert const("DOSE_AT") == f"/{hybrid.DOSE_AT.pattern}/gu"
    assert set(strings(const("NAME_TAILS"))[0]) == set(hybrid.NAME_TAILS)
    assert set(strings(const("NAME_HEADS"))[0]) == set(hybrid.NAME_HEADS)
    assert int(const("ALIAS_MAX_CHARS")) == hybrid.ALIAS_MAX_CHARS  # longer questions are read without the layer
    # the parity questions on either side of it (d1fixture.REFERENCE): one read with the layer, one without
    from taochronos.chat.d1fixture import LONG_QUESTION, REFERENCE

    asked = [args["query"] for name, args in REFERENCE if name == "classics.search"]
    norm = DomainPack(ROOT / "domains" / "classics").variants.normalize_text
    assert [len(norm(q)) for q in asked if len(q) >= hybrid.ALIAS_MAX_CHARS] == [hybrid.ALIAS_MAX_CHARS, len(LONG_QUESTION)]
    assert len(norm(LONG_QUESTION)) > hybrid.ALIAS_MAX_CHARS
    assert tuple(strings(const("ROUTES"))) == hybrid.ROUTES and tuple(strings(const("ALIAS_MODES"))) == hybrid.ALIAS_MODES
    assert "alias" in strings(const("SERVED_ROUTES")) and "alias" not in hybrid.ROUTES
    # the cap counts the profile's mask_bits: an expansion it searches beyond the Worker's bits would go unread there
    bits = int(const("MASK_BITS"))  # an int32's bits in JavaScript
    assert bits == DEFAULT_ALIAS["mask_bits"] and _exported("ALIAS_PARAMS")["mask_bits"] <= bits <= 31
    labels = dict(re.findall(r'(\w+): "([^"]+)"', const("SYNONYM_LABELS")))
    pack = DomainPack(ROOT / "domains" / "classics")
    assert labels == {k.value: pack.synonym_kind_label(k.value) for k in SynonymKind}
