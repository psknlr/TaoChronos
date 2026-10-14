// The archive (security/archive.js) under Node: the stores on an in-memory SQLite (node:sqlite), a bucket in memory
// that checks what R2 checks, the relay's and the site's endpoints over them.  Run: node --test security/test/

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { archiveBody, archiveKey, canonical, Drainer, drain, EVENTS, RECORDS, serveArchive } from "../archive.js";
import { assess, fingerprint, serveSecurity, WatchCore } from "../sentinel.js";
import { LogBookCore } from "../../relay/src/state.js";

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

/** An R2 bucket in memory: a put with a sha256 that does not match the body is refused, as R2 refuses it; `fail(key)`
 * makes a put throw (the network, R2 down). */
function bucket({ fail = () => false } = {}) {
  const objects = new Map();
  const puts = [];
  return {
    objects, puts,
    async put(key, body, options = {}) {
      puts.push(key);
      if (fail(key)) throw new Error("R2 unavailable");
      if (options.sha256 && createHash("sha256").update(body).digest("hex") !== options.sha256) throw new Error("sha256 mismatch");
      objects.set(key, { body, options });
      return { key, size: Buffer.byteLength(body) };
    },
    async get(key) {
      const o = objects.get(key);
      return o ? { text: async () => o.body } : null;
    },
    async list({ prefix = "", limit = 1000, cursor } = {}) {
      const keys = [...objects.keys()].filter((k) => k.startsWith(prefix)).sort();
      const from = cursor ? Number(cursor) : 0;
      const page = keys.slice(from, from + limit);
      const truncated = from + limit < keys.length;
      return { objects: page.map((key) => ({ key })), truncated, cursor: truncated ? String(from + limit) : undefined };
    },
  };
}

const record = (k, extra = {}) => JSON.stringify({ v: 1, conversation: `c_${k}`, turn: k, question: `问${k}`, answer: `答${k}`, ...extra });
const TOKEN = "export-token-0123456789abcdef";

test("keys are made of the day and the id; a body is the collector's line, its keys sorted", () => {
  assert.equal(archiveKey(RECORDS, { id: 42, received: "2026-10-14T03:04:05.000Z" }), "chat-logs/2026/10/14/000000000042.json");
  assert.equal(archiveKey(EVENTS("site"), { id: 7, received: "2026-10-14T23:59:59Z" }), "security-logs/site/2026/10/14/000000000007.json");
  assert.equal(archiveKey(RECORDS, { id: 1, received: "garbage" }), "chat-logs/0000/00/00/000000000001.json");
  const body = archiveBody({ id: 3, received: "2026-10-14T00:00:00Z", event: { z: 1, a: { y: 2, b: 3 } } }, "event", { source: "relay" });
  assert.equal(body, '{"a":{"b":3,"y":2},"n":3,"received":"2026-10-14T00:00:00Z","source":"relay","z":1}');
  assert.deepEqual(canonical([{ b: 1, a: 2 }]), [{ a: 2, b: 1 }]);
});

test("the records go into the bucket and only then leave the book; a write that fails keeps them, a repeat writes the same objects", async () => {
  const book = new LogBookCore(sqlStore());
  for (let k = 1; k <= 5; k++) book.add(record(k), `2026-10-14T0${k}:00:00.000Z`);
  let broken = true;
  const b = bucket({ fail: (key) => broken && key.endsWith("000000000004.json") });
  const first = await drain(book, b, { prefix: RECORDS, field: "record" });
  assert.deepEqual(first, { archived: 3, through: 3, more: true, failed: true });
  assert.deepEqual(book.records(0, 10).items.map((i) => i.id), [4, 5]); // removed through the last one written, not further
  assert.equal(b.objects.size, 3);
  const one = JSON.parse(b.objects.get("chat-logs/2026/10/14/000000000002.json").body);
  assert.deepEqual([one.n, one.turn, one.question, one.received], [2, 2, "问2", "2026-10-14T02:00:00.000Z"]);
  assert.equal(b.objects.get("chat-logs/2026/10/14/000000000002.json").options.customMetadata.conversation, "c_2");
  broken = false;
  const second = await drain(book, b, { prefix: RECORDS, field: "record" });
  assert.deepEqual(second, { archived: 2, through: 5, more: false, failed: false });
  assert.equal(book.waiting(), 0);
  assert.equal(b.objects.size, 5);
  // the same item written twice (a drain that wrote, then failed before removing) lands on the same object, unchanged
  const again = new LogBookCore(sqlStore());
  again.add(record(1), "2026-10-14T01:00:00.000Z");
  const before = b.objects.get("chat-logs/2026/10/14/000000000001.json").body;
  await drain(again, b, { prefix: RECORDS, field: "record" });
  assert.equal(b.objects.size, 5);
  assert.equal(b.objects.get("chat-logs/2026/10/14/000000000001.json").body, before);
  // nothing waiting: nothing written, nothing removed
  assert.deepEqual(await drain(again, b, { prefix: RECORDS, field: "record" }), { archived: 0, through: 0, more: false, failed: false });
});

test("a body that does not reach the bucket whole is refused there, and stays in the book", async () => {
  const book = new LogBookCore(sqlStore());
  book.add(record(1), "2026-10-14T01:00:00.000Z");
  const b = bucket();
  const put = b.put.bind(b);
  b.put = (key, body, options) => put(key, `${body} `, options); // a byte changed on the way
  const errors = [];
  const log = console.error;
  console.error = (...a) => errors.push(a.join(" "));
  try {
    assert.equal((await drain(book, b, { prefix: RECORDS, field: "record" })).failed, true);
  } finally { console.error = log; }
  assert.match(errors[0], /sha256 mismatch/);
  assert.equal(book.waiting(), 1);
  assert.equal(b.objects.size, 0);
});

test("the Durable Object's alarm: set once after a write, again at once while more wait, later after a failure; nothing without a bucket", async () => {
  const storage = { alarm: null, sets: [], async getAlarm() { return this.alarm; }, async setAlarm(t) { this.alarm = t; this.sets.push(t); } };
  const book = new LogBookCore(sqlStore());
  const b = bucket();
  const d = new Drainer(storage, b, { store: book, prefix: RECORDS, field: "record", limit: 2 }, { delay: 30000, retry: 300000 });
  for (let k = 1; k <= 3; k++) book.add(record(k), "2026-10-14T01:00:00.000Z");
  await d.arm(1000);
  await d.arm(1001);
  assert.deepEqual(storage.sets, [31000]); // once: the later writes find it armed
  storage.alarm = null; // the alarm fires
  assert.deepEqual(await d.run(31000), { archived: 2, through: 2, more: true, failed: false });
  assert.deepEqual(storage.sets, [31000, 32000]); // more wait: again in a second
  storage.alarm = null;
  assert.deepEqual(await d.run(32000), { archived: 1, through: 3, more: false, failed: false });
  assert.equal(storage.alarm, null); // all archived: no alarm until the next write
  book.add(record(4), "2026-10-14T02:00:00.000Z");
  b.put = async () => { throw new Error("R2 unavailable"); };
  await d.arm(40000);
  storage.alarm = null;
  const log = console.error;
  console.error = () => {};
  try { assert.equal((await d.run(70000)).failed, true); } finally { console.error = log; }
  assert.equal(storage.alarm, 370000); // tried again in five minutes; the record waits in the book
  assert.equal(book.waiting(), 1);
  const none = new Drainer(storage, undefined, { store: book, prefix: RECORDS, field: "record" });
  storage.sets = [];
  await none.arm();
  assert.equal(await none.run(), null);
  assert.deepEqual(storage.sets, []);
});

test("a day of the archive is read back with the collector's token, a page at a time", async () => {
  const book = new LogBookCore(sqlStore());
  for (let k = 1; k <= 3; k++) book.add(record(k), "2026-10-14T01:00:00.000Z");
  book.add(record(4), "2026-10-15T01:00:00.000Z");
  const b = bucket();
  await drain(book, b, { prefix: RECORDS, field: "record" });
  const read = (q, auth = TOKEN, method = "GET") => serveArchive(new Request(`https://chat-api.impf.ai/v1/logs/archive${q}`, { method, headers: auth ? { Authorization: `Bearer ${auth}` } : {} }),
    new URL(`https://chat-api.impf.ai/v1/logs/archive${q}`), { bucket: b, prefix: RECORDS, token: TOKEN });
  assert.equal((await read("?day=2026-10-14", null)).status, 401);
  assert.equal((await read("?day=2026-10-14", "wrong-token-0123456789")).status, 401);
  assert.equal((await read("?day=14.10.2026")).status, 400);
  assert.equal((await read("?day=2026-10-14", TOKEN, "POST")).status, 405);
  const page1 = await (await read("?day=2026-10-14&limit=2")).json();
  assert.deepEqual([page1.items.map((i) => i.n), page1.more], [[1, 2], true]);
  const page2 = await (await read(`?day=2026-10-14&limit=2&cursor=${page1.cursor}`)).json();
  assert.deepEqual([page2.items.map((i) => i.n), page2.more, page2.cursor], [[3], false, null]);
  assert.deepEqual((await (await read("?day=2026-10-15")).json()).items.map((i) => i.question), ["问4"]);
  const none = await serveArchive(new Request("https://x/a?day=2026-10-14"), new URL("https://x/a?day=2026-10-14"), { bucket: undefined, prefix: RECORDS, token: TOKEN });
  assert.equal(none.status, 404);
});

test("the sentinel's events: drained like the records, the export says the archive collects them, an ack is refused", async () => {
  const watch = new WatchCore(sqlStore());
  const t = Date.UTC(2026, 9, 14, 8, 0, 0);
  const probe = new Request("https://chat.impf.ai/wp-login.php", { headers: { "User-Agent": "python-requests/2.31.0", "CF-Connecting-IP": "45.138.12.10" } });
  const fp = fingerprint(probe, t);
  await watch.observe(fp, assess(fp, { route: "honeypot" }), { status: 404 }, undefined, t);
  const b = bucket();
  const out = await drain(watch, b, { prefix: EVENTS("site"), field: "event", extra: { source: "site" } });
  assert.deepEqual([out.archived, out.failed], [1, false]);
  const [key] = b.objects.keys();
  assert.equal(key, "security-logs/site/2026/10/14/000000000001.json");
  const ev = JSON.parse(b.objects.get(key).body);
  assert.deepEqual([ev.n, ev.source, ev.kind, ev.fp.path], [1, "site", "honeypot", "/wp-login.php"]);
  assert.deepEqual(watch.records(0, 10).items, []);
  const serve = (path, init = {}) => serveSecurity(new Request(`https://chat.impf.ai/api/security/${path}`, { ...init, headers: { Authorization: `Bearer ${TOKEN}` } }),
    new URL(`https://chat.impf.ai/api/security/${path}`), { prefix: "/api/security", token: TOKEN, watch, cfg: {}, fp, now: t, archived: true });
  assert.equal((await (await serve("export")).json()).archive, "r2");
  const ack = await serve("ack", { method: "POST", body: JSON.stringify({ through: 1 }) });
  assert.equal(ack.status, 409);
  assert.equal((await ack.json()).error.type, "archived");
});
