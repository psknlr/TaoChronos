// The site's Worker under Node: the handler (site.js) with plain objects for its bindings — the site's files, the
// corpus Worker, the bucket and the rate limits.  Run: node --test cloud/test/

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { drain, EVENTS } from "../../security/archive.js";
import { WatchCore } from "../../security/sentinel.js";
import { UsageCore } from "../../security/usage.js";
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

/** The site with plain objects for its bindings.  watch: true gives it the sentinel's memory; cf: what the edge would
 * say of every request (request.cf). */
function site({ corpus = true, store = false, env = {}, limit, watch = false, cf } = {}) {
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
    ...env,
  };
  const core = watch ? new WatchCore(sqlStore()) : null;
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
  }
  const call = (url, init = {}) => {
    const request = new Request(url, init);
    if (cf) request.cf = cf;
    return handle(request, full, deps);
  };
  const settle = () => { for (const go of held.splice(0)) go(); return Promise.all(pending.splice(0)); }; // what the Worker finishes after the answer (ctx.waitUntil)
  return { call, seen, objects, watch: core, counts, usageCalls, settle, advance: (ms) => { t += ms; }, deps };
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
  assert.deepEqual(seen.corpus.map((c) => new URL(c.url).pathname + new URL(c.url).search), [
    "/api/info", "/api/catalog?mode=all", "/api/passage?id=jc_a000.12", "/api/research/job-1a2b", "/api/session/s_42?what=summary", "/api/call"]);
});

test("nothing else reaches the corpus: no model proxy, no other endpoint or method", async () => {
  const { call, seen } = site();
  for (const [path, init] of [["/api/llm", { method: "POST", body: "{}" }], ["/api/llm/chat/completions", { method: "POST", body: "{}" }],
    ["/api/providers", {}], ["/api/info", { method: "POST", body: "{}" }], ["/api/call", {}], ["/api/session/a/b", {}],
    ["/api/research/a%2Fb", {}], ["/api", {}]]) {
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

test("the pages' headers: no device features; the reported policy and where to report it", async () => {
  const { call } = site({ env: { CSP_REPORT_ONLY: "default-src 'self'; report-to csp" } });
  const page = await call(`${PAGE}/`);
  const script = await call(`${PAGE}/js/app.js`);
  assert.equal(page.headers.get("Permissions-Policy"), DEFAULTS.PERMISSIONS_POLICY);
  assert.equal(page.headers.get("Content-Security-Policy-Report-Only"), "default-src 'self'; report-to csp");
  assert.equal(page.headers.get("Reporting-Endpoints"), 'csp="https://chat.impf.ai/api/security/csp"');
  assert.equal(page.headers.get("X-Frame-Options"), "SAMEORIGIN");
  assert.equal(page.headers.get("Cross-Origin-Opener-Policy"), "same-origin");
  assert.equal(page.headers.get("Cross-Origin-Resource-Policy"), "same-origin");
  assert.equal(script.headers.get("Cross-Origin-Opener-Policy"), null);
  assert.equal(script.headers.get("Content-Security-Policy-Report-Only"), null);
  assert.equal(script.headers.get("Permissions-Policy"), DEFAULTS.PERMISSIONS_POLICY);
  const uri = site({ env: { CSP_REPORT_ONLY: "default-src 'self'; report-uri /api/security/csp" } });
  assert.equal((await uri.call(`${PAGE}/`)).headers.get("Reporting-Endpoints"), null);
  const none = site();
  assert.equal((await none.call(`${PAGE}/`)).headers.get("Content-Security-Policy-Report-Only"), null);
  assert.equal((await none.call(`${PAGE}/`)).headers.get("Reporting-Endpoints"), null);
});

test("the policy deployed names the pages' inline scripts and styles by their hashes, as web/ has them", () => {
  const toml = readFileSync(new URL("../site/wrangler.toml", import.meta.url), "utf-8");
  const policy = /^CSP_REPORT_ONLY = "(.*)"$/m.exec(toml)[1];
  const hash = (text) => `'sha256-${createHash("sha256").update(text).digest("base64")}'`;
  const inline = { scripts: [], styles: [], attrs: [] };
  for (const file of ["index.html", "about.html", "attribution.html"]) {
    const html = readFileSync(new URL(`../../web/${file}`, import.meta.url), "utf-8");
    for (const m of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) if (!/ld\+json|src=/.test(m[1])) inline.scripts.push(hash(m[2]));
    for (const m of html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) inline.styles.push(hash(m[1]));
    for (const m of html.matchAll(/ style="([^"]*)"/g)) inline.attrs.push(hash(m[1]));
  }
  assert.deepEqual([inline.scripts.length, inline.styles.length, inline.attrs.length], [2, 2, 1]); // an inline block added to a page needs its hash in the policy
  const directive = (name) => (new RegExp(`(?:^|; )${name} ([^;]*)`).exec(policy) || [])[1] || "";
  for (const h of inline.scripts) assert.ok(directive("script-src").includes(h), `script-src lacks ${h}`);
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
