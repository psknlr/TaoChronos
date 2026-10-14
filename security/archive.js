// The archive: a private R2 bucket (the binding ARCHIVE, when a Worker has one) that takes over from the repository what
// the Workers' Durable Objects keep waiting — the conversation records (relay/src/state.js: LogBookCore) and the
// sentinel's events (security/sentinel.js: WatchCore) — so that neither is committed to the repository any more
// (docs/adr/0023-workers-paid.md).  Shared by both Workers, as the sentinel is; tested under Node (security/test/).
//
// The Durable Object is the outbox: a record or an event is in its SQLite before its request is answered, and leaves it
// only once its object is in the bucket.  drain() reads the oldest waiting, writes one object each — its key made of
// its day and its id, so that a write repeated after a failure lands on the same object — and removes them through the
// last one written.  An object's body is the line the repository's collector writes (n, received, the record's or the
// event's fields; the source of an event), its keys sorted, and R2 checks its sha256 on the way in.
//
//   chat-logs/YYYY/MM/DD/<id>.json                  a conversation record (the relay)
//   security-logs/<source>/YYYY/MM/DD/<id>.json     an event of a sentinel (source: relay | site)
//
// No name, address or text is in a key.  While a Worker has the bucket, the archive is its stores' only collector: the
// repository's acknowledgement is refused (409), so that two collectors never delete from the same store.  The holder of
// the collector's token reads a day back with serveArchive().

import { bearerOk, json } from "./sentinel.js";

export const RECORDS = "chat-logs/";
export const EVENTS = (source) => `security-logs/${source}/`;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");

/** A value with its objects' keys sorted, all the way down (one body for one record, however its fields were built). */
export const canonical = (v) => (Array.isArray(v) ? v.map(canonical)
  : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canonical(v[k])])) : v);

/** The key of an item ({id, received}) under a prefix: its day (UTC, as received) and its id. */
export function archiveKey(prefix, item) {
  const day = String(item.received || "").slice(0, 10);
  const d = DAY.test(day) ? day : "0000-00-00";
  return `${prefix}${d.slice(0, 4)}/${d.slice(5, 7)}/${d.slice(8, 10)}/${String(item.id).padStart(12, "0")}.json`;
}

/** The body of an item: {n, received, ...extra, ...item[field]}, its keys sorted. */
export function archiveBody(item, field, extra = {}) {
  return JSON.stringify(canonical({ n: item.id, received: item.received, ...extra, ...(item[field] || {}) }));
}

/**
 * The oldest items a store keeps waiting, into the bucket: store {records(after, limit) → {items, more}, remove(through)}
 * (a Durable Object's core: LogBookCore, WatchCore), bucket an R2 binding.  Written one at a time, oldest first; removed
 * through the last one written, never further.  → {archived, through, more, failed}: more — others wait (drain again
 * soon); failed — a write failed (drain again later; what was written is removed, the rest stays).
 */
export async function drain(store, bucket, { prefix, field, extra = {}, limit = 100 }) {
  const { items, more } = await store.records(0, limit);
  let through = 0;
  let archived = 0;
  let failed = false;
  for (const item of items) {
    const body = archiveBody(item, field, extra);
    try {
      const sha256 = hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)));
      const put = await bucket.put(archiveKey(prefix, item), body, {
        sha256, httpMetadata: { contentType: "application/json; charset=utf-8" },
        customMetadata: { received: String(item.received || ""), conversation: String(item[field]?.conversation || "").slice(0, 64) },
      });
      if (!put) throw new Error("not written");
    } catch (err) {
      console.error("archive", prefix, err?.name || "Error", err?.message || "");
      failed = true;
      break;
    }
    through = item.id;
    archived += 1;
  }
  if (through) await store.remove(through);
  return { archived, through, more: Boolean(more) || archived < items.length, failed };
}

/**
 * What a Durable Object does to keep one store drained into the bucket: arm() after it writes (an alarm a moment later,
 * set once — `armed` spares the storage a look on every request), run() from its alarm() (another alarm at once while
 * more wait, later after a failure).  Without a bucket, nothing.
 */
export class Drainer {
  constructor(storage, bucket, job, { delay = 30000, retry = 300000 } = {}) {
    this.storage = storage;
    this.bucket = bucket || null;
    this.job = job;
    this.delay = delay;
    this.retry = retry;
    this.armed = false;
  }

  async arm(now = Date.now()) {
    if (!this.bucket || this.armed) return;
    this.armed = true;
    if ((await this.storage.getAlarm()) === null) await this.storage.setAlarm(now + this.delay);
  }

  async run(now = Date.now()) {
    this.armed = false;
    if (!this.bucket) return null;
    const out = await drain(this.job.store, this.bucket, this.job);
    if (out.failed || out.more) {
      this.armed = true;
      await this.storage.setAlarm(now + (out.failed ? this.retry : 1000));
    }
    return out;
  }
}

/**
 * GET <path>?day=YYYY-MM-DD&cursor=&limit=  the items archived that day under `prefix`, oldest first, for the holder of
 * the collector's token: {day, items, cursor, more}.  Without a bucket, 404.
 */
export async function serveArchive(request, url, { bucket, prefix, token, cors = {} }) {
  if (!bucket) return json({ error: { message: "没有归档", type: "not_found" } }, 404, cors);
  if (request.method !== "GET") return json({ error: { message: "GET", type: "bad_request" } }, 405, { ...cors, Allow: "GET" });
  if (!(await bearerOk(request, token))) return json({ error: { message: "需要收集令牌", type: "unauthorized" } }, 401, cors);
  const day = url.searchParams.get("day") || "";
  if (!DAY.test(day)) return json({ error: { message: "day=YYYY-MM-DD", type: "bad_request" } }, 400, cors);
  const limit = Math.min(100, Math.max(1, Math.floor(Number(url.searchParams.get("limit") || 100)) || 100));
  const listed = await bucket.list({ prefix: `${prefix}${day.slice(0, 4)}/${day.slice(5, 7)}/${day.slice(8, 10)}/`, limit,
    cursor: url.searchParams.get("cursor") || undefined });
  const items = [];
  for (const o of listed.objects) {
    const got = await bucket.get(o.key);
    if (!got) continue; // removed since it was listed
    try { items.push(JSON.parse(await got.text())); } catch { items.push({ key: o.key, unreadable: true }); }
  }
  return json({ day, items, cursor: listed.truncated ? listed.cursor : null, more: Boolean(listed.truncated) }, 200, cors);
}
