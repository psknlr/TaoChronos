// The relay under Node: the request handler and the two stores on an in-memory SQLite (node:sqlite), a mock MiniMax.
// Run: node --test relay/test/

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { config, handle, normalizeRecord, withoutReasoning } from "../src/relay.js";
import { LimiterCore, LogBookCore } from "../src/state.js";

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

function relay({ env = {}, upstream, now = () => Date.UTC(2026, 8, 28, 12, 0, 0) } = {}) {
  const limiter = new LimiterCore(sqlStore());
  const book = new LogBookCore(sqlStore());
  const calls = [];
  const deps = {
    limit: async (who, kind, limits) => limiter.hit(who, kind, limits, now()),
    logbook: { add: async (...a) => book.add(...a), records: async (...a) => book.records(...a), remove: async (...a) => book.remove(...a) },
    fetch: async (url, init) => {
      calls.push({ url, init, body: JSON.parse(init.body) });
      return upstream ? upstream(url, init) : sse(["{\"choices\":[{\"delta\":{\"content\":\"可以\"}}]}", "[DONE]"]);
    },
    now,
  };
  const fullEnv = { MINIMAX_API_KEY: KEY, LOG_EXPORT_TOKEN: TOKEN, ...env };
  const call = (path, init = {}) => handle(new Request(`https://chat-api.impf.ai${path}`, init), fullEnv, deps);
  return { call, calls, book, limiter };
}

function sse(events) {
  const body = events.map((e) => `data: ${e}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const post = (body, headers = {}) => ({
  method: "POST", headers: { "Content-Type": "application/json", Origin: PAGE, "CF-Connecting-IP": "203.0.113.7", ...headers },
  body: typeof body === "string" ? body : JSON.stringify(body),
});

const ask = { model: "MiniMax-M3", messages: [{ role: "user", content: "桂枝汤主治什么？" }], stream: true, max_completion_tokens: 16000, n: 3 };

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
  assert.equal(c.body.max_completion_tokens, 8192); // capped
  assert.equal(c.body.n, undefined);
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
  const raw = JSON.stringify({ model: "MiniMax-M3", messages: [{ role: "user", content: "桂枝汤" }], stream: true, max_completion_tokens: 8192 });
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
  assert.match((await other.json()).error.message, /MiniMax-M3/);
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
  assert.equal(noModel.calls[0].body.max_completion_tokens, 8192);
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
  const rate = relay({ upstream: async () => new Response(JSON.stringify({ error: { message: "rate limit" } }), { status: 429 }) });
  const rr = await rate.call("/v1/chat/completions", post(ask));
  assert.equal(rr.status, 429);
  assert.match((await rr.json()).error.message, /rate limit/);
  const down = relay({ upstream: async () => { throw new TypeError("network"); } });
  assert.equal((await down.call("/v1/chat/completions", post(ask))).status, 502);
});

test("health says what the page needs, nothing secret", async () => {
  const r = relay();
  const res = await r.call("/v1/health", { headers: { Origin: PAGE } });
  const j = await res.json();
  assert.deepEqual([j.ok, j.model, j.logs], [true, "MiniMax-M3", true]);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), PAGE);
  assert.ok(!JSON.stringify(j).includes(KEY) && !JSON.stringify(j).includes(TOKEN));
  const bare = await relay({ env: { MINIMAX_API_KEY: "", LOGS: "off" } }).call("/v1/health");
  assert.deepEqual([(await bare.json()).ok], [false]);
});

// ------------------------------------------------------------------ the records
const turn = {
  v: 1, id: "t1", conversation: "c_x", turn: 1, question: "桂枝汤主治什么？", answer: "太阳中风……[[cm_shanghan_npm.00012]]",
  model: "MiniMax-M3", provider: "impf", runtime: "browser", corpus: "canon", ms: 12345, status: "done",
  tools: [{ name: "classics.search", ok: true, ms: 80, args: "{\"query\":\"桂枝汤\"}", extra: "dropped" }],
  citations: { total: 2, ok: 2, warn: 0, bad: 0, pending: 0, pids: ["cm_shanghan_npm.00012"] }, usage: { input: 1200, output: 180, cost: "x" },
  apiKey: "must not be kept", settings: { keys: { minimax: "x" } },
};

test("a record is kept only as its known fields, from the page, within its limits", async () => {
  const r = relay();
  assert.equal((await r.call("/v1/logs", post(turn))).status, 204);
  assert.equal((await r.call("/v1/logs", post(turn, { Origin: "https://evil.example" }))).status, 403);
  assert.equal((await r.call("/v1/logs", post({ ...turn, v: 2 }))).status, 400);
  assert.equal((await r.call("/v1/logs", post("{not json"))).status, 400);
  assert.equal((await relay({ env: { LOGS: "off" } }).call("/v1/logs", post(turn))).status, 404);
  const { items } = r.book.records(0, 10);
  assert.equal(items.length, 1);
  const kept = items[0].record;
  assert.equal(kept.question, turn.question);
  assert.equal(kept.apiKey, undefined);
  assert.equal(kept.settings, undefined);
  assert.equal(kept.tools[0].extra, undefined);
  assert.equal(kept.citations.ok, 2);
  assert.deepEqual(kept.usage, { input: 1200, output: 180 });
  const long = normalizeRecord({ ...turn, answer: "字".repeat(30000), question: "问".repeat(5000) });
  assert.equal(long.answer.length, 20000);
  assert.equal(long.question.length, 4000);
  assert.equal(normalizeRecord({ v: 1, question: "" }), null);
  assert.equal(normalizeRecord([1]), null);
});

test("the collector: token required, records after its cursor, deleted once committed, ids never reused", async () => {
  const r = relay();
  for (let k = 0; k < 5; k++) await r.call("/v1/logs", post({ ...turn, turn: k + 1 }));
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

test("config: the defaults, and the Worker's variables over them", () => {
  const c = config({ MODELS: "MiniMax-M3, MiniMax-M2.7", UPSTREAM_BASE: "https://api.minimax.io/v1/" });
  assert.deepEqual(c.models, ["MiniMax-M3", "MiniMax-M2.7"]);
  assert.equal(c.upstream, "https://api.minimax.io/v1");
  assert.ok(config().origins.includes("https://chat.impf.ai"));
});
