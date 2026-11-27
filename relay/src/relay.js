// 道乃久默认服务 — the relay between the published page (chat.impf.ai) and MiniMax, so that visitors can ask without a
// key of their own.  The MiniMax key is a secret of this Worker: it never reaches a browser, the page or the repository.
//
//   POST /v1/chat/completions   the page's model calls, forwarded (streamed) with the key; only from the page's origins,
//                               only the allowed models, output capped, limited per visitor per minute and per day and in
//                               all per day
//   GET  /v1/health             whether the service is configured, its model, whether records are collected, the limits
//   GET  /v1/egress             how a call from where the caller is looks to the second model's edge; with Bearer
//                               LOG_EXPORT_TOKEN, the owner's diagnostic: the same from each place the models are called
//                               from, and whether the default model's host answers from each
//   POST /v1/logs               one turn of a conversation, sent by the page only when the visitor agreed to it
//   POST /v1/feedback           a visitor's rating of an answer (👍 / 👎), what they wrote of it, and — only when they chose
//                               to attach it — the turn's question and answer; kept with the records
//   GET  /v1/logs/export        the records waiting, for the repository's collector (Authorization: Bearer LOG_EXPORT_TOKEN)
//   POST /v1/logs/ack           the collector has committed them: they are deleted here (409 while the archive collects)
//   GET  /v1/logs/archive       a day of the records archived in the private bucket ARCHIVE (Bearer LOG_EXPORT_TOKEN), when
//                               the Worker has one: then the records go there, not to the repository (security/archive.js)
//   GET  /v1/security/export    the sentinel's events waiting (Bearer LOG_EXPORT_TOKEN); POST /v1/security/ack deletes them;
//                               GET /v1/security/archive, a day of them archived
//   GET  /v1/security/summary   the visitors by score and the addresses refused now (Bearer LOG_EXPORT_TOKEN)
//   POST /v1/security/csp       a browser's Content-Security-Policy report (kept as an event)
//   POST /v1/sponsor            a visitor's own API key and model, given to the service (赞助): kept encrypted, apart from
//                               the records, never logged (relay/src/sponsors.js)
//   GET  /v1/sponsors           the sponsorships, keys hinted only; ?reveal=ID one key in full (Bearer SPONSOR_SECRET);
//                               POST /v1/sponsors/delete removes one
//   POST /v1/activity           a turn's end as the page tells it, in counts (how it ended, its rounds, its tools, its
//                               tokens) — the only word of a question asked of a visitor's own model, which never passes
//                               here; never what was asked or answered.  Only with the activity ledger
//   GET  /v1/activity/health    the ledger's outbox here: what waits, what was dropped (Bearer LOG_EXPORT_TOKEN)
//
// A second model, GPT-6 Luna (OpenAI), is offered beside the default one when the Worker has OPENAI_API_KEY: the page
// asks for it by its public name, the relay sends it to OpenAI with that key, and a visitor may ask it a few questions a
// day (OPENAI_QUESTIONS_PER_DAY; a question is counted once however many calls its tool rounds take).
//
// Visitors are counted by a hash of their address and the day; addresses are not stored, and records carry none.  The
// sentinel (security/sentinel.js) sees every request: a scanner path refuses its address for a day, a request that is
// not the page's is scored and, flagged, kept whole for the owner; in enforce mode an address over the block score is
// refused for a while.  An answer's tokens, as the upstream reports them, count against the visitor's day and the day.
// A request the page of another site made a reader's browser send (security/sentinel.js, ledFrom) is answered 403
// before any of that: it is none of the reader's doing, so nothing of it is counted or kept against the address.
//
// A question is a turn, not a call.  The page names each turn (X-Tao-Turn) on every call of it, and the turn's first
// call is the question, whatever the calls after it end with (gate.js).  With the activity ledger (security/ledger.js:
// the Worker has ACTIVITY_KEY and ACTIVITY_DB) each question and each model call is written down — for the visitor the
// page's pass names (X-Tao-Visitor: security/visitor.js), with how the call ended and what it cost, and never with the
// page's name of the turn, which a conversation record carries: the ledger cannot say who asked what.

import { EVENTS, RECORDS, serveArchive } from "../../security/archive.js";
import { assess, bodyShape, clipped, fingerprint, ipKey, isHoneypot, ledFrom, logLine, sentinelConfig, serveSecurity } from "../../security/sentinel.js";
import { place, serveStats, usageConfig, usageDay } from "../../security/usage.js";
import { ledgerConfig, readPass, turnKey } from "../../security/visitor.js";
import { normalizeSponsor, sealSponsor, sponsorReady, unseal } from "./sponsors.js";
import { day } from "./state.js";

export const VERSION = "1";
const LOCAL = new Set(["localhost", "127.0.0.1", "[::1]"]);

export const DEFAULTS = {
  UPSTREAM_BASE: "https://api.minimax.cn/v1", // MiniMax's mainland platform; https://api.minimax.io/v1 for international keys
  MODELS: "MiniMax-M3",                       // the first is the default
  // what a visitor sees of the upstream: nothing.  The page knows the default service's model by this name only; the
  // upstream's parameters are added here; its reasoning formats reach the page as "Tao-…" and go back as they came
  PUBLIC_MODEL: "Tao-R1",
  UPSTREAM_FIELDS: '{"reasoning_split":true}',
  FORMAT_PREFIX: "MiniMax-",
  MAX_OUTPUT_TOKENS: "32768",                 // per reply, its reasoning included (MiniMax-M3 itself takes far more)
  // a model service that sends nothing — no status, no header — for this long is not waited for: the call is given up
  // and made again, UPSTREAM_ATTEMPTS times in all, before the visitor is told (0 seconds: waited for as long as it
  // takes).  In the records to 2026-11-10, of the calls a page watched, none that answered took 90 s to begin, 2.5%
  // took more than 30 s — and one in ten began never: 53 s to the service's own 5xx, or past the page's two minutes.
  // The attempts together stay under the page's own wait for a first reply (web/js/limits.js, firstReply: 120 s)
  UPSTREAM_FIRST_BYTE_SECONDS: "30",
  UPSTREAM_ATTEMPTS: "3",
  // where the default model is asked from, in turn: "direct" — the Cloudflare location the visitor reached, where this
  // Worker runs — and Durable Object location hints (an object placed there makes the call: index.js, Egress).  A
  // visitor in mainland China reaches Cloudflare in Amsterdam, Seattle, San Jose, Los Angeles or London (the sentinel's
  // events), and the model service is in mainland China: asked from there, the request crosses the border a second
  // time, on that location's own path — and it is on that path that one request in ten never began (never another
  // visitor's in the same minutes, never another service's from the same page: docs/adr/0033).  An ask that is silent
  // for UPSTREAM_HEDGE_SECONDS is joined — not given up — by one from the next place, and the first to answer is the
  // reply; the place that was silent, failed or refused is asked last for a while (deps.routes, this instance's memory)
  UPSTREAM_VIA: "direct,apac",
  UPSTREAM_HEDGE_SECONDS: "12",
  MAX_BODY_BYTES: "2000000",
  PER_MINUTE: "30",                           // model calls per visitor (one question takes several: the tools)
  PER_DAY: "600",
  TOTAL_PER_DAY: "5000",                      // all visitors together
  TOKENS_PER_DAY: "10000000",                 // tokens (input + output, as the upstream counts them) per visitor per day
  TOTAL_TOKENS_PER_DAY: "200000000",          // and all visitors together (0: no limit)
  LOGS: "on",
  LOG_MAX_BYTES: "65536",
  LOGS_PER_MINUTE: "20",
  LOGS_PER_DAY: "500",
  // what a day's records may weigh, in bytes as they are sent: of one visitor (8 MiB), and of all together (64 MiB;
  // 0: no limit).  The records go into the repository, and nothing bounded what a day adds to it: a visitor's 500 a
  // day are 29 MiB at their largest, and there was no total at all
  LOG_BYTES_PER_DAY: "8388608",
  LOG_BYTES_TOTAL_PER_DAY: "67108864",
  LOG_KEEP: "50000",                          // records waiting to be collected at most: beyond, new ones are refused (none dropped)
  FEEDBACK: "on",                             // ratings and written feedback on answers, kept with the records
  FEEDBACK_PER_MINUTE: "10",
  FEEDBACK_PER_DAY: "100",
  FEEDBACK_BYTES_PER_DAY: "2097152",          // and by weight, as the records: of one visitor (2 MiB), of all (16 MiB)
  FEEDBACK_BYTES_TOTAL_PER_DAY: "16777216",
  // the second model: GPT-6 Luna through OpenAI, with the Worker's secret OPENAI_API_KEY (offered only when it is set).
  // Its own limits: questions per visitor per day (a question's tool rounds are not counted again) and in all; and,
  // under them, calls and tokens — what bounds a question's rounds, and a client that is not the page
  OPENAI: "on",
  OPENAI_BASE: "https://api.openai.com/v1",
  OPENAI_MODEL: "gpt-6-luna",
  OPENAI_PUBLIC_MODEL: "GPT-6 Luna",          // its name on the page
  OPENAI_QUESTIONS_PER_DAY: "3",
  OPENAI_TOTAL_QUESTIONS_PER_DAY: "300",
  OPENAI_PER_MINUTE: "10",                    // model calls per visitor
  OPENAI_CALLS_PER_DAY: "60",
  OPENAI_TOKENS_PER_DAY: "3000000",
  OPENAI_TOTAL_TOKENS_PER_DAY: "60000000",
  // where OpenAI is called from: a Durable Object placed there (index.js, Egress).  The Worker runs at the visitor's
  // nearest Cloudflare location, and OpenAI refuses some regions such a location may be in (a 403).  A list: the next is
  // tried when OpenAI refuses the region of one.  "off" calls from the visitor's location
  OPENAI_LOCATION: "enam,wnam",
  OPENAI_MIN_OUTPUT: "2048",                  // a reasoning model refuses a smaller output cap (16 was refused)
  // the model the page chooses for a visitor who has chosen none: a public name the service offers, until
  // DEFAULT_MODEL_UNTIL (an ISO time; "" no end) — then PUBLIC_MODEL again.  "": PUBLIC_MODEL
  DEFAULT_MODEL: "",
  DEFAULT_MODEL_UNTIL: "",
  // visitors' own API keys given to the service (赞助): on only when the Worker also has SPONSOR_SECRET (32+ characters)
  SPONSOR: "on",
  SPONSOR_PER_DAY: "5",                       // per visitor
  SPONSOR_KEEP: "1000",                       // kept at most: beyond, new ones are refused (none dropped)
  ALLOWED_ORIGINS: "https://chat.impf.ai,https://psknlr.github.io", // https only: the site serves no page over http
};

export function config(env = {}) {
  const get = (k) => (env[k] !== undefined && env[k] !== "" ? env[k] : DEFAULTS[k]);
  const num = (k) => Number(get(k));
  const list = (k) => String(get(k)).split(",").map((s) => s.trim()).filter(Boolean);
  const models = list("MODELS");
  let fields = {};
  try {
    const v = JSON.parse(String(get("UPSTREAM_FIELDS")));
    if (v && typeof v === "object" && !Array.isArray(v)) fields = v;
  } catch { /* none */ }
  return {
    upstream: String(get("UPSTREAM_BASE")).replace(/\/+$/, ""),
    models,
    model: models[0],
    publicModel: String(get("PUBLIC_MODEL")),
    upstreamFields: fields,
    formatPrefix: String(get("FORMAT_PREFIX")),
    maxTokens: num("MAX_OUTPUT_TOKENS"),
    // the wait for the upstream's first byte, in milliseconds (0: none), and how many times it is asked (1 to 5)
    firstByteMs: Math.max(0, Math.round((num("UPSTREAM_FIRST_BYTE_SECONDS") || 0) * 1000)),
    attempts: Math.min(5, Math.max(1, Math.floor(num("UPSTREAM_ATTEMPTS")) || 1)),
    // the places the default model is asked from, in order ("direct", or a location hint; none named: direct), and how
    // long an ask may be silent before another place joins it, in milliseconds (0: none joins)
    via: ((v) => (v.length ? v : [DIRECT]))([...new Set(list("UPSTREAM_VIA").map((x) => x.toLowerCase()).filter((x) => x === DIRECT || PLACES.has(x)))]),
    hedgeMs: Math.max(0, Math.round((num("UPSTREAM_HEDGE_SECONDS") || 0) * 1000)),
    maxBody: num("MAX_BODY_BYTES"),
    origins: list("ALLOWED_ORIGINS"),
    chat: { perMinute: num("PER_MINUTE"), perDay: num("PER_DAY"), total: num("TOTAL_PER_DAY"), tokensPerDay: num("TOKENS_PER_DAY"), totalTokens: num("TOTAL_TOKENS_PER_DAY") },
    log: { perMinute: num("LOGS_PER_MINUTE"), perDay: num("LOGS_PER_DAY"), total: 0, tokensPerDay: num("LOG_BYTES_PER_DAY"), totalTokens: num("LOG_BYTES_TOTAL_PER_DAY") },
    logs: String(get("LOGS")).toLowerCase() !== "off",
    rate: { perMinute: num("FEEDBACK_PER_MINUTE"), perDay: num("FEEDBACK_PER_DAY"), total: 0, tokensPerDay: num("FEEDBACK_BYTES_PER_DAY"),
      totalTokens: num("FEEDBACK_BYTES_TOTAL_PER_DAY") },
    feedback: String(get("FEEDBACK")).toLowerCase() !== "off",
    logMax: num("LOG_MAX_BYTES"),
    keep: num("LOG_KEEP"),
    openai: {
      on: String(get("OPENAI")).toLowerCase() !== "off",
      upstream: String(get("OPENAI_BASE")).replace(/\/+$/, ""),
      model: String(get("OPENAI_MODEL")),
      publicModel: String(get("OPENAI_PUBLIC_MODEL")),
      questions: { perDay: num("OPENAI_QUESTIONS_PER_DAY"), total: num("OPENAI_TOTAL_QUESTIONS_PER_DAY") },
      chat: { perMinute: num("OPENAI_PER_MINUTE"), perDay: num("OPENAI_CALLS_PER_DAY"), total: 0, tokensPerDay: num("OPENAI_TOKENS_PER_DAY"),
        totalTokens: num("OPENAI_TOTAL_TOKENS_PER_DAY") },
      locations: list("OPENAI_LOCATION").filter((x) => PLACES.has(x)), // "off" (or anything else): none
      minOutput: num("OPENAI_MIN_OUTPUT") || 0,
    },
    defaultModel: String(get("DEFAULT_MODEL")).trim(),
    defaultUntil: String(get("DEFAULT_MODEL_UNTIL")).trim() ? Date.parse(String(get("DEFAULT_MODEL_UNTIL")).trim()) : Infinity,
    sponsor: String(get("SPONSOR")).toLowerCase() !== "off",
    sponsorLimits: { perMinute: 3, perDay: num("SPONSOR_PER_DAY"), total: 0 },
    sponsorKeep: num("SPONSOR_KEEP"),
  };
}

// Durable Objects' location hints (Cloudflare): where a model may be called from besides where the Worker runs
const PLACES = new Set(["wnam", "enam", "sam", "weur", "eeur", "apac", "oc", "afr", "me"]);
const DIRECT = "direct"; // from where the Worker runs: the Cloudflare location the visitor reached

/** Is the second model offered: switched on, and the Worker has its key? */
const secondReady = (env, cfg) => Boolean(cfg.openai.on && env.OPENAI_API_KEY && cfg.openai.model && cfg.openai.publicModel);

/** The model the page chooses for a visitor who has chosen none: DEFAULT_MODEL while it is offered and its time lasts
 * (an unreadable DEFAULT_MODEL_UNTIL: never), else the default service's own. */
export function defaultModel(models, cfg, now) {
  return cfg.defaultModel && models.includes(cfg.defaultModel) && now < cfg.defaultUntil ? cfg.defaultModel : cfg.publicModel;
}

/**
 * deps: {gate({who, kind, limits, fp, a, shape, status, cfg}) → {ok, reason, retry, remaining, watch}, observe(fp, a, extra, cfg),
 * spend(who, kind, tokens), watch: {observe, records, remove, summary}, logbook: {add, records, remove}, defer(promise),
 * fetch, now} (the Durable Objects and the network in the Worker; plain objects in tests).
 */
export async function handle(request, env, deps) {
  const cfg = config(env);
  const url = new URL(request.url);
  const origin = request.headers.get("Origin") || "";
  const allowed = cfg.origins.includes(origin);
  // the page reads how long a refusal asks it to wait (Retry-After), and asks again no sooner
  // (and how many times the model service was asked for a reply, and from where it came: for the turn's record)
  const cors = allowed ? { "Access-Control-Allow-Origin": origin, "Access-Control-Expose-Headers": "Retry-After, X-Tao-Asks, X-Tao-Via", Vary: "Origin" } : { Vary: "Origin" };
  // the sentinel: the request as seen at the edge, and a note of it when it is worth one (security/sentinel.js)
  const scfg = sentinelConfig(env);
  const fp = fingerprint(request, deps.now());
  const s = scfg.mode === "off" ? null : { cfg: scfg, fp, origins: cfg.origins, deps };
  // the activity ledger (security/ledger.js): on with its key, its registry and the object that keeps its outbox.  A:
  // what a request is to it — its route, and what an event of it needs besides what the sentinel read
  const lcfg = ledgerConfig(env);
  const A = { lcfg, fp, now: deps.now(), route: ROUTES.has(url.pathname) ? url.pathname : "other",
    L: lcfg.on && env.ACTIVITY_DB && deps.ledger ? { offset: usageConfig(env).offset, flagScore: scfg.flagScore } : null };
  if (s) s.A = A;
  // a request the page of another site made a reader's browser send (an image, a form, a script's fetch pointed here):
  // this host answers the project's own pages only — a rule of access, whether or not the sentinel records — and
  // nothing of it is counted or kept against the reader's address
  const led = ledFrom(fp, cfg.origins);
  if (led) {
    if (s) logLine("relay", fp, { route: "led", score: 0, reasons: ["led"], led }, null, 403, scfg);
    return error(403, "此接口只供道乃久的网页调用", "cross_site", cors);
  }
  if (url.protocol === "http:" && !LOCAL.has(url.hostname)) { // a conversation is never taken in clear
    if (s) note(s, "other", 403);
    return error(403, "请使用 https", "https_required", cors);
  }
  if (request.method === "OPTIONS") {
    if (!allowed) {
      if (s) note(s, "other", 403);
      return new Response(null, { status: 403, headers: cors });
    }
    return new Response(null, {
      status: 204,
      // (no Authorization: the page sends the relay no key, and reads nothing of it that needs one)
      headers: { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Accept, X-Tao-Turn, X-Tao-Visitor",
        "Access-Control-Max-Age": "86400" },
    });
  }
  try {
    if (s && isHoneypot(url.pathname)) {
      note(s, "honeypot", 404); // the address is noted — and, HONEYPOT = block, refused from now on — after the answer
      return error(404, "没有这个接口", "not_found", cors);
    }
    if (s && url.pathname.startsWith("/v1/security/")) {
      if (url.pathname === "/v1/security/csp" && (await bursting(request, deps))) return error(429, "报告太频繁", "rate_limited", { ...cors, "Retry-After": "10" });
      if (url.pathname === "/v1/security/archive") return await serveArchive(request, url, { bucket: env.ARCHIVE, prefix: EVENTS("relay"), token: env.LOG_EXPORT_TOKEN || "" });
      const res = await serveSecurity(request, url, { prefix: "/v1/security", token: env.LOG_EXPORT_TOKEN || "", watch: deps.watch, cfg: scfg, fp: s.fp,
        now: deps.now(), cors, archived: Boolean(env.ARCHIVE) });
      if (res) return res;
    }
    switch (`${request.method} ${url.pathname}`) {
      case "GET /v1/health": return health(env, cfg, cors, deps.now(), A);
      case "GET /v1/stats": return await stats(request, env, url, deps);
      case "GET /v1/egress": return await egress(request, env, cfg, cors, deps);
      case "POST /v1/chat/completions": return await chat(request, env, cfg, cors, allowed, deps, s, A);
      case "POST /v1/logs": return await submit(request, cfg, cors, allowed, deps, s, A);
      case "POST /v1/feedback": return await feedback(request, cfg, cors, allowed, deps, s, A);
      case "POST /v1/activity": return await beacon(request, cfg, cors, allowed, deps, s, A);
      case "GET /v1/activity/health":
        if (!(await authorized(request, env))) return error(401, "需要收集令牌", "unauthorized");
        return A.L ? json({ v: 1, relay: await deps.ledger.health(), ids: lcfg.ids }) : error(404, "这里没有活动账本", "activity_off");
      case "GET /v1/logs/export": return await records(request, env, url, deps);
      case "POST /v1/logs/ack": return await ack(request, env, deps);
      case "GET /v1/logs/archive": return await serveArchive(request, url, { bucket: env.ARCHIVE, prefix: RECORDS, token: env.LOG_EXPORT_TOKEN || "" });
      case "POST /v1/sponsor": return await sponsor(request, env, cfg, cors, allowed, deps, s, A);
      case "GET /v1/sponsors": return await sponsors(request, env, url, deps, s);
      case "POST /v1/sponsors/delete": return await unsponsor(request, env, deps, s);
      default:
        if (s) note(s, "other", 404);
        return error(404, "没有这个接口", "not_found", cors);
    }
  } catch (err) {
    console.error("relay error", err?.name || "Error"); // never the request: it may carry what a visitor wrote
    return error(500, "默认服务出错了，请稍后再试", "relay_error", cors);
  }
}

// ------------------------------------------------------------------ helpers
const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

/** Errors in the shape the page's model clients read (an OpenAI-style error object). */
const error = (status, message, type, headers = {}, extra = {}) => json({ error: { message, type } }, status, { ...headers, ...extra });
const refusal = error;

const encoder = new TextEncoder();

async function sha256(text) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text)));
}

const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

/** Who is calling, for the counters: a hash of the address (an IPv6 one by its /64) and the day (the address itself is
 * kept nowhere). */
async function caller(request, now) {
  const ip = request.headers.get("CF-Connecting-IP") || request.headers.get("X-Forwarded-For")?.split(",")[0]?.trim() || "unknown";
  return hex(await sha256(`${ipKey(ip)}|${day(now)}`)).slice(0, 24);
}

/** Compare two secrets in constant time (both hashed first, so their lengths do not show). */
async function sameSecret(given, expected) {
  const [a, b] = await Promise.all([sha256(given), sha256(expected)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function authorized(request, env) {
  const expected = env.LOG_EXPORT_TOKEN || "";
  const given = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  return expected.length >= 16 && given.length > 0 && (await sameSecret(given, expected));
}

/** The body as text, or null when it is larger than `max` bytes: refused by its declared length, else read only up to
 * the limit (a body sent without a length is not taken whole into memory first). */
async function readBody(request, max) {
  const declared = request.headers.get("Content-Length");
  if (declared !== null && Number(declared) > max) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const parts = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel().catch(() => {});
      return null;
    }
    parts.push(value);
  }
  const bytes = new Uint8Array(size);
  let at = 0;
  for (const part of parts) { bytes.set(part, at); at += part.byteLength; }
  return new TextDecoder().decode(bytes);
}

/** Over the ten-second gate for this address and location?  (The binding is approximate and local; the counters decide.) */
async function bursting(request, deps) {
  if (!deps.burst) return false;
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  return !(await deps.burst(ipKey(ip)));
}

/** A request noted by the sentinel without waiting for it (an answer that needs no decision from it). */
function note(s, route, status, extra = {}) {
  const a = assess(s.fp, { route, origins: s.origins, ownPrefix: s.cfg.ownPrefix });
  logLine("relay", s.fp, a, null, status, s.cfg);
  // (with the ledger: an event of it too, written by the object in the same round trip)
  s.deps.defer(s.deps.observe(s.fp, a, { status, ...extra, ...(s.A?.L ? { activity: written(s.A, { route: route === "honeypot" ? "honeypot" : s.A.route }) } : {}) }, s.cfg));
}

// ------------------------------------------------------------------ the activity ledger (security/ledger.js)
// the relay's own addresses, as an event names them; anything else is "other" (a path a scanner made up is in no event)
const ROUTES = new Set(["/v1/health", "/v1/stats", "/v1/egress", "/v1/chat/completions", "/v1/logs", "/v1/feedback", "/v1/activity", "/v1/sponsor",
  "/v1/sponsors", "/v1/logs/export", "/v1/logs/ack", "/v1/logs/archive", "/v1/security/csp"]);
// the page's id for a turn (app.js: its answer's message id), sent with each of the turn's calls
const TURN_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** What an event of this request needs besides what the sentinel read of it (gate.js: eventOf). */
const written = (A, more = {}) => ({ ledger: true, route: A.route, offset: A.L.offset, flagScore: A.L.flagScore, keep: A.lcfg.keep, ...more });

/**
 * Which turn a call belongs to, for the object's gate (gate.js): the page's name for it (X-Tao-Turn) as a keyed digest
 * — or, from a page that names none, a digest of what the visitor last asked, per caller and day: a turn's tool rounds
 * repeat it, and then only a call that ends with it may be a question.  With the ledger: the visitor the page's pass
 * names (X-Tao-Visitor), and what is written down of the call.
 */
async function activityOf(request, A, { who, messages, model }) {
  const named = request.headers.get("X-Tao-Turn") || "";
  let t;
  if (TURN_ID.test(named)) t = { key: await turnKey(named, A.lcfg.key), explicit: true, turn: true };
  else {
    let user = null;
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i]?.role === "user") { user = messages[i]; break; }
    t = { key: `q${hex(await sha256(`${who}|${JSON.stringify(user?.content ?? "")}`)).slice(0, 32)}`, explicit: false, turn: messages[messages.length - 1]?.role === "user" };
  }
  const out = { ...t, turnMs: A.lcfg.turnDays * 86400000 };
  if (!A.L) return out;
  const visitor = A.lcfg.ids === "off" ? null : await readPass(request.headers.get("X-Tao-Visitor") || "", A.lcfg.key, A.now);
  return { ...out, ...written(A, { fp: A.fp, visitor, more: { provider: RELAY_PROVIDER, model } }) };
}

/** How a call ended, for the ledger: told once the reply has gone (or could not), after the answer. */
const settling = (gate, deps) => (gate.invocation_id ? (outcome) => deps.defer(deps.ledger.settle({ invocation_id: gate.invocation_id, turn_id: gate.turn_id, ...outcome })) : null);

const BLOCKED = "该地址因异常访问已被暂时限制，请稍后再试";

function limited(gate, limits, cors, what = "请求", second = null) {
  const headers = { ...cors, "Retry-After": String(gate.retry || 60) };
  if (gate.reason === "blocked") return error(403, BLOCKED, "blocked", headers);
  if (second && gate.reason === "questions") {
    return error(429, `今天的 ${second.publicModel} 免费额度已用完（每人每天 ${second.questions.perDay} 个问题），明天再来；也可以改用道乃久默认服务的其他模型，或在“设置 → 模型”里填入自己的 API Key`,
      "daily_limit", headers);
  }
  if (second && gate.reason === "total_questions") {
    return error(429, `默认服务的 ${second.publicModel} 今天的总额度已用完，明天再来；也可以改用道乃久默认服务的其他模型，或在“设置 → 模型”里填入自己的 API Key`,
      "total_limit", headers);
  }
  if (second && gate.reason === "no_question") {
    return error(403, `默认服务的 ${second.publicModel} 按问题计额度：这一轮不属于今天已计的问题，请重新提问`, "no_question", { ...cors });
  }
  if (gate.reason === "burst") return error(429, `${what}太频繁，请稍后再试`, "rate_limited", { ...cors, "Retry-After": "10" });
  if (gate.reason === "not_served") return error(403, "没有这个对话", "not_served", headers);
  if (gate.reason === "tokens") {
    return error(429, "今天的免费额度已用完（按用量计），明天再来，或在“设置 → 模型”里填入自己的 API Key", "daily_limit", headers);
  }
  if (gate.reason === "total_tokens") {
    return error(429, "默认服务今天的总额度已用完（按用量计），明天再来，或在“设置 → 模型”里填入自己的 API Key", "total_limit", headers);
  }
  if (gate.reason === "minute") {
    return error(429, `${what}太频繁：每分钟最多 ${limits.perMinute} 次，请 ${gate.retry || 60} 秒后再试`, "rate_limited", headers);
  }
  if (gate.reason === "day") {
    return error(429, `今天的免费额度已用完（每人每天 ${limits.perDay} 次模型调用），明天再来，或在“设置 → 模型”里填入自己的 API Key`, "daily_limit", headers);
  }
  return error(429, "默认服务今天的总额度已用完，明天再来，或在“设置 → 模型”里填入自己的 API Key", "total_limit", headers);
}

// ------------------------------------------------------------------ endpoints
function health(env, cfg, cors, now, A) {
  const second = secondReady(env, cfg) ? cfg.openai : null;
  const models = [cfg.publicModel, ...(second ? [second.publicModel] : [])];
  return json({
    ok: Boolean(env.MINIMAX_API_KEY), service: "taochronos-relay", version: VERSION, model: cfg.publicModel, models,
    default: defaultModel(models, cfg, now), // what the page chooses for a visitor who has chosen none
    logs: cfg.logs, feedback: cfg.feedback, sponsor: cfg.sponsor && sponsorReady(env), max_output_tokens: cfg.maxTokens,
    // what the page may send besides its calls: its name for each turn (a question is then counted once however many
    // calls it takes) and, with the ledger, a turn's end in counts (POST /v1/activity) and its visitor's pass — ids:
    // whether visitors have ids at all (notice: unless they switch it off; optin: once they switch it on; off: none)
    activity: { turn: true, ...(A?.L ? { beacon: true, ids: A.lcfg.ids } : {}) },
    limits: { per_minute: cfg.chat.perMinute, per_day: cfg.chat.perDay, tokens_per_day: cfg.chat.tokensPerDay,
      // a model counted in questions, not calls: questions per visitor per day
      ...(second ? { questions: { [second.publicModel]: second.questions.perDay } } : {}) },
  }, 200, cors);
}

// MiniMax reports some failures in a 200 reply's base_resp
const BASE_RESP = { 1004: [503, "upstream_auth"], 2049: [503, "upstream_auth"], 1008: [503, "upstream_quota"], 1002: [429, "upstream_rate"],
  1039: [429, "upstream_rate"] };

async function chat(request, env, cfg, cors, allowed, deps, s, A) {
  if (!allowed) {
    if (s) note(s, "chat", 403);
    return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  }
  const notConfigured = () => error(503, "默认服务尚未配置，请在“设置 → 模型”里填入自己的 API Key", "not_configured", cors);
  if (!env.MINIMAX_API_KEY && !secondReady(env, cfg)) return notConfigured();
  if (await bursting(request, deps)) {
    if (s) note(s, "chat", 429);
    return limited({ reason: "burst" }, cfg.chat, cors);
  }
  const raw = await readBody(request, cfg.maxBody);
  if (raw === null) {
    if (s) note(s, "chat", 413);
    return error(413, `对话太长，超过了默认服务的上限（${Math.round(cfg.maxBody / 1e6)} MB）：请新开一个对话`, "too_large", cors);
  }
  let body;
  try { body = JSON.parse(raw); } catch {
    if (s) note(s, "chat", 400);
    return error(400, "请求不是有效的 JSON", "bad_request", cors);
  }
  if (!body || typeof body !== "object" || !Array.isArray(body.messages) || !body.messages.length) {
    if (s) note(s, "chat", 400);
    return error(400, "请求缺少 messages", "bad_request", cors);
  }
  // the sentinel reads the request's shape before the relay edits it: is this the page asking?
  const shape = s ? await bodyShape(body) : null;
  const a = s ? assess(s.fp, { route: "chat", origins: cfg.origins, shape, knownPrompts: s.cfg.knownPrompts, ownPrefix: s.cfg.ownPrefix }) : null;
  const asked = body.model;
  // the second model, by its public name (or OpenAI's): its own key, its own limits (secondChat)
  if (typeof asked === "string" && asked && (asked === cfg.openai.publicModel || asked === cfg.openai.model) && secondReady(env, cfg)) {
    return await secondChat(request, env, cfg, cors, deps, s, { body, raw, shape, a }, A);
  }
  if (!env.MINIMAX_API_KEY) return notConfigured();
  // the default service's model by its public name, or by none (pages older than it send the upstream's own name)
  if (asked !== undefined && asked !== null && asked !== "" && asked !== cfg.publicModel && !cfg.models.includes(asked)) {
    return error(400, "默认服务不提供这个模型：请在“设置 → 模型”里选用道乃久默认服务，或改用自己的 API Key", "model_not_allowed", cors);
  }
  const model = cfg.models.includes(asked) ? asked : cfg.model;
  const fields = Object.fromEntries(Object.entries(cfg.upstreamFields).filter(([k]) => !(k in body)));
  // what else the relay changes: then the request is written anew; otherwise the page's own text is edited (a second
  // serialisation of a long conversation would cost much of the CPU a request is allowed)
  let rewrite = false;
  let capped = false;
  for (const k of ["max_tokens", "max_completion_tokens"]) {
    if (k in body) {
      const v = Math.min(Math.max(1, Math.floor(Number(body[k]) || cfg.maxTokens)), cfg.maxTokens);
      if (v !== body[k]) { body[k] = v; rewrite = true; }
      capped = true;
    }
  }
  if (!capped) { body.max_completion_tokens = cfg.maxTokens; rewrite = true; }
  if ("n" in body) { delete body.n; rewrite = true; } // one answer per call
  let payload = rewrite ? null : upstreamText(raw, model, fields, cfg);
  if (payload === null) {
    Object.assign(body, fields);
    body.model = model;
    restoreFormats(body.messages, cfg);
    payload = JSON.stringify(body);
  }
  // the page asks for no thinking (a question about who answers): none is to reach the browser, whatever the model sends
  const noReasoning = body.thinking?.type === "disabled";

  const who = await caller(request, deps.now());
  // tokens charged now from the request's size (about three bytes a token), reconciled when the answer's usage is known
  const reserve = Math.ceil(raw.length / 3);
  let gate;
  try {
    // the call is counted with the gate's round trip for the owner's daily counts (security/usage.js): its day, its place,
    // and whether it is a question or a tool round of one
    const usage = s ? { day: usageDay(deps.now(), usageConfig(env).offset), ...place(s.fp), turn: Boolean(shape?.turn) } : null;
    gate = await deps.gate({ who, kind: "chat", limits: cfg.chat, fp: s?.fp, a, shape, cfg: s?.cfg, reserve, usage,
      activity: await activityOf(request, A, { who, messages: body.messages, model: cfg.publicModel }) });
  } catch (err) {
    // the counters cannot be asked (the object's day's allowance spent, or a failure): a call is never let through
    // uncounted — the visitor is told to come back, and may use a key of their own
    console.error("gate", err?.name || "Error");
    return error(503, "默认服务暂时不可用，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "unavailable", { ...cors, "Retry-After": "60" });
  }
  if (s) logLine("relay", s.fp, a, gate.watch, gate.ok ? null : gate.reason === "blocked" ? 403 : 429, s.cfg);
  if (!gate.ok) return limited(gate, cfg.chat, cors);
  // what the answer costs, as the upstream reports it when the answer ends, counted against the visitor's day (less
  // what was reserved; an answer that never reports stays charged its reserve)
  const spend = (usage) => {
    const tokens = (Number(usage?.prompt_tokens) || 0) + (Number(usage?.completion_tokens) || 0);
    if (tokens > 0) deps.defer(deps.spend(who, "chat", tokens - (gate.reserved || 0)));
  };

  return relayed({ url: `${cfg.upstream}/chat/completions`, key: env.MINIMAX_API_KEY, payload, request, cors, view: cfg, spend, noReasoning, deps,
    ways: waysOf(cfg.via, deps), settle: settling(gate, deps) });
}

/** The ways a model service is asked, in order: from where the Worker runs, and through an object placed elsewhere
 * (deps.egress; without one — a test, a Worker without the binding — only direct). */
function waysOf(via, deps) {
  const ways = via.filter((v) => v === DIRECT || deps.egress)
    .map((v) => (v === DIRECT ? { name: DIRECT, fetch: deps.fetch } : { name: v, placed: true, fetch: (url, init) => deps.egress(v, url, init) }));
  return ways.length ? ways : [{ name: DIRECT, fetch: deps.fetch }];
}

/**
 * The upstream asked, and its reply as a visitor may see it: its refusals in the default service's words (with what to
 * do instead), its stream or its JSON renamed and filtered for `view` — the model's public name and the upstream's
 * reasoning-format prefix (publicText, publicFilter) — and, asked for no thinking, without reasoning.  `label` names the
 * upstream in the Worker's log (a status code only, never a body).  `settle`, when given, is told how the call ended —
 * a word for it (ok, or the refusal's type), the status the visitor got, the asks it took and from where, its tokens, how
 * long the model service took to begin and the whole took — once: when the reply has gone, or could not.  A reply the
 * visitor left before its end is told by nobody: its call stays open in the ledger.
 */
async function relayed({ url, key, payload, request, cors: plain, view, spend, noReasoning, deps, label = "upstream", ways, settle = null }) {
  const began = deps.now();
  let got = null;
  let first = null;
  let used = null;
  let told = false;
  const end = (execution_status, http_status) => {
    if (told || !settle) return;
    told = true;
    settle({ execution_status, http_status, asks: got?.asks || 0, retry_count: Math.max(0, (got?.asks || 1) - 1), via: got?.via,
      input_tokens: used ? Number(used.prompt_tokens) || 0 : undefined, output_tokens: used ? Number(used.completion_tokens) || 0 : undefined,
      latency_ms: first === null ? undefined : Math.max(0, first - began), duration_ms: Math.max(0, deps.now() - began) });
  };
  const counted = (usage) => { used = usage; spend(usage); };
  const init = {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: request.headers.get("Accept") || "application/json",
      Authorization: `Bearer ${key}` },
    body: payload,
  };
  // the visitor leaving, or stopping the answer, ends the model call too (request.signal)
  got = await reach({ ways, url, init, signal: request.signal, ms: view.firstByteMs, hedgeMs: view.hedgeMs, attempts: view.attempts, label,
    pause: deps.pause || pauseFor, health: deps.routes, now: deps.now, at: request.cf?.colo });
  // how the reply came, for the page's record of the turn: the asks it took, and the place the reply is from
  const cors = { ...plain, "X-Tao-Asks": String(got.asks || 0), ...(got.via ? { "X-Tao-Via": got.via } : {}) };
  // a refusal in the default service's words; its type is the word the ledger keeps for how the call ended
  const error = (status, message, type, headers = {}, extra = {}) => { end(type, status); return refusal(status, message, type, headers, extra); };
  if (!got.res) {
    if (got.silent) return error(504, "默认服务的模型服务暂时没有回应，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_timeout", cors);
    return got.failed
      ? error(502, "默认服务暂时不可用，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_error", cors)
      : error(502, "默认服务暂时连不上模型服务，请稍后再试", "upstream_unreachable", cors);
  }
  first = deps.now();
  const upstream = got.res;
  const type = upstream.headers.get("Content-Type") || "application/json";
  if (upstream.status === 401 || upstream.status === 403) {
    const code = await errorCode(upstream);
    console.error(label, upstream.status, code);
    if (code === "unsupported_country_region_territory") { // the location the call left from, not the key
      return error(503, "默认服务暂时无法从当前线路连到这个模型，请稍后再试，或改用默认服务的其他模型", "upstream_region", cors);
    }
    return error(503, "默认服务暂时不可用（模型服务拒绝了它的密钥），请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_auth", cors);
  }
  if (upstream.status === 429) {
    // a quota that is spent is told apart from a busy moment where the upstream says which: asking again soon does not
    // change it, and the page does not ask (web/js/llm/openai.js, FINAL).  What the upstream asks to wait is passed on,
    // a minute at most (the page asks again no sooner).  The owner finds its word for the refusal in the Worker's log
    const { quota, code } = await rateRefusal(upstream);
    console.error(label, 429, code);
    if (quota) return error(503, "默认服务的模型额度已用完，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_quota", cors);
    const wait = waitAsked(upstream.headers.get("Retry-After"), deps.now());
    return error(429, "默认服务的模型额度暂时用完或调用过于频繁，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_rate", cors,
      wait ? { "Retry-After": String(wait) } : {});
  }
  if (!upstream.ok) {
    // the upstream's own message would name it, its models and its parameters: the visitor is told what to do instead
    // (the owner finds its code and the parameter it names in the Worker's log)
    console.error(label, upstream.status, await errorCode(upstream, true));
    return upstream.status >= 500 || upstream.status === 404
      ? error(502, "默认服务暂时不可用，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_error", cors)
      : error(400, "默认服务无法完成这个请求：请检查“设置 → 模型”里的温度、最大输出等选项，或新开一个对话后重试", "upstream_rejected", cors);
  }
  if (upstream.ok && !type.includes("event-stream") && type.includes("json")) {
    // a stream request answered with plain JSON: MiniMax's base_resp may carry a failure
    const text = await upstream.text();
    let j = null;
    try { j = JSON.parse(text); } catch { /* passed on as it is */ }
    const code = j?.base_resp?.status_code;
    if (code) {
      const [status, kind] = BASE_RESP[code] || [502, "upstream_error"];
      const msg = kind === "upstream_auth" ? "默认服务暂时不可用（模型服务拒绝了它的密钥）"
        : kind === "upstream_quota" ? "默认服务的模型额度已用完" : kind === "upstream_rate" ? "默认服务的模型调用过于频繁" : "默认服务出错了";
      return error(status, `${msg}，请稍后再试，或在“设置 → 模型”里填入自己的 API Key`, kind, cors);
    }
    const out = noReasoning && j ? JSON.stringify(withoutReasoning(j)) : text;
    const said = publicText(out, view, counted);
    end("ok", upstream.status);
    return new Response(said, { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
  }
  if (!type.includes("event-stream") || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    const said = publicText(text, view, counted);
    end("ok", upstream.status);
    return new Response(said, { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
  }
  // (the stream's end tells how the call ended: by then its usage, when the upstream reports one, has passed)
  const stream = (noReasoning ? upstream.body.pipeThrough(reasoningFilter()) : upstream.body).pipeThrough(publicFilter(view, counted, () => end("ok", upstream.status)));
  return new Response(stream, { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
}

const word = (v) => (typeof v === "string" && /^[\w.:-]{1,80}$/.test(v) ? v : "");

/** An upstream's refusal as JSON (its first 4000 characters), or null. */
async function refusalBody(upstream) {
  try { return JSON.parse((await upstream.text()).slice(0, 4000)); } catch { return null; }
}

/** What an upstream's refusal says of itself, for the Worker's log: its error code (and, with `param`, the parameter it
 * names) — short words only, never its message, which may echo what a visitor wrote. */
async function errorCode(upstream, param = false) {
  const j = await refusalBody(upstream);
  const e = j?.error && typeof j.error === "object" ? j.error : {};
  return [word(e.code) || word(e.type), param ? word(e.param) : ""].filter(Boolean).join(" ");
}

// an upstream's own words for a quota that is spent (OpenAI's code; MiniMax's are in BASE_RESP): any other 429 is a
// busy moment
const QUOTA = new Set(["insufficient_quota"]);

/** A 429 of the upstream's: is it a quota spent (`quota`) and not a busy moment, and its own short word for it (`code`:
 * its error code or type, or the status code of its base_resp) — never its message. */
async function rateRefusal(upstream) {
  const j = await refusalBody(upstream);
  const e = j?.error && typeof j.error === "object" ? j.error : {};
  const base = Number(j?.base_resp?.status_code) || 0;
  return {
    quota: BASE_RESP[base]?.[1] === "upstream_quota" || QUOTA.has(e.code) || QUOTA.has(e.type),
    code: word(e.code) || word(e.type) || (base ? String(base) : ""),
  };
}

// the most of an upstream's Retry-After that is passed on to the page, in seconds: the page waits out up to half a
// minute within a turn, and holds its next question back for longer (web/js/pause.js) — for a limit that is the
// service's and not the visitor's, never for long
const MAX_WAIT_ASKED = 60;

/** The seconds an upstream's Retry-After asks to wait (seconds, or a date), within MAX_WAIT_ASKED; 0 when it asks none. */
export function waitAsked(value, now) {
  const v = String(value ?? "").trim();
  if (!v) return 0;
  const s = /^\d+$/.test(v) ? Number(v) : Math.ceil((Date.parse(v) - now) / 1000);
  return Number.isFinite(s) && s > 0 ? Math.min(s, MAX_WAIT_ASKED) : 0;
}

// ------------------------------------------------------------------ the upstream asked, from more than one place
const SILENT = Symbol("silent");
const JOIN = Symbol("join");
// before an ask that failed at once is made again (times the asks made): a failure met at once is not met again at once
const RETRY_PAUSE_MS = 400;
// how long a place that was silent, failed or refused is asked last (this instance's memory, deps.routes): doubled each
// time it does so again, up to REST_MOST_MS; forgotten when it answers
const REST_MS = 300000;
const REST_REFUSED_MS = 60000;
const REST_MOST_MS = 1800000;
// refusals that may be one place's and not the service's: its address limited (429) or not let in (403)
const PLACE_REFUSAL = new Set([403, 429]);

/** A wait of `ms` that ends early when `signal` does. */
function pauseFor(ms, signal) {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const done = () => { clearTimeout(timer); signal?.removeEventListener("abort", done); resolve(); };
    const timer = setTimeout(done, ms);
    signal?.addEventListener("abort", done, { once: true });
  });
}

/**
 * One ask of the upstream.  `settled`: {res} when it answers (its status and headers: its first byte), {silent: true}
 * when it sends nothing for `ms` (0: waited for as long as it takes) — the ask is then ended —, {} when it cannot be
 * made, or is no longer waited for.  drop(): it is not waited for any more — ended, and whatever it still answers (a
 * fetch the signal does not reach: one made from a placed object) is not read.  `signal` (the visitor's request) ends
 * the ask, and goes on ending an answer's stream once it is passed on.
 */
function ask(fetcher, url, init, signal, ms) {
  const ctl = new AbortController();
  const leave = () => ctl.abort();
  if (signal?.aborted) ctl.abort();
  else signal?.addEventListener("abort", leave, { once: true });
  let timer = null;
  let dropped = false;
  const pending = Promise.resolve().then(() => fetcher(url, { ...init, signal: ctl.signal }));
  const drop = () => {
    if (dropped) return;
    dropped = true;
    clearTimeout(timer);
    ctl.abort();
    signal?.removeEventListener("abort", leave);
    pending.then((late) => late?.body?.cancel()).catch(() => {});
  };
  const waits = ms > 0 ? [pending, new Promise((resolve) => { timer = setTimeout(resolve, ms, SILENT); })] : [pending];
  const settled = Promise.race(waits).then((res) => {
    clearTimeout(timer);
    if (res !== SILENT) return dropped ? {} : { res };
    drop();
    return { silent: true };
  }, () => {
    clearTimeout(timer);
    signal?.removeEventListener("abort", leave);
    return {};
  });
  return { settled, drop };
}

/** The ways in the order to ask them now: those this instance has just seen silent, failing or refusing go last. */
function inOrder(ways, health, now) {
  const resting = (w) => (health?.get(w.name)?.until > now ? 1 : 0);
  return [...ways].sort((a, b) => resting(a) - resting(b)); // (stable: otherwise as they are set)
}

/** A place did not answer: asked last for `ms`, doubled each time it does so again before it has answered. */
function rest(health, way, now, ms) {
  if (!health) return;
  const h = health.get(way.name) || { fails: 0, until: 0 };
  h.fails += 1;
  h.until = Math.max(h.until, now + Math.min(REST_MOST_MS, ms * 2 ** (h.fails - 1)));
  health.set(way.name, h);
}

/**
 * The upstream asked until it answers, from the places it may be asked from (`ways`: {name, fetch, placed}, in order;
 * those that just failed last).
 *
 * - An ask that is silent for `hedgeMs` is joined by an ask from the next place: both are waited for, and the first to
 *   answer is the reply (the other is dropped).  A request that hangs on one place's path costs the wait for the next
 *   place, not the whole wait; one that is only slow is not thrown away.
 * - An ask silent for `ms`, one that cannot be made, and one the upstream answers with a failure of its own (5xx) is
 *   over; while no other is under way the next is made (after a short pause, unless it had waited already).
 * - A refusal (4xx) is the answer — but one that may be the place's and not the service's (its address limited, 429,
 *   or not let in, 403) is kept while a place not yet asked is asked once.
 * - `attempts` asks in all, before any of a reply has gone to the visitor: nothing is said twice, and it is still the
 *   one call the visitor was counted for.  The visitor leaving (`signal`) ends them all.
 *
 * → {res, asks, via}: the answer, how many asks it took and the place it is from; or, when none came, {silent: true}
 * (the upstream sent nothing), {failed: status} (its own failure) or {} (it could not be reached, or the visitor left),
 * each with `asks`.  `health` (a Map, this instance's): what it remembers of the places between calls.
 */
async function reach({ ways, url, init, signal, ms, hedgeMs, attempts, label, pause, health, now, at }) {
  const order = inOrder(ways, health, now());
  const where = at ? ` at ${at}` : "";
  const asked = new Set();
  const open = new Set();
  let made = 0;
  let join = null;   // the wait after which another place joins: {wait, stop}
  let held = null;   // a refusal kept while another place is asked: {res, way}
  let failed = 0;    // the status of the upstream's last failure of its own
  let silent = false;
  const lost = new Set(); // the places an ask was over at without an answer
  const resting = (w) => health?.get(w.name)?.until > now();
  const begin = () => {
    const way = order.find((w) => !asked.has(w.name)) || order[made % order.length];
    asked.add(way.name);
    made += 1;
    // (a placed object ends its own call when it hears nothing for as long: the signal does not reach into it)
    const a = ask(way.fetch, url, way.placed && ms > 0 ? { ...init, headers: { ...init.headers, "X-Tao-Wait": String(ms) } } : init, signal, ms);
    const entry = { way, n: made, drop: a.drop };
    entry.settled = a.settled.then((got) => ({ entry, got }));
    open.add(entry);
    join?.stop();
    join = null;
    if (hedgeMs > 0 && made < attempts) {
      let timer = null;
      join = { wait: new Promise((resolve) => { timer = setTimeout(resolve, hedgeMs, JOIN); }), stop: () => clearTimeout(timer) };
    }
  };
  const over = () => {
    join?.stop();
    for (const e of open) e.drop();
    open.clear();
  };
  try {
    for (;;) {
      if (signal?.aborted) return { asks: made };
      if (!open.size) {
        if (made >= attempts || held) break; // (a refusal kept, and the other place gave nothing: the refusal is the answer)
        begin();
      }
      const ev = await Promise.race([...[...open].map((e) => e.settled), ...(join ? [join.wait] : [])]);
      if (signal?.aborted) return { asks: made };
      if (ev === JOIN) { // silent so far: another place joins, and what is silent is not the place to ask first next time
        join = null;
        for (const e of open) rest(health, e.way, now(), REST_MS);
        console.error(label, "silent so far", `ask ${made}/${attempts} via ${[...open].map((e) => e.way.name).join("+")}${where}: joined`);
        begin();
        continue;
      }
      const { entry, got } = ev;
      open.delete(entry);
      const res = got.res;
      if (res?.ok) { // the reply
        health?.delete(entry.way.name);
        if (held) await held.res.body?.cancel().catch(() => {});
        return { res, asks: made, via: entry.way.name };
      }
      if (res && res.status < 500) { // a refusal: the answer, unless it may be this place's and another is left to ask
        if (held) await held.res.body?.cancel().catch(() => {});
        held = { res, way: entry.way };
        const places = PLACE_REFUSAL.has(res.status);
        if (!places) break; // the service's own word (a key, a parameter): no place would hear another
        rest(health, entry.way, now(), REST_REFUSED_MS);
        if (open.size) continue; // another ask is under way: its answer may be a reply
        // (a place not yet asked, and not itself just seen refusing: a limit that is the service's is not asked about twice)
        if (!(made < attempts && order.some((w) => !asked.has(w.name) && !resting(w)))) break;
        console.error(label, res.status, `ask ${made}/${attempts} via ${entry.way.name}${where}: another place asked`);
        begin();
        continue;
      }
      // over without an answer: silent to the end, unreachable, or a failure of the upstream's own
      rest(health, entry.way, now(), REST_MS);
      lost.add(entry.way.name);
      silent = Boolean(got.silent);
      if (res) failed = res.status;
      // a status or a word, never a body: which ask of how many, from where, for the owner
      console.error(label, res ? `${res.status} ${await errorCode(res, true)}`.trim() : silent ? "silent" : "unreachable",
        `ask ${entry.n}/${attempts} via ${entry.way.name}${where}`);
      if (!open.size && made < attempts && !silent) await pause(RETRY_PAUSE_MS * made, signal);
    }
    // A refusal that may be one place's own, while another place gave no answer at all, does not speak for the service:
    // the visitor is told it did not answer (and the page asks again), not that it refused — were the refusal the
    // service's, the place that was silent would say so itself the next time it answers
    const others = held && PLACE_REFUSAL.has(held.res.status) && [...lost].some((name) => name !== held.way.name);
    if (held && !others) return { res: held.res, asks: made, via: held.way.name };
    if (held) await held.res.body?.cancel().catch(() => {});
    return silent ? { silent, asks: made } : failed ? { failed, asks: made } : { asks: made };
  } finally {
    over();
  }
}

/**
 * What an object placed elsewhere does with a call handed to it (index.js, Egress): a request of its own to one of the
 * model services' hosts — the default model's or the second's, no other — with only the headers the call needs (nothing
 * else of the Worker's request travels on), ended when the host sends nothing for as long as the relay waits (X-Tao-Wait,
 * milliseconds: the relay's own signal does not reach into the object).  It keeps nothing.
 */
export async function placedFetch(request, env, fetcher) {
  const target = new URL(request.url);
  const hosts = new Set([env.OPENAI_BASE || DEFAULTS.OPENAI_BASE, env.UPSTREAM_BASE || DEFAULTS.UPSTREAM_BASE].map((u) => new URL(u).host));
  if (target.protocol !== "https:" || !hosts.has(target.host)) return new Response("not allowed", { status: 403 });
  const headers = {};
  for (const name of ["Content-Type", "Accept", "Authorization"]) {
    const value = request.headers.get(name);
    if (value) headers[name] = value;
  }
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.text();
  const wait = Math.min(120000, Math.max(0, Math.floor(Number(request.headers.get("X-Tao-Wait")) || 0)));
  if (!wait) return fetcher(target.href, { method: request.method, headers, body });
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), wait);
  try {
    return await fetcher(target.href, { method: request.method, headers, body, signal: ctl.signal }); // answered: its stream is not ended
  } finally {
    clearTimeout(timer);
  }
}

// ------------------------------------------------------------------ the second model (GPT-6 Luna, through OpenAI)
// what the page's request may carry on to OpenAI: anything else (MiniMax's own fields, the page's thinking switch, a
// temperature the model may refuse) stays here
const OPENAI_FIELDS = ["messages", "tools", "tool_choice", "parallel_tool_calls", "stream", "stream_options", "response_format", "stop", "seed"];
const MESSAGE_FIELDS = ["role", "content", "name", "tool_calls", "tool_call_id"];

/** The page's request in OpenAI's terms: the known fields only, each message without the reasoning another model sent
 * back, the output within [minTokens, maxTokens].  With tools, no reasoning: on Chat Completions GPT-6 Luna calls
 * functions only with reasoning_effort "none" (OpenAI's model page; with tools and its default effort, a 400). */
export function openaiBody(body, model, maxTokens, minTokens = 0) {
  const out = { model };
  for (const k of OPENAI_FIELDS) if (k in body) out[k] = body[k];
  out.messages = (Array.isArray(body.messages) ? body.messages : []).map((m) => {
    const o = {};
    for (const k of MESSAGE_FIELDS) if (m && typeof m === "object" && k in m) o[k] = m[k];
    return o;
  });
  const asked = Math.floor(Number(body.max_completion_tokens ?? body.max_tokens)) || maxTokens;
  out.max_completion_tokens = Math.min(Math.max(1, minTokens, asked), maxTokens);
  if (Array.isArray(out.tools) && out.tools.length) out.reasoning_effort = "none";
  return out;
}

/**
 * Which question a call belongs to: the page's turn (X-Tao-Turn) when it names one — then every call of the turn,
 * however it ends (a tool round, the self-check's note), is the same question — else what the visitor last asked (the
 * text of the last user message: a turn's tool rounds repeat it).  `turn`: may this call ask a new question?  With the
 * page's turn, yes; else only when it ends with what the visitor asked.
 */
async function questionOf(request, messages) {
  const named = request.headers.get("X-Tao-Turn") || "";
  if (TURN_ID.test(named)) return { id: `t${hex(await sha256(named)).slice(0, 24)}`, turn: true };
  let user = null;
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i]?.role === "user") { user = messages[i]; break; }
  return { id: `q${hex(await sha256(JSON.stringify(user?.content ?? ""))).slice(0, 24)}`, turn: messages[messages.length - 1]?.role === "user" };
}

/** A call for the second model: counted in questions per visitor per day (and, under them, in calls and tokens), sent
 * to OpenAI with the Worker's OPENAI_API_KEY, its reply passed on under the model's public name. */
async function secondChat(request, env, cfg, cors, deps, s, { body, raw, shape, a }, A) {
  const o = cfg.openai;
  const payload = JSON.stringify(openaiBody(body, o.model, cfg.maxTokens, o.minOutput));
  const noReasoning = body.thinking?.type === "disabled";
  const who = await caller(request, deps.now());
  const q = await questionOf(request, body.messages);
  const reserve = Math.ceil(raw.length / 3);
  let gate;
  try {
    const usage = s ? { day: usageDay(deps.now(), usageConfig(env).offset), ...place(s.fp), turn: Boolean(shape?.turn) } : null;
    gate = await deps.gate({ who, kind: "openai", limits: o.chat, fp: s?.fp, a, shape, cfg: s?.cfg, reserve, usage,
      question: { kind: "openai-q", limits: o.questions, id: q.id, turn: q.turn },
      activity: await activityOf(request, A, { who, messages: body.messages, model: o.publicModel }) });
  } catch (err) {
    console.error("gate", err?.name || "Error");
    return error(503, "默认服务暂时不可用，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "unavailable", { ...cors, "Retry-After": "60" });
  }
  if (s) logLine("relay", s.fp, a, gate.watch, gate.ok ? null : gate.reason === "blocked" ? 403 : 429, s.cfg);
  if (!gate.ok) return limited(gate, o.chat, cors, "请求", o);
  const spend = (usage) => {
    const tokens = (Number(usage?.prompt_tokens) || 0) + (Number(usage?.completion_tokens) || 0);
    if (tokens > 0) deps.defer(deps.spend(who, "openai", tokens - (gate.reserved || 0)));
  };
  const view = { ...cfg, publicModel: o.publicModel, formatPrefix: "" };
  // from where OpenAI serves (OPENAI_LOCATION), not from the visitor's nearest location; the next place when OpenAI
  // refuses the region of one
  const far = Boolean(o.locations.length && deps.egress);
  const ways = [far ? { name: o.locations.join("+"), placed: true, fetch: placed(o.locations, deps) } : { name: DIRECT, fetch: deps.fetch }];
  return relayed({ url: `${o.upstream}/chat/completions`, key: env.OPENAI_API_KEY, payload, request, cors, view, spend, noReasoning, deps,
    label: "upstream openai", ways, settle: settling(gate, deps) });
}

// ------------------------------------------------------------------ what a visitor sees of the upstream: nothing
const PUBLIC_FORMAT = "Tao-";
const MODEL_FIELD = /"model"\s*:\s*"(?:[^"\\]|\\.)*"/g;
const LEADING_MODEL = /^\{\s*"model"\s*:\s*"(?:[^"\\]|\\.)*"\s*,/;
const PUBLIC_FORMAT_FIELD = /"format"\s*:\s*"Tao-/g;
// fields only the upstream sends (its status block, its content flags, a count in its usage), an error it reports
// inside a reply — and the usage itself (an object: the final event of a stream; "usage":null in the events before it is
// passed over), read for what the answer cost
const VENDOR_FIELD = /"(?:base_resp|input_sensitive|output_sensitive|input_sensitive_type|output_sensitive_type|output_sensitive_int|total_characters|error)"\s*:|"usage"\s*:\s*\{/;
const VENDOR_KEYS = ["base_resp", "input_sensitive", "output_sensitive", "input_sensitive_type", "output_sensitive_type", "output_sensitive_int"];
const formats = new Map();
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * The page's request in the upstream's terms, edited as text: the model, the upstream's fields after it, the reasoning
 * formats of the turns before.  A quote inside a JSON string is escaped, so these patterns meet only keys and their
 * values.  Null when the text does not open with the model, as the page writes it.
 */
function upstreamText(raw, model, fields, cfg) {
  if (!LEADING_MODEL.test(raw)) return null;
  const extra = JSON.stringify(fields).slice(1, -1);
  let out = raw.replace(LEADING_MODEL, () => `{"model":${JSON.stringify(model)},${extra ? `${extra},` : ""}`);
  if (cfg.formatPrefix && out.includes(PUBLIC_FORMAT)) out = out.replace(PUBLIC_FORMAT_FIELD, () => `"format":"${cfg.formatPrefix}`);
  return out;
}

/** The reasoning a page sends back (the turns before) under the upstream's own format names again. */
function restoreFormats(messages, cfg) {
  if (!cfg.formatPrefix) return false;
  let changed = false;
  for (const m of messages) {
    if (!Array.isArray(m?.reasoning_details)) continue;
    for (const d of m.reasoning_details) {
      if (typeof d?.format === "string" && d.format.startsWith(PUBLIC_FORMAT)) {
        d.format = cfg.formatPrefix + d.format.slice(PUBLIC_FORMAT.length);
        changed = true;
      }
    }
  }
  return changed;
}

/** The upstream's model and reasoning format names in a text, the default service's instead (a text pass). */
function renamed(text, cfg) {
  const model = `"model":${JSON.stringify(cfg.publicModel)}`;
  let out = text.replace(MODEL_FIELD, () => model);
  if (cfg.formatPrefix && out.includes(cfg.formatPrefix)) {
    if (!formats.has(cfg.formatPrefix)) formats.set(cfg.formatPrefix, new RegExp(`"format"\\s*:\\s*"${escapeRe(cfg.formatPrefix)}`, "g"));
    out = out.replace(formats.get(cfg.formatPrefix), () => `"format":"${PUBLIC_FORMAT}`);
  }
  return out;
}

/**
 * A reply, or one event's data, as a visitor may see it: the default service's model name for the upstream's, its
 * reasoning formats renamed, the upstream's own fields dropped, and an error it reports inside a reply told in the
 * default service's words.  Text only in the common case (the Worker's CPU is counted per request).  `onUsage` is told
 * the usage a reply carries (what the answer cost).
 */
export function publicText(text, cfg, onUsage) {
  const out = renamed(text, cfg);
  if (!VENDOR_FIELD.test(out)) return out;
  let j;
  try { j = JSON.parse(out); } catch { return out; }
  if (!j || typeof j !== "object" || Array.isArray(j)) return out;
  if (j.error || (j.base_resp && j.base_resp.status_code)) {
    console.error("upstream error in a reply", j.base_resp?.status_code || "");
    return JSON.stringify({ error: { message: "默认服务出错了，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", type: "upstream_error" } });
  }
  for (const k of VENDOR_KEYS) delete j[k];
  for (const c of Array.isArray(j.choices) ? j.choices : []) for (const k of VENDOR_KEYS) if (c && typeof c === "object") delete c[k];
  if (j.usage && typeof j.usage === "object") {
    if (onUsage) { try { onUsage(j.usage); } catch { /* the count is not the visitor's concern */ } }
    delete j.usage.total_characters;
  }
  return JSON.stringify(j);
}

/** One pattern for what the stream's text may hold of the upstream: a model name, a reasoning format with its prefix,
 * one of its own fields (so that a single pass finds them all). */
function streamPattern(cfg) {
  const key = `stream:${cfg.formatPrefix}`;
  if (!formats.has(key)) {
    const vendor = String.raw`"(?:base_resp|input_sensitive|output_sensitive|input_sensitive_type|output_sensitive_type|output_sensitive_int|total_characters|error)"\s*:|"usage"\s*:\s*\{`;
    const format = cfg.formatPrefix ? String.raw`|"format"\s*:\s*"${escapeRe(cfg.formatPrefix)}` : "";
    formats.set(key, new RegExp(String.raw`"model"\s*:\s*"(?:[^"\\]|\\.)*"|${vendor}${format}`, "g"));
  }
  return formats.get(key);
}

/**
 * The stream's events as a visitor may see them, passed on up to the last whole line of what has arrived, in one pass
 * over the text: the model's and the reasoning formats' names replaced; a stretch naming one of the upstream's own
 * fields (its final usage, or an error) is read event by event (publicText).  The Worker's CPU is counted per request
 * and every byte of an answer passes through here, so nothing is done twice (about 5 ms per MB of stream under Node,
 * most of it decoding and encoding; a long answer is well under 1 MB).
 */
export function publicFilter(cfg, onUsage, onEnd = null) {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const pattern = streamPattern(cfg);
  const model = `"model":${JSON.stringify(cfg.publicModel)}`;
  const format = `"format":"${PUBLIC_FORMAT}`;
  let buffer = "";
  const pass = (text) => {
    let vendor = false;
    const out = text.replace(pattern, (m) => (m.charCodeAt(1) === 0x6d ? model : m.charCodeAt(1) === 0x66 ? format : ((vendor = true), m)));
    if (!vendor) return encoder.encode(out);
    return encoder.encode(out.split(/\r?\n/).map((line) => {
      const m = /^data:\s?(.*)$/.exec(line);
      if (!m || m[1].trim() === "[DONE]") return line;
      return `data: ${publicText(m[1], cfg, onUsage)}`;
    }).join("\n"));
  };
  return new TransformStream({
    transform(chunk, controller) {
      buffer += decoder.decode(chunk, { stream: true });
      const end = buffer.lastIndexOf("\n");
      if (end < 0) return;
      controller.enqueue(pass(buffer.slice(0, end + 1)));
      buffer = buffer.slice(end + 1);
    },
    flush(controller) {
      buffer += decoder.decode();
      if (buffer) controller.enqueue(pass(buffer));
      if (onEnd) { try { onEnd(); } catch { /* the count is not the visitor's concern */ } }
    },
  });
}

/** A completion, or one chunk of a stream, without the model's reasoning: its reasoning fields, and whatever of its
 * content lies inside <think>…</think>.  `open` carries, per choice, whether the stream is inside such a block — its
 * chunks may bring the content piece by piece, or (as MiniMax's examples read them) all of it so far each time. */
export function withoutReasoning(j, open = new Map()) {
  for (const [k, choice] of (Array.isArray(j?.choices) ? j.choices : []).entries()) {
    for (const part of [choice.delta, choice.message]) {
      if (!part || typeof part !== "object") continue;
      delete part.reasoning_details;
      delete part.reasoning_content;
      delete part.reasoning;
      if (typeof part.content !== "string") continue;
      const index = choice.index ?? k;
      let text = part.content;
      let out = "";
      if (open.get(index) && !text.startsWith("<think>")) { // inside a block: drop up to its end
        const close = text.indexOf("</think>");
        if (close < 0) text = "";
        else { text = text.slice(close + 8).replace(/^\s+/, ""); open.set(index, false); }
      }
      for (;;) {
        const at = text.indexOf("<think>");
        if (at < 0) { out += text; break; }
        out += text.slice(0, at);
        const close = text.indexOf("</think>", at);
        if (close < 0) { open.set(index, true); break; }
        open.set(index, false);
        text = text.slice(close + 8).replace(/^\s+/, "");
      }
      part.content = out;
    }
  }
  return j;
}

/** The stream's events, each without the model's reasoning (an event is read whole: its lines up to a blank line). */
export function reasoningFilter() {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";
  const open = new Map();
  const clean = (event) => event.split("\n").map((line) => {
    const m = /^data:\s?(.*)$/.exec(line);
    if (!m || m[1].trim() === "[DONE]") return line;
    try { return `data: ${JSON.stringify(withoutReasoning(JSON.parse(m[1]), open))}`; } catch { return line; }
  }).join("\n");
  return new TransformStream({
    transform(chunk, controller) {
      buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n/g, "\n");
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        controller.enqueue(encoder.encode(`${clean(buffer.slice(0, end))}\n\n`));
        buffer = buffer.slice(end + 2);
      }
    },
    flush(controller) {
      buffer += decoder.decode();
      if (buffer) controller.enqueue(encoder.encode(clean(buffer)));
    },
  });
}

// ------------------------------------------------------------------ records
const RELAY_PROVIDER = "impf"; // the page's id for the default service (web/js/providers.js)
// a field of text: its first n units, cut between characters and with no half character left in it (sentinel.js,
// clipped) — a question or an answer cut at its limit in the middle of a rare character was kept with a lone
// surrogate, which the collector cannot write
const str = clipped;
// a number a record says: none below zero, none past what a turn can be.  A record is a visitor's to send, and its
// numbers are summed for the owner (security/activity.py): one of -1e308 rounds, or of 1e308 tokens, was kept as it was
const num = (v, most = 1e12) => (typeof v === "number" && v >= 0 && v <= most ? v : undefined);
// a short word of the page's own (a status, a way a request ended): kept as a count's name, so never a sender's words
const short = (v, n) => (typeof v === "string" && v.length <= n && /^[a-z][a-z0-9_-]*$/.test(v) ? v : undefined);
// a model's name, as the ledger takes one (normalizeTurn): letters, digits and what a name is written with
const MODEL = /^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,79}$/;
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : null);
const list = (v, n, each) => (Array.isArray(v) ? v.slice(0, n).map((x) => each(obj(x) || {})) : undefined);

// a place a reply came from, as the relay itself names it (X-Tao-Via): "direct", or location hints
const PLACE = /^[a-z]{2,8}(\+[a-z]{2,8}){0,4}$/;

/** A turn as the page sends it, reduced to the known fields and their limits (anything else is dropped).  Where its time
 * went (web/js/records.js, timings): its model requests, its calls' times and ends, what happened between them, how long the
 * page was hidden or did not run, and the runtime it began on — numbers and short words only. */
export function normalizeRecord(r) {
  if (!r || typeof r !== "object" || Array.isArray(r) || r.v !== 1) return null;
  const question = str(r.question, 4000);
  if (!question && !num(r.images)) return null;
  const out = {
    v: 1, id: str(r.id, 64), conversation: str(r.conversation, 64), turn: num(r.turn, 1e5),
    started: str(r.started, 40), finished: str(r.finished, 40), ms: num(r.ms, 864e5), rounds: num(r.rounds, 1000), resumed: num(r.resumed, 1000),
    question: question || "", images: num(r.images, 100), answer: str(r.answer, 20000), redacted: num(r.redacted, 1e5),
    status: short(r.status, 20), error: str(r.error, 500),
    model: typeof r.model === "string" && MODEL.test(r.model) ? r.model : undefined, provider: str(r.provider, 80),
    runtime: short(r.runtime, 40), corpus: short(r.corpus, 40), app: str(r.app, 40),
    tools: list(r.tools, 40, (t) => ({
      name: str(t.name, 80), ok: t.ok === true, ms: num(t.ms), args: str(t.args, 300),
      id: str(t.id, 64), round: num(t.round, 1000), status: short(t.status, 20), at: num(t.at), wait: num(t.wait), compute: num(t.compute),
    })) || [],
    requests: list(r.requests, 48, (q) => ({
      round: num(q.round, 1000), attempt: num(q.attempt, 1000), sent: num(q.sent), open: num(q.open), first: num(q.first), text: num(q.text),
      last: num(q.last), end: num(q.end), finish: str(q.finish, 40), failed: str(q.failed, 40), expired: str(q.expired, 20),
      status: num(q.status, 999), input: num(q.input, 1e9), output: num(q.output, 1e9), hidden: num(q.hidden), asleep: num(q.asleep),
      asks: num(q.asks, 1000), via: typeof q.via === "string" && PLACE.test(q.via) ? q.via : undefined, // how many times the service asked the model service, and from where the reply came
    })),
    events: list(r.events, 40, (e) => ({ at: num(e.at), what: str(e.what, 40) })),
    hidden: num(r.hidden), asleep: num(r.asleep),
    was: obj(r.was) ? { runtime: str(r.was.runtime, 40), corpus: str(r.was.corpus, 40) } : undefined,
  };
  const u = r.usage;
  if (u && typeof u === "object" && !Array.isArray(u)) {
    out.usage = {};
    for (const k of ["input", "output"]) if (num(u[k], 1e9) !== undefined) out.usage[k] = u[k]; // tokens, summed over the turn's rounds
  }
  const c = r.citations;
  if (c && typeof c === "object" && !Array.isArray(c)) {
    out.citations = {};
    for (const k of ["total", "ok", "warn", "bad", "pending"]) if (num(c[k], 1e5) !== undefined) out.citations[k] = c[k];
    if (Array.isArray(c.pids)) out.citations.pids = c.pids.filter((p) => typeof p === "string").slice(0, 60).map((p) => str(p, 80));
  }
  return JSON.parse(JSON.stringify(out)); // without the undefined fields
}

// what a visitor may say of an answer (web/js/records.js, REASONS): short words, so that the counts can be read without
// reading what anyone wrote
const RATINGS = new Set(["up", "down"]);
const REASON = /^[a-z_]{1,32}$/;

/** A visitor's feedback on an answer as the page sends it, reduced to the known fields and their limits: which turn (its
 * message id and conversation, as the turn's own record has them), the rating — "up", "down", or null when the visitor
 * took it back —, the reasons ticked, what they wrote, whether the turn was recorded (its record then holds the question
 * and answer), and the turn's question and answer only when the visitor chose to attach them.  Null when it is not one. */
export function normalizeFeedback(r) {
  if (!obj(r) || r.v !== 1 || r.kind !== "feedback") return null;
  const id = str(r.id, 64);
  const rating = RATINGS.has(r.rating) ? r.rating : r.rating === null ? null : undefined;
  if (!id || rating === undefined) return null;
  const out = {
    v: 1, kind: "feedback", id, conversation: str(r.conversation, 64), turn: num(r.turn, 1e5), rating, given: str(r.given, 40),
    model: typeof r.model === "string" && MODEL.test(r.model) ? r.model : undefined, provider: str(r.provider, 80),
    runtime: short(r.runtime, 40), corpus: short(r.corpus, 40), app: str(r.app, 40),
  };
  if (rating) { // taken back: nothing more is kept
    Object.assign(out, {
      reasons: Array.isArray(r.reasons) ? [...new Set(r.reasons.filter((x) => typeof x === "string" && REASON.test(x)))].slice(0, 8) : [],
      comment: str(r.comment, 2000)?.trim() || undefined, recorded: r.recorded === true || undefined,
      question: str(r.question, 4000) || undefined, answer: str(r.answer, 20000) || undefined,
    });
  }
  return JSON.parse(JSON.stringify(out)); // without the undefined fields
}

async function submit(request, cfg, cors, allowed, deps, s, A) {
  return intake(request, cfg, cors, allowed, deps, s, A, {
    route: "logs", kind: "log", on: cfg.logs, limits: cfg.log, normalize: normalizeRecord, what: "记录",
    // to the ledger: the turn is archived — and, where the ledger never heard of the turn, counted (ledger.js: recorded),
    // unless it is the default service's own: its question was counted here with its first call, whatever it was known
    // by.  Told by a keyed digest of the turn's id; the record itself goes to the book, and nothing of it but counts here
    kept: async (record, model, act) => deps.ledger.recorded(act, await turnKey(record.id, A.lcfg.key), recordInfo(record, model),
      record.provider === RELAY_PROVIDER),
    off: ["对话记录已关闭", "logs_off"], full: "对话记录暂存已满，这条记录未保存",
    // a record of the default service's own conversation comes from a visitor it answered today; a record of a
    // conversation held with the visitor's own key (another provider) never passed through here, and is taken on its
    // origin alone
    served: (record) => (record.provider === RELAY_PROVIDER ? "chat" : undefined),
    lost: () => new Response(null, { status: 204, headers: cors }), // the record is let go: it is not the visitor's concern
  });
}

/** Feedback is the visitor's own act, on a turn of any day: taken on its origin and its own limits, and kept with the
 * records (the collector takes both).  The visitor waits for it: a feedback that could not be kept says so. */
async function feedback(request, cfg, cors, allowed, deps, s, A) {
  return intake(request, cfg, cors, allowed, deps, s, A, {
    route: "feedback", kind: "feedback", on: cfg.feedback, limits: cfg.rate, normalize: normalizeFeedback, what: "反馈",
    kept: async (record, model, act) => deps.ledger.logged({ ...act, type: "feedback_submitted", more: { detail: record.rating || "none" } }),
    off: ["反馈已关闭", "feedback_off"], full: "暂存已满，这条反馈未保存",
    day: `今天的反馈已达上限（每人每天 ${cfg.rate.perDay} 条），明天再来`,
    lost: () => error(503, "反馈暂时无法提交，请稍后再试", "feedback_unavailable", { ...cors, "Retry-After": "60" }),
  });
}

/** What the page sends to be kept (a record, a feedback): from the page's origins, within the ten-second gate and the
 * size limit, of the known fields, past the sentinel and the counters — then into the book for the collector. */
async function intake(request, cfg, cors, allowed, deps, s, A, how) {
  const { route, what } = how;
  if (!allowed) {
    if (s) note(s, route, 403);
    return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  }
  if (!how.on) return error(404, how.off[0], how.off[1], cors);
  if (await bursting(request, deps)) {
    if (s) note(s, route, 429);
    return limited({ reason: "burst" }, how.limits, cors, what);
  }
  const raw = await readBody(request, cfg.logMax);
  if (raw === null) return error(413, `${what}过大`, "too_large", cors);
  let r;
  try { r = JSON.parse(raw); } catch {
    if (s) note(s, route, 400);
    return error(400, `${what}不是有效的 JSON`, "bad_record", cors);
  }
  const record = how.normalize(r);
  if (!record) {
    if (s) note(s, route, 400);
    return error(400, `${what}格式不对`, "bad_record", cors);
  }
  // the page names the default service's model by its public name; the records (the owner's) keep the one that answered
  const named = record.model;
  if (record.model === cfg.publicModel) record.model = cfg.model;
  else if (record.model === cfg.openai.publicModel) record.model = cfg.openai.model;
  const a = s ? assess(s.fp, { route, origins: cfg.origins, ownPrefix: s.cfg.ownPrefix }) : null;
  let gate;
  try {
    // counted by what it weighs too (its bytes as sent, charged as the limiter charges a call's tokens)
    gate = await deps.gate({ who: await caller(request, deps.now()), kind: how.kind, limits: how.limits, fp: s?.fp, a, cfg: s?.cfg,
      served: how.served?.(record), reserve: new TextEncoder().encode(raw).length });
  } catch (err) {
    console.error("gate", err?.name || "Error");
    return how.lost();
  }
  if (s) logLine("relay", s.fp, a, gate.watch, gate.ok ? 204 : gate.reason === "blocked" ? 403 : 429, s.cfg);
  if (!gate.ok && gate.reason === "day" && how.day) return error(429, how.day, "daily_limit", { ...cors, "Retry-After": String(gate.retry || 60) });
  // the day's weight: a visitor's own, and all visitors' together (said as what it is: the limiter's own words are of model calls)
  if (!gate.ok && gate.reason === "tokens") return error(429, `今天发来的${what}已达上限，明天再发`, "daily_limit", { ...cors, "Retry-After": String(gate.retry || 60) });
  if (!gate.ok && (gate.reason === "total_tokens" || gate.reason === "total")) {
    return error(429, `今天收下的${what}已达上限，明天再收`, "total_limit", { ...cors, "Retry-After": String(gate.retry || 60) });
  }
  if (!gate.ok) return limited(gate, how.limits, cors, what);
  const id = await deps.logbook.add(JSON.stringify(record), new Date(deps.now()).toISOString(), cfg.keep);
  if (id === null) {
    // the book is full (nothing collected it for a long while): this one is refused, the ones taken in stay
    console.error("logs full", cfg.keep);
    return error(503, how.full, "logs_full", { ...cors, "Retry-After": "3600" });
  }
  // (the ledger hears of it after the answer; a record names no visitor, and its event none either)
  if (A?.L && how.kept && typeof record.id === "string" && TURN_ID.test(record.id)) {
    deps.defer(how.kept(record, named, written(A, { fp: s?.fp || A.fp, a, w: gate.watch, status: 204 })));
  }
  return new Response(null, { status: 204, headers: cors });
}

// ------------------------------------------------------------------ a turn's end, as the page tells it
const SLUG = /^[a-z0-9][a-z0-9_-]{0,39}$/;
const MODULES = new Set(["chat", "diet", "medicinal", "mydata", "research"]);
// a turn that touched the visitor's own health or their own data is counted, and for no one (the page sends no pass
// with it either: web/js/telemetry.js)
const UNNAMED = new Set(["diet", "medicinal", "mydata"]);
const ACTIVITY_MAX_BYTES = 4096;
const ACTIVITY_LIMITS = { perMinute: 30, perDay: 1000, total: 0 };

/** A provider as the ledger names it: the default service, the page's own reply, a preset's id — or "custom" for an
 * endpoint a visitor set by hand (its id is theirs, and so is its address). */
const providerOf = (v) => (typeof v !== "string" || !v ? null : v.startsWith("custom") ? "custom" : SLUG.test(v) ? v : "other");

/** What a conversation record says of its turn, in counts: for a turn the page did not tell the end of. */
function recordInfo(r, model) {
  return {
    provider: providerOf(r.provider), model: r.provider === RELAY_PROVIDER ? str(model, 80) ?? null : null, // a visitor's own model is their setting
    execution_status: str(r.status, 20), rounds: num(r.rounds), tool_count: Array.isArray(r.tools) ? r.tools.length : undefined,
    retry_count: Array.isArray(r.requests) ? r.requests.filter((q) => q.attempt > 1).length : undefined,
    input_tokens: num(r.usage?.input), output_tokens: num(r.usage?.output), duration_ms: num(r.ms), runtime: str(r.runtime, 20), corpus: str(r.corpus, 20),
    turn_index: num(r.turn),
  };
}

/**
 * A turn's end as the page sends it (web/js/telemetry.js), reduced to the known fields and their limits: which turn (the
 * page's id of it), the visitor's pass, and how it went in words from a short list and counts — never a question, an
 * answer, a tool's arguments, an address or a key.  Null when it is not one.
 */
export function normalizeTurn(r) {
  if (!obj(r) || r.v !== 1 || r.kind !== "turn" || typeof r.turn !== "string" || !TURN_ID.test(r.turn)) return null;
  const word = (v, re) => (typeof v === "string" && re.test(v) ? v : undefined);
  const count = (v, most) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.min(most, Math.floor(v)) : undefined);
  const tools = {};
  if (obj(r.tools)) {
    for (const [name, n] of Object.entries(r.tools).slice(0, 20)) if (/^[a-z][a-z0-9_.]{1,60}$/.test(name) && count(n, 10000)) tools[name] = count(n, 10000);
  }
  const info = {
    provider: providerOf(r.provider), model: word(r.model, /^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,79}$/) ?? null,
    execution_status: word(r.status, /^(?:done|error|stopped)$/), rounds: count(r.rounds, 1000), tool_count: count(r.tool_count, 100000),
    tools: Object.keys(tools).length ? tools : undefined, retry_count: count(r.retries, 1000), input_tokens: count(r.input, 1e9), output_tokens: count(r.output, 1e9),
    duration_ms: count(r.ms, 86400000), runtime: word(r.runtime, /^(?:browser|server)$/), corpus: word(r.corpus, /^[a-z]{1,12}$/),
    module: MODULES.has(r.module) ? r.module : undefined, turn_index: count(r.turn_index, 100000),
    content_consent: r.consent === true ? true : r.consent === false ? false : undefined, ui_lang: word(r.lang, /^[a-z]{2,3}(?:-[A-Za-z]{2,8})?$/),
  };
  return { turn: r.turn, pass: str(r.pass, 120) ?? "", info: JSON.parse(JSON.stringify(info)) };
}

/**
 * POST /v1/activity: from the page's origins, within the ten-second gate, a small body of the known fields, past the
 * sentinel and its own counters — then to the ledger, after the answer.  A question asked of a visitor's own model, or
 * answered by the page itself, never passes the relay: this is the only word of it, and it is the page's.
 */
async function beacon(request, cfg, cors, allowed, deps, s, A) {
  if (!allowed) {
    if (s) note(s, "activity", 403);
    return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  }
  if (!A.L) return error(404, "这里不收使用统计", "activity_off", cors);
  if (await bursting(request, deps)) {
    if (s) note(s, "activity", 429);
    return limited({ reason: "burst" }, ACTIVITY_LIMITS, cors, "提交");
  }
  const raw = await readBody(request, ACTIVITY_MAX_BYTES);
  if (raw === null) return error(413, "内容过大", "too_large", cors);
  let r;
  try { r = JSON.parse(raw); } catch { r = null; }
  const turn = normalizeTurn(r);
  if (!turn) {
    if (s) note(s, "activity", 400);
    return error(400, "格式不对", "bad_activity", cors);
  }
  const a = s ? assess(s.fp, { route: "activity", origins: cfg.origins, ownPrefix: s.cfg.ownPrefix }) : null;
  let gate;
  try {
    gate = await deps.gate({ who: await caller(request, deps.now()), kind: "activity", limits: ACTIVITY_LIMITS, fp: s?.fp, a, cfg: s?.cfg });
  } catch (err) {
    console.error("gate", err?.name || "Error");
    return new Response(null, { status: 204, headers: cors }); // let go: it is not the visitor's concern
  }
  if (s) logLine("relay", s.fp, a, gate.watch, gate.ok ? 204 : gate.reason === "blocked" ? 403 : 429, s.cfg);
  if (!gate.ok) return limited(gate, ACTIVITY_LIMITS, cors, "提交");
  const visitor = A.lcfg.ids === "off" || UNNAMED.has(turn.info.module) ? null : await readPass(turn.pass, A.lcfg.key, A.now);
  deps.defer((async () => deps.ledger.finished(written(A, { fp: s?.fp || A.fp, a, w: gate.watch, status: 204, visitor }), await turnKey(turn.turn, A.lcfg.key), turn.info))());
  return new Response(null, { status: 204, headers: cors });
}

/** A fetch made from the Durable Object at each place in turn (index.js, Egress) until OpenAI does not refuse its
 * region — the last place's answer whatever it is. */
function placed(places, deps) {
  return async (url, init) => {
    let res;
    for (const [i, place] of places.entries()) {
      res = await deps.egress(place, url, init);
      if (res.status !== 403 || i === places.length - 1) return res;
      const text = await res.clone().text().catch(() => "");
      if (!text.includes("unsupported_country_region_territory")) return res;
      await res.body?.cancel();
      console.error("upstream openai region refused from", place);
    }
    return res;
  };
}

// how long the diagnostic waits for the default model's host to answer from one place
const PROBE_MS = 8000;

/** Where a call to the second model comes from, as OpenAI's own edge sees it (Cloudflare's trace on its host: the
 * location and country).  Anyone may ask how it looks from where they are (this Worker runs where the caller is: one
 * request, no secret, nothing of the caller beyond its Cloudflare location) — someone in a region OpenAI refuses can
 * see that it is so.  The rest is the owner's diagnostic, with the collector's token (Bearer LOG_EXPORT_TOKEN): from
 * each place the models may be called from instead, and whether the default model's host answers from each — a dozen
 * requests from several places, seconds waited for each, and where the service calls from: not something anyone may
 * set off or read.  Within the ten-second gate. */
async function egress(request, env, cfg, cors, deps) {
  if (await bursting(request, deps)) return error(429, "请求太频繁，请稍后再试", "rate_limited", { ...cors, "Retry-After": "10" });
  const owner = await authorized(request, env);
  const trace = `${new URL(cfg.openai.upstream).origin}/cdn-cgi/trace`;
  const read = async (pending) => {
    try {
      const res = await pending;
      const text = res.ok ? await res.text() : "";
      const field = (k) => (new RegExp(`^${k}=([A-Za-z0-9-]{1,12})$`, "m").exec(text) || [])[1] || null;
      return res.ok ? { colo: field("colo"), loc: field("loc") } : { error: res.status };
    } catch {
      return { error: "unreachable" };
    }
  };
  const init = { method: "GET", headers: {} };
  const out = { worker: request.cf?.colo || null, direct: await read(deps.fetch(trace, init)) };
  if (!owner) return json(out, 200, cors);
  out.places = {};
  for (const place of cfg.openai.locations) out.places[place] = deps.egress ? await read(deps.egress(place, trace, init)) : null;
  // and the default model's host from each place it is asked from (UPSTREAM_VIA): whether it answers anything at all
  // there, and how soon — no key is sent, and nothing of the host is told
  const host = `${new URL(cfg.upstream).origin}/`;
  out.model = {};
  for (const way of waysOf(cfg.via, deps)) {
    const began = Date.now();
    const got = await ask(way.fetch, host, way.placed ? { ...init, headers: { "X-Tao-Wait": String(PROBE_MS) } } : init, request.signal, PROBE_MS).settled;
    await got.res?.body?.cancel().catch(() => {});
    out.model[way.name] = got.res ? { status: got.res.status, ms: Date.now() - began } : { error: got.silent ? "silent" : "unreachable", ms: Date.now() - began };
  }
  return json(out, 200, cors);
}

// ------------------------------------------------------------------ sponsorship (赞助): visitors' own keys
const SPONSOR_MAX_BYTES = 8192;

/** A visitor gives the service an API key of their own, and the model it is for: from the page's origins, within the
 * ten-second gate and its own counters, of the known fields — then encrypted into the sponsors' book (never the
 * records', which the repository collects).  Nothing of it is logged. */
async function sponsor(request, env, cfg, cors, allowed, deps, s, A) {
  if (!allowed) {
    if (s) note(s, "sponsor", 403);
    return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  }
  if (!cfg.sponsor || !sponsorReady(env)) return error(404, "赞助通道尚未开启", "sponsor_off", cors);
  if (await bursting(request, deps)) {
    if (s) note(s, "sponsor", 429);
    return limited({ reason: "burst" }, cfg.sponsorLimits, cors, "提交");
  }
  const raw = await readBody(request, SPONSOR_MAX_BYTES);
  if (raw === null) return error(413, "赞助信息过大", "too_large", cors);
  let r;
  try { r = JSON.parse(raw); } catch {
    if (s) note(s, "sponsor", 400);
    return error(400, "赞助信息不是有效的 JSON", "bad_sponsor", cors);
  }
  const got = normalizeSponsor(r);
  if (got.error) {
    if (s) note(s, "sponsor", 400);
    return error(400, got.error, "bad_sponsor", cors);
  }
  const a = s ? assess(s.fp, { route: "sponsor", origins: cfg.origins, ownPrefix: s.cfg.ownPrefix }) : null;
  let gate;
  try {
    gate = await deps.gate({ who: await caller(request, deps.now()), kind: "sponsor", limits: cfg.sponsorLimits, fp: s?.fp, a, cfg: s?.cfg });
  } catch (err) {
    console.error("gate", err?.name || "Error");
    return error(503, "赞助暂时无法提交，请稍后再试", "sponsor_unavailable", { ...cors, "Retry-After": "60" });
  }
  if (s) logLine("relay", s.fp, a, gate.watch, gate.ok ? 204 : gate.reason === "blocked" ? 403 : 429, s.cfg);
  if (!gate.ok && gate.reason === "day") {
    return error(429, `今天的赞助提交已达上限（每人每天 ${cfg.sponsorLimits.perDay} 次），明天再来`, "daily_limit", { ...cors, "Retry-After": String(gate.retry || 60) });
  }
  if (!gate.ok) return limited(gate, cfg.sponsorLimits, cors, "提交");
  const kept = await deps.sponsors.add(await sealSponsor(got.sponsor, env.SPONSOR_SECRET, new Date(deps.now()).toISOString()), cfg.sponsorKeep);
  if (kept === null) {
    console.error("sponsors full", cfg.sponsorKeep);
    return error(503, "赞助暂存已满，请稍后再试", "sponsor_full", { ...cors, "Retry-After": "3600" });
  }
  if (A?.L) deps.defer(deps.ledger.logged(written(A, { type: "sponsor_submitted", fp: s?.fp || A.fp, a, w: gate.watch, status: 204 }))); // that one was given: never what
  return new Response(null, { status: 204, headers: cors });
}

/** The owner, by SPONSOR_SECRET (compared in constant time; none set, no one). */
async function sponsorOwner(request, env) {
  const given = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  return sponsorReady(env) && given.length > 0 && (await sameSecret(given, env.SPONSOR_SECRET));
}

/** The sponsorships for the owner: hinted keys; ?reveal=ID, that one's key in full. */
async function sponsors(request, env, url, deps, s) {
  if (!(await sponsorOwner(request, env))) {
    if (s) note(s, "other", 401);
    return error(401, "需要 SPONSOR_SECRET", "unauthorized");
  }
  const reveal = url.searchParams.get("reveal");
  if (reveal === null) return json({ sponsors: await deps.sponsors.list() });
  const row = await deps.sponsors.get(Math.floor(Number(reveal)) || 0);
  if (!row) return error(404, "没有这条赞助", "not_found");
  const { sealed, ...shown } = row;
  const key = await unseal(sealed, env.SPONSOR_SECRET);
  if (key === null) return error(409, "这把密钥无法解密：SPONSOR_SECRET 在它提交后更换过", "unsealable");
  return json({ sponsor: { ...shown, key } });
}

async function unsponsor(request, env, deps, s) {
  if (!(await sponsorOwner(request, env))) {
    if (s) note(s, "other", 401);
    return error(401, "需要 SPONSOR_SECRET", "unauthorized");
  }
  let body;
  try { body = JSON.parse(await request.text()); } catch { return error(400, "请求不是有效的 JSON", "bad_request"); }
  const id = Math.floor(Number(body?.id));
  if (!Number.isFinite(id) || id < 1) return error(400, "缺少 id", "bad_request");
  return json(await deps.sponsors.remove(id));
}

// ------------------------------------------------------------------ the daily counts: the owner's
/** GET /v1/stats: for the holder of the collector's token alone (security/usage.js), and for no page: no CORS headers. */
async function stats(request, env, url, deps) {
  if (await bursting(request, deps)) return error(429, "请求太频繁，请稍后再试", "rate_limited", { "Retry-After": "10" });
  const ucfg = usageConfig(env);
  const today = usageDay(deps.now(), ucfg.offset);
  return serveStats(request, url, { token: env.LOG_EXPORT_TOKEN || "", stats: (days) => deps.stats(days, today), today, offset: ucfg.offset });
}

async function records(request, env, url, deps) {
  if (!(await authorized(request, env))) return error(401, "需要收集令牌", "unauthorized");
  const after = Math.max(0, Math.floor(Number(url.searchParams.get("after") || 0)) || 0);
  const limit = Math.min(1000, Math.max(1, Math.floor(Number(url.searchParams.get("limit") || 500)) || 500));
  const page = await deps.logbook.records(after, limit);
  // with the archive's bucket the records go there (the Durable Object drains them): the repository's collector is told
  return json(env.ARCHIVE ? { ...page, archive: "r2" } : page);
}

async function ack(request, env, deps) {
  if (!(await authorized(request, env))) return error(401, "需要收集令牌", "unauthorized");
  if (env.ARCHIVE) return error(409, "记录由归档取走，这里不再确认", "archived"); // one collector deletes from the book, never two
  let body;
  try { body = JSON.parse(await request.text()); } catch { return error(400, "请求不是有效的 JSON", "bad_request"); }
  const through = Math.floor(Number(body?.through));
  if (!Number.isFinite(through) || through < 1) return error(400, "缺少 through", "bad_request");
  return json(await deps.logbook.remove(through));
}
