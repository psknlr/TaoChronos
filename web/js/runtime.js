// Where TaoChronos runs: in this browser (Pyodide in a worker, demonstration corpus) or on the user's machine
// (`taochronos serve`, the full corpus).  Both answer the same calls — info, catalog, call, passage, research — with the
// same shapes, because both run the same Python module (taochronos.chat).

export class BrowserRuntime {
  constructor() {
    this.kind = "browser";
    this.label = "浏览器内";
    this.worker = null;
    this.pending = new Map();
    this.seq = 0;
    this.listeners = new Set();
    this.state = { status: "idle", progress: 0, message: "" };
    this.ready = null;
  }

  onStatus(fn) { this.listeners.add(fn); fn(this.state); return () => this.listeners.delete(fn); }
  _status(patch) { this.state = { ...this.state, ...patch }; for (const fn of this.listeners) fn(this.state); }

  start() {
    if (this.ready) return this.ready;
    this._status({ status: "loading", progress: 2, message: "启动运行环境" });
    this.worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module", name: "taochronos" });
    this.worker.onmessage = (e) => {
      const msg = e.data || {};
      if (msg.type === "progress") { this._status({ status: "loading", progress: msg.progress, message: msg.message }); return; }
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

  _rpc(method, params = {}) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, method, params });
    });
  }

  async call_(method, params) { await this.start(); return this._rpc(method, params); }
  async info() { return this.info_ || (await this.start()); }
  catalog(mode) { return this.call_("catalog", { mode }); }
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
  constructor(url) {
    this.kind = "server";
    this.label = "本地服务";
    this.url = url.replace(/\/+$/, "");
    this.state = { status: "idle", progress: 0, message: "" };
    this.listeners = new Set();
    this.ready = null;
  }

  onStatus(fn) { this.listeners.add(fn); fn(this.state); return () => this.listeners.delete(fn); }
  _status(patch) { this.state = { ...this.state, ...patch }; for (const fn of this.listeners) fn(this.state); }

  async _fetch(path, init = {}, timeout = 0) {
    const ctl = new AbortController();
    const t = timeout ? setTimeout(() => ctl.abort(), timeout) : null;
    try {
      const r = await fetch(this.url + path, { ...init, signal: init.signal || ctl.signal });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      return j;
    } catch (err) {
      if (err.name === "AbortError" && !init.signal) throw new Error(`连接 ${this.url} 超时`);
      if (err instanceof TypeError) throw new Error(`无法连接 ${this.url}：请确认已运行 taochronos serve（网页由 HTTPS 打开时，浏览器可能会询问是否允许访问本机网络）`);
      throw err;
    } finally {
      if (t) clearTimeout(t);
    }
  }

  start() {
    if (this.ready) return this.ready;
    this._status({ status: "loading", progress: 30, message: "连接本地服务" });
    this.ready = this._fetch("/api/info", {}, 8000)
      .then((info) => { this.info_ = info; this._status({ status: "ready", progress: 100, message: "" }); return info; })
      .catch((err) => { this._status({ status: "error", message: err.message }); this.ready = null; throw err; });
    return this.ready;
  }

  async info() { return this.info_ || (await this.start()); }
  catalog(mode) { return this._fetch(`/api/catalog?mode=${encodeURIComponent(mode)}`); }
  call(name, args, { maxChars, signal } = {}) {
    return this._fetch("/api/call", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, arguments: args, max_chars: maxChars }), signal });
  }
  passage(id) { return this._fetch(`/api/passage?id=${encodeURIComponent(id)}`); }
  session(id, what, extra = {}) {
    const q = new URLSearchParams({ what, ...extra });
    return this._fetch(`/api/session/${encodeURIComponent(id)}?${q}`);
  }
  async research(args, { onProgress, signal } = {}) {
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
export async function sameOriginServer() {
  if (!/^https?:$/.test(location.protocol) || location.hostname.endsWith("github.io")) return null;
  try {
    const r = await fetch("api/info", { cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.name === "TaoChronos" ? new URL(".", location.href).href : null;
  } catch {
    return null;
  }
}
