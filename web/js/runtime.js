// Where TaoChronos runs: in this browser (Pyodide in a worker, on the 要籍语料) or under `taochronos serve` — on the
// user's machine or another one they run it on (the full corpus).  Both answer the same calls — info, catalog, call,
// passage, research — with the same shapes, because both run the same Python module (taochronos.chat).  The browser
// runtime knows its info and catalogs before it has loaded (runtime/boot.json, written by the build), so that a
// conversation can begin at once; only the tools it calls wait for it.

const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

export function isLoopback(url) {
  try { return LOOPBACK.has(new URL(url).hostname); } catch { return false; }
}

/** Why this page cannot reach a server at `url` at all, if it cannot. */
export function unreachable(url) {
  let u;
  try { u = new URL(url); } catch { return `服务地址无效：${url}`; }
  if (!/^https?:$/.test(u.protocol)) return `服务地址须以 http:// 或 https:// 开头：${url}`;
  if (location.protocol === "https:" && u.protocol === "http:" && !LOOPBACK.has(u.hostname)) {
    return `本页经 HTTPS 打开，浏览器不允许它访问其他机器上的 http:// 地址：请直接打开该服务自己的网页（${u.origin}/），或为服务配置 HTTPS`;
  }
  return null;
}

const tokenHeaders = (token) => (token ? { "X-TC-Token": token } : {});

/** Is a TaoChronos server answering at `url`?  A quick look: the page uses the browser runtime when none answers. */
export async function probeServer(url, token = "", timeout = 2500) {
  if (unreachable(url)) return false;
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(`${url.replace(/\/+$/, "")}/api/info`, { headers: tokenHeaders(token), cache: "no-store", signal: ctl.signal });
    const j = await r.json().catch(() => ({}));
    return (r.ok && j?.name === "TaoChronos") || (r.status === 401 && Boolean(j?.token_required));
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

export class BrowserRuntime {
  constructor() {
    this.kind = "browser";
    this.label = "浏览器内";
    this.worker = null;
    this.pending = new Map();
    this.seq = 0;
    this.listeners = new Set();
    this.state = { status: "idle", progress: 0, message: "", index: null };
    this.ready = null;
    this.boot = null; // runtime/boot.json: {info, catalogs}
  }

  onStatus(fn) { this.listeners.add(fn); fn(this.state); return () => this.listeners.delete(fn); }
  _status(patch) { this.state = { ...this.state, ...patch }; for (const fn of this.listeners) fn(this.state); }

  start() {
    if (this.ready) return this.ready;
    this._status({ status: "loading", progress: 2, message: "启动运行环境" });
    this.boot ||= fetch(new URL("../runtime/boot.json", import.meta.url), { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    this.worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module", name: "taochronos" });
    this.worker.onmessage = (e) => {
      const msg = e.data || {};
      if (msg.type === "progress") { this._status({ status: "loading", progress: msg.progress, message: msg.message }); return; }
      if (msg.type === "index") { this._status({ index: { ...this.state.index, ...msg } }); return; }
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error));
      else p.resolve(msg.result);
    };
    this.worker.onerror = (e) => {
      this._status({ status: "error", message: e.message || "运行环境出错" });
      for (const p of this.pending.values()) p.reject(new Error(e.message || "worker error"));
      this.pending.clear();
    };
    this.ready = this._rpc("init", { base: new URL("../", import.meta.url).href })
      .then((info) => { this._status({ status: "ready", progress: 100, message: "" }); this.info_ = info; return info; })
      .catch((err) => { this._status({ status: "error", message: err.message }); this.ready = null; throw err; });
    return this.ready;
  }

  stop() {
    this.worker?.terminate();
    this.worker = null;
    for (const p of this.pending.values()) p.reject(new Error("运行环境已切换"));
    this.pending.clear();
    this.ready = null;
  }

  _rpc(method, params = {}) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, method, params });
    });
  }

  async call_(method, params) { await this.start(); return this._rpc(method, params); }
  /** The runtime's info — while it loads, what it will say once loaded (the boot file), when the site has one. */
  async info() {
    if (this.info_) return this.info_;
    const started = this.start();
    started.catch(() => { /* shown in the status */ });
    const boot = await this.boot;
    return boot?.info || (await started);
  }
  async catalog(mode) {
    if (!this.info_) {
      this.start().catch(() => { /* shown in the status */ });
      const boot = await this.boot;
      if (boot?.catalogs?.[mode]) return boot.catalogs[mode];
    }
    return this.call_("catalog", { mode });
  }
  call(name, args, { maxChars } = {}) { return this.call_("call", { name, arguments: args, max_chars: maxChars }); }
  passage(id) { return this.call_("passage", { id }); }
  session(id, what, extra = {}) { return this.call_("session", { session_id: id, what, ...extra }); }
  async research(args, { maxChars, onProgress } = {}) {
    const started = Date.now();
    const timer = setInterval(() => onProgress?.({ status: "running", elapsed_s: (Date.now() - started) / 1000 }), 500);
    try { return await this.call("taochronos_research", args, { maxChars }); } finally { clearInterval(timer); }
  }
}

export class ServerRuntime {
  /** `fallback` (the site's own server): a runtime to answer instead when this server cannot — asleep past waiting, or
   * down — called once, with the error. */
  constructor(url, token = "", { label = "", fallback = null } = {}) {
    this.kind = "server";
    this.url = url.replace(/\/+$/, "");
    this.token = token || "";
    this.label = label || (isLoopback(this.url) ? "本地服务" : "远程服务");
    this.state = { status: "idle", progress: 0, message: "" };
    this.listeners = new Set();
    this.ready = null;
    this.fallback = fallback;
    this.backup = null;
  }

  /** Answer with the fallback runtime when this server is unavailable (not for an error the server itself reports). */
  async _or(err, fn) {
    if (!this.fallback || !err?.unavailable) throw err;
    this.backup ||= this.fallback(err);
    return fn(this.backup);
  }

  onStatus(fn) { this.listeners.add(fn); fn(this.state); return () => this.listeners.delete(fn); }
  _status(patch) { this.state = { ...this.state, ...patch }; for (const fn of this.listeners) fn(this.state); }

  stop() { /* nothing runs here: the server keeps serving other pages */ }

  async _fetch(path, init = {}, timeout = 0) {
    const bad = unreachable(this.url);
    if (bad) throw new Error(bad);
    const ctl = new AbortController();
    const t = timeout ? setTimeout(() => ctl.abort(), timeout) : null;
    try {
      const r = await fetch(this.url + path, { ...init, headers: { ...tokenHeaders(this.token), ...(init.headers || {}) }, signal: init.signal || ctl.signal });
      const j = await r.json().catch(() => ({}));
      if ([502, 503, 504].includes(r.status)) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), { unavailable: true });
      if (r.status === 401 && j.token_required) {
        throw Object.assign(new Error(this.token
          ? "访问令牌不对：请核对 taochronos serve 启动时打印的令牌（设置 → 运行环境）"
          : "这个服务需要访问令牌：请填写 taochronos serve 启动时打印的令牌（设置 → 运行环境）"), { tokenRequired: true });
      }
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      return j;
    } catch (err) {
      if (err.name === "AbortError" && !init.signal) throw Object.assign(new Error(`连接 ${this.url} 超时`), { unavailable: true });
      if (err instanceof TypeError) {
        throw Object.assign(new Error(this.fallback ? `无法连接 ${this.url}` : `无法连接 ${this.url}：请确认 taochronos serve 正在运行（网页由 HTTPS 打开时，浏览器可能会询问是否允许访问本机网络）`), { unavailable: true });
      }
      throw err;
    } finally {
      if (t) clearTimeout(t);
    }
  }

  start() {
    if (this.ready) return this.ready;
    this._status({ status: "loading", progress: 30, message: `连接${this.label}` });
    this.ready = this._fetch("/api/info", {}, 30000)
      .then((info) => { this.info_ = info; this._status({ status: "ready", progress: 100, message: "" }); return info; })
      .catch((err) => { this._status({ status: "error", message: err.message }); this.ready = null; throw err; });
    return this.ready;
  }

  async info() { return this.info_ || (await this.start()); }
  catalog(mode) { return this._fetch(`/api/catalog?mode=${encodeURIComponent(mode)}`); }
  call(name, args, { maxChars, signal } = {}) {
    if (this.backup) return this.backup.call(name, args, { maxChars, signal });
    return this._fetch("/api/call", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, arguments: args, max_chars: maxChars }), signal })
      .catch((err) => this._or(err, (rt) => rt.call(name, args, { maxChars, signal })));
  }
  passage(id) {
    if (this.backup) return this.backup.passage(id);
    return this._fetch(`/api/passage?id=${encodeURIComponent(id)}`).catch((err) => this._or(err, (rt) => rt.passage(id)));
  }
  session(id, what, extra = {}) {
    if (this.backup) return this.backup.session(id, what, extra);
    const q = new URLSearchParams({ what, ...extra });
    return this._fetch(`/api/session/${encodeURIComponent(id)}?${q}`);
  }
  async research(args, options = {}) {
    if (this.backup) return this.backup.research(args, options);
    try {
      return await this._research(args, options);
    } catch (err) {
      return this._or(err, (rt) => rt.research(args, options));
    }
  }
  async _research(args, { onProgress, signal } = {}) {
    const { job } = await this._fetch("/api/research", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args) });
    for (;;) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
      await new Promise((r) => setTimeout(r, 900));
      const st = await this._fetch(`/api/research/${job}`);
      onProgress?.(st);
      if (st.status === "done" || st.status === "error") return st.outcome;
      if (st.status === "unknown") throw new Error("研究任务已丢失（服务是否重启过？）");
    }
  }
}

/** Is a TaoChronos server answering at this origin (the client served by `taochronos serve`)? */
export async function sameOriginServer(token = "") {
  if (!/^https?:$/.test(location.protocol) || location.hostname.endsWith("github.io")) return null;
  const here = new URL(".", location.href).href;
  return (await probeServer(here, token, 8000)) ? here : null;
}
