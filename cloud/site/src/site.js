// 道乃久 on Cloudflare — the Worker that serves https://chat.impf.ai (cloud/README.md).
//
//   everything but /api/…   the site (taochronos web build: the web client, and the in-browser runtime it falls back on),
//                           over https only: a request over http is redirected
//   GET  /api/info           the full corpus's runtime, answered by the corpus Worker (cloud/corpus: a container running
//   GET  /api/catalog         taochronos on the full corpus, started on demand) through a service binding, when the site
//   GET  /api/passage         has one; else by the D1 backup (./backup: the full corpus in D1, the tools in this Worker)
//   POST /api/call            once its import is complete (D1_BACKUP); without either these answer 503 and the page runs
//   POST /api/research, …     the 要籍语料 in the browser
//   GET  /api/research/<job>, GET /api/session/<id>
//   PUT  /api/store/<sha256>/part-NNN   the full corpus store, uploaded part by part into the site's Workers KV namespace,
//   HEAD /api/store/<sha256>/part-NNN   with the token whose sha256 is STORE_TOKEN_SHA256 (`taochronos web upload`); the
//                                       deploy workflow reads it from there to build the container
//   GET  /api/security/export, POST /api/security/ack, GET /api/security/summary   the sentinel's events and its view of
//                                       the visitors (Bearer LOG_EXPORT_TOKEN); POST /api/security/csp takes the browsers'
//                                       Content-Security-Policy reports
//
// Nothing else reaches the corpus: not the model proxy of `taochronos serve` (the page talks to its models itself, or to
// the relay), not its static files.  API calls are limited per visitor (the rate-limit bindings).  The sentinel
// (security/sentinel.js) sees the pages, the API and what is not found: a scanner path refuses its address for a day, an
// API call that is not the page's is scored and, flagged, kept whole for the owner; addresses are kept only then.

import { assess, fingerprint, ipKey, isHoneypot, logLine, sentinelConfig, serveSecurity } from "../../../security/sentinel.js";
import { answer as backupAnswer, ready as backupReady } from "./backup/api.js";

export const DEFAULTS = {
  ALLOWED_ORIGINS: "https://chat.impf.ai",
  HSTS_MAX_AGE: "86400",
  MAX_BODY_BYTES: "262144",
  STORE_MAX_PART_BYTES: "26214400", // a Workers KV value is at most 25 MiB
  // the pages' Content-Security-Policy, reported and not enforced (security/README.md): empty, none is sent
  CSP_REPORT_ONLY: "",
  // per visitor (an IPv6 address by its /64) per day: reads (passages, catalogs, polls) and calls (tools, research).
  // A reader of a citation-heavy answer takes some 60 passages; the heaviest day seen was 7 turns of 40 tool calls.
  // Many people may share one address (carrier NAT), so these are wide; 0: no cap
  API_READS_PER_DAY: "6000",
  API_CALLS_PER_DAY: "3000",
  // what the page never uses (the clipboard it does: copying an answer stays allowed)
  PERMISSIONS_POLICY: "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
    + "magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), serial=(), usb=(), "
    + "xr-spatial-tracking=(), browsing-topics=()",
};

const GETS = /^\/api\/(?:info|catalog|passage|research\/[A-Za-z0-9_.:-]{1,100}|session\/[A-Za-z0-9_.:-]{1,100})$/;
const POSTS = /^\/api\/(?:call|research)$/;
const STORE = /^\/api\/(store\/[0-9a-f]{64}\/part-\d{3})$/;
const HEX64 = /^[0-9a-f]{64}$/;
const LOCAL = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function config(env = {}) {
  const get = (k) => (env[k] !== undefined && env[k] !== "" ? String(env[k]) : DEFAULTS[k]);
  return {
    origins: get("ALLOWED_ORIGINS").split(",").map((s) => s.trim()).filter(Boolean),
    hsts: Number(get("HSTS_MAX_AGE")),
    maxBody: Number(get("MAX_BODY_BYTES")),
    maxPart: Number(get("STORE_MAX_PART_BYTES")),
    storeToken: String(env.STORE_TOKEN_SHA256 || "").trim().toLowerCase(),
    csp: get("CSP_REPORT_ONLY").trim(),
    permissions: get("PERMISSIONS_POLICY").trim(),
    readsPerDay: Number(get("API_READS_PER_DAY")),
    callsPerDay: Number(get("API_CALLS_PER_DAY")),
  };
}

/**
 * deps: {limit(kind, key) → Promise<boolean>, watch: {observe, blocked, records, remove, summary} | null, defer(promise), now,
 * local: Map} (the rate-limit bindings and the Durable Object in the Worker; plain functions in tests).  Without `watch`,
 * nothing is recorded and the site is what it was.  `local`: what this instance remembers of its readers between round
 * trips to the object (one a minute for a quiet reader, not one a read: the plan counts requests to the objects per day).
 */
export async function handle(request, env, deps = {}) {
  const cfg = config(env);
  const url = new URL(request.url);
  if (url.protocol === "http:" && !LOCAL.has(url.hostname)) {
    url.protocol = "https:";
    return new Response(null, { status: 301, headers: { Location: url.href, "Cache-Control": "max-age=3600" } });
  }
  // the sentinel: the request as seen at the edge, and a note of it when it is worth one (security/sentinel.js)
  const scfg = sentinelConfig(env);
  const now = deps.now ? deps.now() : Date.now();
  const s = deps.watch && scfg.mode !== "off" ? { cfg: scfg, fp: fingerprint(request, now), origins: cfg.origins, self: url.origin, deps, now } : null;
  let response;
  try {
    if (s && isHoneypot(url.pathname)) {
      note(s, "honeypot", 404); // the address is noted — and, HONEYPOT = block, refused the API from now on — after the answer
      response = new Response("Not Found", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
    } else if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      response = await api(request, env, cfg, deps, url, s);
    } else {
      response = await site(request, env, s);
    }
  } catch (err) {
    console.error("site error", err?.name || "Error", err?.message || ""); // never the request: it may carry what a visitor wrote
    response = json({ error: "服务出错了，请稍后再试" }, 500);
  }
  return secure(response, cfg, url.origin);
}

/**
 * A request noted by the sentinel without waiting for it (an answer that needs no decision from it).  A scanner path
 * is reported at once (its address is to be refused); other notes of an address within a minute of its last report are
 * held in this instance (deps.local) and go with the next one, their paths along: a flood of misses costs one object
 * request a minute, not one a miss.
 */
function note(s, route, status) {
  const a = assess(s.fp, { route, origins: s.origins, selfOrigin: s.self, ownPrefix: s.cfg.ownPrefix });
  logLine("site", s.fp, a, null, status, s.cfg);
  const local = s.deps.local || (s.deps.local = new Map());
  const who = ipKey(s.fp.ip);
  let l = local.get(who);
  if (!l) {
    if (local.size >= 5000) local.delete(local.keys().next().value);
    l = { at: 0, reads: 0, today: 0, blockedUntil: 0, notedAt: 0, notes: 0, paths: [] };
    local.set(who, l);
  }
  if (route !== "honeypot" && l.notedAt && s.now - l.notedAt < 60000) {
    l.notes += 1;
    if (status === 404 && l.paths.length < 20 && !l.paths.includes(s.fp.path)) l.paths.push(s.fp.path);
    return;
  }
  const extra = { status, count: 1 + l.notes, paths: l.paths };
  l.notedAt = s.now; l.notes = 0; l.paths = [];
  s.deps.defer(s.deps.watch.observe(s.fp, a, extra, s.cfg));
}

const BLOCKED = "该地址因异常访问已被暂时限制，请稍后再试";

// ------------------------------------------------------------------ the site
async function site(request, env, s) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    if (s) note(s, "page", 405);
    return new Response("Method Not Allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
  }
  const res = await env.ASSETS.fetch(request);
  if (s) {
    // a page asked for by what is not a browser, or a file that is not there (a probe, or a link gone stale): noted
    if (res.status === 404) note(s, "other", 404);
    else if (assess(s.fp, { route: "page", ownPrefix: s.cfg.ownPrefix }).score >= 1) note(s, "page", res.status);
  }
  return res;
}

/** The headers every answer carries: https from now on, no sniffing, no framing by other sites, no device features;
 * on the pages, their own browsing context (no other page holds a handle to them) and the policy reported on
 * (CSP_REPORT_ONLY) with where to report it. */
function secure(response, cfg, origin) {
  const res = new Response(response.body, response);
  if (cfg.hsts > 0) res.headers.set("Strict-Transport-Security", `max-age=${cfg.hsts}`);
  res.headers.set("X-Content-Type-Options", "nosniff");
  res.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  if (cfg.permissions) res.headers.set("Permissions-Policy", cfg.permissions);
  if ((res.headers.get("Content-Type") || "").startsWith("text/html")) {
    res.headers.set("X-Frame-Options", "SAMEORIGIN");
    res.headers.set("Cross-Origin-Opener-Policy", "same-origin");
    res.headers.set("Cross-Origin-Resource-Policy", "same-origin");
    if (cfg.csp) {
      res.headers.set("Content-Security-Policy-Report-Only", cfg.csp);
      if (/report-to\s+csp\b/.test(cfg.csp)) res.headers.set("Reporting-Endpoints", `csp="${origin}/api/security/csp"`);
    }
  }
  return res;
}

// ------------------------------------------------------------------ the API
const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

async function api(request, env, cfg, deps, url, s) {
  const origin = request.headers.get("Origin");
  const allowed = !origin || origin === url.origin || cfg.origins.includes(origin);
  const cors = origin && allowed ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : { Vary: "Origin" };
  if (request.method === "OPTIONS") {
    if (!allowed) return new Response(null, { status: 403, headers: cors });
    return new Response(null, { status: 204, headers: { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
  }
  if (url.pathname.startsWith("/api/security/")) { // before the origin check: a browser's report may come with none
    if (!s) return url.pathname === "/api/security/csp" ? new Response(null, { status: 204 }) : json({ error: "no such endpoint" }, 404, cors);
    if (url.pathname === "/api/security/csp" && deps.limit && !(await deps.limit("call", ipKey(s.fp.ip)))) return new Response(null, { status: 429, headers: { "Retry-After": "60" } });
    const res = await serveSecurity(request, url, { prefix: "/api/security", token: env.LOG_EXPORT_TOKEN || "", watch: deps.watch, cfg: s.cfg, fp: s.fp,
      now: s.now, cors });
    if (res) return res;
  }
  if (!allowed) {
    if (s) note(s, "api-call", 403);
    return json({ error: `origin ${origin} may not call this API` }, 403, cors);
  }
  const who = ipKey(request.headers.get("CF-Connecting-IP") || "unknown"); // an IPv6 address by its /64
  const store = url.pathname.match(STORE);
  if (store) {
    if (deps.limit && !(await deps.limit("call", who))) return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { "Retry-After": "60" });
    return storePart(request, env, cfg, store[1]);
  }
  const isGet = request.method === "GET" || request.method === "HEAD";
  if (!(isGet && GETS.test(url.pathname)) && !(request.method === "POST" && POSTS.test(url.pathname))) {
    if (s) note(s, "other", 404);
    return json({ error: `no such endpoint ${request.method} ${url.pathname}` }, 404, cors);
  }
  const route = isGet ? "api-read" : "api-call";
  if (deps.limit && !(await deps.limit(isGet ? "read" : "call", who))) {
    if (s) note(s, route, 429);
    return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { ...cors, "Retry-After": "60" });
  }
  if (s) {
    // every API call is seen by the sentinel: an address it refuses gets nothing from the corpus, and one over its
    // day's reads or calls waits for tomorrow.  A call, and a reader's first request, wait for the object; a quiet
    // reader's further requests within the minute are counted here and reported with the next round trip
    const a = assess(s.fp, { route, origins: cfg.origins, selfOrigin: url.origin, ownPrefix: s.cfg.ownPrefix });
    const verdict = await consult(deps, s, a, who, isGet, cfg);
    // refused as 503, which the page takes as the corpus being away and falls back on the 要籍语料 in the browser — not as
    // an answer about the passage (a 403 or 429 would be shown as "no such passage")
    logLine("site", s.fp, a, verdict.w, verdict.blocked || verdict.over ? 503 : null, s.cfg);
    if (verdict.blocked) return json({ error: BLOCKED, blocked: true, starting: false }, 503, { ...cors, "Retry-After": String(verdict.retry || 60), "X-TC-Corpus": "refused" });
    if (verdict.over) return json({ error: "今天的查询次数已用完，明天再来", rate_limited: true, daily: true, starting: false }, 503, { ...cors, "Retry-After": String(secondsToMidnight(s.now)), "X-TC-Corpus": "refused" });
  }
  if (!env.CORPUS && !backupReady(env)) {
    return json({ error: "本站的全量语料服务未部署：网页在浏览器里运行要籍语料", corpus: "none" }, 503, cors);
  }
  const headers = { Accept: "application/json" };
  let body;
  if (!isGet) {
    const declared = Number(request.headers.get("Content-Length") || "NaN");
    if (declared > cfg.maxBody) return json({ error: "请求太大" }, 413, cors);
    body = await request.arrayBuffer();
    if (body.byteLength > cfg.maxBody) return json({ error: "请求太大" }, 413, cors);
    headers["Content-Type"] = "application/json";
  }
  if (!env.CORPUS) {
    // no container: the D1 backup answers (the full corpus in D1, the tools in this Worker; ./backup)
    const res = await backupAnswer(request.method, url, body, env);
    const out = new Response(res.body, { status: res.status, headers: { ...cors, "Cache-Control": "no-store" } });
    for (const h of ["Content-Type", "X-TC-Corpus"]) if (res.headers.has(h)) out.headers.set(h, res.headers.get(h));
    return out;
  }
  // only the path, the query and the body go on: not the visitor's cookies, address or other headers
  let upstream;
  try {
    upstream = await env.CORPUS.fetch(new Request(`https://corpus.internal${url.pathname}${url.search}`, { method: request.method, headers, body }));
  } catch (err) {
    // the corpus Worker failed: the page falls back on a 503 (and runs the 要籍语料 in the browser)
    console.error("corpus", err?.message || err);
    return json({ error: "全量语料服务暂不可用，请稍后再试", starting: true }, 503, { ...cors, "Retry-After": "10" });
  }
  let out = upstream.body;
  if (upstream.status >= 500) {
    // the corpus's own words of a failure may name its code and tables: the page is told what it can act on, the rest
    // of the answer (starting, corpus, …) stays as the page reads it
    const text = await upstream.text().catch(() => "");
    let j = null;
    try { j = JSON.parse(text); } catch { /* not JSON */ }
    out = JSON.stringify({ ...(j && typeof j === "object" && !Array.isArray(j) ? j : {}), error: "全量语料服务出错了，请稍后再试" });
  }
  const res = new Response(out, { status: upstream.status, headers: { ...cors, "Cache-Control": "no-store" } });
  res.headers.set("Content-Type", upstream.status >= 500 ? "application/json; charset=utf-8" : upstream.headers.get("Content-Type") || "application/json; charset=utf-8");
  for (const h of ["X-TC-Corpus", "Retry-After"]) if (upstream.headers.has(h)) res.headers.set(h, upstream.headers.get(h));
  return res;
}

const secondsToMidnight = (now) => Math.ceil((86400000 - (now % 86400000)) / 1000);

/**
 * The sentinel's word on an API request: {w, blocked, retry, over}.  deps.local (a Map, this instance's) remembers per
 * address the last round trip and the reads since; a quiet reader (score 0) within the minute is answered from it.  The
 * object out of reach — its day's allowance spent, or a failure — lets reads go on (the rate-limit bindings stand) and
 * logs it: the site fails open, the page's fallback is the browser.
 */
async function consult(deps, s, a, who, isGet, cfg) {
  const local = deps.local || (deps.local = new Map());
  let l = local.get(who);
  if (!l) {
    if (local.size >= 5000) local.delete(local.keys().next().value);
    l = { at: 0, reads: 0, today: 0, blockedUntil: 0, notedAt: 0, notes: 0, paths: [] };
    local.set(who, l);
  }
  const route = isGet ? "api-read" : "api-call";
  const cap = isGet ? cfg.readsPerDay : cfg.callsPerDay;
  const sameDay = Math.floor(l.at / 86400000) === Math.floor(s.now / 86400000);
  if (isGet && a.score < 1 && l.at && s.now - l.at < 60000 && sameDay) {
    l.reads += 1;
    return { w: null, blocked: l.blockedUntil > s.now, retry: Math.ceil((l.blockedUntil - s.now) / 1000), over: cap > 0 && l.today + l.reads > cap };
  }
  let w = null;
  try {
    // a read reports the reads counted here since the last round trip; a call reports itself (the reads wait for the next read)
    w = await deps.watch.observe(s.fp, a, { status: null, count: isGet && sameDay ? 1 + l.reads : 1 }, s.cfg);
  } catch (err) {
    console.error("sentinel", err?.name || "Error");
  }
  if (isGet) { l.at = s.now; l.reads = 0; }
  if (!w) return { w: null, blocked: false, retry: 0, over: false };
  if (isGet) l.today = Number(w.today?.["api-read"] || 0);
  l.blockedUntil = w.blocked ? w.until : 0;
  return { w, blocked: w.blocked, retry: w.retry, over: cap > 0 && Number(w.today?.[route] || 0) > cap };
}

// ------------------------------------------------------------------ the store's upload
const encoder = new TextEncoder();
const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function tokenOk(request, expected) {
  if (!HEX64.test(expected)) return false;
  const given = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!given) return false;
  const digest = hex(await crypto.subtle.digest("SHA-256", encoder.encode(given)));
  let diff = 0;
  for (let i = 0; i < 64; i++) diff |= digest.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

async function storePart(request, env, cfg, key) {
  if (!env.STORE || !HEX64.test(cfg.storeToken)) return json({ error: "uploads are off here" }, 404);
  if (!(await tokenOk(request, cfg.storeToken))) return json({ error: "a valid token is required" }, 401);
  if (request.method === "HEAD" || request.method === "GET") {
    const { keys } = await env.STORE.list({ prefix: key, limit: 1 });
    const hit = keys.find((k) => k.name === key);
    if (!hit) return json({ error: "no such part" }, 404);
    return new Response(null, { status: 200, headers: { "X-Content-Length": String(hit.metadata?.size ?? ""), "X-Content-SHA256": hit.metadata?.sha256 || "" } });
  }
  if (request.method !== "PUT") return json({ error: "PUT or HEAD" }, 405, { Allow: "PUT, HEAD" });
  const size = Number(request.headers.get("Content-Length") || "NaN");
  if (!Number.isFinite(size) || size <= 0) return json({ error: "Content-Length is required" }, 411);
  if (size > cfg.maxPart) return json({ error: `a part is at most ${cfg.maxPart} bytes` }, 413);
  const sha256 = (request.headers.get("X-Content-SHA256") || "").toLowerCase();
  if (!HEX64.test(sha256)) return json({ error: "X-Content-SHA256 (hex) is required" }, 400);
  // the bytes stream straight into KV; the workflow checks each part against cloud/store.json when it reads it back
  await env.STORE.put(key, request.body, { metadata: { sha256, size } });
  return json({ key, size }, 201);
}
