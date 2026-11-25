// 登记册 — the activity ledger's registry in Cloudflare D1: what the outboxes (ledger.js) are drained into, and what the
// 统计 pane and the daily reports read.  Both Workers bind the same database (ACTIVITY_DB); tested under Node on
// node:sqlite (security/test/ledger.test.js).
//
//   visitors                 a visitor's first and last day, where they first came from, their browser's four words.
//                            An id counts as a visitor once a browser has brought it back (confirmed): one given out and
//                            never seen again — a crawler's, a browser's that keeps no cookies — is a page opened, not a
//                            visitor, or every page such a browser opens would be a new one
//   visitor_daily_activity   a row a visitor a day they were active: what the active-visitor counts and the retention
//                            are made of.  COUNT(DISTINCT visitor_id) over any stretch of days is exact — a month's
//                            visitors are the union of its days', never their sum
//   sessions                 a visit: a visitor's events with no gap longer than SESSION_GAP_MINUTES, within one day
//   activity_events          the events themselves, for ACTIVITY_EVENT_DAYS
//   question_events          a row a question (a turn), whoever answered it: recorded or not, how it ended, what it took
//   model_invocations        a row a model call the relay let through: how it ended, its tokens, how often it was asked
//   daily_metrics            a day's sums, by what they are of: kept for good, and all that is left of a day once its
//                            events are gone
//   archive_manifest         the archive's objects (R2), with what each must hash to
//
// Written to be written twice.  An outbox is drained at least once, so a batch may come again after a failure: every
// insert is by its id and ignored the second time, every update sets a value rather than adding to one, and every sum —
// a visitor's day, a visit, a question's calls and tokens, a day's metrics — is made again from the rows it is a sum
// of.  Two outboxes write here in no order: nothing depends on which came first.

import { bearerOk, json } from "./sentinel.js";
import { shiftDay } from "./usage.js";
import { isVisitor } from "./visitor.js";

export const TABLES = [
  "CREATE TABLE IF NOT EXISTS visitors (visitor_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, first_day TEXT NOT NULL, last_day TEXT NOT NULL, " +
    "first_source TEXT, first_referrer TEXT, first_country TEXT, first_region TEXT, country TEXT, region TEXT, browser_family TEXT, os_family TEXT, device_type TEXT, " +
    "language TEXT, confirmed INTEGER NOT NULL DEFAULT 0)",
  "CREATE INDEX IF NOT EXISTS visitors_first ON visitors (first_day)",
  "CREATE INDEX IF NOT EXISTS visitors_last ON visitors (last_day)",
  "CREATE TABLE IF NOT EXISTS visitor_daily_activity (visitor_id TEXT NOT NULL, day TEXT NOT NULL, events INTEGER NOT NULL, page_views INTEGER NOT NULL, " +
    "questions INTEGER NOT NULL, model_calls INTEGER NOT NULL, sessions INTEGER NOT NULL DEFAULT 0, first_ts TEXT NOT NULL, last_ts TEXT NOT NULL, country TEXT, " +
    "region TEXT, device_type TEXT, PRIMARY KEY (visitor_id, day))",
  "CREATE INDEX IF NOT EXISTS visitor_days ON visitor_daily_activity (day)",
  "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, day TEXT NOT NULL, started TEXT NOT NULL, ended TEXT NOT NULL, " +
    "duration_s INTEGER NOT NULL, events INTEGER NOT NULL, page_views INTEGER NOT NULL, questions INTEGER NOT NULL, entry TEXT, country TEXT, region TEXT, device_type TEXT)",
  "CREATE INDEX IF NOT EXISTS sessions_day ON sessions (day)",
  "CREATE INDEX IF NOT EXISTS sessions_visitor ON sessions (visitor_id, day)",
  "CREATE TABLE IF NOT EXISTS activity_events (event_id TEXT PRIMARY KEY, ts TEXT NOT NULL, t INTEGER NOT NULL, day TEXT NOT NULL, source TEXT NOT NULL, " +
    "event_type TEXT NOT NULL, visitor_id TEXT, host TEXT, route TEXT, method TEXT, status INTEGER, latency_ms INTEGER, n INTEGER NOT NULL DEFAULT 1, browser_family TEXT, " +
    "os_family TEXT, device_type TEXT, language TEXT, country TEXT, region TEXT, asn INTEGER, http_protocol TEXT, tls_version TEXT, traffic_class TEXT, risk_score INTEGER, " +
    "security_action TEXT, turn_id TEXT, referrer TEXT, detail TEXT, schema_version INTEGER NOT NULL)",
  "CREATE INDEX IF NOT EXISTS activity_day ON activity_events (day, event_type)",
  "CREATE INDEX IF NOT EXISTS activity_visitor ON activity_events (visitor_id, day)",
  "CREATE TABLE IF NOT EXISTS question_events (turn_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, ts TEXT NOT NULL, day TEXT NOT NULL, source TEXT NOT NULL, " +
    "basis TEXT NOT NULL, named INTEGER NOT NULL DEFAULT 1, visitor_id TEXT, provider TEXT, model TEXT, module TEXT, turn_index INTEGER, content_consent INTEGER, " +
    "archive_status TEXT NOT NULL DEFAULT 'not_archived', archived_at TEXT, execution_status TEXT, rounds INTEGER, calls INTEGER NOT NULL DEFAULT 0, " +
    "retry_count INTEGER, tool_count INTEGER, tools TEXT, input_tokens INTEGER, output_tokens INTEGER, duration_ms INTEGER, runtime TEXT, corpus TEXT, ui_lang TEXT, " +
    "country TEXT, region TEXT, device_type TEXT, schema_version INTEGER NOT NULL)",
  "CREATE INDEX IF NOT EXISTS question_day ON question_events (day)",
  "CREATE INDEX IF NOT EXISTS question_visitor ON question_events (visitor_id)",
  "CREATE TABLE IF NOT EXISTS model_invocations (invocation_id TEXT PRIMARY KEY, turn_id TEXT, event_id TEXT NOT NULL, ts TEXT NOT NULL, day TEXT NOT NULL, " +
    "visitor_id TEXT, provider TEXT, model TEXT, execution_status TEXT NOT NULL DEFAULT 'open', http_status INTEGER, asks INTEGER, retry_count INTEGER, via TEXT, " +
    "input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, duration_ms INTEGER, country TEXT, region TEXT, schema_version INTEGER NOT NULL)",
  "CREATE INDEX IF NOT EXISTS invocation_day ON model_invocations (day)",
  "CREATE INDEX IF NOT EXISTS invocation_turn ON model_invocations (turn_id)",
  "CREATE INDEX IF NOT EXISTS invocation_visitor ON model_invocations (visitor_id)",
  "CREATE TABLE IF NOT EXISTS daily_metrics (day TEXT NOT NULL, metric TEXT NOT NULL, k1 TEXT NOT NULL DEFAULT '', k2 TEXT NOT NULL DEFAULT '', value INTEGER NOT NULL, " +
    "PRIMARY KEY (day, metric, k1, k2))",
  "CREATE TABLE IF NOT EXISTS archive_manifest (key TEXT PRIMARY KEY, source TEXT NOT NULL, day TEXT NOT NULL, hour TEXT NOT NULL, part INTEGER NOT NULL, " +
    "events INTEGER NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, first_seq INTEGER NOT NULL, last_seq INTEGER NOT NULL, types TEXT NOT NULL, written TEXT NOT NULL)",
  "CREATE INDEX IF NOT EXISTS manifest_day ON archive_manifest (source, day)",
  // the days whose sums are to be made again; counts that outlive their rows (visitors_removed); visitors who asked to
  // be forgotten, for the two days an event of theirs may still be on its way; what was deleted, when and at whose word
  "CREATE TABLE IF NOT EXISTS ledger_dirty (day TEXT PRIMARY KEY, at INTEGER NOT NULL)",
  "CREATE TABLE IF NOT EXISTS ledger_state (k TEXT PRIMARY KEY, v INTEGER NOT NULL)",
  "CREATE TABLE IF NOT EXISTS forgotten (visitor_id TEXT PRIMARY KEY, at INTEGER NOT NULL)",
  "CREATE TABLE IF NOT EXISTS deletion_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, what TEXT NOT NULL, by TEXT NOT NULL, rows TEXT NOT NULL)",
];

/** The tables, made when they are not there (a statement each: D1 runs them as one transaction). */
export async function ensure(db) {
  await db.batch(TABLES.map((sql) => db.prepare(sql)));
}

// ------------------------------------------------------------------ what an event is reduced to
// the events that are rows of activity_events; the others change a row written before
const ROWS = new Set(["page_view", "page_ready", "api_read", "api_call", "research_started", "request", "question_submitted", "model_invocation",
  "model_refused", "feedback_submitted", "sponsor_submitted", "visitor_choice"]);
// what a visit is made of: what a visitor did, not what the service did for it
const str = (v, n = 80) => (typeof v === "string" && v ? v.slice(0, n) : null);
const int = (v, most = 1e12) => (Number.isFinite(Number(v)) && v !== null && v !== "" && typeof v !== "boolean" ? Math.max(0, Math.min(most, Math.round(Number(v)))) : null);
const flag = (v) => (v === true || v === 1 ? 1 : v === false || v === 0 ? 0 : null);
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A tool's name → how often, as a turn's end tells it: names of the site's own tools only, twenty at most. */
function toolCounts(v) {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const out = {};
  for (const [name, n] of Object.entries(v).slice(0, 40)) {
    if (/^[a-z][a-z0-9_.]{1,60}$/.test(name) && int(n, 10000)) out[name] = int(n, 10000);
    if (Object.keys(out).length >= 20) break;
  }
  return Object.keys(out).length ? JSON.stringify(out) : null;
}

function row(e) {
  const t = Date.parse(e.timestamp);
  if (!Number.isFinite(t) || !DAY.test(String(e.day)) || typeof e.event_id !== "string") return null;
  return {
    event_id: e.event_id.slice(0, 40), ts: new Date(t).toISOString(), t, day: e.day, source: str(e.source, 12) || "site", event_type: e.event_type,
    visitor_id: isVisitor(e.visitor_id) ? e.visitor_id : null, host: str(e.host), route: str(e.route, 120), method: str(e.method, 10), status: int(e.status, 999),
    latency_ms: int(e.latency_ms, 86400000), n: Math.max(1, int(e.n, 1e9) || 1), browser_family: str(e.browser_family, 20), os_family: str(e.os_family, 20),
    device_type: str(e.device_type, 10), language: str(e.language, 12), country: str(e.country, 2), region: str(e.region, 60), asn: int(e.asn),
    http_protocol: str(e.http_protocol, 12), tls_version: str(e.tls_version, 12), traffic_class: str(e.traffic_class, 12), risk_score: int(e.risk_score, 999),
    security_action: str(e.security_action, 14), turn_id: str(e.turn_id, 40), referrer: str(e.referrer, 120), detail: str(e.detail, 40),
    schema_version: int(e.schema_version, 99) || 1,
    // a question's and a model call's own
    invocation_id: str(e.invocation_id, 40), basis: str(e.basis, 8), named: e.named === false ? 0 : 1, provider: str(e.provider, 40), model: str(e.model, 80),
    fresh: e.new_visitor === true ? 1 : 0,
  };
}

/** A turn's end, a record's arrival or a call's outcome: the fields a row is updated with (null: left as it is). */
function change(e) {
  const t = Date.parse(e.timestamp);
  if (!Number.isFinite(t)) return null;
  return {
    ts: new Date(t).toISOString(), turn_id: str(e.turn_id, 40), invocation_id: str(e.invocation_id, 40), execution_status: str(e.execution_status, 24),
    http_status: int(e.http_status, 999), rounds: int(e.rounds, 10000), tool_count: int(e.tool_count, 100000), tools: toolCounts(e.tools),
    retry_count: int(e.retry_count, 10000), asks: int(e.asks, 100), via: str(e.via, 40), input_tokens: int(e.input_tokens), output_tokens: int(e.output_tokens),
    latency_ms: int(e.latency_ms, 86400000), duration_ms: int(e.duration_ms, 864000000), runtime: str(e.runtime, 20), corpus: str(e.corpus, 20),
    module: str(e.module, 20), turn_index: int(e.turn_index, 100000), content_consent: flag(e.content_consent), ui_lang: str(e.ui_lang, 12),
    provider: str(e.provider, 40), model: str(e.model, 80),
  };
}

/** The last word on each key: later fields over earlier ones, a null changing nothing. */
function lastBy(list, key) {
  const out = new Map();
  for (const c of list) {
    if (!c || !c[key]) continue;
    const held = out.get(c[key]) || {};
    for (const [k, v] of Object.entries(c)) if (v !== null && v !== undefined) held[k] = v;
    out.set(c[key], held);
  }
  return [...out.values()];
}

const x = (name) => `json_extract(value, '$.${name}')`;
const cols = (names) => names.map((c) => `${x(c)} AS ${c}`).join(", ");
// a visitor who asked to be forgotten is not written again by an event that was still on its way
const KNOWN = `CASE WHEN ${x("visitor_id")} IN (SELECT visitor_id FROM forgotten) THEN NULL ELSE ${x("visitor_id")} END`;
const EVENT_COLS = ["event_id", "ts", "t", "day", "source", "event_type", "visitor_id", "host", "route", "method", "status", "latency_ms", "n", "browser_family",
  "os_family", "device_type", "language", "country", "region", "asn", "http_protocol", "tls_version", "traffic_class", "risk_score", "security_action", "turn_id",
  "referrer", "detail", "schema_version"];
const pick = (names) => names.map((c) => `${c === "visitor_id" ? KNOWN : x(c)} AS ${c}`).join(", ");
const TOUCHED = "SELECT json_extract(value, '$[0]') AS v, json_extract(value, '$[1]') AS d FROM json_each(?1)";

/**
 * A batch of events into the tables, as one transaction.  Applied again, it changes nothing.  gapMinutes: the silence
 * that ends a visit.
 */
export async function apply(db, events, { gapMinutes = 30 } = {}) {
  const rows = [];
  const finished = [], archived = [], settled = [];
  for (const e of Array.isArray(events) ? events : []) {
    if (!e || typeof e !== "object") continue;
    if (ROWS.has(e.event_type)) { const r = row(e); if (r) rows.push(r); }
    else if (e.event_type === "turn_finished") finished.push(change(e));
    else if (e.event_type === "record_archived") archived.push(change(e));
    else if (e.event_type === "model_settled") settled.push(change(e));
  }
  const questions = rows.filter((r) => r.event_type === "question_submitted" && r.turn_id);
  const calls = rows.filter((r) => r.event_type === "model_invocation" && r.invocation_id);
  const ends = lastBy(finished, "turn_id");
  const records = lastBy(archived, "turn_id");
  const outcomes = lastBy(settled, "invocation_id");
  // a visitor's first and last event of the batch (the registry keeps the earliest first and the latest last)
  const seen = new Map();
  for (const r of rows) {
    if (!r.visitor_id) continue;
    const v = seen.get(r.visitor_id) || { visitor_id: r.visitor_id, first: r, last: r, confirmed: 0 };
    if (r.t < v.first.t) v.first = r;
    if (r.t >= v.last.t) v.last = r;
    if (!(r.event_type === "page_view" && r.fresh)) v.confirmed = 1; // it came back with the id: a browser that keeps one
    seen.set(r.visitor_id, v);
  }
  const visitors = [...seen.values()].map((v) => ({
    visitor_id: v.visitor_id, first_seen: v.first.ts, last_seen: v.last.ts, first_day: v.first.day, last_day: v.last.day, first_source: v.first.source,
    first_referrer: v.first.referrer, first_country: v.first.country, first_region: v.first.region, country: v.last.country, region: v.last.region,
    browser_family: v.last.browser_family, os_family: v.last.os_family, device_type: v.last.device_type, language: v.last.language, confirmed: v.confirmed,
  }));
  const pairs = [...new Set(rows.filter((r) => r.visitor_id).map((r) => `${r.visitor_id}|${r.day}`))].map((p) => p.split("|"));
  const turns = [...new Set([...calls.map((r) => r.turn_id), ...outcomes.map((o) => o.turn_id), ...ends.map((o) => o.turn_id), ...records.map((o) => o.turn_id)].filter(Boolean))];
  const invocations = [...new Set([...calls.map((r) => r.invocation_id), ...outcomes.map((o) => o.invocation_id)])];
  const days = [...new Set(rows.map((r) => r.day))];
  const now = Date.now();
  const J = (v) => JSON.stringify(v);
  const st = [];
  if (rows.length) {
    st.push(db.prepare(`INSERT OR IGNORE INTO activity_events (${EVENT_COLS.join(", ")}) SELECT ${pick(EVENT_COLS)} FROM json_each(?1)`).bind(J(rows)));
  }
  if (questions.length) {
    const names = ["turn_id", "event_id", "ts", "day", "source", "basis", "named", "visitor_id", "provider", "model", "country", "region", "device_type", "schema_version"];
    st.push(db.prepare(`INSERT OR IGNORE INTO question_events (${names.join(", ")}) SELECT ${pick(names)} FROM json_each(?1)`).bind(J(questions)));
  }
  if (calls.length) {
    const names = ["invocation_id", "turn_id", "event_id", "ts", "day", "visitor_id", "provider", "model", "country", "region", "schema_version"];
    st.push(db.prepare(`INSERT OR IGNORE INTO model_invocations (${names.join(", ")}) SELECT ${pick(names)} FROM json_each(?1)`).bind(J(calls)));
  }
  if (outcomes.length) {
    const names = ["execution_status", "http_status", "asks", "retry_count", "via", "input_tokens", "output_tokens", "latency_ms", "duration_ms"];
    st.push(db.prepare(`UPDATE model_invocations SET ${names.map((c) => `${c} = COALESCE(j.${c}, model_invocations.${c})`).join(", ")} ` +
      `FROM (SELECT ${cols(["invocation_id", ...names])} FROM json_each(?1)) AS j WHERE model_invocations.invocation_id = j.invocation_id`)
      .bind(J(outcomes)));
  }
  if (ends.length) {
    // the page's word for how a turn ended; of a turn the relay answered, the tokens are the relay's own count (below)
    const names = ["execution_status", "rounds", "tool_count", "tools", "retry_count", "duration_ms", "runtime", "corpus", "module", "turn_index", "content_consent", "ui_lang"];
    st.push(db.prepare(`UPDATE question_events SET ${names.map((c) => `${c} = COALESCE(j.${c}, question_events.${c})`).join(", ")}, ` +
      "input_tokens = CASE WHEN question_events.calls > 0 THEN question_events.input_tokens ELSE COALESCE(j.input_tokens, question_events.input_tokens) END, " +
      "output_tokens = CASE WHEN question_events.calls > 0 THEN question_events.output_tokens ELSE COALESCE(j.output_tokens, question_events.output_tokens) END " +
      `FROM (SELECT ${cols(["turn_id", ...names, "input_tokens", "output_tokens"])} FROM json_each(?1)) AS j WHERE question_events.turn_id = j.turn_id`).bind(J(ends)));
  }
  if (records.length) {
    // a record came: the turn is archived, and what the page did not say of its end the record does (in counts)
    const names = ["execution_status", "rounds", "tool_count", "retry_count", "duration_ms", "runtime", "corpus", "turn_index"];
    st.push(db.prepare("UPDATE question_events SET archive_status = 'archived', archived_at = COALESCE(question_events.archived_at, j.ts), content_consent = 1, " +
      `${names.map((c) => `${c} = COALESCE(question_events.${c}, j.${c})`).join(", ")}, ` +
      "input_tokens = CASE WHEN question_events.calls > 0 THEN question_events.input_tokens ELSE COALESCE(question_events.input_tokens, j.input_tokens) END, " +
      "output_tokens = CASE WHEN question_events.calls > 0 THEN question_events.output_tokens ELSE COALESCE(question_events.output_tokens, j.output_tokens) END " +
      `FROM (SELECT ${cols(["turn_id", "ts", ...names, "input_tokens", "output_tokens"])} FROM json_each(?1)) AS j WHERE question_events.turn_id = j.turn_id`).bind(J(records)));
  }
  if (turns.length) {
    // a question's calls and what they cost, counted again from its calls
    const of = (what) => `(SELECT ${what} FROM model_invocations m WHERE m.turn_id = question_events.turn_id)`;
    st.push(db.prepare(`UPDATE question_events SET calls = ${of("COUNT(*)")}, input_tokens = ${of("SUM(m.input_tokens)")}, output_tokens = ${of("SUM(m.output_tokens)")}, ` +
      "basis = CASE WHEN basis = 'client' THEN 'relay' ELSE basis END " +
      "WHERE turn_id IN (SELECT value FROM json_each(?1)) AND EXISTS (SELECT 1 FROM model_invocations m WHERE m.turn_id = question_events.turn_id)").bind(J(turns)));
  }
  if (visitors.length) {
    // an id brought back for the first time: the days it was already seen on now have a visitor more
    const back = visitors.filter((v) => v.confirmed).map((v) => v.visitor_id);
    if (back.length) {
      st.push(db.prepare("INSERT INTO ledger_dirty (day, at) SELECT DISTINCT a.day, ?2 FROM visitor_daily_activity a JOIN visitors v ON v.visitor_id = a.visitor_id " +
        "WHERE v.confirmed = 0 AND a.visitor_id IN (SELECT value FROM json_each(?1)) ON CONFLICT (day) DO UPDATE SET at = excluded.at").bind(J(back), now));
    }
    const names = Object.keys(visitors[0]);
    const later = (c) => `${c} = CASE WHEN excluded.last_seen >= visitors.last_seen THEN excluded.${c} ELSE visitors.${c} END`;
    const earlier = (c) => `${c} = CASE WHEN excluded.first_seen < visitors.first_seen THEN excluded.${c} ELSE visitors.${c} END`;
    st.push(db.prepare(`INSERT INTO visitors (${names.join(", ")}) SELECT ${cols(names)} FROM json_each(?1) WHERE ${x("visitor_id")} NOT IN (SELECT visitor_id FROM forgotten) ` +
      `ON CONFLICT (visitor_id) DO UPDATE SET ${["first_source", "first_referrer", "first_country", "first_region"].map(earlier).join(", ")}, ` +
      `${["country", "region", "browser_family", "os_family", "device_type", "language"].map(later).join(", ")}, ` +
      "first_seen = MIN(visitors.first_seen, excluded.first_seen), last_seen = MAX(visitors.last_seen, excluded.last_seen), " +
      "first_day = MIN(visitors.first_day, excluded.first_day), last_day = MAX(visitors.last_day, excluded.last_day), " +
      "confirmed = MAX(visitors.confirmed, excluded.confirmed)").bind(J(visitors)));
  }
  if (pairs.length) {
    const p = J(pairs);
    const firstOf = (c) => `(SELECT x.${c} FROM activity_events x WHERE x.visitor_id = e.visitor_id AND x.day = e.day ORDER BY x.t, x.event_id LIMIT 1)`;
    // a visitor's day: counted again from that day's events
    st.push(db.prepare("INSERT OR REPLACE INTO visitor_daily_activity (visitor_id, day, events, page_views, questions, model_calls, sessions, first_ts, last_ts, country, region, device_type) " +
      "SELECT e.visitor_id, e.day, SUM(e.n), SUM(CASE WHEN e.event_type = 'page_view' THEN e.n ELSE 0 END), SUM(CASE WHEN e.event_type = 'question_submitted' THEN 1 ELSE 0 END), " +
      `SUM(CASE WHEN e.event_type = 'model_invocation' THEN 1 ELSE 0 END), 0, MIN(e.ts), MAX(e.ts), ${firstOf("country")}, ${firstOf("region")}, ${firstOf("device_type")} ` +
      `FROM activity_events e JOIN (${TOUCHED}) AS p ON e.visitor_id = p.v AND e.day = p.d GROUP BY e.visitor_id, e.day`).bind(p));
    // and its visits: made again from that day's events (a silence longer than the gap begins a new one)
    st.push(db.prepare(`DELETE FROM sessions WHERE (visitor_id, day) IN (${TOUCHED})`).bind(p));
    st.push(db.prepare("WITH ev AS (SELECT e.visitor_id, e.day, e.t, e.ts, e.n, e.event_type, e.route, e.country, e.region, e.device_type, e.event_id, " +
      "CASE WHEN LAG(e.t) OVER w IS NULL OR e.t - LAG(e.t) OVER w > ?2 THEN 1 ELSE 0 END AS begins " +
      `FROM activity_events e JOIN (${TOUCHED}) AS p ON e.visitor_id = p.v AND e.day = p.d WINDOW w AS (PARTITION BY e.visitor_id, e.day ORDER BY e.t, e.event_id)), ` +
      "numbered AS (SELECT *, SUM(begins) OVER (PARTITION BY visitor_id, day ORDER BY t, event_id ROWS UNBOUNDED PRECEDING) AS k FROM ev) " +
      "INSERT OR REPLACE INTO sessions (session_id, visitor_id, day, started, ended, duration_s, events, page_views, questions, entry, country, region, device_type) " +
      "SELECT 'ses_' || substr(visitor_id, 3) || '_' || MIN(t), visitor_id, day, MIN(ts), MAX(ts), (MAX(t) - MIN(t)) / 1000, SUM(n), " +
      "SUM(CASE WHEN event_type = 'page_view' THEN n ELSE 0 END), SUM(CASE WHEN event_type = 'question_submitted' THEN 1 ELSE 0 END), " +
      "MAX(CASE WHEN begins = 1 THEN route END), MAX(country), MAX(region), MAX(device_type) FROM numbered GROUP BY visitor_id, day, k")
      .bind(p, Math.round(gapMinutes * 60000)));
    st.push(db.prepare("UPDATE visitor_daily_activity SET sessions = (SELECT COUNT(*) FROM sessions s WHERE s.visitor_id = visitor_daily_activity.visitor_id AND s.day = visitor_daily_activity.day) " +
      `WHERE (visitor_id, day) IN (${TOUCHED})`).bind(p));
  }
  // the days whose sums no longer hold: the events' own, and those of the questions and calls that changed
  const dirty = "ON CONFLICT (day) DO UPDATE SET at = excluded.at";
  if (days.length) st.push(db.prepare(`INSERT INTO ledger_dirty (day, at) SELECT value, ?2 FROM json_each(?1) WHERE 1 ${dirty}`).bind(J(days), now));
  if (turns.length) {
    st.push(db.prepare(`INSERT INTO ledger_dirty (day, at) SELECT DISTINCT day, ?2 FROM question_events WHERE turn_id IN (SELECT value FROM json_each(?1)) ${dirty}`).bind(J(turns), now));
  }
  if (invocations.length) {
    st.push(db.prepare(`INSERT INTO ledger_dirty (day, at) SELECT DISTINCT day, ?2 FROM model_invocations WHERE invocation_id IN (SELECT value FROM json_each(?1)) ${dirty}`)
      .bind(J(invocations), now));
  }
  if (st.length) await db.batch(st);
  return { rows: rows.length, questions: questions.length, calls: calls.length, changes: ends.length + records.length + outcomes.length, visitors: visitors.length };
}

/** The archive's objects an outbox wrote, for whoever checks the archive against them. */
export async function syncManifest(db, objects) {
  const list = objects.map((o) => ({ key: o.key, source: o.source, day: o.day, hour: new Date(Number(o.hour)).toISOString().slice(11, 13), part: Number(o.part),
    events: Number(o.events), bytes: Number(o.bytes), sha256: o.sha256, first_seq: Number(o.first_seq), last_seq: Number(o.last_seq), types: String(o.types || "{}"),
    written: new Date(Number(o.written)).toISOString() }));
  if (!list.length) return;
  const names = Object.keys(list[0]);
  await db.batch([db.prepare(`INSERT OR REPLACE INTO archive_manifest (${names.join(", ")}) SELECT ${cols(names)} FROM json_each(?1)`).bind(JSON.stringify(list))]);
}

// ------------------------------------------------------------------ a day's sums
const HUMAN = "traffic_class = 'human'";
const VIEW = `event_type = 'page_view' AND ${HUMAN}`;
const one = (sql) => `SELECT '', '', COALESCE((${sql}), 0)`;
const SEEN = "visitor_daily_activity a JOIN visitors v ON v.visitor_id = a.visitor_id AND v.confirmed = 1";
const VISITS = "sessions s JOIN visitors v ON v.visitor_id = s.visitor_id AND v.confirmed = 1";
const LENGTH = "CASE WHEN duration_s < 10 THEN '0-10s' WHEN duration_s < 60 THEN '10-60s' WHEN duration_s < 300 THEN '1-5m' WHEN duration_s < 900 THEN '5-15m' " +
  "WHEN duration_s < 3600 THEN '15-60m' ELSE '60m+' END";

/**
 * metric → the rows (k1, k2, value) of day ?1.  The counts of visitors are of the day alone (`active`), and of the
 * seven and thirty days ending with it (`active_7`, `active_30`): each a count of different visitors, which is why they
 * are kept and not added up afterwards.
 */
export const METRICS = {
  // everything a Worker answered, by what the sentinel made of it: the visitors' part is `human`
  requests: "SELECT COALESCE(traffic_class, ''), COALESCE(security_action, ''), SUM(n) FROM activity_events WHERE day = ?1 AND event_type NOT IN ('question_submitted', 'page_ready', 'visitor_choice') GROUP BY 1, 2",
  page_views: `SELECT COALESCE(country, 'XX'), COALESCE(region, ''), SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} GROUP BY 1, 2`,
  page_views_identified: one(`SELECT SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} AND visitor_id IS NOT NULL`),
  page_ready: one("SELECT SUM(n) FROM activity_events WHERE day = ?1 AND event_type = 'page_ready'"),
  pages: `SELECT COALESCE(route, ''), '', SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} GROUP BY 1`,
  referrers: `SELECT referrer, '', SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} AND referrer IS NOT NULL GROUP BY 1`,
  browsers: `SELECT COALESCE(browser_family, 'Other'), '', SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} GROUP BY 1`,
  systems: `SELECT COALESCE(os_family, 'Other'), '', SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} GROUP BY 1`,
  devices: `SELECT COALESCE(device_type, 'other'), '', SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} GROUP BY 1`,
  languages: `SELECT COALESCE(language, ''), '', SUM(n) FROM activity_events WHERE day = ?1 AND ${VIEW} GROUP BY 1`,
  ui_languages: "SELECT COALESCE(detail, ''), '', SUM(n) FROM activity_events WHERE day = ?1 AND event_type = 'page_ready' GROUP BY 1",
  api: `SELECT event_type, CAST(COALESCE(status, 0) AS TEXT), SUM(n) FROM activity_events WHERE day = ?1 AND event_type IN ('api_read', 'api_call', 'research_started') AND ${HUMAN} GROUP BY 1, 2`,
  visitors: `SELECT COALESCE(a.country, 'XX'), COALESCE(a.region, ''), COUNT(*) FROM ${SEEN} WHERE a.day = ?1 GROUP BY 1, 2`,
  active: one(`SELECT COUNT(*) FROM ${SEEN} WHERE a.day = ?1`),
  active_7: one(`SELECT COUNT(DISTINCT a.visitor_id) FROM ${SEEN} WHERE a.day > date(?1, '-7 days') AND a.day <= ?1`),
  active_30: one(`SELECT COUNT(DISTINCT a.visitor_id) FROM ${SEEN} WHERE a.day > date(?1, '-30 days') AND a.day <= ?1`),
  new_visitors: "SELECT COALESCE(first_country, 'XX'), COALESCE(first_region, ''), COUNT(*) FROM visitors WHERE first_day = ?1 AND confirmed = 1 GROUP BY 1, 2",
  // ids given out that day and not brought back since: pages opened by what keeps no cookie
  unconfirmed: one("SELECT COUNT(*) FROM visitors WHERE first_day = ?1 AND confirmed = 0"),
  returning: one(`SELECT COUNT(*) FROM ${SEEN} WHERE a.day = ?1 AND v.first_day < ?1`),
  sessions: one(`SELECT COUNT(*) FROM ${VISITS} WHERE s.day = ?1`),
  session_seconds: one(`SELECT SUM(s.duration_s) FROM ${VISITS} WHERE s.day = ?1`),
  session_length: `SELECT ${LENGTH}, '', COUNT(*) FROM ${VISITS} WHERE s.day = ?1 GROUP BY 1`,
  questions: "SELECT basis, archive_status, COUNT(*) FROM question_events WHERE day = ?1 GROUP BY 1, 2",
  questions_place: "SELECT COALESCE(country, 'XX'), COALESCE(region, ''), COUNT(*) FROM question_events WHERE day = ?1 GROUP BY 1, 2",
  questions_model: "SELECT COALESCE(provider, ''), COALESCE(model, ''), COUNT(*) FROM question_events WHERE day = ?1 GROUP BY 1, 2",
  questions_module: "SELECT COALESCE(module, ''), '', COUNT(*) FROM question_events WHERE day = ?1 GROUP BY 1",
  questions_status: "SELECT COALESCE(execution_status, ''), '', COUNT(*) FROM question_events WHERE day = ?1 GROUP BY 1",
  questions_consent: "SELECT CASE content_consent WHEN 1 THEN 'yes' WHEN 0 THEN 'no' ELSE '' END, '', COUNT(*) FROM question_events WHERE day = ?1 GROUP BY 1",
  askers: one("SELECT COUNT(DISTINCT visitor_id) FROM question_events WHERE day = ?1 AND visitor_id IS NOT NULL"),
  runtimes: "SELECT COALESCE(runtime, ''), COALESCE(corpus, ''), COUNT(*) FROM question_events WHERE day = ?1 AND runtime IS NOT NULL GROUP BY 1, 2",
  tools: "SELECT j.key, '', SUM(j.value) FROM question_events q, json_each(q.tools) AS j WHERE q.day = ?1 AND q.tools IS NOT NULL GROUP BY 1",
  tool_calls: one("SELECT SUM(tool_count) FROM question_events WHERE day = ?1"),
  // model calls: the relay's own count of what it let through, by how each ended; and, of the turns asked of a visitor's
  // own model, the calls the page says they took
  model_calls: "SELECT COALESCE(model, ''), execution_status, COUNT(*) FROM model_invocations WHERE day = ?1 GROUP BY 1, 2",
  model_asks: one("SELECT SUM(COALESCE(asks, 1)) FROM model_invocations WHERE day = ?1"),
  rounds: "SELECT COALESCE(provider, ''), COALESCE(model, ''), SUM(rounds) FROM question_events WHERE day = ?1 AND calls = 0 AND rounds > 0 GROUP BY 1, 2",
  tokens_in: "SELECT COALESCE(provider, ''), COALESCE(model, ''), SUM(input_tokens) FROM question_events WHERE day = ?1 AND input_tokens > 0 GROUP BY 1, 2",
  tokens_out: "SELECT COALESCE(provider, ''), COALESCE(model, ''), SUM(output_tokens) FROM question_events WHERE day = ?1 AND output_tokens > 0 GROUP BY 1, 2",
  refusals: "SELECT COALESCE(detail, ''), '', SUM(n) FROM activity_events WHERE day = ?1 AND event_type = 'model_refused' GROUP BY 1",
  feedback: "SELECT COALESCE(detail, ''), '', SUM(n) FROM activity_events WHERE day = ?1 AND event_type = 'feedback_submitted' GROUP BY 1",
  choices: "SELECT COALESCE(detail, ''), '', SUM(n) FROM activity_events WHERE day = ?1 AND event_type = 'visitor_choice' GROUP BY 1",
};

/**
 * The sums of the days that changed, made again from their rows (a day's old sums go first: a group that is no longer
 * there must not stay).  At most `limit` days a call, the oldest first.  → the days done.
 */
export async function rollup(db, { limit = 14 } = {}) {
  const { results } = await db.prepare("SELECT day, at FROM ledger_dirty ORDER BY day LIMIT ?1").bind(limit).all();
  const done = [];
  for (const { day, at } of results || []) {
    const st = [db.prepare("DELETE FROM daily_metrics WHERE day = ?1").bind(day)];
    for (const [metric, sql] of Object.entries(METRICS)) {
      st.push(db.prepare(`WITH sums (a, b, c) AS (${sql}) INSERT OR REPLACE INTO daily_metrics (day, metric, k1, k2, value) ` +
        `SELECT ?1, '${metric}', a, b, c FROM sums WHERE c IS NOT NULL AND a IS NOT NULL`).bind(day));
    }
    // only if nothing touched the day meanwhile: else it is done again
    st.push(db.prepare("DELETE FROM ledger_dirty WHERE day = ?1 AND at = ?2").bind(day, at));
    await db.batch(st);
    done.push(day);
  }
  return done;
}

// ------------------------------------------------------------------ what is no longer kept
/**
 * Once a day: the events older than eventDays go (their days' sums stay); a visitor not seen for keepDays goes, with
 * their days — counted in visitors_removed, so that the number of visitors there ever were does not fall — and what
 * they asked stays as questions of no one.  → what went.
 */
export async function prune(db, { today, eventDays = 90, keepDays = 760 }) {
  const events = shiftDay(today, -eventDays);
  const old = shiftDay(today, -keepDays);
  const gone = await db.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(confirmed), 0) AS confirmed FROM visitors WHERE last_day < ?1").bind(old).first();
  const n = Number(gone?.n || 0);
  const st = [
    db.prepare("DELETE FROM activity_events WHERE day < ?1").bind(events),
    db.prepare("DELETE FROM model_invocations WHERE day < ?1").bind(events),
    db.prepare("DELETE FROM sessions WHERE day < ?1").bind(events),
    db.prepare("DELETE FROM question_events WHERE day < ?1").bind(old),
    db.prepare("DELETE FROM visitor_daily_activity WHERE day < ?1").bind(old),
    db.prepare("DELETE FROM forgotten WHERE at < ?1").bind(Date.now() - 2 * 86400000),
  ];
  if (n) {
    st.push(db.prepare("UPDATE question_events SET visitor_id = NULL WHERE visitor_id IN (SELECT visitor_id FROM visitors WHERE last_day < ?1)").bind(old),
      db.prepare("DELETE FROM visitor_daily_activity WHERE visitor_id IN (SELECT visitor_id FROM visitors WHERE last_day < ?1)").bind(old),
      db.prepare("DELETE FROM visitors WHERE last_day < ?1").bind(old),
      db.prepare("INSERT INTO ledger_state (k, v) VALUES ('visitors_removed', ?1) ON CONFLICT (k) DO UPDATE SET v = v + excluded.v").bind(Number(gone.confirmed || 0)),
      db.prepare("INSERT INTO deletion_log (at, what, by, rows) VALUES (?1, 'retention', 'schedule', ?2)").bind(new Date().toISOString(), JSON.stringify({ visitors: n, before: old })));
  }
  await db.batch(st);
  return { visitors: n, events_before: events, visitors_before: old };
}

/**
 * A visitor forgotten, at their own word (设置 → 数据) or the owner's: their row, their days and their visits are
 * deleted; their events, questions and model calls stay as no one's (the counts of pages and questions do not change;
 * the count of visitors there ever were does not fall); the deletion is written down without the id.  An event of
 * theirs still on its way is written as no one's for two days.  → {found, rows}
 */
export async function forget(db, visitor, { by = "self", now = Date.now() } = {}) {
  if (!isVisitor(visitor)) return { found: false, rows: {} };
  const count = async (table) => Number((await db.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE visitor_id = ?1`).bind(visitor).first())?.n || 0);
  const rows = {};
  for (const t of ["visitors", "visitor_daily_activity", "sessions", "activity_events", "question_events", "model_invocations"]) rows[t] = await count(t);
  const found = rows.visitors > 0;
  const was = found ? await db.prepare("SELECT confirmed FROM visitors WHERE visitor_id = ?1").bind(visitor).first() : null;
  const st = [
    db.prepare("INSERT INTO forgotten (visitor_id, at) VALUES (?1, ?2) ON CONFLICT (visitor_id) DO UPDATE SET at = excluded.at").bind(visitor, now),
    db.prepare("INSERT INTO ledger_dirty (day, at) SELECT day, ?2 FROM visitor_daily_activity WHERE visitor_id = ?1 ON CONFLICT (day) DO UPDATE SET at = excluded.at").bind(visitor, now),
    ...["activity_events", "question_events", "model_invocations"].map((t) => db.prepare(`UPDATE ${t} SET visitor_id = NULL WHERE visitor_id = ?1`).bind(visitor)),
    ...["sessions", "visitor_daily_activity", "visitors"].map((t) => db.prepare(`DELETE FROM ${t} WHERE visitor_id = ?1`).bind(visitor)),
    db.prepare("INSERT INTO deletion_log (at, what, by, rows) VALUES (?1, 'visitor', ?2, ?3)").bind(new Date(now).toISOString(), by, JSON.stringify(rows)),
  ];
  if (was?.confirmed) st.push(db.prepare("INSERT INTO ledger_state (k, v) VALUES ('visitors_removed', 1) ON CONFLICT (k) DO UPDATE SET v = v + 1"));
  await db.batch(st);
  return { found, rows };
}

/** What the registry holds of a visitor, for that visitor (设置 → 数据): their first and last day, and the days and
 * questions counted — or null. */
export async function known(db, visitor) {
  if (!isVisitor(visitor)) return null;
  const v = await db.prepare("SELECT first_day, last_day FROM visitors WHERE visitor_id = ?1").bind(visitor).first();
  if (!v) return null;
  const a = await db.prepare("SELECT COUNT(*) AS days, SUM(page_views) AS page_views, SUM(questions) AS questions FROM visitor_daily_activity WHERE visitor_id = ?1").bind(visitor).first();
  return { first_day: v.first_day, last_day: v.last_day, days: Number(a?.days || 0), page_views: Number(a?.page_views || 0), questions: Number(a?.questions || 0) };
}

// ------------------------------------------------------------------ what the 统计 pane and the reports read
const MAX_SERIES = 800;
const SERIES = ["active", "active_7", "active_30", "page_views", "sessions", "questions", "new_visitors", "model_calls", "tokens_in", "tokens_out", "returning"];
const monday = (col) => `date(${col}, 'weekday 0', '-6 days')`;

/**
 * The ledger over the days `from` … `to` (from: null — since its first day).  The sums that add up come from the days'
 * sums; the counts of different visitors are counted over the stretch itself.  minCell: a place with fewer visitors
 * than this is folded into the rest.
 */
export async function stats(db, { from = null, to, today = to, minCell = 1 }) {
  const firstRow = await db.prepare("SELECT MIN(day) AS first, MAX(day) AS last FROM daily_metrics").first();
  const first = firstRow?.first || null;
  const start = from && (!first || from > first) ? from : first || to;
  const q = (sql, ...args) => db.prepare(sql).bind(...args);
  const range = "day >= ?1 AND day <= ?2";
  const res = await db.batch([
    q(`SELECT metric, k1, k2, SUM(value) AS value FROM daily_metrics WHERE ${range} AND metric NOT IN ('active', 'active_7', 'active_30') GROUP BY metric, k1, k2`, start, to),
    q(`SELECT day, metric, SUM(value) AS value FROM daily_metrics WHERE ${range} AND metric IN (${SERIES.map((m) => `'${m}'`).join(", ")}) GROUP BY day, metric`, start, to),
    q(`SELECT COUNT(DISTINCT a.visitor_id) AS n FROM ${SEEN} WHERE a.day >= ?1 AND a.day <= ?2`, start, to),
    q(`SELECT COUNT(*) AS n FROM (SELECT a.visitor_id FROM ${SEEN} WHERE a.day >= ?1 AND a.day <= ?2 GROUP BY a.visitor_id HAVING COUNT(*) >= 2 OR MIN(v.first_day) < ?1)`, start, to),
    q(`SELECT COALESCE(a.country, 'XX') AS country, COALESCE(a.region, '') AS region, COUNT(DISTINCT a.visitor_id) AS n FROM ${SEEN} WHERE a.day >= ?1 AND a.day <= ?2 GROUP BY 1, 2`, start, to),
    q("SELECT (SELECT COUNT(*) FROM visitors WHERE confirmed = 1) AS here, (SELECT COUNT(*) FROM visitors WHERE confirmed = 0) AS unconfirmed, " +
      "COALESCE((SELECT v FROM ledger_state WHERE k = 'visitors_removed'), 0) AS removed"),
    // retention by the week a visitor first came: of each of the last weeks' new visitors, how many were back in the weeks after
    q(`SELECT ${monday("v.first_day")} AS cohort, CAST((julianday(${monday("a.day")}) - julianday(${monday("v.first_day")})) / 7 AS INTEGER) AS k, COUNT(DISTINCT a.visitor_id) AS n ` +
      `FROM visitors v JOIN visitor_daily_activity a ON a.visitor_id = v.visitor_id WHERE v.confirmed = 1 AND v.first_day >= ${monday("date(?1, '-49 days')")} AND v.first_day <= ?1 AND a.day <= ?1 GROUP BY 1, 2`, to),
    // and by the day: of the visitors who first came N days or more before the last day, how many were back on their Nth day
    ...[1, 7, 30].map((n) => q("SELECT COUNT(*) AS cohort, COALESCE(SUM(CASE WHEN EXISTS (SELECT 1 FROM visitor_daily_activity a WHERE a.visitor_id = v.visitor_id " +
      `AND a.day = date(v.first_day, '+${n} days')) THEN 1 ELSE 0 END), 0) AS back FROM visitors v WHERE v.confirmed = 1 AND v.first_day >= ?1 AND v.first_day <= date(?2, '-${n} days')`, start, today)),
    q(`SELECT s.duration_s FROM ${VISITS} WHERE s.day >= ?1 AND s.day <= ?2 ORDER BY s.duration_s LIMIT 1 OFFSET (SELECT COUNT(*) / 2 FROM ${VISITS} WHERE s.day >= ?1 AND s.day <= ?2)`, start, to),
    q("SELECT COUNT(*) AS n FROM ledger_dirty"),
  ]);
  const rowsOf = (i) => res[i]?.results || [];
  const sums = new Map(); // metric → [[k1, k2, value]]
  for (const r of rowsOf(0)) {
    if (!sums.has(r.metric)) sums.set(r.metric, []);
    sums.get(r.metric).push([r.k1, r.k2, Number(r.value) || 0]);
  }
  const total = (metric, test = () => true) => (sums.get(metric) || []).reduce((n, [a, b, v]) => n + (test(a, b) ? v : 0), 0);
  const top = (metric, limit = 12, by = 0) => {
    const merged = new Map();
    for (const [a, b, v] of sums.get(metric) || []) { const k = by === 0 ? a : by === 1 ? b : `${a}\u0000${b}`; merged.set(k, (merged.get(k) || 0) + v); }
    return [...merged].sort((p, r) => r[1] - p[1]).slice(0, limit).map(([k, v]) => (by === 2 ? [...k.split("\u0000"), v] : [k, v]));
  };
  // the days: the last MAX_SERIES of the stretch
  const length = Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1;
  const shown = Math.max(1, Math.min(length, MAX_SERIES));
  const days = Array.from({ length: shown }, (_, i) => shiftDay(to, i - shown + 1));
  const at = new Map(days.map((d, i) => [d, i]));
  const daily = Object.fromEntries(SERIES.map((m) => [m, days.map(() => 0)]));
  for (const r of rowsOf(1)) if (at.has(r.day)) daily[r.metric][at.get(r.day)] = Number(r.value) || 0;
  // places: page views and questions from the days' sums, visitors counted over the stretch; the small ones folded
  const places = new Map();
  const placeOf = (country, region) => {
    const key = `${country}|${region}`;
    if (!places.has(key)) places.set(key, { country, region, visitors: 0, page_views: 0, questions: 0 });
    return places.get(key);
  };
  for (const [c, r, v] of sums.get("page_views") || []) placeOf(c, r).page_views += v;
  for (const [c, r, v] of sums.get("questions_place") || []) placeOf(c, r).questions += v;
  for (const r of rowsOf(4)) placeOf(r.country, r.region).visitors += Number(r.n) || 0;
  const all = [...places.values()];
  const kept = all.filter((p) => p.visitors >= minCell || minCell <= 1);
  const folded = all.filter((p) => !kept.includes(p));
  if (folded.length) {
    kept.push({ country: "", region: "", visitors: folded.reduce((n, p) => n + p.visitors, 0), page_views: folded.reduce((n, p) => n + p.page_views, 0),
      questions: folded.reduce((n, p) => n + p.questions, 0), folded: folded.length });
  }
  kept.sort((a, b) => (b.visitors - a.visitors) || (b.page_views - a.page_views) || (b.questions - a.questions));
  // retention
  const cohorts = new Map();
  for (const r of rowsOf(6)) {
    if (!cohorts.has(r.cohort)) cohorts.set(r.cohort, []);
    cohorts.get(r.cohort)[Number(r.k)] = Number(r.n) || 0;
  }
  const weekly = [...cohorts].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([week, back]) => ({ week, size: back[0] || 0, back: Array.from(back, (v) => v || 0).slice(1) }));
  const byDay = Object.fromEntries([1, 7, 30].map((n, i) => { const r = rowsOf(7 + i)[0] || {}; return [`d${n}`, { cohort: Number(r.cohort) || 0, back: Number(r.back) || 0 }]; }));
  const questions = total("questions");
  const archived = total("questions", (basis, status) => status === "archived");
  const views = total("page_views");
  const sessions = total("sessions");
  const here = rowsOf(5)[0] || {};
  const order = ["0-10s", "10-60s", "1-5m", "5-15m", "15-60m", "60m+"];
  const lengths = new Map(top("session_length", 10));
  return {
    v: 1, from: start, to, asOf: today, first_day: first, days,
    totals: {
      visitors: Number(rowsOf(2)[0]?.n || 0), new_visitors: total("new_visitors"), returning_visitors: Number(rowsOf(3)[0]?.n || 0),
      visits: sessions, page_views: views, questions, questions_archived: archived, questions_unarchived: questions - archived,
      model_calls: total("model_calls") + total("rounds"), model_calls_relay: total("model_calls"), model_calls_reported: total("rounds"),
      tokens_in: total("tokens_in"), tokens_out: total("tokens_out"), tool_calls: total("tool_calls"),
      countries: new Set(all.filter((p) => p.country && p.country !== "XX").map((p) => p.country)).size, regions: all.filter((p) => p.region).length,
    },
    // the visitors there ever were: those here, and those since deleted (forgotten at their word, or past their time)
    lifetime: { visitors: Number(here.here || 0) + Number(here.removed || 0), unconfirmed: Number(here.unconfirmed || 0), removed: Number(here.removed || 0) },
    daily,
    questions: { by_basis: top("questions", 6), by_model: top("questions_model", 12, 2), by_module: top("questions_module"), by_status: top("questions_status"),
      by_consent: top("questions_consent"), refusals: top("refusals") },
    models: { calls: top("model_calls", 12, 0), outcomes: top("model_calls", 12, 1), asks: total("model_asks"), tokens_in: top("tokens_in", 12, 2), tokens_out: top("tokens_out", 12, 2) },
    places: kept.slice(0, 300),
    retention: { weekly, ...byDay },
    features: { tools: top("tools", 20), runtimes: top("runtimes", 8, 2), pages: top("pages"), api: top("api", 12, 2), feedback: top("feedback"),
      ui_languages: top("ui_languages"), choices: top("choices") },
    audience: { browsers: top("browsers"), systems: top("systems"), devices: top("devices"), languages: top("languages"), referrers: top("referrers") },
    sessions: { count: sessions, seconds: total("session_seconds"), median_s: Number(rowsOf(10)[0]?.duration_s ?? 0), lengths: order.map((k) => [k, lengths.get(k) || 0]) },
    security: { classes: top("requests", 10, 0), actions: top("requests", 10, 1) },
    coverage: {
      // of the pages browsers opened: how many for a visitor with an id, and how many said so themselves once loaded
      page_views_identified: total("page_views_identified"), page_ready: total("page_ready"), unconfirmed: total("unconfirmed"),
      questions_relay: total("questions", (b) => b === "relay"), questions_client: total("questions", (b) => b === "client"),
      questions_record: total("questions", (b) => b === "record"), pending_days: Number(rowsOf(11)[0]?.n || 0),
    },
  };
}

/**
 * GET …/activity/stats?days=N | from=YYYY-MM-DD&to=YYYY-MM-DD | range=all — for the holder of the stats token (or the
 * collector's), or anyone when the counts are public; then a place needs five visitors to be named.  The days that
 * changed are summed first, so what is read is what has been written.  cfg: usageConfig; ledger: ledgerConfig.
 */
export async function serveLedgerStats(request, url, { db, cfg, ledger, today, cors = {}, collector = "" }) {
  if (request.method !== "GET" && request.method !== "HEAD") return json({ error: "method not allowed" }, 405, cors);
  if (!db || !ledger?.on) return json({ error: "这里没有活动账本", ledger: false }, 404, cors);
  let open = cfg.public;
  if (!(await bearerOk(request, cfg.token)) && !(await bearerOk(request, collector))) {
    if (!cfg.public) return json({ error: cfg.token ? "统计令牌不对" : "统计尚未开放", token_required: true, configured: Boolean(cfg.token) }, 401, cors);
  } else open = false;
  const p = url.searchParams;
  const to = DAY.test(p.get("to") || "") && p.get("to") <= today ? p.get("to") : today;
  let from = null;
  if (DAY.test(p.get("from") || "")) from = p.get("from") <= to ? p.get("from") : to;
  else if (p.get("range") !== "all") from = shiftDay(to, -(Math.min(Math.max(Math.floor(Number(p.get("days"))) || 30, 1), 3660) - 1));
  try {
    await ensure(db);
    await rollup(db, { limit: 5 });
    return json(await stats(db, { from, to, today, minCell: open ? Math.max(5, ledger.minCell) : ledger.minCell }), 200, cors);
  } catch (err) {
    console.error("ledger", "stats", err?.name || "Error", String(err?.message || "").slice(0, 200));
    return json({ error: "活动账本暂时读不到，请稍后再试" }, 503, { ...cors, "Retry-After": "30" });
  }
}
