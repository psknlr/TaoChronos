// The relay under Node: the request handler and the two stores on an in-memory SQLite (node:sqlite), a mock MiniMax.
// Run: node --test relay/test/

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { drain, EVENTS, RECORDS } from "../../security/archive.js";
import { WatchCore } from "../../security/sentinel.js";
import { config, handle, normalizeRecord, publicText, withoutReasoning } from "../src/relay.js";
import { LimiterCore, LogBookCore } from "../src/state.js";
import { UsageCore } from "../../security/usage.js";

/** The Durable Object SQL API's shape over node:sqlite. */
function sqlStore() {
  const db = new DatabaseSync(":memory:");
  return {
    exec(query, ...params) {
      const stmt = db.prepare(query);
      const rows = /^\s*select|returning/i.test(query) ? stmt.all(...params) : (stmt.run(...params), []);
      return {
        toArray: () => rows,
        one: () => {
          if (rows.length !== 1) throw new Error(`expected one row, got ${rows.length}`);
          return rows[0];
        },
      };
    },
  };
}

const KEY = "relay-test-key-not-a-real-one";
const TOKEN = "export-token-0123456789abcdef";
const PAGE = "https://chat.impf.ai";

/** The relay with its stores in memory.  `cf`: what the edge would say of every request (request.cf). */
function relay({ env = {}, upstream, now = () => Date.UTC(2026, 8, 28, 12, 0, 0), cf, burst, gateFails = false } = {}) {
  const limiter = new LimiterCore(sqlStore());
  const watch = new WatchCore(sqlStore());
  const book = new LogBookCore(sqlStore());
  const usage = new UsageCore(sqlStore());
  const calls = [];
  const pending = [];
  const bursts = [];
  const observe = async (fp, a, extra, cfg) => watch.observe(fp, a, extra, cfg, now());
  const deps = {
    limit: async (who, kind, limits) => limiter.hit(who, kind, limits, now()),
    // as the Durable Object does it (relay/src/index.js): the sentinel first, then the counters
    gate: async ({ who, kind, limits, fp, a, shape, status, cfg, served, reserve, usage: counted }) => {
      if (gateFails) throw new Error("Durable Object: daily limit reached");
      const w = fp && a ? await observe(fp, a, { shape, status }, cfg) : null;
      if (w?.blocked) return { ok: false, reason: "blocked", retry: w.retry, watch: w };
      const keys = fp ? [await WatchCore.who(fp.ip, cfg, now()), await WatchCore.who(fp.ip, cfg, now() - 86400000)] : [];
      if (served && !(fp ? limiter.wasServed(keys, now()) : limiter.served(who, served, now()))) return { ok: false, reason: "not_served", retry: 0, watch: w };
      const gate = limiter.hit(who, kind, limits, now(), reserve);
      if (gate.ok && kind === "chat" && keys.length) limiter.markServed(keys[0], now());
      if (gate.ok && kind === "chat" && counted) usage.call(counted, keys[0]);
      return { ...gate, watch: w };
    },
    stats: async (days, today) => usage.stats(days, today),
    observe,
    spend: async (who, kind, tokens) => limiter.spend(who, kind, tokens, now()),
    burst: async (key) => { bursts.push(key); return burst ? burst(key) : true; },
    watch: { observe, records: async (...a) => watch.records(...a), remove: async (...a) => watch.remove(...a), summary: async () => watch.summary(now()) },
    defer: (p) => { pending.push(Promise.resolve(p).catch(() => {})); },
    logbook: { add: async (...a) => book.add(...a), records: async (...a) => book.records(...a), remove: async (...a) => book.remove(...a) },
    fetch: async (url, init) => {
      calls.push({ url, init, body: JSON.parse(init.body) });
      return upstream ? upstream(url, init) : sse(["{\"choices\":[{\"delta\":{\"content\":\"可以\"}}]}", "[DONE]"]);
    },
    now,
  };
  const fullEnv = { MINIMAX_API_KEY: KEY, LOG_EXPORT_TOKEN: TOKEN, ...env };
  const call = (path, init = {}) => {
    const request = new Request(`https://chat-api.impf.ai${path}`, init);
    if (cf) request.cf = cf;
    return handle(request, fullEnv, deps);
  };
  const settle = () => Promise.all(pending.splice(0)); // what the Worker finishes after the answer (ctx.waitUntil)
  return { call, calls, book, limiter, watch, usage, settle, bursts };
}

function sse(events) {
  const body = events.map((e) => `data: ${e}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const BROWSER = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
  Accept: "text/event-stream", "Accept-Language": "zh-CN,zh;q=0.9", "Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
  "Sec-CH-UA": '"Chromium";v="129"' };
const post = (body, headers = {}) => ({
  method: "POST", headers: { "Content-Type": "application/json", Origin: PAGE, "CF-Connecting-IP": "203.0.113.7", ...BROWSER, ...headers },
  body: typeof body === "string" ? body : JSON.stringify(body),
});

const ask = { model: "MiniMax-M3", messages: [{ role: "user", content: "桂枝汤主治什么？" }], stream: true, max_completion_tokens: 100000, n: 3 };

// ------------------------------------------------------------------ the model calls
test("the key is added by the relay, the page never has it; the stream passes through", async () => {
  const r = relay();
  const res = await r.call("/v1/chat/completions", post(ask));
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("Content-Type"), "text/event-stream");
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), PAGE);
  assert.match(await res.text(), /可以/);
  const [c] = r.calls;
  assert.equal(c.url, "https://api.minimax.cn/v1/chat/completions");
  assert.equal(c.init.headers.Authorization, `Bearer ${KEY}`);
  assert.equal(c.body.max_completion_tokens, 32768); // capped
  assert.equal(c.body.n, undefined);
  assert.equal(c.body.reasoning_split, true); // the upstream's own parameter, added here: the page sends none
  for (const [, v] of res.headers) assert.ok(!v.includes(KEY));
});

test("asked for no thinking, the relay lets no reasoning through, however the stream is cut", async () => {
  const events = [
    '{"choices":[{"delta":{"reasoning_details":[{"type":"reasoning.text","text":"底层是某模型"}],"reasoning_content":"想"}}]}',
    '{"choices":[{"delta":{"content":"<think>内心独白</think>欢迎使用"}}]}',
    '{"choices":[{"delta":{"content":"道乃久"}}]}',
    "[DONE]",
  ];
  const whole = events.map((e) => `data: ${e}\n\n`).join("");
  const cut = (text) => { // the upstream's bytes in pieces that split events, lines and characters
    const bytes = new TextEncoder().encode(text);
    return new Response(new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += 7) c.enqueue(bytes.slice(i, i + 7)); c.close(); } }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };
  const hidden = await relay({ upstream: () => cut(whole) }).call("/v1/chat/completions", post({ ...ask, thinking: { type: "disabled" } }));
  const text = await hidden.text();
  assert.ok(!/reasoning|底层是某模型|内心独白|think>/.test(text), text);
  assert.match(text, /欢迎使用/);
  assert.match(text, /道乃久/);
  assert.match(text, /data: \[DONE\]/);
  const plain = await relay({ upstream: () => cut(whole) }).call("/v1/chat/completions", post(ask));
  assert.match(await plain.text(), /reasoning_details/); // otherwise the stream passes through as it came
  const json = await relay({ upstream: () => new Response(JSON.stringify({ choices: [{ message: { content: "答", reasoning_content: "想" } }] }),
    { status: 200, headers: { "Content-Type": "application/json" } }) }).call("/v1/chat/completions", post({ ...ask, thinking: { type: "disabled" } }));
  assert.deepEqual(await json.json(), { choices: [{ message: { content: "答" } }] });
  // a <think> block streamed in pieces, or cumulatively: none of it passes
  const read = (chunks) => { const open = new Map(); return chunks.map((c) => withoutReasoning({ choices: [{ delta: { content: c } }] }, open).choices[0].delta.content).join("|"); };
  assert.equal(read(["<think>一", "二", "三</think>答", "案"]), "||答|案");
  assert.equal(read(["<think>一", "<think>一二", "<think>一二</think>答", "<think>一二</think>答案"]), "||答|答案");
});

test("a request the relay need not change goes on byte for byte", async () => {
  const r = relay();
  const raw = JSON.stringify({ model: "MiniMax-M3", messages: [{ role: "user", content: "桂枝汤" }], stream: true, max_completion_tokens: 8192,
    reasoning_split: true });
  assert.equal((await r.call("/v1/chat/completions", post(raw))).status, 200);
  assert.equal(r.calls[0].init.body, raw);
});

test("only the page's origins, only the allowed models, bodies within the limit", async () => {
  const r = relay();
  assert.equal((await r.call("/v1/chat/completions", post(ask, { Origin: "https://evil.example" }))).status, 403);
  const noOrigin = post(ask);
  delete noOrigin.headers.Origin;
  assert.equal((await r.call("/v1/chat/completions", noOrigin)).status, 403);
  const other = await r.call("/v1/chat/completions", post({ ...ask, model: "MiniMax-M2.7" }));
  assert.equal(other.status, 400);
  const refused = (await other.json()).error.message;
  assert.match(refused, /默认服务不提供这个模型/);
  assert.doesNotMatch(refused, /MiniMax|M3/); // the models the upstream has are not named
  const big = await relay({ env: { MAX_BODY_BYTES: "1000" } }).call("/v1/chat/completions", post({ ...ask, messages: [{ role: "user", content: "字".repeat(2000) }] }));
  assert.equal(big.status, 413);
  const declared = post(ask, { "Content-Length": "5000" }); // a declared length over the limit is refused before reading
  assert.equal((await relay({ env: { MAX_BODY_BYTES: "1000" } }).call("/v1/chat/completions", declared)).status, 413);
  const cjk = await relay({ env: { MAX_BODY_BYTES: "3000" } }).call("/v1/chat/completions",
    post({ ...ask, messages: [{ role: "user", content: "字".repeat(1500) }] })); // 1 500 characters, 4 500 bytes
  assert.equal(cjk.status, 413);
  const unset = await relay({ env: { MINIMAX_API_KEY: "" } }).call("/v1/chat/completions", post(ask));
  assert.equal(unset.status, 503);
  assert.equal(r.calls.length, 0); // none of these reached MiniMax
  const noModel = relay();
  await noModel.call("/v1/chat/completions", post({ messages: ask.messages }));
  assert.equal(noModel.calls[0].body.model, "MiniMax-M3");
  assert.equal(noModel.calls[0].body.max_completion_tokens, 32768);
});

test("a visitor sees none of the upstream: its model, its reasoning formats, its fields, its errors", async () => {
  const events = [
    '{"id":"a1","choices":[{"index":0,"delta":{"role":"assistant"}}],"created":1,"model":"MiniMax-M3","object":"chat.completion.chunk","usage":null}',
    '{"id":"a1","choices":[{"index":0,"delta":{"reasoning_content":"想","reasoning_details":[{"type":"reasoning.text","id":"r1","format":"MiniMax-response-v1","index":0,"text":"想"}]}}],"model":"MiniMax-M3"}',
    '{"id":"a1","choices":[{"index":0,"delta":{"content":"答：\\"model\\":\\"MiniMax-M3\\" 是原文"}}],"model":"MiniMax-M3","input_sensitive":false,"output_sensitive":false}',
    '{"id":"a1","choices":[{"finish_reason":"stop","index":0,"delta":{}}],"model":"MiniMax-M3","base_resp":{"status_code":0,"status_msg":""},"usage":{"total_characters":0,"prompt_tokens":3,"completion_tokens":2}}',
    "[DONE]",
  ];
  const whole = events.map((e) => `data: ${e}\n\n`).join("");
  const cut = () => { // in pieces that split events, lines and characters
    const bytes = new TextEncoder().encode(whole);
    return new Response(new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += 5) c.enqueue(bytes.slice(i, i + 5)); c.close(); } }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };
  const r = relay({ upstream: cut });
  // the page asks for the default service's model by its public name, and sends back the reasoning under the public format
  const history = [{ role: "user", content: "问" },
    { role: "assistant", content: "答", reasoning_details: [{ type: "reasoning.text", id: "r1", format: "Tao-response-v1", index: 0, text: "想" }] },
    { role: "user", content: "再问" }];
  const res = await r.call("/v1/chat/completions", post({ model: "Tao-R1", messages: history, stream: true, max_completion_tokens: 1000 }));
  assert.equal(res.status, 200);
  const text = await res.text();
  const visible = text.replace(/\\"model\\":\\"MiniMax-M3\\"/g, ""); // the answer's own words, which are the visitor's text
  assert.doesNotMatch(visible, /MiniMax|minimax|base_resp|_sensitive|total_characters/, text);
  assert.match(text, /"model":"Tao-R1"/);
  assert.match(text, /"format":"Tao-response-v1"/);
  assert.match(text, /答：\\"model\\":\\"MiniMax-M3\\" 是原文/); // content is never rewritten
  assert.match(text, /"usage":\{"prompt_tokens":3/);
  assert.match(text, /data: \[DONE\]/);
  for (const line of text.split("\n").filter((l) => l.startsWith("data: {"))) JSON.parse(line.slice(6)); // every event still JSON
  // the upstream is asked in its own terms
  const [c] = r.calls;
  assert.equal(c.body.model, "MiniMax-M3");
  assert.equal(c.body.reasoning_split, true);
  assert.equal(c.body.messages[1].reasoning_details[0].format, "MiniMax-response-v1");
  // an error the upstream reports inside the stream is told in the default service's words
  const failing = relay({ upstream: () => sse(['{"id":"b","choices":[],"model":"MiniMax-M3","base_resp":{"status_code":1027,"status_msg":"output new_sensitive MiniMax"}}', "[DONE]"]) });
  const f = await (await failing.call("/v1/chat/completions", post(ask))).text();
  assert.doesNotMatch(f, /MiniMax|sensitive|1027/);
  assert.match(f, /默认服务出错了/);
  // a plain JSON reply too
  const plain = relay({ upstream: async () => new Response(JSON.stringify({ id: "c", model: "MiniMax-M3", choices: [{ message: { content: "好" } }],
    base_resp: { status_code: 0, status_msg: "" } }), { status: 200, headers: { "Content-Type": "application/json" } }) });
  const pj = await (await plain.call("/v1/chat/completions", post({ ...ask, stream: false }))).json();
  assert.deepEqual(pj, { id: "c", model: "Tao-R1", choices: [{ message: { content: "好" } }] });
  // the request is edited as text: its model and formats, never what a message says (a quote inside it is escaped)
  const said = '{"model":"Tao-R1","format":"Tao-x"} 与 "format":"Tao-y"';
  const edited = relay({ upstream: cut });
  await (await edited.call("/v1/chat/completions", post({ model: "Tao-R1", messages: [{ role: "user", content: said }, ...history.slice(1)],
    stream: true, max_completion_tokens: 1000 }))).text();
  const sent = edited.calls[0];
  assert.ok(sent.init.body.startsWith('{"model":"MiniMax-M3","reasoning_split":true,"messages":')); // not written anew
  assert.equal(sent.body.messages[0].content, said);
  assert.equal(sent.body.messages[1].reasoning_details[0].format, "MiniMax-response-v1");
  // a stream in \r\n lines, with a comment, and the upstream's fields in its last event
  const crlf = relay({ upstream: () => new Response(": ping\r\n\r\n" + events.slice(0, 2).map((e) => `data: ${e}\r\n\r\n`).join("") +
    'data: {"id":"a1","choices":[],"model":"MiniMax-M3","usage":{"total_characters":0,"prompt_tokens":3},"base_resp":{"status_code":0}}\r\n\r\n' +
    "data: [DONE]\r\n\r\n", { status: 200, headers: { "Content-Type": "text/event-stream" } }) });
  const c2 = await (await crlf.call("/v1/chat/completions", post(ask))).text();
  assert.doesNotMatch(c2, /MiniMax|base_resp|total_characters/, c2);
  assert.match(c2, /"usage":\{"prompt_tokens":3\}/);
  assert.equal(c2.split("\n").filter((l) => l.startsWith("data: {")).map((l) => JSON.parse(l.slice(6).trim())).length, 3);
  // only the configured upstream's formats are renamed; any other passes as it is
  assert.match(publicText('{"format":"Other-v1","model":"x"}', config({})), /"format":"Other-v1","model":"Tao-R1"/);
  assert.match(publicText('{"format":"MiniMax-response-v1"}', config({ FORMAT_PREFIX: "Other-" })), /"format":"MiniMax-response-v1"/);
});

test("preflight: allowed origins only", async () => {
  const r = relay();
  const ok = await r.call("/v1/chat/completions", { method: "OPTIONS", headers: { Origin: "http://chat.impf.ai", "Access-Control-Request-Method": "POST" } });
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), "http://chat.impf.ai");
  assert.match(ok.headers.get("Access-Control-Allow-Headers"), /Content-Type/);
  const bad = await r.call("/v1/chat/completions", { method: "OPTIONS", headers: { Origin: "https://evil.example" } });
  assert.equal(bad.status, 403);
  assert.equal(bad.headers.get("Access-Control-Allow-Origin"), null);
});

test("limits: per visitor per minute, per visitor per day, all visitors per day", async () => {
  const r = relay({ env: { PER_MINUTE: "2", PER_DAY: "3", TOTAL_PER_DAY: "4" } });
  assert.equal((await r.call("/v1/chat/completions", post(ask))).status, 200);
  assert.equal((await r.call("/v1/chat/completions", post(ask))).status, 200);
  const minute = await r.call("/v1/chat/completions", post(ask));
  assert.equal(minute.status, 429);
  assert.ok(Number(minute.headers.get("Retry-After")) > 0);
  assert.equal(minute.headers.get("Access-Control-Expose-Headers"), "Retry-After"); // the page waits as long as it is asked
  assert.match((await minute.json()).error.message, /每分钟最多 2 次/);
  let t = Date.UTC(2026, 8, 28, 12, 5, 0);
  const later = relay({ env: { PER_MINUTE: "10", PER_DAY: "2", TOTAL_PER_DAY: "3" }, now: () => t });
  assert.equal((await later.call("/v1/chat/completions", post(ask))).status, 200);
  assert.equal((await later.call("/v1/chat/completions", post(ask))).status, 200);
  const day = await later.call("/v1/chat/completions", post(ask));
  assert.equal(day.status, 429);
  assert.match((await day.json()).error.message, /今天的免费额度已用完/);
  assert.equal((await later.call("/v1/chat/completions", post(ask, { "CF-Connecting-IP": "198.51.100.1" }))).status, 200);
  const total = await later.call("/v1/chat/completions", post(ask, { "CF-Connecting-IP": "198.51.100.2" }));
  assert.equal(total.status, 429);
  assert.match((await total.json()).error.message, /总额度/);
  t = Date.UTC(2026, 8, 29, 0, 0, 1); // a new day
  assert.equal((await later.call("/v1/chat/completions", post(ask))).status, 200);
});

test("MiniMax's refusals become messages a visitor can act on, without its details of the key", async () => {
  const auth = relay({ upstream: async () => new Response(JSON.stringify({ error: { message: "invalid api key sk-cp-***" } }), { status: 401 }) });
  const a = await auth.call("/v1/chat/completions", post(ask));
  assert.equal(a.status, 503);
  const msg = (await a.json()).error.message;
  assert.match(msg, /默认服务暂时不可用/);
  assert.ok(!msg.includes("sk-"));
  const quota = relay({ upstream: async () => new Response(JSON.stringify({ base_resp: { status_code: 1008, status_msg: "insufficient balance" } }),
    { status: 200, headers: { "Content-Type": "application/json" } }) });
  const q = await quota.call("/v1/chat/completions", post(ask));
  assert.equal(q.status, 503);
  assert.match((await q.json()).error.message, /额度已用完/);
  const rate = relay({ upstream: async () => new Response(JSON.stringify({ error: { message: "MiniMax rate limit" } }), { status: 429 }) });
  const rr = await rate.call("/v1/chat/completions", post(ask));
  assert.equal(rr.status, 429);
  assert.doesNotMatch((await rr.json()).error.message, /MiniMax|rate limit/);
  // its other refusals in its own words (they name it, its models, its parameters): told in the default service's
  const said = { error: { message: "invalid params, temperature of MiniMax-M3 must be in (0, 1] (api.minimax.cn)" } };
  const bad = await relay({ upstream: async () => new Response(JSON.stringify(said), { status: 400 }) }).call("/v1/chat/completions", post(ask));
  assert.equal(bad.status, 400);
  const badMsg = (await bad.json()).error.message;
  assert.match(badMsg, /默认服务无法完成这个请求/);
  assert.doesNotMatch(badMsg, /MiniMax|minimax|temperature/);
  const broken = await relay({ upstream: async () => new Response("MiniMax internal error", { status: 500 }) }).call("/v1/chat/completions", post(ask));
  assert.equal(broken.status, 502);
  assert.doesNotMatch(JSON.stringify(await broken.json()), /MiniMax/);
  const odd = relay({ upstream: async () => new Response(JSON.stringify({ base_resp: { status_code: 2013, status_msg: "invalid params, MiniMax-M3" } }),
    { status: 200, headers: { "Content-Type": "application/json" } }) });
  const o = await odd.call("/v1/chat/completions", post(ask));
  assert.equal(o.status, 502);
  assert.doesNotMatch(JSON.stringify(await o.json()), /MiniMax|2013/);
  const down = relay({ upstream: async () => { throw new TypeError("network"); } });
  assert.equal((await down.call("/v1/chat/completions", post(ask))).status, 502);
});

test("health says what the page needs, nothing secret", async () => {
  const r = relay();
  const res = await r.call("/v1/health", { headers: { Origin: PAGE } });
  const j = await res.json();
  assert.deepEqual([j.ok, j.model, j.models, j.logs], [true, "Tao-R1", ["Tao-R1"], true]);
  assert.doesNotMatch(JSON.stringify(j), /MiniMax|minimax/); // the upstream is not named
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), PAGE);
  assert.ok(!JSON.stringify(j).includes(KEY) && !JSON.stringify(j).includes(TOKEN));
  const bare = await relay({ env: { MINIMAX_API_KEY: "", LOGS: "off" } }).call("/v1/health");
  assert.deepEqual([(await bare.json()).ok], [false]);
});

// ------------------------------------------------------------------ the records
const turn = {
  v: 1, id: "t1", conversation: "c_x", turn: 1, question: "桂枝汤主治什么？", answer: "太阳中风……[[cm_shanghan_npm.00012]]",
  model: "Tao-R1", provider: "impf", runtime: "browser", corpus: "canon", ms: 12345, status: "done",
  tools: [{ name: "classics.search", ok: true, ms: 80, args: "{\"query\":\"桂枝汤\"}", extra: "dropped" }],
  citations: { total: 2, ok: 2, warn: 0, bad: 0, pending: 0, pids: ["cm_shanghan_npm.00012"] }, usage: { input: 1200, output: 180, cost: "x" },
  apiKey: "must not be kept", settings: { keys: { minimax: "x" } },
};

test("a record is kept only as its known fields, from the page, within its limits", async () => {
  const r = relay();
  // a record of the default service's conversation: only from a visitor the relay answered today
  const unserved = await r.call("/v1/logs", post(turn));
  assert.equal(unserved.status, 403);
  assert.equal((await unserved.json()).error.type, "not_served");
  assert.equal((await r.call("/v1/logs", post({ ...turn, provider: "openai", model: "gpt-x" }))).status, 204); // a conversation held with the visitor's own key
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK))).status, 200);
  assert.equal((await r.call("/v1/logs", post(turn))).status, 204);
  // a turn answered before midnight, its record sent after: taken
  let t = Date.UTC(2026, 8, 28, 23, 59, 30);
  const late = relay({ now: () => t });
  assert.equal((await late.call("/v1/chat/completions", post(PAGE_ASK))).status, 200);
  t = Date.UTC(2026, 8, 29, 0, 0, 30);
  assert.equal((await late.call("/v1/logs", post(turn))).status, 204);
  t = Date.UTC(2026, 8, 30, 3, 0, 0); // more than a day on: no longer
  assert.equal((await late.call("/v1/logs", post(turn))).status, 403);
  assert.equal((await r.call("/v1/logs", post(turn, { Origin: "https://evil.example" }))).status, 403);
  assert.equal((await r.call("/v1/logs", post({ ...turn, v: 2 }))).status, 400);
  assert.equal((await r.call("/v1/logs", post("{not json"))).status, 400);
  assert.equal((await relay({ env: { LOGS: "off" } }).call("/v1/logs", post(turn))).status, 404);
  const { items } = r.book.records(0, 10);
  assert.equal(items.length, 2);
  const kept = items[1].record;
  assert.equal(kept.question, turn.question);
  assert.equal(kept.model, "MiniMax-M3"); // the page's public name, kept as the model that answered
  assert.equal(kept.apiKey, undefined);
  assert.equal(kept.settings, undefined);
  assert.equal(kept.tools[0].extra, undefined);
  assert.equal(kept.citations.ok, 2);
  assert.deepEqual(kept.usage, { input: 1200, output: 180 });
  const long = normalizeRecord({ ...turn, answer: "字".repeat(30000), question: "问".repeat(5000) });
  assert.equal(long.answer.length, 20000);
  // how many inside names the page told in plain words in the answer it shows (web/js/redact.js): kept, as a number
  assert.equal(normalizeRecord({ ...turn, redacted: 5 }).redacted, 5);
  assert.equal(normalizeRecord({ ...turn, redacted: "5" }).redacted, undefined);
  assert.equal(long.question.length, 4000);
  assert.equal(normalizeRecord({ v: 1, question: "" }), null);
  assert.equal(normalizeRecord([1]), null);
  // where the turn's time went (web/js/records.js, timings): numbers and short words only, within their limits
  const timed = normalizeRecord({
    ...turn,
    tools: [{ ...turn.tools[0], ok: false, id: "call_1", round: 1, status: "timeout", at: 1200, wait: 300, compute: 80 }],
    requests: [
      { round: 1, attempt: 1, sent: 5, open: 400, first: 410, text: 900, last: 1100, end: 1101, finish: "tool_calls", input: 1200, output: 80, body: "dropped" },
      { round: 1, attempt: 2, sent: 1200, end: 1300, failed: "overloaded_error", status: 529 },
      ...Array.from({ length: 60 }, (_, i) => ({ round: 2, attempt: i + 1, failed: "timeout".repeat(20), expired: "silence", sent: "5", status: "503" })),
    ],
    events: [{ at: 1500, what: "asked" }, { at: "soon", what: { no: 1 } }, null],
    hidden: 2000, asleep: "0", was: { runtime: "server", corpus: "full", url: "https://x.example" },
  });
  assert.deepEqual(timed.tools[0], { name: "classics.search", ok: false, ms: 80, args: "{\"query\":\"桂枝汤\"}", id: "call_1", round: 1,
    status: "timeout", at: 1200, wait: 300, compute: 80 });
  assert.deepEqual(timed.requests[0], { round: 1, attempt: 1, sent: 5, open: 400, first: 410, text: 900, last: 1100, end: 1101,
    finish: "tool_calls", input: 1200, output: 80 });
  assert.equal(timed.requests.length, 48);
  assert.deepEqual(timed.requests[1], { round: 1, attempt: 2, sent: 1200, end: 1300, failed: "overloaded_error", status: 529 });
  assert.deepEqual(timed.requests[2], { round: 2, attempt: 1, failed: "timeout".repeat(20).slice(0, 40), expired: "silence" });
  assert.deepEqual(timed.events, [{ at: 1500, what: "asked" }, {}, {}]);
  assert.deepEqual([timed.hidden, timed.asleep, timed.was], [2000, undefined, { runtime: "server", corpus: "full" }]);
  // an older page's record has none of them
  assert.deepEqual(Object.keys(normalizeRecord(turn)).filter((k) => ["requests", "events", "hidden", "asleep", "was"].includes(k)), []);
});

test("the collector: token required, records after its cursor, deleted once committed, ids never reused", async () => {
  const r = relay();
  await r.call("/v1/chat/completions", post(PAGE_ASK));
  for (let k = 0; k < 5; k++) await r.call("/v1/logs", post({ ...turn, turn: k + 1 }));
  assert.equal(r.book.records(0, 10).items.length, 5);
  assert.equal((await r.call("/v1/logs/export?after=0")).status, 401);
  assert.equal((await r.call("/v1/logs/export?after=0", { headers: { Authorization: "Bearer wrong-token-0123456789" } })).status, 401);
  const auth = { Authorization: `Bearer ${TOKEN}` };
  const page1 = await (await r.call("/v1/logs/export?after=0&limit=3", { headers: auth })).json();
  assert.deepEqual([page1.items.length, page1.last, page1.more], [3, 3, true]);
  assert.ok(page1.items[0].received.startsWith("2026-09-28T12:00"));
  const page2 = await (await r.call(`/v1/logs/export?after=${page1.last}&limit=3`, { headers: auth })).json();
  assert.deepEqual([page2.items.length, page2.last, page2.more], [2, 5, false]);
  assert.equal((await r.call("/v1/logs/ack", { method: "POST", body: JSON.stringify({ through: 5 }) })).status, 401);
  const ack = await (await r.call("/v1/logs/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: 5 }) })).json();
  assert.equal(ack.remaining, 0);
  await r.call("/v1/logs", post({ ...turn, turn: 6 }));
  const next = await (await r.call("/v1/logs/export?after=5", { headers: auth })).json();
  assert.deepEqual(next.items.map((i) => i.id), [6]); // not 1 again: the collector's cursor stays valid
  const weak = relay({ env: { LOG_EXPORT_TOKEN: "short" } });
  assert.equal((await weak.call("/v1/logs/export", { headers: { Authorization: "Bearer short" } })).status, 401);
});

test("with the archive's bucket the records and events go there: the repository's collector is told, and may not delete", () => quiet(async () => {
  const objects = new Map();
  const ARCHIVE = {
    put: async (key, body) => { objects.set(key, body); return { key }; },
    get: async (key) => (objects.has(key) ? { text: async () => objects.get(key) } : null),
    list: async ({ prefix }) => ({ objects: [...objects.keys()].filter((k) => k.startsWith(prefix)).sort().map((key) => ({ key })), truncated: false }),
  };
  const r = relay({ env: { ARCHIVE } });
  await r.call("/v1/chat/completions", post(PAGE_ASK));
  assert.equal((await r.call("/v1/logs", post({ ...turn, turn: 1 }))).status, 204);
  const auth = { Authorization: `Bearer ${TOKEN}` };
  const page = await (await r.call("/v1/logs/export?after=0", { headers: auth })).json();
  assert.equal(page.archive, "r2"); // the collector stands down (relay/collect.py)
  const refused = await r.call("/v1/logs/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: 1 }) });
  assert.equal(refused.status, 409);
  assert.equal(r.book.waiting(), 1); // still there, for the archive
  await drain(r.book, ARCHIVE, { prefix: RECORDS, field: "record" }); // what the Durable Object's alarm does (relay/src/index.js)
  assert.equal(r.book.waiting(), 0);
  const day = await (await r.call("/v1/logs/archive?day=2026-09-28", { headers: auth })).json();
  assert.deepEqual(day.items.map((i) => [i.n, i.turn, i.model]), [[1, 1, "MiniMax-M3"]]);
  assert.equal((await r.call("/v1/logs/archive?day=2026-09-28")).status, 401);
  // the sentinel's events: the same
  assert.equal((await r.call("/wp-config.php", { headers: { "CF-Connecting-IP": "45.138.12.10" } })).status, 404);
  await r.settle();
  assert.equal((await (await r.call("/v1/security/export", { headers: auth })).json()).archive, "r2");
  assert.equal((await r.call("/v1/security/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: 1 }) })).status, 409);
  await drain(r.watch, ARCHIVE, { prefix: EVENTS("relay"), field: "event", extra: { source: "relay" } });
  const events = await (await r.call("/v1/security/archive?day=2026-09-28", { headers: auth })).json();
  assert.deepEqual(events.items.map((e) => [e.source, e.kind]), [["relay", "honeypot"]]);
  // without the bucket: as before (the repository's collector acknowledges), and no archive to read
  const plain = relay();
  assert.equal((await (await plain.call("/v1/logs/export?after=0", { headers: auth })).json()).archive, undefined);
  assert.equal((await plain.call("/v1/logs/archive?day=2026-09-28", { headers: auth })).status, 404);
}));

test("a full book refuses the next record and keeps every one it took in", () => quiet(async () => {
  const r = relay({ env: { LOG_KEEP: "3" } });
  await r.call("/v1/chat/completions", post(PAGE_ASK));
  for (let k = 1; k <= 3; k++) assert.equal((await r.call("/v1/logs", post({ ...turn, turn: k }))).status, 204);
  const errors = [];
  const log = console.error;
  console.error = (...a) => errors.push(a.join(" "));
  try {
    const full = await r.call("/v1/logs", post({ ...turn, turn: 4 }));
    assert.equal(full.status, 503);
    assert.equal((await full.json()).error.type, "logs_full");
  } finally { console.error = log; }
  assert.deepEqual(errors, ["logs full 3"]); // said in the Worker's logs, where the owner's alerts look
  assert.deepEqual(r.book.records(0, 10).items.map((i) => i.record.turn), [1, 2, 3]); // none dropped to make room
  const auth = { Authorization: `Bearer ${TOKEN}` };
  await r.call("/v1/logs/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: 2 }) });
  assert.equal((await r.call("/v1/logs", post({ ...turn, turn: 5 }))).status, 204); // room again once collected
  assert.equal(r.book.waiting(), 2);
  // LOG_KEEP = 0: no bound, and the count stays true — also for an object started again over the records it kept
  const sql = sqlStore();
  const before = new LogBookCore(sql);
  for (let k = 1; k <= 3; k++) assert.equal(before.add(JSON.stringify({ ...turn, turn: k }), "2026-10-14T00:00:00Z", 0), k);
  const restarted = new LogBookCore(sql);
  restarted.add(JSON.stringify(turn), "2026-10-14T00:00:00Z", 0);
  assert.equal(restarted.waiting(), 4);
}));

// ------------------------------------------------------------------ the sentinel
const PAGE_ASK = { model: "Tao-R1", messages: [{ role: "system", content: "你是道乃久" }, { role: "user", content: "桂枝汤主治什么？" }], stream: true,
  tools: [{ type: "function", function: { name: "classics.search" } }], max_completion_tokens: 8192, stream_options: { include_usage: true } };
const quiet = async (fn) => { const log = console.log; console.log = () => {}; try { return await fn(); } finally { console.log = log; } };

test("a scanner path refuses its address for a day; the page's requests score nothing and leave only a count", () => quiet(async () => {
  let t = Date.UTC(2026, 8, 28, 12, 0, 0);
  const r = relay({ now: () => t });
  const probe = await r.call("/wp-config.php.bak", { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "45.138.12.10" } });
  assert.equal(probe.status, 404);
  await r.settle();
  t += 61000; // a minute on: the scanner tries the API
  const refused = await r.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "45.138.12.10" }));
  assert.equal(refused.status, 403);
  assert.equal((await refused.json()).error.type, "blocked");
  assert.equal(Number(refused.headers.get("Retry-After")), 21600 - 61); // a home network's address: the ordinary six hours
  assert.equal((await r.call("/v1/logs", post(turn, { "CF-Connecting-IP": "45.138.12.10" }))).status, 403);
  assert.equal(r.calls.length, 0); // nothing reached MiniMax
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK))).status, 200); // another address
  const auth = { Authorization: `Bearer ${TOKEN}` };
  const { items } = await (await r.call("/v1/security/export", { headers: auth })).json();
  assert.deepEqual(items.map((i) => i.event.kind), ["honeypot", "blocked"]); // the refused requests of the same minute: one event
  assert.deepEqual([items[0].event.fp.ip, items[0].event.fp.path, items[0].event.fp.uaClass, items[0].event.status], ["45.138.12.10", "/wp-config.php.bak", "tool", 404]);
  assert.deepEqual(items[1].event.decision, { mode: "observe", blocked: true, shadow: false, until: "2026-09-28T18:00:00.000Z" });
  const summary = await (await r.call("/v1/security/summary", { headers: auth })).json();
  assert.equal(summary.blocked.length, 1);
  assert.equal(summary.blocked[0].ip, "45.138.12.10");
  const page = summary.top.find((v) => v.ip === undefined);
  assert.deepEqual([page.n, page.score, page.flagged], [1, 0, 0]); // the page's visitor: a count, no address
  assert.equal((await r.call("/v1/security/export")).status, 401);
  assert.equal((await r.call("/v1/security/summary", { headers: { Authorization: "Bearer not-the-token-0123456789" } })).status, 401);
  assert.deepEqual(await (await r.call("/v1/security/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: items[1].id }) })).json(), { remaining: 0 });
  // a browser's policy report is kept as an event
  const csp = await r.call("/v1/security/csp", { method: "POST", headers: { "Content-Type": "application/csp-report", Origin: PAGE },
    body: JSON.stringify({ "csp-report": { "violated-directive": "script-src", "blocked-uri": "https://evil.example/x.js" } }) });
  assert.equal(csp.status, 204);
  assert.equal((await (await r.call("/v1/security/export", { headers: auth })).json()).items[0].event.kind, "csp");
}));

test("what is not the page's is scored: served and flagged in observe mode, refused in enforce mode; the owner's clients stay under the line", () => quiet(async () => {
  const script = { "User-Agent": "python-requests/2.31.0", Accept: "application/json", "Accept-Language": "", "Sec-Fetch-Site": "", "Sec-Fetch-Mode": "",
    "Sec-Fetch-Dest": "", "Sec-CH-UA": "", "CF-Connecting-IP": "198.51.100.77" };
  const bare = { model: "Tao-R1", messages: [{ role: "user", content: "hi" }], max_tokens: 50 };
  const observe = relay({ cf: { asn: 14061, country: "US", httpProtocol: "HTTP/1.1", tlsVersion: "TLSv1.3" } });
  const served = await observe.call("/v1/chat/completions", post(bare, script));
  assert.equal(served.status, 200);
  assert.equal(observe.calls.length, 1);
  const auth = { Authorization: `Bearer ${TOKEN}` };
  const [ev] = (await (await observe.call("/v1/security/export", { headers: auth })).json()).items;
  assert.equal(ev.event.kind, "shadow"); // would have been refused in enforce mode
  assert.deepEqual(ev.event.reasons, ["ua_tool", "dc_asn", "no_stream", "no_stream_options", "max_tokens_key", "no_tools", "no_system"]);
  assert.deepEqual([ev.event.fp.ip, ev.event.fp.asn, ev.event.shape.system, ev.event.decision.shadow], ["198.51.100.77", 14061, false, true]);
  const enforce = relay({ env: { SENTINEL: "enforce" }, cf: { asn: 14061, country: "US" } });
  const refused = await enforce.call("/v1/chat/completions", post(bare, script));
  assert.equal(refused.status, 403);
  assert.equal(enforce.calls.length, 0);
  assert.equal(Number(refused.headers.get("Retry-After")), 21600);
  assert.equal((await enforce.call("/v1/chat/completions", post(PAGE_ASK))).status, 200); // the page, from another address
  // a flagged request under the block score is served in enforce mode too (the collector's check call is one)
  const check = { "User-Agent": "taochronos-collector/1", Accept: "application/json", "Accept-Language": "", "Sec-Fetch-Site": "", "Sec-Fetch-Mode": "",
    "Sec-Fetch-Dest": "", "Sec-CH-UA": "", "CF-Connecting-IP": "198.51.100.78" };
  assert.equal((await enforce.call("/v1/chat/completions", post({ model: "Tao-R1", messages: [{ role: "user", content: "请只回复两个字：可以" }], max_completion_tokens: 16 }, check))).status, 200);
  // the owner's own agent string is a label, not a pass: on a scanner path it is refused like anyone
  const own = relay();
  assert.equal((await own.call("/.git/HEAD", { headers: { "User-Agent": "taochronos-deploy/1", "CF-Connecting-IP": "198.51.100.79" } })).status, 404);
  await own.settle();
  assert.equal((await own.call("/v1/chat/completions", post(PAGE_ASK, { ...check, "CF-Connecting-IP": "198.51.100.79" }))).status, 403);
  assert.equal(own.watch.records().items[0].event.own, true);
  // SENTINEL = off: nothing is recorded, the security endpoints are not there
  const off = relay({ env: { SENTINEL: "off" } });
  assert.equal((await off.call("/wp-config.php", { headers: { "CF-Connecting-IP": "45.138.12.10" } })).status, 404);
  await off.settle();
  assert.equal((await off.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "45.138.12.10" }))).status, 200);
  assert.equal((await off.call("/v1/security/summary", { headers: auth })).status, 404);
  assert.deepEqual(off.watch.records().items, []);
}));

test("tokens: what an answer cost counts against the visitor's day, and against the day", () => quiet(async () => {
  const final = '{"id":"a","choices":[{"finish_reason":"stop","index":0,"delta":{}}],"model":"MiniMax-M3","usage":{"prompt_tokens":70,"completion_tokens":40,"total_characters":9},"base_resp":{"status_code":0}}';
  const events = ['{"id":"a","choices":[{"index":0,"delta":{"content":"答"}}],"model":"MiniMax-M3","usage":null}', final, "[DONE]"];
  const r = relay({ env: { TOKENS_PER_DAY: "200", TOTAL_TOKENS_PER_DAY: "300" }, upstream: () => sse(events) });
  const first = await r.call("/v1/chat/completions", post(PAGE_ASK));
  const text = await first.text(); // the stream read to its end, as a browser would
  assert.doesNotMatch(text, /total_characters/);
  assert.match(text, /"usage":\{"prompt_tokens":70,"completion_tokens":40\}/);
  await r.settle();
  const read = async (res) => { assert.equal(res.status, 200); await res.text(); await r.settle(); }; // an answer read to its end: its cost counted
  await read(await r.call("/v1/chat/completions", post(PAGE_ASK))); // 220 of 200: the next is refused
  const over = await r.call("/v1/chat/completions", post(PAGE_ASK));
  assert.equal(over.status, 429);
  assert.match((await over.json()).error.message, /按用量计/);
  await read(await r.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "198.51.100.1" }))); // 330 in all: over the day
  const total = await r.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "198.51.100.2" }));
  assert.equal(total.status, 429);
  assert.match((await total.json()).error.message, /总额度已用完（按用量计）/);
  assert.equal(r.calls.length, 3);
  // a plain JSON reply counts too; the health says the budget
  const plain = relay({ env: { TOKENS_PER_DAY: "100" }, upstream: async () => new Response(JSON.stringify({ id: "c", model: "MiniMax-M3", choices: [{ message: { content: "好" } }],
    usage: { prompt_tokens: 90, completion_tokens: 20 } }), { status: 200, headers: { "Content-Type": "application/json" } }) });
  assert.equal((await plain.call("/v1/chat/completions", post({ ...PAGE_ASK, stream: false }))).status, 200);
  await plain.settle();
  assert.equal((await plain.call("/v1/chat/completions", post({ ...PAGE_ASK, stream: false }))).status, 429);
  assert.equal((await (await plain.call("/v1/health")).json()).limits.tokens_per_day, 100);
  const none = relay({ env: { TOKENS_PER_DAY: "0", TOTAL_TOKENS_PER_DAY: "0" }, upstream: () => sse(events) });
  for (let i = 0; i < 3; i++) { await (await none.call("/v1/chat/completions", post(PAGE_ASK))).text(); await none.settle(); }
  assert.equal(none.calls.length, 3);
  // a call is charged its size as it goes out, the answer's usage settles it: thirty calls in flight cannot overdraw
  const inflight = relay({ env: { TOKENS_PER_DAY: "250" }, upstream: () => sse(events) });
  const flight = await inflight.call("/v1/chat/completions", post(PAGE_ASK)); // reserved ~ a third of the body's bytes
  const who = inflight.limiter.sql.exec("SELECT k FROM hits WHERE k LIKE 'k:chat:%'").toArray()[0].k;
  const reserved = inflight.limiter.count(who);
  assert.ok(reserved > 50 && reserved < 250, String(reserved));
  await flight.text(); await inflight.settle();
  assert.equal(inflight.limiter.count(who), 110); // settled to what the answer cost
  // the upstream call carries the visitor's signal: leaving cancels it
  assert.ok(inflight.calls[0].init.signal instanceof AbortSignal);
  // the counters out of reach: a call is not let through uncounted; a record is let go
  const down = relay({ gateFails: true });
  const refused = await down.call("/v1/chat/completions", post(PAGE_ASK));
  assert.equal(refused.status, 503);
  assert.equal((await refused.json()).error.type, "unavailable");
  assert.equal(down.calls.length, 0);
  assert.equal((await down.call("/v1/logs", post(turn))).status, 204);
  assert.equal(down.book.records().items.length, 0);
}));

test("https only; the ten-second gate before anything is read; a body without a length is read only up to the limit", () => quiet(async () => {
  const r = relay();
  const clear = await handle(new Request("http://chat-api.impf.ai/v1/chat/completions", post(PAGE_ASK)), { MINIMAX_API_KEY: KEY, LOG_EXPORT_TOKEN: TOKEN }, {
    ...Object.fromEntries(["gate", "spend", "burst", "watch", "logbook", "fetch"].map((k) => [k, async () => { throw new Error("not reached"); }])),
    observe: async () => null, defer: () => {}, now: () => Date.UTC(2026, 8, 28, 12, 0, 0) });
  assert.equal(clear.status, 403);
  assert.equal((await clear.json()).error.type, "https_required");
  const gated = relay({ burst: (key) => key !== "203.0.113.7" });
  const refused = await gated.call("/v1/chat/completions", post(PAGE_ASK));
  assert.equal(refused.status, 429);
  assert.equal(refused.headers.get("Retry-After"), "10");
  assert.equal(gated.calls.length, 0);
  assert.equal((await gated.call("/v1/logs", post(turn))).status, 429);
  assert.equal((await gated.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "2001:db8:1:2:aaaa::1" }))).status, 200);
  assert.deepEqual(gated.bursts.slice(-1), ["2001:db8:1:2::/64"]); // the gate's key: an IPv6 address by its /64
  const chunked = relay({ env: { MAX_BODY_BYTES: "1000" } });
  const body = new ReadableStream({ start(c) { for (let i = 0; i < 20; i++) c.enqueue(new TextEncoder().encode("x".repeat(100))); c.close(); } });
  const big = await chunked.call("/v1/chat/completions", { ...post(""), body, duplex: "half" });
  assert.equal(big.status, 413);
  assert.equal(chunked.calls.length, 0);
}));

test("config: the defaults, and the Worker's variables over them", () => {
  const c = config({ MODELS: "MiniMax-M3, MiniMax-M2.7", UPSTREAM_BASE: "https://api.minimax.io/v1/" });
  assert.deepEqual(c.models, ["MiniMax-M3", "MiniMax-M2.7"]);
  assert.equal(c.upstream, "https://api.minimax.io/v1");
  assert.ok(config().origins.includes("https://chat.impf.ai"));
});

// ------------------------------------------------------------------ the counts for the settings' 统计 pane
const STATS = "stats-token-0123456789abcdef";

test("a question is counted with its place and visitor, a tool round only as a call, a refused call not at all", () => quiet(async () => {
  let t = Date.UTC(2026, 9, 6, 16, 30, 0); // 00:30 on the 7th in Beijing: the readers' day
  const r = relay({ now: () => t, cf: { country: "CN", regionCode: "GD", asn: 4134 }, env: { STATS_TOKEN: STATS } });
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK))).status, 200);
  const round = { ...PAGE_ASK, messages: [...PAGE_ASK.messages, { role: "assistant", content: null, tool_calls: [{ id: "c1", type: "function", function: { name: "classics.search", arguments: "{}" } }] },
    { role: "tool", tool_call_id: "c1", content: "《伤寒论》……" }] };
  t += 5000;
  assert.equal((await r.call("/v1/chat/completions", post(round))).status, 200);
  t += 5000;
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK))).status, 200); // the same visitor asks again
  const s = r.usage.stats(1, "2026-10-07");
  assert.deepEqual(s.today, { view: 0, visitor: 0, question: 2, call: 3, asker: 1 });
  assert.deepEqual(s.places, [{ country: "CN", region: "GD", view: 0, visitor: 0, question: 2, call: 3, asker: 1 }]); // ISO 3166-2, as Cloudflare gives it
  const refused = relay({ cf: { country: "US", regionCode: "OH" }, burst: () => false });
  assert.equal((await refused.call("/v1/chat/completions", post(PAGE_ASK))).status, 429);
  assert.deepEqual(refused.usage.stats(1, "2026-09-28").places, []);
}));

test("the counts are read with the stats token, from the page's origin", () => quiet(async () => {
  const t = Date.UTC(2026, 9, 7, 4, 0, 0);
  const r = relay({ now: () => t, cf: { country: "CN", regionCode: "BJ" }, env: { STATS_TOKEN: STATS } });
  await r.call("/v1/chat/completions", post(PAGE_ASK));
  const preflight = await r.call("/v1/stats", { method: "OPTIONS", headers: { Origin: PAGE, "Access-Control-Request-Headers": "authorization" } });
  assert.match(preflight.headers.get("Access-Control-Allow-Headers"), /Authorization/);
  const none = await r.call("/v1/stats?days=7", { headers: { Origin: PAGE } });
  assert.equal(none.status, 401);
  assert.equal(none.headers.get("Access-Control-Allow-Origin"), PAGE); // the page reads why
  const ok = await r.call("/v1/stats?days=7", { headers: { Origin: PAGE, Authorization: `Bearer ${STATS}` } });
  assert.equal(ok.status, 200);
  const body = await ok.json();
  assert.equal(body.asOf, "2026-10-07");
  assert.deepEqual(body.today, { view: 0, visitor: 0, question: 1, call: 1, asker: 1 });
  assert.equal(body.days.length, 7);
  assert.deepEqual([body.totals.question, body.totals.call], [1, 1]);
  assert.equal(body.places[0].region, "BJ");
  const unset = relay({ cf: { country: "CN" } });
  assert.equal((await (await unset.call("/v1/stats", { headers: { Origin: PAGE, Authorization: `Bearer ${STATS}` } })).json()).configured, false);
  const open = relay({ env: { STATS_PUBLIC: "1" } });
  assert.equal((await open.call("/v1/stats", { headers: { Origin: PAGE } })).status, 200);
}));
