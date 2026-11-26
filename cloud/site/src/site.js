// 道乃久 on Cloudflare — the Worker that serves https://chat.impf.ai (cloud/README.md).
//
//   everything but /api/…   the site (taochronos web build: the web client, and the in-browser runtime it falls back on),
//                           over https only: a request over http is redirected
//   GET  /api/info           the full corpus's runtime, answered by the corpus Worker (cloud/corpus: a container running
//   GET  /api/catalog         taochronos on the full corpus, started on demand) through a service binding, when the site
//   GET  /api/passage         has one; else by the D1 backup (./backup: the full corpus in D1, the tools in this Worker)
//   POST /api/call            once its import is complete (D1_BACKUP); without either these answer 503 and the page runs
//   POST /api/research, …     the 要籍语料 in the browser
//   GET  /api/research/<job>, POST /api/research/<job>/cancel|resume, GET /api/session/<id>
//   PUT  /api/store/<sha256>/part-NNN   the full corpus store, uploaded part by part into the site's Workers KV namespace,
//   HEAD /api/store/<sha256>/part-NNN   with the token whose sha256 is STORE_TOKEN_SHA256 (`taochronos web upload`); the
//                                       deploy workflow reads it from there to build the container
//   GET  /api/security/export, POST /api/security/ack, GET /api/security/summary   the sentinel's events and its view of
//                                       the visitors (Bearer LOG_EXPORT_TOKEN); POST /api/security/csp takes the browsers'
//                                       Content-Security-Policy reports; GET /api/security/archive?day=, a day of the
//                                       events archived in the private bucket ARCHIVE, when the site has one (then the
//                                       events go there, not to the repository: security/archive.js)
//   POST /api/activity/hello            the page, once it has loaded: who its visitor is to the activity ledger (a pass
//   POST /api/activity/choice, forget   for the relay; security/visitor.js), and the visitor's own switches — the count
//   GET  /api/activity/me               off or on, everything of theirs forgotten, what is held of them
//   GET  /api/activity/stats            the ledger's counts for the 统计 pane and the daily reports (the stats token);
//   GET  /api/activity/health, archive  how its pipeline stands and whether a day of its archive is whole (Bearer
//                                       LOG_EXPORT_TOKEN) — security/ledger.js, security/ledger-d1.js
//
// Nothing else reaches the corpus: not the model proxy of `taochronos serve` (the page talks to its models itself, or to
// the relay), not its static files.  API calls are limited per visitor (the rate-limit bindings).  The sentinel
// (security/sentinel.js) sees the pages, the API and what is not found: a scanner path refuses its address for a day, an
// API call that is not the page's is scored and, flagged, kept whole for the owner; addresses are kept only then.
// A request the page of another site made a reader's browser send (ledFrom) is none of the reader's doing: the API
// answers it 403, a path that is not there 404, and nothing of it is counted or kept against the address — only the
// site's own pages are served to it, as to anyone who follows a link.
//
// A refusal says so (docs/adr/0023-workers-paid.md): an address the sentinel refuses is answered 403, a day's reads or
// calls spent 429, each with Retry-After and X-TC-Corpus: refused; 503 is kept for a corpus that cannot answer.  The page
// carries on with the 要籍语料 in the browser either way — public files, not a way round the refusal — and says which.
// A call or a research run (work the account pays for) is not let through while the sentinel cannot be asked.
//
// The activity ledger (security/ledger.js), when the Worker has its key (ACTIVITY_KEY) and its registry (ACTIVITY_DB):
// every request is written down as an event — a page opened, the API read or called, what was refused — whatever the
// sentinel scored it, with a visitor's id where the browser has one and never an address.  It decides nothing and is
// never waited for: without it, or when it fails, the site is what it was.

import { EVENTS, serveArchive } from "../../../security/archive.js";
import { envelope, verifyArchive } from "../../../security/ledger.js";
import { ensure, forget, known, serveLedgerStats } from "../../../security/ledger-d1.js";
import { assess, bearerOk, fingerprint, ipKey, isHoneypot, keptPath, ledFrom, logLine, readText, sentinelConfig, serveSecurity, WatchCore } from "../../../security/sentinel.js";
import { place, serveStats, usageConfig, usageDay } from "../../../security/usage.js";
import { clearCookie, identify, ledgerConfig, OFF, passFor, setCookie } from "../../../security/visitor.js";
import { answer as backupAnswer, ready as backupReady } from "./backup/api.js";

export const DEFAULTS = {
  ALLOWED_ORIGINS: "https://chat.impf.ai",
  HSTS_MAX_AGE: "86400",
  MAX_BODY_BYTES: "262144",
  STORE_MAX_PART_BYTES: "26214400", // a Workers KV value is at most 25 MiB
  // the pages' Content-Security-Policy (security/README.md): CSP enforced, CSP_REPORT_ONLY reported and not enforced;
  // empty, none is sent
  CSP: "",
  CSP_REPORT_ONLY: "",
  // per visitor (an IPv6 address by its /64) per day: reads (passages, catalogs, polls) and calls (tools, research).
  // A reader of a citation-heavy answer takes some 60 passages; the heaviest day seen was 7 turns of 40 tool calls.
  // Many people may share one address (carrier NAT), so these are wide; 0: no cap
  API_READS_PER_DAY: "6000",
  API_CALLS_PER_DAY: "3000",
  // research runs started per visitor per day: the corpus runs one at a time, a minute or two each, and holds only so
  // many waiting (src/taochronos/chat/jobs.py) — an address that could start thousands would keep everyone else out
  API_RESEARCH_PER_DAY: "100",
  // what the page never uses (the clipboard it does: copying an answer stays allowed)
  PERMISSIONS_POLICY: "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
    + "magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), serial=(), usb=(), "
    + "xr-spatial-tracking=(), browsing-topics=()",
};

const GETS = /^\/api\/(?:info|catalog|passage|research\/[A-Za-z0-9_.:-]{1,100}|session\/[A-Za-z0-9_.:-]{1,100})$/;
const POSTS = /^\/api\/(?:call|research(?:\/[A-Za-z0-9_.:-]{1,100}\/(?:cancel|resume))?)$/;
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
    csp: get("CSP").trim(),
    cspReportOnly: get("CSP_REPORT_ONLY").trim(),
    permissions: get("PERMISSIONS_POLICY").trim(),
    readsPerDay: Number(get("API_READS_PER_DAY")),
    callsPerDay: Number(get("API_CALLS_PER_DAY")),
    researchPerDay: Number(get("API_RESEARCH_PER_DAY")),
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
  const fp = fingerprint(request, now);
  const s = deps.watch && scfg.mode !== "off" ? { cfg: scfg, fp, origins: cfg.origins, self: url.origin, deps, now } : null;
  // the page of another site that made a browser send this, if one did: read whether or not the sentinel records —
  // what the API refuses it is a rule of access, not a note
  const from = ledFrom(fp, cfg.origins, url.origin);
  if (s) s.led = from;
  // the activity ledger: on with its key, its registry and the object that keeps its outbox.  `mark` is what this
  // request will be written down as (the branch that answers it says; anything else is a `request`), `who` its visitor
  const lcfg = ledgerConfig(env);
  const L = lcfg.on && env.ACTIVITY_DB && deps.watch?.activity
    ? { cfg: lcfg, db: env.ACTIVITY_DB, fp, now, deps, led: from, flagScore: scfg.flagScore, offset: usageConfig(env).offset, began: Date.now(), mark: null, who: null }
    : null;
  if (L) L.identify = (mintable = false) => (L.who ||= identify(request, lcfg, now, { mintable }));
  if (s) s.L = L;
  let response;
  try {
    if (s && isHoneypot(url.pathname)) {
      // the address is noted — and, HONEYPOT = block, refused the API from now on — after the answer (not a reader's
      // whom another site's page sent here: note)
      note(s, "honeypot", 404);
      response = new Response("Not Found", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
    } else if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      response = await api(request, env, cfg, deps, url, s, from, L);
    } else {
      response = await site(request, env, s, L, url, cfg);
    }
  } catch (err) {
    console.error("site error", err?.name || "Error", err?.message || ""); // never the request: it may carry what a visitor wrote
    response = json({ error: "服务出错了，请稍后再试" }, 500);
  }
  if (L) {
    try {
      record(L, L.mark || { type: "request", route: "other" }, response.status);
    } catch (err) {
      console.error("ledger", err?.name || "Error"); // never in an answer's way
    }
  }
  return secure(response, cfg, url.origin);
}

// ------------------------------------------------------------------ the activity ledger
const LEDGER_MS = 2000;   // events are held this long in the instance, and go to the object together
const LEDGER_HELD = 500;  // at most: beyond, they are counted as lost (the object has been out of reach)

/**
 * A request written down for the ledger (security/ledger.js: envelope), held in this instance (deps.ledger) and sent to
 * the object a moment later with the others of that moment, after the answer.  m: {type, route, a, w, visitor, more,
 * sum, page} — sum: a reader's like requests of the minute are one line with their number (a citation-heavy answer
 * reads sixty passages); page: a page a visitor opened, which another site's link may have led to.  An event that could
 * not be brought to the object is counted, and the count goes with the next that can.
 */
function record(L, m, status) {
  const latency = Date.now() - L.began;
  const event = envelope({ type: m.type, source: "site", fp: L.fp, a: m.a || null, w: m.w || null, led: m.page ? null : L.led, status, visitor: m.visitor || null,
    now: L.now, offset: L.offset, route: m.route, latency, flagScore: L.flagScore, more: m.more || {} });
  const b = L.deps.ledger || (L.deps.ledger = { events: [], sums: new Map(), pending: false, lost: 0 });
  if (b.events.length + b.sums.size >= LEDGER_HELD) b.lost += 1;
  else if (m.sum) {
    const key = [Math.floor(L.now / 60000), event.event_type, event.visitor_id, event.route, event.status, event.traffic_class, event.security_action, event.country, event.region].join("|");
    const held = b.sums.get(key);
    if (held) { held.event.n += 1; held.ms += latency; } else b.sums.set(key, { event, ms: latency });
  } else b.events.push(event);
  if (b.pending) return;
  b.pending = true;
  const moment = L.deps.batch ? L.deps.batch() : new Promise((resolve) => setTimeout(resolve, LEDGER_MS)); // a test says when
  L.deps.defer((async () => {
    await moment;
    const events = [...b.events, ...[...b.sums.values()].map((h) => ({ ...h.event, latency_ms: Math.round(h.ms / h.event.n) }))];
    const lost = b.lost;
    b.events = [];
    b.sums = new Map();
    b.pending = false;
    b.lost = 0;
    try {
      await L.deps.watch.activity(events, lost);
    } catch (err) {
      b.lost += lost + events.reduce((n, e) => n + (e.n || 1), 0);
      console.error("ledger", err?.name || "Error");
    }
  })());
}

/** A page's address as the ledger keeps it — "/", "/about", "/attribution" — or null for what is not one of the pages. */
function pageRoute(pathname) {
  const m = /^\/(index|about|attribution)?(?:\.html)?$/.exec(pathname);
  return m ? (m[1] && m[1] !== "index" ? `/${m[1]}` : "/") : null;
}

/**
 * A request noted by the sentinel without waiting for it (an answer that needs no decision from it).  A scanner path
 * is reported at once (its address is to be refused); other notes of an address within a minute of its last report are
 * held in this instance (deps.local) and go with the next one, their paths along: a flood of misses costs one object
 * request a minute, not one a miss.
 */
function note(s, route, status) {
  if (s.led) return led(s, route, status); // none of the reader's doing: not noted
  const a = assess(s.fp, { route, origins: s.origins, selfOrigin: s.self, ownPrefix: s.cfg.ownPrefix });
  if (s.L) s.L.mark = s.L.mark ? { ...s.L.mark, a } : { type: "request", route, a };
  logLine("site", s.fp, a, null, status, s.cfg);
  const local = s.deps.local || (s.deps.local = new Map());
  const who = ipKey(s.fp.ip);
  let l = local.get(who);
  if (!l) {
    if (local.size >= 5000) local.delete(local.keys().next().value);
    l = { at: 0, reads: 0, today: 0, blockedUntil: 0, notedAt: 0, notes: 0, paths: [] };
    local.set(who, l);
  }
  // a scanner path: what this instance remembered of the address no longer stands — its next read waits for the object,
  // which refuses it from now on (HONEYPOT = block)
  if (route === "honeypot") l.at = 0;
  if (route !== "honeypot" && l.notedAt && s.now - l.notedAt < 60000) {
    l.notes += 1;
    if (status === 404 && l.paths.length < 20 && !l.paths.includes(s.fp.path)) l.paths.push(s.fp.path);
    return;
  }
  const extra = { status, count: 1 + l.notes, paths: l.paths };
  l.notedAt = s.now; l.notes = 0; l.paths = [];
  s.deps.defer(s.deps.watch.observe(s.fp, a, extra, s.cfg));
}

/** A request another site's page made a browser send (s.led: that page's origin): a line in the Worker's log, without
 * the address, and nothing kept or counted against it. */
function led(s, route, status) {
  logLine("site", s.fp, { route, score: 0, reasons: ["led"], led: s.led }, null, status, s.cfg);
}

const BLOCKED = "该地址因异常访问已被暂时限制，请稍后再试";

// ------------------------------------------------------------------ the site
async function site(request, env, s, L, url, cfg) {
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
  if (!s && !L) return res;
  // a page a browser opened (only the pages come through this Worker: run_worker_first) is counted for the 统计 pane —
  // one a visitor came to by a link too, not one another site's page loaded as its image or its frame; and one the
  // browser already holds and asks about (304: it is shown from the browser's copy) as much as one sent anew
  const fp = s?.fp || L.fp;
  const from = s ? s.led : L.led;
  const route = pageRoute(url.pathname);
  const opened = !from || (fp.sfDest ? fp.sfDest === "document" : /text\/html/.test(fp.accept || ""));
  const page = request.method === "GET" && (res.status === 200 || (res.status === 304 && route !== null)) && fp.uaClass === "browser" && opened;
  if (page && s?.deps.watch?.usage) tally(s, env);
  if (L && page && route !== null) {
    // the ledger's page view, for the visitor the browser's cookie names — or the one it is given now (visitor.js)
    const who = await L.identify(true);
    const came = fp.referer && /^https?:\/\//.test(fp.referer) && fp.referer !== url.origin && !cfg.origins.includes(fp.referer) ? fp.referer.slice(0, 120) : null;
    L.mark = { type: "page_view", route, page: true, a: L.mark?.a || assess(fp, { route: "page", ownPrefix: sentinelConfig(env).ownPrefix }), visitor: who.visitor,
      more: { ...(came ? { referrer: came } : {}), ...(who.state === "new" ? { new_visitor: true } : {}) } };
    if (who.cookie) {
      const out = new Response(res.body, res);
      out.headers.append("Set-Cookie", who.cookie);
      return out;
    }
  }
  return res;
}

// ------------------------------------------------------------------ the counts for the settings' 统计 pane
const BATCH_MS = 15000;

/**
 * A page opened, counted by day and place (security/usage.js) — held in this instance (deps.usage) and sent to the
 * object a moment later with the others of that moment, after the answer: the visitor never waits for it.  The visitor is
 * counted once a day by the sentinel's hashed key; the address itself never leaves the instance.
 */
function tally(s, env) {
  const u = s.deps.usage || (s.deps.usage = { counts: new Map(), visitors: new Map(), pending: false });
  const offset = usageConfig(env).offset;
  const day = usageDay(s.now, offset);
  const { country, region } = place(s.fp);
  const key = `${day}|${country}|${region}`;
  u.counts.set(key, (u.counts.get(key) || 0) + 1);
  const visitor = `${day}|${ipKey(s.fp.ip)}`;
  if (!u.visitors.has(visitor) && u.visitors.size < 5000) u.visitors.set(visitor, { day, country, region, ip: s.fp.ip });
  if (u.pending) return;
  u.pending = true;
  const moment = s.deps.batch ? s.deps.batch() : new Promise((resolve) => setTimeout(resolve, BATCH_MS)); // a test says when
  s.deps.defer((async () => {
    await moment;
    const counts = [...u.counts].map(([k, n]) => { const [d, c, r] = k.split("|"); return { day: d, kind: "view", country: c, region: r, n }; });
    const visitors = [...u.visitors.values()];
    u.counts = new Map();
    u.visitors = new Map();
    u.pending = false;
    const seen = [];
    for (const v of visitors) seen.push({ day: v.day, kind: "visitor", who: await WatchCore.who(v.ip, s.cfg, s.now), country: v.country, region: v.region });
    await s.deps.watch.usage(counts, seen, usageDay(s.now, offset));
  })());
}

/** The headers every answer carries: https from now on, no sniffing, no framing by other sites, no device features;
 * on the pages, their own browsing context (no other page holds a handle to them), the policy enforced (CSP) and the
 * stricter one reported on (CSP_REPORT_ONLY), with where to report them. */
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
    if (cfg.csp) res.headers.set("Content-Security-Policy", cfg.csp);
    if (cfg.cspReportOnly) res.headers.set("Content-Security-Policy-Report-Only", cfg.cspReportOnly);
    if ([cfg.csp, cfg.cspReportOnly].some((p) => /report-to\s+csp\b/.test(p))) {
      res.headers.set("Reporting-Endpoints", `csp="${origin}/api/security/csp"`);
    }
  }
  return res;
}

// ------------------------------------------------------------------ the API
const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

async function api(request, env, cfg, deps, url, s, from = null, L = null) {
  const origin = request.headers.get("Origin");
  const allowed = !origin || origin === url.origin || cfg.origins.includes(origin);
  const cors = origin && allowed ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : { Vary: "Origin" };
  if (request.method === "OPTIONS") {
    if (!allowed) return new Response(null, { status: 403, headers: cors });
    return new Response(null, { status: 204, headers: { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
  }
  if (from) { // another site's page made the browser ask: nothing is answered, and nothing counted against the reader
    if (s) led(s, "api", 403);
    return json({ error: "this API answers the site's own pages only" }, 403, cors);
  }
  if (url.pathname.startsWith("/api/security/")) { // before the origin check: a browser's report may come with none
    if (!s) return url.pathname === "/api/security/csp" ? new Response(null, { status: 204 }) : json({ error: "no such endpoint" }, 404, cors);
    if (url.pathname === "/api/security/csp" && deps.limit && !(await deps.limit("call", ipKey(s.fp.ip)))) return new Response(null, { status: 429, headers: { "Retry-After": "60" } });
    if (url.pathname === "/api/security/archive") return serveArchive(request, url, { bucket: env.ARCHIVE, prefix: EVENTS("site"), token: env.LOG_EXPORT_TOKEN || "", cors });
    const res = await serveSecurity(request, url, { prefix: "/api/security", token: env.LOG_EXPORT_TOKEN || "", watch: deps.watch, cfg: s.cfg, fp: s.fp,
      now: s.now, cors, archived: Boolean(env.ARCHIVE) });
    if (res) return res;
  }
  if (!allowed) {
    if (s) note(s, "api-call", 403);
    return json({ error: `origin ${origin} may not call this API` }, 403, cors);
  }
  const who = ipKey(request.headers.get("CF-Connecting-IP") || "unknown"); // an IPv6 address by its /64
  if (url.pathname.startsWith("/api/activity/")) return activity(request, env, deps, url, L, cors, who);
  const store = url.pathname.match(STORE);
  if (store) {
    if (deps.limit && !(await deps.limit("call", who))) return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { "Retry-After": "60" });
    return storePart(request, env, cfg, store[1]);
  }
  if (url.pathname === "/api/stats") { // the counts for the settings' 统计 pane: the stats token's holder (security/usage.js)
    if (deps.limit && !(await deps.limit("read", who))) return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { ...cors, "Retry-After": "60" });
    if (!deps.watch?.stats) return json({ error: "这里没有统计" }, 404, cors);
    const ucfg = usageConfig(env);
    const today = usageDay(deps.now ? deps.now() : Date.now(), ucfg.offset);
    return serveStats(request, url, { cfg: ucfg, stats: (days) => deps.watch.stats(days, today), cors, today });
  }
  const isGet = request.method === "GET" || request.method === "HEAD";
  if (!(isGet && GETS.test(url.pathname)) && !(request.method === "POST" && POSTS.test(url.pathname))) {
    if (s) note(s, "other", 404);
    return json({ error: `no such endpoint ${request.method} ${url.pathname}` }, 404, cors);
  }
  const route = isGet ? "api-read" : url.pathname === "/api/research" ? "api-research" : "api-call";
  // to the ledger: a read (a reader's like reads of the minute are one line), a call, or a research run begun — for the
  // visitor the browser's cookie names; a refusal below is the same event with its status
  if (L) {
    L.mark = { type: isGet ? "api_read" : route === "api-research" ? "research_started" : "api_call", route: keptPath(url.pathname),
      visitor: (await L.identify()).visitor, sum: isGet };
  }
  if (deps.limit && !(await deps.limit(isGet ? "read" : "call", who))) {
    if (s) note(s, route, 429);
    return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { ...cors, "Retry-After": "60" });
  }
  if (s) {
    // every API call is seen by the sentinel: an address it refuses gets nothing from the corpus, and one over its
    // day's reads or calls waits for tomorrow.  A call, and a reader's first request, wait for the object; a quiet
    // reader's further requests within the minute are counted here and reported with the next round trip
    const a = assess(s.fp, { route, origins: cfg.origins, selfOrigin: url.origin, ownPrefix: s.cfg.ownPrefix });
    const verdict = await consult(deps, s, a, who, isGet, route === "api-research" ? cfg.researchPerDay : isGet ? cfg.readsPerDay : cfg.callsPerDay);
    // a refusal is told as one (the page carries on in the browser and says why: web/js/runtime.js); a call while the
    // sentinel cannot be asked is the site's failure, not the visitor's (503: the page carries on in the browser too)
    const status = verdict.blocked ? 403 : verdict.over ? 429 : verdict.unavailable ? 503 : null;
    logLine("site", s.fp, a, verdict.w, status, s.cfg);
    if (L) Object.assign(L.mark, { a, w: verdict.w });
    if (verdict.blocked) return json({ error: BLOCKED, blocked: true, starting: false }, 403, { ...cors, "Retry-After": String(verdict.retry || 60), "X-TC-Corpus": "refused" });
    // a day's research runs spent is the run's refusal, not the corpus's: the page goes on reading and calling it
    if (verdict.over && route === "api-research") return json({ error: `今天从这个地址发起的研究已达上限（每天 ${cfg.researchPerDay} 次），明天再来`, rate_limited: true, research_daily: true }, 429, { ...cors, "Retry-After": String(secondsToMidnight(s.now)) });
    if (verdict.over) return json({ error: "今天的查询次数已用完，明天再来", rate_limited: true, daily: true, starting: false }, 429, { ...cors, "Retry-After": String(secondsToMidnight(s.now)), "X-TC-Corpus": "refused" });
    if (verdict.unavailable) return json({ error: "全量语料服务暂时无法核对访问，请稍后再试", starting: false }, 503, { ...cors, "Retry-After": "30" });
  }
  if (!env.CORPUS && !backupReady(env)) {
    return json({ error: "本站的全量语料服务未部署：网页改用内置运行环境的要籍语料", corpus: "none" }, 503, cors);
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

// ------------------------------------------------------------------ the activity ledger's endpoints
const LANG = /^[a-z]{2,3}(?:-[A-Za-z]{2,8})?$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TABLES = ["visitors", "visitor_daily_activity", "sessions", "activity_events", "question_events", "model_invocations", "daily_metrics", "archive_manifest",
  "ledger_dirty", "deletion_log"];

/**
 * Under /api/activity/ (the site's own pages and the owner's tools; another site's page was refused before this):
 *
 *   POST hello          the page, once loaded: {ids, state, visitor, pass, expires} — the mode the ledger runs in, what
 *                       this browser is to it (valid · none · off · declined), its id (shown to the visitor, who may ask
 *                       for it to be forgotten) and a pass for the relay.  Counted as a page that loaded
 *   POST choice {ids}   "off": no id from now on (the cookie says so, and nothing more); "on": one is made
 *   POST forget         everything held of this visitor is deleted (ledger-d1.js: forget), and the count is off
 *   GET  me             what is held of this visitor: their first and last day, the days and questions counted
 *   GET  stats          the counts (the stats token, or public: ledger-d1.js)
 *   GET  health         the outbox, the registry's rows, what was dropped or lost (Bearer LOG_EXPORT_TOKEN)
 *   GET  archive?day=   that day of the archive against its manifest, both Workers' (Bearer LOG_EXPORT_TOKEN)
 */
async function activity(request, env, deps, url, L, cors, address) {
  const what = url.pathname.slice("/api/activity/".length);
  if (!L) return json({ error: "这里没有活动账本", ledger: false }, 404, cors);
  if (deps.limit && !(await deps.limit("read", address))) return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { ...cors, "Retry-After": "60" });
  const ucfg = usageConfig(env);
  L.mark = { type: "request", route: `/api/activity/${["hello", "choice", "forget", "me", "stats", "health", "archive"].includes(what) ? what : "…"}` };
  const get = request.method === "GET" || request.method === "HEAD";
  if (what === "stats") return serveLedgerStats(request, url, { db: L.db, cfg: ucfg, ledger: L.cfg, today: usageDay(L.now, ucfg.offset), cors, collector: env.LOG_EXPORT_TOKEN || "" });
  if (what === "health" || what === "archive") {
    if (!get) return json({ error: "GET" }, 405, { ...cors, Allow: "GET" });
    if (!(await bearerOk(request, env.LOG_EXPORT_TOKEN || ""))) return json({ error: "需要收集令牌" }, 401, cors);
    if (what === "archive") {
      const day = url.searchParams.get("day") || "";
      if (!env.ARCHIVE) return json({ error: "没有归档", archive: false }, 404, cors);
      if (!DAY.test(day)) return json({ error: "day=YYYY-MM-DD" }, 400, cors);
      const sources = ["site", "relay"].filter((x) => !url.searchParams.get("source") || url.searchParams.get("source") === x);
      return json({ v: 1, day, sources: Object.fromEntries(await Promise.all(sources.map(async (x) => [x, await verifyArchive(env.ARCHIVE, x, day)]))) }, 200, cors);
    }
    await ensure(L.db);
    const counts = await L.db.batch(TABLES.map((t) => L.db.prepare(`SELECT COUNT(*) AS n FROM ${t}`)));
    const days = await L.db.prepare("SELECT MIN(day) AS first, MAX(day) AS last FROM daily_metrics").first();
    return json({ v: 1, site: await deps.watch.ledgerHealth(), archive: Boolean(env.ARCHIVE), ids: L.cfg.ids,
      registry: { ...Object.fromEntries(TABLES.map((t, i) => [t, Number(counts[i].results?.[0]?.n || 0)])), first_day: days?.first || null, last_day: days?.last || null } }, 200, cors);
  }
  // the page's own, from a browser: its visitor is whoever the cookie names
  if (L.fp.uaClass !== "browser" || (L.fp.sfSite && L.fp.sfSite !== "same-origin")) return json({ error: "这个接口只供本站的网页调用" }, 403, cors);
  if (what === "me") {
    if (!get) return json({ error: "GET" }, 405, { ...cors, Allow: "GET" });
    const who = await L.identify();
    const held = who.visitor ? await ensure(L.db).then(() => known(L.db, who.visitor)).catch(() => null) : null;
    return json({ v: 1, ids: L.cfg.ids, state: who.state, visitor: who.visitor, held }, 200, cors);
  }
  if (request.method !== "POST") return json({ error: "POST" }, 405, { ...cors, Allow: "POST" });
  const text = await readText(request, 1024);
  if (text === null) return json({ error: "请求太大" }, 413, cors);
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { return json({ error: "请求不是有效的 JSON" }, 400, cors); }
  // what the page is told of its visitor: the id is theirs to see, the pass is what the relay reads it from
  const told = async (who) => ({ v: 1, ledger: true, ids: L.cfg.ids, state: who.state === "new" ? "valid" : who.state, visitor: who.visitor,
    pass: who.visitor ? await passFor(who.visitor, L.cfg.key, L.now, L.cfg.passMs) : null, expires: who.visitor ? L.now + L.cfg.passMs : null });
  if (what === "hello") {
    const who = await L.identify();
    const lang = typeof body?.lang === "string" && LANG.test(body.lang) ? body.lang : null;
    L.mark = { type: "page_ready", route: "/", visitor: who.visitor, more: lang ? { detail: lang } : {} };
    return json(await told(who), 200, cors);
  }
  if (what === "choice" && (body?.ids === "on" || body?.ids === "off")) {
    L.mark = { type: "visitor_choice", route: "/api/activity/choice", more: { detail: body.ids } };
    if (body.ids === "off") return json({ v: 1, ledger: true, ids: L.cfg.ids, state: "off", visitor: null, pass: null, expires: null }, 200, { ...cors, "Set-Cookie": setCookie(OFF, L.cfg.visitorDays) });
    L.who = identify(request, L.cfg, L.now, { optedIn: true });
    const who = await L.who;
    return json(await told(who), 200, who.cookie ? { ...cors, "Set-Cookie": who.cookie } : cors);
  }
  if (what === "forget") {
    const who = await L.identify();
    L.mark = { type: "visitor_choice", route: "/api/activity/forget", more: { detail: "forget" } };
    // (a registry switched on a moment ago may have no tables yet: they are made first)
    const done = who.visitor ? await ensure(L.db).then(() => forget(L.db, who.visitor, { by: "self", now: L.now })) : { found: false };
    // the cookie goes, and none is made again: someone who asked to be forgotten is not counted anew the next day
    return json({ v: 1, ledger: true, ids: L.cfg.ids, state: "off", visitor: null, pass: null, expires: null, forgotten: Boolean(done.found) }, 200,
      { ...cors, "Set-Cookie": L.cfg.ids === "off" ? clearCookie() : setCookie(OFF, L.cfg.visitorDays) });
  }
  return json({ error: `no such endpoint ${request.method} ${url.pathname}` }, 404, cors);
}

/**
 * The sentinel's word on an API request (a: its assessment; cap: its route's allowance for the day): {w, blocked, retry,
 * over, unavailable}.  deps.local (a Map, this instance's)
 * remembers per address the last round trip and the reads since; a quiet reader (score 0) within the minute is answered
 * from it.  The object out of reach (a failure) lets reads go on — the corpus's public passages, the rate-limit bindings
 * still standing — and refuses calls and research runs (unavailable): work the account pays for is not let through
 * unchecked.  On the Free plan the object's daily allowance made this unaffordable; on Workers Paid it has none.
 */
async function consult(deps, s, a, who, isGet, cap) {
  const local = deps.local || (deps.local = new Map());
  let l = local.get(who);
  if (!l) {
    if (local.size >= 5000) local.delete(local.keys().next().value);
    l = { at: 0, reads: 0, today: 0, blockedUntil: 0, notedAt: 0, notes: 0, paths: [] };
    local.set(who, l);
  }
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
  if (!w) return { w: null, blocked: false, retry: 0, over: false, unavailable: !isGet };
  if (isGet) l.today = Number(w.today?.["api-read"] || 0);
  l.blockedUntil = w.blocked ? w.until : 0;
  return { w, blocked: w.blocked, retry: w.retry, over: cap > 0 && Number(w.today?.[a.route] || 0) > cap };
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
