"""The chat runtime, its local server and the site build (src/taochronos/chat)."""

from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.robotparser
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


def test_the_assistant_is_daonaijiu_with_the_model_tao_r1_published_by_impf_ai(rt):
    info = rt.info()
    assert (info["agent_name"], info["assistant_name"]) == ("道乃久", "Tao-R1")
    assert info["publisher"] == "医哲未来人工智能研究院（IMPF-AI）"
    prompt = info["system_prompt"]
    assert prompt.startswith("你是道乃久（TaoChronos）") and "医哲未来人工智能研究院（IMPF-AI）发布" in prompt and "Tao-R1" in prompt
    # asked who it is, it introduces the platform as the page's fixed reply does, and neither names nor denies its model
    flat = prompt.replace("\n", "")
    assert "欢迎用户使用道乃久（TaoChronos）中医古籍科学知识发现智能体平台" in flat and "本平台由医哲未来人工智能研究院（IMPF-AI）研发" in flat
    assert "不谈底层模型" in flat and "不否认" in flat and "不冒称其他身份" in flat
    assert prompt.rstrip().endswith("连接本地服务（全量语料）。")
    assert info["corpus"]["kind"] == "demo" and info["corpus"]["canon"]["listed"] == 350
    books = next(t for t in rt.catalog("all")["tools"] if t["tool"] == "classics.list_books")
    assert set(books["parameters"]["properties"]) == {"query", "dynasty", "category", "limit"}


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
    listed = {p["id"]: p for p in json.loads(raw)}  # the local server's page offers every preset (a published one: fewer)
    assert {"minimax", "deepseek", "anthropic", "ollama"} <= set(listed)
    assert listed["minimax"]["thinking_off"] == {"thinking": {"type": "disabled"}} and listed["deepseek"]["thinking_off"] is None
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
    for origin in ("https://chat.impf.ai", "http://chat.impf.ai"):  # the published client under its own domain
        resp, _ = request(server, "OPTIONS", "/api/call", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert resp.status == 204 and resp.getheader("Access-Control-Allow-Origin") == origin
    resp, _ = request(server, "POST", "/api/call", {"name": "classics.search", "arguments": {"query": "x"}},
                      {"Origin": "https://evil.example"})
    assert resp.status == 403
    resp, _ = request(server, "GET", "/api/info", headers={"Host": "rebound.example"})
    assert resp.status == 421
    resp, raw = request(server, "POST", "/api/llm", b"{}", {"X-TC-Target": "https://evil.example/v1/chat/completions"})
    assert resp.status == 403 and b"listed providers" in raw


def test_the_proxy_reaches_a_hand_set_endpoint_only_when_allowed(rt):
    from taochronos.chat.server import ChatServer, allowed_host

    assert allowed_host("api.example.com") == ("https", "api.example.com", 443)
    assert allowed_host("http://10.0.0.5:8000/v1") == ("http", "10.0.0.5", 8000)
    with pytest.raises(ValueError):
        allowed_host("ftp://x")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=None, home=ROOT, allow_hosts=["https://gw.example.com:8443"])
    try:
        assert ("https", "gw.example.com", 8443) in srv.proxy_hosts and ("https", "api.minimax.cn", 443) in srv.proxy_hosts
    finally:
        srv.server_close()


def test_the_server_answers_its_own_pages_wherever_it_is_reached(server):
    assert server.origin_allowed("http://192.168.1.5:8765", "192.168.1.5:8765")  # its own page, on a LAN address
    assert not server.origin_allowed("http://192.168.1.5:8765", "192.168.1.6:8765")
    assert not server.origin_allowed("https://evil.example", "192.168.1.5:8765")


def test_a_server_other_machines_can_reach_needs_its_token(rt):
    from taochronos.chat.server import ChatServer, access_token

    assert access_token("127.0.0.1", None) is None and access_token("0.0.0.0", "given") == "given"
    one, two = access_token("0.0.0.0", None), access_token("192.168.1.5", None)
    assert one and two and one != two and len(one) >= 20
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT, token="t0ken")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        resp, raw = request(srv, "GET", "/api/info")
        assert resp.status == 401 and json.loads(raw)["token_required"]
        resp, _ = request(srv, "GET", "/api/info", headers={"X-TC-Token": "t0ke"})
        assert resp.status == 401
        resp, raw = request(srv, "GET", "/api/info", headers={"X-TC-Token": "t0ken"})
        assert resp.status == 200 and json.loads(raw)["assistant_name"] == "Tao-R1"
        resp, _ = request(srv, "POST", "/api/llm", b"{}", {"X-TC-Target": "https://api.minimaxi.com/v1/chat/completions"})
        assert resp.status == 401  # the model proxy as well
        resp, raw = request(srv, "GET", "/")  # the page is not secret: it asks for the token
        assert resp.status == 200 and b"Tao-R1" in raw
        resp, _ = request(srv, "OPTIONS", "/api/info", headers={"Origin": "https://psknlr.github.io", "Access-Control-Request-Method": "GET",
                                                               "Access-Control-Request-Headers": "x-tc-token"})
        assert resp.status == 204 and "x-tc-token" in resp.getheader("Access-Control-Allow-Headers")
    finally:
        srv.shutdown()
        srv.server_close()


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
    if (ROOT / "corpus" / "web" / "passages.jsonl.gz").is_file():  # the 要籍语料: a store without its index, xz-compressed
        corpus = manifest["files"]["corpus.sqlite.xz"]
        assert corpus["profile"] == "web-canon" and corpus["bytes"] == (site / "runtime" / "corpus.sqlite.xz").stat().st_size
        assert corpus["encoding"] == "xz" and corpus["core_rank"] == 40 and corpus["core_passages"] < corpus["passages"]
    # the YAML the runtime reads, parsed by the build: the browser reads it from the cache, keyed by each file's content
    shipped = zipfile.ZipFile(site / "runtime" / "home.zip")
    cached = [n for n in shipped.namelist() if n.startswith(".cache/yaml/")]
    assert len(cached) > 40 and all(n.endswith(".v1.pickle") for n in cached)
    import hashlib
    import pickle

    from taochronos.protocol.yamlio import load_yaml
    raw = shipped.read("domains/classics/periods.yaml")
    key = hashlib.sha256(raw).hexdigest()
    entry = f".cache/yaml/{key[:2]}/{key}.v1.pickle"
    assert entry in cached and pickle.loads(shipped.read(entry)) == load_yaml(ROOT / "domains" / "classics" / "periods.yaml")
    # what the runtime will report, known before it loads: the page asks the model at once
    boot = json.loads((site / "runtime" / "boot.json").read_text(encoding="utf-8"))
    assert boot["info"]["name"] == "TaoChronos" and boot["info"]["runtime"] == "browser" and boot["info"]["system_prompt"]
    core, every = ({t["name"] for t in boot["catalogs"][mode]["tools"]} for mode in ("core", "all"))
    assert "classics__search" in core and core - {"taochronos_catalog", "taochronos_call"} < every  # core: some, with the catalog
    html = (site / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'(src|href)="/', html)  # every path is relative: the site lives under /TaoChronos/
    # the texts' credits travel with the site (the repository is private); no conversation record can enter it
    assert (site / "attribution.html").is_file() and "CC BY-SA 4.0" in (site / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert not any("chat-logs" in p.as_posix() or p.relative_to(site).parts[0] == "data" for p in site.rglob("*"))
    assert not any(n.startswith("data/") for n in names)
    assert not (site / "site.json").exists() and info["relay"] is None  # without a relay: the visitor's own key, as before
    # what a search engine reads: the pages' text without the script, their addresses, and the files it may skip
    about = (site / "about.html").read_text(encoding="utf-8")
    assert not re.search(r'(src|href)="/', about) and '<link rel="canonical" href="https://chat.impf.ai/about">' in about
    assert '<link rel="canonical" href="https://chat.impf.ai/">' in html and 'class="intro-static"' in html
    assert 'href="about"' in html and "医哲未来人工智能研究院" in html
    robots = (site / "robots.txt").read_text(encoding="utf-8")
    assert "Disallow: /runtime/" in robots and "Sitemap: https://chat.impf.ai/sitemap.xml" in robots
    # every search engine may read the pages (Baidu's, Petal's and Toutiao's crawlers too: they gather for search as
    # well); a crawler that only gathers training data may not
    rules = urllib.robotparser.RobotFileParser()
    rules.parse(robots.splitlines())
    for agent in ("Baiduspider", "Googlebot", "bingbot", "Sogou web spider", "360Spider", "YisouSpider", "PetalBot", "Bytespider",
                  "Applebot", "YandexBot", "DuckDuckBot", "OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"):
        assert rules.can_fetch(agent, "https://chat.impf.ai/") and rules.can_fetch(agent, "https://chat.impf.ai/about"), agent
    for agent in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended", "Applebot-Extended", "meta-externalagent", "Amazonbot"):
        assert not rules.can_fetch(agent, "https://chat.impf.ai/"), agent
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert re.findall(r"<loc>(.*?)</loc>", sitemap) == ["https://chat.impf.ai/", "https://chat.impf.ai/about",
                                                         "https://chat.impf.ai/attribution"]


def test_the_site_names_its_relay_only_when_told(tmp_path):
    from taochronos.chat.build import build_site

    info = build_site(tmp_path / "a", home=ROOT, pyodide="cdn", relay="https://chat-api.impf.ai/")
    assert json.loads((tmp_path / "a" / "site.json").read_text()) == {"relay": "https://chat-api.impf.ai"} == {"relay": info["relay"]}
    build_site(tmp_path / "b", home=ROOT, pyodide="cdn", relay="none")
    assert not (tmp_path / "b" / "site.json").exists()
    with pytest.raises(ValueError):
        build_site(tmp_path / "c", home=ROOT, pyodide="cdn", relay="chat-api.impf.ai")
    # the page names no vendor behind its default service: the build leaves out the presets it is told to
    build_site(tmp_path / "d", home=ROOT, pyodide="cdn", relay="https://chat-api.impf.ai", unlist=["minimax", " minimax-global"])
    offered = (tmp_path / "d" / "providers.json").read_text(encoding="utf-8")
    assert json.loads(offered)[0]["id"] == "deepseek" and "minimax" not in offered.lower()
    assert "minimax" in (tmp_path / "a" / "providers.json").read_text(encoding="utf-8").lower()
    with pytest.raises(ValueError, match="no such provider preset: minmax"):
        build_site(tmp_path / "e", home=ROOT, pyodide="cdn", unlist=["minmax"])
    key = re.compile(rb"sk-[A-Za-z0-9_-]{24,}")  # no key-shaped string anywhere in what the site serves
    assert not [p for p in (tmp_path / "a").rglob("*") if p.is_file() and p.suffix in (".json", ".js", ".html", ".md") and key.search(p.read_bytes())]
