// 道乃久默认服务 — the relay between the published page (chat.impf.ai) and MiniMax, so that visitors can ask without a
// key of their own.  The MiniMax key is a secret of this Worker: it never reaches a browser, the page or the repository.
//
//   POST /v1/chat/completions   the page's model calls, forwarded (streamed) with the key; only from the page's origins,
//                               only the allowed models, output capped, limited per visitor per minute and per day and in
//                               all per day
//   GET  /v1/health             whether the service is configured, its model, whether records are collected, the limits
//   POST /v1/logs               one turn of a conversation, sent by the page only when the visitor agreed to it
//   GET  /v1/logs/export        the records waiting, for the repository's collector (Authorization: Bearer LOG_EXPORT_TOKEN)
//   POST /v1/logs/ack           the collector has committed them: they are deleted here
//
// Visitors are counted by a hash of their address and the day; addresses are not stored, and records carry none.

import { day } from "./state.js";

export const VERSION = "1";

export const DEFAULTS = {
  UPSTREAM_BASE: "https://api.minimax.cn/v1", // MiniMax's mainland platform; https://api.minimax.io/v1 for international keys
  MODELS: "MiniMax-M3",                       // the first is the default
  MAX_OUTPUT_TOKENS: "8192",
  MAX_BODY_BYTES: "2000000",
  PER_MINUTE: "30",                           // model calls per visitor (one question takes several: the tools)
  PER_DAY: "600",
  TOTAL_PER_DAY: "5000",                      // all visitors together
  LOGS: "on",
  LOG_MAX_BYTES: "65536",
  LOGS_PER_MINUTE: "20",
  LOGS_PER_DAY: "500",
  LOG_KEEP: "50000",                          // records never collected beyond this many: the oldest are dropped
  ALLOWED_ORIGINS: "https://chat.impf.ai,http://chat.impf.ai,https://psknlr.github.io",
};

export function config(env = {}) {
  const get = (k) => (env[k] !== undefined && env[k] !== "" ? env[k] : DEFAULTS[k]);
  const num = (k) => Number(get(k));
  const list = (k) => String(get(k)).split(",").map((s) => s.trim()).filter(Boolean);
  const models = list("MODELS");
  return {
    upstream: String(get("UPSTREAM_BASE")).replace(/\/+$/, ""),
    models,
    model: models[0],
    maxTokens: num("MAX_OUTPUT_TOKENS"),
    maxBody: num("MAX_BODY_BYTES"),
    origins: list("ALLOWED_ORIGINS"),
    chat: { perMinute: num("PER_MINUTE"), perDay: num("PER_DAY"), total: num("TOTAL_PER_DAY") },
    log: { perMinute: num("LOGS_PER_MINUTE"), perDay: num("LOGS_PER_DAY"), total: 0 },
    logs: String(get("LOGS")).toLowerCase() !== "off",
    logMax: num("LOG_MAX_BYTES"),
    keep: num("LOG_KEEP"),
  };
}

/**
 * deps: {limit(who, kind, limits) → {ok, reason, retry, remaining}, logbook: {add, records, remove}, fetch, now}
 * (the Durable Objects and the network in the Worker; plain objects in tests).
 */
export async function handle(request, env, deps) {
  const cfg = config(env);
  const url = new URL(request.url);
  const origin = request.headers.get("Origin") || "";
  const allowed = cfg.origins.includes(origin);
  const cors = allowed ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : { Vary: "Origin" };
  if (request.method === "OPTIONS") {
    if (!allowed) return new Response(null, { status: 403, headers: cors });
    return new Response(null, {
      status: 204,
      headers: { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Accept",
        "Access-Control-Max-Age": "86400" },
    });
  }
  try {
    switch (`${request.method} ${url.pathname}`) {
      case "GET /v1/health": return health(env, cfg, cors);
      case "POST /v1/chat/completions": return await chat(request, env, cfg, cors, allowed, deps);
      case "POST /v1/logs": return await submit(request, cfg, cors, allowed, deps);
      case "GET /v1/logs/export": return await records(request, env, url, deps);
      case "POST /v1/logs/ack": return await ack(request, env, deps);
      default: return error(404, "没有这个接口", "not_found", cors);
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

/** Who is calling, for the counters: a hash of the address and the day (the address itself is kept nowhere). */
async function caller(request, now) {
  const ip = request.headers.get("CF-Connecting-IP") || request.headers.get("X-Forwarded-For")?.split(",")[0]?.trim() || "unknown";
  return hex(await sha256(`${ip}|${day(now)}`)).slice(0, 24);
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

/** The body as text, or null when it is larger than `max` bytes (measured only when no length was declared). */
async function readBody(request, max) {
  const declared = request.headers.get("Content-Length");
  if (declared !== null && Number(declared) > max) return null;
  const text = await request.text();
  if (declared !== null) return text; // the body is the length it declared, within the limit
  return encoder.encode(text).length > max ? null : text;
}

function limited(gate, limits, cors, what = "请求") {
  const headers = { ...cors, "Retry-After": String(gate.retry || 60) };
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
    ok: Boolean(env.MINIMAX_API_KEY), service: "taochronos-relay", version: VERSION, model: cfg.model, models: cfg.models,
    logs: cfg.logs, max_output_tokens: cfg.maxTokens, limits: { per_minute: cfg.chat.perMinute, per_day: cfg.chat.perDay },
  }, 200, cors);
}

// MiniMax reports some failures in a 200 reply's base_resp
const BASE_RESP = { 1004: [503, "upstream_auth"], 2049: [503, "upstream_auth"], 1008: [503, "upstream_quota"], 1002: [429, "upstream_rate"],
  1039: [429, "upstream_rate"] };

async function chat(request, env, cfg, cors, allowed, deps) {
  if (!allowed) return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  if (!env.MINIMAX_API_KEY) return error(503, "默认服务尚未配置，请在“设置 → 模型”里填入自己的 API Key", "not_configured", cors);
  const raw = await readBody(request, cfg.maxBody);
  if (raw === null) return error(413, `对话太长，超过了默认服务的上限（${Math.round(cfg.maxBody / 1e6)} MB）：请新开一个对话`, "too_large", cors);
  let body;
  try { body = JSON.parse(raw); } catch { return error(400, "请求不是有效的 JSON", "bad_request", cors); }
  if (!body || typeof body !== "object" || !Array.isArray(body.messages) || !body.messages.length) {
    return error(400, "请求缺少 messages", "bad_request", cors);
  }
  // what the relay changes; an unchanged request goes on as it came (no second serialisation: CPU is counted per request)
  let changed = false;
  if (body.model === undefined || body.model === null || body.model === "") { body.model = cfg.model; changed = true; }
  if (!cfg.models.includes(body.model)) return error(400, `默认服务只提供 ${cfg.models.join("、")}`, "model_not_allowed", cors);
  let capped = false;
  for (const k of ["max_tokens", "max_completion_tokens"]) {
    if (k in body) {
      const v = Math.min(Math.max(1, Math.floor(Number(body[k]) || cfg.maxTokens)), cfg.maxTokens);
      if (v !== body[k]) { body[k] = v; changed = true; }
      capped = true;
    }
  }
  if (!capped) { body.max_completion_tokens = cfg.maxTokens; changed = true; }
  if ("n" in body) { delete body.n; changed = true; } // one answer per call
  // the page asks for no thinking (a question about who answers): none is to reach the browser, whatever the model sends
  const noReasoning = body.thinking?.type === "disabled";

  const gate = await deps.limit(await caller(request, deps.now()), "chat", cfg.chat);
  if (!gate.ok) return limited(gate, cfg.chat, cors);

  let upstream;
  try {
    upstream = await deps.fetch(`${cfg.upstream}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: request.headers.get("Accept") || "application/json",
        Authorization: `Bearer ${env.MINIMAX_API_KEY}` },
      body: changed ? JSON.stringify(body) : raw,
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
    const detail = await upstream.text().catch(() => "");
    return error(429, `默认服务的模型额度暂时用完或调用过于频繁，请稍后再试，或在“设置 → 模型”里填入自己的 API Key（${upstreamMessage(detail)}）`,
      "upstream_rate", cors);
  }
  if (upstream.ok && !type.includes("event-stream") && type.includes("json")) {
    // a stream request answered with plain JSON: MiniMax's base_resp may carry a failure
    const text = await upstream.text();
    let j = null;
    try { j = JSON.parse(text); } catch { /* passed on as it is */ }
    const code = j?.base_resp?.status_code;
    if (code && BASE_RESP[code]) {
      const [status, kind] = BASE_RESP[code];
      const msg = kind === "upstream_auth" ? "默认服务暂时不可用（模型服务拒绝了它的密钥）"
        : kind === "upstream_quota" ? "默认服务的模型额度已用完" : "默认服务的模型调用过于频繁";
      return error(status, `${msg}，请稍后再试，或在“设置 → 模型”里填入自己的 API Key`, kind, cors);
    }
    const out = noReasoning && j ? JSON.stringify(withoutReasoning(j)) : text;
    return new Response(out, { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
  }
  const stream = noReasoning && upstream.body && type.includes("event-stream") ? upstream.body.pipeThrough(reasoningFilter()) : upstream.body;
  return new Response(stream, { status: upstream.status, headers: { ...cors, "Content-Type": type, "Cache-Control": "no-store" } });
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

function upstreamMessage(text) {
  try {
    const j = JSON.parse(text);
    return String(j.error?.message || j.base_resp?.status_msg || j.message || "限流").slice(0, 200);
  } catch {
    return "限流";
  }
}

// ------------------------------------------------------------------ records
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
    question: question || "", images: num(r.images), answer: str(r.answer, 20000), status: str(r.status, 20), error: str(r.error, 500),
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

async function submit(request, cfg, cors, allowed, deps) {
  if (!allowed) return error(403, "这个服务只供道乃久网页使用", "forbidden_origin", cors);
  if (!cfg.logs) return error(404, "对话记录已关闭", "logs_off", cors);
  const raw = await readBody(request, cfg.logMax);
  if (raw === null) return error(413, "记录过大", "too_large", cors);
  let r;
  try { r = JSON.parse(raw); } catch { return error(400, "记录不是有效的 JSON", "bad_record", cors); }
  const record = normalizeRecord(r);
  if (!record) return error(400, "记录格式不对", "bad_record", cors);
  const gate = await deps.limit(await caller(request, deps.now()), "log", cfg.log);
  if (!gate.ok) return limited(gate, cfg.log, cors, "记录");
  await deps.logbook.add(JSON.stringify(record), new Date(deps.now()).toISOString(), cfg.keep);
  return new Response(null, { status: 204, headers: cors });
}

async function records(request, env, url, deps) {
  if (!(await authorized(request, env))) return error(401, "需要收集令牌", "unauthorized");
  const after = Math.max(0, Math.floor(Number(url.searchParams.get("after") || 0)) || 0);
  const limit = Math.min(1000, Math.max(1, Math.floor(Number(url.searchParams.get("limit") || 500)) || 500));
  return json(await deps.logbook.records(after, limit));
}

async function ack(request, env, deps) {
  if (!(await authorized(request, env))) return error(401, "需要收集令牌", "unauthorized");
  let body;
  try { body = JSON.parse(await request.text()); } catch { return error(400, "请求不是有效的 JSON", "bad_request"); }
  const through = Math.floor(Number(body?.through));
  if (!Number.isFinite(through) || through < 1) return error(400, "缺少 through", "bad_request");
  return json(await deps.logbook.remove(through));
}
