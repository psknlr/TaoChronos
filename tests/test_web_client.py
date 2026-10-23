"""The web client (web/): its pure logic under Node, and the whole page in Chromium against a scripted provider.

Both are skipped where Node or a Playwright Chromium is not available (the CI image has neither by default).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NODE_TEST = r"""
import assert from "node:assert/strict";
import { Accum, ProviderError, splitThink, streamChat } from "./js/llm/openai.js";
import { loadSettings, outputLimit, publicConversation, publicError } from "./js/providers.js";
import { answerDangling, budgetNote, buildHistory, lessThinking, retryWait, runTurn, userText, withoutReasoning } from "./js/agent.js";
import { brief, dataNote, deidLabel, isMine, personal, sizeLabel } from "./js/mydata.js";
import { extractCitations } from "./js/markdown.js";
import { count, hitNotes, withFound } from "./js/util.js";
import { fixedReply, IDENTITY_REPLY, isIdentityQuestion, touchesIdentity } from "./js/fixed.js";
import { ServerRuntime } from "./js/runtime.js";
import { redact, scrub, toolWord } from "./js/redact.js";
import { boxRows, captionText, chartsOf, clipText, commonTitle, documentOf, fmt, fmtEst, forestDomain, invalid, logTicks, niceMax, normalize, seriesColors, stemGaps, textWidth, ticks, timelineLanes, toCSV, toMarkdown, tukey } from "./js/chart.js";
import { crc32, packBits, pngWithDpi, tiff, unpackBits, zip } from "./js/bytes.js";
import { documentXML, headRows, invalidTable, runs, tablesOf, tex, toCSV as tableCSV, toLaTeX, toMarkdown as tableMarkdown } from "./js/table.js";

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

// the self-check (自查): an answer citing passages the corpus has not is asked again, once, with them named — while the
// turn has rounds of tools left, the whole of it when it was written on; a rewrite that fails, is stopped or is cut short
// is taken out of the turn, and the answer stands
{
  const { reviewNote, runTurn } = await import("./js/agent.js");
  const { rawAnswer } = await import("./js/view/thread.js");
  // an answer the self-check had rewritten is not the turn's: neither replayed to another provider nor read
  const rewritten = { role: "assistant", segments: [{ type: "text", text: "初稿[[x.1]]", superseded: true },
    { type: "check", missing: ["x.1"] }, { type: "text", text: "重写" }] };
  assert.deepEqual(buildHistory([{ role: "user", text: "问" }, rewritten], { id: "anthropic", format: "anthropic" }),
    [{ role: "user", content: "问" }, { role: "assistant", content: "重写" }]);
  assert.equal(rawAnswer(rewritten), "重写");
  const model = { id: "deepseek", format: "openai", baseUrl: "https://model.example/v1", model: "m", apiKey: "k" };
  let replies = [];
  const bodies = [];
  globalThis.fetch = async (url, init) => {
    bodies.push(JSON.parse(init.body));
    const next = replies.shift();
    if (typeof next === "function") return next();
    const [status, content, finish = "stop"] = next;
    const body = status === 200 ? { choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: finish }] }
      : { error: { message: content } };
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  };
  const turn = (answers, missing, { settings = {}, signal = new AbortController().signal, hurry, limits } = {}) => {
    replies = answers;
    bodies.length = 0;
    const seen = [], reviewed = [], sink = [];
    const review = async (text) => { reviewed.push(text); return missing(text); };
    const hooks = { review: (m) => seen.push(["review", m]), reviewCut: (err) => seen.push(["cut", err ? err.message : null]) };
    const done = runTurn({ provider: model, settings, route: { kind: "direct" }, runtime: {}, tools: [], system: "s", history: [],
      user: { text: "问" }, signal, hurry, limits, hooks, sink, review });
    return { done, seen, reviewed, sink };
  };
  const cited = (text) => (text.includes("[[x.1]]") ? ["x.1"] : []);
  const said = (wire) => wire.map((m) => `${m.role}:${m.content}`);
  // named, asked again, and the rewrite stands — itself not checked again
  let t = turn([[200, "甲[[x.1]]"], [200, "乙"]], cited);
  let r = await t.done;
  assert.deepEqual(said(r.wire), ["assistant:甲[[x.1]]", `user:${reviewNote(["x.1"])}`, "assistant:乙"]);
  assert.equal(r.wire, t.sink);
  assert.deepEqual(t.reviewed, ["甲[[x.1]]"]);
  assert.deepEqual(t.seen, [["review", ["x.1"]]]);
  assert.equal(bodies[1].messages.at(-1).content, reviewNote(["x.1"]));
  assert.ok(reviewNote(["x.1"]).startsWith("［自查：回答所引的 [[x.1]] 在语料中查无此段。"));
  assert.ok(reviewNote(["x.1", "y.2"]).includes("[[x.1]]、[[y.2]]"));
  // nothing missing: the answer stands as it came
  t = turn([[200, "甲[[x.1]]"]], () => []);
  assert.deepEqual(said((await t.done).wire), ["assistant:甲[[x.1]]"]);
  assert.deepEqual(t.seen, []);
  // too few rounds of tools left to look anything up: not asked
  t = turn([[200, "甲[[x.1]]"]], cited, { settings: { maxSteps: 2 } });
  assert.deepEqual(said((await t.done).wire), ["assistant:甲[[x.1]]"]);
  assert.deepEqual(t.reviewed, []);
  // the rewrite fails: the turn ends with the answer it was about, and says why
  t = turn([[200, "甲[[x.1]]"], [400, "invalid params"]], cited);
  assert.deepEqual(said((await t.done).wire), ["assistant:甲[[x.1]]"]);
  assert.deepEqual(t.seen, [["review", ["x.1"]], ["cut", "模型服务返回 400：invalid params"]]);
  // an answer cut at the output limit and written on is checked whole — the round that wrote it on spends none of the
  // rounds the self-check needs
  t = turn([[200, "甲[[x", "length"], [200, ".1]]乙"], [200, "丙"]], cited, { settings: { maxSteps: 3 } });
  r = await t.done;
  assert.deepEqual(t.reviewed, ["甲[[x.1]]乙"]);
  assert.deepEqual([t.seen, said(r.wire).at(-2), said(r.wire).at(-1)], [[["review", ["x.1"]]], `user:${reviewNote(["x.1"])}`, "assistant:丙"]);
  // a rewrite cut at the output limit past what can be written on: taken out, and the answer it was about stands
  t = turn([[200, "甲[[x.1]]"], [200, "乙", "length"], [200, "乙", "length"], [200, "乙", "length"]], cited);
  assert.deepEqual(said((await t.done).wire), ["assistant:甲[[x.1]]"]);
  assert.deepEqual(t.seen, [["review", ["x.1"]], ["cut", null]]);
  // the user asked for the answer (or the turn ran its time): nothing is asked — the model could look nothing up
  const hurried = new AbortController();
  hurried.abort();
  t = turn([[200, "甲[[x.1]]"]], cited, { hurry: hurried.signal });
  assert.deepEqual([said((await t.done).wire), t.reviewed], [["assistant:甲[[x.1]]"], []]);
  // lookups that do not come back: waited for no longer than a tool call, and the answer stands as it is
  t = turn([[200, "甲[[x.1]]"]], () => new Promise(() => {}), { limits: { tool: 150 } });
  assert.deepEqual([said((await t.done).wire), t.reviewed, t.seen], [["assistant:甲[[x.1]]"], ["甲[[x.1]]"], []]);
  // stopped during the rewrite: stopped, with the answer it was about
  const stop = new AbortController();
  t = turn([[200, "甲[[x.1]]"], () => { stop.abort(); throw new DOMException("aborted", "AbortError"); }], cited, { signal: stop.signal });
  await assert.rejects(t.done, (e) => e.name === "AbortError");
  assert.deepEqual(said(t.sink), ["assistant:甲[[x.1]]"]);
  assert.deepEqual(t.seen, [["review", ["x.1"]], ["cut", null]]);
}

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
// a question that touches who answers, even in passing, is answered without thinking; the rest are not
for (const q of ["你是谁？张仲景是谁？", "你是什么模型？帮我查一下桂枝汤", "你是谁"]) assert.ok(touchesIdentity(q), q);
for (const q of ["张仲景是谁", "桂枝汤主治什么？", "《伤寒论》是谁写的？"]) assert.ok(!touchesIdentity(q), q);
assert.deepEqual(withoutReasoning([
  { role: "assistant", content: "<think>想</think>答", reasoning_details: [{ text: "想" }], reasoning_content: "想" },
  { role: "assistant", content: [{ type: "thinking", thinking: "想", signature: "s" }, { type: "text", text: "答" }] },
  { role: "tool", tool_call_id: "c", content: "<think>工具结果原样</think>" }]), [
  { role: "assistant", content: "答" },
  { role: "assistant", content: [{ type: "text", text: "答" }] },
  { role: "tool", tool_call_id: "c", content: "<think>工具结果原样</think>" }]);

// the site's own server (chat.impf.ai, the full corpus on Cloudflare): when it cannot answer, the page carries on in the
// browser — once, for everything after; an error the server reports is the tool's, and a server the user chose has no stand-in
globalThis.location = { protocol: "https:", hostname: "chat.impf.ai", href: "https://chat.impf.ai/" };
const answers = { "/api/call": [503, { error: "全量语料服务正在启动或暂不可用，请稍后再试", starting: true }], "/api/passage": [404, { error: "no such passage" }] };
globalThis.fetch = async (url) => {
  const [status, body] = answers[new URL(url).pathname] || [200, { name: "TaoChronos" }];
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
};
let fell = 0;
const inBrowser = { call: async (name) => ({ ok: true, tool: name, from: "browser" }), passage: async (id) => ({ ok: true, passage_id: id, from: "browser" }) };
const site = new ServerRuntime("https://chat.impf.ai/", "", { label: "本站服务", fallback: (err) => { fell++; assert.ok(err.unavailable); return inBrowser; } });
assert.equal(site.label, "本站服务");
assert.deepEqual(await site.call("classics.search", { query: "桂枝汤" }), { ok: true, tool: "classics.search", from: "browser" });
answers["/api/call"] = [200, { ok: true, from: "server" }];
assert.equal((await site.call("classics.search", {})).from, "browser");
assert.equal((await site.passage("a.1")).from, "browser");
assert.equal(fell, 1);
const up = new ServerRuntime("https://chat.impf.ai", "", { fallback: () => { throw new Error("not unavailable"); } });
assert.equal((await up.call("classics.search", {})).from, "server");
await assert.rejects(up.passage("zz.1"), /no such passage/);
answers["/api/call"] = [503, { error: "down" }];
await assert.rejects(new ServerRuntime("https://example.org").call("x", {}), (e) => e.unavailable === true && /down/.test(e.message));
assert.equal(new ServerRuntime("http://localhost:8765").label, "本地服务");
// a refusal by the site's own server (403 for an address it restricts, 429 for the day spent) is told as one: the page
// carries on in the browser and knows why; a minute's 429, or a 403 of another server, is the call's own error
const refusing = (status, body) => {
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-TC-Corpus": "refused" } });
};
for (const [status, body, why] of [[403, { error: "该地址因异常访问已被暂时限制，请稍后再试", blocked: true }, "blocked"],
  [429, { error: "今天的查询次数已用完，明天再来", rate_limited: true, daily: true }, "daily"]]) {
  refusing(status, body);
  let reason = null;
  const refused = new ServerRuntime("https://chat.impf.ai", "", { fallback: (err) => { reason = err.refused; return inBrowser; } });
  assert.equal((await refused.call("classics.search", {})).from, "browser");
  assert.equal(reason, why);
  await assert.rejects(new ServerRuntime("https://chat.impf.ai").call("x", {}), (e) => !e.unavailable && !e.refused); // a server the user chose: no stand-in
}
refusing(429, { error: "请求太频繁，请稍候再试", rate_limited: true });
await assert.rejects(new ServerRuntime("https://chat.impf.ai", "", { fallback: () => inBrowser }).call("x", {}), (e) => !e.unavailable && /太频繁/.test(e.message));

// the default service reaches the visitor in its own words: an error it passed on from the model behind it is a plain
// failure; its own messages come without the model client's preamble; another provider's errors come as they are
const relayP = { id: "impf", relay: true, baseUrl: "https://relay.example/v1", model: "Tao-R1", extra_body: {},
  max_tokens_param: "max_completion_tokens", thinking_off: { thinking: { type: "disabled" } }, reasoning: "reasoning_details" };
const FAILED = "默认服务出错了，请稍后再试，或在“设置 → 模型”里填入自己的 API Key";
let sent = null;
const reply = (status, body, type = "application/json") => {
  globalThis.fetch = async (url, init) => { sent = JSON.parse(init.body); return new Response(body, { status, headers: { "Content-Type": type } }); };
};
reply(400, JSON.stringify({ error: { message: "invalid params: temperature (MiniMax-M3)" }, base_resp: { status_code: 2013 } }));
await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: { thinking: false } }),
  (e) => e.message === FAILED && e.body === "");
assert.deepEqual(sent.thinking, { type: "disabled" }); // no thinking asked for, in the service's own field
assert.equal(sent.reasoning_split, undefined); // the relay adds what the model behind it needs
reply(429, JSON.stringify({ error: { message: "今天的免费额度已用完，明天再来", type: "daily_limit" } }));
await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: {} }), (e) => e.message === "今天的免费额度已用完，明天再来");
reply(200, 'data: {"error":{"message":"output new_sensitive (MiniMax)"}}\n\n', "text/event-stream");
await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: {} }), (e) => e.message === FAILED);
reply(400, JSON.stringify({ error: { message: "invalid params" } }));
await assert.rejects(streamChat({ provider: { ...relayP, id: "deepseek", relay: false, thinking_off: null }, messages: [], tools: [],
  settings: { thinking: false } }), (e) => e.message === "模型服务返回 400：invalid params");
assert.equal(sent.thinking, undefined);

// a reply that breaks off while it streams (Chrome's "network error", Safari's "Load failed") is asked again from the
// start of its round: what it had shown goes; a browser with no body to read a reply from as it arrives reads it whole
const enc = new TextEncoder();
const sse = (text) => new ReadableStream({ start(c) { c.enqueue(enc.encode(text)); c.close(); } });
const brokenOff = (text) => new ReadableStream({ start(c) { c.enqueue(enc.encode(text)); }, pull(c) { c.error(new TypeError("network error")); } });
const delta = (content, finish = null) => `data: ${JSON.stringify({ choices: [{ delta: { content }, finish_reason: finish }] })}\n\n`;
const streamed = (body) => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
globalThis.fetch = async () => streamed(brokenOff(delta("桂枝")));
await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: {} }),
  (e) => e instanceof ProviderError && e.retryable && e.message === "连接在回复途中断开（network error）");
globalThis.fetch = async () => ({ ok: true, status: 200, headers: new Headers({ "Content-Type": "text/event-stream" }), body: undefined,
  text: async () => delta("桂枝汤") + delta("主之", "stop") + "data: [DONE]\n\n" });
assert.equal((await streamChat({ provider: relayP, messages: [], tools: [], settings: {} })).text, "桂枝汤主之");
let attempts = 0;
globalThis.fetch = async () => streamed(++attempts === 1 ? brokenOff(delta("半")) : sse(delta("答", "stop") + "data: [DONE]\n\n"));
const seen = [];
const resumed = await runTurn({ provider: relayP, settings: {}, route: null, runtime: null, tools: [], system: "s", history: [],
  user: { text: "问" }, signal: new AbortController().signal, hooks: { retry: (n) => seen.push(n), text: (t) => seen.push(t) } });
assert.deepEqual([seen, resumed.wire.at(-1).content, attempts], [["半", 1, "答"], "答", 2]);
// a refusal that asking again soon does not change is told at once (the day's allowance, the service's); one that asks
// to wait is waited for as long as it asks, up to half a minute
for (const [status, kind] of [[429, "daily_limit"], [429, "total_limit"], [503, "not_configured"]]) {
  reply(status, JSON.stringify({ error: { message: "今天的免费额度已用完，明天再来", type: kind } }));
  await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: {} }), (e) => !e.retryable && e.kind === kind);
}
reply(503, JSON.stringify({ error: { message: "默认服务暂时连不上模型服务", type: "upstream_unreachable" } }));
await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: {} }), (e) => e.retryable && e.retryAfter === null);
globalThis.fetch = async () => new Response(JSON.stringify({ error: { message: "请求太频繁：每分钟最多 10 次，请 12 秒后再试", type: "rate_limited" } }),
  { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "12" } });
await assert.rejects(streamChat({ provider: relayP, messages: [], tools: [], settings: {} }),
  (e) => e.retryable && e.retryAfter === 12 && e.kind === "rate_limited" && /每分钟最多 10 次/.test(e.message));
const even = () => 0.5;
assert.deepEqual([0, 1, 2, 3].map((n) => retryWait({ retryable: true }, n, even)), [1500, 4000, 10000, null]);
assert.deepEqual([retryWait({ retryable: false }, 0, even), retryWait({ retryable: true, retryAfter: 12 }, 0, even),
  retryWait({ retryable: true, retryAfter: 60 }, 0, even)], [null, 12000, null]);
// pages a failure struck together do not ask again together: a wait is spread over a quarter either way, never below
// what the service asks
assert.deepEqual([retryWait({ retryable: true }, 1, () => 0), retryWait({ retryable: true }, 1, () => 0.999999)], [3000, 5000]);
assert.equal(retryWait({ retryable: true, retryAfter: 4 }, 1, () => 0), 4000);
// a stop while the turn waits to ask again (or as it begins to) ends the turn there, not asked again
for (const after of [30, 0]) {
  let asked = 0;
  const stop = new AbortController();
  globalThis.fetch = async () => (asked++, new Response(JSON.stringify({ error: { message: "请求太频繁", type: "rate_limited" } }),
    { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "20" } }));
  const from = Date.now();
  await assert.rejects(runTurn({ provider: relayP, settings: {}, route: null, runtime: null, tools: [], system: "s", history: [],
    user: { text: "问" }, signal: stop.signal, hooks: { retry: () => (after ? setTimeout(() => stop.abort(), after) : stop.abort()) } }),
  (e) => e.name === "AbortError");
  assert.ok(asked === 1 && Date.now() - from < 5000, `${after}: asked ${asked} times, ${Date.now() - from} ms`);
}

// the last rounds of tools a turn may run are named to the model with what it has left, and the last that it is to answer
assert.deepEqual([3, 2, 1, 0, -1].map((n) => budgetNote(n) !== ""), [false, true, true, true, false]);
const askedFor = [];
globalThis.fetch = async (url, init) => {
  askedFor.push(JSON.parse(init.body).messages);
  const call = { index: 0, id: `c${askedFor.length}`, function: { name: "classics__search", arguments: '{"query":"桂枝汤"}' } };
  return streamed(sse(`data: ${JSON.stringify({ choices: [{ delta: { tool_calls: [call] }, finish_reason: "tool_calls" }] })}\n\ndata: [DONE]\n\n`));
};
const stoppedAt = [];
await runTurn({ provider: relayP, settings: { maxSteps: 2 }, route: null, runtime: { call: async () => ({ ok: true, text: "{}" }) }, tools: [],
  system: "s", history: [], user: { text: "问" }, signal: new AbortController().signal, hooks: { limit: (n) => stoppedAt.push(n) } });
const budgetTold = askedFor.slice(1).map((m) => m.filter((x) => x.role === "tool").at(-1).content);
assert.deepEqual(budgetTold, ["{}\n\n［提示：回答这个问题还可再调用 1 轮工具，请在用完之前作答］",
  "{}\n\n［提示：回答这个问题的工具调用已用完，请根据已有结果直接作答，不要再调用工具］", "ERROR: 已达到本轮工具调用的上限：请根据已有结果直接作答。"]);
assert.deepEqual(stoppedAt, [2]);

// a reply is complete when the service says so: a stream that ends with neither a finish_reason nor [DONE] broke off
// and is asked again; either one is enough, streamed or read whole
const readWhole = (text) => async () => ({ ok: true, status: 200, headers: new Headers({ "Content-Type": "text/event-stream" }),
  body: undefined, text: async () => text });
for (const [fetcher, complete] of [[() => streamed(sse(delta("桂枝"))), false], [readWhole(delta("桂枝")), false],
  [() => streamed(sse(delta("桂枝") + "data: [DONE]\n\n")), true], [() => streamed(sse(delta("桂枝", "stop"))), true],
  [readWhole(delta("桂枝") + "data: [DONE]"), true], [readWhole(delta("桂枝", "stop")), true]]) {
  globalThis.fetch = fetcher;
  const asking = streamChat({ provider: relayP, messages: [], tools: [], settings: {} });
  if (complete) assert.equal((await asking).text, "桂枝");
  else await assert.rejects(asking, (e) => e instanceof ProviderError && e.retryable && e.message === "回复没有完整到达：连接在模型说完之前就结束了");
}
globalThis.fetch = async () => streamed(sse(delta("桂", "insufficient_system_resource") + "data: [DONE]\n\n")); // DeepSeek's servers
await assert.rejects(streamChat({ provider: { ...relayP, relay: false }, messages: [], tools: [], settings: {} }),
  (e) => e.retryable && e.message === "模型服务资源不足，回复中途停止");

// what a reply may use: the visitor's number within the service's own ceiling; with none, that ceiling, or a default
// (Claude's larger, as Anthropic advises for a streamed reply; an endpoint set by hand keeps the general one)
assert.deepEqual([outputLimit({}, { max_output: 32768 }), outputLimit({ maxTokens: 50000 }, { max_output: 32768 }),
  outputLimit({ maxTokens: 4096 }, { max_output: 32768 }), outputLimit({}, { format: "anthropic" }),
  outputLimit({ maxTokens: "8000" }, { format: "anthropic" }), outputLimit({}, { format: "anthropic", custom: true }),
  outputLimit({ maxTokens: null }, { format: "openai" })], [32768, 32768, 4096, 64000, 8000, 16000, 16000]);
reply(200, delta("答", "stop"), "text/event-stream");
await streamChat({ provider: relayP, messages: [], tools: [], settings: { maxTokens: null } });
assert.equal(sent.max_completion_tokens, 16000);
await streamChat({ provider: { ...relayP, max_output: 32768 }, messages: [], tools: [], settings: {} });
assert.equal(sent.max_completion_tokens, 32768);
// the old default an older page kept as the visitor's own number is read as no number
const shelf = new Map();
globalThis.localStorage = { getItem: (k) => shelf.get(k) ?? null, setItem: (k, v) => shelf.set(k, String(v)), removeItem: (k) => shelf.delete(k) };
shelf.set("tc.settings", JSON.stringify({ maxTokens: 16000, thinking: false }));
assert.deepEqual([loadSettings().maxTokens, loadSettings().thinking], [null, false]);
shelf.set("tc.settings", JSON.stringify({ maxTokens: 12000 }));
assert.equal(loadSettings().maxTokens, 12000);
delete globalThis.localStorage;

// a reply cut at the output limit: an answer is written on from where it stopped — the cut answer, then the page's
// note, in the turn — and a round that writes on spends none of the turn's rounds of tools
const scripted = (...replies) => {
  const bodies = [];
  globalThis.fetch = async (url, init) => { bodies.push(JSON.parse(init.body)); return streamed(sse(replies.shift())); };
  return bodies;
};
const thought = (text, finish = null) => `data: ${JSON.stringify({ choices: [{ delta: { reasoning_details: [
  { type: "reasoning.text", id: "r1", index: 0, text }] }, finish_reason: finish }] })}\n\n`;
const calling = (args, finish) => `data: ${JSON.stringify({ choices: [{ delta: { tool_calls: [
  { index: 0, id: `c${args.length}`, function: { name: "classics__search", arguments: args } }] }, finish_reason: finish }] })}\n\n`;
const heard = [];
const listen = { continued: (w) => heard.push(`continued:${w}`), cut: (w) => heard.push(`cut:${w}`), assistant: (r) => heard.push(r.text) };
const turnWith = (provider, extra = {}) => runTurn({ provider, settings: {}, route: null, runtime: null, tools: [], system: "s",
  history: [], user: { text: "问" }, signal: new AbortController().signal, hooks: listen, ...extra });
let bodies = scripted(delta("桂枝汤主", "length"), delta("之。", "stop"));
let done = await turnWith(relayP);
assert.deepEqual(heard.splice(0), ["桂枝汤主", "continued:answer", "之。"]);
assert.deepEqual(done.wire.map((m) => [m.role, m.content.slice(0, 12)]), [["assistant", "桂枝汤主"], ["user", "［提示：上面的回答在输出"], ["assistant", "之。"]]);
assert.equal(bodies[1].messages.at(-1).content, "［提示：上面的回答在输出上限处被截断了。请从截断处接着写下去：不要重复已写的内容，不要加开场白，也不要从头再来。］");
// cut again and again: written on twice, then told
scripted(delta("一", "length"), delta("二", "length"), delta("三", "length"));
await turnWith(relayP);
assert.deepEqual(heard.splice(0), ["一", "continued:answer", "二", "continued:answer", "三", "cut:answer"]);
// all of it spent on thinking: asked again without (the service's own field), the cut reply not kept; told when that too
// only thinks, and at once where the service cannot be asked without
bodies = scripted(thought("想", "length"), delta("答", "stop"));
done = await turnWith(relayP);
assert.deepEqual(heard.splice(0), ["continued:thinking", "答"]);
assert.deepEqual([bodies[0].thinking, bodies[1].thinking, bodies[1].messages], [undefined, { type: "disabled" }, bodies[0].messages]);
assert.deepEqual(done.wire.map((m) => m.content), ["答"]);
scripted(thought("想", "length"), thought("又想", "length"));
await turnWith(relayP);
assert.deepEqual(heard.splice(0), ["continued:thinking", "", "cut:thinking"]);
scripted(thought("想", "length"));
await turnWith({ ...relayP, thinking_off: null });
assert.deepEqual(heard.splice(0), ["", "cut:thinking"]);
assert.deepEqual([lessThinking("anthropic", {}, {}), lessThinking("anthropic", {}, { effort: "low" }), lessThinking("openai", relayP, {}),
  lessThinking("openai", relayP, { thinking: false }), lessThinking("openai", { thinking_off: null }, {})],
  [{ effort: "low" }, null, { thinking: false }, null, null]); // Claude thinks less at low effort
// a call written into a cut reply never runs (its arguments may be cut too): the model is told, and the turn goes on
let ran = 0;
const runtime = { call: async () => (ran++, { ok: true, text: "{}" }) };
bodies = scripted(calling('{"query": "桂枝', "length"), delta("答", "stop"));
await turnWith(relayP, { runtime });
assert.equal(ran, 0);
assert.match(bodies[1].messages.at(-1).content, /^ERROR: 这次回复在输出上限处被截断，调用的参数可能不完整，没有执行。/);
assert.deepEqual(heard.splice(0), ["", "答"]);
// the content filter stopped it, or (Claude) it filled the model's context window: told, its calls not run, the turn over
for (const [why, told] of [["content_filter", "cut:filtered"], ["model_context_window_exceeded", "cut:context"]]) {
  bodies = scripted(delta("部分", null) + calling('{"query": "桂枝汤"}', why), delta("不该再问", "stop"));
  done = await turnWith(relayP, { runtime });
  assert.deepEqual([heard.splice(0), bodies.length, ran, done.wire.length], [["部分", told], 1, 0, 1]);
}
// a round that wrote on a cut answer is not one of the turn's rounds of tools: the next call still runs
bodies = scripted(calling('{"query": "桂枝汤"}', "tool_calls"), delta("先", "length"), calling('{"query": "麻黄汤"}', "tool_calls"),
  delta("答", "stop"));
await turnWith(relayP, { runtime, settings: { maxSteps: 2 } });
assert.equal(ran, 2);
assert.match(bodies[3].messages.at(-1).content, /^\{\}\n\n［提示：回答这个问题的工具调用已用完/);
heard.splice(0);

// conversations an older page kept: the default service's turns as it presents itself now; nothing else is touched
const kept = { messages: [
  { role: "user", text: "问" },
  { role: "assistant", provider: "impf", model: "MiniMax-M3", wireProvider: "impf", error: "模型服务返回 400：默认服务只提供 MiniMax-M3",
    wire: [{ role: "assistant", content: "答", reasoning_details: [{ type: "reasoning.text", format: "MiniMax-response-v1", text: "想" }] }] },
  { role: "assistant", provider: "impf", model: "MiniMax-M3", error: "模型服务返回 400：invalid params, temperature out of range" },
  { role: "assistant", provider: "impf", error: "模型服务返回 429（请求过于频繁或额度不足）：默认服务的模型额度暂时用完或调用过于频繁，请稍后再试，" +
    "或在“设置 → 模型”里填入自己的 API Key（rate limit exceeded（MiniMax））" },
  { role: "assistant", provider: "impf", error: "模型服务报错：output new_sensitive" },
  { role: "assistant", provider: "impf", error: "工具运行出错：timeout" },
  { role: "assistant", provider: "deepseek", model: "deepseek-chat", error: "模型服务返回 400：invalid params" },
] };
assert.equal(publicConversation(kept), true);
const [, k1, k2, k3, k4, k5, k6] = kept.messages;
assert.ok(!/MiniMax|invalid|sensitive|rate limit/.test(JSON.stringify([k1, k2, k3, k4, k5])));
assert.deepEqual([k1.model, k2.model, k1.wire[0].reasoning_details[0].format], ["Tao-R1", "Tao-R1", "Tao-response-v1"]);
assert.equal(k1.error, "默认服务不提供这个模型：请在“设置 → 模型”里选用道乃久默认服务，或改用自己的 API Key");
assert.deepEqual([k2.error, k4.error], [FAILED, FAILED]);
assert.equal(k3.error, "默认服务的模型额度暂时用完或调用过于频繁，请稍后再试，或在“设置 → 模型”里填入自己的 API Key");
assert.equal(k5.error, "工具运行出错：timeout"); // not the model service's
assert.deepEqual([k6.model, k6.error], ["deepseek-chat", "模型服务返回 400：invalid params"]); // another provider's
assert.equal(publicConversation(kept), false); // once is enough
assert.equal(publicError("无法连接道乃久默认服务：网络不通"), "无法连接道乃久默认服务：网络不通");

// what a visitor reads of the model: the names it works with inside — tools, fields, codes, commands, files — in plain
// words, wherever the model put them; a citation's mark, a link and the platform's own names stay as they are
const leaked = "用户可在本机运行 `taochronos serve`，并在平台设置中连接；并附 passage_id 以便复核；D1–D5 的多智能体研究；" +
  "用 `validation__verify_quote`、`audit__claim` 等工具核对，或 classics.search/study.formula；须经专家核验（G7）；见 docs/web.md。";
const told = scrub(leaked);
assert.equal(told.text, "用户可在本机运行本地服务，并在平台设置中连接；并附段落编号以便复核；知识发现的多智能体研究；" +
  "用引文核验、论断审计等工具核对，或古籍检索/方源考；须经专家核验；见内部文件。");
assert.equal(told.hits, 9);
assert.equal(redact(told.text), told.text); // once is enough
const plain = "「太阳病，头痛」[[shanghanlun.c013]] 见 https://chat.impf.ai/a_b?q=classics.search；道乃久（TaoChronos）· Tao-R1；" +
  "多巴胺 D2 受体、维生素 D3；ICD-10、HPO";
assert.deepEqual(scrub(plain), { text: plain, hits: 0 });
assert.equal(redact("D2 概念漂移；D4 分析；门控 G0–G8；技能 S01–S15 的图；证据审计 (S15)；设置 holdout_after 参数；STATS_TOKEN"),
  "概念漂移；关联规则与隐含关联分析；各级门控；各项技能的图；证据审计；设置相应参数；内部配置");
// the labels the tools grade with, as a reader says them (not 内部配置)
assert.equal(redact("判读证据等级（SUPPORTED / CONTESTED / INSUFFICIENT_EVIDENCE …）；证据类型 systematic_review；SOURCE_ASSERTED"),
  "判读证据等级（有据 / 有争议 / 证据不足 …）；证据类型系统综述；原文所言");
// in a code block only the names: the identifiers of the code are its own
assert.equal(redact("```py\nn_total = 1  # passage_id\nclassics__search(q)\n```"), "```py\nn_total = 1  # 段落编号\n古籍检索(q)\n```");
// while the answer streams, half a name is never shown
assert.equal(redact("先用 validation__ver", { streaming: true }), "先用 ");
assert.equal(redact("先用 validation__verify_quote 核对", { streaming: true }), "先用引文核验核对");
assert.deepEqual([toolWord("classics__search"), toolWord("study.formula"), toolWord("taochronos_research"), toolWord("study.new_one"), toolWord("…")],
  ["古籍检索", "方源考", "发现研究", "治学工具", "…"]);
assert.deepEqual([toolWord("study.compare"), toolWord("study.protocol")], ["方剂比较", "研究方案设计"]);

// charts: a model's ```chart block is checked before it is drawn, made whole, and its table is the CSV and the export
const spec = { type: "bar", title: "甘草·用量", x: { key: "时期" }, series: ["两"], rows: [{ 时期: "汉", 两: 2 }, { 时期: "宋", 两: 1.5 }] };
assert.equal(invalid(spec), null);
assert.match(invalid({ ...spec, type: "pie" }), /不支持的图表类型/);
assert.match(invalid({ ...spec, rows: [] }), /rows/);
assert.match(invalid({ type: "network", nodes: Array(401).fill({ id: "a" }) }), /网络过大/);
const whole = normalize(spec);
assert.deepEqual(whole.series, [{ key: "两", label: "两" }]);
assert.deepEqual(whole.columns.map((c) => c.key), ["时期", "两"]);
assert.equal(toCSV(whole), "\ufeff时期,两\r\n汉,2\r\n宋,1.5\r\n");
assert.equal(toCSV({ ...whole, rows: [{ 时期: "明,清", 两: 'a"b' }] }, false), '时期,两\r\n"明,清","a""b"\r\n');
assert.equal(toMarkdown(whole), "**甘草·用量**\n\n| 时期 | 两 |\n| --- | --- |\n| 汉 | 2 |\n| 宋 | 1.5 |");
assert.deepEqual(seriesColors(["甲", "其他", "乙"]), ["var(--viz-1)", "var(--viz-other)", "var(--viz-2)"]);
assert.deepEqual([niceMax(7), niceMax(11), niceMax(295), niceMax(0)], [8, 15, 300, 1]);

// a timeline's lanes as the Python figures lay them out (tests/test_figure_layout.py): no stem through a label, the
// right edge's labels turned; a stem still crossing one is broken around it; a long name cut to its room
const family = ["葛根汤", "大青龙汤", "小建中汤", "桂枝加葛根汤", "桂枝二麻黄一汤", "桂枝加桂汤", "桂枝加附子汤", "桂枝附子汤", "茯苓白术汤",
  "黄芩加半夏生姜汤", "栝楼桂枝汤", "桂枝二越婢一汤", "桂枝加黄芪汤", "桂枝去芍药加附子汤", "桂枝救逆汤", "龙骨汤", "泽兰汤", "干地黄汤",
  "栝楼汤", "生地黄汤", "芍药汤", "乌头汤", "四逆汤", "葵子汤", "青龙汤", "桂枝葛根汤", "葛根加半夏汤", "当归芍药汤", "当归四逆汤", "桂枝加芍药汤"];
const years = [...Array(16).fill(209.5), 654.5, 654.5, 654.5, 682, 752, 752, 752, 752, 752, 1180, 1398, 1652, 1685, 1732];
const lanes = timelineLanes(years.map((y) => 30 + ((y - 200) / (1740 - 200)) * (304 - 60)), family.map((f) => textWidth(f, 10.5) + 14), 304);
assert.deepEqual(lanes.lane, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 15, 16, 17, 14, 10, 12, 0, 1, 2, 0, 1, 4, 3, 2]);
assert.deepEqual(family.filter((_, i) => lanes.flip[i]), ["当归芍药汤", "当归四逆汤", "桂枝加芍药汤"]);
assert.deepEqual(stemGaps(100, 0, 100, [[90, 20, 120, 30], [0, 40, 50, 50], [95, 60, 99, 70]]), [[0, 18], [32, 58], [72, 100]]);
const cut = clipText("加味甘草汤（出《太平惠民和剂局方》卷三）", 11, 60);
assert.ok(cut.endsWith("…") && textWidth(cut, 11) <= 60 && cut.startsWith("加味甘草") && clipText("甘草", 11, 60) === "甘草");
assert.deepEqual(ticks(0, 10, 4, true), [0, 5, 10]);
assert.deepEqual(ticks(0, 1.5), [0, 0.5, 1, 1.5]);
assert.deepEqual([fmt(0.125, true), fmt(1234), fmt(2), fmt(0.4375)], ["13%", "1.2K", "2", "0.438"]);
assert.deepEqual(chartsOf({ charts: [spec, { type: "pie" }] }), [spec]);
assert.deepEqual(chartsOf(null), []);
assert.deepEqual(documentOf({ document: { name: "桂枝汤/方案", text: "# 方案" } }), { name: "桂枝汤_方案.md", format: "markdown", text: "# 方案" });
assert.equal(documentOf({ document: { name: "x.md", text: "" } }), null);

// the scientific figures: a box plot's numbers (Tukey), a forest plot's log axis, a tree checked, captions
assert.deepEqual(tukey([1, 2, 3, 4, 5, 6, 7, 8, 9, 100]), { n: 10, min: 1, q1: 3.25, median: 5.5, q3: 7.75, lo: 1, hi: 9, max: 100, mean: 14.5 });
assert.equal(boxRows({ type: "box", x: { key: "期" }, rows: [{ 期: "汉", values: [1, 2, 3] }] })[0].median, 2);
assert.match(invalid({ type: "box", x: { key: "期" }, rows: [{ 期: "汉" }] }), /箱线图需要/);
assert.equal(invalid({ type: "forest", y: { key: "药" }, estimate: { key: "or", lo: "lo", hi: "hi" }, rows: [{ 药: "甲", or: 2, lo: 1, hi: 4 }] }), null);
assert.deepEqual(forestDomain([{ or: 2, lo: 1, hi: 4 }], { key: "or", lo: "lo", hi: "hi" }, { log: true, ref: 1 }), { lo: 1 / 1.3, hi: 4 * 1.3, log: true });
assert.deepEqual([logTicks(0.05, 60), logTicks(0.8, 4)], [[0.1, 1, 10], [1, 2]]);
assert.match(invalid({ type: "dendrogram", labels: ["甲", "乙", "丙"], merges: [[0, 1, 0.5, 2]] }), /n − 1/);
assert.equal(invalid({ type: "dendrogram", labels: ["甲", "乙", "丙"], merges: [[0, 1, 0.5, 2], [2, 3, 0.9, 3]] }), null);
assert.equal(normalize({ type: "dendrogram", labels: ["甲", "乙"], merges: [[0, 1, 1, 2]] }).rows.length, 2);
assert.equal(invalid({ type: "scatter", x: { key: "年" }, rows: [{ 年: 1 }] }), "散点图需要 x.key 与 y.key");
assert.deepEqual([fmtEst(67.61), fmtEst(2.434), fmtEst(0.0873), fmtEst(0.004)], ["67.6", "2.43", "0.09", "0.004"]);
assert.equal(captionText({ title: "甘草 · 历代汤剂用量", subtitle: "箱为四分位距。" }), "甘草：历代汤剂用量。箱为四分位距。");
assert.deepEqual([commonTitle([{ title: "甘草 · 甲" }, { title: "甘草 · 乙" }]), commonTitle([{ title: "甲" }, { title: "甘草 · 乙" }])], ["甘草", ""]);

// the files written byte by byte: CRC-32 as PNG and ZIP compute it, PackBits both ways, a TIFF that says its dpi
assert.equal(crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
const row = Uint8Array.from([0, 0, 0, 0, 5, 6, 7, 7, 7, 7, 7, 1, 2]);
assert.deepEqual(unpackBits(packBits(row), row.length), row);
assert.ok(packBits(new Uint8Array(1000).fill(255)).length <= 16);
const tif = tiff({ width: 3, height: 2, data: Uint8ClampedArray.from([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 0, 1, 2, 3, 255, 4, 5, 6, 255, 7, 8, 9, 255]) }, 300);
const tv = new DataView(tif.buffer), ifd = tv.getUint32(4, true), tags = {};
for (let k = 0; k < tv.getUint16(ifd, true); k++) tags[tv.getUint16(ifd + 2 + 12 * k, true)] = tv.getUint32(ifd + 10 + 12 * k, true);
assert.equal(String.fromCharCode(tif[0], tif[1]) + tv.getUint16(2, true), "II42");
assert.deepEqual([tags[256], tags[257], tags[259], tags[262], tv.getUint32(tags[282], true) / tv.getUint32(tags[282] + 4, true)], [3, 2, 32773, 2, 300]);
assert.deepEqual([...unpackBits(tif.subarray(tags[273]), 18).subarray(0, 9)], [255, 0, 0, 0, 255, 0, 255, 255, 255]); // transparent: white
const fakePng = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, ...new Array(17).fill(0), 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130]);
const dpiPng = pngWithDpi(fakePng, 300), pv = new DataView(dpiPng.buffer);
assert.equal(String.fromCharCode(...dpiPng.subarray(37, 41)), "pHYs");
assert.deepEqual([pv.getUint32(41), pv.getUint32(45), dpiPng[49]], [11811, 11811, 1]);
assert.equal(pv.getUint32(50), crc32(dpiPng.subarray(37, 50)));
assert.equal(pngWithDpi(dpiPng, 600).length, dpiPng.length); // the old pHYs replaced, not kept
const z = zip([{ name: "a.txt", data: "甲" }, { name: "word/b.xml", data: "<x/>" }]), zv = new DataView(z.buffer);
assert.deepEqual([zv.getUint32(0, true), zv.getUint32(z.length - 22, true), zv.getUint16(z.length - 12, true)], [0x04034b50, 0x06054b50, 2]);

// three-line tables: grouped heads, italic symbols, LaTeX (booktabs), CSV, Markdown and Word's XML
const tspec = { id: "t", title: "各时期的用量", columns: [{ key: "p", label: "时期", align: "left" }, { key: "m", label: "M (P25, P75)", align: "center", group: "折合克数（g）" },
  { key: "s", label: "x̄ ± s", align: "center", group: "折合克数（g）" }], rows: [{ p: "汉", m: "29.4 (29.4, 29.4)", s: "29.4 ± 7.3" }], notes: ["P < 0.05"], source: "演示" };
assert.equal(invalidTable(tspec), null);
assert.match(invalidTable({ columns: [] }), /columns/);
assert.deepEqual(tablesOf({ tables: [tspec, { title: "坏" }] }), [tspec]);
assert.deepEqual(headRows(tspec).map((r) => r.map((c) => [c.label, c.span, c.rows])), [[["时期", 1, 2], ["折合克数（g）", 2, 1]], [["M (P25, P75)", 1, 1], ["x̄ ± s", 1, 1]]]);
assert.deepEqual(runs("P < 0.05，n = 3；Jaccard"), [["P", true], [" < 0.05，", false], ["n", true], [" = 3；Jaccard", false]]);
assert.equal(tex("50% & _x，P"), "50\\% \\& \\_x，\\textit{P}");
const latex = toLaTeX(tspec, 2);
for (const piece of ["\\caption{各时期的用量}", "\\toprule", "\\multirow{2}{*}{时期}", "\\cmidrule(lr){2-3}", "$\\bar{x}$", "\\bottomrule", "注：\\textit{P} < 0.05"]) assert.ok(latex.includes(piece), piece);
assert.equal(tableCSV(tspec), '﻿时期,"折合克数（g） · M (P25, P75)",折合克数（g） · x̄ ± s\r\n汉,"29.4 (29.4, 29.4)",29.4 ± 7.3\r\n'); // commas quoted
assert.equal(tableCSV({ ...tspec, columns: [tspec.columns[0]], rows: [{ p: "=HYPERLINK(1)" }, { p: "-0.5" }, { p: "@A1" }], notes: [] }, false), "时期\r\n'=HYPERLINK(1)\r\n-0.5\r\n'@A1\r\n"); // a formula stays text
assert.ok(tableMarkdown(tspec, 1).startsWith("**表1　各时期的用量**\n\n| 时期 | 折合克数（g） · M (P25, P75) |"));
const docXML = documentXML([tspec]);
for (const piece of ['<w:gridSpan w:val="2"/>', '<w:vMerge w:val="restart"/>', "<w:vMerge/>", "<w:tblHeader/>", "表1　各时期的用量", '<w:top w:val="single" w:sz="12"', "<w:i/>"]) assert.ok(docXML.includes(piece), piece);

// 我的资料: what a message keeps of a dataset (its shape, no rows), what the model reads of it, what the page says
const dataset = { id: "d1a2b3c", name: "门诊.csv", kind: "table", rows: 120, created: "2026-10-11T00:00:00+00:00",
  columns: [{ name: "姓名", type: "text" }, { name: "处方", type: "prescription" }, { name: "电话", type: "empty" }],
  preview: [{ 姓名: "P0001" }], deidentified: { columns: { 姓名: "以化名代替（P0001…）", 电话: "已删除" }, masked: { 手机号: 2 } } };
const shape = brief(dataset);
assert.ok(!("preview" in shape) && shape.rows === 120 && shape.columns.length === 3);
assert.equal(sizeLabel(shape), "表格 120 行 · 3 列");
assert.equal(deidLabel(shape), "姓名：以化名代替（P0001…）；电话已删除；文中手机号 2 处");
const note = dataNote([shape]);
assert.ok(note.includes("d1a2b3c「门诊.csv」，表格 120 行；列：姓名（文本）、处方（处方）") && note.includes("[[mine:…]]") && !note.includes("电话（"));
assert.equal(userText({ text: "分析", data: [shape] }), "分析" + note);
assert.equal(userText({ text: "分析" }), "分析");
const withData = buildHistory([{ role: "user", text: "看看", data: [shape] }, { role: "assistant", segments: [{ type: "text", text: "好" }] }],
  { format: "openai", id: "x" });
assert.ok(withData[0].content.includes("d1a2b3c「门诊.csv」"));
assert.ok(isMine("mydata__describe") && isMine("mydata.read") && !isMine("study__pairs") && !isMine(undefined));

// a search's hits found under another name of the asked drug, or flagged, are labelled in plain words (ADR 0023): one
// badge per kind, drug and source, the asked name only where it is known, the kind worded as a relation; as in the
// ledger's words, only an asked name stands before an arrow, and a passage writing another name of the drug asked says
// so after the drug (写作)
const viaOf = (o) => ({ kind: "异名", status: "open", witness: null, reading: null, p: null, ...o });
const lexOf = (surface, direction, o = {}) => viaOf({ surface, referent: "地黄", direction, kind: "炮制/加工名", source: ["词表"], ...o });
const searched = {
  query: { terms: [], aliases: { asked: [{ surface: "国老", referents: [{ head: "甘草" }] }],
    expansions: [{ surface: "甘草", for: "国老", direction: "alias→drug", referent: "甘草", searched: true }] } },
  hits: [
    { passage_id: "a.1", matched: ["国老"] },
    { passage_id: "b.1", matched: ["甘草"], routes: ["alias"], via: [viaOf({ surface: "甘草", referent: "甘草", direction: "alias→drug",
      source: ["别名录（中醫笈成）", "编者审定"], witness: "w.1" })] },
    { passage_id: "c.1", matched: ["独摇草"], via: [viaOf({ surface: "独摇草", referent: "鬼督邮", direction: "drug→alias", source: ["词表"] })] },
    { passage_id: "d.1", matched: ["鬼督邮"], via: [viaOf({ surface: "鬼督邮", referent: "徐长卿", direction: "asked", status: "cue",
      source: ["纲目释名"], reading: "徐长卿", p: 0.6667 })] },
    { passage_id: "e.1", matched: ["鬼督邮"], via: [viaOf({ surface: "鬼督邮", referent: null, direction: "asked", kind: null, status: null,
      source: [], p: 0.5 })], flags: ["homonym:鬼督邮"] },
    { passage_id: "f.1", matched: ["山药"], via: [viaOf({ surface: "山药", referent: "山药", direction: "alias→drug", kind: "避讳改名",
      source: ["避讳"] }), null, "x"], flags: ["anachronism:山药<1063:edition", "demoted:inside 大将军", "demoted:inside ?", "demoted:no-context",
      "other-referent:通草", "new:x", null, { text: "x" }] },
    { passage_id: "g.1", matched: ["地黄", "熟地黄", "熟地"], via: [lexOf("地黄", "alias→drug", { for: "生地" }), lexOf("熟地黄", "drug→alias"),
      lexOf("熟地", "drug→alias"), lexOf("干地黄", "drug→alias", { kind: "异名" })] },
    { passage_id: "h.1", matched: ["屏风"], via: ["屏风", "百枝", "百蜚", "茴草", "铜芸"].map((s) =>
      viaOf({ surface: s, referent: "防风", direction: "drug→alias", source: ["词表"] })) },
  ],
};
const notes = hitNotes(searched);
const texts = (n) => n.labels.map((l) => l.text);
assert.deepEqual(Object.keys(notes), ["b.1", "c.1", "d.1", "e.1", "f.1", "g.1", "h.1"]);
assert.deepEqual(texts(notes["b.1"]), ["别名：国老→甘草 · 别名录（中醫笈成）"]);
assert.equal(notes["b.1"].labels[0].title, "此段写作「甘草」；「国老」即甘草（异名）；依据：别名录（中醫笈成）、编者审定；书证 w.1");
assert.deepEqual(texts(notes["c.1"]), ["别名：鬼督邮（写作独摇草） · 词表"]);
assert.deepEqual(texts(notes["d.1"]), ["读作：鬼督邮→徐长卿"]);
assert.ok(notes["d.1"].labels[0].title.includes("0.6667"));
assert.deepEqual(texts(notes["e.1"]), []);
assert.deepEqual(notes["e.1"].flags.map((f) => f.text), ["同名异物"]);
// no expansion, asked name or `for` of its drug: no asked name is put on it (not every asked name of the question)
assert.deepEqual(texts(notes["f.1"]), ["避讳改名：山药 · 避讳"]);
assert.equal(notes["f.1"].labels[0].title, "此段写作「山药」；所问之名与山药：避讳改名；依据：避讳");
assert.deepEqual(notes["f.1"].flags.map((f) => f.text), ["年代存疑", "仅见于「大将军」", "仅见于他名之中", "无药物语境", "所指不同"]);
assert.ok(notes["f.1"].flags[0].title.includes("1063") && notes["f.1"].flags[0].title.includes("刊本"));
// the via's own `for` names the asked name; vias of one kind, drug and source share a badge, asked names (before the
// arrow) and written ones (写作) never
assert.deepEqual(texts(notes["g.1"]), ["炮制/加工名：生地→地黄 · 词表", "炮制/加工名：地黄（写作熟地黄、熟地） · 词表",
  "别名：地黄（写作干地黄） · 词表"]);
assert.equal(notes["g.1"].labels[0].title, "此段写作「地黄」；「生地」与地黄：炮制/加工名；依据：词表");
assert.equal(notes["g.1"].labels[1].title, "此段写作「熟地黄」「熟地」，与地黄：炮制/加工名；依据：词表");
assert.deepEqual(texts(notes["h.1"]), ["别名：防风（写作屏风、百枝、百蜚、茴草等） · 词表"]);
assert.equal(notes["h.1"].labels[0].title, "此段写作「屏风」「百枝」「百蜚」「茴草」「铜芸」，即防风（异名）；依据：词表");
assert.equal(notes["c.1"].labels[0].title, "此段写作「独摇草」，即鬼督邮（异名）；依据：词表");
// a passage writing another name of the drug an asked name names: the written name and the asked one follow the drug,
// with no arrow, since the kind is the written name's (炮制/加工名：薯蓣→山药 would be false); it is a badge of its own
// beside the asked name's, and a false friend asked says so
const sideOf = (vias) => hitNotes({ query: { terms: [] }, hits: [{ passage_id: "x", via: vias }] }).x.labels;
const yamWritten = viaOf({ surface: "山芋", for: ["薯蓣"], referent: "山药", direction: "drug→alias", source: ["别名录（中醫笈成）"] });
assert.deepEqual(sideOf([yamWritten]).map((l) => [l.text, l.title]), [["别名：山药（写作山芋；所问薯蓣） · 别名录（中醫笈成）",
  "此段写作「山芋」，即山药（异名）；为所问「薯蓣」检索山药；依据：别名录（中醫笈成）"]]);
assert.equal(sideOf([{ ...yamWritten, surface: "干山药", kind: "炮制/加工名", source: ["词表"] }])[0].text, "炮制/加工名：山药（写作干山药；所问薯蓣） · 词表");
assert.equal(sideOf([{ ...yamWritten, for: ["山药"] }])[0].text, "别名：山药（写作山芋） · 别名录（中醫笈成）"); // the drug asked
const sedum = (surface, direction) => viaOf({ surface, for: ["救火"], referent: "景天", direction, status: "stop", source: ["词表"] });
const friend = sideOf([sedum("景天", "alias→drug"), sedum("慎火", "drug→alias"), sedum("水母", "drug→alias")]);
assert.deepEqual(friend.map((l) => l.text), ["别名：救火→景天 · 词表", "别名：景天（写作慎火、水母；所问救火） · 词表"]);
assert.ok(friend.every((l) => l.title.includes("「救火」多作普通词语")));
assert.equal(friend[1].title, "此段写作「慎火」「水母」，即景天（异名）；为所问「救火」检索景天；「救火」多作普通词语，罕作药名；依据：词表");
// the kind is a relation: no label says which name is the other's
assert.ok(Object.values(notes).every((n) => n.labels.every((l) => !/是.*的/u.test(l.title))));
// the two ways a pair finds a passage never read alike, and an arrow reads as on an ask card (the ledger's words): 川楝子
// asked, a passage that writes 金铃子; 金铃子 asked, a passage that writes 川楝子
const melia = viaOf({ referent: "川楝子", source: ["词表"] });
assert.deepEqual([sideOf([{ ...melia, surface: "金铃子", for: ["川楝子"], direction: "drug→alias" }]),
  sideOf([{ ...melia, surface: "川楝子", for: ["金铃子"], direction: "alias→drug" }])].map((l) => l[0].text),
  ["别名：川楝子（写作金铃子） · 词表", "别名：金铃子→川楝子 · 词表"]);
// no name the passage writes stands before an arrow
for (const l of [...Object.values(notes).flatMap((n) => n.labels), ...sideOf([yamWritten]), ...friend]) {
  const before = /^[^：]+：(.+?)→/u.exec(l.text);
  const written = /^此段写作((?:「[^」]+」)+)/u.exec(l.title);
  if (before && written && !l.text.startsWith("读作")) {
    assert.ok(before[1].replace(/等$/u, "").split("、").every((s) => !written[1].includes(`「${s}」`)), l.text);
  }
}
// without `for`: the expansions searched under that name, else the asked names of its drug, else the expansions' asked names
const lexical = (aliases, via) => hitNotes({ query: { terms: [], aliases }, hits: [{ passage_id: "x", via: [via] }] }).x.labels[0].text;
const yam = viaOf({ surface: "山药", referent: "山药", direction: "alias→drug", kind: "避讳改名", source: ["词表"] });
assert.equal(lexical({ asked: [], expansions: [{ surface: "山芋", for: "薯蓣", direction: "drug→alias", referent: "山药" }] }, yam),
  "避讳改名：薯蓣→山药 · 词表");
assert.equal(lexical({ asked: [{ surface: "薯蓣", referents: [{ head: "山药" }] }, { surface: "国老", referents: [{ head: "甘草" }] }],
  expansions: [] }, yam), "避讳改名：薯蓣→山药 · 词表");
assert.equal(lexical(undefined, yam), "避讳改名：山药 · 词表");
assert.deepEqual(hitNotes({ hits: [{ passage_id: "x", score: 1 }] }), {});
assert.deepEqual(hitNotes({ rows: [] }), {});
assert.deepEqual(hitNotes(null), {});
// a search's hits carry what it found them under — null for one found as asked, so that a later search clears an
// earlier one's label — and nothing else is touched
const cards = [{ passage_id: "a.1", title: "甲" }, { passage_id: "b.1", title: "乙" }, { passage_id: "z.9", title: "丙" }];
const marked = withFound(cards, searched);
assert.deepEqual(marked.map((c) => c.found === undefined ? "none" : c.found === null ? "null" : texts(c.found)[0]),
  ["null", "别名：国老→甘草 · 别名录（中醫笈成）", "none"]);
assert.equal(withFound(cards, { rows: [] }), cards);
assert.equal(withFound(cards, { query: "门诊", terms: [], hits: [{ passage_id: "a.1" }] }), cards); // not a classics search
// a taochronos_ask source's labels (the evidence ledger's words, chat/results.py CARD_FIELDS) are its found: a via or a
// reading a label, a flag by its word in warn, the whole in its title; they do not stay on the card, and an unlabelled
// source (perhaps not a search's) is left as it is
const late = "年代存疑（甘草约 1180 年后才通行；或经后世刊本改字）";
const sources = [
  { passage_id: "a.1", title: "甲", labels: ["via 国老→甘草（别名录（中醫笈成））", late, "同名异物（国老未能判定所指）", "仅见于「国老汤」", "lost:x"] },
  { passage_id: "b.1", labels: ["via 川楝子（写作金铃子；词表）", "读作 鬼督邮→徐长卿（p 0.6667）"] },
  { passage_id: "z.9", title: "丙" }, { passage_id: "y.1", labels: [7, ""] }, null];
const ask = withFound(sources, { run: "r", steps: [], report_markdown: "", sources });
assert.deepEqual(ask.map((c) => c && "labels" in c), [false, false, false, false, null]);
assert.equal(ask[0].title, "甲");
assert.deepEqual(texts(ask[0].found), ["via 国老→甘草（别名录（中醫笈成））"]);
assert.deepEqual(ask[0].found.flags.map((f) => [f.text, f.title]), [["年代存疑", late], ["同名异物", "同名异物（国老未能判定所指）"],
  ["仅见于「国老汤」", "仅见于「国老汤」"], ["lost:x", "lost:x"]]);
assert.deepEqual(texts(ask[1].found), ["via 川楝子（写作金铃子；词表）", "读作 鬼督邮→徐长卿（p 0.6667）"]);
assert.ok(ask[1].found.labels[0].title.startsWith("via 川楝子（写作金铃子；词表）。") && ask[1].found.labels[0].title.includes("所问为甲"));
assert.deepEqual(ask[1].found.flags, []);
assert.equal(ask[2], sources[2]);
assert.ok(!("found" in ask[3]) && ask[3].passage_id === "y.1");
// a search's hit is found by the search, whatever else the card says
assert.deepEqual(withFound([{ passage_id: "b.1", labels: ["via 国老→甘草（词表）"] }], searched).map((c) => [texts(c.found), "labels" in c]),
  [[["别名：国老→甘草 · 别名录（中醫笈成）"], false]]);
assert.equal(personal({ messages: [{ role: "user", text: "桂枝汤" }] }), false);
assert.equal(personal({ messages: [{ role: "user", text: "看看", data: [shape] }] }), true);
assert.equal(personal({ messages: [{ role: "assistant", segments: [{ type: "tools", calls: [{ name: "mydata__list" }] }] }] }), true);
assert.equal(personal({ messages: [{ role: "assistant", segments: [{ type: "tools", calls: [{ name: "taochronos_call", args: { tool: "mydata.read" } }] }] }] }), true);
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


# the waits of a turn (web/js/limits.js, agent.js, runtime.js): each with its limit, each call to an end
NODE_WAITS = r"""
import assert from "node:assert/strict";
import { limit } from "./js/limits.js";
import { ProviderError, streamChat } from "./js/llm/openai.js";
import { closingNote, runTurn } from "./js/agent.js";
import { BrowserRuntime, ServerRuntime } from "./js/runtime.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const abortError = () => new DOMException("aborted", "AbortError");
// a promise that never settles by itself; with a signal, one that ends when it does (as fetch does)
const hang = (signal) => new Promise((resolve, reject) => signal?.addEventListener("abort", () => reject(abortError())));
// a signal whose listeners are counted: what a request adds to it, it takes away when it is done
let listening = 0;
const counted = () => {
  const c = new AbortController();
  const add = c.signal.addEventListener.bind(c.signal);
  const remove = c.signal.removeEventListener.bind(c.signal);
  c.signal.addEventListener = (...a) => { listening++; add(...a); };
  c.signal.removeEventListener = (...a) => { listening--; remove(...a); };
  return c;
};

// a limit counts the time the page runs: once used up it says so, once; a pause does not count, and a restart begins
// the count again
let fired = 0;
limit(100, () => fired++);
await sleep(400);
assert.equal(fired, 1);
let l = limit(150, () => fired++);
l.pause();
await sleep(400);
assert.equal(fired, 1);
l.resume();
await sleep(500);
assert.equal(fired, 2);
l = limit(500, () => fired++);
await sleep(300);
l.restart();
await sleep(300);
assert.equal(fired, 2);
await sleep(500);
assert.equal(fired, 3);
// a long gap between two looks at the clock is a page that did not run (a phone asleep, a tab the browser froze): it
// counts no more than a hidden tab's minute between looks
const realNow = Date.now;
let skew = 0;
Date.now = () => realNow() + skew;
l = limit(100000, () => fired++);
skew += 3600000;
await sleep(1300);
assert.equal(fired, 3);
assert.ok(l.spent >= 60000 && l.spent < 70000, String(l.spent));
skew += 3600000;
await sleep(1100);
assert.equal(fired, 4);
Date.now = realNow;

// a model's reply: its first byte waited for so long, then its silences — each ends the request, which is asked again
// like one that broke off; the caller's stop ends it too, as a stop
const relayP = { id: "impf", relay: true, baseUrl: "https://relay.example/v1", model: "Tao-R1", extra_body: {},
  max_tokens_param: "max_completion_tokens", thinking_off: { thinking: { type: "disabled" } }, reasoning: "reasoning_details" };
const enc = new TextEncoder();
const delta = (content, finish = null) => `data: ${JSON.stringify({ choices: [{ delta: { content }, finish_reason: finish }] })}\n\n`;
const streamed = (body) => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
const sse = (text) => new ReadableStream({ start(c) { c.enqueue(enc.encode(text)); c.close(); } });
const silent = (text) => new ReadableStream({ start(c) { c.enqueue(enc.encode(text)); } }); // says this, then nothing
const ask = (extra) => streamChat({ provider: relayP, messages: [], tools: [], settings: {}, ...extra });
globalThis.fetch = () => new Promise(() => {}); // a service that never answers, and does not heed the signal either
await assert.rejects(ask({ limits: { firstReply: 150 } }),
  (e) => e instanceof ProviderError && e.retryable && e.kind === "timeout" && e.message === "模型服务 0 秒没有回应");
globalThis.fetch = async () => streamed(silent(delta("桂枝")));
await assert.rejects(ask({ limits: { silence: 150 } }),
  (e) => e instanceof ProviderError && e.retryable && e.kind === "timeout" && e.message === "回复中断：模型服务 0 秒没有再发来内容");
globalThis.fetch = async () => streamed(new ReadableStream({ async start(c) { // one that keeps talking is not cut
  for (let i = 0; i < 8; i++) { c.enqueue(enc.encode(delta("字"))); await sleep(60); }
  c.enqueue(enc.encode(delta("。", "stop")));
  c.close();
} }));
assert.equal((await ask({ limits: { silence: 200 } })).text, "字字字字字字字字。");
globalThis.fetch = async () => ({ ok: true, status: 200, headers: new Headers({ "Content-Type": "text/event-stream" }), body: undefined,
  text: () => new Promise(() => {}) }); // read whole, and never done
await assert.rejects(ask({ limits: { whole: 150 } }), (e) => e.retryable && e.message === "回复 0 秒还没有读完");
// a request with both the caller's stop and a limit: either ends it, and it leaves no listener behind
for (const [after, limits, check] of [[60, { silence: 5000 }, (e) => e.name === "AbortError"],
  [5000, { silence: 150 }, (e) => e.kind === "timeout"]]) {
  const stop = counted();
  const timer = setTimeout(() => stop.abort(), after);
  globalThis.fetch = async () => streamed(silent(delta("桂枝")));
  await assert.rejects(ask({ signal: stop.signal, limits }), check);
  clearTimeout(timer);
  assert.equal(listening, 0);
}
// a request stopped as it is sent: a stop, and the fetch's own failure is not left unhandled
let unhandled = 0;
const unhandledSeen = () => unhandled++;
process.on("unhandledRejection", unhandledSeen);
const stopNow = new AbortController();
globalThis.fetch = async () => { stopNow.abort(); throw abortError(); };
await assert.rejects(ask({ signal: stopNow.signal }), (e) => e.name === "AbortError");
await sleep(30);
process.off("unhandledRejection", unhandledSeen);
assert.equal(unhandled, 0);
// a reply that stalled is asked again, and what it had shown goes
let asked = 0;
globalThis.fetch = async () => streamed(++asked === 1 ? silent(delta("半")) : sse(delta("答", "stop")));
const seen = [];
const res = await runTurn({ provider: relayP, settings: {}, route: null, runtime: null, tools: [], system: "s", history: [],
  user: { text: "问" }, signal: new AbortController().signal, limits: { silence: 150 },
  hooks: { retry: (n, e) => seen.push(n, e.message), text: (t) => seen.push(t) } });
assert.deepEqual([seen, res.wire.at(-1).content, asked], [["半", 1, "回复中断：模型服务 0 秒没有再发来内容", "答"], "答", 2]);

// a round's tools: each call ends — ok, error, timeout, stopped, skipped — and the model is asked again once every one
// of them has, with each call's result in its place
const calls = (...cs) => `data: ${JSON.stringify({ choices: [{ delta: { tool_calls: cs.map(([name, args], i) => (
  { index: i, id: `c${i}`, function: { name, arguments: JSON.stringify(args) } })) }, finish_reason: "tool_calls" }] })}\n\ndata: [DONE]\n\n`;
const scripted = (...replies) => {
  const bodies = [];
  globalThis.fetch = async (url, init) => { bodies.push(JSON.parse(init.body)); return streamed(sse(replies.shift())); };
  return bodies;
};
const told = (body) => body.messages.filter((m) => m.role === "tool").map((m) => [m.tool_call_id, m.content]);
const log = [];
const hooks = {
  toolWaiting: (c, why) => log.push(`${c.name} ${why}`), toolRunning: (c) => log.push(`${c.name} runs`),
  toolEnd: (c, o) => log.push(`${c.name} ${o.ok ? "ok" : o.status || "error"}`),
  toolLater: (c, ending) => { log.push(`${c.name} later`); ending.then((o) => log.push(`${c.name} ended ${o.ok ? "ok" : o.status}`)); },
  limit: (n, why) => log.push(`limit ${why}`),
};
const turn = (runtime, extra = {}) => runTurn({ provider: relayP, settings: {}, route: null, runtime, tools: [], system: "s",
  history: [], user: { text: "问" }, signal: new AbortController().signal, hooks, ...extra });
const CHART = '{"chart": 1}';
// a chart that is done, and a search that never ends (nor heeds its stop): the chart's end is shown at once, the search
// is not waited for past its deadline, and the model explains the chart without it
let stopped = null;
let bodies = scripted(calls(["analysis__chart", {}], ["classics__search", { query: "桂枝" }]), delta("答", "stop"));
let rt = { call: (name, args, o) => {
  if (name === "analysis__chart") return Promise.resolve({ ok: true, text: CHART });
  stopped = o.signal;
  return new Promise(() => {});
} };
let from = Date.now();
let done = await turn(rt, { limits: { tool: 300 } });
assert.ok(Date.now() - from < 2000);
assert.deepEqual(log.splice(0), ["analysis__chart ok", "classics__search timeout"]);
assert.ok(stopped.aborted); // the runtime is told it is not waited for
assert.deepEqual(told(bodies[1]), [["c0", CHART],
  ["c1", "ERROR: 这个调用运行了 0 秒还没有完成，页面不再等待，结果不可用。请根据已有结果作答，并在回答中说明缺少这一项；需要时可以缩小范围再调用一次。"]]);
assert.equal(done.wire.at(-1).content, "答");
// the time a call waits — for the runtime to load, or for its turn — does not count towards its deadline
bodies = scripted(calls(["classics__search", {}]), delta("答", "stop"));
rt = { call: (name, args, o) => new Promise((resolve) => {
  o.onWait("loading");
  setTimeout(() => o.onWait("queued"), 150);
  setTimeout(() => { o.onStart(); setTimeout(() => resolve({ ok: true, text: "{}" }), 100); }, 500);
}) };
await turn(rt, { limits: { tool: 300 } });
assert.deepEqual(log.splice(0), ["classics__search loading", "classics__search queued", "classics__search runs", "classics__search ok"]);
assert.deepEqual(told(bodies[1]), [["c0", "{}"]]);
// a runtime that fails, or throws before it begins: an error the model reads
bodies = scripted(calls(["a__x", {}], ["b__y", {}]), delta("答", "stop"));
rt = { call: (name) => { if (name === "b__y") throw new Error("坏了"); return Promise.reject(new Error("出错了")); } };
await turn(rt);
assert.deepEqual(log.splice(0).sort(), ["a__x error", "b__y error"]);
assert.deepEqual(told(bodies[1]), [["c0", "ERROR: 出错了"], ["c1", "ERROR: 坏了"]]);
// a stop while a call runs: it ends as stopped, its runtime is told, and the model is not asked again
let stop = new AbortController();
bodies = scripted(calls(["classics__search", {}]), delta("不该", "stop"));
rt = { call: (name, args, o) => { stopped = o.signal; return hang(o.signal); } };
setTimeout(() => stop.abort(), 100);
done = await turn(rt, { signal: stop.signal });
assert.deepEqual([log.splice(0), bodies.length, stopped.aborted, done.wire.at(-1).content], [["classics__search stopped"], 1, true, "ERROR: 调用已停止"]);
// the user asks for the answer while a search runs: the search is not waited for, no more calls run, the model is told to
// answer from what it has and to say what it lacks — and when it asks for another call anyway, that one is refused
let hurry = new AbortController();
bodies = scripted(calls(["analysis__chart", {}], ["classics__search", {}]), calls(["classics__search", {}]), delta("答", "stop"));
rt = { call: (name, args, o) => (name === "analysis__chart" ? Promise.resolve({ ok: true, text: CHART }) : hang(o.signal)) };
setTimeout(() => hurry.abort(), 100);
done = await turn(rt, { hurry: hurry.signal });
assert.deepEqual(log.splice(0), ["analysis__chart ok", "classics__search skipped", "limit asked", "classics__search skipped"]);
assert.deepEqual(told(bodies[1]), [["c0", CHART], ["c1", `ERROR: 用户想先看到回答，这个调用没有等到结果。请根据已有结果作答，并在回答中说明缺少这一项。${closingNote("asked")}`]]);
assert.equal(told(bodies[2]).at(-1)[1], "ERROR: 用户想先看到回答，不再调用工具：请根据已有结果直接作答。");
assert.equal(done.wire.at(-1).content, "答");
assert.equal(closingNote("asked"), "\n\n［提示：用户想先看到回答，请根据已有结果直接作答，不要再调用工具；没有等到的结果，请在回答中说明缺了什么］");
// …and a model that keeps asking is stopped, as at the end of its rounds
scripted(calls(["classics__search", {}]), calls(["classics__search", {}]), calls(["classics__search", {}]), delta("不该", "stop"));
hurry = new AbortController();
setTimeout(() => hurry.abort(), 100);
done = await turn(rt, { hurry: hurry.signal });
assert.deepEqual(log.splice(0), ["classics__search skipped", "limit asked", "classics__search skipped", "classics__search skipped", "limit asked"]);
// a research run the user does not wait for goes on by itself: the turn answers without it, and its end comes later
hurry = new AbortController();
bodies = scripted(calls(["taochronos_research", { question: "q" }]), delta("答", "stop"));
let giving = null;
rt = { research: (args, o) => new Promise((resolve) => {
  o.onStart();
  giving = o.giving;
  setTimeout(() => resolve({ ok: true, text: '{"report": 1}' }), 500);
}) };
setTimeout(() => hurry.abort(), 100);
done = await turn(rt, { hurry: hurry.signal });
assert.deepEqual(log.splice(0), ["taochronos_research runs", "taochronos_research later", "taochronos_research background", "limit asked"]);
assert.ok(giving.aborted); // it may give way to the calls behind it
assert.match(told(bodies[1])[0][1], /^ERROR: 这次研究仍在后台进行，结果现在还不能用/);
await sleep(900);
assert.deepEqual(log.splice(0), ["taochronos_research ended ok"]);
// a research run past its own deadline ends as one, later too
hurry = new AbortController();
scripted(calls(["taochronos_research", { question: "q" }]), delta("答", "stop"));
rt = { research: (args, o) => { o.onStart(); return new Promise(() => {}); } };
setTimeout(() => hurry.abort(), 100);
await turn(rt, { hurry: hurry.signal, limits: { research: 400 } });
await sleep(1500);
assert.deepEqual(log.splice(0), ["taochronos_research runs", "taochronos_research later", "taochronos_research background", "limit asked",
  "taochronos_research ended timeout"]);
// the turn runs its time: the call under way is not waited for, and the model answers from what it has
bodies = scripted(calls(["classics__search", {}]), delta("答", "stop"));
rt = { call: (name, args, o) => hang(o.signal) };
from = Date.now();
done = await turn(rt, { limits: { turn: 300 } });
assert.ok(Date.now() - from < 2000);
assert.deepEqual(log.splice(0), ["classics__search skipped", "limit time"]);
assert.equal(told(bodies[1])[0][1], "ERROR: 这一轮回答的时间已用完，这个调用没有等到结果。请根据已有结果作答，并在回答中说明缺少这一项。"
  + "\n\n［提示：这一轮回答已经用了 0 分钟，请根据已有结果直接作答，不要再调用工具；没有拿到的结果，请在回答中说明缺了什么］");
assert.equal(done.wire.at(-1).content, "答");

// the browser's runtime: a worker that runs one call at a time.  This one answers each call after `took` ms (never, when
// it is below 0), and can be interrupted when the page is cross-origin isolated
const workers = [];
globalThis.Worker = class {
  constructor() { this.posted = []; this.ended = false; workers.push(this); }
  postMessage(msg) {
    this.posted.push(msg.params?.name || msg.method);
    const say = (data, after = 0) => setTimeout(() => !this.ended && this.onmessage?.({ data }), after);
    if (msg.method === "init") {
      if (globalThis.SHARED) say({ type: "interrupt", buffer: globalThis.SHARED });
      return say({ id: msg.id, result: { name: "TaoChronos" } }, 50);
    }
    const took = msg.params?.arguments?.took ?? 20;
    if (took >= 0) say({ id: msg.id, result: { ok: true, text: msg.params.name } }, took);
  }
  terminate() { this.ended = true; }
};
globalThis.fetch = async () => new Response("null", { status: 404 }); // no boot file
const browser = new BrowserRuntime();
const events = [];
const watched = (tag, extra = {}) => ({ onWait: (why) => events.push(`${tag} ${why}`), onStart: () => events.push(`${tag} runs`), ...extra });
// a call made while it loads waits for it, then for the calls before it
const a = browser.call("a", { took: 100 }, watched("a"));
const b = browser.call("b", { took: 10 }, watched("b"));
assert.deepEqual((await Promise.all([a, b])).map((r) => r.text), ["a", "b"]);
assert.deepEqual(events.splice(0), ["a loading", "b loading", "a runs", "b queued", "b runs"]);
// a call no longer waited for while it waits is never sent; one the worker runs ends at once for its caller, and what it
// returns later is dropped — the next call gets its own result
const stopD = counted();
const c = browser.call("c", { took: 150 }, watched("c"));
const d = browser.call("d", { took: 10 }, watched("d", { signal: stopD.signal }));
const e = browser.call("e", { took: 10 }, watched("e"));
await sleep(5); // d waits behind c
stopD.abort();
await assert.rejects(d, (x) => x.name === "AbortError");
assert.deepEqual(browser.queue.map((j) => j.params.name), ["e"]);
const stopF = counted();
const f = browser.call("f", { took: 200 }, watched("f", { signal: stopF.signal }));
await Promise.all([c, e]);
await sleep(10);
from = Date.now();
stopF.abort();
await assert.rejects(f, (x) => x.name === "AbortError");
assert.ok(Date.now() - from < 50);
assert.equal((await browser.call("g", { took: 10 }, watched("g"))).text, "g");
assert.deepEqual(workers[0].posted, ["init", "a", "b", "c", "e", "f", "g"]);
assert.deepEqual([browser.queue.length, browser.busy, listening], [0, null, 0]); // nothing left waiting, no listener left
events.length = 0;
// a call no one waits for, which never ends, holding up one that waits: the worker is started again, and the call
// waiting runs on the new one
browser.stuckMs = 200;
const stopH = new AbortController();
const held = browser.call("h", { took: -1 }, { signal: stopH.signal });
await sleep(20);
stopH.abort();
await assert.rejects(held, (x) => x.name === "AbortError");
const i = browser.call("i", { took: 10 }, watched("i"));
assert.equal((await i).text, "i");
assert.deepEqual([workers.length, workers[0].ended, workers[1].posted], [2, true, ["init", "i"]]);
assert.deepEqual(events.splice(0), ["i queued", "i runs"]);
// a call that may give way (a research run going on by itself) is let run while no one waits behind it
const giveWay = new AbortController();
const j = browser.call("j", { took: 300 }, { giving: giveWay.signal });
giveWay.abort();
assert.equal((await j).text, "j");
assert.equal(workers.length, 2);
// where the page is cross-origin isolated, a call no one waits for is interrupted (SIGINT), and the flag is cleared for
// the next call
globalThis.SHARED = new SharedArrayBuffer(4);
const isolated = new BrowserRuntime();
await isolated.start();
await sleep(10);
const stopK = new AbortController();
const k = isolated.call("k", { took: -1 }, { signal: stopK.signal });
await sleep(10);
stopK.abort();
await assert.rejects(k);
assert.equal(new Int32Array(globalThis.SHARED)[0], 2);
delete globalThis.SHARED;
isolated.stop();
browser.stop();

// a server: a request ends at the caller's stop or at its own limit, whichever comes first, and leaves no listener behind
globalThis.location = { protocol: "https:", hostname: "chat.impf.ai", href: "https://chat.impf.ai/" };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
globalThis.fetch = (url, init) => hang(init.signal);
const srv = new ServerRuntime("https://chat.impf.ai");
await assert.rejects(srv._fetch("/api/info", { signal: counted().signal }, 150), (x) => x.unavailable && x.message === "连接 https://chat.impf.ai 超时");
assert.equal(listening, 0);
const stopL = counted();
setTimeout(() => stopL.abort(), 60);
await assert.rejects(srv._fetch("/api/info", { signal: stopL.signal }, 5000), (x) => x.name === "AbortError");
assert.equal(listening, 0);
globalThis.fetch = async () => json({ ok: true });
await srv._fetch("/api/info", { signal: counted().signal }, 5000);
assert.equal(listening, 0);
// a few calls at once, the rest waiting their turn (as "queued"), and a call stopped while it waits leaves its place
let inFlight = 0;
let most = 0;
globalThis.fetch = async () => { inFlight++; most = Math.max(most, inFlight); await sleep(50); inFlight--; return json({ ok: true, text: "{}" }); };
const queued = [];
await Promise.all([...Array(7)].map((_, n) => srv.call("x", {}, { onWait: () => queued.push(n) })));
assert.deepEqual([most, queued, srv.running, srv.waiting.length], [4, [4, 5, 6], 0, 0]);
const stopM = new AbortController();
const four = [...Array(4)].map(() => srv.call("x", {}));
const fifth = srv.call("x", {}, { signal: stopM.signal });
stopM.abort();
await assert.rejects(fifth, (x) => x.name === "AbortError");
await Promise.all(four);
assert.deepEqual([srv.running, srv.waiting.length], [0, 0]);
// a research run on a server: queued while the server finishes another, then running; a look that hangs is given up at
// its own limit and the next one made
srv.pollEvery = 20;
let looks = 0;
globalThis.fetch = async (url, init) => {
  if (new URL(url).pathname === "/api/research") return json({ job: "j1" });
  looks++;
  if (looks === 2) return hang(init.signal);
  return json(looks < 3 ? { status: "queued", elapsed_s: 1 } : looks < 5 ? { status: "running", progress: { round: 1 } }
    : { status: "done", outcome: { ok: true, text: "R" } });
};
const heard = [];
const outcome = await srv.research({ question: "q" }, { onWait: (w) => heard.push(w), onStart: () => heard.push("runs"),
  onProgress: (p) => heard.push(p.status), limits: { poll: 150 } });
assert.deepEqual([outcome, looks], [{ ok: true, text: "R" }, 5]);
assert.deepEqual(heard, ["queued", "queued", "runs", "running", "running", "done"]);
// looks that keep failing (five in a row) lose the run — not as an unavailable server: the run is not started again in
// the browser — and a refusal loses it at once
const site = (fetcher) => {
  globalThis.fetch = fetcher;
  const s = new ServerRuntime("https://chat.impf.ai", "", { fallback: () => { throw new Error("not started again"); } });
  s.pollEvery = 20;
  return s;
};
looks = 0;
let s = site(async (url) => (new URL(url).pathname === "/api/research" ? json({ job: "j2" }) : (looks++, json({ error: "bad gateway" }, 502))));
await assert.rejects(s.research({ question: "q" }, {}), (x) => !x.unavailable && x.message === "与研究任务失去联系：bad gateway");
assert.equal(looks, 5);
looks = 0;
s = site(async (url) => (new URL(url).pathname === "/api/research" ? json({ job: "j3" })
  : (looks++, new Response(JSON.stringify({ error: "今天的查询次数已用完", daily: true }),
    { status: 429, headers: { "Content-Type": "application/json", "X-TC-Corpus": "refused" } }))));
await assert.rejects(s.research({ question: "q" }, {}), (x) => !x.unavailable && /^与研究任务失去联系：今天的查询次数已用完/.test(x.message));
assert.equal(looks, 1);
// a stop while it is looked at ends it at once; one while it is started, too
for (const hangs of ["/api/research/j4", "/api/research"]) {
  globalThis.fetch = (url, init) => (new URL(url).pathname === hangs ? hang(init.signal) : Promise.resolve(json({ job: "j4" })));
  const stopR = counted();
  setTimeout(() => stopR.abort(), 200);
  from = Date.now();
  await assert.rejects(srv.research({ question: "q" }, { signal: stopR.signal }), (x) => x.name === "AbortError");
  assert.ok(Date.now() - from < 1000);
  assert.equal(listening, 0);
}
console.log("ok");
"""


def test_waits_and_stops_under_node(tmp_path):
    """A reply that stalls asked again; a search that never returns ended at its deadline while the chart beside it is
    explained; a stop, the answer asked for, a research run left to go on and the turn's own time; the browser
    runtime's queue, a late result dropped and a runtime held up started again; a server's calls four at a time and
    its research looked at within limits — every listener removed and nothing left waiting."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    shutil.copytree(ROOT / "web" / "js", tmp_path / "js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text(NODE_WAITS, encoding="utf-8")
    run = subprocess.run([node, "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and run.stdout.strip() == "ok", run.stderr[-2000:]


def test_every_tool_the_model_can_call_has_plain_words_on_the_page():
    """The tool steps and the answers name a tool in plain words, never by its inside name (web/js/redact.js): there are
    words for every tool the model can be offered, and none of them is an identifier."""
    from taochronos.chat import ChatRuntime

    source = (ROOT / "web" / "js" / "redact.js").read_text(encoding="utf-8")
    start = source.index("export const TOOL_WORDS")
    words = dict(re.findall(r'"?([a-z_]+(?:\.[a-z_]+)?)"?: "([^"]+)"', source[start:source.index("};", start)]))
    rt = ChatRuntime.create(kind="browser", ephemeral=True)
    tools = {t["tool"] for t in rt.catalog("all")["tools"]} | {t["tool"] for t in rt.catalog("core")["tools"]} | {"research.run_code"}
    assert len(tools) > 70 and not sorted(tools - set(words)), sorted(tools - set(words))
    assert not [w for w in words.values() if re.search(r"[a-z_]", w)], words


def _published(web: Path, relay: str) -> None:
    """The client as the site's build publishes it (.github/workflows/site.yml): the relay's address, and the provider
    list without the presets of the model behind it."""
    from taochronos.chat.providers import web_providers

    shutil.copytree(ROOT / "web", web)
    (web / "site.json").write_text(json.dumps({"relay": relay}), encoding="utf-8")
    (web / "providers.json").write_text(json.dumps(web_providers(["minimax", "minimax-global"]), ensure_ascii=False), encoding="utf-8")


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
    from web_mock import ANSWER, LONG_CUT, MockProvider, MockRelay

    mock = MockProvider().start()
    relay = MockRelay(mock.base_url).start()
    web = tmp_path / "web"
    _published(web, relay.url)
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
            held: list = []

            def hold_the_runtime(route) -> None:  # the page's look for a server passes; the runtime's own start waits
                held.append(route)
                if len(held) != 2:
                    route.continue_()

            page.route("**/api/info", hold_the_runtime)
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            # loading: 加载中 and one bar for the whole load — no step, no percent, no runtime, corpus or counts
            page.wait_for_function("document.querySelector('.hero .status.loading [role=progressbar]')?.getAttribute('aria-valuenow') === '30'",
                                   timeout=30000)
            assert page.inner_text(".hero .status") == "加载中" and page.inner_text(".runtime-pill") == "加载中"
            assert page.get_attribute(".runtime-pill [role=progressbar]", "aria-valuenow") == "30"
            for _ in range(200):
                if len(held) == 2:
                    break
                page.wait_for_timeout(25)
            held[1].continue_()
            page.unroute("**/api/info")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            # ready: the opening screen says nothing of the runtime, and there is no 接入全部古籍 to it
            assert not page.query_selector(".hero .status, .hero .hero-action") and page.inner_text(".runtime-pill") == "运行环境\n已就绪"
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=10000)
            assert page.title() == "道乃久 · 中医古籍研究智能体" and page.inner_text(".hero h1") == "道乃久"
            assert page.inner_text(".hero .publisher") == "医哲未来人工智能研究院（IMPF-AI）发布"
            page.fill("#input", "桂枝汤主治什么？请给出原文。")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            # the answer cited a passage the corpus has not: the self-check named it to the model, which looked again and
            # answered without it; the first answer is kept, folded, its citations not counted under the answer
            cites = page.eval_on_selector_all(".md .cite", "els => els.map(e => [e.dataset.pid, e.className])")
            assert cites == [["shanghanlun.c013", "cite ok"], ["shanghanlun.c012", "cite warn"],
                             ["shanghanlun.c013", "cite ok"]]  # the last quoted in the traditional script
            note = page.inner_text(".msg.assistant .notice.check")
            assert "fake.999" in note and "查无此段" in note and "shanghanlun" not in note
            bar = page.inner_text(".msg.assistant .verify-bar")
            assert "2 条与原文一致" in bar and "1 条存疑" in bar and "查无此段" not in bar
            told = mock.requests[2]["body"]["messages"][-1]
            assert told["role"] == "user" and told["content"].startswith("［自查：") and "[[fake.999]]" in told["content"]
            assert "shanghanlun" not in told["content"]  # only the passage the corpus has not
            assert mock.requests[3]["body"]["messages"][-1]["role"] == "tool"  # looked up again before answering
            page.click(".msg.assistant details.draft summary")
            page.wait_for_function("document.querySelectorAll('.draft .md .cite.pending').length === 0", timeout=15000)
            assert page.eval_on_selector_all(".draft .md .cite", "els => els.map(e => [e.dataset.pid, e.className])") == [
                ["shanghanlun.c013", "cite ok"], ["shanghanlun.c012", "cite warn"], ["fake.999", "cite bad"], ["shanghanlun.c013", "cite ok"]]
            assert page.inner_text(".msg.assistant .verify-bar") == bar  # the answer's own still
            page.click(".msg.assistant details.draft summary")
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
            steps = page.inner_text(".steps .list")
            assert "古籍检索" in steps and "classics" not in steps  # a tool by its plain words
            # the names the model worked with, told in plain words: in the answer and in its thinking, wherever it put them
            assert "以上经古籍检索检得，可用引文核验复核，出处附段落编号。" in page.inner_text(".msg.assistant .md:not(.superseded)")
            said = "".join(page.eval_on_selector_all(".msg.assistant", "els => els.map(e => e.textContent)"))
            assert "古籍检索检索到了原文" in said and not re.search(r"classics|validation|passage_id|__", said)
            assert "繁简" in page.eval_on_selector_all(".md:not(.superseded) .cite.ok", "els => els[1].title")
            page.click(".md:not(.superseded) .cite.ok >> nth=0")
            assert page.inner_text(".passage-view .text mark") == "太阳病，头痛，发热，汗出，恶风，桂枝汤主之"
            # a second turn replays the first verbatim: tool call, reasoning_details, tool result
            page.fill("#input", "它的组成呢？")
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelectorAll('.msg.assistant .verify-bar').length >= 2", timeout=60000)
            first, second = mock.requests[0]["body"], mock.requests[1]["body"]
            assert first["max_completion_tokens"] == 32768 and first["reasoning_split"] is True and first["tools"]  # the relay's ceiling
            # the page asks in the default service's own terms (the relay adds the upstream's), and reads them back
            asked = relay.chat[0]["body"]
            assert asked["model"] == "Tao-R1" and "reasoning_split" not in asked and first["model"] == "MiniMax-M3"
            assert "MiniMax" not in json.dumps(relay.chat, ensure_ascii=False)
            assert first["messages"][0]["role"] == "system" and "[[passage_id]]" in first["messages"][0]["content"]
            system = first["messages"][0]["content"]
            assert system.startswith("你是道乃久") and "MiniMax" not in system and "底层语言模型：" not in system  # no model named
            replay = second["messages"][2]
            assert replay["tool_calls"][0]["function"] == {"name": "classics__search", "arguments": '{"query": "桂枝汤 主之", "k": 3}'}
            assert replay["reasoning_details"][0]["text"] == "用户问桂枝汤的主治，先检索原文。"
            assert replay["reasoning_details"][0]["format"] == "MiniMax-response-v1"  # the page kept it as Tao-…; the relay restores it
            assert second["messages"][3]["role"] == "tool" and "shanghanlun.c013" in second["messages"][3]["content"]
            later = mock.requests[4]["body"]["messages"]  # the first turn whole, the self-check's note in it
            assert [m["role"] for m in later] == ["system", "user", "assistant", "tool", "assistant", "user", "assistant", "tool",
                                                  "assistant", "user"]
            assert later[5]["content"] == told["content"] and "fake.999" not in later[8]["content"]
            # the conversation survives a reload, and keeps nothing of the upstream
            page.reload()
            page.wait_for_selector(".conv.active", timeout=15000)
            assert page.locator(".msg.assistant").count() == 2
            stored = page.evaluate("import('./js/store.js').then((s) => s.listConversations()).then((l) => JSON.stringify(l))")
            assert "MiniMax" not in stored and '"model":"Tao-R1"' in stored and '"format":"Tao-response-v1"' in stored
            # an answer cut at the output limit is written on from where it stopped, and reads as one answer
            asked_before = len(mock.requests)
            page.fill("#input", "请写一篇长篇的桂枝汤论述。")
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelectorAll('.msg.assistant .verify-bar').length >= 3", timeout=60000)
            long = page.locator(".msg.assistant").nth(2)
            assert long.locator(".md").count() == 1 and long.locator(".notice:not(.check)").count() == 0
            assert "《伤寒论》以桂枝汤治太阳中风" in long.inner_text() and "不构成医疗建议" in long.inner_text()
            on = mock.requests[asked_before + 2]["body"]["messages"]  # the round asked to write on: the cut answer, the note
            assert on[-1]["role"] == "user" and on[-1]["content"].startswith("［提示：上面的回答")
            assert on[-2]["role"] == "assistant" and on[-2]["content"] == ANSWER[:LONG_CUT]
            # the answer, written on, self-checked whole: the passage that does not exist named, looked for, and dropped
            told = mock.requests[asked_before + 3]["body"]["messages"][-1]["content"]
            assert len(mock.requests) - asked_before == 5 and told.startswith("［自查：") and "[[fake.999]]" in told
            assert "fake.999" in long.locator(".notice.check").inner_text()
            # one that spent all of it on thinking is asked again without: what it showed of that goes
            asked_before = len(mock.requests)
            page.fill("#input", "这个问题请想得很久再答。")
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelectorAll('.msg.assistant .verify-bar').length >= 4", timeout=60000)
            thought = page.locator(".msg.assistant").nth(3)
            assert "想了又想" not in thought.inner_text() and thought.locator(".md").count() == 1
            assert thought.locator(".notice:not(.check)").count() == 0
            again, cut = mock.requests[asked_before + 2]["body"], mock.requests[asked_before + 1]["body"]
            assert again["thinking"] == {"type": "disabled"} and "thinking" not in cut and again["messages"] == cut["messages"]
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        relay.shutdown()
        mock.shutdown()


def _png_dpi(data: bytes) -> tuple[int, int]:
    """(width in pixels, dots per inch) of a PNG: its IHDR and its pHYs."""
    import struct

    width, at = struct.unpack(">I", data[16:20])[0], 8
    while at < len(data):
        n, kind = struct.unpack(">I4s", data[at: at + 8])
        if kind == b"pHYs":
            ppm, _, unit = struct.unpack(">IIB", data[at + 8: at + 17])
            return width, round(ppm * 0.0254) if unit == 1 else 0
        at += 12 + n
    return width, 0


def _tiff_info(data: bytes) -> tuple[int, int]:
    """(width in pixels, dots per inch) of a little-endian TIFF: its first directory."""
    import struct

    assert data[:4] == b"II*\x00"
    ifd = struct.unpack("<I", data[4:8])[0]
    tags = {}
    for k in range(struct.unpack("<H", data[ifd: ifd + 2])[0]):
        tag, kind, count, value = struct.unpack("<HHII", data[ifd + 2 + 12 * k: ifd + 14 + 12 * k])
        tags[tag] = (kind, count, value)
    num, den = struct.unpack("<II", data[tags[282][2]: tags[282][2] + 8])
    return tags[256][2], num // den


def _docx_text(path) -> str:
    """The paragraphs of a Word document (its tables' cells among them), one a line."""
    import xml.etree.ElementTree as ET
    import zipfile

    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join("".join(t.text or "" for t in p.iter(f"{w}t")) for p in root.iter(f"{w}p"))


def test_charts_in_the_browser(tmp_path):
    """A study's figures and tables under its step — one at a time, a chart as its table or as a journal prints it,
    exported as SVG, PNG and TIFF at a journal's width and resolution, as one figure in panels; a table copied for Word,
    downloaded as Word and LaTeX — a chart the model draws in a ```chart block and a table it writes, and the tool
    console's; the model is told which figures and tables the page shows, never their data."""
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
    _published(web, relay.url)
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    consent = {"v": 1, "logs": False, "at": "2026-09-28T00:00:00Z"}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN", accept_downloads=True)
            ctx.add_init_script(f"localStorage.setItem('tc.consent', {json.dumps(json.dumps(consent))});")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.fill("#input", "用图表比较桂枝汤与麻黄汤")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .actions .meta", timeout=60000)
            # the study's figures and tables, under its step: tabs, one at a time
            tabs = page.eval_on_selector_all(".msg.assistant .charts .chart-tabs [role=tab]", "els => els.map(e => e.textContent)")
            assert tabs == ["图1 配伍比例对照", "图2 方剂相似度", "表1 桂枝汤、麻黄汤的组成与剂量", "表2 方剂两两比较"]
            assert page.locator(".msg.assistant .charts .viz-svg path").count() >= 4  # the bars
            page.click(".msg.assistant .chart-tabs [role=tab] >> nth=1")
            assert page.inner_text(".msg.assistant .charts .viz-card .title") == "图2　方剂相似度"
            # the chart the model drew in its answer, and its table: three-line, with its caption and notes, to Word
            assert page.inner_text(".md figure.viz-card .title") == "桂枝汤与麻黄汤共有之药" and not page.query_selector(".md pre")
            page.click(".md figure.viz-card .viz-toggle >> text=表格")
            assert page.eval_on_selector_all(".md .viz-table tbody tr", "rows => rows.map(r => r.textContent)") == ["桂2", "甘草2"]
            assert page.inner_text(".md .md-table .tbl-cap") == "表1　两方共有之药的剂量"
            assert page.inner_text(".md .md-table .tbl-note").startswith("注：剂量照原书所写")
            page.click(".md .md-table-tools .viz-dl > button")
            with page.expect_download() as word:
                page.click(".md .md-table-tools .viz-menu button >> text=Word 文档（.docx）")
            doc = _docx_text(word.value.path())
            assert word.value.suggested_filename == "表1-两方共有之药的剂量.docx"
            assert "表1　两方共有之药的剂量" in doc and "三两" in doc and "注：剂量照原书所写；n = 2。" in doc
            # a figure's export: a journal's style at its width and resolution — PNG and TIFF say their dpi — SVG, CSV
            card = ".msg.assistant .charts .viz-card"
            page.click(f"{card} .viz-dl > button")
            with page.expect_download() as png:
                page.click(f"{card} .viz-export button >> text=PNG")
            assert png.value.suggested_filename == "图2-方剂相似度.png"
            data = Path(png.value.path()).read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n" and _png_dpi(data) == (1417, 300)  # 120 mm at 300 dpi
            page.check(f"{card} .viz-export input[value=single]")
            page.check(f"{card} .viz-export input[value='600']")
            with page.expect_download() as tif:
                page.click(f"{card} .viz-export button >> text=TIFF")
            assert tif.value.suggested_filename == "图2-方剂相似度.tif" and _tiff_info(Path(tif.value.path()).read_bytes()) == (2008, 600)
            with page.expect_download() as svg_file:
                page.click(f"{card} .viz-export button >> text=SVG")
            figure = Path(svg_file.value.path()).read_text(encoding="utf-8")
            assert 'width="85mm"' in figure and "图2" in figure and "方剂相似度" in figure and "var(--" not in figure
            with page.expect_download() as csv_file:
                page.click(f"{card} .viz-export button >> text=CSV")
            table = Path(csv_file.value.path()).read_text(encoding="utf-8")
            assert table.startswith("\ufeff") and "桂枝汤" in table and "麻黄汤" in table
            page.keyboard.press("Escape")
            # the journal style in the page: what the download gives, its caption under it
            page.click(f"{card} .viz-toggle >> text=期刊样式")
            assert "图2" in page.text_content(f"{card} .viz-paper") and page.is_visible(f"{card} .viz-paper svg")
            # all the figures as one figure in panels; all the tables in one Word document
            page.click(".msg.assistant .chart-all .viz-dl > button")
            with page.expect_download() as panels:
                page.click(".msg.assistant .chart-all .viz-export button >> text=SVG")
            figure = Path(panels.value.path()).read_text(encoding="utf-8")
            assert 'width="175mm"' in figure and "（A）配伍比例对照" in figure and "（B）方剂相似度" in figure
            page.keyboard.press("Escape")
            with page.expect_download() as all_tables:
                page.click(".msg.assistant .chart-all button >> text=全部表格（Word）")
            doc = _docx_text(all_tables.value.path())
            assert "表1　桂枝汤、麻黄汤的组成与剂量" in doc and "表2　方剂两两比较" in doc
            # a table of the study: three-line, its notes under it; LaTeX, and a copy that pastes into Word as a table
            page.click(".msg.assistant .chart-tabs [role=tab] >> nth=2")
            assert page.locator(".msg.assistant .charts .tbl-card .sci-table tbody tr").count() >= 4
            assert page.inner_text(".msg.assistant .tbl-card .tbl-notes").startswith("注：各方取其原方")
            page.click(".msg.assistant .tbl-card .viz-dl > button")
            with page.expect_download() as tex:
                page.click(".msg.assistant .tbl-card .viz-menu button >> text=LaTeX（booktabs）")
            latex = Path(tex.value.path()).read_text(encoding="utf-8")
            assert "\\toprule" in latex and "\\midrule" in latex and "\\bottomrule" in latex and "桂枝汤" in latex
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            page.click(".msg.assistant .tbl-card button >> text=复制")
            page.wait_for_selector(".toast >> text=已复制", timeout=10000)
            copied = page.evaluate("async () => { const [item] = await navigator.clipboard.read(); return await (await item.getType('text/html')).text(); }")
            assert "border-top:1.5pt solid #000" in copied and "表1" in copied and "桂枝汤" in copied
            # what the model read of the result: which figures and tables the page shows, not their data
            told = next(m["content"] for m in mock.requests[1]["body"]["messages"] if m["role"] == "tool")
            assert '"charts_shown":["配伍比例对照","方剂相似度"]' in told and '"heatmap"' not in told
            assert '"tables_shown":["桂枝汤、麻黄汤的组成与剂量","方剂两两比较"]' in told and '"columns"' not in told
            # the tool console draws the charts of what it runs
            page.click("#toggle-drawer")
            page.click(".drawer .tab >> text=工具台")
            page.fill(".drawer input[type=search]", "study.usage")
            page.click(".drawer .tool-item >> nth=0")
            page.fill(".drawer .console-form input[type=text] >> nth=0", "甘草")
            page.click(".drawer .console-form .btn >> text=运行")
            page.wait_for_selector(".drawer .console-form .charts .viz-svg", timeout=30000)
            assert page.locator(".drawer .console-form .chart-tabs [role=tab]").count() >= 2
            # a research protocol run there is offered as a document to download
            page.click(".drawer .console-form .icon-btn[aria-label=关闭]")
            page.fill(".drawer input[type=search]", "study.protocol")
            page.click(".drawer .tool-item >> nth=0")
            page.fill(".drawer .console-form textarea >> nth=0", "桂枝汤与桂枝加桂汤的组成与剂量有何异同？")
            page.click(".drawer .console-form .btn >> text=运行")
            page.wait_for_selector(".drawer .console-form .doc-dl", timeout=60000)
            with page.expect_download() as doc:
                page.click(".drawer .console-form .doc-dl")
            assert doc.value.suggested_filename.endswith("研究方案.md")
            text = Path(doc.value.path()).read_text(encoding="utf-8")
            assert text.startswith("# 桂枝汤") and "证伪条件" in text and "桂枝加桂汤即桂枝汤加重桂之量" in text
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        relay.shutdown()
        mock.shutdown()


def test_a_search_that_does_not_come_back_does_not_hold_up_the_answer(tmp_path):
    """A comparison and a search in one round, the search held: the steps count the comparison done and the search
    running, and after a while offer 不再等待 — taken, the search is not waited for, the model answers from the comparison
    with both calls in their places, and the answer says it may be incomplete; a search held past its deadline ends
    without anyone asking; a stop while one is held leaves the page ready for the next question."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import BOTH, PARTIAL_ANSWER, MockProvider, MockRelay

    mock = MockProvider().start()
    relay = MockRelay(mock.base_url).start()
    web = tmp_path / "web"
    _published(web, relay.url)
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    consent = {"v": 1, "logs": False, "at": "2026-09-28T00:00:00Z"}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.consent', {json.dumps(json.dumps(consent))});")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            held: list = []

            def hold_the_search(route) -> None:  # a search never comes back; every other call does
                if json.loads(route.request.post_data or "{}").get("name") == "classics__search":
                    held.append(route)
                else:
                    route.continue_()

            page.route("**/api/call", hold_the_search)
            page.clock.install()  # the page's own time, which the test moves on
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)

            def held_round(n: int):
                """The n-th answer's round of tools under way: the comparison done, the search held."""
                page.fill("#input", f"用{BOTH}比较桂枝汤与麻黄汤")
                page.keyboard.press("Enter")
                page.wait_for_function(f"document.querySelectorAll('.msg.assistant')[{n}]?.querySelector('.steps .head')"
                                       "?.textContent.includes('正在调用工具（1/2）')", timeout=60000)
                return page.locator(".msg.assistant").nth(n)

            def told() -> list[dict]:
                """What the model was told of the calls, in the last request."""
                return [m for m in mock.requests[-1]["body"]["messages"] if m["role"] == "tool"]

            # the comparison done, the search running: so the steps say, and after a while the page offers the answer
            first = held_round(0)
            assert first.locator(".steps .tool .st.ok").count() == 1 and first.locator(".steps .tool .st .spinner").count() == 1
            assert first.locator(".steps .tool .row > .sm").nth(1).text_content() == "运行中…" and not first.locator(".steps .offer").count()
            page.clock.fast_forward(21000)
            page.wait_for_selector(".msg.assistant .steps .offer button", timeout=10000)
            assert first.locator(".steps .tool .row > .ms").nth(1).text_content().endswith("秒")  # how long the search has run
            # taken: the search is not waited for, and the model answers from the comparison, told what it did not get
            asked = len(mock.requests)
            page.click(".msg.assistant .steps .offer button")
            page.wait_for_selector(".msg.assistant .actions .meta", timeout=60000)
            assert PARTIAL_ANSWER in first.locator(".md").inner_text()
            assert "你选择了不再等待工具，回答可能不完整。" in first.locator(".notice.err").inner_text()
            assert first.locator(".steps .tool .st.ok").count() == 1 and first.locator(".steps .tool .st.warn").count() == 1
            assert first.locator(".steps .tool .row > .sm").nth(1).text_content() == "没有等它：你选择了先看回答"
            assert len(mock.requests) == asked + 1 and [m["tool_call_id"] for m in told()] == ["call_1", "call_2"]
            assert not told()[0]["content"].startswith("ERROR") and "桂枝汤" in told()[0]["content"]
            assert told()[1]["content"].startswith("ERROR: 用户想先看到回答，这个调用没有等到结果。")
            assert "［提示：用户想先看到回答，请根据已有结果直接作答" in told()[1]["content"]
            # held past its deadline — two minutes of the page's time — the search ends, and the model is asked without it
            second = held_round(1)
            page.clock.fast_forward(61000)
            page.clock.fast_forward(61000)
            page.wait_for_function("document.querySelectorAll('.msg.assistant .actions .meta').length >= 2", timeout=60000)
            assert second.locator(".steps .tool .st.warn").count() == 1 and not second.locator(".notice").count()
            assert second.locator(".steps .tool .row > .sm").nth(1).text_content() == "运行了 120 秒还没有完成，不再等待"
            assert told()[-1]["content"].startswith("ERROR: 这个调用运行了 120 秒还没有完成，页面不再等待，结果不可用。")
            # a stop while it is held: the call ends as stopped, and the page is ready for the next question
            third = held_round(2)
            page.click("#send.stop")
            page.wait_for_function("!document.querySelector('#send').classList.contains('stop')", timeout=10000)
            assert third.locator(".steps .tool .st.off").count() == 1 and third.locator(".notice.warn").count() == 1
            assert len(held) == 3
            page.unroute("**/api/call")
            for route in held:
                try:
                    route.abort()
                except Error:
                    pass  # the page has given it up already
            # and the next question is answered — one the model searches for twice, in two rounds, each call under the
            # same id (a service that numbers its calls afresh in each reply): each step ends as its own
            page.fill("#input", "桂枝汤主治什么？请再查一遍原文。")
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelectorAll('.msg.assistant')[3]?.querySelector('.verify-bar')", timeout=60000)
            fourth = page.locator(".msg.assistant").nth(3)
            assert [m["tool_call_id"] for m in mock.requests[-1]["body"]["messages"] if m["role"] == "tool"][-2:] == ["call_1", "call_1"]
            # its answer cites the passage that does not exist: the self-check's round searches once more, its call under
            # the same id again
            assert fourth.locator(".notice.check").count() == 1 and fourth.locator(".steps .tool .st.ok").count() == 3
            assert fourth.locator(".steps .tool .row > .sm").all_inner_texts() == ["3 条命中"] * 3
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
    from web_mock import ANSWER, LONG_CUT, MockAnthropic

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
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
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
            # the passage that does not exist, named by the self-check: looked for again, and the answer is given without it
            told = mock.requests[2]["body"]["messages"][-1]
            assert told["role"] == "user" and told["content"].startswith("［自查：") and "[[fake.999]]" in told["content"]
            assert mock.requests[3]["body"]["messages"][-1]["content"][0]["type"] == "tool_result"
            assert page.eval_on_selector_all(".md .cite", "els => els.map(e => e.className)") == ["cite ok", "cite warn", "cite ok"]
            assert first["body"]["max_tokens"] == 64000  # no number set: what Anthropic advises for a streamed reply

            def turn(question: str, n: int) -> list[dict]:
                """Ask, wait for the n-th answer, and return the requests the turn made."""
                before = len(mock.requests)
                page.fill("#input", question)
                page.keyboard.press("Enter")
                page.wait_for_function(f"document.querySelectorAll('.msg.assistant .verify-bar').length >= {n}", timeout=60000)
                return [r["body"] for r in mock.requests[before:]]

            def self_checked(asked: list[dict], at: int) -> bool:
                """The at-th request is the self-check's note on the passage that does not exist; the next, its search."""
                note = asked[at]["messages"][-1]["content"]
                return note.startswith("［自查：") and "[[fake.999]]" in note and len(asked) == at + 2

            # a reply whose stream ended part-way, or stopped without saying why, is asked again, not taken as the answer
            # (which, citing the passage that does not exist, the self-check then has rewritten)
            asked = turn("断流也请答：桂枝汤主治什么？", 2)
            assert asked[1] == asked[2] == asked[3] and self_checked(asked, 4)
            broken = page.locator(".msg.assistant").nth(1)
            assert broken.locator(".notice:not(.check)").count() == 0 and "不构成医疗建议" in broken.inner_text()
            # an answer cut at max_tokens is written on from where it stopped, as one answer, and is self-checked whole
            asked = turn("请写一篇长篇的桂枝汤论述。", 3)
            assert asked[2]["messages"][-1]["content"].startswith("［提示：上面的回答在输出上限处被截断了")
            assert asked[2]["messages"][-2]["content"][-1]["text"] == ANSWER[:LONG_CUT] and self_checked(asked, 3)
            long = page.locator(".msg.assistant").nth(2)
            assert long.locator(".md").count() == 1 and long.locator(".notice:not(.check)").count() == 0
            assert "不构成医疗建议" in long.inner_text()
            # one that spent all of it on thinking is asked again at low effort, still thinking (newer models always do)
            asked = turn("这个问题请想得很久再答。", 4)
            assert asked[2]["output_config"] == {"effort": "low"} and "output_config" not in asked[1] and self_checked(asked, 3)
            assert asked[2]["thinking"] == asked[1]["thinking"] and asked[2]["messages"] == asked[1]["messages"]
            thought = page.locator(".msg.assistant").nth(3)
            assert "想了又想" not in thought.inner_text() and thought.locator(".notice:not(.check)").count() == 0
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
            page = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN").new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{pages.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.bad", timeout=30000)  # no browser runtime here, no server known
            page.click(".hero-action")
            page.fill(".connect-row input[type=url]", f"http://127.0.0.1:{api.server_address[1]}/")
            page.click(".connect-row .btn")
            page.wait_for_selector(".connect .notice.warn", timeout=30000)  # connected: a server with only the demonstration corpus
            assert "尚未构建全量语料" in page.inner_text(".connect .notice.warn")
            # and nothing more of it, the settings neither: no 当前：…, no runtime, no counts
            pane = page.inner_text(".settings-pane")
            assert not any(w in pane for w in ("当前：", "本地服务", "项工具", "万段", "画像")), pane
            page.click(".modal-foot .btn:not(.secondary)")
            # the page itself says only that it is ready: no runtime, corpus or counts, and no 接入全部古籍 on the opening screen
            assert page.inner_text(".runtime-pill") == "运行环境\n已就绪" and page.inner_text("#hint") == "Tao-R1"
            assert page.query_selector(".hero") and not page.query_selector(".hero .status, .hero .hero-action")
            page.reload()  # auto mode: the server this browser worked with, first (this page has no runtime of its own)
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.click(".runtime-pill")
            page.wait_for_selector(".connect .notice.warn", timeout=10000)  # that server, with its demonstration corpus
            assert "当前：" not in page.inner_text(".settings-pane")
            page.click(".modal-foot .btn.secondary")
            assert json.loads(page.evaluate("localStorage.getItem('tc.settings')"))["runtime"] == "auto"

            page = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN").new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{locked.server_address[1]}/#token=t0ken")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert "token" not in page.url
            assert json.loads(page.evaluate("localStorage.getItem('tc.settings')"))["serverToken"] == "t0ken"
            page = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN").new_page()
            page.goto(f"http://127.0.0.1:{locked.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.bad", timeout=30000)
            assert "访问令牌" in page.inner_text(".hero .status")  # what went wrong is said, and how to put it right

            # the server this browser knew is down, so the browser's own runtime takes over: the bar never goes back
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
            ctx.add_init_script("""localStorage.setItem('tc.server', JSON.stringify('http://127.0.0.1:9'));
              window.__bars = [];
              const seen = (n) => n.nodeType === 1 && [n, ...n.querySelectorAll('[role=progressbar]')]
                .forEach((b) => b.getAttribute('role') === 'progressbar' && __bars.push(+b.getAttribute('aria-valuenow')));
              new MutationObserver((ms) => ms.forEach((m) => m.type === 'attributes' ? seen(m.target) : m.addedNodes.forEach(seen)))
                .observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-valuenow'] });""")
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{pages.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.bad", timeout=30000)  # and this page has no browser runtime either
            bars = page.evaluate("window.__bars")
            assert 12 in bars and bars == sorted(bars), bars

            # the server that served the page answers the page's look, then cannot start: the browser takes over without a word
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            seen: list = []

            def then_down(route) -> None:
                seen.append(route)
                if len(seen) == 2:
                    route.fulfill(status=503, content_type="application/json", body=json.dumps({"error": "全量语料服务未部署"}))
                else:
                    route.continue_()

            page.route("**/api/info", then_down)
            page.goto(f"http://127.0.0.1:{api.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.bad", timeout=30000)  # the browser's runtime is not on this server
            bars = page.evaluate("window.__bars")
            assert len(seen) >= 2 and 30 in bars and bars == sorted(bars), bars
            assert not page.query_selector(".toast"), page.inner_text(".toasts")
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
            page = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN").new_page()
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
    _published(web, relay.url)
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
            assert "桂枝汤" in rec["answer"] and rec["status"] == "done" and rec["provider"] == "impf" and rec["model"] == "Tao-R1"
            # the answer as the visitor read it, and how many inside names it was spared (redact.js)
            assert "以上经古籍检索检得，可用引文核验复核，出处附段落编号。" in rec["answer"] and rec["redacted"] == 3
            assert rec["tools"] and rec["tools"][0]["name"].startswith("classics") and rec["tools"][0]["ok"]
            # the answer that stands (the self-check had the one citing a passage the corpus has not answered again), and
            # every round the turn took
            assert rec["citations"]["total"] == 3 and rec["citations"]["bad"] == 0 and rec["citations"]["pending"] == 0
            assert rec["usage"] == {"input": 2400, "output": 360} and rec["rounds"] == 4 and len(rec["tools"]) == 2
            assert not {"apiKey", "keys", "settings"} & set(rec) and MockRelay.SECRET not in json.dumps(rec)
            assert relay.chat and all("authorization" not in {k.lower() for k in c["headers"]} for c in relay.chat)  # no key from the page
            assert all(r["headers"].get("Authorization") == f"Bearer {MockRelay.SECRET}" for r in mock.requests)
            assert relay.chat[0]["body"]["model"] == "Tao-R1"
            assert relay.chat[0]["body"]["max_completion_tokens"] == 32768  # the relay's ceiling (no number set): forwarded unchanged
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
    _published(web, relay.url)
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
            # and, touching who answers, it is asked without thinking; what thinking comes is neither shown nor kept
            assert all(c["body"]["thinking"] == {"type": "disabled"} for c in relay.chat[asked:])
            assert "thinking" not in relay.chat[0]["body"]
            assert page.locator(".msg.assistant").nth(2).locator(".think").count() == 0
            assert page.locator(".msg.assistant").nth(1).locator(".think").count() >= 1  # a research question keeps its thinking
            stored = page.evaluate("import('./js/store.js').then((s) => s.listConversations()).then((l) => JSON.stringify(l[0].messages.at(-1)))")
            assert "reasoning" not in stored and "用户问桂枝汤" not in stored and "桂枝汤" in stored, stored[:500]
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
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.settings', {json.dumps(json.dumps(settings))});")
            page = ctx.new_page()
            fetched = []
            page.on("request", lambda r: fetched.append(r.url))
            page.goto(f"http://taochronos.test:{site.server_address[1]}/")
            assert page.evaluate("() => !window.isSecureContext && typeof caches === 'undefined'")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=240000)
            assert page.inner_text(".runtime-pill") == "运行环境\n已就绪" and not page.query_selector(".hero .status")
            # the rest of the 要籍 is indexed in the background: not shown on the page, but the pill carries it for scripts
            page.wait_for_selector(".runtime-pill[data-indexing]", state="attached", timeout=60000)
            page.wait_for_selector(".runtime-pill:not([data-indexing])", state="attached", timeout=240000)
            page.click(".runtime-pill")  # the settings' 运行环境 says nothing of the runtime or its corpus either
            page.wait_for_selector(".settings-pane .connect", timeout=10000)
            assert "当前：" not in page.inner_text(".settings-pane") and not page.query_selector(".settings-pane .notice")
            page.click(".modal-foot .btn.secondary")
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


# ------------------------------------------------------------------ 我的资料
def _clinic_csv(path: Path, rows: int = 30) -> Path:
    """A clinic's prescriptions as a Chinese Excel saves them (GB18030): names, telephones and identity card numbers that
    must never leave the machine, a diagnosis to compare and the prescriptions to read."""
    import random

    rng = random.Random(7)
    bases = {"感冒": ["柴胡", "黄芩", "半夏", "党参", "甘草", "生姜", "大枣"], "咳嗽": ["麻黄", "杏仁", "甘草", "石膏"],
             "腹痛": ["白芍", "甘草", "桂枝", "生姜", "大枣"]}
    lines = ["姓名,电话,身份证号,性别,年龄,诊断,处方,疗效"]
    for i in range(rows):
        dx = list(bases)[i % 3]
        drugs = [d for d in bases[dx] if rng.random() > 0.12 or d in bases[dx][:2]]
        rx = "柴胡12g 黄芩9g 半夏9g 党参15g 甘草6g" if i == 0 else " ".join(f"{d}{rng.choice([6, 9, 12])}g" for d in drugs)
        lines.append(f"张{'三四五'[i % 3]}{i},1380013{i:04d},11010519491231{i:03d}X,{'男女'[i % 2]},{20 + i},{dx},{rx},"
                     f"{rng.choice(['有效', '无效'])}")
    path.write_bytes("\n".join(lines).encode("gb18030"))
    return path


def test_my_data_with_a_server_on_this_machine(tmp_path):
    """我的资料 with `taochronos serve` on this machine: the notice before the first upload, a GB18030 CSV read and made
    anonymous by the server, attached to a message, its prescriptions analysed with figures and tables, a row cited and
    checked — and nothing that names a patient sent to the model, no record of the turn sent to the relay."""
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
    _published(web, relay.url)
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    csv_file = _clinic_csv(tmp_path / "门诊处方.csv")
    consent = {"v": 1, "logs": True, "at": "2026-10-11T00:00:00Z"}  # the visitor agreed to records: still none of this
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
            # the first upload: what happens to the data, before any file is chosen
            page.click("#attach-data")
            page.wait_for_selector("dialog.data-notice[open]", timeout=10000)
            notice = page.inner_text("dialog.data-notice")
            assert "在本机处理" in notice and "读取时即脱敏" in notice and "不记录" in notice and "模型读到什么" in notice
            with page.expect_file_chooser() as chooser:
                page.click("dialog.data-notice .btn:not(.secondary)")
            chooser.value.set_files(str(csv_file))
            page.wait_for_selector("#attachments .data-chip:not(.busy)", timeout=30000)
            assert page.inner_text("#attachments .data-chip .nm") == "门诊处方.csv"
            assert "表格 30 行 · 8 列" in page.inner_text("#attachments .data-chip")
            [ds] = rt.data_list()["datasets"]
            assert {c["name"]: c["type"] for c in ds["columns"]}["处方"] == "prescription"
            assert ds["preview"][0]["姓名"] == "P0001" and ds["preview"][0]["电话"] == "" and ds["preview"][0]["身份证号"] == "ID0001"
            # the side panel lists it, with what was taken out
            page.click("#toggle-drawer")
            page.click(".drawer .tab:has-text('资料')")
            card = page.inner_text(".data-card")
            assert "门诊处方.csv" in card and "化名" in card and "电话已删除" in card and ds["id"] in card
            # a message with the data: the model reads its shape, analyses it with the tools, cites its first row
            page.fill("#input", "分析这些处方的用药规律")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            assert "门诊处方.csv" in page.inner_text(".msg.user .data-chips")
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            assert page.eval_on_selector_all(".md .cite", "els => els.map(e => [e.dataset.pid, e.className])") == \
                [[f"mine:{ds['id']}.r1", "cite ok"]]
            page.click(".steps .head")
            assert "处方用药分析" in page.inner_text(".steps .list") and "mydata" not in page.inner_text(".steps .list")
            tabs = page.eval_on_selector_all(".msg.assistant .charts .chart-tabs [role=tab]", "els => els.map(e => e.textContent)")
            assert len(tabs) >= 10 and any("高频药物" in t for t in tabs) and any("最相近的经典方" in t for t in tabs), tabs
            assert "道乃久（TaoChronos）· 用户资料（本机分析）" in page.inner_text(".msg.assistant .charts .viz-card")
            page.click(".md .cite.ok")
            assert "第 1 行" in page.inner_text(".passage-view") and "柴胡12g 黄芩9g" in page.inner_text(".passage-view .text")
            first = mock.requests[0]["body"]
            assert "［本条消息附有用户上传的资料" in json.dumps(first, ensure_ascii=False)
            assert "mydata__prescriptions" in [t["function"]["name"] for t in first["tools"]]
            sent = json.dumps(mock.requests, ensure_ascii=False) + json.dumps(relay.chat, ensure_ascii=False)
            assert "张三" not in sent and "13800130000" not in sent and "110105" not in sent  # names, telephones, ID numbers
            assert "P0001" in sent  # the model read the rows it asked for, made anonymous
            time.sleep(1.5)
            assert relay.records == []  # a conversation that touches the user's data is never recorded
            # removed from the side panel: gone from the server
            page.click(".drawer .tab:has-text('资料')")
            page.once("dialog", lambda d: d.accept())
            page.click(".data-card .icon-btn")
            page.wait_for_selector(".data-pane .pane-empty", timeout=10000)
            assert rt.data_list()["datasets"] == []
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        relay.shutdown()
        mock.shutdown()


# a stand-in for Pyodide (pyodide.mjs): the worker's Python runs in the test's CPython, behind a server of the test's
# (PY: its address, "" when it is the site's own) — the worker's own code, its IndexedDB and the page are the real ones
STAND_IN = r"""
const PY = "{py}";
function post(path, body, type) {
  const x = new XMLHttpRequest();
  x.open("POST", PY + path, false); // a worker may wait: Python's calls are synchronous too
  x.setRequestHeader("Content-Type", type || "text/plain");
  x.send(body);
  if (x.status !== 200) throw new Error(x.responseText);
  return x.responseText;
}
export async function loadPyodide() {
  post("/py/start", "{}"); // a new visit: a new interpreter
  const rpc = (method, params) => post("/py/rpc", JSON.stringify({ method, params }));
  return {
    loadPackage: async () => {},
    unpackArchive: () => {},
    runPython: (code) => (code.includes("purelib") ? "/lib/python3.13/site-packages" : undefined),
    globals: { get: (name) => (name === "_rpc" ? rpc : undefined), set: () => {} },
    FS: {
      mkdirTree: () => {},
      writeFile: (path, bytes) => post(`/py/fs?path=${encodeURIComponent(path)}`, bytes, "text/plain"),
      unlink: (path) => post(`/py/fs?path=${encodeURIComponent(path)}&unlink=1`, ""),
    },
  };
}
"""


def _browser_runtime(site: Path, tmp: Path, py: str = "") -> None:
    """The in-browser runtime's files in ``site``, with the stand-in for Pyodide (its Python behind ``py``)."""
    (site / "runtime").mkdir(exist_ok=True)
    (site / "runtime" / "manifest.json").write_text(json.dumps({"version": "test", "pyodide_base": "pyodide/",
                                                                "files": {"taochronos.zip": {}, "home.zip": {}}}), encoding="utf-8")
    for name in ("taochronos.zip", "home.zip"):
        (site / "runtime" / name).write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (site / "pyodide").mkdir(exist_ok=True)
    (site / "pyodide" / "pyodide.mjs").write_text(STAND_IN.replace("{py}", py), encoding="utf-8")


def _python_behind(site: Path, tmp: Path):
    """A server of the site's files and of the stand-in's Python (the worker's BOOT code, run here): /py/start a new
    interpreter, /py/rpc a call, /py/fs the files the worker writes (kept in ``tmp``/uploads, where its Python reads them)."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlsplit

    source = (ROOT / "web" / "js" / "worker.js").read_text(encoding="utf-8")
    boot = re.search(r"const BOOT = `(.*?)`;", source, re.S).group(1).replace("/home/pyodide/data", str(tmp / "data"))
    uploads = tmp / "uploads"
    uploads.mkdir(exist_ok=True)
    reading = 'with open(p["path"], "rb") as f:'
    assert reading in boot
    boot = boot.replace(reading, f'with open({str(uploads)!r} + "/" + p["path"].rsplit("/", 1)[-1], "rb") as f:')
    python: dict = {}

    class Site(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript", ".js": "text/javascript"}

        def log_message(self, *args) -> None:
            pass

        def end_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            url = urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if url.path == "/py/start":
                python.clear()
                python.update(_profile="full-discovery")
                exec(boot, python)  # noqa: S102 — the worker's own Python
                out = b"null"
            elif url.path == "/py/rpc":
                call = json.loads(body)
                out = python["_rpc"](call["method"], call["params"]).encode("utf-8")
            elif url.path == "/py/fs":
                q = {k: v[-1] for k, v in parse_qs(url.query).items()}
                name = uploads / Path(q["path"]).name
                name.unlink(missing_ok=True) if q.get("unlink") else name.write_bytes(body)
                out = b"null"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Site, directory=str(site)))
    server.python, server.uploads = python, uploads
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


MINE_KEYS = ("() => new Promise((ok) => { const r = indexedDB.open('taochronos-runtime'); r.onsuccess = () => { "
             "const q = r.result.transaction('files').objectStore('files').getAllKeys(); q.onsuccess = () => ok(q.result.filter((k) => "
             "String(k).startsWith('mydata:'))); }; })")


def _prescriptions_book(tmp: Path) -> Path:
    from officefiles import xlsx

    rows = [["姓名", "联系电话", "诊断", "处方"]] + [[f"王{i}", f"1370000{i:04d}", ["感冒", "咳嗽"][i % 2],
                                                     "柴胡12g 黄芩9g 半夏9g 甘草6g" if i % 2 == 0 else "麻黄9g 杏仁9g 甘草6g 石膏30g"]
                                                    for i in range(12)]
    book = tmp / "处方.xlsx"
    book.write_bytes(xlsx(rows))
    return book


def test_my_data_in_the_browsers_own_runtime(tmp_path):
    """我的资料 with TaoChronos in the browser (the published site's runtime): an Excel workbook read by the worker's
    Python, its anonymous dataset kept in IndexedDB and given back to the runtime at the next visit, analysed through the
    tools the page offers while there is data, removed from IndexedDB with the dataset."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from web_mock import MockProvider

    site = tmp_path / "site"
    shutil.copytree(ROOT / "web", site)
    _browser_runtime(site, tmp_path)
    server = _python_behind(site, tmp_path)
    mock = MockProvider().start()
    settings = {"provider": "custom-e2e", "customProviders": [{"id": "custom-e2e", "label": "测试网关", "format": "openai",
                "base_url": mock.base_url, "model": "test-model"}], "keys": {"custom-e2e": "k"}, "route": "direct", "runtime": "browser"}
    book = _prescriptions_book(tmp_path)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.settings', {json.dumps(json.dumps(settings))});"
                                "localStorage.setItem('tc.mydata.notice', JSON.stringify({v: 1}));")  # the notice: the other test
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=60000)
            page.set_input_files("#data-file", str(book))
            page.wait_for_selector("#attachments .data-chip:not(.busy)", timeout=30000)
            assert "表格 12 行 · 4 列" in page.inner_text("#attachments .data-chip")
            [kept] = page.evaluate(MINE_KEYS)
            ds = kept.split(":", 1)[1]
            # the next visit: a new interpreter, the dataset given back from IndexedDB before the runtime answers
            page.reload()
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=60000)
            page.click("#toggle-drawer")
            page.click(".drawer .tab:has-text('资料')")
            page.wait_for_selector(".data-card", timeout=10000)
            assert "处方.xlsx" in page.inner_text(".data-card") and "联系电话已删除" in page.inner_text(".data-card")
            page.click(".data-card .btn.secondary")  # 附到消息
            page.fill("#input", "分析这些处方的用药规律")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            assert page.eval_on_selector_all(".md .cite", "els => els.map(e => [e.dataset.pid, e.className])") == [[f"mine:{ds}.r1", "cite ok"]]
            assert "王0" not in json.dumps(mock.requests, ensure_ascii=False) and "P0001" in json.dumps(mock.requests, ensure_ascii=False)
            page.click(".drawer .tab:has-text('资料')")
            page.once("dialog", lambda d: d.accept())
            page.click(".data-card .icon-btn")
            page.wait_for_selector(".data-pane .pane-empty", timeout=10000)
            assert page.evaluate(MINE_KEYS) == []
            assert not list(server.uploads.iterdir())  # the worker removed the file it was handed
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        mock.shutdown()


def test_my_data_stays_in_the_browser_when_the_site_answers(tmp_path):
    """The page working with the site's own server (one other machines reach, like the published site's): the user's
    data is read by a runtime of the page's own in this browser — the server is never sent it, and refuses it — and
    the 我的资料 tools and the rows they cite are answered there, the rest by the server."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockProvider

    web = tmp_path / "web"
    shutil.copytree(ROOT / "web", web)
    python = _python_behind(tmp_path, tmp_path)  # the stand-in's Python, apart from the site
    _browser_runtime(web, tmp_path, py=f"http://127.0.0.1:{python.server_address[1]}")
    mock = MockProvider().start()
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "server-data")
    srv = ChatServer(("0.0.0.0", 0), rt, web_root=web, home=ROOT)  # reached by its name: not this machine's to the page
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    settings = {"provider": "custom-e2e", "customProviders": [{"id": "custom-e2e", "label": "测试网关", "format": "openai",
                "base_url": mock.base_url, "model": "test-model"}], "keys": {"custom-e2e": "k"}, "route": "direct"}
    book = _prescriptions_book(tmp_path)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}),
                                            args=["--host-resolver-rules=MAP taochronos.test 127.0.0.1"])
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.settings', {json.dumps(json.dumps(settings))});"
                                "localStorage.setItem('tc.mydata.notice', JSON.stringify({v: 1}));")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            calls: list[str] = []  # what the page asked of the server: each request's address and body
            page.on("request", lambda r: calls.append(f"{r.url} {r.post_data or ''}") if "/api/" in r.url else None)
            page.goto(f"http://taochronos.test:{srv.server_address[1]}/")
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert page.evaluate("() => location.hostname") == "taochronos.test"
            page.set_input_files("#data-file", str(book))
            page.wait_for_selector("#attachments .data-chip:not(.busy)", timeout=60000)
            assert rt.data_list()["datasets"] == [] and len(page.evaluate(MINE_KEYS)) == 1  # in this browser, not the server
            page.fill("#input", "分析这些处方的用药规律")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            page.wait_for_function("document.querySelectorAll('.md .cite.pending').length === 0", timeout=15000)
            [[pid, cls]] = page.eval_on_selector_all(".md .cite", "els => els.map(e => [e.dataset.pid, e.className])")
            assert pid.startswith("mine:") and cls == "cite ok"
            assert not [u for u in calls if "/api/data" in u or "mine" in u or "mydata" in u or "王0" in u]  # nothing of it
            assert any("/api/info" in u for u in calls) and rt.data_list()["datasets"] == []
            [ds] = python.python["_rt"].data_list()["datasets"]  # read and analysed by the browser's own runtime
            assert ds["name"] == "处方.xlsx" and pid.startswith(f"mine:{ds['id']}.")
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        python.shutdown()
        mock.shutdown()


def test_the_page_in_eight_languages(tmp_path):
    """A browser not set to Chinese reads the page in its own language if the page has it (the six of the United Nations,
    Traditional Chinese and Malay), else in English; the menu in the top bar changes it, and the choice is kept
    (web/js/i18n.js).  Arabic is laid out right to left.  A browser set to Chinese, as the tests above, reads it in
    Chinese."""
    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer

    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=ROOT / "web", home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            errors: list[str] = []

            def opened(locale: str, path: str = ""):
                page = browser.new_context(viewport={"width": 1280, "height": 860}, locale=locale).new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url + path)
                page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
                return page

            page = opened("en-SG")
            assert page.evaluate("[document.documentElement.lang, document.documentElement.dir]") == ["en", "ltr"]
            assert page.inner_text("#new-chat").startswith("New chat")
            assert page.get_attribute("#input", "placeholder").startswith("Ask a question")
            assert page.inner_text(".runtime-pill") == "Runtime\nReady"
            assert "Formula origins" in page.inner_text(".starters")  # the server's starters, in English
            page.click("#settings-btn")
            assert "Model" in page.inner_text(".settings-pane")
            page.keyboard.press("Escape")
            # the menu: every language by its own name, the page's chosen
            assert page.eval_on_selector_all("#lang-select option", "os => os.map((o) => o.textContent)") == [
                "简体中文", "繁體中文", "English", "Français", "Español", "Русский", "العربية", "Bahasa Melayu"]
            assert page.input_value("#lang-select") == "en" and page.inner_text(".lang-short") == "EN"
            page.select_option("#lang-select", "zh")  # to Chinese, kept in this browser
            page.wait_for_function("document.documentElement.lang === 'zh-CN'", timeout=30000)
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert "新对话" in page.inner_text("#new-chat") and page.inner_text(".lang-short") == "简"
            assert page.evaluate("localStorage.getItem('tc.lang')") == '"zh"'
            page.goto(url + "?lang=fr")  # a link can ask for a language
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert page.inner_text("#new-chat").startswith("Nouvelle conversation")
            assert page.inner_text(".runtime-pill") == "Environnement\nPrêt"

            # the browser's own language, where the page has it; Traditional Chinese for Taiwan, Hong Kong and Macau
            for locale, lang, new_chat in [("zh-TW", "zh-Hant", "新對話"), ("es-ES", "es", "Nueva conversación"),
                                           ("ru-RU", "ru", "Новый чат"), ("ms-SG", "ms", "Sembang baharu"), ("de-DE", "en", "New chat")]:
                page = opened(locale)
                assert page.evaluate("document.documentElement.lang") == lang, locale
                assert page.inner_text("#new-chat").startswith(new_chat), locale
            page = opened("ar-EG")
            assert page.evaluate("[document.documentElement.lang, document.documentElement.dir]") == ["ar", "rtl"]
            assert page.inner_text("#new-chat").startswith("محادثة جديدة")
            # right to left: the conversation list on the right
            sidebar, main = page.eval_on_selector_all("#sidebar, #main", "es => es.map((e) => e.getBoundingClientRect().x)")
            assert sidebar > main
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
