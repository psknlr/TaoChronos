"""The web client (web/): its pure logic under Node, and the whole page in Chromium against a scripted provider.

Both are skipped where Node or a Playwright Chromium is not available (the CI image has neither by default).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NODE_TEST = r"""
import assert from "node:assert/strict";
import { Accum, splitThink } from "./js/llm/openai.js";
import { answerDangling, buildHistory } from "./js/agent.js";
import { extractCitations } from "./js/markdown.js";

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
    settings = {"provider": "minimax", "baseUrls": {"minimax": mock.base_url}, "keys": {"minimax": "test-key"}, "route": "direct"}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.settings', {json.dumps(json.dumps(settings))});")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.fill("#input", "桂枝汤主治什么？请给出原文。")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            cites = page.eval_on_selector_all(".md .cite", "els => els.map(e => [e.dataset.pid, e.className])")
            assert cites == [["shanghanlun.c013", "cite ok"], ["shanghanlun.c012", "cite warn"], ["fake.999", "cite bad"],
                             ["shanghanlun.c013", "cite ok"]]  # the last quoted in the traditional script
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
            assert first["max_completion_tokens"] and first["reasoning_split"] is True and first["tools"]
            assert first["messages"][0]["role"] == "system" and "[[passage_id]]" in first["messages"][0]["content"]
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
