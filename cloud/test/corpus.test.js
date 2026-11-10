// The corpus Worker's routing under Node (corpus.js): what it keeps, what it forwards to the container.
// Run: node --test cloud/test/

import assert from "node:assert/strict";
import test from "node:test";

import { forwarded, reach, route, unavailable } from "../corpus/src/corpus.js";

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

/** The Durable Object's side of a call (index.js): whether it knows its container up, and what it did. */
function container({ running = true, start, send } = {}) {
  const c = { known: false, running, did: [] };
  c.box = {
    up: () => c.known && c.running,
    mark: (up) => { c.known = up; },
    start: async () => { c.did.push("start"); if (start) await start(c); c.running = true; },
    send: async () => { c.did.push("send"); return send ? send(c) : new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }); },
  };
  return c;
}

test("a container that is up is asked at once: it is started, and waited for, only when it is not known to be", async () => {
  const c = container();
  for (let i = 0; i < 4; i++) assert.equal((await forwarded(c.box)).status, 200); // a round of tools
  assert.deepEqual(c.did, ["start", "send", "send", "send", "send"]); // the first call finds out; the others pay nothing
  // asleep (it stopped running): the next call starts it again, and the ones after are asked at once again
  c.running = false;
  await forwarded(c.box);
  await forwarded(c.box);
  assert.deepEqual(c.did.slice(5), ["start", "send", "send"]);
  // an object brought back (its memory gone) finds out again, once
  c.known = false;
  await forwarded(c.box);
  await forwarded(c.box);
  assert.deepEqual(c.did.slice(8), ["start", "send", "send"]);
});

test("a container that cannot start, or that does not answer as the runtime does, is not taken for up", async () => {
  const quiet = async (fn) => { const err = console.error; console.error = () => {}; try { return await fn(); } finally { console.error = err; } };
  // it cannot start: the page is told what it can fall back on, nothing is sent, and the next call tries again
  let fail = true;
  const cold = container({ running: false, start: async () => { if (fail) throw new Error("no instance"); } });
  const res = await quiet(() => forwarded(cold.box));
  assert.equal(res.status, 503);
  assert.equal(res.headers.get("X-TC-Corpus"), "unavailable");
  assert.deepEqual(cold.did, ["start"]);
  fail = false;
  assert.equal((await forwarded(cold.box)).status, 200);
  assert.deepEqual(cold.did, ["start", "start", "send"]);
  // an answer that is not the runtime's (a 5xx that is not JSON): unavailable, and the next call waits for it again
  let odd = false;
  const ill = container({ send: () => (odd ? new Response("upstream connect error", { status: 502 }) : new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })) });
  await forwarded(ill.box);
  odd = true;
  const bad = await forwarded(ill.box);
  assert.equal(bad.status, 503);
  assert.equal(ill.known, false);
  odd = false;
  assert.equal((await forwarded(ill.box)).status, 200);
  assert.deepEqual(ill.did, ["start", "send", "send", "start", "send"]);
  // the runtime's own failure (JSON) is its answer: passed on, the container still up
  const own = container({ send: () => new Response(JSON.stringify({ error: "KeyError: x" }), { status: 500, headers: { "Content-Type": "application/json" } }) });
  assert.equal((await forwarded(own.box)).status, 500);
  assert.equal(own.known, true);
  // the container gone under the call: the failure is the caller's to tell (reach), and it is started again next time
  let gone = true;
  const lost = container({ send: () => { if (gone) throw new Error("Network connection lost."); return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }); } });
  const told = await quiet(() => reach(() => forwarded(lost.box)));
  assert.equal(told.status, 503);
  assert.equal(lost.known, false);
  gone = false;
  assert.equal((await forwarded(lost.box)).status, 200);
  assert.deepEqual(lost.did, ["start", "send", "start", "send"]);
});
