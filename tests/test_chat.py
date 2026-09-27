"""The chat runtime, its local server and the site build (src/taochronos/chat)."""

from __future__ import annotations

import http.client
import json
import re
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from taochronos.chat import ChatRuntime
from taochronos.chat.catalog import CORE, clean_schema
from taochronos.chat.results import citations, compact, for_interface, summarize

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@pytest.fixture(scope="module")
def rt(tmp_path_factory):
    return ChatRuntime.create("full-discovery", kind="test", ephemeral=True, data_dir=tmp_path_factory.mktemp("chat"))


# ------------------------------------------------------------------ catalog
def test_the_catalog_offers_the_core_tools_and_reaches_every_other_through_meta_tools(rt):
    core = {t["tool"]: t for t in rt.catalog("core")["tools"]}
    every = {t["tool"]: t for t in rt.catalog("all")["tools"]}
    assert set(CORE) <= set(core) and {"taochronos_catalog", "taochronos_call", "taochronos_research"} <= set(core)
    assert len(every) >= 70 and "taochronos_catalog" not in every  # "all" offers every tool directly
    for tools in (core, every):
        assert "kg.propose_change" not in tools and "research.run_code" not in tools  # a person's act; Code Mode is opt-in
        for t in tools.values():
            assert NAME.match(t["name"]), t["name"]
            assert t["parameters"]["type"] == "object"
    assert every["vision.layout"]["parameters"]["properties"]["tokens"]["items"] == {"type": "object"}
    assert clean_schema({"type": "object", "properties": {"x": {"type": "array"}}})["properties"]["x"]["items"]


def test_tools_are_called_by_either_name_and_failures_are_results_not_crashes(rt):
    by_model_name = rt.call("classics__search", {"query": "桂枝汤", "k": 3})
    assert by_model_name["ok"] and by_model_name["tool"] == "classics.search"
    assert by_model_name["citations"] and all(c["passage_id"] for c in by_model_name["citations"])
    assert json.loads(by_model_name["text"])["hits"]
    assert rt.call("classics.get_passage", {"passage_id": "shanghanlun.c013"})["ok"]
    for name, args, needle in [("kg.propose_change", {}, "people"), ("research.run_code", {"code": "1"}, "Code Mode"),
                               ("no.such_tool", {}, "unknown tool"), ("taochronos_session", {}, "needs session_id"),
                               ("classics.search", {}, "invalid arguments")]:
        out = rt.call(name, args)
        assert not out["ok"] and needle in out["error"] and out["text"].startswith("ERROR:")


def test_meta_tools_list_and_call_the_rest(rt):
    cat = rt.call("taochronos_catalog", {"query": "配伍"})
    assert cat["ok"] and any(m["tool"] == "study.pairs" for m in cat["result"]["matched"])
    assert "study" in cat["result"]["families"]
    via = rt.call("taochronos_call", {"tool": "study.herb", "arguments": {"name": "黄连"}})
    assert via["ok"] and via["tool"] == "study.herb" and via["citations"]
    assert not rt.call("taochronos_call", {"tool": "kg.propose_change", "arguments": {}})["ok"]


def test_the_system_prompt_carries_the_evidence_discipline_and_the_corpus(rt):
    info = rt.info()
    assert info["corpus"]["demo"] and info["corpus"]["passages"] > 100
    prompt = info["system_prompt"]
    for must in ("[[passage_id]]", "逐字", "不提供诊断", "消渴＝糖尿病", "演示语料", "taochronos_catalog"):
        assert must in prompt


# ------------------------------------------------------------------ results
def test_compact_keeps_the_shape_and_fits_the_budget():
    big = {"hits": [{"passage_id": f"b.{i}", "text": "字" * 500} for i in range(300)], "note": "n"}
    for limit in (20000, 6000, 1500):
        text = compact(big, limit)
        assert len(text) <= limit + 40
    assert json.loads(compact(big, 20000))["hits"][-1].startswith("…（另有")
    assert for_interface(big, 50000)["note"] == "n"


def test_citations_are_gathered_once_with_the_fullest_text():
    cards = citations({"a": [{"passage_id": "p1", "text": "短"}, {"passage_id": "p1", "quote": "更长的引文", "title": "书"}],
                       "b": {"passage_id": "p2", "start": 0, "end": 3}})
    by = {c["passage_id"]: c for c in cards}
    assert by["p1"] == {"passage_id": "p1", "text": "更长的引文", "title": "书"}
    assert by["p2"] == {"passage_id": "p2"}
    assert summarize({"hits": [1, 2]}) == "2 条命中" and summarize([1, 2, 3]) == "3 项"


# ------------------------------------------------------------------ engine tools
def test_a_research_run_returns_its_hypotheses_with_evidence_and_can_be_followed_up(rt):
    out = rt.call("taochronos_research", {"question": "消渴的概念如何随时代演变？", "focus_terms": ["消渴"], "max_rounds": 1})
    assert out["ok"], out.get("error")
    res = out["result"]
    assert res["hypotheses"] and res["report_markdown"].startswith("# ")
    assert "report_markdown" not in json.loads(out["text"])  # the model reads the summary, the interface the report
    assert any(h["supporting"] for h in res["hypotheses"])
    assert res["metrics"]["agents_spawned"]
    assert "假说" in out["summary"]
    h1 = rt.call("taochronos_session", {"session_id": res["session_id"], "what": "hypothesis", "hypothesis": "H1"})
    assert h1["ok"] and h1["result"]["id"] == res["hypotheses"][0]["id"]
    assert rt.call("taochronos_session", {"session_id": res["session_id"], "what": "report", "section": "替代解释"})["result"]["matched"]


def test_the_v2_workflow_answers_with_its_steps_and_sources(rt):
    out = rt.call("taochronos_ask", {"question": "桂枝汤的组成在历代如何变化？"})
    assert out["ok"] and out["result"]["steps"] and out["result"]["report_markdown"]
    assert out["summary"].startswith("技能 S01")


# ------------------------------------------------------------------ the local server
@pytest.fixture(scope="module")
def server(rt):
    from taochronos.chat.server import ChatServer

    srv = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=60)
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    conn.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp, raw


def test_the_server_answers_the_api_and_serves_the_client(server):
    resp, raw = request(server, "GET", "/api/info")
    assert resp.status == 200 and json.loads(raw)["name"] == "TaoChronos"
    resp, raw = request(server, "POST", "/api/call", {"name": "classics.search", "arguments": {"query": "消渴"}})
    assert json.loads(raw)["ok"]
    resp, raw = request(server, "GET", "/api/passage?id=shanghanlun.c013")
    assert json.loads(raw)["title"] == "伤寒论"
    resp, raw = request(server, "GET", "/")
    assert resp.status == 200 and b"TaoChronos" in raw and resp.getheader("Content-Type").startswith("text/html")
    resp, raw = request(server, "GET", "/js/app.js")
    assert resp.getheader("Content-Type").startswith("text/javascript")
    resp, raw = request(server, "GET", "/providers.json")
    assert json.loads(raw)[0]["id"] == "minimax" and json.loads(raw)[0]["default_model"] == "MiniMax-M3"
    resp, raw = request(server, "GET", "/runtime/manifest.json")
    manifest = json.loads(raw)
    resp, pkg = request(server, "GET", "/runtime/taochronos.zip")
    assert len(pkg) == manifest["files"]["taochronos.zip"]["bytes"]
    assert "taochronos/chat/__init__.py" in zipfile.ZipFile(BytesIO(pkg)).namelist()
    resp, _ = request(server, "GET", "/../pyproject.toml")
    assert resp.status == 404


def test_the_server_admits_only_this_machine_and_the_published_client(server):
    resp, _ = request(server, "OPTIONS", "/api/call", headers={"Origin": "https://psknlr.github.io",
                                                             "Access-Control-Request-Method": "POST",
                                                             "Access-Control-Request-Private-Network": "true"})
    assert resp.status == 204 and resp.getheader("Access-Control-Allow-Origin") == "https://psknlr.github.io"
    assert resp.getheader("Access-Control-Allow-Private-Network") == "true"
    resp, _ = request(server, "POST", "/api/call", {"name": "classics.search", "arguments": {"query": "x"}},
                      {"Origin": "https://evil.example"})
    assert resp.status == 403
    resp, _ = request(server, "GET", "/api/info", headers={"Host": "rebound.example"})
    assert resp.status == 421
    resp, raw = request(server, "POST", "/api/llm", b"{}", {"X-TC-Target": "https://evil.example/v1/chat/completions"})
    assert resp.status == 403 and b"listed providers" in raw


def test_research_runs_in_the_background_and_is_polled(server):
    resp, raw = request(server, "POST", "/api/research", {"question": "中风的认识如何演变？", "focus_terms": ["中风"], "max_rounds": 1})
    job = json.loads(raw)["job"]
    import time

    for _ in range(240):
        resp, raw = request(server, "GET", f"/api/research/{job}")
        st = json.loads(raw)
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert st["status"] == "done" and st["outcome"]["ok"] and st["outcome"]["result"]["hypotheses"]


def test_the_model_proxy_streams_and_can_add_this_machines_key(server, monkeypatch):
    from web_mock import MockProvider

    mock = MockProvider().start()
    try:
        host = ("http", "127.0.0.1", mock.server_address[1])
        server.proxy_hosts.add(host)
        body = {"model": "MiniMax-M3", "messages": [{"role": "user", "content": "你好"}], "stream": True}
        resp, raw = request(server, "POST", "/api/llm", body, {"X-TC-Target": f"{mock.base_url}/chat/completions",
                                                               "Authorization": "Bearer user-key"})
        assert resp.status == 200 and resp.getheader("Content-Type") == "text/event-stream"
        assert b"reasoning_details" in raw and raw.rstrip().endswith(b"[DONE]")
        assert mock.requests[-1]["headers"]["Authorization"] == "Bearer user-key"
        # an SDK's own path under the proxy, with the machine's key standing in for the client's placeholder
        monkeypatch.setattr("taochronos.chat.server.key_env_for", lambda host: "TC_TEST_KEY")
        monkeypatch.setenv("TC_TEST_KEY", "machine-key")
        server.env_keys = True
        resp, raw = request(server, "POST", "/api/llm/v1/chat/completions?x=1", body,
                            {"X-TC-Target": f"http://127.0.0.1:{mock.server_address[1]}", "Authorization": "Bearer tc-env-key"})
        assert resp.status == 200
        assert mock.requests[-1]["path"] == "/v1/chat/completions?x=1"
        assert mock.requests[-1]["headers"]["Authorization"] == "Bearer machine-key"
    finally:
        server.env_keys = False
        server.proxy_hosts.discard(host)
        mock.shutdown()


# ------------------------------------------------------------------ the site
def test_the_site_build_is_deterministic_and_complete(tmp_path):
    from taochronos.chat.build import build_site, home_zip, package_zip

    assert package_zip() == package_zip()
    names = zipfile.ZipFile(BytesIO(home_zip(ROOT))).namelist()
    assert "architecture-policy.yaml" in names and any(n.startswith("corpus/demo/books/") for n in names)
    assert not any(n.startswith("domains/classics/lexicon-harvested/") for n in names)
    assert not any(n.endswith("tcm.sqlite") for n in names)
    info = build_site(tmp_path / "site", home=ROOT, pyodide="cdn")
    site = tmp_path / "site"
    for rel in ("index.html", "js/app.js", "js/worker.js", "css/app.css", "providers.json", "runtime/taochronos.zip",
                "runtime/home.zip", "runtime/manifest.json", ".nojekyll"):
        assert (site / rel).is_file(), rel
    manifest = json.loads((site / "runtime" / "manifest.json").read_text())
    assert manifest["pyodide_base"].startswith("https://cdn.jsdelivr.net/pyodide/") and info["files"] == manifest["files"]
    html = (site / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'(src|href)="/', html)  # every path is relative: the site lives under /TaoChronos/
