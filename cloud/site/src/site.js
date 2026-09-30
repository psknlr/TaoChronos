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
//
// Nothing else reaches the corpus: not the model proxy of `taochronos serve` (the page talks to its models itself, or to
// the relay), not its static files.  API calls are limited per visitor (the rate-limit bindings); addresses are kept
// nowhere.

import { answer as backupAnswer, ready as backupReady } from "./backup/api.js";

export const DEFAULTS = {
  ALLOWED_ORIGINS: "https://chat.impf.ai",
  HSTS_MAX_AGE: "86400",
  MAX_BODY_BYTES: "262144",
  STORE_MAX_PART_BYTES: "26214400", // a Workers KV value is at most 25 MiB
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
  };
}

/** deps: {limit(kind, key) → Promise<boolean>} (the rate-limit bindings in the Worker; plain functions in tests). */
export async function handle(request, env, deps = {}) {
  const cfg = config(env);
  const url = new URL(request.url);
  if (url.protocol === "http:" && !LOCAL.has(url.hostname)) {
    url.protocol = "https:";
    return new Response(null, { status: 301, headers: { Location: url.href, "Cache-Control": "max-age=3600" } });
  }
  let response;
  try {
    response = url.pathname === "/api" || url.pathname.startsWith("/api/") ? await api(request, env, cfg, deps, url) : await site(request, env);
  } catch (err) {
    console.error("site error", err?.name || "Error", err?.message || ""); // never the request: it may carry what a visitor wrote
    response = json({ error: "服务出错了，请稍后再试" }, 500);
  }
  return secure(response, cfg);
}

// ------------------------------------------------------------------ the site
async function site(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
  }
  return env.ASSETS.fetch(request);
}

/** The headers every answer carries: https from now on, no sniffing, no framing by other sites. */
function secure(response, cfg) {
  const res = new Response(response.body, response);
  if (cfg.hsts > 0) res.headers.set("Strict-Transport-Security", `max-age=${cfg.hsts}`);
  res.headers.set("X-Content-Type-Options", "nosniff");
  res.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  if ((res.headers.get("Content-Type") || "").startsWith("text/html")) res.headers.set("X-Frame-Options", "SAMEORIGIN");
  return res;
}

// ------------------------------------------------------------------ the API
const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

async function api(request, env, cfg, deps, url) {
  const origin = request.headers.get("Origin");
  const allowed = !origin || origin === url.origin || cfg.origins.includes(origin);
  const cors = origin && allowed ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : { Vary: "Origin" };
  if (request.method === "OPTIONS") {
    if (!allowed) return new Response(null, { status: 403, headers: cors });
    return new Response(null, { status: 204, headers: { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
  }
  if (!allowed) return json({ error: `origin ${origin} may not call this API` }, 403, cors);
  const store = url.pathname.match(STORE);
  if (store) return storePart(request, env, cfg, store[1]);
  const isGet = request.method === "GET" || request.method === "HEAD";
  if (!(isGet && GETS.test(url.pathname)) && !(request.method === "POST" && POSTS.test(url.pathname))) {
    return json({ error: `no such endpoint ${request.method} ${url.pathname}` }, 404, cors);
  }
  const who = request.headers.get("CF-Connecting-IP") || "unknown";
  if (deps.limit && !(await deps.limit(isGet ? "read" : "call", who))) {
    return json({ error: "请求太频繁，请稍候再试", rate_limited: true }, 429, { ...cors, "Retry-After": "60" });
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
  const res = new Response(upstream.body, { status: upstream.status, headers: { ...cors, "Cache-Control": "no-store" } });
  res.headers.set("Content-Type", upstream.headers.get("Content-Type") || "application/json; charset=utf-8");
  for (const h of ["X-TC-Corpus", "Retry-After"]) if (upstream.headers.has(h)) res.headers.set(h, upstream.headers.get(h));
  return res;
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
