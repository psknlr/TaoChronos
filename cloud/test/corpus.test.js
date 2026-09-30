// The corpus Worker's routing under Node (corpus.js): what it keeps, what it forwards to the container.
// Run: node --test cloud/test/

import assert from "node:assert/strict";
import test from "node:test";

import { reach, route, unavailable } from "../corpus/src/corpus.js";

function box({ version = "v2", answer } = {}) {
  const storage = new Map();
  const seen = { forwarded: [], warmed: 0 };
  const b = {
    version,
    storage,
    seen,
    get: async (k) => storage.get(k),
    put: async (k, v) => { storage.set(k, v); },
    list: async (prefix) => new Map([...storage].filter(([k]) => k.startsWith(prefix))),
    delete: async (keys) => { for (const k of keys) storage.delete(k); },
    warm: () => { seen.warmed++; },
    forward: async (request) => {
      seen.forwarded.push(`${request.method} ${new URL(request.url).pathname}${new URL(request.url).search}`);
      return answer ? answer(request) : new Response(JSON.stringify({ name: "TaoChronos", path: new URL(request.url).pathname }), {
        headers: { "Content-Type": "application/json" } });
    },
  };
  return b;
}

const get = (path) => new Request(`https://corpus.internal${path}`);

test("info and the catalogs are asked once per version, then answered while the container sleeps", async () => {
  const b = box();
  b.storage.set("snap:v1:info", "{\"old\":true}");
  b.storage.set("token", "t");
  const first = await route(get("/api/info"), b);
  assert.equal(first.headers.get("X-TC-Corpus"), "live");
  assert.equal((await first.json()).path, "/api/info");
  assert.deepEqual(b.seen.forwarded, ["GET /api/info"]);
  assert.equal(b.storage.has("snap:v1:info"), false, "an earlier version's answers are dropped");
  assert.equal(b.storage.get("token"), "t");
  const again = await route(get("/api/info"), b);
  assert.equal(again.headers.get("X-TC-Corpus"), "kept");
  assert.equal((await again.json()).path, "/api/info");
  assert.equal(b.seen.forwarded.length, 1);
  assert.equal(b.seen.warmed, 1, "a page asking wakes the container");
  await route(get("/api/catalog"), b);
  await route(get("/api/catalog?mode=core"), b);
  await route(get("/api/catalog?mode=all"), b);
  await route(get("/api/catalog?mode=all"), b);
  assert.deepEqual(b.seen.forwarded, ["GET /api/info", "GET /api/catalog", "GET /api/catalog?mode=all"]);
  assert.deepEqual([...b.storage.keys()].filter((k) => k.startsWith("snap:")).sort(), ["snap:v2:catalog:all", "snap:v2:catalog:core", "snap:v2:info"]);
});

test("everything else goes to the container, every time", async () => {
  const b = box();
  for (const request of [get("/api/passage?id=a.1"), get("/api/passage?id=a.1"), get("/api/catalog?mode=odd"), get("/api/research/j1"),
    new Request("https://corpus.internal/api/call", { method: "POST", body: "{}" })]) {
    await route(request, b);
  }
  assert.deepEqual(b.seen.forwarded, ["GET /api/passage?id=a.1", "GET /api/passage?id=a.1", "GET /api/catalog?mode=odd", "GET /api/research/j1", "POST /api/call"]);
  assert.equal([...b.storage.keys()].length, 0);
});

test("an answer that is not the runtime's is passed on, not kept", async () => {
  const down = box({ answer: () => unavailable() });
  const res = await route(get("/api/info"), down);
  assert.equal(res.status, 503);
  assert.equal(res.headers.get("Retry-After"), "10");
  assert.equal((await res.json()).starting, true);
  assert.equal(down.storage.size, 0);
  const odd = box({ answer: () => new Response("<html>", { status: 200 }) });
  assert.equal((await route(get("/api/info"), odd)).status, 502);
  assert.equal(odd.storage.size, 0);
});

test("a Durable Object without its container, or failing, is answered as the page can fall back on", async () => {
  const ok = await reach(async () => new Response("{}", { status: 200 }));
  assert.equal(ok.status, 200);
  // the Worker uploaded, its container not deployed (no Workers Paid, or the token cannot deploy containers)
  const bare = await reach(async () => {
    throw new Error("Containers have not been enabled for this Durable Object class. Have you correctly setup your Wrangler config?");
  });
  assert.equal(bare.status, 503);
  assert.equal(bare.headers.get("X-TC-Corpus"), "none");
  assert.equal((await bare.json()).corpus, "none");
  const broken = await reach(async () => { throw new Error("Durable Object reset because its code was updated."); });
  assert.equal(broken.status, 503);
  assert.equal(broken.headers.get("Retry-After"), "10");
  assert.equal((await broken.json()).starting, true);
});
