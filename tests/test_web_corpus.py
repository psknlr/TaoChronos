"""要籍 and 要籍语料: the ranking of the works (corpus/catalog/canon.yaml), the pack of their texts (corpus/web), the
store the site ships and the browser indexes — the first-ranked works first, the rest in the background — and the harness
running on it (profile web-canon)."""

from __future__ import annotations

import gzip
import json
import lzma
from pathlib import Path

import pytest
import yaml

from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import ingest_kanripo, load_catalog
from taochronos.plugins.classics.store import CorpusStore, StoreCorpus
from taochronos.plugins.classics.study.canon import OPEN_SOURCES, witness_order
from taochronos.plugins.classics.webcorpus import (CORE_RANK, NEVER_PACKED, WEB_SOURCES, build_store, export_pack,
                                                   index_state, index_store, pack_order, select)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "kanripo"


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(ROOT / "domains" / "classics")


@pytest.fixture(scope="module")
def fixture_store(tmp_path_factory, pack) -> Path:
    path = tmp_path_factory.mktemp("canon") / "tcm.sqlite"
    store = CorpusStore(path, create=True)
    ingest_kanripo(store, load_catalog(FIXTURES / "catalog.yaml"), FIXTURES, pack.variants.normalize_text,
                   pack.variants.fingerprint, log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    store.optimize()
    store.close()
    return path


# ------------------------------------------------------------------ the ranked list
def test_the_ranked_list_is_metadata_ordered_by_citation():
    data = yaml.safe_load((ROOT / "corpus" / "catalog" / "canon.yaml").read_text(encoding="utf-8"))
    works = data["works"]
    assert len(works) == data["top"] == 350 and [w["rank"] for w in works] == list(range(1, 351))
    assert [w["score"] for w in works] == sorted((w["score"] for w in works), reverse=True)
    top = [w["title"] for w in works[:8]]
    for classic in ("黄帝内经素问", "伤寒论", "金匮要略方论", "神农本草经"):
        assert classic in top, top
    assert all(w["cited_by"] >= 1 for w in works) and not any("text" in w for w in works)  # no text in the list
    assert data["open"] == sum(1 for w in works if w["open"]) and all(
        (w["open_witness"] is not None) == w["open"] for w in works)
    assert all(w["open"] == bool(set(w["sources"]) & set(OPEN_SOURCES)) for w in works)  # open: a source in OPEN_SOURCES
    assert not any(w["category"] in ("现代", "非医籍") for w in works)
    pack = ROOT / "corpus" / "web" / "books.json"
    if pack.is_file():  # an open work's witness is the pack's first: the same order (OPEN_SOURCES leads WEB_SOURCES)
        first = {b["work"]: b["id"] for b in json.loads(pack.read_text(encoding="utf-8")) if b["witness"] == 1}
        assert all(first[w["work"]] == w["open_witness"] for w in works if w["open"])


def test_witnesses_are_chosen_open_collated_and_complete_first():
    sources = {"a": "kanripo", "b": "cmeta", "c": "cmeta", "d": "jicheng", "e": "tcm-ancient-books"}
    size = {"a": 90_000, "b": 30_000, "c": 88_000, "d": 99_000, "e": 500_000}
    assert sorted(sources, key=lambda b: witness_order(b, sources, size)) == ["c", "b", "a", "d", "e"]
    # 笈成 (CC0 1.0 for its editorial work) is open, last: the others keep their order
    assert list(OPEN_SOURCES) == ["cmeta", "kanripo", "wikisource", "mcgill", "jicheng"]


def test_the_site_takes_every_ranked_work_openly_licensed_witnesses_first_never_what_may_not_be_passed_on():
    sources = {"a": "kanripo", "b": "jicheng", "c": "cmeta", "d": "tcm-ancient-books", "e": "aeam"}
    size = {"a": 10, "b": 99_000, "c": 5, "d": 120_000, "e": 200_000}
    assert sorted(sources, key=lambda b: pack_order(b, sources, size))[:4] == ["c", "a", "b", "d"]
    assert list(WEB_SOURCES) == [*OPEN_SOURCES, "tcm-ancient-books", "tcmoc"]  # the open first, then the 笈成 copies
    assert set(NEVER_PACKED) == {"aeam", "hf-tcm-canon"} and not set(NEVER_PACKED) & set(WEB_SOURCES)


# ------------------------------------------------------------------ the pack and its store
def _rows(n: int, chapter_every: int = 5, size: int = 100) -> list[dict]:
    return [{"id": f"b.{k:05d}", "kind": "text", "text": "字" * size,
             "locator": {"volume": f"卷{k // (chapter_every * 4)}", "chapter": f"篇{k // chapter_every}"}} for k in range(n)]


def test_a_witness_over_its_budget_keeps_whole_chapters_spread_through_the_book():
    rows = _rows(400)  # 40 000 characters in 80 chapters of 500
    kept, extent = select(rows, 10_000)
    assert extent["chars"] == 40_000 and extent["kept_chars"] <= 10_000 and not extent["whole"]
    chapters = sorted({r["locator"]["chapter"] for r in kept}, key=lambda c: int(c[1:]))
    assert all(sum(1 for r in kept if r["locator"]["chapter"] == c) == 5 for c in chapters)  # whole chapters only
    positions = [int(c[1:]) for c in chapters]
    assert positions[0] < 10 and positions[-1] > 65  # from the beginning to the end of the book
    kept, extent = select(_rows(40), 10_000)
    assert extent["whole"] and len(kept) == 40


def test_the_pack_becomes_a_store_the_harness_reads_once_indexed(fixture_store, tmp_path, pack):
    import sqlite3

    works = [{"rank": 1, "work": "ceshi_neijing", "title": "测试内经"}, {"rank": 2, "work": "ceshi_fangshu", "title": "测试方书"}]
    info = export_pack(sqlite3.connect(fixture_store), works, tmp_path / "web")
    assert info["works"] == 2 and info["books"] == 2 and info["passages"] > 0
    assert "CC BY-SA 4.0" in (tmp_path / "web" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    lines = gzip.decompress((tmp_path / "web" / "passages.jsonl.gz").read_bytes()).decode().splitlines()
    first = json.loads(lines[0])
    assert first["id"].startswith("ceshi_") and "source_file" not in first["extra"]  # the full corpus's ids
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    build_store(tmp_path / "web", a, pack.variants.normalize_text, pack.variants.fingerprint, index=False)
    build_store(tmp_path / "web", b, pack.variants.normalize_text, pack.variants.fingerprint, index=False)
    assert a.read_bytes() == b.read_bytes()  # the same pack, the same bytes
    corpus = StoreCorpus(CorpusStore(a), pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)
    assert corpus.edition == "web" and not corpus.contains("消渴")  # not indexed yet
    corpus.store.close()
    assert index_store(a, pack.variants.normalize_text) == info["passages"]
    assert index_store(a, pack.variants.normalize_text) == 0  # once
    corpus = StoreCorpus(CorpusStore(a), pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)
    assert corpus.contains("消渴") and corpus.contains("治之以蘭除陳氣也") == ["ceshi_neijing.001.00000"]


def test_the_browser_indexes_the_first_ranked_works_first_and_the_rest_in_slices(fixture_store, tmp_path, pack):
    import sqlite3

    works = [{"rank": 1, "work": "ceshi_neijing", "title": "测试内经"}, {"rank": CORE_RANK + 1, "work": "ceshi_fangshu", "title": "测试方书"}]
    export_pack(sqlite3.connect(fixture_store), works, tmp_path / "web")
    db = tmp_path / "tcm.sqlite"
    build_store(tmp_path / "web", db, pack.variants.normalize_text, pack.variants.fingerprint, index=False)
    total = index_state(db)["total"]
    assert index_state(db) == {"state": "pending", "indexed": 0, "total": total}
    core = index_store(db, pack.variants.normalize_text, phase="core")
    assert 0 < core < total and index_state(db) == {"state": "pending", "indexed": core, "total": total}
    corpus = StoreCorpus(CorpusStore(db), pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)
    assert corpus.contains("治之以蘭除陳氣也") == ["ceshi_neijing.001.00000"]  # the first-ranked work: searchable
    assert set(corpus.books) == {"ceshi_neijing", "ceshi_fangshu"}  # the rest is there, its search follows
    later = [pid for pid in corpus.passage_ids() if pid.startswith("ceshi_fangshu")][0]
    assert not corpus.search([corpus.passage(later).text[:6]], book_ids=["ceshi_fangshu"])
    slices = []
    while n := index_store(db, pack.variants.normalize_text, limit=1, chunk=1):  # the rest in slices, while it reads
        slices.append(n)
    assert len(slices) == total - core and index_state(db) == {"state": "built", "indexed": total, "total": total}
    assert corpus.search([corpus.passage(later).text[:6]], book_ids=["ceshi_fangshu"])  # the same connection sees it
    assert index_store(db, pack.variants.normalize_text) == 0
    corpus.store.close()


# ------------------------------------------------------------------ the shipped pack in the browser's profile
@pytest.fixture(scope="module")
def web_runtime(tmp_path_factory):
    from taochronos.chat import ChatRuntime
    from taochronos.chat.build import corpus_store

    built = corpus_store(ROOT)
    if built is None:
        pytest.skip("no corpus/web pack in this checkout")
    data = tmp_path_factory.mktemp("webdata")
    (data / "corpus").mkdir()
    db = data / "corpus" / "tcm.sqlite"
    db.write_bytes(lzma.decompress(built[0]))
    domain = DomainPack(ROOT / "domains" / "classics")
    assert index_store(db, domain.variants.normalize_text) == built[1]["passages"]
    return ChatRuntime.create("web-canon", kind="browser", ephemeral=True, data_dir=data), built[1]


def test_the_site_corpus_is_the_ranked_works(web_runtime):
    rt, meta = web_runtime
    info = rt.info()
    corpus = info["corpus"]
    assert corpus["kind"] == "canon" and corpus["label"] == "要籍语料" and corpus["demo"]
    assert corpus["canon"]["listed"] == 350 and corpus["canon"]["held"] >= 345  # all but those known only through NEVER_PACKED
    assert meta["bytes"] < 16_000_000 and corpus["passages"] == meta["passages"] and 0 < meta["core_passages"] < meta["passages"]
    books = json.loads((ROOT / "corpus" / "web" / "books.json").read_text(encoding="utf-8"))
    assert {b["source"] for b in books} <= set(WEB_SOURCES) and not {b["source"] for b in books} & set(NEVER_PACKED)
    assert [b["rank"] for b in books] == sorted(b["rank"] for b in books)  # rank order: the first-ranked are indexed first
    for b in books:  # an openly licensed transcription keeps its own terms, any other says on what terms the site carries it
        assert (b["source"] in OPEN_SOURCES) != bool(b["data"]["source"].get("published")), b["id"]
    assert "要籍语料" in info["system_prompt"] and "classics.canon" in info["system_prompt"]
    hit = rt.call("validation.verify_quote", {"quote": "太阳病，头痛，发热，汗出，恶风，桂枝汤主之。"})
    assert hit["ok"] and "cm_shanghan_npm" in json.dumps(hit["result"], ensure_ascii=False)  # the 宋本, punctuation aside
    held = rt.call("classics.canon", {"held": False, "limit": 5})["result"]
    assert held["works"] and not any(w["in_this_corpus"] for w in held["works"])
    search = rt.call("classics.search", {"query": "消渴", "k": 3})
    assert search["ok"] and search["citations"]


def test_the_store_the_site_ships_is_deterministic():
    from taochronos.chat import build

    built = build.corpus_store(ROOT)
    if built is None:
        pytest.skip("no corpus/web pack in this checkout")
    again = build._corpus_store.__wrapped__(str(ROOT), build._pack_digest(ROOT / "corpus" / "web"), 1)  # not the cached one
    assert again[1]["sha256"] == built[1]["sha256"] and again[1]["encoding"] == "xz"
