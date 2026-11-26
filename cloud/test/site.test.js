// The site's Worker under Node: the handler (site.js) with plain objects for its bindings — the site's files, the
// corpus Worker, the bucket and the rate limits.  Run: node --test cloud/test/

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { drain, EVENTS } from "../../security/archive.js";
import { LedgerCore } from "../../security/ledger.js";
import { apply, ensure, rollup } from "../../security/ledger-d1.js";
import { WatchCore } from "../../security/sentinel.js";
import { bucket, d1 } from "../../security/test/fakes.js";
import { UsageCore } from "../../security/usage.js";
import { COOKIE, isVisitor, readPass } from "../../security/visitor.js";
import { DEFAULTS, handle } from "../site/src/site.js";

const TOKEN = "upload-token-for-tests-only";
const TOKEN_SHA = createHash("sha256").update(TOKEN).digest("hex");
const EXPORT = "export-token-0123456789abcdef";
const PAGE = "https://chat.impf.ai";
const T0 = Date.UTC(2026, 9, 5, 8, 0, 0);
const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36";
// the headers a browser sends with the page's own fetch
const BROWSER = { "User-Agent": CHROME, "Accept-Language": "zh-CN,zh;q=0.9", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors",
  "Sec-Fetch-Dest": "empty", "Sec-CH-UA": '"Chromium";v="129"', "CF-Connecting-IP": "203.0.113.9" };

/** The Durable Object SQL API's shape over node:sqlite. */
function sqlStore() {
  const db = new DatabaseSync(":memory:");
  return {
    exec(query, ...params) {
      const stmt = db.prepare(query);
      const rows = /^\s*select|returning/i.test(query) ? stmt.all(...params) : (stmt.run(...params), []);
      return { toArray: () => rows, one: () => { if (rows.length !== 1) throw new Error(`expected one row, got ${rows.length}`); return rows[0]; } };
    },
  };
}

const ACTIVITY_KEY = "activity-key-for-tests-0123456789abcdef";

/** The site with plain objects for its bindings.  watch: true gives it the sentinel's memory; cf: what the edge would
 * say of every request (request.cf); ledger: true gives it the activity ledger — its key, its registry (a D1 in
 * memory) and the object's outbox (`ledger`; `registry()` drains the outbox into the registry and sums its days). */
function site({ corpus = true, store = false, env = {}, limit, watch = false, cf, ledger = false } = {}) {
  const seen = { assets: [], corpus: [], puts: [] };
  const objects = new Map();
  const full = {
    ASSETS: {
      fetch: async (request) => {
        seen.assets.push(request);
        const path = new URL(request.url).pathname;
        if (path.startsWith("/missing")) return new Response("Not Found", { status: 404 });
        const html = path === "/";
        return new Response(html ? "<!doctype html><title>道乃久</title>" : "export {}", {
          headers: { "Content-Type": html ? "text/html; charset=utf-8" : "text/javascript; charset=utf-8", ETag: "\"x\"" },
        });
      },
    },
    ...(corpus ? {
      CORPUS: {
        fetch: async (request) => {
          seen.corpus.push({ url: request.url, method: request.method, headers: Object.fromEntries(request.headers),
                             body: request.method === "POST" ? await request.text() : null });
          return new Response(JSON.stringify({ name: "TaoChronos", corpus: { kind: "full", books: 958 } }), {
            headers: { "Content-Type": "application/json; charset=utf-8", "X-TC-Corpus": "kept", "Set-Cookie": "no=1" },
          });
        },
      },
    } : {}),
    ...(store ? {
      STORE: {
        list: async ({ prefix, limit }) => ({ keys: [...objects.keys()].filter((k) => k.startsWith(prefix)).slice(0, limit)
          .map((name) => ({ name, metadata: objects.get(name).metadata })) }),
        put: async (key, body, options) => {
          const bytes = Buffer.from(await new Response(body).arrayBuffer());
          objects.set(key, { bytes, metadata: options.metadata });
          seen.puts.push({ key, options });
        },
      },
      STORE_TOKEN_SHA256: TOKEN_SHA,
    } : {}),
    ...(ledger ? { ACTIVITY_KEY, ACTIVITY_DB: d1() } : {}),
    ...env,
  };
  const core = watch ? new WatchCore(sqlStore()) : null;
  const book = ledger ? new LedgerCore(sqlStore(), "site") : null;
  const brought = []; // what the instance brought the object, call by call
  const counts = watch ? new UsageCore(sqlStore()) : null;
  const usageCalls = [];
  const pending = [];
  let t = T0; // the clock: advance(ms) moves it
  const held = []; // the counts' moment (site.js: tally) passes when the test settles
  const deps = { limit, now: () => t, defer: (p) => { pending.push(Promise.resolve(p).catch(() => {})); }, local: new Map(),
    batch: () => new Promise((resolve) => held.push(resolve)) };
  if (core) {
    deps.watch = { observe: (fp, a, extra, cfg) => core.observe(fp, a, extra, cfg, t), blocked: (ip, cfg) => core.blocked(ip, cfg, t),
      records: (...a) => core.records(...a), remove: (...a) => core.remove(...a), summary: () => core.summary(t),
      usage: async (c, seen, today) => { usageCalls.push(c); counts.add(c, seen, today); }, stats: async (days, today) => counts.stats(days, today) };
    if (book) {
      deps.watch.activity = async (events, lost = 0) => { brought.push({ events, lost }); for (const e of events) book.note(e, t); book.bump("lost", lost); };
      deps.watch.ledgerHealth = async () => book.health(t);
    }
  }
  const registry = async () => {
    const db = full.ACTIVITY_DB;
    await ensure(db);
    book.flush(t, 0, true);
    await apply(db, book.batch(book.get("applied"), 5000).map((r) => { book.set("applied", r.seq); return r.event; }));
    await rollup(db);
    return db;
  };
  const call = (url, init = {}) => {
    const request = new Request(url, init);
    if (cf) request.cf = cf;
    return handle(request, full, deps);
  };
  const settle = () => { for (const go of held.splice(0)) go(); return Promise.all(pending.splice(0)); }; // what the Worker finishes after the answer (ctx.waitUntil)
  return { call, seen, objects, watch: core, counts, usageCalls, settle, advance: (ms) => { t += ms; }, deps, ledger: book, brought, registry, env: full,
    // (what is not a visitor's is added up by the minute in the object, and written when the minute is over: here, now)
    events: () => { book.flush(t, 0, true); return book.batch(0, 5000).map((r) => r.event); } };
}
const quiet = async (fn) => { const log = console.log; console.log = () => {}; try { return await fn(); } finally { console.log = log; } };

test("http is redirected to https, path and query kept", async () => {
  const { call, seen } = site();
  const res = await call("http://chat.impf.ai/attribution.html?corpus=full");
  assert.equal(res.status, 301);
  assert.equal(res.headers.get("Location"), "https://chat.impf.ai/attribution.html?corpus=full");
  assert.equal(seen.assets.length, 0);
});

test("the site's files are served with the security headers", async () => {
  const { call } = site();
  const page = await call(`${PAGE}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /道乃久/);
  assert.equal(page.headers.get("Strict-Transport-Security"), "max-age=86400");
  assert.equal(page.headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(page.headers.get("X-Frame-Options"), "SAMEORIGIN");
  assert.equal(page.headers.get("ETag"), "\"x\"");
  const script = await call(`${PAGE}/js/app.js`);
  assert.equal(script.headers.get("X-Frame-Options"), null);
  assert.equal(script.headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal((await call(`${PAGE}/`, { method: "POST", body: "x" })).status, 405);
  const off = site({ env: { HSTS_MAX_AGE: "0" } });
  assert.equal((await off.call(`${PAGE}/`)).headers.get("Strict-Transport-Security"), null);
});

test("without the corpus Worker the API says so, and the page runs in the browser", async () => {
  const { call } = site({ corpus: false });
  const res = await call(`${PAGE}/api/info`);
  assert.equal(res.status, 503);
  assert.equal((await res.json()).corpus, "none");
});

test("a corpus Worker that fails is answered with a 503, which the page falls back on", async () => {
  const { call } = site({ env: { CORPUS: { fetch: async () => { throw new Error("internal error; reference = x"); } } } });
  const res = await call(`${PAGE}/api/info`, { headers: { Origin: PAGE } });
  assert.equal(res.status, 503);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), PAGE);
  assert.equal(res.headers.get("Retry-After"), "10");
  assert.equal((await res.json()).starting, true);
});

test("the API's reads and calls reach the corpus with only their path, query and body", async () => {
  const { call, seen } = site();
  const info = await call(`${PAGE}/api/info`, { headers: { Cookie: "secret=1", "CF-Connecting-IP": "203.0.113.9" } });
  assert.equal(info.status, 200);
  assert.equal((await info.json()).corpus.books, 958);
  assert.equal(info.headers.get("X-TC-Corpus"), "kept");
  assert.equal(info.headers.get("Set-Cookie"), null);
  assert.equal(info.headers.get("Cache-Control"), "no-store");
  assert.equal(seen.corpus[0].url, "https://corpus.internal/api/info");
  assert.deepEqual(Object.keys(seen.corpus[0].headers).sort(), ["accept"]);
  await call(`${PAGE}/api/catalog?mode=all`);
  await call(`${PAGE}/api/passage?id=${encodeURIComponent("jc_a000.12")}`);
  await call(`${PAGE}/api/research/job-1a2b`);
  await call(`${PAGE}/api/session/s_42?what=summary`);
  const body = JSON.stringify({ name: "classics.search", arguments: { query: "桂枝汤" } });
  const called = await call(`${PAGE}/api/call`, { method: "POST", body, headers: { "Content-Type": "application/json", Origin: PAGE } });
  assert.equal(called.status, 200);
  assert.equal(called.headers.get("Access-Control-Allow-Origin"), PAGE);
  const last = seen.corpus.at(-1);
  assert.equal(last.method, "POST");
  assert.equal(last.body, body);
  for (const act of ["cancel", "resume"]) { // a research run stopped, or taken up again after the container restarted
    const res = await call(`${PAGE}/api/research/job_0123456789ab/${act}`, { method: "POST", body: "{}", headers: { "Content-Type": "application/json", Origin: PAGE } });
    assert.equal(res.status, 200, act);
  }
  assert.deepEqual(seen.corpus.map((c) => new URL(c.url).pathname + new URL(c.url).search), [
    "/api/info", "/api/catalog?mode=all", "/api/passage?id=jc_a000.12", "/api/research/job-1a2b", "/api/session/s_42?what=summary", "/api/call",
    "/api/research/job_0123456789ab/cancel", "/api/research/job_0123456789ab/resume"]);
});

test("nothing else reaches the corpus: no model proxy, no other endpoint or method", async () => {
  const { call, seen } = site();
  for (const [path, init] of [["/api/llm", { method: "POST", body: "{}" }], ["/api/llm/chat/completions", { method: "POST", body: "{}" }],
    ["/api/providers", {}], ["/api/info", { method: "POST", body: "{}" }], ["/api/call", {}], ["/api/session/a/b", {}],
    ["/api/research/a%2Fb", {}], ["/api", {}], ["/api/research/job_1/cancel", {}], ["/api/research/job_1/delete", { method: "POST", body: "{}" }],
    ["/api/research/a/b/cancel", { method: "POST", body: "{}" }]]) {
    const res = await call(`${PAGE}${path}`, init);
    assert.equal(res.status, 404, path);
  }
  assert.equal(seen.corpus.length, 0);
});

test("a call too large is refused before it reaches the corpus", async () => {
  const { call, seen } = site({ env: { MAX_BODY_BYTES: "100" } });
  const res = await call(`${PAGE}/api/call`, { method: "POST", body: "x".repeat(101), headers: { "Content-Type": "application/json" } });
  assert.equal(res.status, 413);
  assert.equal(seen.corpus.length, 0);
});

test("other sites' pages may not call the API", async () => {
  const { call, seen } = site();
  const res = await call(`${PAGE}/api/call`, { method: "POST", body: "{}", headers: { Origin: "https://evil.example" } });
  assert.equal(res.status, 403);
  assert.equal((await call(`${PAGE}/api/info`, { method: "OPTIONS", headers: { Origin: "https://evil.example" } })).status, 403);
  const pre = await call(`${PAGE}/api/call`, { method: "OPTIONS", headers: { Origin: PAGE } });
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get("Access-Control-Allow-Origin"), PAGE);
  const mirror = site({ env: { ALLOWED_ORIGINS: "https://chat.impf.ai,https://psknlr.github.io" } });
  assert.equal((await mirror.call(`${PAGE}/api/info`, { headers: { Origin: "https://psknlr.github.io" } })).status, 200);
  assert.equal(seen.corpus.length, 0);
});

test("calls are limited per visitor: reads and calls apart", async () => {
  const asked = [];
  const { call, seen } = site({ limit: async (kind, who) => { asked.push([kind, who]); return kind !== "call"; } });
  assert.equal((await call(`${PAGE}/api/info`, { headers: { "CF-Connecting-IP": "203.0.113.5" } })).status, 200);
  const res = await call(`${PAGE}/api/call`, { method: "POST", body: "{}", headers: { "CF-Connecting-IP": "203.0.113.5" } });
  assert.equal(res.status, 429);
  assert.equal(res.headers.get("Retry-After"), "60");
  assert.deepEqual(asked, [["read", "203.0.113.5"], ["call", "203.0.113.5"]]);
  assert.equal(seen.corpus.length, 1);
  const v6 = site({ limit: async (kind, who) => { asked.push([kind, who]); return true; } });
  await v6.call(`${PAGE}/api/info`, { headers: { "CF-Connecting-IP": "2001:db8:1:2:aaaa:bbbb::1" } });
  assert.deepEqual(asked.at(-1), ["read", "2001:db8:1:2::/64"]); // an IPv6 address by its /64
  // the store's upload waits for the rate limit too
  const stored = site({ store: true, limit: async () => false });
  assert.equal((await stored.call(`${PAGE}/api/store/${"a".repeat(64)}/part-000`, { method: "PUT", body: "x", headers: { "Content-Length": "1" } })).status, 429);
});

test("the corpus's own words of a failure stay inside; the page's fallback fields do not", async () => {
  const failing = site({ env: { CORPUS: { fetch: async () => new Response(JSON.stringify({ error: "KeyError: 'passages_v3' at corpus.py:88", starting: true }),
    { status: 503, headers: { "Content-Type": "application/json", "Retry-After": "10" } }) } } });
  const res = await failing.call(`${PAGE}/api/info`);
  assert.equal(res.status, 503);
  const j = await res.json();
  assert.deepEqual(j, { error: "全量语料服务出错了，请稍后再试", starting: true });
  assert.equal(res.headers.get("Retry-After"), "10");
  const plain = site({ env: { CORPUS: { fetch: async () => new Response("Traceback (most recent call last) ...", { status: 500 }) } } });
  assert.deepEqual(await (await plain.call(`${PAGE}/api/info`)).json(), { error: "全量语料服务出错了，请稍后再试" });
});

test("a visitor's day of the API has a ceiling: reads and calls apart, wide, by the /64; a quiet reader's minute is one round trip", () => quiet(async () => {
  const { call, seen, watch, advance } = site({ watch: true, env: { API_READS_PER_DAY: "3", API_CALLS_PER_DAY: "1" } });
  let trips = 0;
  const observe = watch.observe.bind(watch);
  watch.observe = (...a) => { trips++; return observe(...a); };
  for (let i = 0; i < 3; i++) assert.equal((await call(`${PAGE}/api/passage?id=p${i}`, { headers: BROWSER })).status, 200);
  assert.equal(trips, 1); // the first read waited for the object; the next two were counted here
  const over = await call(`${PAGE}/api/passage?id=p3`, { headers: BROWSER });
  assert.equal(over.status, 429); // a refusal, told as one: the page carries on in the browser for the day and says why
  assert.equal(over.headers.get("X-TC-Corpus"), "refused");
  assert.deepEqual(await over.json(), { error: "今天的查询次数已用完，明天再来", rate_limited: true, daily: true, starting: false });
  assert.equal(Number(over.headers.get("Retry-After")), 16 * 3600); // T0 is 08:00 UTC
  const post = { method: "POST", body: "{}", headers: { ...BROWSER, Origin: PAGE, "Content-Type": "application/json" } };
  assert.equal((await call(`${PAGE}/api/call`, post)).status, 200); // calls are counted apart, and always wait for the object
  assert.equal((await call(`${PAGE}/api/call`, post)).status, 429);
  assert.equal(trips, 3);
  advance(61000);
  assert.equal((await call(`${PAGE}/api/passage?id=p9`, { headers: BROWSER })).status, 429); // the object's count agrees: the minute's reads reported with this one
  assert.equal(trips, 4);
  assert.equal(watch.summary(T0 + 61000).top.find((v) => v.today["api-read"]).today["api-read"], 5);
  assert.equal((await call(`${PAGE}/api/passage?id=x`, { headers: { ...BROWSER, "CF-Connecting-IP": "198.51.100.40" } })).status, 200); // another address
  assert.equal(seen.corpus.length, 5);
  const none = site({ watch: true, env: { API_READS_PER_DAY: "0" } });
  for (let i = 0; i < 5; i++) assert.equal((await none.call(`${PAGE}/api/passage?id=p${i}`, { headers: BROWSER })).status, 200);
  // the object out of reach: reads of the public passages go on (the rate-limit bindings stand); a call — work the
  // account pays for — is not let through unchecked: a 503, on which the page carries on in the browser
  const down = site({ watch: true });
  down.watch.observe = async () => { throw new Error("Durable Object: overloaded"); };
  assert.equal((await down.call(`${PAGE}/api/passage?id=p`, { headers: BROWSER })).status, 200);
  const unchecked = await down.call(`${PAGE}/api/call`, post);
  assert.equal(unchecked.status, 503);
  assert.equal(unchecked.headers.get("X-TC-Corpus"), null); // the site's failure, not a refusal
  assert.equal((await down.call(`${PAGE}/api/research`, post)).status, 503);
  assert.equal(down.seen.corpus.length, 1); // only the read reached the corpus
}));

test("research runs started have a day's ceiling of their own, and their ids go into no log", () => quiet(async () => {
  // the corpus runs one research at a time and holds only so many waiting: an address is given so many a day, counted
  // apart from its calls, and told so in words the page shows — the corpus itself goes on answering it
  const { call, seen, watch, settle } = site({ watch: true, env: { API_RESEARCH_PER_DAY: "2", API_CALLS_PER_DAY: "2", LOG_EXPORT_TOKEN: EXPORT } });
  const post = (body = "{}") => ({ method: "POST", body, headers: { ...BROWSER, Origin: PAGE, "Content-Type": "application/json" } });
  for (let i = 0; i < 2; i++) assert.equal((await call(`${PAGE}/api/research`, post('{"question":"消渴"}'))).status, 200);
  const over = await call(`${PAGE}/api/research`, post('{"question":"消渴"}'));
  assert.equal(over.status, 429);
  assert.deepEqual(await over.json(), { error: "今天从这个地址发起的研究已达上限（每天 2 次），明天再来", rate_limited: true, research_daily: true });
  assert.equal(over.headers.get("X-TC-Corpus"), null); // not a refusal of the corpus: the page does not leave it
  assert.equal(Number(over.headers.get("Retry-After")), 16 * 3600);
  assert.equal((await call(`${PAGE}/api/call`, post())).status, 200); // calls are counted apart: the day's two are still there
  const job = "job_0123456789abcdef0123456789abcdef";
  assert.equal((await call(`${PAGE}/api/research/${job}`, { headers: BROWSER })).status, 200); // following a run is a read
  assert.equal((await call(`${PAGE}/api/research/${job}/cancel`, post())).status, 200); // stopping one is a call, not a start
  assert.equal((await (await call(`${PAGE}/api/call`, post())).json()).daily, true); // and now the calls are spent
  assert.equal(seen.corpus.length, 5);
  assert.equal(DEFAULTS.API_RESEARCH_PER_DAY, "100");
  // a run's id is the only key to it: what the sentinel keeps of a request names none (a scanner asking after a run is
  // flagged, its event kept whole — but for the id)
  const script = { "User-Agent": "Mozilla/5.0 (compatible; Nuclei - Open-source project)", "CF-Connecting-IP": "198.51.100.61" };
  await call(`${PAGE}/api/research/${job}`, { headers: script });
  await call(`${PAGE}/api/session/ses_0123456789abcdef0123456789abcdef?what=report`, { headers: script });
  await settle();
  const kept = JSON.stringify([watch.records().items, watch.summary(T0)]);
  assert.ok(kept.includes("/api/research/…") && !kept.includes("0123456789abcdef"), kept);
}));

test("the store is uploaded part by part, only with the token, with the digest it is checked against later", async () => {
  const part = Buffer.from("xz-bytes-of-the-store");
  const sha = createHash("sha256").update(part).digest("hex");
  const key = `store/${"a".repeat(64)}/part-000`;
  const url = `${PAGE}/api/${key}`;
  const put = (headers, body = part) => ({ method: "PUT", body, headers: { "Content-Length": String(body.length), ...headers } });

  const none = site();
  assert.equal((await none.call(url, put({ Authorization: `Bearer ${TOKEN}`, "X-Content-SHA256": sha }))).status, 404);
  const off = site({ store: true, env: { STORE_TOKEN_SHA256: "" } });  // as deployed: no token registered, uploads off
  assert.equal((await off.call(url, put({ Authorization: `Bearer ${TOKEN}`, "X-Content-SHA256": sha }))).status, 404);
  assert.equal((await off.call(url, put({ Authorization: "Bearer ", "X-Content-SHA256": sha }))).status, 404);
  assert.equal(off.objects.size, 0);

  const { call, seen, objects } = site({ store: true });
  assert.equal((await call(url, { method: "HEAD", headers: { Authorization: `Bearer ${TOKEN}` } })).status, 404);
  assert.equal((await call(url, put({ Authorization: "Bearer wrong", "X-Content-SHA256": sha }))).status, 401);
  assert.equal((await call(url, put({ "X-Content-SHA256": sha }))).status, 401);
  assert.equal((await call(url, put({ Authorization: `Bearer ${TOKEN}` }))).status, 400);
  assert.equal((await call(url, put({ Authorization: `Bearer ${TOKEN}`, "X-Content-SHA256": "xyz" }))).status, 400);
  assert.equal(objects.size, 0);
  const ok = await call(url, put({ Authorization: `Bearer ${TOKEN}`, "X-Content-SHA256": sha }));
  assert.equal(ok.status, 201);
  assert.equal((await ok.json()).size, part.length);
  assert.deepEqual(seen.puts[0].options.metadata, { sha256: sha, size: part.length });
  assert.deepEqual(objects.get(key).bytes, part);
  const head = await call(url, { method: "HEAD", headers: { Authorization: `Bearer ${TOKEN}` } });
  assert.equal(head.status, 200);
  assert.equal(head.headers.get("X-Content-SHA256"), sha);
  assert.equal(head.headers.get("X-Content-Length"), String(part.length));
  assert.equal((await call(`${url.slice(0, -1)}1`, { method: "HEAD", headers: { Authorization: `Bearer ${TOKEN}` } })).status, 404);
  const big = site({ store: true, env: { STORE_MAX_PART_BYTES: "10" } });
  assert.equal((await big.call(url, put({ Authorization: `Bearer ${TOKEN}`, "X-Content-SHA256": sha }))).status, 413);
  assert.equal((await call(`${PAGE}/api/store/abc/part-000`, put({ Authorization: `Bearer ${TOKEN}`, "X-Content-SHA256": sha }))).status, 404);
  assert.equal((await call(url, { method: "DELETE", headers: { Authorization: `Bearer ${TOKEN}` } })).status, 405);
  assert.equal(seen.corpus.length, 0);
});

// ------------------------------------------------------------------ the sentinel
test("a scanner path refuses its address the API for a day; the page's own calls leave only a count", () => quiet(async () => {
  const { call, seen, settle, watch, advance } = site({ watch: true, env: { LOG_EXPORT_TOKEN: EXPORT } });
  const probe = await call(`${PAGE}/wp-config.php`, { headers: { "User-Agent": "python-requests/2.31.0", "CF-Connecting-IP": "45.138.12.10" } });
  assert.equal(probe.status, 404);
  assert.equal(seen.assets.length, 0); // never asked of the site's files
  await settle();
  advance(61000); // a minute on: the scanner tries the API
  const refused = await call(`${PAGE}/api/info`, { headers: { "CF-Connecting-IP": "45.138.12.10" } });
  assert.equal(refused.status, 403); // a refusal, told as one (the page carries on in the browser and says why)
  assert.equal((await refused.json()).blocked, true);
  assert.equal(refused.headers.get("X-TC-Corpus"), "refused");
  assert.equal(Number(refused.headers.get("Retry-After")), 21600 - 61); // a home network's address: the ordinary six hours
  assert.equal(seen.corpus.length, 0);
  assert.equal((await call(`${PAGE}/`, { headers: { ...BROWSER, "CF-Connecting-IP": "45.138.12.10" } })).status, 200); // the page itself still answers
  assert.equal((await call(`${PAGE}/api/info`, { headers: BROWSER })).status, 200);
  assert.equal((await call(`${PAGE}/api/call`, { method: "POST", body: "{}", headers: { ...BROWSER, Origin: PAGE, "Content-Type": "application/json" } })).status, 200);
  await settle();
  const auth = { Authorization: `Bearer ${EXPORT}` };
  const { items } = await (await call(`${PAGE}/api/security/export`, { headers: auth })).json();
  assert.deepEqual(items.map((i) => i.event.kind), ["honeypot", "blocked"]);
  assert.deepEqual([items[0].event.fp.ip, items[0].event.fp.path, items[0].event.route], ["45.138.12.10", "/wp-config.php", "honeypot"]);
  const summary = await (await call(`${PAGE}/api/security/summary`, { headers: auth })).json();
  assert.equal(summary.blocked[0].ip, "45.138.12.10");
  const visitor = summary.top.find((v) => !v.ip);
  assert.deepEqual([visitor.n, visitor.score, visitor.flagged], [2, 0, 0]); // the browser's two calls: a count, no address
  assert.equal((await call(`${PAGE}/api/security/export`)).status, 401);
  assert.equal((await call(`${PAGE}/api/security/summary`, { headers: { Authorization: "Bearer not-it-not-it-not-it" } })).status, 401);
  assert.deepEqual(await (await call(`${PAGE}/api/security/ack`, { method: "POST", headers: auth, body: JSON.stringify({ through: items[1].id }) })).json(), { remaining: 0 });
  // a browser's policy report comes with no origin of its own, and is kept
  const csp = await call(`${PAGE}/api/security/csp`, { method: "POST", headers: { "Content-Type": "application/reports+json", Origin: "null", ...BROWSER },
    body: JSON.stringify([{ type: "csp-violation", body: { blockedURL: "https://evil.example/x.js", effectiveDirective: "script-src" } }]) });
  assert.equal(csp.status, 204);
  assert.equal(watch.records().items[0].event.kind, "csp");
  // a file that is not there is noted (a probe, or a stale link); the page by a browser is not
  let trips = 0;
  const observe = watch.observe.bind(watch);
  watch.observe = (...a) => { trips++; return observe(...a); };
  for (const p of ["x.txt", "old-page", "a", "b", "c"]) await call(`${PAGE}/missing/${p}`, { headers: { ...BROWSER } });
  await settle();
  assert.equal(trips, 1); // five misses in a minute: one round trip, the rest held here
  advance(61000);
  await call(`${PAGE}/missing/d`, { headers: { ...BROWSER } });
  await settle();
  assert.equal(trips, 2); // the held misses went with this one, their paths along
  const me = watch.summary(T0 + 61000).top.find((v) => v.n >= 8);
  assert.deepEqual(me.paths, ["/missing/x.txt", "/missing/old-page", "/missing/a", "/missing/b", "/missing/c", "/missing/d"]);
  assert.equal(me.ip, undefined); // files not found: noted, still nobody's address
  // a browser's reports: taken within the rate limit
  const limited = site({ watch: true, limit: async () => false });
  assert.equal((await limited.call(`${PAGE}/api/security/csp`, { method: "POST", headers: BROWSER, body: "{}" })).status, 429);
}));

test("what another site's page makes a reader's browser send: the API refuses it, a miss is not noted, a page is served", () => quiet(async () => {
  const { call, seen, settle, watch, counts } = site({ watch: true, env: { SENTINEL: "enforce" }, cf: { country: "CN", regionCode: "GD", asn: 4134, httpProtocol: "HTTP/2" } });
  // an image on a forum's page, pointed here: the reader's browser asks, and says who made it ask
  const planted = (path, headers = {}, init = {}) => call(`${PAGE}${path}`, { ...init, headers: { ...BROWSER, Accept: "image/avif,image/webp,*/*", "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image", Referer: "https://forum.example/t/42", ...headers } });
  assert.equal((await planted("/backup.sql")).status, 404); // a scanner's path
  for (let i = 0; i < 30; i++) assert.equal((await planted(`/missing/pixel-${i}.png`)).status, 404); // thirty that are not there
  assert.equal((await planted("/api/passage?passage_id=shanghanlun.c013")).status, 403); // a read: the reader's day is not another site's to spend
  assert.equal((await planted("/api/call", { Origin: "https://forum.example", "Content-Type": "text/plain" }, { method: "POST", body: "{}" })).status, 403);
  assert.equal((await planted("/api/security/csp", { Origin: "https://forum.example", "Content-Type": "text/plain" }, { method: "POST",
    body: JSON.stringify({ "csp-report": { "violated-directive": "script-src", "blocked-uri": "https://x.example/a.js" } }) })).status, 403);
  assert.equal((await planted("/", {}, { method: "POST", body: "x" })).status, 405);
  await settle();
  assert.equal(seen.corpus.length, 0);
  const none = watch.summary(T0);
  assert.deepEqual([none.visitors, none.events, none.blocked], [0, 0, []]); // not a row, not an event, not a refusal
  // the reader's own calls afterwards: served, nothing against the address
  assert.equal((await call(`${PAGE}/api/info`, { headers: BROWSER })).status, 200);
  await settle();
  const [reader] = watch.summary(T0).top;
  assert.deepEqual([reader.n, reader.score, reader.flagged, reader.ip], [1, 0, 0, undefined]);
  // a link followed from another site to a page of ours is a visit; the page as that site's frame or image is served
  // (it is public) and is not one
  const link = { ...BROWSER, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", Referer: "https://www.google.com/", "CF-Connecting-IP": "203.0.113.21" };
  assert.equal((await call(`${PAGE}/`, { headers: link })).status, 200);
  assert.equal((await call(`${PAGE}/`, { headers: { ...link, "Sec-Fetch-Dest": "iframe", "CF-Connecting-IP": "203.0.113.22" } })).status, 200);
  assert.equal((await planted("/", { "CF-Connecting-IP": "203.0.113.23" })).status, 200);
  await settle();
  assert.deepEqual(counts.stats(1, "2026-10-05").today, { view: 1, visitor: 1, question: 0, call: 0, asker: 0 });
  // a browser too old to say it is read by where it comes from
  const OLD = "Mozilla/5.0 (Linux; U; Android 9; zh-cn; MI 6 Build/PKQ1) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/66.0.3359.126 MQQBrowser/10.1 Mobile Safari/537.36";
  assert.equal((await call(`${PAGE}/api/info`, { headers: { "User-Agent": OLD, "Accept-Language": "zh-CN", Referer: "https://forum.example/t/42", "CF-Connecting-IP": "203.0.113.31" } })).status, 403);
  assert.equal((await call(`${PAGE}/api/info`, { headers: { "User-Agent": OLD, "Accept-Language": "zh-CN", Referer: `${PAGE}/`, "CF-Connecting-IP": "203.0.113.31" } })).status, 200);
  // a scanner's path asked for in the visitor's own name refuses the address as before
  assert.equal((await call(`${PAGE}/backup.sql`, { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "45.138.12.10" } })).status, 404);
  await settle();
  assert.equal((await call(`${PAGE}/api/info`, { headers: { ...BROWSER, "CF-Connecting-IP": "45.138.12.10" } })).status, 403);
  // without the sentinel the API's refusal stands: a rule of access, not a note
  const bare = site();
  assert.equal((await bare.call(`${PAGE}/api/info`, { headers: { ...BROWSER, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image" } })).status, 403);
  assert.equal(bare.seen.corpus.length, 0);
  assert.equal((await bare.call(`${PAGE}/api/info`, { headers: BROWSER })).status, 200);
}));

test("a scanner path within a quiet reader's minute: the address's next read waits for the object, and is refused", () => quiet(async () => {
  const { call, settle, watch, seen } = site({ watch: true });
  let trips = 0;
  const observe = watch.observe.bind(watch);
  watch.observe = (...a) => { trips++; return observe(...a); };
  const spoofed = { ...BROWSER, "CF-Connecting-IP": "45.138.12.11" }; // a browser's headers: a quiet reader's score
  assert.equal((await call(`${PAGE}/api/passage?id=a`, { headers: spoofed })).status, 200);
  assert.equal((await call(`${PAGE}/api/passage?id=b`, { headers: spoofed })).status, 200);
  assert.equal(trips, 1); // the second read was answered from this instance's memory
  assert.equal((await call(`${PAGE}/.env`, { headers: spoofed })).status, 404);
  await settle();
  const refused = await call(`${PAGE}/api/passage?id=c`, { headers: spoofed }); // within the same minute
  assert.equal(refused.status, 403);
  assert.equal(trips, 3); // the scanner path, then the read: not answered from memory
  assert.equal(seen.corpus.length, 2);
}));

test("with the archive's bucket the sentinel's events go there: the export says so, an ack is refused, a day is read back", () => quiet(async () => {
  const objects = new Map();
  const ARCHIVE = {
    put: async (key, body) => { objects.set(key, body); return { key }; },
    get: async (key) => (objects.has(key) ? { text: async () => objects.get(key) } : null),
    list: async ({ prefix }) => ({ objects: [...objects.keys()].filter((k) => k.startsWith(prefix)).sort().map((key) => ({ key })), truncated: false }),
  };
  const { call, settle, watch } = site({ watch: true, env: { ARCHIVE, LOG_EXPORT_TOKEN: EXPORT } });
  assert.equal((await call(`${PAGE}/xmlrpc.php`, { headers: { "CF-Connecting-IP": "45.138.12.12" } })).status, 404);
  await settle();
  const auth = { Authorization: `Bearer ${EXPORT}` };
  assert.equal((await (await call(`${PAGE}/api/security/export`, { headers: auth })).json()).archive, "r2");
  assert.equal((await call(`${PAGE}/api/security/ack`, { method: "POST", headers: auth, body: JSON.stringify({ through: 1 }) })).status, 409);
  await drain(watch, ARCHIVE, { prefix: EVENTS("site"), field: "event", extra: { source: "site" } }); // the Watch object's alarm (cloud/site/src/index.js)
  const day = await (await call(`${PAGE}/api/security/archive?day=2026-10-05`, { headers: auth })).json();
  assert.deepEqual(day.items.map((e) => [e.source, e.kind, e.fp.path]), [["site", "honeypot", "/xmlrpc.php"]]);
  assert.equal((await call(`${PAGE}/api/security/archive?day=2026-10-05`)).status, 401);
}));

test("an API call that is not the page's is scored: served and flagged in observe mode, refused over the block score in enforce mode", () => quiet(async () => {
  const script = { "User-Agent": "python-requests/2.31.0", "CF-Connecting-IP": "198.51.100.77" };
  const observe = site({ watch: true, cf: { asn: 14061, country: "US" } });
  assert.equal((await observe.call(`${PAGE}/api/passage?id=jc_a000.12`, { headers: script })).status, 200);
  const [flag] = observe.watch.records().items;
  assert.deepEqual([flag.event.kind, flag.event.route, flag.event.reasons, flag.event.fp.ip], ["flag", "api-read", ["ua_tool", "dc_asn"], "198.51.100.77"]);
  const scanner = { "User-Agent": "Mozilla/5.0 (compatible; Nuclei - Open-source project (github.com/projectdiscovery/nuclei))", Referer: "https://evil.example/",
    "CF-Connecting-IP": "198.51.100.78" };
  assert.equal((await observe.call(`${PAGE}/api/info`, { headers: scanner })).status, 200); // observe: served, a shadow of a refusal
  assert.equal(observe.watch.records().items[1].event.kind, "shadow");
  const enforce = site({ watch: true, env: { SENTINEL: "enforce" }, cf: { asn: 14061, country: "US" } });
  assert.equal((await enforce.call(`${PAGE}/api/passage?id=x`, { headers: script })).status, 200); // flagged, under the block score
  const refused = await enforce.call(`${PAGE}/api/info`, { headers: scanner });
  assert.equal(refused.status, 403);
  assert.equal(enforce.seen.corpus.length, 1);
  assert.equal((await enforce.call(`${PAGE}/api/info`, { headers: BROWSER })).status, 200);
  // the deploy check's agent string is a label, not a pass: on a scanner path it is refused like anyone; off a scanner
  // path its calls stay under the block score.  The site without the binding, or off, records nothing
  const own = site({ watch: true, env: { SENTINEL: "enforce" } });
  assert.equal((await own.call(`${PAGE}/api/info`, { headers: { "User-Agent": "taochronos-deploy/1", "CF-Connecting-IP": "198.51.100.79" } })).status, 200);
  assert.equal((await own.call(`${PAGE}/.git/config`, { headers: { "User-Agent": "taochronos-deploy/1", "CF-Connecting-IP": "198.51.100.79" } })).status, 404);
  await own.settle();
  own.advance(61000);
  assert.equal((await own.call(`${PAGE}/api/info`, { headers: { "User-Agent": "taochronos-deploy/1", "CF-Connecting-IP": "198.51.100.79" } })).status, 403);
  assert.equal(own.watch.records().items[0].event.own, true);
  const off = site({ watch: true, env: { SENTINEL: "off", LOG_EXPORT_TOKEN: EXPORT } });
  assert.equal((await off.call(`${PAGE}/wp-login.php`, { headers: { "CF-Connecting-IP": "45.138.12.10" } })).status, 200); // asked of the files as any path
  assert.equal((await off.call(`${PAGE}/api/security/summary`, { headers: { Authorization: `Bearer ${EXPORT}` } })).status, 404);
  assert.equal((await off.call(`${PAGE}/api/security/csp`, { method: "POST", body: "{}" })).status, 204); // a browser's report is taken, and dropped
  assert.deepEqual(off.watch.records().items, []);
  const plain = site();
  assert.equal((await plain.call(`${PAGE}/api/security/summary`, { headers: { Authorization: `Bearer ${EXPORT}` } })).status, 404);
}));

test("the pages' headers: no device features; the policy enforced, the one reported, and where to report them", async () => {
  const { call } = site({ env: { CSP: "script-src 'self'; report-to csp", CSP_REPORT_ONLY: "default-src 'self'; report-to csp" } });
  const page = await call(`${PAGE}/`);
  const script = await call(`${PAGE}/js/app.js`);
  assert.equal(page.headers.get("Permissions-Policy"), DEFAULTS.PERMISSIONS_POLICY);
  assert.equal(page.headers.get("Content-Security-Policy"), "script-src 'self'; report-to csp");
  assert.equal(page.headers.get("Content-Security-Policy-Report-Only"), "default-src 'self'; report-to csp");
  assert.equal(page.headers.get("Reporting-Endpoints"), 'csp="https://chat.impf.ai/api/security/csp"');
  assert.equal(page.headers.get("X-Frame-Options"), "SAMEORIGIN");
  assert.equal(page.headers.get("Cross-Origin-Opener-Policy"), "same-origin");
  assert.equal(page.headers.get("Cross-Origin-Resource-Policy"), "same-origin");
  assert.equal(script.headers.get("Cross-Origin-Opener-Policy"), null);
  assert.equal(script.headers.get("Content-Security-Policy"), null);
  assert.equal(script.headers.get("Content-Security-Policy-Report-Only"), null);
  assert.equal(script.headers.get("Permissions-Policy"), DEFAULTS.PERMISSIONS_POLICY);
  const uri = site({ env: { CSP_REPORT_ONLY: "default-src 'self'; report-uri /api/security/csp" } });
  assert.equal((await uri.call(`${PAGE}/`)).headers.get("Reporting-Endpoints"), null);
  const enforcedOnly = site({ env: { CSP: "script-src 'self'; report-to csp" } });
  const alone = await enforcedOnly.call(`${PAGE}/`);
  assert.equal(alone.headers.get("Content-Security-Policy-Report-Only"), null);
  assert.equal(alone.headers.get("Reporting-Endpoints"), 'csp="https://chat.impf.ai/api/security/csp"'); // the enforced policy's reports go there too
  const none = site();
  assert.equal((await none.call(`${PAGE}/`)).headers.get("Content-Security-Policy"), null);
  assert.equal((await none.call(`${PAGE}/`)).headers.get("Content-Security-Policy-Report-Only"), null);
  assert.equal((await none.call(`${PAGE}/`)).headers.get("Reporting-Endpoints"), null);
});

test("the policies deployed name the pages' inline scripts and styles by their hashes, as web/ has them", () => {
  const toml = readFileSync(new URL("../site/wrangler.toml", import.meta.url), "utf-8");
  const policy = /^CSP_REPORT_ONLY = "(.*)"$/m.exec(toml)[1];
  const enforced = /^CSP = "(.*)"$/m.exec(toml)[1];
  const hash = (text) => `'sha256-${createHash("sha256").update(text).digest("base64")}'`;
  const inline = { scripts: [], styles: [], attrs: [] };
  for (const file of ["index.html", "about.html", "attribution.html"]) {
    const html = readFileSync(new URL(`../../web/${file}`, import.meta.url), "utf-8");
    for (const m of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) if (!/ld\+json|src=/.test(m[1])) inline.scripts.push(hash(m[2]));
    for (const m of html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) inline.styles.push(hash(m[1]));
    for (const m of html.matchAll(/ style="([^"]*)"/g)) inline.attrs.push(hash(m[1]));
  }
  assert.deepEqual([inline.scripts.length, inline.styles.length, inline.attrs.length], [1, 2, 1]); // an inline block added to a page needs its hash in the policy
  const directive = (name, of = policy) => (new RegExp(`(?:^|; )${name} ([^;]*)`).exec(of) || [])[1] || "";
  for (const h of inline.scripts) assert.ok(directive("script-src").includes(h), `script-src lacks ${h}`);
  // the enforced policy: the same scripts (a page whose inline script lost its hash would not start), and what keeps
  // out a script that is not the page's and where one could send what it read
  assert.equal(directive("script-src", enforced), directive("script-src"));
  assert.deepEqual(["object-src", "base-uri", "form-action", "frame-ancestors", "worker-src", "img-src", "connect-src"].map((d) => directive(d, enforced)),
    ["'none'", "'none'", "'self'", "'self'", "'self'", "'self' data: blob:", "'self' https: http://localhost:* http://127.0.0.1:*"]);
  assert.doesNotMatch(enforced, /default-src|style-src|font-src|media-src|frame-src/); // reported only: extensions add their own (wrangler.toml)
  assert.match(enforced, /report-uri \/api\/security\/csp; report-to csp$/);
  assert.doesNotMatch(enforced, /unsafe-inline|unsafe-eval|unsafe-hashes/); // (and so no wasm-unsafe-eval: the page compiles none)
  // jsDelivr's npm files only (the SDK and what its +esm imports), not its /gh/ files: any public repository's
  assert.ok(directive("script-src").split(" ").includes("https://cdn.jsdelivr.net/npm/"), "script-src names jsDelivr's npm path");
  assert.doesNotMatch(directive("script-src"), /https:\/\/cdn\.jsdelivr\.net(?:\s|$)/);
  for (const h of inline.styles) assert.ok(directive("style-src").includes(h), `style-src lacks ${h}`);
  for (const h of inline.attrs) assert.ok(directive("style-src-attr").includes(h), `style-src-attr lacks ${h}`);
  // the edge adds Cloudflare Web Analytics' beacon to every page: without it, each visit would file a report
  assert.ok(directive("script-src").split(" ").includes("https://static.cloudflareinsights.com"), "script-src lacks the analytics beacon");
  assert.match(policy, /report-to csp$/);
  assert.doesNotMatch(policy, /unsafe-inline|unsafe-eval/);
  const headers = readFileSync(new URL("../site/_headers", import.meta.url), "utf-8");
  assert.match(headers, /^\/js\/worker\.js\n  Content-Security-Policy-Report-Only: .*wasm-unsafe-eval.*report-uri \/api\/security\/csp$/m);
  assert.match(headers, /^\/js\/unpack-worker\.js\n  Content-Security-Policy-Report-Only: .*connect-src 'self' data:/m);
  assert.doesNotMatch(headers, /Content-Security-Policy-Report-Only:.*report-to/); // a worker's response may not have its Reporting-Endpoints processed: report-uri alone
});

// ------------------------------------------------------------------ the counts for the settings' 统计 pane
const STATS = "stats-token-0123456789abcdef";
const visit = (call, ip, { ua = CHROME, path = "/", method = "GET" } = {}) =>
  call(`${PAGE}${path}`, { method, headers: { "User-Agent": ua, "Accept-Language": "zh-CN", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
    "CF-Connecting-IP": ip } });

test("a page a browser opens is counted by day and place, its visitor once a day, after the answer and in one batch", async () => {
  const { call, counts, usageCalls, settle, advance } = site({ watch: true, cf: { country: "CN", regionCode: "GD", asn: 4134 } });
  for (const ip of ["203.0.113.1", "203.0.113.1", "203.0.113.2"]) assert.equal((await visit(call, ip)).status, 200);
  assert.equal((await visit(call, "203.0.113.3", { path: "/about" })).status, 200);
  await visit(call, "203.0.113.4", { ua: "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" }); // a crawler
  await visit(call, "203.0.113.5", { ua: "python-requests/2.32" }); // a script
  await visit(call, "203.0.113.6", { method: "HEAD" });
  await visit(call, "203.0.113.7", { path: "/missing-page" }); // not there
  assert.equal(usageCalls.length, 0); // nothing yet: the visitor never waits for it
  await settle();
  assert.equal(usageCalls.length, 1); // the moment's pages, together
  const s = counts.stats(1, "2026-10-05");
  assert.deepEqual(s.today, { view: 4, visitor: 3, question: 0, call: 0, asker: 0 });
  assert.deepEqual(s.places, [{ country: "CN", region: "GD", view: 4, visitor: 3, question: 0, call: 0, asker: 0 }]);
  advance(3600000);
  await visit(call, "203.0.113.1");
  await settle();
  assert.deepEqual(counts.stats(1, "2026-10-05").today, { view: 5, visitor: 3, question: 0, call: 0, asker: 0 }); // the same visitor, the same day
});

test("the counts are read with the stats token; without the sentinel's object there are none", async () => {
  const { call } = site({ watch: true, env: { STATS_TOKEN: STATS }, cf: { country: "CN", regionCode: "SH" } });
  await visit(call, "203.0.113.9");
  assert.equal((await call(`${PAGE}/api/stats?days=7`)).status, 401);
  const ok = await call(`${PAGE}/api/stats?days=7`, { headers: { Authorization: `Bearer ${STATS}` } });
  assert.equal(ok.status, 200);
  const body = await ok.json();
  assert.equal(body.days.length, 7);
  assert.equal(body.offset, 8);
  assert.equal(ok.headers.get("Cache-Control"), "no-store");
  const foreign = await call(`${PAGE}/api/stats`, { headers: { Authorization: `Bearer ${STATS}`, Origin: "https://evil.example" } });
  assert.equal(foreign.status, 403);
  const bare = site({ env: { STATS_PUBLIC: "1" } });
  assert.equal((await bare.call(`${PAGE}/api/stats`)).status, 404);
});

// ------------------------------------------------------------------ the activity ledger (security/ledger.js)
const NAV = { "User-Agent": CHROME, Accept: "text/html,application/xhtml+xml", "Accept-Language": "zh-CN,zh;q=0.9", "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Dest": "document", "Sec-CH-UA": '"Chromium";v="129"', "CF-Connecting-IP": "203.0.113.9" };
const CF = { country: "CN", regionCode: "GD", asn: 4134, httpProtocol: "HTTP/2", tlsVersion: "TLSv1.3" };
const open = (call, headers = {}, path = "/") => call(`${PAGE}${path}`, { headers: { ...NAV, ...headers } });
const cookieOf = (res) => (res.headers.get("Set-Cookie") || "").split(";")[0];
const post = (call, path, body, headers = {}) => call(`${PAGE}${path}`, { method: "POST", headers: { ...BROWSER, Origin: PAGE, "Content-Type": "application/json", ...headers },
  body: JSON.stringify(body) });

test("without the ledger's key the site is what it was: no cookie, nothing written, no endpoint", async () => {
  const { call, settle, deps } = site({ watch: true, cf: CF });
  const res = await open(call);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("Set-Cookie"), null);
  await settle();
  assert.equal(deps.ledger, undefined);
  assert.deepEqual(await (await post(call, "/api/activity/hello", {})).json(), { error: "这里没有活动账本", ledger: false });
  // nor with the key and no registry, or with the ledger switched off
  for (const env of [{ ACTIVITY_KEY }, { ACTIVITY_KEY, ACTIVITY_DB: d1(), ACTIVITY: "off" }]) {
    const half = site({ watch: true, cf: CF, env });
    assert.equal((await open(half.call)).headers.get("Set-Cookie"), null);
    assert.equal((await half.call(`${PAGE}/api/activity/stats`)).status, 404);
  }
});

test("a page a browser opens is written down for a visitor: an id it is given, and is known by when it comes back", async () => {
  const { call, settle, events, advance, env } = site({ watch: true, ledger: true, cf: CF });
  const first = await open(call, { Referer: "https://www.baidu.com/s?wd=%E6%A1%82%E6%9E%9D%E6%B1%A4" });
  assert.equal(first.status, 200);
  assert.match(first.headers.get("Set-Cookie"), /^__Host-tcv=[A-Za-z0-9_-]{22}\.[0-9a-z]+\.[A-Za-z0-9_-]{22}; Path=\/; Max-Age=33696000; Secure; HttpOnly; SameSite=Lax$/);
  assert.match(await first.text(), /道乃久/); // the page itself, as before
  assert.ok(first.headers.get("Content-Security-Policy") !== undefined && first.headers.get("X-Frame-Options") === "SAMEORIGIN");
  const cookie = cookieOf(first);
  advance(60000);
  const again = await open(call, { Cookie: cookie }, "/about");
  assert.equal(again.headers.get("Set-Cookie"), null); // it has one
  // a page the browser holds and asks about is a page opened too
  env.ASSETS = { fetch: async () => new Response(null, { status: 304, headers: { ETag: "\"x\"" } }) };
  advance(60000);
  assert.equal((await open(call, { Cookie: cookie, "If-None-Match": "\"x\"" })).status, 304);
  await settle();
  const seen = events();
  assert.deepEqual(seen.map((e) => [e.event_type, e.route, e.status, e.traffic_class, e.security_action, e.new_visitor === true, e.referrer || null]),
    [["page_view", "/", 200, "human", "none", true, "https://www.baidu.com"], ["page_view", "/about", 200, "human", "none", false, null], ["page_view", "/", 304, "human", "none", false, null]]);
  assert.ok(isVisitor(seen[0].visitor_id));
  assert.deepEqual(new Set(seen.map((e) => e.visitor_id)).size, 1);
  assert.deepEqual([seen[0].browser_family, seen[0].os_family, seen[0].device_type, seen[0].language, seen[0].country, seen[0].region, seen[0].asn, seen[0].http_protocol],
    ["Chrome", "Windows", "desktop", "zh-CN", "CN", "GD", 4134, "HTTP/2"]);
  const text = JSON.stringify(seen);
  for (const kept of ["203.0.113", "Mozilla", "wd=", cookie.slice(11, 33)]) assert.ok(!text.includes(kept), kept); // no address, no agent, no query, not the cookie
});

test("who is given no id: what is not a browser, a browser that asks not to be tracked, one whose user switched the count off", async () => {
  const { call, settle, events } = site({ watch: true, ledger: true, cf: CF });
  const curl = await quiet(() => call(`${PAGE}/`, { headers: { "User-Agent": "curl/8.5.0", "CF-Connecting-IP": "203.0.113.20" } }));
  assert.equal(curl.headers.get("Set-Cookie"), null);
  assert.equal((await open(call, { "Sec-GPC": "1" })).headers.get("Set-Cookie"), null);
  assert.equal((await open(call, { DNT: "1" })).headers.get("Set-Cookie"), null);
  assert.equal((await open(call, { Cookie: `${COOKIE}=off` })).headers.get("Set-Cookie"), null);
  assert.equal((await call(`${PAGE}/`, { method: "HEAD", headers: NAV })).headers.get("Set-Cookie"), null);
  // another site's page loading ours as its image: served, and no visit of anyone's
  await quiet(() => call(`${PAGE}/`, { headers: { ...NAV, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image", Referer: "https://forum.example/t/1" } }));
  // a forged cookie is not counted for the visitor it names: a new one is made
  const forged = await open(call, { Cookie: `${COOKIE}=${"A".repeat(22)}.abc.${"B".repeat(22)}` });
  assert.match(forged.headers.get("Set-Cookie"), /^__Host-tcv=/);
  await settle();
  const seen = events();
  assert.deepEqual(seen.map((e) => [e.event_type, e.traffic_class, e.visitor_id === null]), [["page_view", "human", true], ["page_view", "human", true],
    ["page_view", "human", true], ["request", "human", true], ["page_view", "human", false], ["request", "automation", true], ["request", "cross_site", true]]);
  assert.deepEqual([seen[6].security_action, seen[6].country, seen[6].asn, seen[6].browser_family], ["cross_site", "CN", undefined, undefined]);
});

test("optin: an id only once the visitor switched the count on; off: none at all, and everything is still counted", async () => {
  const optin = site({ watch: true, ledger: true, cf: CF, env: { ACTIVITY_IDS: "optin" } });
  assert.equal((await open(optin.call)).headers.get("Set-Cookie"), null);
  const told = await post(optin.call, "/api/activity/hello", { lang: "zh" });
  assert.deepEqual(await told.json(), { v: 1, ledger: true, ids: "optin", state: "none", visitor: null, pass: null, expires: null });
  const on = await post(optin.call, "/api/activity/choice", { ids: "on" });
  const cookie = cookieOf(on);
  assert.match(cookie, /^__Host-tcv=[A-Za-z0-9_-]{22}\./);
  const body = await on.json();
  assert.deepEqual([body.state, isVisitor(body.visitor), await readPass(body.pass, ACTIVITY_KEY, T0)], ["valid", true, body.visitor]);
  assert.equal((await open(optin.call, { Cookie: cookie })).headers.get("Set-Cookie"), null);
  await optin.settle();
  assert.deepEqual(optin.events().map((e) => [e.event_type, e.visitor_id !== null, e.detail || null]),
    [["page_view", false, null], ["page_ready", false, "zh"], ["visitor_choice", false, "on"], ["page_view", true, null]]);
  const off = site({ watch: true, ledger: true, cf: CF, env: { ACTIVITY_IDS: "off" } });
  assert.equal((await open(off.call)).headers.get("Set-Cookie"), null);
  assert.equal((await (await post(off.call, "/api/activity/choice", { ids: "on" })).json()).state, "disabled");
  await off.settle();
  assert.deepEqual(off.events().map((e) => [e.event_type, e.visitor_id]), [["page_view", null], ["visitor_choice", null]]);
});

test("the page, once loaded, is told who its visitor is: an id to show them and a pass for the relay", async () => {
  const { call, settle, events } = site({ watch: true, ledger: true, cf: CF });
  const cookie = cookieOf(await open(call));
  const res = await post(call, "/api/activity/hello", { lang: "en", more: "ignored" }, { Cookie: cookie });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("Set-Cookie"), null);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  const told = await res.json();
  assert.deepEqual([told.ledger, told.ids, told.state, told.expires], [true, "notice", "valid", T0 + 86400000]);
  assert.equal(await readPass(told.pass, ACTIVITY_KEY, T0), told.visitor);
  assert.ok(!told.pass.includes(cookie.slice(11, 33)));
  // without a cookie (the mirror's page asking, a browser that keeps none): no id, no pass
  assert.deepEqual(await (await post(call, "/api/activity/hello", {})).json(), { v: 1, ledger: true, ids: "notice", state: "none", visitor: null, pass: null, expires: null });
  assert.equal((await (await post(call, "/api/activity/hello", {}, { Cookie: cookie, "Sec-GPC": "1" })).json()).state, "declined");
  // only the site's own pages, from a browser
  assert.equal((await quiet(() => post(call, "/api/activity/hello", {}, { "User-Agent": "curl/8.5.0" }))).status, 403);
  assert.equal((await quiet(() => post(call, "/api/activity/hello", {}, { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }))).status, 403);
  assert.equal((await call(`${PAGE}/api/activity/hello`, { headers: BROWSER })).status, 405);
  assert.equal((await post(call, "/api/activity/hello", "x".repeat(2000), { Cookie: cookie })).status, 413);
  assert.equal((await post(call, "/api/activity/nothing", {})).status, 404);
  await settle();
  const ready = events().filter((e) => e.event_type === "page_ready");
  assert.deepEqual(ready.map((e) => [e.visitor_id, e.detail || null]), [[told.visitor, "en"], [null, null], [null, null]]);
});

test("the visitor's own switches: the count off, on again, and everything held of them forgotten", async () => {
  const { call, settle, registry, events } = site({ watch: true, ledger: true, cf: CF });
  const cookie = cookieOf(await open(call));
  const hello = await (await post(call, "/api/activity/hello", {}, { Cookie: cookie })).json();
  await settle();
  const db = await registry();
  assert.deepEqual(db.rows("SELECT visitor_id, confirmed FROM visitors"), [{ visitor_id: hello.visitor, confirmed: 1 }]);
  const me = await (await call(`${PAGE}/api/activity/me`, { headers: { ...BROWSER, Cookie: cookie } })).json();
  assert.deepEqual(me, { v: 1, ids: "notice", state: "valid", visitor: hello.visitor, held: { first_day: "2026-10-05", last_day: "2026-10-05", days: 1, page_views: 1, questions: 0 } });
  // off: the cookie says so and nothing more; a page opened after it makes no new id
  const off = await post(call, "/api/activity/choice", { ids: "off" }, { Cookie: cookie });
  assert.equal(off.headers.get("Set-Cookie"), "__Host-tcv=off; Path=/; Max-Age=33696000; Secure; HttpOnly; SameSite=Lax");
  assert.deepEqual(await off.json(), { v: 1, ledger: true, ids: "notice", state: "off", visitor: null, pass: null, expires: null });
  assert.equal((await open(call, { Cookie: "__Host-tcv=off" })).headers.get("Set-Cookie"), null);
  assert.equal((await (await post(call, "/api/activity/hello", {}, { Cookie: "__Host-tcv=off" })).json()).state, "off");
  // on again: a new id (the old one is not taken up again)
  const on = await post(call, "/api/activity/choice", { ids: "on" }, { Cookie: "__Host-tcv=off" });
  const next = await on.json();
  assert.ok(isVisitor(next.visitor) && next.visitor !== hello.visitor);
  assert.match(on.headers.get("Set-Cookie"), /^__Host-tcv=[A-Za-z0-9_-]{22}\./);
  assert.equal((await post(call, "/api/activity/choice", { ids: "perhaps" })).status, 404);
  // forgotten: the first visitor's rows go, and the cookie is "off"
  const gone = await post(call, "/api/activity/forget", {}, { Cookie: cookie });
  assert.deepEqual(await gone.json(), { v: 1, ledger: true, ids: "notice", state: "off", visitor: null, pass: null, expires: null, forgotten: true });
  assert.match(gone.headers.get("Set-Cookie"), /^__Host-tcv=off;/);
  assert.deepEqual(db.rows("SELECT COUNT(*) AS n FROM visitors WHERE visitor_id = ?", hello.visitor), [{ n: 0 }]);
  assert.deepEqual(db.rows("SELECT what, by FROM deletion_log"), [{ what: "visitor", by: "self" }]);
  assert.equal((await (await post(call, "/api/activity/forget", {})).json()).forgotten, false); // no one to forget
  await settle();
  assert.deepEqual(events().filter((e) => e.event_type === "visitor_choice").map((e) => [e.detail, e.visitor_id]), [["off", null], ["on", null], ["forget", null], ["forget", null]]);
});

test("the API is written down whatever its score: a reader's reads of a minute one line, a call its own, a refusal with its status", async () => {
  const { call, settle, events, advance } = site({ watch: true, ledger: true, cf: CF, env: { API_READS_PER_DAY: "4" } });
  const cookie = cookieOf(await open(call));
  const api = (path, init = {}) => call(`${PAGE}${path}`, { ...init, headers: { ...BROWSER, Cookie: cookie, ...(init.headers || {}) } });
  for (let i = 0; i < 3; i++) assert.equal((await api(`/api/passage?id=p${i}`)).status, 200);
  assert.equal((await api("/api/call", { method: "POST", headers: { "Content-Type": "application/json", Origin: PAGE }, body: '{"name":"classics.search"}' })).status, 200);
  assert.equal((await api("/api/research", { method: "POST", headers: { "Content-Type": "application/json", Origin: PAGE }, body: "{}" })).status, 200);
  assert.equal((await api("/api/research/job_secret-id-0123456789")).status, 200);
  advance(61000); // the day's reads spent, as the object says at the next round trip
  assert.equal((await api("/api/passage?id=p9")).status, 429);
  assert.equal((await quiet(() => api("/api/nothing"))).status, 404);
  // another site's page making the reader's browser ask: refused, counted for no one
  assert.equal((await quiet(() => api("/api/passage?id=p1", { headers: { "Sec-Fetch-Site": "cross-site", Origin: "https://forum.example" } }))).status, 403);
  await settle();
  const seen = events().filter((e) => e.event_type !== "page_view");
  assert.deepEqual(seen.map((e) => [e.event_type, e.route, e.status, e.n, e.security_action, e.visitor_id !== null]), [
    ["api_call", "/api/call", 200, 1, "none", true], ["research_started", "/api/research", 200, 1, "none", true], ["request", "other", 404, 1, "none", false],
    ["api_read", "/api/passage", 200, 3, "none", true], ["api_read", "/api/research/…", 200, 1, "none", true], ["api_read", "/api/passage", 429, 1, "rate_limited", true],
    ["request", "other", 403, 1, "cross_site", false]]);
  assert.ok(!JSON.stringify(seen).includes("secret-id")); // a research run's id is the only key to it
  assert.ok(seen.every((e) => e.latency_ms >= 0));
});

test("the ledger's counts are read with the stats token; its pipeline and its archive with the collector's", async () => {
  const { call, settle, registry, advance } = site({ watch: true, ledger: true, cf: CF, env: { STATS_TOKEN: STATS, LOG_EXPORT_TOKEN: EXPORT } });
  const a = cookieOf(await open(call));
  await post(call, "/api/activity/hello", {}, { Cookie: a });
  advance(40 * 60000);
  await open(call, { Cookie: a }); // forty minutes on: a second visit
  const b = cookieOf(await open(call, { "CF-Connecting-IP": "203.0.113.10" }));
  await post(call, "/api/activity/hello", {}, { Cookie: b, "CF-Connecting-IP": "203.0.113.10" });
  await open(call, { "CF-Connecting-IP": "203.0.113.11", "Sec-GPC": "1" });
  await settle();
  await registry();
  assert.equal((await call(`${PAGE}/api/activity/stats?range=all`)).status, 401);
  const res = await call(`${PAGE}/api/activity/stats?range=all`, { headers: { Authorization: `Bearer ${STATS}` } });
  assert.equal(res.status, 200);
  const s = await res.json();
  assert.deepEqual([s.from, s.to, s.totals.visitors, s.totals.visits, s.totals.page_views, s.coverage.page_views_identified, s.coverage.page_ready], ["2026-10-05", "2026-10-05", 2, 3, 4, 3, 2]);
  assert.deepEqual(s.places, [{ country: "CN", region: "GD", visitors: 2, page_views: 4, questions: 0 }]);
  assert.deepEqual(s.sessions.lengths.find(([k]) => k === "0-10s"), ["0-10s", 3]);
  // the pipeline, for the owner
  assert.equal((await call(`${PAGE}/api/activity/health`, { headers: { Authorization: `Bearer ${STATS}` } })).status, 401);
  const health = await (await call(`${PAGE}/api/activity/health`, { headers: { Authorization: `Bearer ${EXPORT}` } })).json();
  assert.deepEqual([health.site.source, health.site.appended, health.site.dropped, health.site.lost, health.archive, health.ids, health.registry.visitors, health.registry.first_day],
    ["site", 6, 0, 0, false, "notice", 2, "2026-10-05"]);
  assert.equal((await call(`${PAGE}/api/activity/archive?day=2026-10-05`, { headers: { Authorization: `Bearer ${EXPORT}` } })).status, 404); // no bucket
  // with the archive's bucket: a day of both Workers' archives against their manifests
  const archived = site({ watch: true, ledger: true, cf: CF, env: { LOG_EXPORT_TOKEN: EXPORT, ARCHIVE: bucket() } });
  const check = (q, token = EXPORT) => archived.call(`${PAGE}/api/activity/archive${q}`, { headers: { Authorization: `Bearer ${token}` } });
  assert.equal((await check("?day=2026-10-05", "not-the-token-0123456789")).status, 401);
  assert.equal((await check("?day=yesterday")).status, 400);
  const day = await (await check("?day=2026-10-05")).json();
  assert.deepEqual([day.day, Object.keys(day.sources), day.sources.site.ok, day.sources.relay.objects], ["2026-10-05", ["site", "relay"], null, 0]); // nothing written that day
  assert.deepEqual(Object.keys((await (await check("?day=2026-10-05&source=relay")).json()).sources), ["relay"]);
});

test("a ledger that cannot be reached is never in a visitor's way, and what it missed is counted", async () => {
  const { call, settle, deps, brought, ledger } = site({ watch: true, ledger: true, cf: CF });
  const reach = deps.watch.activity;
  deps.watch.activity = async () => { throw new Error("Durable Object reset"); };
  const errors = console.error;
  console.error = () => {};
  try {
    assert.equal((await open(call)).status, 200);
    assert.equal((await open(call, {}, "/about")).status, 200);
    await settle();
  } finally { console.error = errors; }
  assert.equal(brought.length, 0);
  deps.watch.activity = reach;
  assert.equal((await open(call)).status, 200);
  await settle();
  assert.deepEqual(brought.map((b) => [b.events.length, b.lost]), [[1, 2]]);
  assert.equal(ledger.get("lost"), 2);
});

test("a visitor may ask what is held of them, and be forgotten, before the registry has been written to at all", async () => {
  const { call } = site({ watch: true, ledger: true, cf: CF });
  const cookie = cookieOf(await open(call)); // nothing drained yet: the registry has no tables
  const me = await (await call(`${PAGE}/api/activity/me`, { headers: { ...BROWSER, Cookie: cookie } })).json();
  assert.deepEqual([me.state, isVisitor(me.visitor), me.held], ["valid", true, null]);
  const gone = await post(call, "/api/activity/forget", {}, { Cookie: cookie });
  assert.equal(gone.status, 200);
  assert.equal((await gone.json()).forgotten, false);
});
