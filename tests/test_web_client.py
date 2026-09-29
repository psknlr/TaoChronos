"""The web client (web/): its pure logic under Node, and the whole page in Chromium against a scripted provider.

Both are skipped where Node or a Playwright Chromium is not available (the CI image has neither by default).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NODE_TEST = r"""
import assert from "node:assert/strict";
import { Accum, splitThink } from "./js/llm/openai.js";
import { answerDangling, buildHistory } from "./js/agent.js";
import { extractCitations } from "./js/markdown.js";
import { count } from "./js/util.js";
import { fixedReply, IDENTITY_REPLY, isIdentityQuestion } from "./js/fixed.js";

// streams: increments and MiniMax's cumulative chunks read alike
const inc = new Accum(); for (const t of ["桂", "枝", "汤主之。"]) inc.push(t);
assert.equal(inc.text, "桂枝汤主之。");
const cum = new Accum(); for (const t of ["桂", "桂枝", "桂枝汤主之", "桂枝汤主之。太阳病"]) cum.push(t);
assert.equal(cum.text, "桂枝汤主之。太阳病");
assert.deepEqual(splitThink("<think>想</think>\n答"), { thinking: "想", answer: "答", open: false });

// history: MiniMax gets its reasoning_details back; other providers do not; old tool results are shortened
const wire = [
  { role: "assistant", content: "", reasoning_details: [{ type: "reasoning.text", text: "t" }], reasoning_content: "r",
    tool_calls: [{ id: "c1", type: "function", function: { name: "classics__search", arguments: "{}" } }] },
  { role: "tool", tool_call_id: "c1", content: "R".repeat(5000) },
  { role: "assistant", content: "答", reasoning_details: [{ text: "u" }] },
];
const msgs = [{ role: "user", text: "问" },
  { role: "assistant", wire, wireFormat: "openai", wireProvider: "minimax", segments: [{ type: "text", text: "答" }] }];
let h = buildHistory(msgs, { id: "minimax", format: "openai", reasoning: "reasoning_details" });
assert.equal(h.length, 4);
assert.ok(h[1].reasoning_details && h[1].tool_calls);
assert.equal(h[1].reasoning_content, undefined);
assert.ok(h[2].content.length < 3000 && h[2].content.includes("截短"));
assert.equal(wire[1].content.length, 5000); // the stored turn is not changed
h = buildHistory(msgs, { id: "deepseek", format: "openai", reasoning: "reasoning_content" });
assert.equal(h[1].reasoning_details, undefined);
h = buildHistory(msgs, { id: "anthropic", format: "anthropic" });
assert.deepEqual(h, [{ role: "user", content: "问" }, { role: "assistant", content: "答" }]);

// a stopped turn: every tool call still gets an answer
const d = answerDangling([{ role: "assistant", content: "", tool_calls: [{ id: "a" }, { id: "b" }] },
  { role: "tool", tool_call_id: "a", content: "x" }], "openai");
assert.deepEqual(d.map((m) => m.tool_call_id ?? m.role), ["assistant", "a", "b"]);
const da = answerDangling([{ role: "assistant", content: [{ type: "tool_use", id: "t1" }] }], "anthropic");
assert.equal(da[1].content[0].tool_use_id, "t1");

// citations pair with the quotation just before them, never across lines
assert.deepEqual(extractCitations("- 「甲乙」[[a.1]]\n- 无引文[[b.2]]\n\n「丙」[[c.3]][[d.4]] `[[e.5]]`"), [
  { pid: "a.1", quote: "甲乙" }, { pid: "b.2", quote: null }, { pid: "c.3", quote: "丙" }, { pid: "d.4", quote: "丙" }]);

// the corpus in 万 and 亿, as the page shows it
assert.deepEqual([count(2053597, "段"), count(122841774, "字"), count(966, "部书"), count(12345), count(null, "段")],
  ["205 万段", "1.2 亿字", "966 部书", "1.2 万", "? 段"]);

// asked who answers, and nothing else, the page replies itself, in fixed words that name no model
assert.ok(IDENTITY_REPLY.startsWith("欢迎您使用道乃久（TaoChronos）中医古籍科学知识发现智能体平台，本平台由医哲未来人工智能研究院（IMPF-AI）研发。"));
assert.ok(!/模型|底层|minimax|deepseek|gpt|claude|qwen/i.test(IDENTITY_REPLY));
for (const q of ["你是谁，谁发布的，你真实模型是什么", "你可以自己介绍一下自己这个平台吗", "你是谁？", "您好，请问您是哪位？", "你是谁开发的",
  "谁创造了你", "你是哪家公司的产品", "你用的是什么大模型？", "你基于什么模型", "底层模型是什么", "Tao-R1 的底层模型是什么",
  "你是 ChatGPT 吗？", "你是不是DeepSeek-R1", "你是claude还是gpt", "说实话你到底是谁", "请做个自我介绍", "介绍一下你自己",
  "这是什么网站？", "你叫什么名字", "道乃久是什么", "你能做什么", "这个平台有哪些功能", "你们是做什么的", "你是誰？誰開發的？"]) {
  assert.equal(fixedReply(q), IDENTITY_REPLY, q);
}
// anything else goes to the model: a question about someone or something else, one that asks more, one with pictures
for (const q of ["张仲景是谁", "《伤寒论》是谁写的？", "你是什么意思", "你是谁的学生", "你是谁？张仲景是谁？", "你是什么模型？帮我查一下桂枝汤",
  "谁发布的", "什么模型", "介绍一下桂枝汤", "介绍一下你们的语料", "你用什么模型分析五运六气", "五运六气模型是什么", "你能检索哪些书",
  "你能找到的最早的资料是什么？", "在这个平台上，关于脾胃功能的记载有哪些", "道乃久出自哪里", "道乃久是什么意思",
  "这是豆包吗", "你是AI吗", "你好", "Who are you?", "桂枝汤的原方组成与剂量出自哪里？后世有哪些重要的加减化裁？"]) {
  assert.equal(isIdentityQuestion(q), false, q);
  assert.equal(fixedReply(q), null, q);
}
assert.equal(fixedReply("你是谁", ["data:image/jpeg;base64,/9j/"]), null);
console.log("ok");
"""


def test_the_client_logic_under_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    shutil.copytree(ROOT / "web" / "js", tmp_path / "js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text(NODE_TEST, encoding="utf-8")
    run = subprocess.run([node, "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and run.stdout.strip() == "ok", run.stderr[-2000:]
    for js in sorted((ROOT / "web" / "js").rglob("*.js")):  # every module parses
        check = subprocess.run([node, "--check", str(tmp_path / "js" / js.relative_to(ROOT / "web" / "js"))],
                               capture_output=True, text=True, timeout=60)
        assert check.returncode == 0, (js, check.stderr[-1000:])


def _chromium():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return None
    for path in (os.environ.get("TAOCHRONOS_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if path and Path(path).exists():
            return path
    return ""  # Playwright's own browser, if it has one


def test_a_conversation_in_the_browser(tmp_path):
    """A conversation on 道乃久默认服务 — MiniMax's wire behind the relay, never named on the page."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockProvider, MockRelay

    mock = MockProvider().start()
    relay = MockRelay(mock.base_url).start()
    web = tmp_path / "web"
    shutil.copytree(ROOT / "web", web)
    (web / "site.json").write_text(json.dumps({"relay": relay.url}), encoding="utf-8")
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    consent = {"v": 1, "logs": False, "at": "2026-09-28T00:00:00Z"}  # asked before (the question itself: the next test)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.consent', {json.dumps(json.dumps(consent))});")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=10000)
            assert page.title() == "道乃久 · 中医古籍研究智能体" and page.inner_text(".hero h1") == "道乃久"
            assert page.inner_text(".hero .publisher") == "医哲未来人工智能研究院（IMPF-AI）发布"
            page.fill("#input", "桂枝汤主治什么？请给出原文。")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            cites = page.eval_on_selector_all(".md .cite", "els => els.map(e => [e.dataset.pid, e.className])")
            assert cites == [["shanghanlun.c013", "cite ok"], ["shanghanlun.c012", "cite warn"], ["fake.999", "cite bad"],
                             ["shanghanlun.c013", "cite ok"]]  # the last quoted in the traditional script
            assert page.inner_text("#model-chip .nm") == "Tao-R1" and page.get_attribute("#model-chip", "title") == "Tao-R1 · 道乃久默认服务"
            assert page.inner_text(".msg.assistant .meta").startswith("Tao-R1 · ")
            assert page.get_attribute(".msg.assistant .meta", "title") == "道乃久默认服务"
            # the page names no vendor: not in what it shows, nor in its titles, nor in the model settings
            shown = page.inner_text("body") + "".join(page.eval_on_selector_all("[title]", "els => els.map(e => e.title)"))
            assert "MiniMax" not in shown and "minimax" not in shown.lower()
            page.click("#model-chip")
            settings_text = page.inner_text("#settings")
            assert "道乃久默认服务" in settings_text and "免密钥" in settings_text and "minimax" not in settings_text.lower()
            page.keyboard.press("Escape")
            page.click(".steps .head")  # the finished steps are folded
            assert "classics.search" in page.inner_text(".steps .list")
            assert "繁简" in page.eval_on_selector_all(".md .cite.ok", "els => els[1].title")
            page.click(".md .cite.ok >> nth=0")
            assert page.inner_text(".passage-view .text mark") == "太阳病，头痛，发热，汗出，恶风，桂枝汤主之"
            # a second turn replays the first verbatim: tool call, reasoning_details, tool result
            page.fill("#input", "它的组成呢？")
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelectorAll('.msg.assistant .verify-bar').length >= 2", timeout=60000)
            first, second = mock.requests[0]["body"], mock.requests[1]["body"]
            assert first["max_completion_tokens"] == 8192 and first["reasoning_split"] is True and first["tools"]  # within the relay's ceiling
            assert first["messages"][0]["role"] == "system" and "[[passage_id]]" in first["messages"][0]["content"]
            system = first["messages"][0]["content"]
            assert system.startswith("你是道乃久") and "MiniMax" not in system and "底层语言模型：" not in system  # no model named
            replay = second["messages"][2]
            assert replay["tool_calls"][0]["function"] == {"name": "classics__search", "arguments": '{"query": "桂枝汤 主之", "k": 3}'}
            assert replay["reasoning_details"][0]["text"] == "用户问桂枝汤的主治，先检索原文。"
            assert second["messages"][3]["role"] == "tool" and "shanghanlun.c013" in second["messages"][3]["content"]
            later = mock.requests[2]["body"]["messages"]
            assert [m["role"] for m in later] == ["system", "user", "assistant", "tool", "assistant", "user"]
            # the conversation survives a reload
            page.reload()
            page.wait_for_selector(".conv.active", timeout=15000)
            assert page.locator(".msg.assistant").count() == 2
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        relay.shutdown()
        mock.shutdown()


def test_claude_through_the_official_sdk(tmp_path):
    """The Claude adapter loads the pinned SDK from jsDelivr (fetched here by Python, TLS verified, and handed to the
    page), asks with adaptive thinking and server-side fallbacks, and replays the thinking block verbatim."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    import urllib.request

    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockAnthropic

    sdk = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.128.0/+esm"
    try:
        urllib.request.urlopen(sdk, timeout=20).close()
    except OSError as exc:
        pytest.skip(f"the Anthropic SDK cannot be fetched here: {exc}")

    def via_python(route):
        with urllib.request.urlopen(route.request.url, timeout=60) as r:
            route.fulfill(status=r.status, body=r.read(), headers={"content-type": r.headers.get("content-type", "text/javascript"),
                                                                    "access-control-allow-origin": "*"})

    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    mock = MockAnthropic().start()
    settings = {"provider": "anthropic", "baseUrls": {"anthropic": mock.base_url}, "keys": {"anthropic": "sk-test"}, "route": "direct"}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            ctx.route("https://cdn.jsdelivr.net/**", via_python)
            ctx.add_init_script(f"localStorage.setItem('tc.settings', {json.dumps(json.dumps(settings))});")
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.fill("#input", "桂枝汤主治什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            first, second = mock.requests[0], mock.requests[1]
            assert first["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
            assert first["body"]["fallbacks"] == "default" and first["body"]["model"] == "claude-opus-5"
            assert first["body"]["thinking"] == {"type": "adaptive", "display": "summarized"}
            assert all(t["eager_input_streaming"] for t in first["body"]["tools"])
            replay = second["body"]["messages"][1]["content"]
            assert replay[0] == {"type": "thinking", "thinking": "先检索原文。", "signature": "sig-abc"}
            assert replay[1]["type"] == "tool_use" and replay[1]["input"] == {"query": "桂枝汤 主之", "k": 3}
            assert second["body"]["messages"][2]["content"][0]["tool_use_id"] == "toolu_1"
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            assert page.eval_on_selector_all(".md .cite", "els => els.map(e => e.className)") == ["cite ok", "cite warn", "cite bad", "cite ok"]
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        mock.shutdown()


def test_a_published_page_connects_to_a_server_and_remembers_it(tmp_path):
    """The page served elsewhere (as on GitHub Pages) connects to `taochronos serve` in one step and, in auto mode, uses
    it again on the next visit; a server other machines can reach takes its token from the address, and without it
    says what is missing."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer

    class Static(SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    api = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT)
    locked = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT, token="t0ken")
    pages = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Static, directory=str(ROOT / "web")))  # no runtime files
    for s in (api, locked, pages):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            page = browser.new_context(viewport={"width": 1280, "height": 860}).new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{pages.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.bad", timeout=30000)  # no browser runtime here, no server known
            page.click(".hero-action")
            page.fill(".connect-row input[type=url]", f"http://127.0.0.1:{api.server_address[1]}/")
            page.click(".connect-row .btn")
            page.wait_for_function("document.querySelector('.settings-pane .notice')?.textContent.includes('当前：本地服务')", timeout=30000)
            assert "尚未构建全量语料" in page.inner_text(".connect .notice.warn")  # this server has only the demonstration corpus
            page.click(".modal-foot .btn:not(.secondary)")
            assert "本地服务" in page.inner_text(".runtime-pill") and "演示语料" in page.inner_text(".runtime-pill")
            assert page.inner_text("#hint") == "Tao-R1 · 本地服务 · 演示语料"
            page.reload()  # auto mode: the server this browser worked with, first
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert page.inner_text(".runtime-pill").startswith("本地服务")
            assert json.loads(page.evaluate("localStorage.getItem('tc.settings')"))["runtime"] == "auto"

            page = browser.new_context(viewport={"width": 1280, "height": 860}).new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{locked.server_address[1]}/#token=t0ken")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert "token" not in page.url
            assert json.loads(page.evaluate("localStorage.getItem('tc.settings')"))["serverToken"] == "t0ken"
            page = browser.new_context(viewport={"width": 1280, "height": 860}).new_page()
            page.goto(f"http://127.0.0.1:{locked.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.bad", timeout=30000)
            assert "访问令牌" in page.inner_text(".hero .status")
            assert not errors, errors
            browser.close()
    finally:
        for s in (api, locked, pages):
            s.shutdown()
            s.server_close()


def test_an_api_set_by_hand(tmp_path):
    """设置 → 模型 → 自定义 API: any OpenAI-compatible endpoint with its own address, model, key and headers."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockProvider

    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    mock = MockProvider().start()
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            page = browser.new_context(viewport={"width": 1280, "height": 860}).new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.click("#model-chip")
            page.click(".provider-opt.add")
            page.fill(".custom-api input[type=text] >> nth=0", "我的网关")
            page.fill(".custom-api input[type=url]", mock.base_url)
            page.fill(".custom-api input[placeholder^='服务要求的模型名']", "my-model")
            tile = page.inner_text(".provider-opt.on")
            assert "我的网关" in tile and "my-model" in tile, tile  # the tile follows the form as it is filled
            page.click(".custom-api details summary")
            page.fill(".custom-api textarea >> nth=0", '{"X-Gateway": "tc-test"}')
            page.fill(".custom-api textarea >> nth=1", "{not json")
            assert "JSON 有误" in page.inner_text(".custom-api")  # a malformed field is shown, not taken
            page.fill(".custom-api textarea >> nth=1", '{"top_k": 20}')
            page.fill(".settings-pane input[type=password]", "sk-custom")
            page.click(".modal-foot .btn:not(.secondary)")
            assert "my-model（我的网关）" in page.get_attribute("#model-chip", "title")
            page.fill("#input", "桂枝汤主治什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            req = mock.requests[0]
            assert req["path"] == "/v1/chat/completions" and req["body"]["model"] == "my-model" and req["body"]["top_k"] == 20
            assert req["headers"]["Authorization"] == "Bearer sk-custom" and req["headers"]["X-Gateway"] == "tc-test"
            assert "my-model" not in req["body"]["messages"][0]["content"]  # the instructions name no model, the visitor's own included
            saved = json.loads(page.evaluate("localStorage.getItem('tc.settings')"))
            assert saved["provider"].startswith("custom-") and saved["customProviders"][0]["headers"] == {"X-Gateway": "tc-test"}
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        mock.shutdown()


def test_the_default_service_asks_nothing_and_records_only_with_consent(tmp_path):
    """道乃久默认服务 (the site's relay, site.json): a visitor asks at once, without a key; the page sends none; a turn is
    recorded only after the visitor agreed — never with a key or the settings — and no more once they say no; a relay
    slow to answer, or missed once, is still found; with the relay down the page asks for a key as before."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockProvider, MockRelay

    mock = MockProvider().start()
    relay = MockRelay(mock.base_url).start()
    web = tmp_path / "web"
    shutil.copytree(ROOT / "web", web)
    (web / "site.json").write_text(json.dumps({"relay": relay.url}), encoding="utf-8")
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def records(n, wait=25.0):
        end = time.time() + wait
        while len(relay.records) < n and time.time() < end:
            time.sleep(0.2)
        return relay.records

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")

            def visit(down=False, missed_once=False):
                ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                if down:
                    page.route("**/v1/health", lambda route: route.abort())
                if missed_once:
                    missed: list[int] = []
                    page.route("**/v1/health", lambda route: (missed.append(1), route.abort()) if not missed else route.continue_())
                page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
                return ctx, page, errors

            def ask(page, text, answers):
                page.fill("#input", text)
                page.keyboard.press("Enter")
                if page.query_selector("#consent[open]") is None:
                    page.wait_for_function(f"document.querySelectorAll('.msg.assistant .verify-bar').length >= {answers}", timeout=60000)

            # a first visit, nothing set: the default service; asked once; agreed → the turn is recorded
            ctx, page, errors = visit()
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=10000)
            assert "道乃久默认服务" in page.get_attribute("#model-chip", "title")
            page.fill("#input", "桂枝汤主治什么？请给出原文。")
            page.keyboard.press("Enter")
            page.wait_for_selector("#consent[open]", timeout=10000)
            notice = page.inner_text("#consent")
            assert "研究院（IMPF-AI）的服务器" in notice and "不记录 API Key" in notice and "GitHub" not in notice
            page.click("#consent .btn:not(.secondary)")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            rec = records(1)[0]
            assert rec["v"] == 1 and rec["question"] == "桂枝汤主治什么？请给出原文。" and rec["turn"] == 1
            assert "桂枝汤" in rec["answer"] and rec["status"] == "done" and rec["provider"] == "impf" and rec["model"] == "MiniMax-M3"
            assert rec["tools"] and rec["tools"][0]["name"].startswith("classics") and rec["tools"][0]["ok"]
            assert rec["citations"]["total"] == 4 and rec["citations"]["bad"] == 1 and rec["citations"]["pending"] == 0
            assert rec["usage"] == {"input": 1200, "output": 180} and rec["rounds"] == 2
            assert not {"apiKey", "keys", "settings"} & set(rec) and MockRelay.SECRET not in json.dumps(rec)
            assert relay.chat and all("authorization" not in {k.lower() for k in c["headers"]} for c in relay.chat)  # no key from the page
            assert all(r["headers"].get("Authorization") == f"Bearer {MockRelay.SECRET}" for r in mock.requests)
            assert relay.chat[0]["body"]["model"] == "MiniMax-M3"
            assert relay.chat[0]["body"]["max_completion_tokens"] == 8192  # within the relay's ceiling: forwarded unchanged
            assert relay.record_types[0].startswith("text/plain")  # a simple request: no preflight
            # the choice is kept: a follow-up asks nothing and is recorded as the conversation's second turn
            ask(page, "它的剂量出自哪里？", 2)
            assert page.query_selector("#consent[open]") is None
            second = records(2)[1]
            assert second["turn"] == 2 and second["conversation"] == rec["conversation"]
            # 设置 → 数据: the switch shows the choice and changes it at once
            page.click("#settings-btn")
            page.click("nav.settings-nav button:has-text('数据')")
            box = page.locator(".settings-pane input[type=checkbox]").first
            assert box.is_checked()
            box.uncheck()
            page.keyboard.press("Escape")
            ask(page, "再问一次。", 3)
            time.sleep(2)
            assert len(relay.records) == 2
            assert not errors, errors
            ctx.close()

            # another visitor says no: answered, never recorded
            ctx, page, errors = visit()
            page.fill("#input", "消渴是什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector("#consent[open]", timeout=10000)
            page.click("#consent .btn.secondary")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            time.sleep(2)
            assert len(relay.records) == 2
            assert not errors, errors
            ctx.close()

            # a relay slow to answer (the page loading its runtime shares the link), or missed once: still found
            relay.health_delay = 6.0
            ctx, page, errors = visit()
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=20000)
            relay.health_delay = 0.0
            ctx.close()
            ctx, page, errors = visit(missed_once=True)
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=20000)
            assert not errors, errors
            ctx.close()

            # the relay down: the page asks for a key, as it did before there was one
            ctx, page, errors = visit(down=True)
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('配置底层模型')", timeout=15000)
            assert "未配置" in page.inner_text("#model-chip")
            assert not errors, errors
            ctx.close()
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        relay.shutdown()
        mock.shutdown()


def test_a_question_about_the_assistant_gets_the_fixed_reply(tmp_path):
    """Asked who it is, who made it or what model it runs on, the page answers itself (web/js/fixed.js): the same words
    every time, no model called and no key needed; with consent the turn is recorded as the page's.  The next question
    goes to the model with that reply in its history, and so does one that asks more than who answers."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockProvider, MockRelay

    mock = MockProvider().start()
    relay = MockRelay(mock.base_url).start()
    web = tmp_path / "web"
    shutil.copytree(ROOT / "web", web)
    (web / "site.json").write_text(json.dumps({"relay": relay.url}), encoding="utf-8")
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    consent = {"v": 1, "logs": True, "at": "2026-09-29T00:00:00Z"}
    welcome = "欢迎您使用道乃久（TaoChronos）中医古籍科学知识发现智能体平台，本平台由医哲未来人工智能研究院（IMPF-AI）研发。"
    question = "你是谁，谁发布的，你真实模型是什么"

    def records(n, wait=25.0):
        end = time.time() + wait
        while len(relay.records) < n and time.time() < end:
            time.sleep(0.2)
        return relay.records

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")

            def visit(down=False):
                ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
                ctx.add_init_script(f"localStorage.setItem('tc.consent', {json.dumps(json.dumps(consent))});")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                if down:
                    page.route("**/v1/health", lambda route: route.abort())
                page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
                return ctx, page, errors

            def answers(page, n):
                page.wait_for_function(f"document.querySelectorAll('.msg.assistant .actions').length >= {n}", timeout=60000)
                return page.eval_on_selector_all(".msg.assistant .md", "els => els.map(e => e.innerText)")

            # on the default service: the page's own words, no model asked, recorded as the page's
            ctx, page, errors = visit()
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=10000)
            page.fill("#input", question)
            page.keyboard.press("Enter")
            reply = answers(page, 1)[0]
            assert reply.startswith(welcome) and "检索与细读原文" in reply and "模型" not in reply
            assert page.inner_text(".msg.assistant .meta") == "Tao-R1" and page.query_selector(".msg.assistant .think") is None
            assert not relay.chat and not mock.requests
            rec = records(1)[0]
            assert rec["question"] == question and rec["answer"].startswith(welcome) and rec["status"] == "done"
            assert rec["provider"] == "fixed" and "model" not in rec and rec["rounds"] == 0 and rec["tools"] == []
            # the next question goes to the model, the reply in its history as the assistant's own; the instructions name no model
            page.fill("#input", "桂枝汤主治什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            sent = relay.chat[0]["body"]["messages"]
            assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
            assert sent[1]["content"] == question and sent[2]["content"].startswith(welcome)
            assert "MiniMax" not in sent[0]["content"] and "底层语言模型：" not in sent[0]["content"]
            # a question that asks more than who answers is the model's
            asked = len(relay.chat)
            page.fill("#input", "你是谁？张仲景是谁？")
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelectorAll('.msg.assistant .verify-bar').length >= 2", timeout=60000)
            assert len(relay.chat) > asked and records(3)[2]["provider"] == "impf"
            assert not errors, errors
            ctx.close()

            # no service and no key of the visitor's: still answered, and again the same when asked to answer again
            ctx, page, errors = visit(down=True)
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('配置底层模型')", timeout=15000)
            asked, recorded = len(relay.chat), len(relay.records)
            page.fill("#input", "请介绍一下你自己")
            page.keyboard.press("Enter")
            assert answers(page, 1)[0].startswith(welcome)
            assert page.query_selector("#settings[open]") is None  # no key asked for
            before = page.get_attribute(".msg.assistant", "data-id")
            page.click(".msg.assistant [aria-label='重新生成']")
            page.wait_for_function(f"document.querySelector('.msg.assistant .actions')?.closest('.msg').dataset.id !== {json.dumps(before)}",
                                   timeout=10000)
            assert answers(page, 1) == [page.inner_text(".msg.assistant .md")] and answers(page, 1)[0].startswith(welcome)
            assert len(relay.chat) == asked and len(relay.records) == recorded  # no model; nothing recorded without the service
            assert not errors, errors
            ctx.close()
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        relay.shutdown()
        mock.shutdown()


@pytest.mark.skipif(not os.environ.get("TAOCHRONOS_PYODIDE_E2E"), reason="set TAOCHRONOS_PYODIDE_E2E=1: builds the site with Pyodide")
def test_the_published_site_runs_on_the_canon_corpus_in_the_browser(tmp_path):
    """The built site in Chromium, on an http:// origin like the published one (no Cache API there): Pyodide starts, the
    要籍语料 is downloaded and indexed — the first-ranked works before the runtime answers, the rest in the background —
    and kept in IndexedDB, so that a reload has nothing to download or index; a turn cites it."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    import functools
    import time
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from playwright.sync_api import sync_playwright

    from taochronos.chat.build import build_site
    from web_mock import MockProvider

    build_site(tmp_path / "site", home=ROOT)

    class Static(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript", ".js": "text/javascript",
                          ".wasm": "application/wasm"}

        def log_message(self, *args) -> None:
            pass

    site = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Static, directory=str(tmp_path / "site")))
    threading.Thread(target=site.serve_forever, daemon=True).start()
    mock = MockProvider().start()
    settings = {"provider": "custom-e2e", "customProviders": [{"id": "custom-e2e", "label": "测试网关", "format": "openai",
                "base_url": mock.base_url, "model": "test-model"}], "keys": {"custom-e2e": "k"}, "route": "direct", "runtime": "browser"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**({"executable_path": exe} if exe else {}),
                                        args=["--host-resolver-rules=MAP taochronos.test 127.0.0.1"])
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            ctx.add_init_script(f"localStorage.setItem('tc.settings', {json.dumps(json.dumps(settings))});")
            page = ctx.new_page()
            fetched = []
            page.on("request", lambda r: fetched.append(r.url))
            page.goto(f"http://taochronos.test:{site.server_address[1]}/")
            assert page.evaluate("() => !window.isSecureContext && typeof caches === 'undefined'")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=240000)
            assert "要籍语料" in page.inner_text(".runtime-pill")
            page.wait_for_function("() => document.querySelector('.runtime-pill').innerText.includes('其余要籍检索索引')", timeout=60000)
            page.wait_for_function("() => !document.querySelector('.runtime-pill').innerText.includes('其余要籍检索索引')", timeout=240000)
            time.sleep(3)  # the indexed store is written to IndexedDB
            fetched.clear()
            t0 = time.time()
            page.reload()  # the indexed store is kept: no download, no indexing
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=120000)
            assert time.time() - t0 < 30
            assert not [u for u in fetched if "corpus.sqlite" in u]
            page.fill("#input", "桂枝汤主治什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=120000)
            browser.close()
    finally:
        site.shutdown()
        mock.shutdown()
