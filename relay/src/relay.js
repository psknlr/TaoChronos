// 道乃久默认服务 — the relay between the published page (chat.impf.ai) and MiniMax, so that visitors can ask without a
// key of their own.  The MiniMax key is a secret of this Worker: it never reaches a browser, the page or the repository.
//
//   POST /v1/chat/completions   the page's model calls, forwarded (streamed) with the key; only from the page's origins,
//                               only the allowed models, output capped, limited per visitor per minute and per day and in
//                               all per day
//   GET  /v1/health             whether the service is configured, its model, whether records are collected, the limits
//   POST /v1/logs               one turn of a conversation, sent by the page only when the visitor agreed to it
//   GET  /v1/logs/export        the records waiting, for the repository's collector (Authorization: Bearer LOG_EXPORT_TOKEN)
//   POST /v1/logs/ack           the collector has committed them: they are deleted here (409 while the archive collects)
//   GET  /v1/logs/archive       a day of the records archived in the private bucket ARCHIVE (Bearer LOG_EXPORT_TOKEN), when
//                               the Worker has one: then the records go there, not to the repository (security/archive.js)
//   GET  /v1/security/export    the sentinel's events waiting (Bearer LOG_EXPORT_TOKEN); POST /v1/security/ack deletes them;
//                               GET /v1/security/archive, a day of them archived
//   GET  /v1/security/summary   the visitors by score and the addresses refused now (Bearer LOG_EXPORT_TOKEN)
//   POST /v1/security/csp       a browser's Content-Security-Policy report (kept as an event)
//
// Visitors are counted by a hash of their address and the day; addresses are not stored, and records carry none.  The
// sentinel (security/sentinel.js) sees every request: a scanner path refuses its address for a day, a request that is
// not the page's is scored and, flagged, kept whole for the owner; in enforce mode an address over the block score is
// refused for a while.  An answer's tokens, as the upstream reports them, count against the visitor's day and the day.

import { EVENTS, RECORDS, serveArchive } from "../../security/archive.js";
import { assess, bodyShape, fingerprint, ipKey, isHoneypot, logLine, sentinelConfig, serveSecurity } from "../../security/sentinel.js";
import { place, serveStats, usageConfig, usageDay } from "../../security/usage.js";
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
  MAX_OUTPUT_TOKENS: "8192",
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
  LOG_KEEP: "50000",                          // records waiting to be collected at most: beyond, new ones are refused (none dropped)
  ALLOWED_ORIGINS: "https://chat.impf.ai,http://chat.impf.ai,https://psknlr.github.io",
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
    maxBody: num("MAX_BODY_BYTES"),
    origins: list("ALLOWED_ORIGINS"),
    chat: { perMinute: num("PER_MINUTE"), perDay: num("PER_DAY"), total: num("TOTAL_PER_DAY"), tokensPerDay: num("TOKENS_PER_DAY"), totalTokens: num("TOTAL_TOKENS_PER_DAY") },
    log: { perMinute: num("LOGS_PER_MINUTE"), perDay: num("LOGS_PER_DAY"), total: 0 },
    logs: String(get("LOGS")).toLowerCase() !== "off",
    logMax: num("LOG_MAX_BYTES"),
    keep: num("LOG_KEEP"),
  };
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
  const cors = allowed ? { "Access-Control-Allow-Origin": origin, "Access-Control-Expose-Headers": "Retry-After", Vary: "Origin" } : { Vary: "Origin" };
  // the sentinel: the request as seen at the edge, and a note of it when it is worth one (security/sentinel.js)
  const scfg = sentinelConfig(env);
  const s = scfg.mode === "off" ? null : { cfg: scfg, fp: fingerprint(request, deps.now()), origins: cfg.origins, deps };
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
      headers: { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Accept, Authorization",
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
      if (url.pathname === "/v1/security/archive") return await serveArchive(request, url, { bucket: env.ARCHIVE, prefix: EVENTS("relay"), token: env.LOG_EXPORT_TOKEN || "", cors });
      const res = await serveSecurity(request, url, { prefix: "/v1/security", token: env.LOG_EXPORT_TOKEN || "", watch: deps.watch, cfg: scfg, fp: s.fp,
        now: deps.now(), cors, archived: Boolean(env.ARCHIVE) });
      if (res) return res;
    }
    switch (`${request.method} ${url.pathname}`) {
      case "GET /v1/health": return health(env, cfg, cors);
      case "GET /v1/stats": return await stats(request, env, url, cors, deps);
      case "POST /v1/chat/completions": return await chat(request, env, cfg, cors, allowed, deps, s);
      case "POST /v1/logs": return await submit(request, cfg, cors, allowed, deps, s);
      case "GET /v1/logs/export": return await records(request, env, url, deps);
      case "POST /v1/logs/ack": return await ack(request, env, deps);
      case "GET /v1/logs/archive": return await serveArchive(request, url, { bucket: env.ARCHIVE, prefix: RECORDS, token: env.LOG_EXPORT_TOKEN || "" });
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
  s.deps.defer(s.deps.observe(s.fp, a, { status, ...extra }, s.cfg));
}

const BLOCKED = "该地址因异常访问已被暂时限制，请稍后再试";

function limited(gate, limits, cors, what = "请求") {
  const headers = { ...cors, "Retry-After": String(gate.retry || 60) };
  if (gate.reason === "blocked") return error(403, BLOCKED, "blocked", headers);
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
function health(env, cfg, cors) {
  return json({
    ok: Boolean(env.MINIMAX_API_KEY), service: "taochronos-relay", version: VERSION, model: cfg.publicModel, models: [cfg.publicModel],
    logs: cfg.logs, max_output_tokens: cfg.maxTokens, limits: { per_minute: cfg.chat.perMinute, per_day: cfg.chat.perDay, tokens_per_day: cfg.chat.tokensPerDay },
  }, 200, cors);
}

// MiniMax reports some failures in a 200 reply's base_resp
const BASE_RESP = { 1004: [503, "upstream_auth"], 2049: [503, "upstream_auth"], 1008: [503, "upstream_quota"], 1002: [429, "upstream_rate"],
  1039: [429, "upstream_rate"] };

async function chat(request, env, cfg, cors, allowed, deps, s) {
  if (!allowed) {
    if (s) note(s, "chat", 403);
    return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  }
  if (!env.MINIMAX_API_KEY) return error(503, "默认服务尚未配置，请在“设置 → 模型”里填入自己的 API Key", "not_configured", cors);
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
  // the default service's model by its public name, or by none (pages older than it send the upstream's own name)
  const asked = body.model;
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
    // the call is counted with the gate's round trip for the settings' 统计 pane (security/usage.js): its day, its place,
    // and whether it is a question or a tool round of one
    const usage = s ? { day: usageDay(deps.now(), usageConfig(env).offset), ...place(s.fp), turn: Boolean(shape?.turn) } : null;
    gate = await deps.gate({ who, kind: "chat", limits: cfg.chat, fp: s?.fp, a, shape, cfg: s?.cfg, reserve, usage });
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

  let upstream;
  try {
    upstream = await deps.fetch(`${cfg.upstream}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: request.headers.get("Accept") || "application/json",
        Authorization: `Bearer ${env.MINIMAX_API_KEY}` },
      body: payload,
      signal: request.signal, // the visitor leaving, or stopping the answer, ends the model call too
    });
  } catch {
    return error(502, "默认服务暂时连不上模型服务，请稍后再试", "upstream_unreachable", cors);
  }
  const type = upstream.headers.get("Content-Type") || "application/json";
  if (upstream.status === 401 || upstream.status === 403) {
    await upstream.body?.cancel();
    return error(503, "默认服务暂时不可用（模型服务拒绝了它的密钥），请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_auth", cors);
  }
  if (upstream.status === 429) {
    await upstream.body?.cancel();
    return error(429, "默认服务的模型额度暂时用完或调用过于频繁，请稍后再试，或在“设置 → 模型”里填入自己的 API Key", "upstream_rate", cors);
  }
  if (!upstream.ok) {
    // the upstream's own message would name it, its models and its parameters: the visitor is told what to do instead
    await upstream.body?.cancel();
    console.error("upstream", upstream.status);
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
    return new Response(publicText(out, cfg, spend), { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
  }
  if (!type.includes("event-stream") || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(publicText(text, cfg, spend), { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
  }
  const stream = (noReasoning ? upstream.body.pipeThrough(reasoningFilter()) : upstream.body).pipeThrough(publicFilter(cfg, spend));
  return new Response(stream, { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
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
export function publicFilter(cfg, onUsage) {
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
const str = (v, n) => (typeof v === "string" ? v.slice(0, n) : undefined);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

/** A turn as the page sends it, reduced to the known fields and their limits (anything else is dropped). */
export function normalizeRecord(r) {
  if (!r || typeof r !== "object" || Array.isArray(r) || r.v !== 1) return null;
  const question = str(r.question, 4000);
  if (!question && !num(r.images)) return null;
  const out = {
    v: 1, id: str(r.id, 64), conversation: str(r.conversation, 64), turn: num(r.turn),
    started: str(r.started, 40), finished: str(r.finished, 40), ms: num(r.ms), rounds: num(r.rounds),
    question: question || "", images: num(r.images), answer: str(r.answer, 20000), redacted: num(r.redacted),
    status: str(r.status, 20), error: str(r.error, 500),
    model: str(r.model, 80), provider: str(r.provider, 80), runtime: str(r.runtime, 40), corpus: str(r.corpus, 40), app: str(r.app, 40),
    tools: Array.isArray(r.tools)
      ? r.tools.slice(0, 40).map((t) => ({ name: str(t?.name, 80), ok: t?.ok === true, ms: num(t?.ms), args: str(t?.args, 300) }))
      : [],
  };
  const u = r.usage;
  if (u && typeof u === "object" && !Array.isArray(u)) {
    out.usage = {};
    for (const k of ["input", "output"]) if (num(u[k]) !== undefined) out.usage[k] = u[k]; // tokens, summed over the turn's rounds
  }
  const c = r.citations;
  if (c && typeof c === "object" && !Array.isArray(c)) {
    out.citations = {};
    for (const k of ["total", "ok", "warn", "bad", "pending"]) if (num(c[k]) !== undefined) out.citations[k] = c[k];
    if (Array.isArray(c.pids)) out.citations.pids = c.pids.filter((p) => typeof p === "string").slice(0, 60).map((p) => p.slice(0, 80));
  }
  return JSON.parse(JSON.stringify(out)); // without the undefined fields
}

async function submit(request, cfg, cors, allowed, deps, s) {
  if (!allowed) {
    if (s) note(s, "logs", 403);
    return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  }
  if (!cfg.logs) return error(404, "对话记录已关闭", "logs_off", cors);
  if (await bursting(request, deps)) {
    if (s) note(s, "logs", 429);
    return limited({ reason: "burst" }, cfg.log, cors, "记录");
  }
  const raw = await readBody(request, cfg.logMax);
  if (raw === null) return error(413, "记录过大", "too_large", cors);
  let r;
  try { r = JSON.parse(raw); } catch {
    if (s) note(s, "logs", 400);
    return error(400, "记录不是有效的 JSON", "bad_record", cors);
  }
  const record = normalizeRecord(r);
  if (!record) {
    if (s) note(s, "logs", 400);
    return error(400, "记录格式不对", "bad_record", cors);
  }
  // the page names the default service's model by its public name; the records (the owner's) keep the one that answered
  if (record.model === cfg.publicModel) record.model = cfg.model;
  const a = s ? assess(s.fp, { route: "logs", origins: cfg.origins, ownPrefix: s.cfg.ownPrefix }) : null;
  // a record of the default service's own conversation comes from a visitor it answered today; a record of a conversation
  // held with the visitor's own key (another provider) never passed through here, and is taken on its origin alone
  const served = record.provider === RELAY_PROVIDER ? "chat" : undefined;
  let gate;
  try {
    gate = await deps.gate({ who: await caller(request, deps.now()), kind: "log", limits: cfg.log, fp: s?.fp, a, cfg: s?.cfg, served });
  } catch (err) {
    console.error("gate", err?.name || "Error"); // the record is let go: it is not the visitor's concern
    return new Response(null, { status: 204, headers: cors });
  }
  if (s) logLine("relay", s.fp, a, gate.watch, gate.ok ? 204 : gate.reason === "blocked" ? 403 : 429, s.cfg);
  if (!gate.ok) return limited(gate, cfg.log, cors, "记录");
  const id = await deps.logbook.add(JSON.stringify(record), new Date(deps.now()).toISOString(), cfg.keep);
  if (id === null) {
    // the book is full (nothing collected it for a long while): this record is refused, the ones taken in stay
    console.error("logs full", cfg.keep);
    return error(503, "对话记录暂存已满，这条记录未保存", "logs_full", { ...cors, "Retry-After": "3600" });
  }
  return new Response(null, { status: 204, headers: cors });
}

// ------------------------------------------------------------------ the counts for the settings' 统计 pane
async function stats(request, env, url, cors, deps) {
  if (await bursting(request, deps)) return error(429, "请求太频繁，请稍后再试", "rate_limited", { ...cors, "Retry-After": "10" });
  const ucfg = usageConfig(env);
  const today = usageDay(deps.now(), ucfg.offset);
  return serveStats(request, url, { cfg: ucfg, stats: (days) => deps.stats(days, today), cors, today });
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
