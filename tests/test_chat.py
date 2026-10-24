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
                               ("no.such_tool", {}, "unknown tool"),
                               ("taochronos_session", {}, "missing required property 'session_id'"),
                               ("taochronos_session", {"session_id": ""}, "needs session_id"),
                               ("classics.search", {}, "invalid arguments")]:
        out = rt.call(name, args)
        assert not out["ok"] and needle in out["error"] and out["text"].startswith("ERROR:")


def test_a_models_arguments_are_repaired_where_only_their_form_is_wrong(rt):
    """A number written as text, a list wrapped as {"item": …} (how some models' tool grammars write one), one value where
    a list is expected, a list or an object written as JSON text: the call runs, and says what was repaired."""
    out = rt.call("classics__search", {"query": "桂枝汤", "k": "3"})
    assert out["ok"] and len(out["result"]["hits"]) == 3 and out["repaired"] == ['$.k: "3" → 3']
    wrapped = rt.call("kg.claims", {"terms": {"item": "消渴"}, "limit": "5"})
    assert wrapped["ok"] and wrapped["repaired"] == ['$.terms: {"item":"消渴"} → ["消渴"]', '$.limit: "5" → 5']
    assert wrapped["result"] == rt.call("kg.claims", {"terms": ["消渴"], "limit": 5})["result"]
    assert rt.call("kg.claims", {"terms": "消渴"})["repaired"] == ['$.terms: "消渴" → ["消渴"]']
    via = rt.call("taochronos_call", {"tool": "study.herb", "arguments": '{"name": "黄连", "items": "2"}'})
    assert via["ok"] and via["tool"] == "study.herb" and via["repaired"] == ['$.items: "2" → 2']
    meta = rt.call("taochronos_catalog", {"family": ["study"]})
    assert meta["ok"] and meta["repaired"] == ['$.family: ["study"] → "study"'] and meta["result"]["matched"]
    # a well-formed call is left exactly as it is; a text that lists several values is not taken for one value
    assert "repaired" not in rt.call("classics.search", {"query": "桂枝汤", "k": 3})
    listed = rt.call("kg.claims", {"terms": "消渴、口渴"})
    assert not listed["ok"] and "$.terms: expected array, got str" in listed["error"]
    assert not rt.call("classics.search", {"query": "桂枝汤", "k": "three"})["ok"]


def test_a_parameter_the_tool_does_not_take_is_refused_with_what_it_takes(rt):
    """A call naming a parameter the tool does not have would run without it — a case search for 耳鸣 written with
    ``query`` returned every case — so it is refused, with the tool's parameters, for the model to correct in one step."""
    out = rt.call("study.herb", {"surface": "黄连"})
    assert not out["ok"] and out["error"] == ("invalid arguments: $: missing required property 'name'; $: unknown parameter "
                                              "'surface' · study.herb takes: name (string, required); items (integer)")
    extra = rt.call("classics.get_passage", {"passage_id": "shanghanlun.c013", "chars": 500})
    assert not extra["ok"] and "unknown parameter 'chars'" in extra["error"] and "passage_id (string, required)" in extra["error"]
    research = rt.call("taochronos_research", {"question": "消渴", "depth": "deep"})
    assert not research["ok"] and "unknown parameter 'depth'" in research["error"] and "question (string, required)" in research["error"]
    assert not rt.call("taochronos_call", {"name": "study.herb", "args": {"name": "黄连"}})["ok"]


def test_a_tool_named_in_another_form_is_that_tool_and_an_unknown_one_is_answered_with_the_closest(rt):
    for written in ("get_passage", "study__get_passage", "get_classics__get_passage", "Classics.Get_Passage"):
        out = rt.call(written, {"passage_id": "shanghanlun.c013"})
        assert out["ok"] and out["tool"] == "classics.get_passage", written
    assert rt.call("taochronos.catalog", {})["tool"] == "taochronos_catalog"
    assert rt.call("taochronos_call", {"tool": "get_passage", "arguments": {"passage_id": "shanghanlun.c013"}})["ok"]
    ambiguous = rt.call("search", {"query": "桂枝汤"})  # classics, modern and mydata each have a search: not guessed
    assert not ambiguous["ok"] and ambiguous["error"].startswith("unknown tool 'search'; closest: classics.search {query (string, required)")
    assert ambiguous["error"].endswith("; use taochronos_catalog to see what exists")
    other = rt.call("literature.search", {"query": "x"})
    assert other["error"].startswith("unknown tool 'literature.search'; closest: modern.search {subject (string, required)")
    # what a chat model is never offered is never reached by another form of its name, nor suggested
    for written in ("KG.Propose-Change", "propose_change", "kg.propose", "run_code", "research.run-code"):
        out = rt.call(written, {})
        closest = out["error"].split("; closest: ", 1)[1]
        assert not out["ok"] and "propose_change" not in closest and "run_code" not in closest, written


def test_a_passage_names_the_ones_around_it_and_an_id_that_is_none_is_answered_with_what_its_book_has(rt):
    """Reading on: a passage's prev and next walk its book, each passage once, and back.  An id that is no passage says
    what its book has there (the passage its number names, else the nearest), or that it names no book — for every tool
    that reads a passage by its id, and for the page's evidence drawer."""
    corpus = rt.h.corpus
    book = corpus.passage("shanghanlun.c013").book_id
    first = next(i for i in corpus.passage_ids() if corpus.passage(i).book_id == book and corpus.around(i)[0] is None)
    walk, at = [], first
    while at:
        card = rt.call("classics.get_passage", {"passage_id": at})["result"]
        walk.append(at)
        at = card["next"]
    assert len(walk) == len(set(walk)) == corpus.book_passage_count(book) > 1
    back, at = [], walk[-1]
    while at:
        back.append(at)
        at = rt.call("classics.get_passage", {"passage_id": at})["result"]["prev"]
    assert back == walk[::-1]
    for args, said in [({"passage_id": "shanghanlun.c13"}, "PassageNotFound: no passage 'shanghanlun.c13' in this corpus; the "
                                                           "passage of shanghanlun (伤寒论) numbered 13 is shanghanlun.c013"),
                       ({"passage_id": "nosuch.c001"}, "PassageNotFound: no passage 'nosuch.c001': it names no book of this "
                                                       "corpus (an id begins with its book's id); classics.list_books lists the "
                                                       "books, and classics.search finds passages by their words")]:
        out = rt.call("classics.get_passage", args)
        assert not out["ok"] and out["error"] == said and out["text"].startswith("ERROR: PassageNotFound")
    unnumbered = rt.call("classics.get_passage", {"passage_id": "shanghanlun.preface"})["error"]
    assert unnumbered == (f"PassageNotFound: no passage 'shanghanlun.preface' in this corpus; shanghanlun (伤寒论) has "
                          f"{corpus.book_passage_count(book)} passages here; classics.search finds them by their words")
    assert "the nearest shanghanlun.c" in rt.call("classics.get_passage", {"passage_id": "shanghanlun.c0135"})["error"]
    assert rt.call("philology.assess_passage", {"passage_id": "shanghanlun.c13"})["error"].endswith("is shanghanlun.c013")
    assert rt.call("philology.collate", {"passage_a": "shanghanlun.c013", "passage_b": "shanghanlun.c13"})["error"].endswith(
        "is shanghanlun.c013")
    drawer = rt.passage("shanghanlun.c13")
    assert not drawer["ok"] and drawer["error"].endswith("numbered 13 is shanghanlun.c013")
    assert {"prev", "next"} <= set(rt.passage("shanghanlun.c013"))


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
    # its answers name nothing of the platform's inside, and offer neither its data nor its code; nor is it told to send
    # anyone to the local service's command
    flat = prompt.replace("\n", "").replace(" ", "")
    for must in ("##不外露内部细节", "不写工具名与函数名、参数与字段名、模块与阶段代号、命令行、文件路径与配置项", "能否下载数据库或语料、源代码",
                 "说明这些不对外提供", "引文后的出处标注[[…]]照常写"):
        assert must in flat, must
    assert "`taochronos serve`" not in prompt and "在本机运行" not in prompt and "（G7）" not in prompt


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
    assert prompt.rstrip().endswith("告诉用户可在“设置 → 运行环境”接入全量语料。")
    import yaml

    listed = len(yaml.safe_load((ROOT / "corpus" / "catalog" / "canon.yaml").read_text(encoding="utf-8"))["works"])
    assert info["corpus"]["kind"] == "demo" and info["corpus"]["canon"]["listed"] == listed
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


def test_a_cards_labels_are_kept_as_words_for_the_page():
    """A taochronos_ask source's ``labels`` (ADR 0023: what the search found it under, in words) reach the page's card:
    every mention's, each once; anything but a list of words is no label."""
    via, flag = "via 国老→甘草（别名录（中醫笈成））", "年代存疑（甘草约 1180 年后才通行；或经后世刊本改字）"
    cards = citations({"sources": [{"passage_id": "p1", "title": "书", "labels": [via, "", 7, via]},
                                   {"passage_id": "p1", "labels": [flag, via]}, {"passage_id": "p2", "labels": []},
                                   {"passage_id": "p3", "labels": {"via": via}}, {"passage_id": "p4", "labels": via}]})
    by = {c["passage_id"]: c for c in cards}
    assert by["p1"] == {"passage_id": "p1", "title": "书", "labels": [via, flag]}
    assert by["p2"] == {"passage_id": "p2"} and by["p3"] == {"passage_id": "p3"} and by["p4"] == {"passage_id": "p4"}


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
    # its state, how long it waited and ran, what its session did
    assert [st["state"], st["position"], st["heartbeat_s"], st["session"]] == ["completed", None, None, st["outcome"]["result"]["session_id"]]
    assert st["queued_s"] >= 0 and st["run_s"] > 0 and st["progress"]["events"] > 0 and st["progress"]["hypotheses"]


def test_a_research_run_on_the_server_can_be_stopped(server):
    """POST …/cancel: a run stops at once while it waits, after the task it runs once it has begun; …/resume takes
    up only a run the server stopped; and the site lets both through to its corpus server (cloud/site/src/site.js)."""
    import time

    starts = [json.loads(request(server, "POST", "/api/research", {"question": q, "focus_terms": ["消渴"], "max_rounds": 1})[1])["job"]
              for q in ("消渴何以为病？", "消渴之名何来？")]
    views = [json.loads(request(server, "POST", f"/api/research/{job}/cancel", b"{}")[1]) for job in reversed(starts)]
    assert views[0]["state"] == "cancelled" and views[0]["position"] is None  # the second was waiting: stopped at once
    for _ in range(240):
        st = json.loads(request(server, "GET", f"/api/research/{starts[0]}")[1])
        if st["state"] in ("cancelled", "completed", "failed"):
            break
        time.sleep(0.25)
    assert st["state"] == "cancelled" and st["status"] == "error" and not st["outcome"]["ok"], st
    assert json.loads(request(server, "POST", f"/api/research/{starts[0]}/resume", b"{}")[1])["state"] == "cancelled"
    assert json.loads(request(server, "POST", "/api/research/job_none/cancel", b"{}")[1])["state"] == "unknown"
    site = (ROOT / "cloud" / "site" / "src" / "site.js").read_text(encoding="utf-8")
    posts = re.search(r"const POSTS = /(.+)/;", site).group(1).replace("\\/", "/")
    assert all(re.match(posts, p) for p in ("/api/research", "/api/research/job_0123456789ab/cancel", "/api/research/job_x/resume"))
    assert not any(re.match(posts, p) for p in ("/api/research/job_x", "/api/research/job_x/delete", "/api/research/a/b/cancel"))


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


def test_home_zip_carries_the_alias_layer_and_nothing_of_a_local_one():
    """ADR 0023: the browser reads the shipped alias layer from home.zip — never a file or a record of the local lists
    (the NTU table, hurbTable, the GB 别名录), which stay under <data>/aliases/local/ — and the directory keeps to its
    deflated budget as home.zip stores it (zlib's default level, as `aliases check` measures it)."""
    from taochronos.chat.build import home_zip
    from taochronos.plugins.classics.aliasbuild import BUDGET
    from taochronos.protocol.yamlio import load_yaml

    shipped = zipfile.ZipFile(BytesIO(home_zip(ROOT)))
    folder = "domains/classics/aliases/"
    members = {i.filename: i for i in shipped.infolist() if i.filename.startswith(folder)}
    assert {folder + "aliases.jsonl", folder + "context.json"} <= set(members)
    assert set(members) <= {folder + f for f in ("aliases.jsonl", "context.json", "curated.yaml", "sources.yaml")}
    # no file a local layer writes: the imported lists, their manifest, the layer built of them, the review sheet
    local = re.compile(r"(^|/)\.taochronos/|(^|/)aliases/local/|aliases-local\.jsonl$|(^|/)(ntu|hurb|bielu-gb)\.jsonl$"
                       r"|(^|/)review\.tsv$")
    assert not [n for n in shipped.namelist() if local.search(n)]
    # nor a record crediting a local list
    registry = load_yaml(ROOT / folder / "sources.yaml")["sources"]
    local_ids = {s["id"] for s in registry if not s.get("ship")}
    assert local_ids == {"bielu-gb", "hurb", "ntu40k"}
    lines = shipped.read(folder + "aliases.jsonl").decode("utf-8").splitlines()
    header = json.loads(lines[0])["_header"]
    credited = {src for line in lines[1:] for ref in json.loads(line).get("r", ()) for src in ref.get("src", ())}
    assert "bielu-jc" in credited and not (set(header["sources"]) | credited) & local_ids
    assert set(header["sources"]) <= {s["id"] for s in registry if s.get("ship")}
    # the directory as the browser downloads it: at most 150 KB deflated
    assert sum(i.compress_size for i in members.values()) <= 150_000 == BUDGET["directory"]


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
