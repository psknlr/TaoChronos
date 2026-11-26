// The relay under Node: the request handler and the two stores on an in-memory SQLite (node:sqlite), a mock MiniMax.
// Run: node --test relay/test/

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { drain, EVENTS, RECORDS } from "../../security/archive.js";
import { LedgerCore } from "../../security/ledger.js";
import { apply, ensure, rollup, stats as ledgerStats } from "../../security/ledger-d1.js";
import { WatchCore } from "../../security/sentinel.js";
import { d1 } from "../../security/test/fakes.js";
import { isVisitor, ledgerConfig, passFor } from "../../security/visitor.js";
import { gateCall, logged as ledgerLogged, turnFinished, turnRecorded } from "../src/gate.js";
import { config, defaultModel, handle, normalizeFeedback, normalizeRecord, normalizeTurn, openaiBody, placedFetch, publicText, waitAsked, withoutReasoning } from "../src/relay.js";
import { normalizeSponsor, seal, SponsorBookCore, unseal } from "../src/sponsors.js";
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
function relay({ env = {}, upstream, now = () => Date.UTC(2026, 8, 28, 12, 0, 0), cf, burst, gateFails = false, egress, routes } = {}) {
  const limiter = new LimiterCore(sqlStore());
  const watch = new WatchCore(sqlStore());
  const book = new LogBookCore(sqlStore());
  const usage = new UsageCore(sqlStore());
  const sponsors = new SponsorBookCore(sqlStore());
  const ledger = new LedgerCore(sqlStore(), "relay"); // the turns the object remembers, and the activity ledger's outbox
  const fullEnv = { MINIMAX_API_KEY: KEY, LOG_EXPORT_TOKEN: TOKEN, ...env };
  const lcfg = ledgerConfig(fullEnv);
  const calls = [];
  const pending = [];
  const bursts = [];
  const pauses = [];
  const observe = async (fp, a, extra, cfg) => {
    const w = await watch.observe(fp, a, extra, cfg, now());
    if (extra?.activity) ledgerLogged(ledger, { ...extra.activity, fp, a, w, status: extra.status, ledger: true }, now());
    return w;
  };
  const deps = {
    limit: async (who, kind, limits) => limiter.hit(who, kind, limits, now()),
    // as the Durable Object does it (relay/src/index.js): its own code (relay/src/gate.js) over these stores
    gate: async (args) => {
      if (gateFails) throw new Error("Durable Object: daily limit reached");
      return gateCall({ core: limiter, watch, usage, ledger }, args, now());
    },
    ledger: {
      settle: async (outcome) => ledger.settle(outcome, now(), { offset: 8, keep: lcfg.keep }),
      finished: async (act, key, info) => turnFinished(ledger, act, key, info, now(), lcfg),
      recorded: async (act, key, info) => turnRecorded(ledger, act, key, info, now(), lcfg),
      logged: async (act) => ledgerLogged(ledger, { ...act, ledger: true }, now()),
      health: async () => ledger.health(now()),
    },
    stats: async (days, today) => usage.stats(days, today),
    observe,
    spend: async (who, kind, tokens) => limiter.spend(who, kind, tokens, now()),
    burst: async (key) => { bursts.push(key); return burst ? burst(key) : true; },
    watch: { observe, records: async (...a) => watch.records(...a), remove: async (...a) => watch.remove(...a), summary: async () => watch.summary(now()) },
    defer: (p) => { pending.push(Promise.resolve(p).catch(() => {})); },
    logbook: { add: async (...a) => book.add(...a), records: async (...a) => book.records(...a), remove: async (...a) => book.remove(...a) },
    sponsors: { add: async (...a) => sponsors.add(...a), list: async () => sponsors.list(), get: async (id) => sponsors.get(id), remove: async (id) => sponsors.remove(id) },
    fetch: async (url, init, place) => {
      calls.push({ url, init, body: init.body ? JSON.parse(init.body) : null, via: place || "direct" });
      return upstream ? upstream(url, init, place) : sse(["{\"choices\":[{\"delta\":{\"content\":\"可以\"}}]}", "[DONE]"]);
    },
    // the Worker's Durable Object placed at a location (index.js, Egress): here, the same fetch, told where from
    ...(egress ? { egress: async (location, url, init) => { egress.push(location); return deps.fetch(url, init, location); } } : {}),
    ...(routes ? { routes } : {}), // what the instance remembers of the places between calls
    pause: async (ms) => { pauses.push(ms); }, // between two asks of the upstream: noted, not waited for
    now,
  };
  const call = (path, init = {}) => {
    const request = new Request(`https://chat-api.impf.ai${path}`, init);
    if (cf) request.cf = cf;
    return handle(request, fullEnv, deps);
  };
  const settle = () => Promise.all(pending.splice(0)); // what the Worker finishes after the answer (ctx.waitUntil)
  // the ledger's events so far (what is not a visitor's is added up by the minute, and written here now), and the
  // registry they are drained into
  const events = () => { ledger.flush(now(), 0, true); return ledger.batch(0, 5000).map((r) => r.event); };
  const registry = async () => {
    const db = fullEnv.ACTIVITY_DB;
    await ensure(db);
    await apply(db, events());
    await rollup(db);
    return db;
  };
  return { call, calls, book, limiter, watch, usage, sponsors, settle, bursts, pauses, ledger, events, registry, env: fullEnv };
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
  const ok = await r.call("/v1/chat/completions", { method: "OPTIONS", headers: { Origin: "https://psknlr.github.io", "Access-Control-Request-Method": "POST" } });
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), "https://psknlr.github.io");
  assert.match(ok.headers.get("Access-Control-Allow-Headers"), /Content-Type/);
  // the page's address over plain http is nobody's now: the site redirects it, so a page there is one put in its place
  const plain = await r.call("/v1/chat/completions", { method: "OPTIONS", headers: { Origin: "http://chat.impf.ai", "Access-Control-Request-Method": "POST" } });
  assert.deepEqual([plain.status, plain.headers.get("Access-Control-Allow-Origin")], [403, null]);
  assert.deepEqual(config({}).origins, ["https://chat.impf.ai", "https://psknlr.github.io"]);
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
  assert.match(minute.headers.get("Access-Control-Expose-Headers"), /^Retry-After\b/); // the page waits as long as it is asked
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

test("a record keeps how many times the model service was asked for a reply and where it came from, as the relay names them", () => {
  const rec = (q) => normalizeRecord({ v: 1, question: "问", requests: [{ round: 1, attempt: 1, sent: 1, end: 2, ...q }] }).requests[0];
  assert.deepEqual(rec({ asks: 2, via: "apac" }), { round: 1, attempt: 1, sent: 1, end: 2, asks: 2, via: "apac" });
  assert.equal(rec({ via: "enam+wnam" }).via, "enam+wnam");
  assert.equal(rec({ via: "direct" }).via, "direct");
  for (const via of ["https://example.com", "apac; drop", "A".repeat(9), 7, "", null, "api.minimax.cn"]) assert.equal(rec({ via }).via, undefined, String(via));
  assert.equal(rec({ asks: "2" }).asks, undefined);
});

// ------------------------------------------------------------------ an upstream that does not answer
const answer = () => sse(['{"choices":[{"delta":{"content":"答"}}]}', "[DONE]"]);
/** An upstream that sends nothing until the ask is ended (its signal), as a service that hangs does. */
const hang = (url, init) => new Promise((resolve, reject) => {
  init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
});
/** Run with the Worker's log kept (console.error): what the owner reads of an upstream's failures. */
const logged = async (fn) => {
  const said = [];
  const err = console.error;
  console.error = (...a) => said.push(a.join(" "));
  try { await fn(said); } finally { console.error = err; }
  return said;
};

test("an upstream that sends nothing is given up and asked again, within the one call the visitor was counted for", async () => {
  let n = 0;
  const r = relay({ env: { UPSTREAM_FIRST_BYTE_SECONDS: "0.03", PER_DAY: "2" }, upstream: (url, init) => (n++ === 0 ? hang(url, init) : answer()) });
  const said = await logged(async () => {
    const res = await r.call("/v1/chat/completions", post(ask));
    assert.equal(res.status, 200);
    assert.match(await res.text(), /答/);
  });
  assert.equal(r.calls.length, 2);
  assert.equal(r.calls[0].init.signal.aborted, true);   // the ask that hung is ended, not left running
  assert.equal(r.calls[1].init.signal.aborted, false);
  assert.deepEqual(r.calls[0].body, r.calls[1].body);   // the same request, with the key
  assert.equal(r.calls[1].init.headers.Authorization, `Bearer ${KEY}`);
  assert.deepEqual(said, ["upstream silent ask 1/3 via direct"]);  // a word for the owner, nothing of the request
  assert.deepEqual(r.pauses, []);                       // it had waited already: asked again at once
  // counted once: of a day of two calls, one is left (asked again by the page, it would have been counted again)
  assert.equal((await r.call("/v1/chat/completions", post(ask))).status, 200);
  assert.equal((await r.call("/v1/chat/completions", post(ask))).status, 429);
});

test("an upstream silent every time is told as one that did not answer, in the default service's words", async () => {
  const r = relay({ env: { UPSTREAM_FIRST_BYTE_SECONDS: "0.02", UPSTREAM_ATTEMPTS: "2" }, upstream: hang });
  const said = await logged(async () => {
    const res = await r.call("/v1/chat/completions", post(ask));
    assert.equal(res.status, 504); // the page asks again, after its own pause (web/js/llm/openai.js: 5xx, not FINAL)
    assert.equal(res.headers.get("Access-Control-Allow-Origin"), PAGE);
    const j = await res.json();
    assert.equal(j.error.type, "upstream_timeout");
    assert.match(j.error.message, /没有回应/);
    assert.doesNotMatch(j.error.message, /MiniMax|minimax/);
  });
  assert.equal(r.calls.length, 2);
  assert.ok(r.calls.every((c) => c.init.signal.aborted));
  assert.deepEqual(said, ["upstream silent ask 1/2 via direct", "upstream silent ask 2/2 via direct"]);
});

test("a failure of the upstream's own, or of the connection, is asked again; a refusal is the answer", async () => {
  // 5xx, then an answer
  let n = 0;
  const flaky = relay({ upstream: async () => (n++ === 0 ? new Response(JSON.stringify({ error: { type: "overloaded_error", message: "MiniMax busy" } }), { status: 503 }) : answer()) });
  const said = await logged(async () => {
    const res = await flaky.call("/v1/chat/completions", post(ask));
    assert.equal(res.status, 200);
    assert.match(await res.text(), /答/);
  });
  assert.equal(flaky.calls.length, 2);
  assert.deepEqual(said, ["upstream 503 overloaded_error ask 1/3 via direct"]); // its code, never its message
  assert.deepEqual(flaky.pauses, [400]); // a failure met at once is not met again at once
  // the connection fails, then an answer
  let m = 0;
  const reset = relay({ upstream: async () => { if (m++ === 0) throw new TypeError("connection reset"); return answer(); } });
  await logged(async () => assert.equal((await reset.call("/v1/chat/completions", post(ask))).status, 200));
  assert.equal(reset.calls.length, 2);
  // failing every time: told as before, after every ask
  const broken = relay({ upstream: async () => new Response("MiniMax internal error", { status: 500 }) });
  await logged(async () => {
    const res = await broken.call("/v1/chat/completions", post(ask));
    assert.equal(res.status, 502);
    assert.equal((await res.json()).error.type, "upstream_error");
  });
  assert.equal(broken.calls.length, 3);
  assert.deepEqual(broken.pauses, [400, 800]);
  const down = relay({ upstream: async () => { throw new TypeError("network"); } });
  await logged(async () => {
    const res = await down.call("/v1/chat/completions", post(ask));
    assert.equal(res.status, 502);
    assert.equal((await res.json()).error.type, "upstream_unreachable");
  });
  assert.equal(down.calls.length, 3);
  // a refusal — a key, a rate, a parameter — is not asked again
  for (const status of [400, 401, 403, 404, 429]) {
    const refused = relay({ upstream: async () => new Response(JSON.stringify({ error: { message: "no" } }), { status }) });
    await logged(async () => { await refused.call("/v1/chat/completions", post(ask)); });
    assert.equal(refused.calls.length, 1, String(status));
  }
  // one ask only, and no wait, when set so: as before
  const once = relay({ env: { UPSTREAM_ATTEMPTS: "1", UPSTREAM_FIRST_BYTE_SECONDS: "0" }, upstream: async () => new Response("down", { status: 502 }) });
  await logged(async () => assert.equal((await once.call("/v1/chat/completions", post(ask))).status, 502));
  assert.equal(once.calls.length, 1);
  assert.deepEqual([config().firstByteMs, config().attempts], [30000, 3]);
  assert.deepEqual([config({ UPSTREAM_ATTEMPTS: "99" }).attempts, config({ UPSTREAM_ATTEMPTS: "0" }).attempts, config({ UPSTREAM_ATTEMPTS: "x" }).attempts], [5, 1, 1]);
  assert.deepEqual([config({ UPSTREAM_FIRST_BYTE_SECONDS: "0" }).firstByteMs, config({ UPSTREAM_FIRST_BYTE_SECONDS: "-3" }).firstByteMs, config({ UPSTREAM_FIRST_BYTE_SECONDS: "x" }).firstByteMs], [0, 0, 0]);
  // the attempts together stay under the page's wait for a first reply (web/js/limits.js, firstReply: 120 s)
  assert.ok(config().firstByteMs * config().attempts < 120000);
});

test("a visitor who leaves ends the ask, and no other is made; one who leaves mid-answer ends the stream", async () => {
  const gone = new AbortController();
  const r = relay({ env: { UPSTREAM_FIRST_BYTE_SECONDS: "5" }, upstream: hang });
  const waiting = logged(async () => { await r.call("/v1/chat/completions", { ...post(ask), signal: gone.signal }); });
  await new Promise((resolve) => setTimeout(resolve, 20));
  gone.abort();
  assert.deepEqual(await waiting, []); // not a failure of the upstream's: nothing for the log
  assert.equal(r.calls.length, 1);
  assert.equal(r.calls[0].init.signal.aborted, true);
  const left = new AbortController();
  const s = relay();
  const res = await s.call("/v1/chat/completions", { ...post(ask), signal: left.signal });
  assert.equal(res.status, 200);
  assert.equal(s.calls[0].init.signal.aborted, false);
  left.abort(); // the answer is streaming: the model call ends with the visitor's request
  assert.equal(s.calls[0].init.signal.aborted, true);
});

test("the second model's asks are bounded alike: a place that sends nothing is given up and asked again", async () => {
  let n = 0;
  const where = [];
  // (a fetch made from a placed object is not reached by the signal: here it simply never answers)
  const r = relay({ env: { OPENAI_API_KEY: OKEY, UPSTREAM_FIRST_BYTE_SECONDS: "0.03" }, egress: where, upstream: () => (n++ === 0 ? new Promise(() => {}) : answer()) });
  await logged(async () => {
    const res = await r.call("/v1/chat/completions", post(LUNA, turnOf("s1")));
    assert.equal(res.status, 200);
    assert.match(await res.text(), /答/);
  });
  assert.equal(r.calls.length, 2);
  assert.deepEqual(where, ["enam", "enam"]);
});

// ------------------------------------------------------------------ the default model asked from more than one place
/** An answer that begins only after `ms` (a place that is slow, not silent); ended like any ask. */
const slow = (ms) => (url, init) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => resolve(answer()), ms);
  init.signal.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("aborted", "AbortError")); }, { once: true });
});
const asks = (res) => [res.status, res.headers.get("X-Tao-Asks"), res.headers.get("X-Tao-Via")];

test("an ask that is silent is joined by one from the next place, and the place is remembered", async () => {
  let t = Date.UTC(2026, 10, 10, 12, 0, 0);
  const routes = new Map();
  const where = [];
  // from where the Worker runs the model service does not answer; from the place in East Asia it does
  const r = relay({ env: { UPSTREAM_HEDGE_SECONDS: "0.02", UPSTREAM_FIRST_BYTE_SECONDS: "5", PER_DAY: "4" }, egress: where, routes, now: () => t, cf: { colo: "AMS" },
    upstream: (url, init, place) => (place ? answer() : hang(url, init)) });
  const said = await logged(async () => {
    const res = await r.call("/v1/chat/completions", post(ask));
    assert.deepEqual(asks(res), [200, "2", "apac"]); // told to the page, for the turn's record
    assert.match(res.headers.get("Access-Control-Expose-Headers"), /X-Tao-Asks, X-Tao-Via/);
    assert.match(await res.text(), /答/);
  });
  assert.deepEqual(r.calls.map((c) => c.via), ["direct", "apac"]);
  assert.deepEqual(where, ["apac"]);
  assert.deepEqual(r.calls[0].body, r.calls[1].body);                 // the same request
  assert.equal(r.calls[1].init.headers.Authorization, `Bearer ${KEY}`);
  assert.equal(r.calls[1].init.headers["X-Tao-Wait"], "5000");         // the placed object ends its own call when it hears nothing
  assert.equal(r.calls[0].init.headers["X-Tao-Wait"], undefined);      // nothing of ours goes to the model service itself
  assert.equal(r.calls[0].init.signal.aborted, true);                  // the silent one is dropped once the reply is here
  assert.deepEqual(said, ["upstream silent so far ask 1/3 via direct at AMS: joined"]); // where, for the owner
  // remembered: the next call asks the place that answered first, and waits for nothing
  const next = await r.call("/v1/chat/completions", post(ask));
  assert.deepEqual(asks(next), [200, "1", "apac"]);
  assert.deepEqual(r.calls.map((c) => c.via), ["direct", "apac", "apac"]);
  // for a while (five minutes); then the Worker's own place is tried first again — and, silent again, rests twice as long
  t += 299000;
  assert.deepEqual(asks(await r.call("/v1/chat/completions", post(ask))), [200, "1", "apac"]);
  t += 2000;
  await logged(async () => assert.deepEqual(asks(await r.call("/v1/chat/completions", post(ask))), [200, "2", "apac"]));
  assert.deepEqual(r.calls.slice(-2).map((c) => c.via), ["direct", "apac"]);
  assert.equal(routes.get("direct").until, t + 600000);
  assert.equal(routes.has("apac"), false); // a place that answers is not held anything against
  // counted once each, whatever it took: four calls, a day of four spent
  assert.equal((await r.call("/v1/chat/completions", post(ask))).status, 429);
});

test("a place that is only slow is not thrown away: the first to answer is the reply, the other is dropped", async () => {
  const routes = new Map();
  const r = relay({ env: { UPSTREAM_HEDGE_SECONDS: "0.02", UPSTREAM_FIRST_BYTE_SECONDS: "5", UPSTREAM_ATTEMPTS: "2" }, egress: [], routes,
    upstream: (url, init, place) => (place ? hang(url, init) : slow(60)(url, init)) });
  await logged(async () => {
    const res = await r.call("/v1/chat/completions", post(ask));
    assert.deepEqual(asks(res), [200, "2", "direct"]);
    assert.match(await res.text(), /答/);
  });
  assert.deepEqual(r.calls.map((c) => c.via), ["direct", "apac"]);
  assert.equal(r.calls[0].init.signal.aborted, false); // the reply's own call goes on: its stream is being read
  assert.equal(routes.has("direct"), false);           // it answered, late as it was
});

test("a failure at one place is asked at the next; every place failing is told as before", async () => {
  // the Worker's own place gets the upstream's 5xx; the other answers
  const r = relay({ egress: [], routes: new Map(), upstream: async (url, init, place) => (place ? answer() : new Response("bad gateway", { status: 502 })) });
  const said = await logged(async () => assert.deepEqual(asks(await r.call("/v1/chat/completions", post(ask))), [200, "2", "apac"]));
  assert.deepEqual(said, ["upstream 502 ask 1/3 via direct"]);
  assert.deepEqual(r.pauses, [400]);
  // silent everywhere: three asks, turn about, each given up; told as a service that did not answer
  const dead = relay({ env: { UPSTREAM_FIRST_BYTE_SECONDS: "0.03", UPSTREAM_HEDGE_SECONDS: "0.01" }, egress: [], routes: new Map(), upstream: hang });
  await logged(async () => {
    const res = await dead.call("/v1/chat/completions", post(ask));
    assert.deepEqual(asks(res), [504, "3", null]);
    assert.equal((await res.json()).error.type, "upstream_timeout");
  });
  assert.deepEqual(dead.calls.map((c) => c.via), ["direct", "apac", "direct"]);
  assert.ok(dead.calls.every((c) => c.init.signal.aborted));
  // without a placed object (a Worker without the binding), or set so: from where the Worker runs only, as before
  for (const one of [relay({ upstream: hang, env: { UPSTREAM_FIRST_BYTE_SECONDS: "0.02", UPSTREAM_HEDGE_SECONDS: "0" } }),
    relay({ upstream: hang, egress: [], env: { UPSTREAM_VIA: "direct", UPSTREAM_FIRST_BYTE_SECONDS: "0.02", UPSTREAM_HEDGE_SECONDS: "0" } })]) {
    await logged(async () => assert.deepEqual(asks(await one.call("/v1/chat/completions", post(ask))), [504, "3", null]));
    assert.deepEqual(one.calls.map((c) => c.via), ["direct", "direct", "direct"]);
  }
  assert.deepEqual([config().via, config().hedgeMs], [["direct", "apac"], 12000]);
  assert.deepEqual(config({ UPSTREAM_VIA: "APAC, direct, apac, nowhere" }).via, ["apac", "direct"]); // in the order set; a place Cloudflare has only
  assert.deepEqual([config({ UPSTREAM_VIA: "off" }).via, config({ UPSTREAM_VIA: "" }).via, config({ UPSTREAM_HEDGE_SECONDS: "x" }).hedgeMs], [["direct"], ["direct", "apac"], 0]);
});

test("a refusal that may be one place's own is asked about at another, once; the service's own word is the answer at once", async () => {
  let t = Date.UTC(2026, 10, 10, 12, 0, 0);
  const limited = () => new Response(JSON.stringify({ error: { type: "rate_limit_error", message: "too many requests from this address" } }), { status: 429 });
  // the Worker's place is limited (its address is everyone's); the other is not
  const routes = new Map();
  const r = relay({ egress: [], routes, now: () => t, upstream: async (url, init, place) => (place ? answer() : limited()) });
  const said = await logged(async () => assert.deepEqual(asks(await r.call("/v1/chat/completions", post(ask))), [200, "2", "apac"]));
  assert.deepEqual(said, ["upstream 429 ask 1/3 via direct: another place asked"]);
  assert.deepEqual(asks(await r.call("/v1/chat/completions", post(ask))), [200, "1", "apac"]); // remembered, for a minute
  t += 61000;
  await logged(async () => assert.deepEqual(asks(await r.call("/v1/chat/completions", post(ask))), [200, "2", "apac"]));
  // limited everywhere: it is the service's — told as before, after one ask at each; and not asked twice again while both rest
  const both = relay({ egress: [], routes: new Map(), now: () => t, upstream: async () => limited() });
  await logged(async () => {
    const res = await both.call("/v1/chat/completions", post(ask));
    assert.deepEqual(asks(res), [429, "2", "apac"]);
    assert.equal((await res.json()).error.type, "upstream_rate");
    assert.equal((await both.call("/v1/chat/completions", post(ask))).headers.get("X-Tao-Asks"), "1");
  });
  assert.deepEqual(both.calls.map((c) => c.via), ["direct", "apac", "direct"]);
  // a key refused, a parameter refused: the service's own word — the answer at once, no other place asked
  for (const status of [400, 401, 404]) {
    const no = relay({ egress: [], routes: new Map(), upstream: async () => new Response(JSON.stringify({ error: { message: "no" } }), { status }) });
    await logged(async () => { await no.call("/v1/chat/completions", post(ask)); });
    assert.deepEqual(no.calls.map((c) => c.via), ["direct"], String(status));
  }
  // the other place refuses for itself (not let in) while the Worker's own gives no answer: that does not speak for the
  // service — the visitor is told it did not answer, and the page asks again; not that its key was refused
  const shut = relay({ env: { UPSTREAM_FIRST_BYTE_SECONDS: "0.05", UPSTREAM_HEDGE_SECONDS: "0.01" }, egress: [], routes: new Map(),
    upstream: (url, init, place) => (place ? new Response(JSON.stringify({ error: { message: "forbidden" } }), { status: 403 }) : hang(url, init)) });
  await logged(async () => {
    const res = await shut.call("/v1/chat/completions", post(ask));
    assert.equal(res.status, 504);
    assert.equal((await res.json()).error.type, "upstream_timeout");
  });
  // refused where the Worker runs and nowhere else to ask: the refusal is the answer
  const only = relay({ upstream: async () => new Response(JSON.stringify({ error: { message: "forbidden" } }), { status: 403 }) });
  await logged(async () => assert.equal((await (await only.call("/v1/chat/completions", post(ask))).json()).error.type, "upstream_auth"));
});

test("an object placed elsewhere forwards to the model services' hosts only, with the call's headers only, and ends a call it hears nothing of", async () => {
  const seen = [];
  const ok = async (url, init) => { seen.push({ url, init }); return new Response("ok"); };
  const to = (url, init = {}) => new Request(url, { method: "POST", body: "{}", ...init, headers: { "Content-Type": "application/json", Accept: "text/event-stream",
    Authorization: "Bearer k", Cookie: "a=b", "X-Forwarded-For": "203.0.113.7", "CF-Connecting-IP": "203.0.113.7", ...(init.headers || {}) } });
  for (const url of ["https://api.minimax.cn/v1/chat/completions", "https://api.openai.com/v1/chat/completions"]) {
    assert.equal((await placedFetch(to(url), {}, ok)).status, 200);
  }
  assert.deepEqual(seen.map((c) => c.url), ["https://api.minimax.cn/v1/chat/completions", "https://api.openai.com/v1/chat/completions"]);
  assert.deepEqual(Object.keys(seen[0].init.headers).sort(), ["Accept", "Authorization", "Content-Type"]); // nothing of the visitor
  assert.equal(seen[0].init.body, "{}");
  // any other host, or the same host in clear: refused, nothing sent
  for (const url of ["https://example.com/v1/chat/completions", "https://api.minimax.cn.evil.example/v1", "http://api.minimax.cn/v1/chat/completions"]) {
    assert.equal((await placedFetch(to(url), {}, ok)).status, 403, url);
  }
  assert.equal(seen.length, 2);
  // the hosts are the Worker's own settings
  assert.equal((await placedFetch(to("https://api.minimax.io/v1/chat/completions"), { UPSTREAM_BASE: "https://api.minimax.io/v1" }, ok)).status, 200);
  assert.equal((await placedFetch(to("https://api.minimax.cn/v1/chat/completions"), { UPSTREAM_BASE: "https://api.minimax.io/v1" }, ok)).status, 403);
  // told how long to wait: a host that sends nothing is given up (the relay's signal does not reach in here) …
  await assert.rejects(placedFetch(to("https://api.minimax.cn/v1/chat/completions", { headers: { "X-Tao-Wait": "20" } }), {}, hang));
  // … and one that has begun to answer is left to finish, however long its answer takes
  let signal = null;
  const res = await placedFetch(to("https://api.minimax.cn/v1/chat/completions", { headers: { "X-Tao-Wait": "20" } }), {},
    async (url, init) => { signal = init.signal; return answer(); });
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(signal.aborted, false);
  assert.match(await res.text(), /答/);
  assert.equal(seen.every((c) => !("X-Tao-Wait" in c.init.headers)), true);
});

test("a quota spent is told apart from a busy moment, and what the upstream asks to wait is passed on", async () => {
  const refuse = (body, headers = {}) => relay({ upstream: async () => new Response(JSON.stringify(body), { status: 429, headers }) });
  const said = await logged(async () => {
    // OpenAI's code for a quota spent, MiniMax's status code for a balance spent: not a busy moment
    for (const body of [{ error: { message: "You exceeded your current quota", type: "insufficient_quota", code: "insufficient_quota" } },
      { base_resp: { status_code: 1008, status_msg: "insufficient balance" } }]) {
      const res = await refuse(body).call("/v1/chat/completions", post(ask));
      assert.equal(res.status, 503);
      const j = await res.json();
      assert.equal(j.error.type, "upstream_quota"); // the page does not ask again (FINAL)
      assert.match(j.error.message, /额度已用完/);
      assert.doesNotMatch(JSON.stringify(j), /insufficient|exceeded|balance|1008/); // none of the upstream's own words
    }
    // a busy moment: as before; with what the upstream asks to wait, a minute at most
    const busy = await refuse({ error: { message: "MiniMax rate limit", type: "rate_limit_error" } }).call("/v1/chat/completions", post(ask));
    assert.deepEqual([busy.status, busy.headers.get("Retry-After")], [429, null]);
    assert.equal((await busy.json()).error.type, "upstream_rate");
    const asked = await refuse({ base_resp: { status_code: 1002 } }, { "Retry-After": "20" }).call("/v1/chat/completions", post(ask));
    assert.deepEqual([asked.status, asked.headers.get("Retry-After"), asked.headers.get("Access-Control-Expose-Headers")], [429, "20", "Retry-After, X-Tao-Asks, X-Tao-Via"]);
    const long = await refuse({}, { "Retry-After": "86400" }).call("/v1/chat/completions", post(ask));
    assert.deepEqual([long.status, long.headers.get("Retry-After")], [429, "60"]);
  });
  assert.deepEqual(said, ["upstream 429 insufficient_quota", "upstream 429 1008", "upstream 429 rate_limit_error", "upstream 429 1002", "upstream 429 "]);
  const now = Date.UTC(2026, 10, 10, 12, 0, 0);
  assert.deepEqual([waitAsked("7", now), waitAsked("0", now), waitAsked("", now), waitAsked(null, now), waitAsked("soon", now), waitAsked("-5", now)], [7, 0, 0, 0, 0, 0]);
  assert.equal(waitAsked(new Date(now + 12000).toUTCString(), now), 12);
  assert.equal(waitAsked(new Date(now - 12000).toUTCString(), now), 0);
});

test("health says what the page needs, nothing secret", async () => {
  const r = relay();
  const res = await r.call("/v1/health", { headers: { Origin: PAGE } });
  const j = await res.json();
  assert.deepEqual([j.ok, j.model, j.models, j.logs, j.feedback], [true, "Tao-R1", ["Tao-R1"], true, true]);
  assert.equal((await (await relay({ env: { FEEDBACK: "off" } }).call("/v1/health")).json()).feedback, false);
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
      { round: 1, attempt: 2, sent: 1200, end: 1300, failed: "overloaded_error", status: 529, hidden: 40, asleep: "0" },
      ...Array.from({ length: 60 }, (_, i) => ({ round: 2, attempt: i + 1, failed: "timeout".repeat(20), expired: "silence", sent: "5", status: "503" })),
    ],
    events: [{ at: 1500, what: "asked" }, { at: "soon", what: { no: 1 } }, null],
    hidden: 2000, asleep: "0", was: { runtime: "server", corpus: "full", url: "https://x.example" }, resumed: 2,
  });
  assert.deepEqual(timed.tools[0], { name: "classics.search", ok: false, ms: 80, args: "{\"query\":\"桂枝汤\"}", id: "call_1", round: 1,
    status: "timeout", at: 1200, wait: 300, compute: 80 });
  assert.deepEqual(timed.requests[0], { round: 1, attempt: 1, sent: 5, open: 400, first: 410, text: 900, last: 1100, end: 1101,
    finish: "tool_calls", input: 1200, output: 80 });
  assert.equal(timed.requests.length, 48);
  // and how long the page was hidden, or did not run, while it was asked: numbers only
  assert.deepEqual(timed.requests[1], { round: 1, attempt: 2, sent: 1200, end: 1300, failed: "overloaded_error", status: 529, hidden: 40 });
  assert.deepEqual(timed.requests[2], { round: 2, attempt: 1, failed: "timeout".repeat(20).slice(0, 40), expired: "silence" });
  assert.deepEqual(timed.events, [{ at: 1500, what: "asked" }, {}, {}]);
  assert.deepEqual([timed.hidden, timed.asleep, timed.was], [2000, undefined, { runtime: "server", corpus: "full" }]);
  // a turn taken up again (继续作答): how many times, as a number
  assert.deepEqual([timed.resumed, normalizeRecord({ ...turn, resumed: "2" }).resumed], [2, undefined]);
  // an older page's record has none of them
  assert.deepEqual(Object.keys(normalizeRecord(turn)).filter((k) => ["requests", "events", "hidden", "asleep", "was", "resumed"].includes(k)), []);
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

// ------------------------------------------------------------------ feedback on answers
const rated = {
  v: 1, kind: "feedback", id: "t1", conversation: "c_x", turn: 1, rating: "down", reasons: ["citation", "incomplete", "Not a code", 7, "citation"],
  comment: "  引的不是这一条。  ", recorded: true, given: "2026-09-28T12:00:00.000Z", model: "Tao-R1", provider: "impf", runtime: "browser",
  corpus: "canon", app: "0.1.0", apiKey: "must not be kept", settings: { keys: { minimax: "x" } },
};

test("feedback: the visitor's own act, on a turn of any day, kept with the records as its known fields", () => quiet(async () => {
  const r = relay();
  // no conversation with the relay needed (a rating may come days after the turn, or be of one held with an own key)
  assert.equal((await r.call("/v1/feedback", post(rated))).status, 204);
  const attached = { ...rated, id: "t2", rating: "up", reasons: ["accurate"], recorded: false, question: "桂枝汤主治什么？", answer: "太阳中风……" };
  assert.equal((await r.call("/v1/feedback", post(attached))).status, 204);
  assert.equal((await r.call("/v1/feedback", post({ ...rated, rating: null, comment: "kept?" }))).status, 204); // taken back
  const [down, up, back] = r.book.records(0, 10).items.map((i) => i.record);
  assert.deepEqual(down, { v: 1, kind: "feedback", id: "t1", conversation: "c_x", turn: 1, rating: "down", given: "2026-09-28T12:00:00.000Z",
    model: "MiniMax-M3", provider: "impf", runtime: "browser", corpus: "canon", app: "0.1.0", reasons: ["citation", "incomplete"],
    comment: "引的不是这一条。", recorded: true });
  assert.deepEqual([up.rating, up.question, up.answer, up.recorded], ["up", "桂枝汤主治什么？", "太阳中风……", undefined]);
  assert.deepEqual([back.rating, back.reasons, back.comment], [null, undefined, undefined]);
  // the collector takes them with the records, in the order they came
  const auth = { Authorization: `Bearer ${TOKEN}` };
  assert.deepEqual((await (await r.call("/v1/logs/export?after=0", { headers: auth })).json()).items.map((i) => i.record.kind), ["feedback", "feedback", "feedback"]);
  // only from the page; only a feedback; within its limits
  assert.equal((await r.call("/v1/feedback", post(rated, { Origin: "https://evil.example" }))).status, 403);
  for (const bad of [{ ...rated, kind: undefined }, { ...rated, rating: "meh" }, { ...rated, id: "" }, { ...rated, v: 2 }, turn]) {
    const res = await r.call("/v1/feedback", post(bad));
    assert.equal(res.status, 400);
    assert.equal((await res.json()).error.message, "反馈格式不对");
  }
  assert.equal((await r.call("/v1/feedback", post("{not json"))).status, 400);
  assert.equal(normalizeFeedback({ ...rated, comment: "评".repeat(3000) }).comment.length, 2000);
  assert.equal(normalizeFeedback({ ...rated, answer: "答".repeat(30000) }).answer.length, 20000);
  assert.equal(normalizeFeedback({ ...rated, reasons: Array.from({ length: 20 }, (_, i) => `r${"x".repeat(i)}`) }).reasons.length, 8);
  assert.equal((await relay({ env: { FEEDBACK: "off" } }).call("/v1/feedback", post(rated))).status, 404);
  // FEEDBACK_PER_MINUTE, then FEEDBACK_PER_DAY, each said in its own words
  const busy = relay({ env: { FEEDBACK_PER_MINUTE: "2", FEEDBACK_PER_DAY: "3" } });
  let t = Date.UTC(2026, 8, 28, 12, 0, 0);
  const daily = relay({ env: { FEEDBACK_PER_DAY: "2" }, now: () => t });
  for (let k = 0; k < 2; k++) assert.equal((await busy.call("/v1/feedback", post(rated))).status, 204);
  const minute = await busy.call("/v1/feedback", post(rated));
  assert.equal(minute.status, 429);
  assert.match((await minute.json()).error.message, /^反馈太频繁/);
  for (let k = 0; k < 2; k++, t += 61000) assert.equal((await daily.call("/v1/feedback", post(rated))).status, 204);
  const day = await daily.call("/v1/feedback", post(rated));
  assert.equal(day.status, 429);
  assert.equal((await day.json()).error.message, "今天的反馈已达上限（每人每天 2 条），明天再来");
  // records and feedback are counted apart: a day's feedback leaves the records' room as it was
  assert.equal((await daily.call("/v1/logs", post({ ...turn, provider: "openai" }))).status, 204);
  // the visitor waits for a feedback: one that could not be kept says so (a record is let go without a word)
  const down503 = await relay({ gateFails: true }).call("/v1/feedback", post(rated));
  assert.deepEqual([down503.status, (await down503.json()).error.type], [503, "feedback_unavailable"]);
  assert.equal((await relay({ gateFails: true }).call("/v1/logs", post({ ...turn, provider: "openai" }))).status, 204);
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
  // the owner's: no page reads them, the site's own included — with the token or without it
  for (const headers of [{ Origin: PAGE }, { Origin: PAGE, ...auth }]) {
    const res = await r.call("/v1/security/summary", { headers });
    assert.equal(res.headers.get("Access-Control-Allow-Origin"), null);
  }
  assert.deepEqual(await (await r.call("/v1/security/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: items[1].id }) })).json(), { remaining: 0 });
  // a browser's policy report is kept as an event
  const csp = await r.call("/v1/security/csp", { method: "POST", headers: { "Content-Type": "application/csp-report", Origin: PAGE },
    body: JSON.stringify({ "csp-report": { "violated-directive": "script-src", "blocked-uri": "https://evil.example/x.js" } }) });
  assert.equal(csp.status, 204);
  assert.equal((await (await r.call("/v1/security/export", { headers: auth })).json()).items[0].event.kind, "csp");
}));

test("what another site's page makes a reader's browser send is refused, and never counts against the reader", () => quiet(async () => {
  // reproduced before this was so (2026-11-25): a page with thirty images pointed at paths of this host got each of
  // its readers refused for six hours (referer_foreign, burst, errors, probing: 12), one image at a scanner's path too
  let t = Date.UTC(2026, 10, 25, 12, 0, 0);
  const r = relay({ env: { SENTINEL: "enforce" }, now: () => t, cf: { asn: 4134, country: "CN", httpProtocol: "HTTP/2", tlsVersion: "TLSv1.3" } });
  const planted = (path, headers = {}, init = {}) => r.call(path, { ...init, headers: { ...BROWSER, Accept: "image/avif,image/webp,*/*", "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image", Referer: "https://forum.example/t/42", "CF-Connecting-IP": "203.0.113.7", ...headers } });
  for (let i = 0; i < 30; i++) {
    const res = await planted(`/v1/pixel-${i}.png`);
    assert.equal(res.status, 403);
    t += 200;
  }
  assert.equal((await (await planted("/v1/notes.bak")).json()).error.type, "cross_site"); // a scanner's path
  assert.equal((await planted("/v1/health")).status, 403); // nothing of this host is another site's to embed
  assert.equal((await planted("/v1/chat/completions", { "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", Origin: "https://forum.example" }, { method: "OPTIONS" })).status, 403);
  assert.equal((await planted("/v1/security/csp", { Origin: "https://forum.example", "Content-Type": "text/plain" }, { method: "POST",
    body: JSON.stringify({ "csp-report": { "violated-directive": "script-src", "blocked-uri": "https://x.example/a.js" } }) })).status, 403);
  await r.settle();
  assert.deepEqual(r.watch.summary(t), { ...r.watch.summary(t), visitors: 0, events: 0, blocked: [] }); // not a row, not an event, not a refusal
  assert.equal(r.calls.length, 0);
  // the reader then opens the page: served, with nothing against the address
  const served = await r.call("/v1/chat/completions", post(PAGE_ASK));
  assert.equal(served.status, 200);
  await r.settle();
  const [reader] = r.watch.summary(t).top;
  assert.deepEqual([reader.n, reader.score, reader.flagged, reader.ip], [1, 0, 0, undefined]);
  // the project's own pages are not another site's: the page, and its mirror
  assert.equal((await r.call("/v1/health", { headers: { ...BROWSER, Origin: PAGE } })).status, 200);
  assert.equal((await r.call("/v1/health", { headers: { ...BROWSER, "Sec-Fetch-Site": "cross-site", Origin: "https://psknlr.github.io" } })).status, 200);
  // what is no browser gets nothing by saying a page sent it: refused, where its own request is at least answered
  assert.equal((await r.call("/v1/health", { headers: { "User-Agent": "curl/8.4.0", "CF-Connecting-IP": "198.51.100.9" } })).status, 200);
  assert.equal((await r.call("/v1/health", { headers: { "User-Agent": "curl/8.4.0", "Sec-Fetch-Site": "cross-site", "CF-Connecting-IP": "198.51.100.9" } })).status, 403);
  // a scanner's path asked for in the reader's own name still refuses the address
  const own = await r.call("/v1/notes.bak", { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "45.138.12.10" } });
  assert.equal(own.status, 404);
  await r.settle();
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "45.138.12.10" }))).status, 403);
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

test("a question is counted with its place and visitor — once a turn: a tool round, the self-check's rewrite and a call made again are calls of it", () => quiet(async () => {
  let t = Date.UTC(2026, 9, 6, 16, 30, 0); // 00:30 on the 7th in Beijing: the readers' day
  const r = relay({ now: () => t, cf: { country: "CN", regionCode: "GD", asn: 4134 }, env: { STATS_TOKEN: STATS } });
  const named = (body, turn) => post(body, { "X-Tao-Turn": turn });
  assert.equal((await r.call("/v1/chat/completions", named(PAGE_ASK, "m_first"))).status, 200);
  const round = { ...PAGE_ASK, messages: [...PAGE_ASK.messages, { role: "assistant", content: null, tool_calls: [{ id: "c1", type: "function", function: { name: "classics.search", arguments: "{}" } }] },
    { role: "tool", tool_call_id: "c1", content: "《伤寒论》……" }] };
  t += 5000;
  assert.equal((await r.call("/v1/chat/completions", named(round, "m_first"))).status, 200);
  // the self-check asks for a rewrite, and an answer cut at the output limit is written on: each a call that ends with a
  // user's message — a note of the page's, not a question of the visitor's
  const checked = { ...PAGE_ASK, messages: [...round.messages, { role: "assistant", content: "桂枝汤主之[[x.1]]" }, { role: "user", content: "［自查：回答所引的 [[x.1]] 在语料中查无此段……］" }] };
  t += 5000;
  assert.equal((await r.call("/v1/chat/completions", named(checked, "m_first"))).status, 200);
  t += 5000;
  assert.equal((await r.call("/v1/chat/completions", named(checked, "m_first"))).status, 200); // asked again after a failure
  t += 5000;
  assert.equal((await r.call("/v1/chat/completions", named(PAGE_ASK, "m_second"))).status, 200); // the same visitor asks the same again: another turn
  const s = r.usage.stats(1, "2026-10-07");
  assert.deepEqual(s.today, { view: 0, visitor: 0, question: 2, call: 5, asker: 1 });
  assert.deepEqual(s.places, [{ country: "CN", region: "GD", view: 0, visitor: 0, question: 2, call: 5, asker: 1 }]); // ISO 3166-2, as Cloudflare gives it
  assert.equal(r.ledger.waiting(), 0); // the turns are remembered; without the ledger's key nothing is written down
  const refused = relay({ cf: { country: "US", regionCode: "OH" }, burst: () => false });
  assert.equal((await refused.call("/v1/chat/completions", post(PAGE_ASK))).status, 429);
  assert.deepEqual(refused.usage.stats(1, "2026-09-28").places, []);
}));

test("a page that names no turn: a call that ends with what was asked is a question once, its tool rounds and the same call again are not", () => quiet(async () => {
  const r = relay({ cf: { country: "CN", regionCode: "GD" } });
  const round = { ...PAGE_ASK, messages: [...PAGE_ASK.messages, { role: "assistant", content: null, tool_calls: [{ id: "c1", type: "function", function: { name: "classics.search", arguments: "{}" } }] },
    { role: "tool", tool_call_id: "c1", content: "……" }] };
  for (const body of [PAGE_ASK, round, PAGE_ASK]) assert.equal((await r.call("/v1/chat/completions", post(body))).status, 200);
  assert.deepEqual(r.usage.stats(1, "2026-09-28").today, { view: 0, visitor: 0, question: 1, call: 3, asker: 1 });
  const other = { ...PAGE_ASK, messages: [PAGE_ASK.messages[0], { role: "user", content: "麻黄汤呢？" }] };
  assert.equal((await r.call("/v1/chat/completions", post(other))).status, 200);
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK, { "CF-Connecting-IP": "203.0.113.8" }))).status, 200); // another visitor asks the same
  assert.deepEqual(r.usage.stats(1, "2026-09-28").today, { view: 0, visitor: 0, question: 3, call: 5, asker: 2 });
}));

test("the counts are the owner's: read with the collector's token alone, never by a page", () => quiet(async () => {
  const t = Date.UTC(2026, 9, 7, 4, 0, 0);
  const r = relay({ now: () => t, cf: { country: "CN", regionCode: "BJ" }, env: { STATS_TOKEN: STATS, STATS_PUBLIC: "1" } }); // (neither means anything now)
  await r.call("/v1/chat/completions", post(PAGE_ASK));
  // the page can neither send a bearer to the relay nor read its counts
  const preflight = await r.call("/v1/stats", { method: "OPTIONS", headers: { Origin: PAGE, "Access-Control-Request-Headers": "authorization" } });
  assert.doesNotMatch(preflight.headers.get("Access-Control-Allow-Headers"), /Authorization/i);
  for (const auth of [null, STATS, "not-the-token-0123456789"]) {
    const res = await r.call("/v1/stats?days=7", { headers: { Origin: PAGE, ...(auth ? { Authorization: `Bearer ${auth}` } : {}) } });
    assert.equal(res.status, 401);
    assert.equal(res.headers.get("Access-Control-Allow-Origin"), null);
    assert.deepEqual(await res.json(), { error: "需要收集令牌" });
  }
  const ok = await r.call("/v1/stats?days=7", { headers: { Authorization: `Bearer ${TOKEN}` } }); // the collector's, as the repository's workflow sends it
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), null);
  const body = await ok.json();
  assert.equal(body.asOf, "2026-10-07");
  assert.deepEqual(body.today, { view: 0, visitor: 0, question: 1, call: 1, asker: 1 });
  assert.equal(body.days.length, 7);
  assert.deepEqual([body.totals.question, body.totals.call], [1, 1]);
  assert.equal(body.places[0].region, "BJ");
}));

// ------------------------------------------------------------------ the second model (GPT-6 Luna, through OpenAI)
const OKEY = "openai-test-key-not-a-real-one";
const LUNA = { model: "GPT-6 Luna", messages: [{ role: "system", content: "你是道乃久" }, { role: "user", content: "桂枝汤主治什么？" }], stream: true,
  tools: [{ type: "function", function: { name: "classics.search" } }], max_completion_tokens: 100000, stream_options: { include_usage: true } };
const lunaRound = (ask, n = 1) => ({ ...ask, messages: [...ask.messages,
  { role: "assistant", content: null, reasoning_details: [{ type: "reasoning.text", text: "想" }], tool_calls: [{ id: `c${n}`, type: "function", function: { name: "classics.search", arguments: "{}" } }] },
  { role: "tool", tool_call_id: `c${n}`, content: "《伤寒论》……" }] });
const asking = (question) => ({ ...LUNA, messages: [LUNA.messages[0], { role: "user", content: question }] });
const turnOf = (id, headers = {}) => ({ "X-Tao-Turn": id, ...headers });

test("the second model: offered only with its own key, sent to OpenAI with it, the page's other fields left behind", () => quiet(async () => {
  const health = async (env) => (await (await relay({ env }).call("/v1/health")).json());
  assert.deepEqual((await health({})).models, ["Tao-R1"]); // no OPENAI_API_KEY: not offered
  const offered = await health({ OPENAI_API_KEY: OKEY });
  assert.deepEqual(offered.models, ["Tao-R1", "GPT-6 Luna"]);
  assert.deepEqual(offered.limits.questions, { "GPT-6 Luna": 3 });
  assert.ok(!JSON.stringify(offered).includes(OKEY));
  assert.deepEqual((await health({ OPENAI_API_KEY: OKEY, OPENAI: "off" })).models, ["Tao-R1"]);
  const refused = await relay().call("/v1/chat/completions", post(LUNA)); // asked for without the key: not a model it offers
  assert.equal(refused.status, 400);

  const r = relay({ env: { OPENAI_API_KEY: OKEY }, upstream: (url) => sse([
    '{"id":"x","model":"gpt-6-luna-2026-10-01","choices":[{"delta":{"content":"太阳中风"}}]}',
    '{"id":"x","model":"gpt-6-luna-2026-10-01","choices":[],"usage":{"prompt_tokens":120,"completion_tokens":30}}', "[DONE]"]) });
  const asked = { ...lunaRound(LUNA), thinking: { type: "disabled" }, temperature: 0.3, reasoning_split: true, n: 2 };
  const res = await r.call("/v1/chat/completions", post({ ...asked, messages: asked.messages.slice(0, 2) }, turnOf("m_a")));
  assert.equal(res.status, 200);
  const text = await res.text();
  assert.match(text, /"model":"GPT-6 Luna"/); // its public name, as the page asked for it
  assert.doesNotMatch(text, /gpt-6-luna/);
  const round = await r.call("/v1/chat/completions", post(asked, turnOf("m_a")));
  assert.equal(round.status, 200);
  await round.text();
  const [first, second] = r.calls;
  assert.equal(first.url, "https://api.openai.com/v1/chat/completions");
  assert.equal(first.init.headers.Authorization, `Bearer ${OKEY}`); // its own key, never MiniMax's
  assert.equal(second.body.model, "gpt-6-luna");
  assert.equal(second.body.max_completion_tokens, 32768);
  for (const k of ["thinking", "temperature", "reasoning_split", "n", "max_tokens"]) assert.equal(second.body[k], undefined, k);
  assert.deepEqual(second.body.stream_options, { include_usage: true });
  assert.equal(second.body.tools.length, 1);
  assert.equal(second.body.messages[2].reasoning_details, undefined); // what another model sent back stays here
  assert.equal(second.body.reasoning_effort, "none"); // with tools: GPT-6 Luna on Chat Completions calls functions only so
  assert.equal(second.body.messages[2].tool_calls[0].id, "c1");
  // Tao-R1 goes on to MiniMax with MiniMax's key, as before
  await (await r.call("/v1/chat/completions", post(PAGE_ASK))).text();
  assert.equal(r.calls[2].url, "https://api.minimax.cn/v1/chat/completions");
  assert.equal(r.calls[2].init.headers.Authorization, `Bearer ${KEY}`);
  // OpenAI refusing the key: told in the default service's words, the key nowhere
  const denied = await relay({ env: { OPENAI_API_KEY: OKEY }, upstream: async () => new Response(JSON.stringify({ error: { message: `Incorrect API key provided: ${OKEY}` } }), { status: 401 }) })
    .call("/v1/chat/completions", post(LUNA, turnOf("m_b")));
  assert.equal(denied.status, 503);
  const said = JSON.stringify(await denied.json());
  assert.ok(!said.includes(OKEY) && !/openai|OpenAI/.test(said), said);
  assert.deepEqual(openaiBody({ max_tokens: 50, messages: [{ role: "user", content: "问", extra: 1 }] }, "m", 100),
    { model: "m", messages: [{ role: "user", content: "问" }], max_completion_tokens: 50 });
  // a cap below the least a reasoning model takes is raised to it (16 was refused); no tools, no effort named
  assert.deepEqual(openaiBody({ max_completion_tokens: 16, messages: [] }, "m", 32768, 2048), { model: "m", messages: [], max_completion_tokens: 2048 });
  assert.equal(config().openai.minOutput, 2048);
  assert.deepEqual(config().openai.locations, ["enam", "wnam"]);
  assert.deepEqual(config({ OPENAI_LOCATION: "off" }).openai.locations, []);
  assert.deepEqual(config({ OPENAI_LOCATION: "apac, nowhere" }).openai.locations, ["apac"]); // a place Cloudflare has only
}));

test("the second model is called from where OpenAI serves, and a region it refuses is told as such", () => quiet(async () => {
  const where = [];
  const r = relay({ env: { OPENAI_API_KEY: OKEY }, egress: where });
  await (await r.call("/v1/chat/completions", post(LUNA, turnOf("e1")))).text();
  assert.deepEqual(where, ["enam"]); // OPENAI_LOCATION
  assert.equal(r.calls[0].url, "https://api.openai.com/v1/chat/completions");
  await (await r.call("/v1/chat/completions", post(PAGE_ASK))).text(); // Tao-R1: straight from the visitor's location
  assert.deepEqual(where, ["enam"]);
  const here = [];
  const direct = relay({ env: { OPENAI_API_KEY: OKEY, OPENAI_LOCATION: "off" }, egress: here });
  await (await direct.call("/v1/chat/completions", post(LUNA, turnOf("e2")))).text();
  assert.deepEqual(here, []);
  const said = [];
  const err = console.error;
  console.error = (...a) => said.push(a.join(" "));
  try {
    const refused = relay({ env: { OPENAI_API_KEY: OKEY }, upstream: async () => new Response(JSON.stringify({ error: {
      message: "Country, region, or territory not supported", type: "request_forbidden", code: "unsupported_country_region_territory" } }), { status: 403 }) });
    const res = await refused.call("/v1/chat/completions", post(LUNA, turnOf("e3")));
    assert.equal(res.status, 503);
    assert.equal((await res.json()).error.type, "upstream_region");
    const bad = relay({ env: { OPENAI_API_KEY: OKEY }, upstream: async () => new Response(JSON.stringify({ error: {
      message: "Function tools with reasoning_effort are not supported for gpt-6-luna in /v1/chat/completions.", type: "invalid_request_error",
      param: "reasoning_effort", code: "unsupported_parameter" } }), { status: 400 }) });
    assert.equal((await bad.call("/v1/chat/completions", post(LUNA, turnOf("e4")))).status, 400);
  } finally {
    console.error = err;
  }
  assert.ok(said.includes("upstream openai 403 unsupported_country_region_territory"), said.join("\n"));
  assert.ok(said.includes("upstream openai 400 unsupported_parameter reasoning_effort"), said.join("\n")); // the owner sees which
  assert.ok(!said.join("\n").includes("not supported"), "never the upstream's message");
}));

test("a region OpenAI refuses from one place is asked from the next; where each is seen is told", () => quiet(async () => {
  const where = [];
  let n = 0;
  const region = () => new Response(JSON.stringify({ error: { code: "unsupported_country_region_territory" } }), { status: 403 });
  const r = relay({ env: { OPENAI_API_KEY: OKEY }, egress: where, upstream: async () => (n++ === 0 ? region() : sse(['{"choices":[{"delta":{"content":"答"}}]}', "[DONE]"])) });
  const res = await r.call("/v1/chat/completions", post(LUNA, turnOf("p1")));
  assert.equal(res.status, 200);
  assert.match(await res.text(), /答/);
  assert.deepEqual(where, ["enam", "wnam"]);
  const all = relay({ env: { OPENAI_API_KEY: OKEY }, egress: [], upstream: async () => region() }); // refused from everywhere: told so
  assert.equal((await (await all.call("/v1/chat/completions", post(LUNA, turnOf("p2")))).json()).error.type, "upstream_region");
  // GET /v1/egress: OpenAI's edge's own trace, from the Worker and from each place; and whether the default model's
  // host answers anything at all from each place it is asked from, and how soon (no key sent, the host not named)
  const traced = [];
  const sent = [];
  const t = relay({ env: { OPENAI_API_KEY: OKEY }, egress: traced, cf: { colo: "HKG" }, upstream: async (url, init, place) => {
    if (url === "https://api.minimax.cn/") {
      sent.push(init);
      if (place) throw new TypeError("connection refused");
      return new Response("404 page not found", { status: 404 });
    }
    assert.equal(url, "https://api.openai.com/cdn-cgi/trace");
    return new Response(`fl=1\nip=2a06:98c0::1\ncolo=${place ? "IAD" : "HKG"}\nloc=${place ? "US" : "HK"}\n`, { status: 200 });
  } });
  // anyone may see how a call from where they are looks to OpenAI's edge: one request; the rest — from each place,
  // and of the default model's host — is the owner's diagnostic, with the collector's token: a dozen requests from
  // several places, seconds waited for each, and where the service calls from
  for (const headers of [{ Origin: PAGE }, { ...BROWSER, Origin: PAGE }, { Authorization: "Bearer not-the-token-0123456789" }]) {
    const open = await t.call("/v1/egress", { headers });
    assert.deepEqual([open.status, await open.json()], [200, { worker: "HKG", direct: { colo: "HKG", loc: "HK" } }]);
  }
  assert.deepEqual([traced, sent, t.calls.length], [[], [], 3]); // one trace each, from here: nothing placed, the model's host not asked
  const seen = await (await t.call("/v1/egress", { headers: { Authorization: `Bearer ${TOKEN}` } })).json();
  const { model, ...openai } = seen;
  assert.deepEqual(openai, { worker: "HKG", direct: { colo: "HKG", loc: "HK" }, places: { enam: { colo: "IAD", loc: "US" }, wnam: { colo: "IAD", loc: "US" } } });
  assert.deepEqual(Object.keys(model), ["direct", "apac"]); // UPSTREAM_VIA
  assert.equal(model.direct.status, 404); // it answered: reachable from here
  assert.equal(model.apac.error, "unreachable");
  assert.ok(Number.isFinite(model.direct.ms) && Number.isFinite(model.apac.ms));
  assert.ok(sent.every((init) => !init.headers.Authorization && init.method === "GET")); // no key
  assert.ok(!JSON.stringify(seen).includes("2a06") && !/minimax|openai/i.test(JSON.stringify(seen))); // no address, no host
}));

test("the default model: the one DEFAULT_MODEL names while it is offered and until DEFAULT_MODEL_UNTIL, then Tao-R1", async () => {
  const until = { DEFAULT_MODEL: "GPT-6 Luna", DEFAULT_MODEL_UNTIL: "2026-11-10T00:00:00+08:00" };
  const at = (iso, env) => relay({ env, now: () => Date.parse(iso) }).call("/v1/health").then((res) => res.json());
  assert.equal((await at("2026-11-08T03:00:00Z", { OPENAI_API_KEY: OKEY, ...until })).default, "GPT-6 Luna");
  assert.equal((await at("2026-11-09T15:59:59Z", { OPENAI_API_KEY: OKEY, ...until })).default, "GPT-6 Luna"); // 9 Nov 23:59:59 in Singapore (UTC+8)
  assert.equal((await at("2026-11-09T16:00:00Z", { OPENAI_API_KEY: OKEY, ...until })).default, "Tao-R1");
  assert.equal((await at("2026-11-08T03:00:00Z", until)).default, "Tao-R1"); // not offered (no key): not the default
  assert.equal((await at("2026-11-08T03:00:00Z", { OPENAI_API_KEY: OKEY })).default, "Tao-R1"); // none named
  const c = config({ DEFAULT_MODEL: "GPT-6 Luna", DEFAULT_MODEL_UNTIL: "not a time" });
  assert.equal(defaultModel(["Tao-R1", "GPT-6 Luna"], c, Date.now()), "Tao-R1"); // an unreadable end: never
  assert.equal(defaultModel(["Tao-R1", "GPT-6 Luna"], config({ DEFAULT_MODEL: "GPT-6 Luna" }), Date.now()), "GPT-6 Luna"); // no end
});

test("the second model: three questions a visitor a day, however many rounds a question takes", () => quiet(async () => {
  let t = Date.UTC(2026, 9, 10, 12, 0, 0);
  const r = relay({ env: { OPENAI_API_KEY: OKEY }, now: () => t });
  const call = (body, headers) => r.call("/v1/chat/completions", post(body, headers)).then(async (res) => { await res.text(); return res.status; });
  // a turn: its question, two tool rounds, the self-check's note (a user message the page adds) — one question
  assert.equal(await call(LUNA, turnOf("m_1")), 200);
  assert.equal(await call(lunaRound(LUNA, 1), turnOf("m_1")), 200);
  assert.equal(await call(lunaRound(lunaRound(LUNA, 1), 2), turnOf("m_1")), 200);
  const review = { ...lunaRound(LUNA), messages: [...lunaRound(LUNA).messages, { role: "assistant", content: "答" }, { role: "user", content: "［自查：……］" }] };
  assert.equal(await call(review, turnOf("m_1")), 200);
  assert.equal(await call(asking("麻黄汤呢？"), turnOf("m_2")), 200);
  assert.equal(await call(asking("小柴胡汤呢？"), turnOf("m_3")), 200);
  const fourth = await r.call("/v1/chat/completions", post(asking("葛根汤呢？"), turnOf("m_4")));
  assert.equal(fourth.status, 429);
  const msg = (await fourth.json()).error.message;
  assert.match(msg, /GPT-6 Luna 免费额度已用完（每人每天 3 个问题）/);
  assert.ok(Number(fourth.headers.get("Retry-After")) > 3600);
  assert.equal(await call(lunaRound(LUNA, 3), turnOf("m_1")), 200); // a question already counted goes on
  assert.equal(await call(PAGE_ASK), 200); // Tao-R1 is not counted with it
  assert.equal(await call(asking("葛根汤呢？"), turnOf("m_4", { "CF-Connecting-IP": "198.51.100.9" })), 200); // another visitor
  // without the page's turn: a question by what was asked — asked again (the page retrying) counted once; a tool round
  // of a question not counted today refused
  const plain = relay({ env: { OPENAI_API_KEY: OKEY }, now: () => t });
  const pcall = (body) => plain.call("/v1/chat/completions", post(body)).then(async (res) => { await res.text(); return res.status; });
  assert.equal(await pcall(lunaRound(asking("问一"))), 403);
  for (const q of ["问一", "问一", "问二", "问三"]) assert.equal(await pcall(asking(q)), 200);
  assert.equal(await pcall(lunaRound(asking("问一"))), 200);
  assert.equal(await pcall(asking("问四")), 429);
  t = Date.UTC(2026, 9, 11, 0, 0, 1); // a new day
  assert.equal(await call(asking("葛根汤呢？"), turnOf("m_5")), 200);
  // under the questions, calls: a question's rounds are bounded too
  const tight = relay({ env: { OPENAI_API_KEY: OKEY, OPENAI_CALLS_PER_DAY: "2" }, now: () => t });
  const tcall = (body) => tight.call("/v1/chat/completions", post(body, turnOf("m_x"))).then(async (res) => { await res.text(); return res.status; });
  assert.deepEqual([await tcall(LUNA), await tcall(lunaRound(LUNA)), await tcall(lunaRound(LUNA, 2))], [200, 200, 429]);
  // a refused call counts no question
  const minute = relay({ env: { OPENAI_API_KEY: OKEY, OPENAI_PER_MINUTE: "1" }, now: () => t });
  const mcall = (body, id) => minute.call("/v1/chat/completions", post(body, turnOf(id))).then(async (res) => { await res.text(); return res.status; });
  assert.deepEqual([await mcall(LUNA, "a"), await mcall(asking("二"), "b")], [200, 429]);
  assert.equal(Number(minute.limiter.sql.exec("SELECT SUM(n) AS n FROM hits WHERE k LIKE 'd:openai-q:%'").one().n), 1);
}));

test("a record of a second-model turn keeps the model that answered", () => quiet(async () => {
  const r = relay({ env: { OPENAI_API_KEY: OKEY } });
  await (await r.call("/v1/chat/completions", post(LUNA, turnOf("t1")))).text();
  const res = await r.call("/v1/logs", post({ ...turn, model: "GPT-6 Luna" }));
  assert.equal(res.status, 204);
  assert.equal(r.book.records(0, 10).items[0].record.model, "gpt-6-luna");
}));

// ------------------------------------------------------------------ sponsorship (赞助)
const SECRET = "sponsor-secret-0123456789abcdef-0123456789";
const GIFT = { v: 1, agree: true, provider: "OpenAI", base_url: "https://api.openai.com/v1?x=1#y", model: "gpt-6-luna",
  key: "sk-proj-sponsored-0123456789abcdefXYZ", note: "每月上限 20 美元", contact: "a@example.org", extra: "dropped" };

test("sponsorship: off without SPONSOR_SECRET; a key given is kept encrypted, apart from the records, read only by the owner", () => quiet(async () => {
  const off = relay();
  assert.equal((await (await off.call("/v1/health")).json()).sponsor, false);
  assert.equal((await off.call("/v1/sponsor", post(GIFT))).status, 404);
  assert.equal((await relay({ env: { SPONSOR_SECRET: "too-short" } }).call("/v1/sponsor", post(GIFT))).status, 404);

  const said = [];
  const [log, err] = [console.log, console.error];
  console.log = (...a) => said.push(a.join(" "));
  console.error = (...a) => said.push(a.join(" "));
  try {
    const r = relay({ env: { SPONSOR_SECRET: SECRET } });
    assert.equal((await (await r.call("/v1/health")).json()).sponsor, true);
    const res = await r.call("/v1/sponsor", post(GIFT));
    assert.equal(res.status, 204);
    assert.equal(res.headers.get("Access-Control-Allow-Origin"), PAGE);
    // stored: the key sealed, a hint beside it; nothing in the records the repository collects
    const stored = JSON.stringify(r.sponsors.sql.exec("SELECT * FROM sponsors").toArray());
    assert.ok(!stored.includes(GIFT.key) && !stored.includes("sponsored-0123"), stored);
    assert.equal(r.book.records(0, 10).items.length, 0);
    // the owner's list: hinted keys only; the base URL without its query or fragment; nothing unknown kept
    const owner = { headers: { Authorization: `Bearer ${SECRET}` } };
    const { sponsors } = await (await r.call("/v1/sponsors", owner)).json();
    assert.equal(sponsors.length, 1);
    assert.deepEqual({ ...sponsors[0], received: undefined }, { id: 1, received: undefined, provider: "OpenAI", base_url: "https://api.openai.com/v1",
      model: "gpt-6-luna", hint: "sk-…fXYZ", note: "每月上限 20 美元", contact: "a@example.org" });
    assert.ok(!JSON.stringify(sponsors).includes(GIFT.key));
    const one = await (await r.call("/v1/sponsors?reveal=1", owner)).json();
    assert.equal(one.sponsor.key, GIFT.key);
    assert.equal(one.sponsor.sealed, undefined);
    // anyone else: nothing
    for (const auth of [{}, { Authorization: `Bearer ${TOKEN}` }, { Authorization: `Bearer ${SECRET}x` }]) {
      assert.equal((await r.call("/v1/sponsors?reveal=1", { headers: auth })).status, 401);
    }
    assert.equal((await r.call("/v1/sponsors/delete", { method: "POST", body: JSON.stringify({ id: 1 }) })).status, 401);
    // the same key again: one sponsorship, what was said of it updated
    assert.equal((await r.call("/v1/sponsor", post({ ...GIFT, model: "gpt-6-luna-mini" }))).status, 204);
    const again = (await (await r.call("/v1/sponsors", owner)).json()).sponsors;
    assert.deepEqual(again.map((x) => x.model), ["gpt-6-luna-mini"]);
    assert.deepEqual(await (await r.call("/v1/sponsors/delete", { ...owner, method: "POST", body: JSON.stringify({ id: 1 }) })).json(), { removed: 1 });
    assert.deepEqual((await (await r.call("/v1/sponsors", owner)).json()).sponsors, []);
    // a secret changed since: the key cannot be opened, and the owner is told why
    await r.call("/v1/sponsor", post(GIFT));
    const rotated = await handle(new Request("https://chat-api.impf.ai/v1/sponsors?reveal=2", { headers: { Authorization: `Bearer ${SECRET}-new` } }),
      { MINIMAX_API_KEY: KEY, SPONSOR_SECRET: `${SECRET}-new` }, { now: () => Date.now(), sponsors: { get: async (id) => r.sponsors.get(id) } });
    assert.equal(rotated.status, 409);
  } finally {
    console.log = log;
    console.error = err;
  }
  assert.ok(!said.join("\n").includes(GIFT.key), "a sponsored key is never logged");
}));

test("sponsorship: only from the page, only what makes sense, within its limits", () => quiet(async () => {
  const r = relay({ env: { SPONSOR_SECRET: SECRET, SPONSOR_PER_DAY: "2" } });
  assert.equal((await r.call("/v1/sponsor", post(GIFT, { Origin: "https://evil.example" }))).status, 403);
  const bad = async (gift, re) => {
    const res = await r.call("/v1/sponsor", post(gift));
    assert.equal(res.status, 400, JSON.stringify(gift));
    assert.match((await res.json()).error.message, re);
  };
  await bad({ ...GIFT, agree: false }, /同意/);
  await bad({ ...GIFT, key: "sk proj with spaces" }, /API Key/);
  await bad({ ...GIFT, key: "short" }, /API Key/);
  await bad({ ...GIFT, model: "  " }, /模型名/);
  await bad({ ...GIFT, base_url: "http://api.example.com/v1" }, /https/);
  await bad({ ...GIFT, base_url: "https://user:pw@api.example.com/v1" }, /https/);
  await bad("not json", /JSON/);
  assert.equal((await r.call("/v1/sponsor", post("x".repeat(9000)))).status, 413);
  assert.equal(r.sponsors.list().length, 0);
  assert.equal((await r.call("/v1/sponsor", post({ ...GIFT, key: "sk-one-0123456789abcdef" }))).status, 204);
  assert.equal((await r.call("/v1/sponsor", post({ ...GIFT, key: "sk-two-0123456789abcdef" }))).status, 204);
  const third = await r.call("/v1/sponsor", post({ ...GIFT, key: "sk-three-0123456789abcdef" }));
  assert.equal(third.status, 429);
  assert.match((await third.json()).error.message, /每人每天 2 次/);
  const full = relay({ env: { SPONSOR_SECRET: SECRET, SPONSOR_KEEP: "1" } });
  assert.equal((await full.call("/v1/sponsor", post(GIFT))).status, 204);
  assert.equal((await full.call("/v1/sponsor", post({ ...GIFT, key: "sk-another-0123456789" }, { "CF-Connecting-IP": "198.51.100.3" }))).status, 503);
  assert.equal((await full.call("/v1/sponsor", post({ ...GIFT, model: "m2" }))).status, 204); // the same key: an update, not a new one
}));

test("sponsorship: sealing round-trips under its secret only; the form's fields are reduced to what is known", async () => {
  const sealed = await seal("sk-abc-0123456789", SECRET);
  assert.match(sealed, /^v1\./);
  assert.notEqual(sealed, await seal("sk-abc-0123456789", SECRET)); // a fresh IV each time
  assert.equal(await unseal(sealed, SECRET), "sk-abc-0123456789");
  assert.equal(await unseal(sealed, `${SECRET}x`), null);
  assert.equal(await unseal("not sealed", SECRET), null);
  const { sponsor } = normalizeSponsor({ ...GIFT, note: ` ${"说".repeat(2000)} ` });
  assert.deepEqual(Object.keys(sponsor).sort(), ["base_url", "contact", "key", "model", "note", "provider"]);
  assert.equal(sponsor.note.length, 1000);
  assert.deepEqual(normalizeSponsor({ ...GIFT, base_url: "" }).sponsor.base_url, "");
});

// ------------------------------------------------------------------ the activity ledger (security/ledger.js)
const ACTIVITY_KEY = "activity-key-for-tests-0123456789abcdef";
const T1 = Date.UTC(2026, 10, 25, 4, 0, 0); // noon in Beijing
const withLedger = (over = {}) => relay({ now: () => T1, cf: { country: "CN", regionCode: "GD", asn: 4134, httpProtocol: "HTTP/2", tlsVersion: "TLSv1.3" }, ...over,
  env: { ACTIVITY_KEY, ACTIVITY_DB: d1(), ...(over.env || {}) } });
const usageStream = (input = 70, output = 40) => sse(['{"choices":[{"delta":{"content":"可以"}}]}',
  `{"choices":[{"finish_reason":"stop","index":0,"delta":{}}],"model":"MiniMax-M3","usage":{"prompt_tokens":${input},"completion_tokens":${output}}}`, "[DONE]"]);
const visitorOf = (n) => `v_${String(n).padStart(24, "0")}`;
const beaconOf = (body, headers = {}) => ({ method: "POST", headers: { "Content-Type": "text/plain;charset=UTF-8", Origin: PAGE, "CF-Connecting-IP": "203.0.113.7", ...BROWSER, ...headers },
  body: JSON.stringify(body) });

test("the relay says what the page may send: a turn's name always; a visitor's pass and a turn's end with the ledger", async () => {
  const bare = await (await relay().call("/v1/health")).json();
  assert.deepEqual(bare.activity, { turn: true });
  const r = withLedger();
  assert.deepEqual((await (await r.call("/v1/health")).json()).activity, { turn: true, beacon: true, ids: "notice" });
  assert.deepEqual((await (await withLedger({ env: { ACTIVITY_IDS: "off" } }).call("/v1/health")).json()).activity, { turn: true, beacon: true, ids: "off" });
  assert.deepEqual((await (await relay({ env: { ACTIVITY_KEY } }).call("/v1/health")).json()).activity, { turn: true }); // the key without the registry: no ledger
  const preflight = await r.call("/v1/chat/completions", { method: "OPTIONS", headers: { Origin: PAGE, "Access-Control-Request-Headers": "x-tao-turn,x-tao-visitor" } });
  assert.match(preflight.headers.get("Access-Control-Allow-Headers"), /X-Tao-Turn, X-Tao-Visitor/);
  assert.equal((await r.call("/v1/activity/health")).status, 401);
  const health = await (await r.call("/v1/activity/health", { headers: { Authorization: `Bearer ${TOKEN}` } })).json();
  assert.deepEqual([health.relay.source, health.relay.waiting, health.relay.dropped, health.ids], ["relay", 0, 0, "notice"]);
  assert.equal((await relay().call("/v1/activity/health", { headers: { Authorization: `Bearer ${TOKEN}` } })).status, 404);
});

test("with the ledger a turn is written down: its question once, each model call with how it ended and what it cost, for the visitor the pass names", () => quiet(async () => {
  let t = T1;
  const r = withLedger({ now: () => t, upstream: () => usageStream() });
  const pass = await passFor(visitorOf(7), ACTIVITY_KEY, T1);
  const headers = { "X-Tao-Turn": "m_turn-1", "X-Tao-Visitor": pass };
  for (let i = 0; i < 3; i++) {
    const res = await r.call("/v1/chat/completions", post(PAGE_ASK, headers));
    assert.equal(res.status, 200);
    await res.text(); // the reply read to its end: its usage has passed
    t += 4000;
  }
  await r.settle();
  const events = r.events();
  // (each call's end is told when its reply has gone, after the answer)
  assert.deepEqual(events.map((e) => e.event_type), ["question_submitted", "model_invocation", "model_settled", "model_invocation", "model_settled", "model_invocation", "model_settled"]);
  const [q, call] = events;
  assert.deepEqual([q.visitor_id, q.basis, q.named, q.provider, q.model, q.route, q.country, q.region, q.traffic_class, q.risk_score, q.day],
    [visitorOf(7), "relay", true, "impf", "Tao-R1", "/v1/chat/completions", "CN", "GD", "human", 0, "2026-11-25"]);
  assert.match(q.turn_id, /^trn_[0-9A-Z]{26}$/);
  assert.equal(new Set(events.map((e) => e.turn_id)).size, 1);
  assert.match(call.invocation_id, /^inv_[0-9A-Z]{26}$/);
  const done = events.at(-1);
  assert.deepEqual([done.execution_status, done.http_status, done.input_tokens, done.output_tokens, done.asks, done.retry_count, done.via], ["ok", 200, 70, 40, 1, 0, "direct"]);
  // not the page's name of the turn, the pass, the address, the agent or a word of the question
  const text = JSON.stringify(events);
  for (const kept of ["m_turn-1", pass.split(".")[2], "203.0.113", "Mozilla", "桂枝"]) assert.ok(!text.includes(kept), kept);
  const db = await r.registry();
  assert.deepEqual(db.rows("SELECT basis, calls, input_tokens, output_tokens, archive_status, visitor_id FROM question_events"),
    [{ basis: "relay", calls: 3, input_tokens: 210, output_tokens: 120, archive_status: "not_archived", visitor_id: visitorOf(7) }]);
  // a pass that is not one, or past its time, names no one: the call is counted all the same
  const anon = withLedger({ upstream: () => usageStream() });
  for (const bad of ["", "v_000000000000000000000007.zzzz.AAAAAAAAAAAAAAAAAAAAAA", await passFor(visitorOf(7), ACTIVITY_KEY, T1 - 3 * 86400000)]) {
    await (await anon.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": `m_${bad.length}`, ...(bad ? { "X-Tao-Visitor": bad } : {}) }))).text();
  }
  await anon.settle();
  assert.deepEqual(anon.events().filter((e) => e.event_type === "question_submitted").map((e) => e.visitor_id), [null, null, null]);
}));

test("a call that got no reply, and a call refused, are written down with why", () => logged(async () => {
  const silent = withLedger({ upstream: () => new Response("{\"error\":{\"code\":\"server_error\"}}", { status: 500 }), env: { UPSTREAM_ATTEMPTS: "2", UPSTREAM_VIA: "direct" } });
  assert.equal((await silent.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": "m_a" }))).status, 502);
  await silent.settle();
  const ended = silent.events().find((e) => e.event_type === "model_settled");
  assert.deepEqual([ended.execution_status, ended.http_status, ended.asks, ended.retry_count, ended.input_tokens], ["upstream_error", 502, 2, 1, undefined]);
  // the day's calls spent: the second call is refused, and that is an event too — with the reason, and no question of it
  const full = withLedger({ env: { PER_DAY: "1" } });
  await (await full.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": "m_b" }))).text();
  assert.equal((await full.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": "m_c" }))).status, 429);
  await full.settle();
  const events = full.events();
  assert.deepEqual(events.map((e) => [e.event_type, e.detail || null, e.status]), [["question_submitted", null, null], ["model_invocation", null, null],
    ["model_settled", null, undefined], ["model_refused", "day", 429]]);
  const db = await full.registry();
  const s = await ledgerStats(db, { from: "2026-11-25", to: "2026-11-25" });
  assert.deepEqual([s.totals.questions, s.totals.model_calls_relay, s.questions.refusals], [1, 1, [["day", 1]]]);
}));

test("a record taken in archives its turn in the ledger, and says nothing of who: recorded and unrecorded questions are counted alike", () => quiet(async () => {
  const r = withLedger({ upstream: () => usageStream() });
  const pass = await passFor(visitorOf(3), ACTIVITY_KEY, T1);
  for (const id of ["m_one", "m_two", "m_three"]) await (await r.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": id, "X-Tao-Visitor": pass }))).text();
  // the visitor agreed to records: the first turn's arrives (twice: it was taken up again), then one of a turn asked of their own model
  for (const record of [{ ...turn, id: "m_one" }, { ...turn, id: "m_one", resumed: 1 }, { ...turn, id: "m_own", provider: "custom-abc123", model: "my-private-deployment", rounds: 2 }]) {
    assert.equal((await r.call("/v1/logs", post(record))).status, 204);
  }
  await r.settle();
  const events = r.events();
  const archived = events.filter((e) => e.event_type === "record_archived");
  assert.equal(archived.length, 2);
  assert.ok(archived.every((e) => !("visitor_id" in e) && !("question" in e) && !("answer" in e)));
  assert.deepEqual([archived[0].execution_status, archived[0].tool_count, archived[0].input_tokens, archived[0].runtime, archived[0].turn_index], ["done", 1, 1200, "browser", 1]);
  const own = events.filter((e) => e.event_type === "question_submitted").at(-1);
  assert.deepEqual([own.basis, own.provider, own.model, own.visitor_id], ["record", "custom", null, null]); // their own endpoint and model are their settings
  const text = JSON.stringify(events);
  for (const kept of ["m_one", "m_own", "桂枝", "太阳中风", "c_x", "my-private", "abc123"]) assert.ok(!text.includes(kept), kept);
  const db = await r.registry();
  const s = await ledgerStats(db, { from: "2026-11-25", to: "2026-11-25" });
  assert.deepEqual([s.totals.questions, s.totals.questions_archived, s.totals.questions_unarchived], [4, 2, 2]);
  assert.deepEqual(db.rows("SELECT basis, archive_status, visitor_id IS NOT NULL AS named, content_consent FROM question_events ORDER BY basis DESC, archive_status"), [
    { basis: "relay", archive_status: "archived", named: 1, content_consent: 1 }, { basis: "relay", archive_status: "not_archived", named: 1, content_consent: null },
    { basis: "relay", archive_status: "not_archived", named: 1, content_consent: null }, { basis: "record", archive_status: "archived", named: 0, content_consent: 1 }]);
  // the book has the record whole, as before; nothing in the book says which visitor
  assert.equal(r.book.records(0, 10).items.length, 3);
  assert.ok(!JSON.stringify(r.book.records(0, 10)).includes(visitorOf(3)));
}));

test("a turn's end as the page tells it: a question asked of one's own model is counted, in counts and never in words", () => quiet(async () => {
  const r = withLedger({ upstream: () => usageStream() });
  const pass = await passFor(visitorOf(5), ACTIVITY_KEY, T1);
  const told = { v: 1, kind: "turn", turn: "m_own-1", pass, provider: "deepseek", model: "deepseek-chat", status: "done", rounds: 4, tool_count: 6,
    tools: { "classics.search": 5, "study.formula": 1, "not a tool": 3 }, retries: 1, input: 9000, output: 700, ms: 41000, runtime: "browser", corpus: "canon", module: "chat",
    turn_index: 2, consent: false, lang: "zh", question: "must not be kept", answer: "nor this", key: "sk-secret" };
  assert.equal((await r.call("/v1/activity", beaconOf(told))).status, 204);
  assert.equal((await r.call("/v1/activity", beaconOf({ ...told, rounds: 5 }))).status, 204); // told again (the turn was taken up): one question still
  // a diet conversation: counted, and for no one, whatever pass came with it
  assert.equal((await r.call("/v1/activity", beaconOf({ ...told, turn: "m_diet", module: "diet" }))).status, 204);
  // the default service's own turn: its question was counted with its call, the page adds how it ended
  await (await r.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": "m_relay", "X-Tao-Visitor": pass }))).text();
  assert.equal((await r.call("/v1/activity", beaconOf({ ...told, turn: "m_relay", provider: "impf", model: "Tao-R1", input: 1, output: 1, consent: true }))).status, 204);
  // the page answered it itself
  assert.equal((await r.call("/v1/activity", beaconOf({ v: 1, kind: "turn", turn: "m_fixed", provider: "fixed", status: "done", rounds: 0, module: "chat" }))).status, 204);
  await r.settle();
  const events = r.events();
  const text = JSON.stringify(events);
  for (const kept of ["must not", "nor this", "sk-secret", "m_own-1", "not a tool", pass.split(".")[2]]) assert.ok(!text.includes(kept), kept);
  const db = await r.registry();
  assert.deepEqual(db.rows("SELECT basis, provider, model, visitor_id, module, rounds, calls, tool_count, tools, input_tokens, output_tokens, execution_status, content_consent, " +
    "turn_index, runtime, ui_lang, retry_count FROM question_events ORDER BY provider, module"), [
    { basis: "client", provider: "deepseek", model: "deepseek-chat", visitor_id: visitorOf(5), module: "chat", rounds: 5, calls: 0, tool_count: 6,
      tools: '{"classics.search":5,"study.formula":1}', input_tokens: 9000, output_tokens: 700, execution_status: "done", content_consent: 0, turn_index: 2, runtime: "browser",
      ui_lang: "zh", retry_count: 1 },
    { basis: "client", provider: "deepseek", model: "deepseek-chat", visitor_id: null, module: "diet", rounds: 4, calls: 0, tool_count: 6,
      tools: '{"classics.search":5,"study.formula":1}', input_tokens: 9000, output_tokens: 700, execution_status: "done", content_consent: 0, turn_index: 2, runtime: "browser",
      ui_lang: "zh", retry_count: 1 },
    { basis: "client", provider: "fixed", model: null, visitor_id: null, module: "chat", rounds: 0, calls: 0, tool_count: null, tools: null, input_tokens: null,
      output_tokens: null, execution_status: "done", content_consent: null, turn_index: null, runtime: null, ui_lang: null, retry_count: null },
    // the relay's own count of its turn's tokens stands (70 and 40), not the page's
    { basis: "relay", provider: "impf", model: "Tao-R1", visitor_id: visitorOf(5), module: "chat", rounds: 4, calls: 1, tool_count: 6,
      tools: '{"classics.search":5,"study.formula":1}', input_tokens: 70, output_tokens: 40, execution_status: "done", content_consent: 1, turn_index: 2, runtime: "browser",
      ui_lang: "zh", retry_count: 1 }]);
  const s = await ledgerStats(db, { from: "2026-11-25", to: "2026-11-25" });
  assert.deepEqual([s.totals.questions, s.coverage.questions_client, s.coverage.questions_relay, s.totals.model_calls_relay, s.totals.model_calls_reported], [4, 3, 1, 1, 9]);
}));

test("who may tell a turn's end: the page, in the known fields, within its limits — and only where there is a ledger", () => quiet(async () => {
  const r = withLedger();
  const ok = { v: 1, kind: "turn", turn: "m_x", provider: "openai", status: "done", rounds: 1 };
  assert.equal((await r.call("/v1/activity", beaconOf(ok, { Origin: "https://evil.example" }))).status, 403);
  for (const bad of [{ ...ok, v: 2 }, { ...ok, kind: "log" }, { ...ok, turn: "has spaces" }, { ...ok, turn: undefined }, "not json", []]) {
    assert.equal((await r.call("/v1/activity", typeof bad === "string" ? { ...beaconOf({}), body: bad } : beaconOf(bad))).status, 400);
  }
  assert.equal((await r.call("/v1/activity", beaconOf({ ...ok, padding: "x".repeat(5000) }))).status, 413);
  assert.equal((await relay().call("/v1/activity", beaconOf(ok))).status, 404);
  assert.equal((await withLedger({ burst: () => false }).call("/v1/activity", beaconOf(ok))).status, 429);
  await r.settle();
  assert.equal(r.events().filter((e) => e.event_type === "question_submitted").length, 0);
  // the fields as they are kept
  assert.equal(normalizeTurn({ ...ok, v: 2 }), null);
  assert.deepEqual(normalizeTurn({ ...ok, provider: "custom-l8x2", model: "x".repeat(200), status: "weird", rounds: -3, tools: { "a.b": 2.9, "A.B": 1, "c.d": "3" }, input: 1e12,
    module: "secret-module", consent: "yes", lang: "zh-Hant", pass: 7 }),
    { turn: "m_x", pass: "", info: { provider: "custom", model: null, tools: { "a.b": 2 }, input_tokens: 1e9, ui_lang: "zh-Hant" } });
}));

test("a rating and a sponsorship are events of the ledger, without what was written or given", () => quiet(async () => {
  const r = withLedger({ env: { SPONSOR_SECRET: "sponsor-secret-0123456789-0123456789-xyz" } });
  assert.equal((await r.call("/v1/feedback", post({ v: 1, kind: "feedback", id: "m_one", conversation: "c_x", rating: "down", reasons: ["citation"], comment: "引文不对" }))).status, 204);
  assert.equal((await r.call("/v1/sponsor", post({ v: 1, provider: "deepseek", model: "deepseek-chat", key: "sk-0123456789abcdef0123456789abcdef", agree: true }))).status, 204);
  await r.settle();
  const events = r.events();
  assert.deepEqual(events.map((e) => [e.event_type, e.detail || null, e.route, e.visitor_id]), [["feedback_submitted", "down", "/v1/feedback", null], ["sponsor_submitted", null, "/v1/sponsor", null]]);
  const text = JSON.stringify(events);
  for (const kept of ["引文不对", "citation", "sk-0123", "deepseek"]) assert.ok(!text.includes(kept), kept);
}));

test("a request the relay only noted — a path that is not there, a caller that is not the page — is an event too, by what it was", () => quiet(async () => {
  const r = withLedger();
  assert.equal((await r.call("/v1/nothing", { headers: { "User-Agent": "curl/8.5.0", "CF-Connecting-IP": "198.51.100.7" } })).status, 404);
  assert.equal((await r.call("/v1/chat/completions", { method: "POST", headers: { "User-Agent": "curl/8.5.0", "CF-Connecting-IP": "198.51.100.7", Origin: "https://evil.example",
    "Content-Type": "application/json" }, body: JSON.stringify(PAGE_ASK) })).status, 403);
  // (what another site's page made a reader's browser send is refused before any of this, and written nowhere: as before)
  assert.equal((await r.call("/v1/chat/completions", post(PAGE_ASK, { Origin: "https://forum.example", "Sec-Fetch-Site": "cross-site" }))).status, 403);
  await r.settle();
  const events = r.events();
  assert.deepEqual(events.map((e) => [e.event_type, e.route, e.status, e.traffic_class, e.visitor_id, e.n]),
    [["request", "other", 404, "automation", null, 1], ["request", "/v1/chat/completions", 403, "automation", null, 1]]);
}));

test("the ledger does not depend on the sentinel: with the sentinel off a question is still written down, with where it came from", () => quiet(async () => {
  const r = withLedger({ env: { SENTINEL: "off" }, upstream: () => usageStream() });
  await (await r.call("/v1/chat/completions", post(PAGE_ASK, { "X-Tao-Turn": "m_quiet", "X-Tao-Visitor": await passFor(visitorOf(9), ACTIVITY_KEY, T1) }))).text();
  await r.settle();
  const [q] = r.events();
  assert.deepEqual([q.event_type, q.visitor_id, q.country, q.region, q.browser_family, q.traffic_class, q.risk_score], ["question_submitted", visitorOf(9), "CN", "GD", "Chrome", "human", 0]);
  assert.equal(r.watch.summary(T1).visitors, 0); // the sentinel kept nothing
}));
