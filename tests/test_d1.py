"""The D1 backup, the Python side (docs/adr/0017-d1-backup.md): the exporter turns the store the site may publish into
statements D1 takes (never a source that may not be passed on; within D1's limits; the same statements every time,
each with the rows it writes), and the import resumes where it stopped — after a slice, a lost answer or a failed
statement — without writing anything twice."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from taochronos.chat import d1
from taochronos.chat.d1 import (MAX_PARAMS, MAX_SQL_BYTES, SqliteTarget, TargetError, fts_form, fts_phrase, make_plan, run_import,
                                status)
from taochronos.chat.d1results import clause_key, pack, unpack
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


def test_another_store_is_imported_afresh_only_when_asked(site_store, tmp_path):
    target = SqliteTarget(tmp_path)
    run_import(small(site_store), target, budget=10**9, log=lambda m: None)
    other = make_plan(site_store, home=ROOT, version="another", db_bytes=2_500, db0_reserve=500, chunk_passages=8, chunk_chars=400)
    with pytest.raises(SystemExit, match="--reset"):
        run_import(other, target, budget=10**9, log=lambda m: None)
    report = run_import(other, target, budget=10**9, log=lambda m: None, reset=True)
    assert report["complete"] and status(target, 0)["version"] == other.version


def dump(target: SqliteTarget, databases: int) -> list:
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


def test_the_workers_tables_are_those_of_this_checkout():
    """cloud/site/src/backup/tables.js is generated (python -m taochronos.chat.d1 tables): the Worker must normalise as the
    databases were built, and offer the tools as they are described here."""
    path = ROOT / "cloud" / "site" / "src" / "backup" / "tables.js"
    assert path.read_text(encoding="utf-8") == module(ROOT), "run: python -m taochronos.chat.d1 tables"
