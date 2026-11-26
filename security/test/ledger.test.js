// The activity ledger under Node: what an event keeps of a request (security/ledger.js), the outbox and the turns on an
// in-memory SQLite, the registry (security/ledger-d1.js) on a D1 of the same, the archive on a bucket in memory.
// Run: node --test security/test/

import assert from "node:assert/strict";
import test from "node:test";

import { ACTIVITY, MANIFESTS, readBatch } from "../archive.js";
import { classify, describe, envelope, EVENT_TYPES, LedgerCore, LedgerDrainer, SCHEMA_VERSION, ulid, verifyArchive } from "../ledger.js";
import { apply, ensure, forget, known, METRICS, prune, rollup, serveLedgerStats, stats, TABLES } from "../ledger-d1.js";
import { fingerprint } from "../sentinel.js";
import { dayAlias, ledgerConfig } from "../visitor.js";
import { alarmStorage, bucket, d1, sqlStore } from "./fakes.js";

const KEY = "activity-key-for-tests-0123456789abcdef";
const CFG = ledgerConfig({ ACTIVITY_KEY: KEY });
const T0 = Date.UTC(2026, 10, 25, 4, 0, 0); // noon in Beijing, 25 November
const MIN = 60000, HOUR = 3600000, DAY = 86400000;
const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36";
const WECHAT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50 NetType/WIFI Language/zh_CN";
const V = (n) => `v_${String(n).padStart(24, "0")}`;
const TURN = { turnMs: 7 * DAY, keep: 0, offset: 8 };

/** A request as the sentinel reads it. */
const fpOf = (over = {}) => ({ ts: new Date(T0).toISOString(), method: "GET", host: "chat.impf.ai", path: "/", ip: "203.0.113.9", asn: 4134, country: "CN", region: "GD",
  proto: "HTTP/2", tls: "TLSv1.3", ua: CHROME, uaClass: "browser", lang: "zh-CN,zh;q=0.9", ...over });
/** An event of a visitor's request. */
const ev = (type, { visitor = null, at = T0, source = "site", route = "/", fp = {}, more = {}, ...rest } = {}) =>
  envelope({ type, source, fp: fpOf(fp), visitor, now: at, route, status: 200, more, ...rest });
const pageView = (visitor, at, more = {}) => ev("page_view", { visitor, at, more });
async function registry(events, db = d1()) {
  await ensure(db);
  await apply(db, events);
  await rollup(db);
  return db;
}
const metric = (db, day, name) => db.rows("SELECT k1, k2, value FROM daily_metrics WHERE day = ? AND metric = ? ORDER BY k1, k2", day, name).map((r) => [r.k1, r.k2, r.value]);

// ------------------------------------------------------------------ what is read of a request
test("an event keeps four words of a browser and nothing that tells one visitor from the next", () => {
  const request = new Request("https://chat.impf.ai/?utm=1&q=secret", { headers: { "User-Agent": CHROME, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "CF-Connecting-IP": "203.0.113.9", "Sec-CH-UA": '"Chromium";v="129"', Referer: "https://www.baidu.com/s?wd=secret" } });
  request.cf = { asn: 4134, asOrganization: "Chinanet", country: "CN", regionCode: "GD", city: "Shenzhen", colo: "SJC", httpProtocol: "HTTP/2", tlsVersion: "TLSv1.3",
    tlsCipher: "AEAD-AES128-GCM-SHA256", tlsClientExtensionsSha1: "abc", clientTcpRtt: 180 };
  const fp = fingerprint(request, T0);
  const e = envelope({ type: "page_view", source: "site", fp, visitor: V(1), now: T0, route: "/", status: 200, latency: 12.4 });
  assert.deepEqual(Object.keys(e).sort(), ["asn", "browser_family", "country", "day", "device_type", "event_id", "event_type", "host", "http_protocol", "language",
    "latency_ms", "method", "n", "os_family", "region", "risk_score", "route", "schema_version", "security_action", "source", "status", "timestamp", "tls_version",
    "traffic_class", "visitor_id"]);
  assert.deepEqual({ b: e.browser_family, o: e.os_family, d: e.device_type, l: e.language, c: e.country, r: e.region, a: e.asn, p: e.http_protocol, t: e.tls_version },
    { b: "Chrome", o: "Windows", d: "desktop", l: "zh-CN", c: "CN", r: "GD", a: 4134, p: "HTTP/2", t: "TLSv1.3" });
  assert.deepEqual([e.traffic_class, e.risk_score, e.security_action, e.visitor_id, e.day, e.latency_ms, e.schema_version], ["human", 0, "none", V(1), "2026-11-25", 12, SCHEMA_VERSION]);
  assert.match(e.event_id, /^evt_[0-9A-Z]{26}$/);
  // not the address, the agent, the city, the handshake, the query or the page it came from in full
  const text = JSON.stringify(e);
  for (const kept of ["203.0.113", "Mozilla", "Shenzhen", "Chinanet", "AES128", "abc", "secret", "utm", "129"]) assert.ok(!text.includes(kept), kept);
});

test("a browser by its family, system and kind; what is not a browser has none", () => {
  const of = (ua, extra = {}) => describe({ ua, uaClass: "browser", ...extra });
  assert.deepEqual(of(WECHAT, { lang: "zh-CN" }), { browser_family: "WeChat", os_family: "iOS", device_type: "mobile", language: "zh-CN" });
  assert.deepEqual(of("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15", { lang: "en-us,en;q=0.5" }),
    { browser_family: "Safari", os_family: "macOS", device_type: "desktop", language: "en-US" });
  assert.deepEqual(of("Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", { lang: "zh-hant-tw" }),
    { browser_family: "Chrome", os_family: "Android", device_type: "tablet", language: "zh-Hant" });
  assert.equal(of("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 EdgA/126.0").browser_family, "Edge");
  assert.equal(of("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0").os_family, "Linux");
  assert.equal(of(CHROME, { chMobile: "?1" }).device_type, "mobile");
  assert.equal(of(CHROME, { lang: "*" }).language, null);
  assert.deepEqual(describe({ ua: "curl/8.5", uaClass: "tool", lang: "en" }), { browser_family: null, os_family: null, device_type: null, language: null });
});

test("what the sentinel made of a request, in three words; a visitor's id only for a visitor", () => {
  const browser = fpOf();
  assert.deepEqual(classify(browser, { score: 0 }), { traffic_class: "human", risk_score: 0, security_action: "none" });
  assert.deepEqual(classify(browser, { score: 2 }, null, { status: 429 }), { traffic_class: "human", risk_score: 2, security_action: "rate_limited" });
  assert.deepEqual(classify(browser, { score: 6 }), { traffic_class: "suspect", risk_score: 6, security_action: "flagged" });
  assert.deepEqual(classify(browser, { score: 12 }, { score: 12, blocked: true, flagged: true }), { traffic_class: "suspect", risk_score: 12, security_action: "blocked" });
  assert.deepEqual(classify(browser, { score: 3, route: "honeypot" }), { traffic_class: "suspect", risk_score: 3, security_action: "honeypot" });
  assert.equal(classify(fpOf({ uaClass: "tool" }), { score: 3 }).traffic_class, "automation");
  assert.equal(classify(fpOf({ uaClass: "bot" }), { score: 0 }).traffic_class, "crawler");
  assert.equal(classify(fpOf({ uaClass: "other" }), { score: 1, own: true }).traffic_class, "own");
  assert.equal(classify(fpOf(), { score: 4 }, null, { flagScore: 3 }).security_action, "flagged");
  // a flagged browser's events are counted, and for no visitor; another site's page: its country, and nothing else of who
  assert.equal(envelope({ type: "request", source: "site", fp: browser, a: { score: 9 }, visitor: V(1), now: T0 }).visitor_id, null);
  const led = envelope({ type: "request", source: "site", fp: browser, led: "https://forum.example", visitor: V(1), now: T0, status: 403 });
  assert.deepEqual([led.traffic_class, led.security_action, led.visitor_id, led.country, led.asn, led.browser_family, led.region, led.language],
    ["cross_site", "cross_site", null, "CN", undefined, undefined, undefined, undefined]);
});

test("an id sorts by the time it was made", () => {
  const a = ulid(T0), b = ulid(T0 + 1), c = ulid(T0 + 1);
  assert.match(a, /^[0-9A-HJKMNP-TV-Z]{26}$/);
  assert.ok(a < b);
  assert.notEqual(b, c);
  assert.equal(b.slice(0, 10), c.slice(0, 10));
});

// ------------------------------------------------------------------ the outbox
test("an event is written once however often it is brought; a full outbox drops, and says how much", () => {
  const core = new LedgerCore(sqlStore(), "site");
  const e = pageView(V(1), T0);
  assert.deepEqual(core.append([e, e, pageView(V(2), T0)], T0), { appended: 2, dropped: 0, duplicates: 1 });
  assert.deepEqual(core.append([e], T0 + 5), { appended: 0, dropped: 0, duplicates: 1 });
  assert.deepEqual(core.append([{ event_type: "nonsense" }, null, "x", { no: "type" }], T0), { appended: 0, dropped: 0, duplicates: 0 });
  assert.equal(core.waiting(), 2);
  const kept = core.batch(0, 10);
  assert.deepEqual(kept.map((r) => [r.event.event_id === e.event_id, r.event.source]), [[true, "site"], [false, "site"]]);
  assert.ok(kept[0].seq < kept[1].seq); // in the order they came (a number an ignored writing took is not given again)
  assert.deepEqual(core.append([pageView(V(3), T0), pageView(V(4), T0)], T0, 3, 7), { appended: 1, dropped: 1, duplicates: 0 });
  const h = core.health(T0 + 30000);
  assert.deepEqual([h.source, h.waiting, h.appended, h.dropped, h.duplicates, h.lost, h.oldest_seconds], ["site", 3, 3, 1, 2, 7, 30]);
});

test("what is not a visitor's is added up by the minute; a visitor's event is its own line", () => {
  const core = new LedgerCore(sqlStore(), "relay");
  const probe = (at, status = 404) => envelope({ type: "request", source: "relay", fp: fpOf({ uaClass: "tool", ua: "curl/8" }), a: { score: 3 }, now: at, route: "other", status });
  for (let i = 0; i < 40; i++) core.note(probe(T0 + i * 1000), T0 + i * 1000);
  core.note(probe(T0 + 5000, 405), T0 + 5000);
  core.note(envelope({ type: "request", source: "relay", fp: fpOf(), a: { score: 0 }, now: T0, route: "other", status: 404 }), T0); // a person's mistyped address
  assert.equal(core.waiting(), 1);
  core.flush(T0 + 30000); // the minute is not over
  assert.equal(core.waiting(), 1);
  core.flush(T0 + MIN + 1);
  const lines = core.batch(0, 10).map((r) => [r.event.traffic_class, r.event.status, r.event.n]);
  assert.deepEqual(lines, [["human", 404, 1], ["automation", 404, 40], ["automation", 405, 1]]);
});

// ------------------------------------------------------------------ a turn is one question
test("a turn is one question however many calls it takes, and every call is a model call", () => {
  const core = new LedgerCore(sqlStore(), "relay");
  const base = ev("request", { visitor: V(1), source: "relay", route: "/v1/chat/completions", more: { provider: "impf", model: "Tao-R1" } });
  const named = { key: "tabc", explicit: true, turn: true };
  const first = core.call(base, named, T0, TURN);
  assert.equal(first.question, true);
  // its tool rounds, the self-check's rewrite, an answer written on, the page asking again: the same turn
  const more = [core.call(base, { ...named, turn: false }, T0 + 1000, TURN), core.call(base, named, T0 + 2000, TURN), core.call(base, named, T0 + 3000, TURN)];
  assert.deepEqual(more.map((m) => [m.question, m.turn_id === first.turn_id]), [[false, true], [false, true], [false, true]]);
  assert.equal(new Set([first, ...more].map((m) => m.invocation_id)).size, 4);
  const types = core.batch(0, 20).map((r) => r.event.event_type);
  assert.deepEqual(types, ["question_submitted", "model_invocation", "model_invocation", "model_invocation", "model_invocation"]);
  const q = core.batch(0, 1)[0].event;
  assert.deepEqual([q.basis, q.named, q.provider, q.model, q.visitor_id, q.turn_id], ["relay", true, "impf", "Tao-R1", V(1), first.turn_id]);
  assert.ok(!JSON.stringify(core.batch(0, 20)).includes("tabc")); // the page's name of the turn is in no event
  // another turn is another question; a turn forgotten is new again
  assert.equal(core.call(base, { key: "tdef", explicit: true }, T0, TURN).question, true);
  assert.equal(core.call(base, named, T0 + 8 * DAY, TURN).question, true);
});

test("a page that does not name its turns: a call that ends with what a visitor asked is a question, a tool round is not", () => {
  const core = new LedgerCore(sqlStore(), "relay");
  const base = ev("request", { source: "relay", route: "/v1/chat/completions" });
  assert.equal(core.call(base, { key: "qaaa", explicit: false, turn: true }, T0, TURN).question, true);
  assert.equal(core.call(base, { key: "qaaa", explicit: false, turn: false }, T0 + 1, TURN).question, false);
  assert.equal(core.call(base, { key: "qaaa", explicit: false, turn: true }, T0 + 2, TURN).question, false); // asked again after a failure
  const lone = core.call(base, { key: "qbbb", explicit: false, turn: false }, T0 + 3, TURN); // a turn taken up again, its question before the ledger
  assert.equal(lone.question, false);
  assert.match(lone.turn_id, /^trn_/);
});

test("a question asked of one's own model is counted on the page's word; a record archives its turn, and counts one the ledger never heard of", () => {
  const core = new LedgerCore(sqlStore(), "relay");
  const base = ev("request", { visitor: V(2), source: "relay", route: "/v1/activity" });
  const info = { provider: "deepseek", model: "deepseek-chat", execution_status: "done", rounds: 3, tool_count: 5, tools: { "classics.search": 4, "study.formula": 1 },
    input_tokens: 9000, output_tokens: 800, duration_ms: 42000, runtime: "browser", corpus: "canon", module: "chat", turn_index: 2, content_consent: false };
  const own = core.finished(base, "town", info, T0, TURN);
  assert.equal(own.question, true);
  assert.equal(core.finished(base, "town", { ...info, rounds: 4 }, T0 + 5000, TURN).question, false); // taken up again: its end told again
  // the relay's own turn: its question was counted with its first call, the page's word adds how it ended
  const mine = core.call({ ...base, provider: "impf", model: "Tao-R1" }, { key: "trelay", explicit: true }, T0, TURN);
  assert.equal(core.finished(base, "trelay", { ...info, provider: "impf", model: "Tao-R1" }, T0 + 9000, TURN).question, false);
  // records: of the relay's turn (archived, once), and of a turn only its record tells of
  const anon = ev("request", { source: "relay", route: "/v1/logs" });
  assert.deepEqual(core.recorded(anon, "trelay", { execution_status: "done" }, T0 + 9500, TURN), { turn_id: mine.turn_id, question: false, archived: true });
  assert.deepEqual(core.recorded(anon, "trelay", { execution_status: "done" }, T0 + 9900, TURN), { turn_id: mine.turn_id, question: false, archived: false });
  const old = core.recorded(anon, "told", { provider: "openai", model: "gpt-x", execution_status: "done", rounds: 2 }, T0 + 9999, TURN);
  assert.deepEqual([old.question, old.archived], [true, true]);
  const events = core.batch(0, 50).map((r) => r.event);
  const questions = events.filter((e) => e.event_type === "question_submitted").map((e) => [e.basis, e.provider, e.visitor_id]);
  assert.deepEqual(questions, [["client", "deepseek", V(2)], ["relay", "impf", V(2)], ["record", "openai", null]]);
  assert.equal(events.filter((e) => e.event_type === "turn_finished").length, 3);
  assert.equal(events.filter((e) => e.event_type === "record_archived").length, 2);
  assert.ok(events.every((e) => EVENT_TYPES.includes(e.event_type)));
});

// ------------------------------------------------------------------ the registry
/** Three visitors over a fortnight: a(1) every day of the first week and once in the second, b(2) on two days, c(3) once
 * — and an id (4) given to what opened a page and never brought it back, and pages opened by browsers without an id. */
function fortnight() {
  const events = [];
  const day = (n, h = 4) => T0 - 13 * DAY + n * DAY + (h - 4) * HOUR; // n = 0 … 13; the 14th day is T0's
  for (let n = 0; n < 7; n++) events.push(pageView(V(1), day(n), n === 0 ? { new_visitor: true, referrer: "https://www.baidu.com" } : {}));
  events.push(pageView(V(1), day(10)));
  events.push(pageView(V(2), day(2), { new_visitor: true }), ev("page_ready", { visitor: V(2), at: day(2) + 2000, more: { detail: "en" } }), pageView(V(2), day(9)));
  const sg = { country: "SG", region: "", ua: WECHAT, lang: "en-SG" };
  events.push(ev("page_view", { visitor: V(3), at: day(13), fp: sg, more: { new_visitor: true } }), ev("page_ready", { visitor: V(3), at: day(13) + 1500, fp: sg, more: { detail: "en" } }));
  events.push(pageView(V(4), day(13) + 5 * MIN, { new_visitor: true }));
  for (let i = 0; i < 4; i++) events.push(pageView(null, day(13) + i * MIN));
  return { events, day };
}

test("the registry: a visitor's first and last day, their days, and a visit that a silence ends", async () => {
  const { events, day } = fortnight();
  // b's second day: a page, three reads a minute later (one line), then nothing for an hour, then a question
  const read = ev("api_read", { visitor: V(2), at: day(9) + MIN, route: "/api/passage", n: 3 });
  const asked = ev("question_submitted", { visitor: V(2), at: day(9) + 70 * MIN, source: "relay", route: "/v1/chat/completions",
    more: { turn_id: "trn_B1", basis: "relay", provider: "impf", model: "Tao-R1" } });
  const db = await registry([...events, read, asked]);
  assert.deepEqual(db.rows("SELECT visitor_id, first_day, last_day, first_referrer, country, confirmed FROM visitors ORDER BY visitor_id"), [
    { visitor_id: V(1), first_day: "2026-11-12", last_day: "2026-11-22", first_referrer: "https://www.baidu.com", country: "CN", confirmed: 1 },
    { visitor_id: V(2), first_day: "2026-11-14", last_day: "2026-11-21", first_referrer: null, country: "CN", confirmed: 1 },
    { visitor_id: V(3), first_day: "2026-11-25", last_day: "2026-11-25", first_referrer: null, country: "SG", confirmed: 1 },
    { visitor_id: V(4), first_day: "2026-11-25", last_day: "2026-11-25", first_referrer: null, country: "CN", confirmed: 0 }, // seen once, with the id it was just given
  ]);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM visitor_daily_activity")[0].n, 8 + 2 + 1 + 1);
  assert.deepEqual(db.rows("SELECT events, page_views, questions, sessions FROM visitor_daily_activity WHERE visitor_id = ? AND day = '2026-11-21'", V(2)),
    [{ events: 5, page_views: 1, questions: 1, sessions: 2 }]);
  const visits = db.rows("SELECT session_id, duration_s, events, page_views, questions, entry FROM sessions WHERE visitor_id = ? AND day = '2026-11-21' ORDER BY started", V(2));
  assert.deepEqual(visits.map(({ session_id, ...v }) => v), [{ duration_s: 60, events: 4, page_views: 1, questions: 0, entry: "/" },
    { duration_s: 0, events: 1, page_views: 0, questions: 1, entry: "/v1/chat/completions" }]);
  assert.match(visits[0].session_id, /^ses_0{23}2_\d+$/);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM activity_events WHERE visitor_id IS NULL")[0].n, 4);
});

test("a batch written twice, or in another order, leaves the registry as it was", async () => {
  const { events, day } = fortnight();
  const core = new LedgerCore(sqlStore(), "relay");
  const base = ev("request", { visitor: V(1), at: day(3), source: "relay", route: "/v1/chat/completions", more: { provider: "impf", model: "Tao-R1" } });
  const c1 = core.call(base, { key: "t1", explicit: true }, day(3), TURN);
  const c2 = core.call(base, { key: "t1", explicit: true }, day(3) + 4000, TURN);
  core.settle({ invocation_id: c1.invocation_id, turn_id: c1.turn_id, execution_status: "ok", http_status: 200, input_tokens: 4000, output_tokens: 300, asks: 2, latency_ms: 900 }, day(3) + 3000, TURN);
  core.settle({ invocation_id: c2.invocation_id, turn_id: c2.turn_id, execution_status: "ok", http_status: 200, input_tokens: 6000, output_tokens: 500, asks: 1 }, day(3) + 9000, TURN);
  core.finished(base, "t1", { execution_status: "done", rounds: 2, tool_count: 2, tools: { "classics.search": 2 }, input_tokens: 1, output_tokens: 1, module: "chat", content_consent: true }, day(3) + 9500, TURN);
  core.recorded(ev("request", { source: "relay", at: day(3) }), "t1", { execution_status: "done" }, day(3) + 9900, TURN);
  const relay = core.batch(0, 50).map((r) => r.event);
  const dump = (db) => JSON.stringify(["visitors", "visitor_daily_activity", "sessions", "activity_events", "question_events", "model_invocations"]
    .map((t) => db.rows(`SELECT * FROM ${t} ORDER BY 1, 2`)));
  const once = await registry([...events, ...relay]);
  const twice = d1();
  await ensure(twice);
  await apply(twice, relay.slice(0, 3)); // the relay's outbox first, in parts
  await apply(twice, events);
  await apply(twice, relay.slice(3));
  await apply(twice, relay); // all of it again, after a failure that was none
  await apply(twice, events.slice(0, 5));
  assert.equal(dump(twice), dump(once));
  const q = once.rows("SELECT * FROM question_events")[0];
  // the tokens are the relay's own count of the turn's calls, not the page's
  assert.deepEqual([q.basis, q.calls, q.input_tokens, q.output_tokens, q.rounds, q.tool_count, q.tools, q.module, q.content_consent, q.archive_status, q.execution_status],
    ["relay", 2, 10000, 800, 2, 2, '{"classics.search":2}', "chat", 1, "archived", "done"]);
  assert.deepEqual(once.rows("SELECT execution_status, asks, input_tokens, latency_ms FROM model_invocations ORDER BY ts"),
    [{ execution_status: "ok", asks: 2, input_tokens: 4000, latency_ms: 900 }, { execution_status: "ok", asks: 1, input_tokens: 6000, latency_ms: null }]);
});

test("the visitors of a stretch are the union of its days', never their sum; who came back; the week and the month", async () => {
  const { events } = fortnight();
  const db = await registry(events);
  const all = await stats(db, { from: null, to: "2026-11-25" });
  assert.equal(all.first_day, "2026-11-12");
  assert.equal(all.days.length, 14);
  assert.deepEqual(all.daily.active, [1, 1, 2, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1]);
  assert.equal(all.daily.active.reduce((a, b) => a + b), 11); // what adding the days up would say
  assert.equal(all.totals.visitors, 3);                       // what there were
  assert.equal(all.lifetime.visitors, 3);
  assert.equal(all.totals.returning_visitors, 2);  // a and b came on more than one day
  assert.equal(all.totals.new_visitors, 3);
  assert.equal(all.totals.page_views, 16);
  assert.equal(all.coverage.page_views_identified, 12);
  // the id that never came back is a page opened, and no visitor
  assert.deepEqual([all.lifetime.unconfirmed, all.coverage.unconfirmed], [1, 1]);
  assert.equal(all.daily.active_7.at(-1), 3);   // the last seven days: a (the 22nd), b (the 21st), c
  assert.equal(all.daily.active_7[6], 2);       // the first seven: a and b
  assert.equal(all.daily.active_30.at(-1), 3);
  // the second week alone: a and b are back (they first came before it), c is new
  const week = await stats(db, { from: "2026-11-19", to: "2026-11-25" });
  assert.deepEqual([week.totals.visitors, week.totals.new_visitors, week.totals.returning_visitors, week.days.length], [3, 1, 2, 7]);
  assert.deepEqual(week.places.map((p) => [p.country, p.region, p.visitors, p.page_views]), [["CN", "GD", 2, 7], ["SG", "", 1, 1]]);
  assert.equal(week.totals.countries, 2);
  // a place with fewer visitors than the least is not named
  const folded = await stats(db, { from: "2026-11-19", to: "2026-11-25", minCell: 2 });
  assert.deepEqual(folded.places.map((p) => [p.country, p.visitors, p.folded]), [["CN", 2, undefined], ["", 1, 1]]);
  // retention: of the week of the 9th's two new visitors both were back the week after; the day after their first, one of the two that could be
  assert.deepEqual(all.retention.weekly.map((c) => [c.week, c.size, c.back]), [["2026-11-09", 2, [2]], ["2026-11-23", 1, []]]);
  assert.deepEqual(all.retention.d1, { cohort: 2, back: 1 });
  assert.deepEqual(all.retention.d7, { cohort: 2, back: 1 }); // b came back on its seventh day
  assert.deepEqual(all.audience.browsers, [["Chrome", 15], ["WeChat", 1]]);
  assert.deepEqual(all.audience.referrers, [["https://www.baidu.com", 1]]);
  assert.deepEqual(all.features.ui_languages, [["en", 2]]);
  assert.equal(all.coverage.page_ready, 2);
});

test("questions recorded and not, whoever answered; model calls and what they cost", async () => {
  const core = new LedgerCore(sqlStore(), "relay");
  const base = (v) => ev("request", { visitor: v, source: "relay", route: "/v1/chat/completions", more: { provider: "impf", model: "Tao-R1" } });
  const note = ev("request", { source: "relay", route: "/v1/logs" });
  // five questions of the default service: two recorded; one refused by the day's limit before any call
  for (let i = 0; i < 5; i++) {
    const c = core.call(base(V(1 + (i % 2))), { key: `t${i}`, explicit: true }, T0 + i * MIN, TURN);
    core.call(base(V(1 + (i % 2))), { key: `t${i}`, explicit: true }, T0 + i * MIN + 5000, TURN);
    core.settle({ invocation_id: c.invocation_id, turn_id: c.turn_id, execution_status: "ok", input_tokens: 1000, output_tokens: 100, asks: i === 0 ? 3 : 1 }, T0 + i * MIN + 9000, TURN);
    if (i < 2) core.recorded(note, `t${i}`, {}, T0 + i * MIN + 9999, TURN);
  }
  core.append([ev("model_refused", { visitor: V(2), source: "relay", route: "/v1/chat/completions", status: 429, more: { detail: "day" } })], T0);
  // three of a visitor's own model, one of them recorded; one the page answered itself
  for (let i = 0; i < 3; i++) {
    core.finished(base(V(3)), `own${i}`, { provider: "deepseek", model: "deepseek-chat", execution_status: i === 2 ? "error" : "done", rounds: 4, tool_count: 2,
      tools: { "classics.search": 2 }, input_tokens: 5000, output_tokens: 400, module: i === 1 ? "diet" : "chat", runtime: "browser", corpus: "canon", content_consent: i === 0 }, T0 + i * MIN, TURN);
  }
  core.recorded(note, "own0", {}, T0 + 9000, TURN);
  core.finished(base(null), "fixed", { provider: "fixed", execution_status: "done", rounds: 0, module: "chat" }, T0, TURN);
  const db = await registry(core.batch(0, 200).map((r) => r.event));
  const s = await stats(db, { from: "2026-11-25", to: "2026-11-25" });
  assert.deepEqual([s.totals.questions, s.totals.questions_archived, s.totals.questions_unarchived], [9, 3, 6]);
  assert.deepEqual(s.questions.by_basis, [["relay", 5], ["client", 4]]);
  assert.deepEqual(s.coverage.questions_relay + s.coverage.questions_client + s.coverage.questions_record, 9);
  assert.deepEqual(s.questions.by_model, [["impf", "Tao-R1", 5], ["deepseek", "deepseek-chat", 3], ["fixed", "", 1]]);
  assert.deepEqual(s.questions.by_module, [["chat", 3], ["", 5], ["diet", 1]].sort((a, b) => b[1] - a[1]));
  assert.deepEqual(s.questions.by_status, [["", 5], ["done", 3], ["error", 1]]);
  assert.deepEqual(s.questions.refusals, [["day", 1]]);
  // model calls: ten the relay let through, twelve the pages say their own models took
  assert.deepEqual([s.totals.model_calls_relay, s.totals.model_calls_reported, s.totals.model_calls], [10, 12, 22]);
  assert.deepEqual(s.models.outcomes, [["ok", 5], ["open", 5]]);
  assert.equal(s.models.asks, 12); // one call was asked of the model service three times
  assert.deepEqual([s.totals.tokens_in, s.totals.tokens_out, s.totals.tool_calls], [5000 + 15000, 500 + 1200, 6]);
  assert.deepEqual(s.features.tools, [["classics.search", 6]]);
  assert.deepEqual(s.features.runtimes, [["browser", "canon", 3]]);
  assert.deepEqual(metric(db, "2026-11-25", "askers"), [["", "", 3]]);
  assert.deepEqual(metric(db, "2026-11-25", "questions"), [["client", "archived", 1], ["client", "not_archived", 3], ["relay", "archived", 2], ["relay", "not_archived", 3]]);
});

test("a day's sums are made again when its rows change, and a group that is gone does not stay", async () => {
  const core = new LedgerCore(sqlStore(), "relay");
  const base = ev("request", { visitor: V(1), at: T0 - DAY, source: "relay", more: { provider: "impf", model: "Tao-R1" } });
  core.call(base, { key: "t1", explicit: true }, T0 - DAY, TURN);
  const db = await registry(core.batch(0, 10).map((r) => r.event));
  assert.deepEqual(metric(db, "2026-11-24", "questions"), [["relay", "not_archived", 1]]);
  assert.deepEqual(db.rows("SELECT * FROM ledger_dirty"), []);
  // its record comes the day after: the sums of the day the question was asked on are what changes
  core.recorded(ev("request", { source: "relay" }), "t1", {}, T0, TURN);
  await apply(db, core.batch(2, 10).map((r) => r.event));
  assert.deepEqual(db.rows("SELECT day FROM ledger_dirty"), [{ day: "2026-11-24" }]);
  assert.deepEqual(await rollup(db), ["2026-11-24"]);
  assert.deepEqual(metric(db, "2026-11-24", "questions"), [["relay", "archived", 1]]);
  assert.deepEqual(await rollup(db), []);
  assert.ok(Object.keys(METRICS).length > 30);
});

test("an id is a visitor once a browser brings it back, and the day it was first seen on is summed again", async () => {
  const db = await registry([pageView(V(1), T0 - DAY, { new_visitor: true })]);
  assert.deepEqual([metric(db, "2026-11-24", "active"), metric(db, "2026-11-24", "unconfirmed")], [[["", "", 0]], [["", "", 1]]]);
  assert.equal((await stats(db, { from: null, to: "2026-11-25" })).totals.visitors, 0);
  await apply(db, [pageView(V(1), T0)]); // the next day, with its cookie
  await rollup(db);
  assert.deepEqual([metric(db, "2026-11-24", "active"), metric(db, "2026-11-24", "unconfirmed"), metric(db, "2026-11-24", "new_visitors")],
    [[["", "", 1]], [["", "", 0]], [["CN", "GD", 1]]]);
  const s = await stats(db, { from: null, to: "2026-11-25" });
  assert.deepEqual([s.totals.visitors, s.totals.returning_visitors, s.daily.active], [1, 1, [1, 1]]);
});

// ------------------------------------------------------------------ what is no longer kept
test("a visitor forgotten: their rows go, the counts of what happened stay, and nothing of theirs is written again", async () => {
  const { events } = fortnight();
  const question = ev("question_submitted", { visitor: V(1), at: T0 - 13 * DAY, source: "relay", more: { turn_id: "trn_A", basis: "relay", provider: "impf" } });
  const db = await registry([...events, question]);
  assert.deepEqual(await known(db, V(1)), { first_day: "2026-11-12", last_day: "2026-11-22", days: 8, page_views: 8, questions: 1 });
  const before = await stats(db, { from: null, to: "2026-11-25" });
  const gone = await forget(db, V(1), { by: "self", now: T0 });
  assert.equal(gone.found, true);
  assert.deepEqual(gone.rows, { visitors: 1, visitor_daily_activity: 8, sessions: 8, activity_events: 9, question_events: 1, model_invocations: 0 });
  for (const t of ["visitors", "visitor_daily_activity", "sessions", "activity_events", "question_events"]) {
    assert.equal(db.rows(`SELECT COUNT(*) AS n FROM ${t} WHERE visitor_id = ?`, V(1))[0].n, 0, t);
  }
  assert.equal(await known(db, V(1)), null);
  await rollup(db);
  const after = await stats(db, { from: null, to: "2026-11-25" });
  assert.equal(after.totals.page_views, before.totals.page_views); // what happened, happened
  assert.equal(after.totals.questions, 1);
  assert.equal(after.totals.visitors, 2);
  assert.deepEqual(after.lifetime, { visitors: 3, unconfirmed: 1, removed: 1 }); // there were three visitors, of whom one asked to be forgotten
  const log = db.rows("SELECT what, by, rows FROM deletion_log");
  assert.deepEqual([log.length, log[0].what, log[0].by], [1, "visitor", "self"]);
  assert.ok(!JSON.stringify(log).includes(V(1))); // the deletion is written down without the id
  // an event of theirs that was still on its way
  await apply(db, [pageView(V(1), T0)]);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM visitors WHERE visitor_id = ?", V(1))[0].n, 0);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM activity_events WHERE visitor_id = ?", V(1))[0].n, 0);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM activity_events")[0].n, 20); // it is written, as no one's
  assert.deepEqual(await forget(db, "not-an-id"), { found: false, rows: {} });
  assert.equal((await forget(db, V(9), { by: "owner" })).found, false);
});

test("retention: the events go after their days, a visitor after theirs; the days' sums and the count of visitors stay", async () => {
  const { events } = fortnight();
  const db = await registry(events);
  const out = await prune(db, { today: "2026-11-25", eventDays: 5, keepDays: 10 }); // before the 20th; before the 15th
  assert.deepEqual(out, { visitors: 0, events_before: "2026-11-20", visitors_before: "2026-11-15" });
  assert.deepEqual(db.rows("SELECT MIN(day) AS first FROM activity_events"), [{ first: "2026-11-21" }]);
  assert.deepEqual(db.rows("SELECT MIN(day) AS first FROM visitor_daily_activity"), [{ first: "2026-11-15" }]);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM visitors")[0].n, 4);
  const later = await prune(db, { today: "2026-12-03", eventDays: 5, keepDays: 10 }); // before the 23rd: a and b were last seen earlier
  assert.equal(later.visitors, 2);
  assert.deepEqual(db.rows("SELECT visitor_id FROM visitors ORDER BY 1"), [{ visitor_id: V(3) }, { visitor_id: V(4) }]);
  const s = await stats(db, { from: null, to: "2026-11-25" });
  assert.equal(s.totals.page_views, 16); // the days' sums are kept for good
  assert.deepEqual(s.daily.active.slice(0, 3), [1, 1, 2]);
  assert.deepEqual(s.lifetime, { visitors: 3, unconfirmed: 1, removed: 2 });
  assert.deepEqual(db.rows("SELECT what, by FROM deletion_log"), [{ what: "retention", by: "schedule" }]);
});

// ------------------------------------------------------------------ the drain
function drainer({ db = d1(), r2 = null, cfg = CFG } = {}) {
  const core = new LedgerCore(sqlStore(), "site");
  const storage = alarmStorage();
  return { core, storage, db, r2, drain: new LedgerDrainer(storage, core, { db, bucket: r2, cfg, offset: 8 }) };
}

test("the outbox is drained into the registry a moment after it is written, and a row goes once it is there", async () => {
  const { core, storage, db, drain } = drainer();
  core.append([pageView(V(1), T0), pageView(V(2), T0 + 1000)], T0 + 1000);
  await drain.arm(T0 + 1000);
  await drain.arm(T0 + 5000); // armed once
  assert.deepEqual(storage.sets, [T0 + 21000]);
  const out = await drain.run(T0 + 21000);
  assert.deepEqual([out.applied, out.failed, out.more, out.next], [2, false, false, null]);
  assert.equal(core.waiting(), 0);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM visitors")[0].n, 2);
  assert.deepEqual(metric(db, "2026-11-25", "active"), [["", "", 2]]); // the day's sums were made with it
  // more within five minutes: applied, and the sums asked for when they are due
  core.append([pageView(V(3), T0 + 60000)], T0 + 60000);
  const again = await drain.run(T0 + 80000);
  assert.deepEqual([again.applied, again.next], [1, T0 + 21000 + 300000]);
  assert.deepEqual(metric(db, "2026-11-25", "active"), [["", "", 2]]);
  await drain.run(T0 + 21000 + 300000);
  assert.deepEqual(metric(db, "2026-11-25", "active"), [["", "", 3]]);
  const h = core.health(T0 + 400000);
  assert.deepEqual([h.waiting, h.appended, h.d1_seq, h.d1_failures ?? 0], [0, 3, 3, 0]);
});

test("a registry out of reach keeps the rows and is tried again; no ledger without one", async () => {
  let down = true;
  const db = d1({ fail: (sql) => down && /INSERT OR IGNORE INTO activity_events/.test(sql) });
  const { core, storage, drain } = drainer({ db });
  core.append([pageView(V(1), T0)], T0);
  const errors = console.error;
  console.error = () => {};
  let out;
  try { out = await drain.run(T0 + 20000); } finally { console.error = errors; }
  assert.deepEqual([out.applied, out.failed, out.next], [0, true, T0 + 20000 + 300000]);
  assert.equal(core.waiting(), 1);
  assert.equal(core.get("d1_failures"), 1);
  assert.equal(db.rows("SELECT COUNT(*) AS n FROM activity_events")[0].n, 0); // a batch is all or nothing
  assert.equal(storage.at, T0 + 320000);
  down = false;
  assert.equal((await drain.run(T0 + 320000)).applied, 1);
  assert.equal(core.waiting(), 0);
  const none = drainer({ db: null });
  none.core.append([pageView(V(1), T0)], T0);
  await none.drain.arm(T0);
  assert.equal(await none.drain.run(T0), null);
  assert.deepEqual(none.storage.sets, []);
});

test("the archive: an hour an object once the hour is over, a visitor named by the day, a manifest that says what each must hash to", async () => {
  const r2 = bucket();
  const { core, storage, db, drain } = drainer({ r2 });
  const h0 = Math.floor(T0 / HOUR) * HOUR; // 04:00 UTC
  core.append([pageView(V(1), h0 + 10 * MIN), pageView(null, h0 + 11 * MIN)], h0 + 11 * MIN);
  core.append([pageView(V(1), h0 + HOUR + 5 * MIN)], h0 + HOUR + 5 * MIN);
  // within the first hour: the registry has them, the archive waits for the hour to end — and the rows wait with it
  const early = await drain.run(h0 + 30 * MIN);
  assert.deepEqual([early.applied, early.archived, early.next], [3, 0, h0 + HOUR + 90000]);
  assert.equal(core.waiting(), 3);
  assert.equal(r2.objects.size, 0);
  const out = await drain.run(h0 + HOUR + 90000);
  assert.deepEqual([out.archived, out.next], [2, h0 + 2 * HOUR + 90000]);
  assert.equal(core.waiting(), 1); // the second hour's
  const key = `${ACTIVITY("site")}2026/11/25/04.jsonl.gz`;
  assert.deepEqual([...r2.objects.keys()].sort(), [`${MANIFESTS("site")}2026/11/25.json`, key]);
  const lines = await readBatch(r2, key);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].visitor_day, await dayAlias(V(1), "2026-11-25", KEY));
  assert.ok(!JSON.stringify(lines).includes(V(1).slice(2)) && !("visitor_id" in lines[0]) && !("visitor_day" in lines[1]));
  assert.deepEqual([lines[0].event_type, lines[0].country, lines[0].schema_version], ["page_view", "CN", 1]);
  assert.equal(r2.objects.get(key).options.httpMetadata.contentType, "application/gzip");
  const manifest = JSON.parse(r2.objects.get(`${MANIFESTS("site")}2026/11/25.json`).bytes.toString());
  assert.deepEqual([manifest.source, manifest.day, manifest.events, manifest.objects.length], ["site", "2026-11-25", 2, 1]);
  assert.deepEqual([manifest.objects[0].key, manifest.objects[0].hour, manifest.objects[0].events, manifest.objects[0].types, manifest.objects[0].first_seq, manifest.objects[0].last_seq],
    [key, "04", 2, { page_view: 2 }, 1, 2]);
  assert.match(manifest.objects[0].sha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(db.rows("SELECT key, source, day, hour, events FROM archive_manifest"), [{ key, source: "site", day: "2026-11-25", hour: "04", events: 2 }]);
  // the day checked against its manifest; then an object gone, one changed, one nobody wrote
  assert.deepEqual(await verifyArchive(r2, "site", "2026-11-25"), { day: "2026-11-25", source: "site", objects: 1, events: 2, bytes: manifest.bytes, missing: [], mismatched: [], unlisted: [], ok: true });
  await drain.run(h0 + 2 * HOUR + 90000);
  assert.equal(core.waiting(), 0);
  assert.equal((await verifyArchive(r2, "site", "2026-11-25")).objects, 2);
  const second = `${ACTIVITY("site")}2026/11/25/05.jsonl.gz`;
  r2.objects.get(second).bytes = Buffer.from("tampered");
  r2.objects.get(second).sha = Buffer.alloc(32);
  r2.objects.delete(key);
  await r2.put(`${ACTIVITY("site")}2026/11/25/23.jsonl.gz`, "x");
  const bad = await verifyArchive(r2, "site", "2026-11-25");
  assert.deepEqual([bad.ok, bad.missing, bad.mismatched, bad.unlisted], [false, [key], [second], [`${ACTIVITY("site")}2026/11/25/23.jsonl.gz`]]);
  assert.deepEqual((await verifyArchive(r2, "site", "2026-11-20")).ok, null); // a day nothing was written on
  assert.equal(storage.at !== null, true);
});

test("an archive out of reach: the registry is written all the same, the rows wait for the archive", async () => {
  let down = true;
  const r2 = bucket({ fail: () => down });
  const { core, drain } = drainer({ r2 });
  const h0 = Math.floor(T0 / HOUR) * HOUR;
  core.append([pageView(V(1), h0)], h0);
  const errors = console.error;
  console.error = () => {};
  let out;
  try { out = await drain.run(h0 + 2 * HOUR); } finally { console.error = errors; }
  assert.deepEqual([out.applied, out.archived, out.failed], [1, 0, true]);
  assert.deepEqual([core.waiting(), core.get("r2_failures"), core.get("d1_seq"), core.get("r2_seq")], [1, 1, 1, 0]);
  down = false;
  out = await drain.run(h0 + 2 * HOUR + 300000);
  assert.deepEqual([out.applied, out.archived, core.waiting()], [0, 1, 0]);
});

// ------------------------------------------------------------------ who may read it
test("the ledger's counts are the owner's: the collector's token alone, never a page", async () => {
  const { events } = fortnight();
  const db = d1();
  await ensure(db);
  await apply(db, events); // not summed yet: reading sums what changed first
  const EXPORT = "export-token-0123456789abcdef";
  const url = (q) => new URL(`https://chat.impf.ai/api/activity/stats${q}`);
  const get = (q, token, opts = {}) => serveLedgerStats(new Request(url(q), { headers: token ? { Authorization: `Bearer ${token}` } : {} }), url(q),
    { db, token: EXPORT, ledger: CFG, today: "2026-11-25", ...opts });
  for (const given of [null, "stats-token-0123456789", "not-the-token-0123456789"]) {
    const res = await get("?range=all", given);
    assert.equal(res.status, 401);
    assert.deepEqual(await res.json(), { error: "需要收集令牌" });
  }
  assert.equal((await get("?range=all", EXPORT, { token: "" })).status, 401); // no token set on the Worker: nobody
  const res = await get("?range=all", EXPORT);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  const all = await res.json();
  assert.deepEqual([all.from, all.to, all.totals.visitors, all.places.length], ["2026-11-12", "2026-11-25", 3, 2]);
  assert.equal((await (await get("?days=7", EXPORT)).json()).from, "2026-11-19");
  const custom = await (await get("?from=2026-11-14&to=2026-11-20", EXPORT)).json();
  assert.deepEqual([custom.from, custom.to, custom.days.length, custom.totals.visitors], ["2026-11-14", "2026-11-20", 7, 2]);
  assert.equal((await (await get("?from=2026-12-30&to=2099-01-01", EXPORT)).json()).to, "2026-11-25"); // no day after today
  // without a ledger: said only to the token's holder
  assert.equal((await get("", null, { db: null })).status, 401);
  assert.equal((await get("", EXPORT, { db: null })).status, 404);
  assert.equal((await serveLedgerStats(new Request(url(""), { method: "POST" }), url(""), { db, token: EXPORT, ledger: CFG, today: "2026-11-25" })).status, 405);
  assert.equal(TABLES.filter((t) => t.startsWith("CREATE TABLE")).length, 12);
});
