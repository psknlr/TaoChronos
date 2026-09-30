// The site's Worker under Node: the handler (site.js) with plain objects for its bindings — the site's files, the
// corpus Worker, the bucket and the rate limits.  Run: node --test cloud/test/

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { handle } from "../site/src/site.js";

const TOKEN = "upload-token-for-tests-only";
const TOKEN_SHA = createHash("sha256").update(TOKEN).digest("hex");
const PAGE = "https://chat.impf.ai";

function site({ corpus = true, store = false, env = {}, limit } = {}) {
  const seen = { assets: [], corpus: [], puts: [] };
  const objects = new Map();
  const full = {
    ASSETS: {
      fetch: async (request) => {
        seen.assets.push(request);
        const html = new URL(request.url).pathname === "/";
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
  const call = (url, init = {}) => handle(new Request(url, init), full, { limit });
  return { call, seen, objects };
}

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
});

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
