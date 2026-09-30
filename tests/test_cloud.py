"""道乃久 on Cloudflare, the Python side (cloud/README.md): the full corpus as the site's server carries it (`taochronos web
store`: never what may not be passed on, the same passage ids, no index), compressed into the parts it is uploaded in,
unpacked, indexed and warmed where the image is built, served by the container only to the Worker's token, and the
upload client."""

from __future__ import annotations

import hashlib
import json
import lzma
import os
import sqlite3
import threading
import tomllib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from taochronos.chat import ChatRuntime
from taochronos.chat import cloud
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import JC_SOURCE, ingest_kanripo, load_catalog
from taochronos.plugins.classics.store import CorpusStore
from taochronos.plugins.classics.webcorpus import (NEVER_PACKED, PUBLISHED, WEB_SOURCES, compress_store, index_state,
                                                   server_attribution, server_store)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "kanripo"


@pytest.fixture(scope="module")
def full_store(tmp_path_factory) -> Path:
    """A full store with books of every kind of source: two Kanripo books (CC BY-SA), copies of one as 笈成 (recorded
    under the older "local research only" terms), TCM-Ancient-Books (no licence declared), 東亜医学協会 and the Hugging
    Face set (whose terms forbid passing them on), and a cached claim."""
    pack = DomainPack(ROOT / "domains" / "classics")
    path = tmp_path_factory.mktemp("full") / "tcm.sqlite"
    store = CorpusStore(path, create=True)
    ingest_kanripo(store, load_catalog(FIXTURES / "catalog.yaml"), FIXTURES, pack.variants.normalize_text,
                   pack.variants.fingerprint, log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    raw = json.loads(store.db.execute("SELECT data FROM books WHERE id = 'ceshi_fangshu'").fetchone()[0])
    rows = store.db.execute("SELECT id, seq, kind, locator, temporal, text FROM passages WHERE book_id = 'ceshi_fangshu'").fetchall()
    for bid, source, license in (("jc_ceshi", "jicheng", "使用者提供之笈成整理本：…仅供本地研究使用"),
                                 ("tab_ceshi", "tcm-ancient-books", "未声明授权；仅供本地研究使用"),
                                 ("ae_ceshi", "aeam", "© 東亜医学協会：限非营利的个人保存与使用"),
                                 ("hf_ceshi", "hf-tcm-canon", "proprietary-commercial")):
        store.put_book({**raw, "id": bid, "title": f"测试方书（{source}）", "source": {**raw["source"], "license": license}}, source)
        store.add_passages(({"id": f"{bid}.{pid.split('.', 1)[1]}", "book_id": bid, "seq": seq, "kind": kind,
                             "locator": {**json.loads(loc), "book_id": bid}, "temporal": json.loads(tmp), "text": text}
                            for pid, seq, kind, loc, tmp, text in rows), pack.variants.normalize_text)
    store.db.execute("INSERT INTO claim_cache VALUES ('ae_ceshi.001.00001', 'v1', '{\"quote\": \"what may not travel\"}')")
    store.count()
    store.commit()
    store.optimize()
    store.close()
    return path


@pytest.fixture(scope="module")
def site_store(full_store, tmp_path_factory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("site") / "tcm.sqlite"
    return out, server_store(full_store, out)


def test_the_site_carries_every_source_it_may_and_nothing_else(full_store, site_store):
    path, info = site_store
    db = sqlite3.connect(path)
    books = dict(db.execute("SELECT id, source FROM books"))
    assert books == {"ceshi_fangshu": "kanripo", "ceshi_neijing": "kanripo", "jc_ceshi": "jicheng", "tab_ceshi": "tcm-ancient-books"}
    assert info["excluded"] == {"aeam": 1, "hf-tcm-canon": 1} and set(info["excluded"]) == set(NEVER_PACKED)
    assert set(info["sources"]) <= set(WEB_SOURCES)
    assert not db.execute("SELECT COUNT(*) FROM passages WHERE book_id IN ('ae_ceshi', 'hf_ceshi')").fetchone()[0]
    assert not db.execute("SELECT COUNT(*) FROM claim_cache").fetchone()[0]
    # the passages as in the full store: the same ids, row ids and texts (a citation means the same passage everywhere)
    full = sqlite3.connect(full_store)
    kept = "SELECT rid, id, text FROM passages WHERE book_id NOT IN ('ae_ceshi', 'hf_ceshi') ORDER BY rid"
    assert db.execute("SELECT rid, id, text FROM passages ORDER BY rid").fetchall() == full.execute(kept).fetchall()
    assert info["passages"] == len(full.execute(kept).fetchall()) and info["books"] == 4
    meta = dict(db.execute("SELECT key, value FROM meta"))
    assert meta["edition"] == "full" and meta["index"] == "pending" and meta["index_rid"] == "0" and meta["counted"]
    assert meta["normalizer"] == dict(full.execute("SELECT key, value FROM meta"))["normalizer"]
    assert not db.execute("SELECT COUNT(*) FROM grams").fetchone()[0], "the index is built where the server is built"
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_each_book_says_on_what_terms_the_site_carries_it(site_store):
    path, info = site_store
    db = sqlite3.connect(path)
    terms = {bid: json.loads(data)["source"] for bid, data in db.execute("SELECT id, data FROM books")}
    assert terms["ceshi_fangshu"]["license"] == "CC BY-SA 4.0" and "published" not in terms["ceshi_fangshu"]
    assert terms["jc_ceshi"]["license"] == JC_SOURCE["license"] and "CC0" in terms["jc_ceshi"]["license"]
    assert terms["tab_ceshi"]["license"] == WEB_SOURCES["tcm-ancient-books"] and terms["tab_ceshi"]["published"] == PUBLISHED
    credits = server_attribution(path, info)
    assert "# 全量语料 · 来源与授权" in credits and f"共 {info['books']} 部录本" in credits
    assert "aeam 1 部" in credits and "hf-tcm-canon 1 部" in credits  # what is left out, and why
    assert credits.count(JC_SOURCE["license"]) == 1, "a source's terms once"
    assert "测试方书（tcm-ancient-books）" in credits and "测试方书（aeam）" not in credits


def test_the_store_travels_compressed_in_parts_it_can_be_checked_against(site_store, tmp_path, monkeypatch):
    path, _ = site_store
    monkeypatch.setattr("taochronos.plugins.classics.webcorpus.PART_BYTES", 4096)
    packed = compress_store(path, tmp_path / "store.xz", preset=1)
    data = (tmp_path / "store.xz").read_bytes()
    assert packed["bytes"] == len(data) and packed["sha256"] == hashlib.sha256(data).hexdigest()
    assert sum(p["bytes"] for p in packed["parts"]) == len(data) and all(p["bytes"] == 4096 for p in packed["parts"][:-1])
    assert b"".join(data[k * 4096:(k + 1) * 4096] for k in range(len(packed["parts"]))) == data
    assert [p["sha256"] for p in packed["parts"]] == [hashlib.sha256(data[k * 4096:(k + 1) * 4096]).hexdigest()
                                                       for k in range(len(packed["parts"]))]
    raw = lzma.decompress(data)
    assert raw == path.read_bytes() and packed["raw_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def prepared(site_store, tmp_path_factory) -> tuple[Path, dict, dict]:
    path, info = site_store
    work = tmp_path_factory.mktemp("image")
    packed = compress_store(path, work / "store.sqlite.xz", preset=1)
    manifest = {"key": f"store/{packed['sha256']}/", **packed, **info}
    data = work / "data"
    out = cloud.prepare(work / "store.sqlite.xz", data, manifest, calls=[("classics.search", {"query": "桂枝", "k": 2})])
    return data, manifest, out


def test_the_image_holds_the_store_indexed_and_warm_and_nothing_else(prepared):
    data, manifest, out = prepared
    store = data / "corpus" / "tcm.sqlite"
    assert index_state(store) == {"state": "built", "indexed": manifest["passages"], "total": manifest["passages"]}
    assert out["corpus"]["kind"] == "full" and out["corpus"]["books"] == 4 and out["corpus"]["label"] == "全量语料"
    assert out["warmed"] == [{"tool": "classics.search", "ok": True, "seconds": out["warmed"][0]["seconds"]}]
    assert sorted(p.name for p in data.iterdir()) == ["corpus"], "not the warm-up's events, artifacts or workspaces"
    assert not [p for p in data.rglob("*") if p.name.endswith(("-wal", "-shm", "-journal"))]
    assert {p.stat().st_mtime for p in data.rglob("*")} == {0}, "the same bytes make the same image layer"


def test_a_store_that_is_not_the_one_named_is_refused(site_store, tmp_path):
    path, info = site_store
    packed = compress_store(path, tmp_path / "store.xz", preset=1)
    with pytest.raises(SystemExit, match="sha256"):
        cloud.unpack(tmp_path / "store.xz", tmp_path / "out.sqlite", {**packed, "sha256": "0" * 64})
    with pytest.raises(SystemExit, match="unpacks"):
        cloud.unpack(tmp_path / "store.xz", tmp_path / "out.sqlite", {**packed, "raw_sha256": "0" * 64})


def _get(url: str, headers: dict | None = None, data: bytes | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})},
                                     method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_the_container_answers_only_the_workers_token_and_forwards_no_model_calls(prepared, monkeypatch):
    data, manifest, _ = prepared
    monkeypatch.setenv("TAOCHRONOS_DATA", str(data))
    monkeypatch.delenv("TAOCHRONOS_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="TAOCHRONOS_TOKEN"):
        cloud.serve(0)
    monkeypatch.setenv("TAOCHRONOS_TOKEN", "worker-token")
    servers = []
    from taochronos.chat import server as server_module

    class Recorded(server_module.ChatServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            servers.append(self)

    monkeypatch.setattr(server_module, "ChatServer", Recorded)
    thread = threading.Thread(target=cloud.serve, args=(0,), daemon=True)
    thread.start()
    for _ in range(600):
        if servers:
            break
        threading.Event().wait(0.05)
    assert servers, "the server did not start"
    base = f"http://127.0.0.1:{servers[0].server_address[1]}"
    try:
        status, body = _get(f"{base}/api/info")
        assert status == 401 and body["token_required"]
        status, info = _get(f"{base}/api/info", {"X-TC-Token": "worker-token"})
        assert status == 200 and info["corpus"]["kind"] == "full" and info["corpus"]["books"] == manifest["books"]
        assert info["proxy"] is False and info["env_keys"] is False
        status, out = _get(f"{base}/api/call", {"X-TC-Token": "worker-token"},
                           json.dumps({"name": "classics.search", "arguments": {"query": "桂枝", "k": 2}}).encode())
        assert status == 200 and out["ok"] and out["citations"]
        status, body = _get(f"{base}/api/llm", {"X-TC-Token": "worker-token", "X-TC-Target": "https://api.minimax.cn/v1/chat/completions"}, b"{}")
        assert status == 403 and "proxy is off" in body["error"]
        status, body = _get(f"{base}/index.html", {"X-TC-Token": "worker-token"})
        assert status == 404
    finally:
        servers[0].shutdown()


class _Bucket(BaseHTTPRequestHandler):
    """The site's Worker as the upload client sees it: HEAD and PUT under /api/store/, with the token."""
    objects: dict[str, bytes] = {}
    puts: list[str] = []

    def log_message(self, *args) -> None:
        pass

    def _auth(self) -> bool:
        if self.headers.get("Authorization") != "Bearer the-token":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    def do_HEAD(self) -> None:
        if not self._auth():
            return
        body = self.objects.get(self.path)
        self.send_response(200 if body is not None else 404)
        if body is not None:
            self.send_header("X-Content-SHA256", hashlib.sha256(body).hexdigest())
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PUT(self) -> None:
        if not self._auth():
            return
        body = self.rfile.read(int(self.headers["Content-Length"]))
        assert hashlib.sha256(body).hexdigest() == self.headers["X-Content-SHA256"]
        self.objects[self.path] = body
        self.puts.append(self.path)
        answer = json.dumps({"size": len(body)}).encode()
        self.send_response(201)
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)


def test_the_upload_sends_each_part_once_with_the_token(site_store, tmp_path, monkeypatch):
    path, info = site_store
    monkeypatch.setattr("taochronos.plugins.classics.webcorpus.PART_BYTES", 8192)
    packed = compress_store(path, tmp_path / "store.xz", preset=1)
    manifest = {"key": f"store/{packed['sha256']}/", **packed}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Bucket)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_address[1]}"
    for var in ("no_proxy", "NO_PROXY"):  # the test's own server, on this machine
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    try:
        _Bucket.objects.clear()
        _Bucket.puts.clear()
        first = cloud.upload(tmp_path / "store.xz", manifest, site, "the-token", log=lambda m: None)
        assert first == {"key": manifest["key"], "parts": len(packed["parts"]), "sent": len(packed["parts"]), "already": 0,
                         "bytes": packed["bytes"]}
        assert _Bucket.puts == [f"/api/store/{packed['sha256']}/{p['name']}" for p in packed["parts"]]
        assert b"".join(_Bucket.objects[p] for p in _Bucket.puts) == (tmp_path / "store.xz").read_bytes()
        again = cloud.upload(tmp_path / "store.xz", manifest, site, "the-token", log=lambda m: None)
        assert again["sent"] == 0 and again["already"] == len(packed["parts"])
        with pytest.raises(SystemExit, match="401"):
            cloud.upload(tmp_path / "store.xz", manifest, site, "wrong", log=lambda m: None)
        with pytest.raises(SystemExit, match="sha256"):
            cloud.upload(tmp_path / "store.xz", {**manifest, "sha256": "0" * 64}, site, "the-token", log=lambda m: None)
    finally:
        server.shutdown()


def test_the_manifest_in_the_repository_names_the_store_it_describes():
    manifest = json.loads((ROOT / "cloud" / "store.json").read_text(encoding="utf-8"))
    assert manifest["key"] == f"store/{manifest['sha256']}/" and manifest["encoding"] == "xz"
    assert sum(p["bytes"] for p in manifest["parts"]) == manifest["bytes"]
    assert [p["name"] for p in manifest["parts"]] == [f"part-{k:03d}" for k in range(len(manifest["parts"]))]
    assert all(p["bytes"] <= 25 * 1024 * 1024 for p in manifest["parts"]), "a part is one Workers KV value (≤ 25 MiB)"
    assert set(manifest["sources"]) <= set(WEB_SOURCES) and set(manifest["excluded"]) <= set(NEVER_PACKED)
    for k in ("books", "passages", "characters"):
        assert manifest[k] == sum(s[k] for s in manifest["sources"].values())
    credits = (ROOT / "cloud" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert f"共 {manifest['books']} 部录本，{manifest['characters']:,} 字，{manifest['passages']:,} 段" in credits
    assert credits.count("\n| ") - len(manifest["sources"]) - 2 == manifest["books"]  # a row per book


def test_the_site_carries_the_full_corpus_credits_beside_the_browsers(tmp_path):
    from taochronos.chat.build import build_site

    os.environ.setdefault("TAOCHRONOS_WEB_XZ_PRESET", "1")
    build_site(tmp_path / "site", home=ROOT, pyodide="cdn")
    assert (tmp_path / "site" / "ATTRIBUTION-full.md").read_text(encoding="utf-8") == (ROOT / "cloud" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "corpus=full" in (tmp_path / "site" / "attribution.html").read_text(encoding="utf-8")


def test_the_worker_runs_only_for_the_pages_and_the_api():
    """On the Workers Free plan every request the Worker answers counts (100,000 a day): the site's files are served
    without it — free and unmetered — with the headers of _headers; the pages (http → https) and the API with its own."""
    config = tomllib.loads((ROOT / "cloud" / "site" / "wrangler.toml").read_text(encoding="utf-8"))
    first = set(config["assets"]["run_worker_first"])
    pages = sorted(p.name for p in (ROOT / "web").glob("*.html"))
    # a page is asked for at its .html address and at the one without it (the assets redirect the first to the second)
    assert pages and first == {"/api/*", *(f"/{p}" for p in pages),
                               *("/" if p == "index.html" else f"/{p.removesuffix('.html')}" for p in pages)}
    rules = [line.strip() for line in (ROOT / "cloud" / "site" / "_headers").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert rules[0] == "/*"
    assert {"X-Content-Type-Options: nosniff", "X-Frame-Options: SAMEORIGIN",
            "Referrer-Policy: strict-origin-when-cross-origin"} <= set(rules)
    assert any(rule.startswith("Strict-Transport-Security: max-age=") for rule in rules)
    assert "cp _headers ../../_site/_headers" in (ROOT / "cloud" / "site" / "deploy.sh").read_text(encoding="utf-8")

