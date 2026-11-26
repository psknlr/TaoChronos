// 活动账本 — the User Activity Ledger: what both Workers write down of every request they answer, whatever its score.
// Shared by the relay (relay/) and the site (cloud/site/), as the sentinel is; tested under Node (security/test/).
//
// The sentinel (sentinel.js) keeps a request only when it is worth a look, and the usage counts (usage.js) keep sums by
// day and place.  Neither can say how many different visitors a month had, how many of them came back, how many
// questions were asked that nobody agreed to have recorded, or what a question cost.  The ledger can, and it is kept
// apart from both: the sentinel still decides what is refused and still holds the addresses of what it flags; the
// ledger holds no address at all and decides nothing.
//
//   an event        one line of what happened: a page opened, the site's API read, a question asked, a model called,
//                   what it cost — who by (a visitor's id: visitor.js; never an address), from where (country, region,
//                   network), with what (the browser's family, the system, phone or desktop, the language), and what the
//                   sentinel made of it (a class, a score, an action).  describe() and classify() below are all that is
//                   read of a request for it
//   the outbox      a Durable Object's SQLite (LedgerCore): an event is in it before anything else happens to it, under
//                   an id that makes a second writing of it a no-op
//   the registry    Cloudflare D1 (ledger-d1.js): the visitors, their days and visits, the questions, the model calls and
//                   the days' sums — what the owner's daily reports read.  The only place that knows two days'
//                   visitors to be the same one
//   the archive     the private R2 bucket (archive.js), when a Worker has one: an hour of events an object, gzip, a
//                   manifest a day saying what each must hash to.  A visitor is named there by the day (visitor.js:
//                   dayAlias), so the archive counts a day's visitors and cannot follow one across days
//
// A question and the conversation it belongs to.  The page names each turn (X-Tao-Turn: its answer's message id), and
// every call of the turn — a tool round, the self-check's rewrite, an answer written on, the page asking again after a
// failure — carries the name, so a turn is one question however many calls it takes.  That name is also in the
// conversation record of a visitor who agreed to one, so the ledger never keeps it: the relay's object remembers a keyed
// digest of it for ACTIVITY_TURN_DAYS (ledger_turns, in no export), and the events carry an id of the ledger's own
// making (turn_id).  Whoever holds the records and the ledger cannot tell which visitor asked what; they can tell how
// many questions were recorded and how many were not, which is what was asked for.

import { ACTIVITY, MANIFESTS, batchKey, canonical, putBatch, sooner } from "./archive.js";
import { apply, ensure, prune, rollup, syncManifest } from "./ledger-d1.js";
import { place, usageDay } from "./usage.js";
import { dayAlias } from "./visitor.js";

export const SCHEMA_VERSION = 1;

/** What an event may be.  `request` is whatever else a Worker answered (a path that is not there, a scanner's, another
 * site's page): counted, classed, and nothing more. */
export const EVENT_TYPES = ["page_view", "page_ready", "api_read", "api_call", "research_started", "request", "question_submitted",
  "model_invocation", "model_settled", "model_refused", "turn_finished", "record_archived", "feedback_submitted", "sponsor_submitted",
  "visitor_choice"];

// ------------------------------------------------------------------ ids
const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** An id that sorts by the time it was made (a ULID: 48 bits of milliseconds, 80 random). */
export function ulid(now = Date.now()) {
  let t = Math.max(0, Math.floor(now));
  let time = "";
  for (let i = 0; i < 10; i++) { time = B32[t % 32] + time; t = Math.floor(t / 32); }
  let rand = "";
  for (const b of crypto.getRandomValues(new Uint8Array(16))) rand += B32[b % 32];
  return time + rand;
}

// ------------------------------------------------------------------ what is read of a request
// a browser by its family: the in-app browsers a link in a chat program opens come first (they also say Chrome or Safari)
const BROWSERS = [[/micromessenger/i, "WeChat"], [/dingtalk/i, "DingTalk"], [/\b(?:lark|feishu)\b/i, "Feishu"], [/alipayclient/i, "Alipay"],
  [/weibo/i, "Weibo"], [/qqbrowser|\bqq\//i, "QQ"], [/ucbrowser|\bucweb/i, "UC"], [/quark/i, "Quark"], [/baiduboxapp|baidubrowser/i, "Baidu"],
  [/huaweibrowser/i, "Huawei"], [/miuibrowser/i, "Mi"], [/heytapbrowser|oppobrowser/i, "OPPO"], [/vivobrowser/i, "vivo"],
  [/samsungbrowser/i, "Samsung"], [/edg(?:e|a|ios)?\//i, "Edge"], [/\bopr\/|opera/i, "Opera"], [/firefox\/|fxios\//i, "Firefox"],
  [/chrome\/|crios\/|chromium\//i, "Chrome"], [/safari\//i, "Safari"]];
const SYSTEMS = [[/windows nt|windows phone/i, "Windows"], [/iphone|ipad|ipod/i, "iOS"], [/harmonyos|openharmony/i, "HarmonyOS"],
  [/android/i, "Android"], [/\bcros\b/i, "ChromeOS"], [/mac os x|macintosh/i, "macOS"], [/linux|x11/i, "Linux"]];
const first = (table, text) => { for (const [re, name] of table) if (re.test(text)) return name; return "Other"; };

/**
 * A request's browser as the ledger keeps it: a family, a system, a kind of device, a language — four words a great
 * many visitors share.  Not the agent string, its version, the client hints or the handshake: those tell one browser
 * from the next, and stay with the sentinel's events of what it flags.  What is not a browser has none of them.
 */
export function describe(fp = {}) {
  if (fp.uaClass !== "browser" || !fp.ua) return { browser_family: null, os_family: null, device_type: null, language: null };
  const ua = fp.ua;
  const tablet = /ipad|tablet|playbook|silk/i.test(ua) || (/android/i.test(ua) && !/mobile/i.test(ua));
  const mobile = !tablet && (fp.chMobile === "?1" || /mobi|iphone|ipod|windows phone/i.test(ua));
  const tag = /^\s*([A-Za-z]{2,3})(?:-([A-Za-z0-9]{2,8}))?/.exec(fp.lang || "");
  return {
    browser_family: first(BROWSERS, ua), os_family: first(SYSTEMS, ua), device_type: tablet ? "tablet" : mobile ? "mobile" : "desktop",
    language: tag ? tag[1].toLowerCase() + (tag[2] ? `-${tag[2].length === 2 ? tag[2].toUpperCase() : tag[2][0].toUpperCase() + tag[2].slice(1).toLowerCase()}` : "") : null,
  };
}

/**
 * What the sentinel made of a request, in three words.  a: its assessment; w: the object's word (when it was asked);
 * led: the page of another site that made a browser send it (sentinel.js: ledFrom).
 *
 *   traffic_class    human (a browser nothing is held against) · suspect (a browser the sentinel flagged) · crawler ·
 *                    automation (a tool, a scanner, no agent) · own (the repository's clients) · cross_site · unknown
 *   security_action  none · flagged · shadow · blocked · honeypot · rate_limited · cross_site
 */
export function classify(fp = {}, a = null, w = null, { led = null, status = null, flagScore = 5 } = {}) {
  const score = Math.max(0, Math.round(Number(w?.score ?? a?.score ?? 0)) || 0);
  if (led) return { traffic_class: "cross_site", risk_score: 0, security_action: "cross_site" };
  const flagged = Boolean(w?.flagged) || score >= flagScore;
  const action = w?.blocked ? "blocked" : a?.route === "honeypot" ? "honeypot" : w?.shadow ? "shadow" : status === 429 ? "rate_limited" : flagged ? "flagged" : "none";
  const cls = a?.own ? "own"
    : fp.uaClass === "browser" ? (action === "none" || action === "rate_limited" ? "human" : "suspect")
      : fp.uaClass === "bot" ? "crawler" : ["tool", "scanner", "empty"].includes(fp.uaClass) ? "automation" : "unknown";
  return { traffic_class: cls, risk_score: score, security_action: action };
}

/**
 * An event of a request: its common fields (more: the event's own).  Never the address, the agent string, a path that
 * is not one of the site's own, a query, or anything a visitor wrote.  A request another site's page made a browser
 * send is counted with its country and nothing else of who sent it, and never for a visitor.
 */
export function envelope({ type, source, fp = {}, a = null, w = null, led = null, status = null, visitor = null, now = Date.now(), offset = 8,
  route = null, latency = null, flagScore = 5, n = 1, more = {} }) {
  const c = classify(fp, a, w, { led, status, flagScore });
  const where = place(fp);
  const out = {
    event_id: `evt_${ulid(now)}`, timestamp: new Date(now).toISOString(), schema_version: SCHEMA_VERSION, source, event_type: type,
    day: usageDay(now, offset), visitor_id: c.traffic_class === "human" ? visitor : null,
    host: fp.host || null, route, method: fp.method || null, status, latency_ms: latency === null ? null : Math.max(0, Math.round(latency)), n,
    country: where.country, ...c,
  };
  if (!led) {
    Object.assign(out, describe(fp), { region: where.region || null, asn: Number.isFinite(Number(fp.asn)) ? Number(fp.asn) : null,
      http_protocol: fp.proto || null, tls_version: fp.tls || null });
  }
  return { ...out, ...more };
}

/** An event that changes one written before (a call's cost, a turn's end): when, and what it is about. */
const update = (type, source, now, offset, more) => ({ event_id: `evt_${ulid(now)}`, timestamp: new Date(now).toISOString(),
  schema_version: SCHEMA_VERSION, source, event_type: type, day: usageDay(now, offset), ...more });

// ------------------------------------------------------------------ the outbox
const parse = (text, fallback) => { try { return JSON.parse(text) ?? fallback; } catch { return fallback; } };
const NOISE_KEYS = 2000;

/**
 * The outbox and what the relay remembers of turns, over a `sql` object with the Durable Object SQL API's shape.
 *
 *   ledger_outbox    the events waiting: for the registry (D1) and, where there is one, the archive (R2).  A row goes
 *                    once both have it (the cursors d1_seq and r2_seq in ledger_meta)
 *   ledger_turns     key (a keyed digest of the page's id of a turn) → the ledger's own id of it, whether its question
 *                    is counted, whether its record came.  Forgotten after ACTIVITY_TURN_DAYS; in no export
 *   ledger_manifest  the archive's objects this object wrote
 *   ledger_meta      the counts the owner watches: appended, dropped (the outbox was full), duplicates (written twice,
 *                    kept once), lost (a Worker could not reach this object), the cursors, the failures
 */
export class LedgerCore {
  constructor(sql, source) {
    this.sql = sql;
    this.source = source;
    sql.exec("CREATE TABLE IF NOT EXISTS ledger_outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, received INTEGER NOT NULL, event TEXT NOT NULL)");
    sql.exec("CREATE TABLE IF NOT EXISTS ledger_meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL)");
    sql.exec("CREATE TABLE IF NOT EXISTS ledger_turns (key TEXT PRIMARY KEY, turn_id TEXT NOT NULL, created INTEGER NOT NULL, asked INTEGER NOT NULL DEFAULT 0, " +
      "archived INTEGER NOT NULL DEFAULT 0)");
    sql.exec("CREATE TABLE IF NOT EXISTS ledger_manifest (key TEXT PRIMARY KEY, day TEXT NOT NULL, hour INTEGER NOT NULL, part INTEGER NOT NULL, events INTEGER NOT NULL, " +
      "bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, first_seq INTEGER NOT NULL, last_seq INTEGER NOT NULL, types TEXT NOT NULL, written INTEGER NOT NULL, " +
      "synced INTEGER NOT NULL DEFAULT 0)");
    this.noise = new Map(); // what is not a visitor's, by the minute: `${minute}|…` → an event with its n (see note)
    this.size = null;       // the outbox's rows: counted once, then kept here
    this.swept = 0;
  }

  // ---- the counts
  get(k) {
    const rows = this.sql.exec("SELECT v FROM ledger_meta WHERE k = ?", k).toArray();
    return rows.length ? Number(rows[0].v) : 0;
  }

  set(k, v) {
    this.sql.exec("INSERT INTO ledger_meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", k, Math.floor(v));
  }

  bump(k, n = 1) {
    if (n) this.sql.exec("INSERT INTO ledger_meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = v + excluded.v", k, Math.floor(n));
  }

  waiting() {
    if (this.size === null) this.size = Number(this.sql.exec("SELECT COUNT(*) AS n FROM ledger_outbox").one().n);
    return this.size;
  }

  // ---- writing
  /**
   * Events into the outbox, each once: one written again under its id is kept once (and counted as a duplicate).  With
   * `keep` rows waiting (0: no bound) a new one is dropped and counted — the registry or the archive has been out of
   * reach for a long while, and what the counts then lack is known exactly.  lost: events a Worker could not bring here
   * before (it says so with the next it can).  → {appended, dropped, duplicates}
   */
  append(events, now = Date.now(), keep = 0, lost = 0) {
    let appended = 0, dropped = 0, duplicates = 0;
    for (const e of Array.isArray(events) ? events : []) {
      if (!e || typeof e !== "object" || !EVENT_TYPES.includes(e.event_type)) continue;
      if (keep && this.waiting() >= keep) { dropped += 1; continue; }
      const id = typeof e.event_id === "string" && /^evt_[0-9A-Z]{26}$/.test(e.event_id) ? e.event_id : `evt_${ulid(now)}`;
      const body = JSON.stringify({ ...e, event_id: id, source: e.source || this.source, schema_version: e.schema_version || SCHEMA_VERSION });
      const got = this.sql.exec("INSERT INTO ledger_outbox (event_id, received, event) VALUES (?, ?, ?) ON CONFLICT(event_id) DO NOTHING RETURNING seq", id, now, body).toArray();
      if (got.length) { appended += 1; if (this.size !== null) this.size += 1; } else duplicates += 1;
    }
    this.bump("appended", appended);
    this.bump("dropped", dropped);
    this.bump("duplicates", duplicates);
    this.bump("lost", Math.max(0, Math.floor(Number(lost) || 0)));
    return { appended, dropped, duplicates };
  }

  /**
   * An event of what is not a visitor's — a scanner's knocks, a crawler, another site's page — is not written at once:
   * the minute's like ones are added up here (in memory: an object evicted mid-minute loses a count of noise) and
   * written as one line when the minute is over.  A visitor's event is always its own line.
   */
  note(event, now = Date.now(), keep = 0) {
    if (!event || event.visitor_id || event.traffic_class === "human" || event.event_type !== "request") return this.append([event], now, keep);
    const minute = Math.floor(now / 60000);
    const key = [minute, event.traffic_class, event.security_action, event.route, event.status, event.host, event.country].join("|");
    const held = this.noise.get(key);
    if (held) held.n += event.n || 1;
    else this.noise.set(key, { ...event, n: event.n || 1 });
    if (this.noise.size > NOISE_KEYS) this.flush(now, keep, true);
    return { appended: 0, dropped: 0, duplicates: 0 };
  }

  /** The minutes that are over (all of them, when forced), into the outbox. */
  flush(now = Date.now(), keep = 0, force = false) {
    if (!this.noise.size) return;
    const minute = Math.floor(now / 60000);
    const done = [];
    for (const [key, event] of this.noise) {
      if (force || Number(key.slice(0, key.indexOf("|"))) < minute) { done.push(event); this.noise.delete(key); }
    }
    if (done.length) this.append(done, now, keep);
  }

  // ---- turns
  /** The turn a key names — opened when it is not known, or was forgotten: {turn_id, asked, archived}. */
  turn(key, now, ms) {
    this.sweep(now, ms);
    const rows = this.sql.exec("SELECT turn_id, created, asked, archived FROM ledger_turns WHERE key = ?", key).toArray();
    if (rows.length && now - Number(rows[0].created) < ms) return { turn_id: rows[0].turn_id, asked: Boolean(rows[0].asked), archived: Boolean(rows[0].archived) };
    const turn_id = `trn_${ulid(now)}`;
    this.sql.exec("INSERT INTO ledger_turns (key, turn_id, created, asked, archived) VALUES (?, ?, ?, 0, 0) " +
      "ON CONFLICT(key) DO UPDATE SET turn_id = excluded.turn_id, created = excluded.created, asked = 0, archived = 0", key, turn_id, now);
    return { turn_id, asked: false, archived: false };
  }

  /** Is this call its turn's first — its question?  For a relay without the ledger: the turn is remembered, so that the
   * usage counts take a question once, and nothing is written down. */
  asks(t, now, turnMs) {
    const turn = this.turn(t.key, now, turnMs);
    const question = !turn.asked && Boolean(t.explicit || t.turn);
    if (question) this.sql.exec("UPDATE ledger_turns SET asked = 1 WHERE key = ?", t.key);
    return { question };
  }

  /**
   * A model call the relay let through.  base: the call's envelope (the question's own fields with it: provider,
   * model); t: {key, explicit, turn} — the turn's key, whether the page named the turn, and, when it did not (a page
   * older than this), whether the call ends with what a visitor asked.  The turn's first call is its question, and
   * counted once; every call is a model invocation.  → {turn_id, invocation_id, question}
   */
  call(base, t, now, { turnMs, keep = 0 }) {
    const turn = this.turn(t.key, now, turnMs);
    const question = !turn.asked && Boolean(t.explicit || t.turn);
    const events = [];
    if (question) {
      this.sql.exec("UPDATE ledger_turns SET asked = 1 WHERE key = ?", t.key);
      events.push({ ...base, event_id: `evt_${ulid(now)}`, event_type: "question_submitted", turn_id: turn.turn_id, basis: "relay", named: Boolean(t.explicit) });
    }
    const invocation_id = `inv_${ulid(now)}`;
    events.push({ ...base, event_id: `evt_${ulid(now)}`, event_type: "model_invocation", turn_id: turn.turn_id, invocation_id });
    this.append(events, now, keep);
    return { turn_id: turn.turn_id, invocation_id, question };
  }

  /** How a model call ended and what it cost: {invocation_id, turn_id, execution_status, http_status, input_tokens,
   * output_tokens, asks, via, latency_ms, duration_ms}. */
  settle(outcome, now, { offset = 8, keep = 0 } = {}) {
    if (!outcome?.invocation_id) return;
    this.append([update("model_settled", this.source, now, offset, outcome)], now, keep);
  }

  /**
   * A turn's end, as the page tells it (the relay's /v1/activity): what it took and how it ended, in counts.  A turn
   * no call of which passed here — asked of the visitor's own model, answered by the page — is a question all the
   * same: counted now, on the page's word (basis: client).
   */
  finished(base, key, info, now, { turnMs, offset = 8, keep = 0 }) {
    const turn = this.turn(key, now, turnMs);
    const events = [];
    if (!turn.asked) {
      this.sql.exec("UPDATE ledger_turns SET asked = 1 WHERE key = ?", key);
      events.push({ ...base, event_id: `evt_${ulid(now)}`, event_type: "question_submitted", turn_id: turn.turn_id, basis: "client", named: true,
        provider: info.provider ?? null, model: info.model ?? null });
    }
    events.push(update("turn_finished", this.source, now, offset, { turn_id: turn.turn_id, ...info }));
    this.append(events, now, keep);
    return { turn_id: turn.turn_id, question: !turn.asked };
  }

  /**
   * A conversation record the relay took in for a turn: the turn is archived.  A record of a turn the ledger never
   * heard of (a page older than this, asking its own model) is the evidence of its question: counted now (basis:
   * record), with what the record says of it in counts — never its words.
   */
  recorded(base, key, info, now, { turnMs, offset = 8, keep = 0 }) {
    const turn = this.turn(key, now, turnMs);
    const events = [];
    if (!turn.asked) {
      events.push({ ...base, event_id: `evt_${ulid(now)}`, event_type: "question_submitted", turn_id: turn.turn_id, basis: "record", named: true,
        provider: info.provider ?? null, model: info.model ?? null });
    }
    if (!turn.archived) events.push(update("record_archived", this.source, now, offset, { turn_id: turn.turn_id, ...info }));
    this.sql.exec("UPDATE ledger_turns SET asked = 1, archived = 1 WHERE key = ?", key);
    this.append(events, now, keep);
    return { turn_id: turn.turn_id, question: !turn.asked, archived: !turn.archived };
  }

  // ---- reading
  /** The oldest `limit` rows after `after`: [{seq, received, event}]. */
  batch(after = 0, limit = 400) {
    return this.sql.exec("SELECT seq, received, event FROM ledger_outbox WHERE seq > ? ORDER BY seq LIMIT ?", after, limit).toArray()
      .map((r) => ({ seq: Number(r.seq), received: Number(r.received), event: parse(r.event, null) })).filter((r) => r.event);
  }

  /** The rows every sink has are let go (sinks: the cursors' names). */
  trim(sinks) {
    if (!sinks.length) return;
    const through = Math.min(...sinks.map((s) => this.get(s)));
    if (through > 0) {
      this.sql.exec("DELETE FROM ledger_outbox WHERE seq <= ?", through);
      this.size = null;
    }
  }

  /** Once an hour: the turns older than `turnMs` are forgotten, and the manifest's rows older than a hundred days (the
   * registry has them). */
  sweep(now, turnMs) {
    if (now - this.swept < 3600000) return;
    this.swept = now;
    this.sql.exec("DELETE FROM ledger_turns WHERE created < ?", now - turnMs);
    this.sql.exec("DELETE FROM ledger_manifest WHERE synced = 1 AND written < ?", now - 100 * 86400000);
  }

  /** What the owner watches (GET …/activity/health). */
  health(now = Date.now()) {
    const oldest = this.sql.exec("SELECT MIN(received) AS t FROM ledger_outbox").toArray()[0]?.t;
    const meta = Object.fromEntries(this.sql.exec("SELECT k, v FROM ledger_meta").toArray().map((r) => [r.k, Number(r.v)]));
    return { v: SCHEMA_VERSION, source: this.source, now: new Date(now).toISOString(), waiting: this.waiting(),
      oldest_seconds: oldest ? Math.max(0, Math.round((now - Number(oldest)) / 1000)) : 0, held: this.noise.size,
      turns: Number(this.sql.exec("SELECT COUNT(*) AS n FROM ledger_turns").one().n),
      objects: Number(this.sql.exec("SELECT COUNT(*) AS n FROM ledger_manifest").one().n),
      appended: 0, dropped: 0, duplicates: 0, lost: 0, d1_seq: 0, r2_seq: 0, d1_failures: 0, r2_failures: 0, ...meta };
  }
}

// ------------------------------------------------------------------ the drain
const D1_BATCH = 400;      // events a statement set: a few hundred kilobytes of JSON, well within D1's two megabytes a value
const D1_ROUNDS = 10;      // batches a run at most: the rest a second later
const PART = 5000;         // events an archive object at most: a busier hour is written in parts
const GRACE = 90000;       // an hour is written this long after it ended
const ROLLUP_MS = 300000;  // the days' sums are made again at most this often by a drain (the stats ask for them too)

/**
 * What a Durable Object does to empty its outbox: arm() after it writes (the object's alarm a moment later; the
 * sentinel's drain shares that alarm: archive.js, sooner), run() from its alarm().  Without a registry (no D1 binding)
 * nothing: the ledger is then off, and nothing is appended either.  A failure — the registry out of reach, a write
 * refused — leaves the rows where they are and tries again later; it is counted, and never thrown at a request.
 */
export class LedgerDrainer {
  constructor(storage, core, { db = null, bucket = null, cfg, offset = 8, delay = 20000, retry = 300000 } = {}) {
    this.storage = storage;
    this.core = core;
    this.db = db;
    this.bucket = bucket;
    this.cfg = cfg || { key: "", turnDays: 7, keep: 0, eventDays: 90, keepDays: 760, gapMinutes: 30 };
    this.offset = offset;
    this.delay = delay;
    this.retry = retry;
    this.armed = false;
    this.ready = false;
  }

  get on() { return Boolean(this.db && this.cfg.on !== false); }

  async arm(now = Date.now()) {
    if (!this.on || this.armed) return;
    this.armed = true;
    await sooner(this.storage, now + this.delay);
  }

  /** → {applied, archived, failed, more, next}: next — when the alarm was asked for again (milliseconds), or null. */
  async run(now = Date.now()) {
    this.armed = false;
    if (!this.on) return null;
    const core = this.core;
    const turnMs = this.cfg.turnDays * 86400000;
    core.flush(now, this.cfg.keep);
    core.sweep(now, turnMs);
    const out = { applied: 0, archived: 0, failed: false, more: false, next: null };
    // the registry
    try {
      if (!this.ready) { await ensure(this.db); this.ready = true; }
      for (let i = 0; i < D1_ROUNDS; i++) {
        const rows = core.batch(core.get("d1_seq"), D1_BATCH);
        if (!rows.length) break;
        await apply(this.db, rows.map((r) => r.event), { gapMinutes: this.cfg.gapMinutes });
        core.set("d1_seq", rows[rows.length - 1].seq);
        core.set("d1_last", now);
        out.applied += rows.length;
        if (rows.length < D1_BATCH) break;
        out.more = i === D1_ROUNDS - 1;
      }
    } catch (err) {
      console.error("ledger", "registry", err?.name || "Error", String(err?.message || "").slice(0, 200));
      core.bump("d1_failures");
      out.failed = true;
    }
    // the archive: the hours that are over
    let hourEnds = null;
    if (this.bucket) {
      try {
        for (let i = 0; i < 6; i++) {
          const step = await this.archive(now);
          out.archived += step.events;
          hourEnds = step.waiting;
          if (!step.events) break;
          out.more ||= i === 5;
        }
      } catch (err) {
        console.error("ledger", "archive", err?.name || "Error", String(err?.message || "").slice(0, 200));
        core.bump("r2_failures");
        out.failed = true;
      }
    }
    core.trim(this.bucket ? ["d1_seq", "r2_seq"] : ["d1_seq"]);
    // the days' sums, what the registry no longer keeps, and the archive's objects it has not heard of
    let sumsAt = null;
    if (!out.failed) {
      try {
        const unsynced = core.sql.exec("SELECT * FROM ledger_manifest WHERE synced = 0 ORDER BY written LIMIT 200").toArray();
        if (unsynced.length) {
          await syncManifest(this.db, unsynced.map((m) => ({ ...m, source: core.source })));
          for (const m of unsynced) core.sql.exec("UPDATE ledger_manifest SET synced = 1 WHERE key = ?", m.key);
        }
        // the days' sums: made again once events were applied since they last were, at most every ROLLUP_MS
        if (out.applied) core.set("rollup_due", 1);
        if (core.get("rollup_due") === 1) {
          if (now - core.get("rollup_last") >= ROLLUP_MS) {
            await rollup(this.db, {});
            core.set("rollup_last", now);
            core.set("rollup_due", 0);
          } else sumsAt = core.get("rollup_last") + ROLLUP_MS;
        }
        const today = usageDay(now, this.offset);
        const stamp = Number(today.replaceAll("-", ""));
        if (core.get("prune_day") !== stamp) {
          await prune(this.db, { today, eventDays: this.cfg.eventDays, keepDays: this.cfg.keepDays });
          core.set("prune_day", stamp);
        }
      } catch (err) {
        console.error("ledger", "upkeep", err?.name || "Error", String(err?.message || "").slice(0, 200));
        core.bump("d1_failures");
      }
    }
    // when next: later after a failure, at once while more wait, when the hour ends for what the archive waits on, when
    // the days' sums are due again, and when the minute's noise can be written
    const held = core.noise.size ? (Math.floor(now / 60000) + 1) * 60000 + 1000 : null; // the minute's noise, once the minute is over
    const wanted = [out.failed ? now + this.retry : null, !out.failed && out.more ? now + 1000 : null, hourEnds, sumsAt, held].filter((t) => t !== null);
    if (wanted.length) {
      out.next = Math.min(...wanted);
      this.armed = true;
      await sooner(this.storage, out.next);
    }
    return out;
  }

  /**
   * The oldest hour that is over, or a part of it, into the bucket: its lines (a visitor named by the day), an object
   * R2 checks the sha256 of, a row in the manifest, and the day's manifest written again.  → {events, waiting}:
   * waiting — when the hour the oldest row belongs to will be written (it is not over yet), else null.
   */
  async archive(now = Date.now()) {
    const core = this.core;
    const rows = core.batch(core.get("r2_seq"), PART);
    if (!rows.length) return { events: 0, waiting: null };
    const hour = Math.floor(rows[0].received / 3600000) * 3600000;
    if (hour + 3600000 + GRACE > now) return { events: 0, waiting: hour + 3600000 + GRACE };
    const mine = rows.filter((r) => r.received < hour + 3600000);
    const part = Number(core.sql.exec("SELECT COUNT(*) AS n FROM ledger_manifest WHERE hour = ?", hour).one().n);
    const lines = [];
    const types = {};
    const names = new Map();
    for (const { event } of mine) {
      const { visitor_id: visitor, ...rest } = event;
      if (visitor) {
        const at = `${visitor}|${event.day}`;
        if (!names.has(at)) names.set(at, await dayAlias(visitor, event.day, this.cfg.key));
        rest.visitor_day = names.get(at);
      }
      types[event.event_type] = (types[event.event_type] || 0) + 1;
      lines.push(JSON.stringify(canonical(rest)));
    }
    const prefix = ACTIVITY(core.source);
    const put = await putBatch(this.bucket, batchKey(prefix, hour, part), lines,
      { source: core.source, first_seq: String(mine[0].seq), last_seq: String(mine[mine.length - 1].seq), schema: String(SCHEMA_VERSION) });
    const day = new Date(hour).toISOString().slice(0, 10);
    core.sql.exec("INSERT INTO ledger_manifest (key, day, hour, part, events, bytes, sha256, first_seq, last_seq, types, written) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) " +
      "ON CONFLICT(key) DO UPDATE SET events = excluded.events, bytes = excluded.bytes, sha256 = excluded.sha256, first_seq = excluded.first_seq, " +
      "last_seq = excluded.last_seq, types = excluded.types, written = excluded.written, synced = 0",
    put.key, day, hour, part, put.events, put.bytes, put.sha256, mine[0].seq, mine[mine.length - 1].seq, JSON.stringify(types), now);
    core.set("r2_seq", mine[mine.length - 1].seq);
    core.set("r2_last", now);
    await this.manifest(day, now);
    return { events: mine.length, waiting: null };
  }

  /** A day's manifest: what its objects are, and what each must hash to.  Written again whenever the day gains one. */
  async manifest(day, now = Date.now()) {
    const core = this.core;
    const objects = core.sql.exec("SELECT key, hour, part, events, bytes, sha256, first_seq, last_seq, types FROM ledger_manifest WHERE day = ? ORDER BY hour, part", day)
      .toArray().map((o) => ({ key: o.key, hour: new Date(Number(o.hour)).toISOString().slice(11, 13), part: Number(o.part), events: Number(o.events),
        bytes: Number(o.bytes), sha256: o.sha256, first_seq: Number(o.first_seq), last_seq: Number(o.last_seq), types: parse(o.types, {}) }));
    const body = JSON.stringify(canonical({ v: SCHEMA_VERSION, source: core.source, day, written: new Date(now).toISOString(),
      events: objects.reduce((n, o) => n + o.events, 0), bytes: objects.reduce((n, o) => n + o.bytes, 0), objects }));
    const sha256 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)))].map((b) => b.toString(16).padStart(2, "0")).join("");
    await this.bucket.put(`${MANIFESTS(core.source)}${day.slice(0, 4)}/${day.slice(5, 7)}/${day.slice(8, 10)}.json`, body,
      { sha256, httpMetadata: { contentType: "application/json; charset=utf-8" } });
  }
}

/**
 * A day of an archive against its manifest, for the holder of the collector's token: every object the manifest names is
 * there, of the size and the sha256 it says (R2 keeps the one it checked on the way in), and nothing is there that it
 * does not name.  → {day, source, objects, events, bytes, missing, mismatched, unlisted, ok}; ok: null when the day has
 * no manifest (nothing was written that day, or its hours are not over).
 */
export async function verifyArchive(bucket, source, day) {
  const at = `${day.slice(0, 4)}/${day.slice(5, 7)}/${day.slice(8, 10)}`;
  const got = await bucket.get(`${MANIFESTS(source)}${at}.json`);
  const listed = await bucket.list({ prefix: `${ACTIVITY(source)}${at}/`, limit: 1000 });
  const there = new Map(listed.objects.map((o) => [o.key, o]));
  if (!got) return { day, source, objects: 0, events: 0, bytes: 0, missing: [], mismatched: [], unlisted: [...there.keys()], ok: there.size ? false : null };
  const manifest = parse(await got.text(), { objects: [] });
  const hexOf = (sum) => (sum ? [...new Uint8Array(sum)].map((b) => b.toString(16).padStart(2, "0")).join("") : null);
  const missing = [], mismatched = [];
  for (const o of manifest.objects || []) {
    const obj = there.get(o.key);
    there.delete(o.key);
    if (!obj) { missing.push(o.key); continue; }
    const sha = hexOf(obj.checksums?.sha256);
    if ((obj.size !== undefined && obj.size !== o.bytes) || (sha && sha !== o.sha256)) mismatched.push(o.key);
  }
  const unlisted = [...there.keys()];
  return { day, source, objects: (manifest.objects || []).length, events: manifest.events || 0, bytes: manifest.bytes || 0, missing, mismatched, unlisted,
    ok: !missing.length && !mismatched.length && !unlisted.length };
}
