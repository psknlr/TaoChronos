// Where TaoChronos runs: in this browser (Pyodide in a worker, on the 要籍语料) or under `taochronos serve` — on the
// user's machine or another one they run it on (the full corpus).  Both answer the same calls — info, catalog, call,
// passage, research — with the same shapes, because both run the same Python module (taochronos.chat).  The browser
// runtime knows its info and catalogs before it has loaded (runtime/boot.json, written by the build), so that a
// conversation can begin at once; only the tools it calls wait for it.
//
// Both also keep the user's own data (我的资料: addData, listData, removeData, clearData) — but only where it stays on the
// user's machine: in this browser, or in a server on this machine (`local`).  The page reads the data with a runtime
// that is (app.js, dataRuntime).
//
// A call (call, research) takes, besides its arguments: `signal`, which ends the wait for it; `onWait(why)` and
// `onStart()`, which the runtime calls when the call waits — for the runtime to load ("loading") or for its turn
// ("queued") — and when it begins to run, so that its deadline (agent.js) counts the time it runs; and `giving`, a
// signal that it may give way to the calls behind it (no one waits for it but a research run going on by itself).  The
// browser's worker runs one call at a time; a server, a few.

import { LANG, T } from "./i18n.js";
import { LIMITS, aborted, limit, pause, until } from "./limits.js";

// a call the browser's worker runs, which no one waits for (or which may give way), while one waits behind it: given
// this long, then the worker is started again — the one way to stop Python here where it cannot be interrupted
const STUCK_MS = 60000;
// a server's calls at once (a round of tools may ask for many)
const SERVER_SLOTS = 4;
// a research run on a server: looked at this often; looks that fail (a network gone a while, a server restarting) less
// and less often, up to POLL_SLOWEST apart, and for LOST_MS in all before the run is given up; a run the server stopped
// (it restarted) taken up again so many times at most
const POLL_EVERY = 900;
const POLL_SLOWEST = 15000;
const LOST_MS = 120000;
const RESUMES = 2;
// a research run's states on a server (taochronos.chat.jobs), and those an earlier server named by its words
const ENDED = new Set(["completed", "failed", "cancelled"]);
const LEGACY = { done: "completed", error: "failed" };

/** A research run's state, from how a server describes it: its `state`, or what the words of an earlier one mean. */
export const jobState = (st) => st?.state || LEGACY[st?.status] || st?.status || "unknown";

/** What a research run's step says while it goes on: from the server's view of it (its state, its place in the queue,
 * how long it waited and ran, its progress and heartbeat), or the page's own (`lost`: it cannot reach the server). */
export function researchText(p) {
  const s = (n) => Math.round(Number(n) || 0);
  const state = jobState(p);
  if (state === "lost") return T`等待恢复：与服务的连接中断，正在重新连接（已 ${s(p.lost_s)} 秒）`;
  if (state === "interrupted") return T("等待恢复：服务重启过，正在从上次的检查点继续");
  if (state === "cancel_requested") return T("正在停止：等当前这一步完成");
  if (state === "queued") { // its place among those waiting: the one running is ahead of them all
    return p.position > 1 ? T`排队中：前面还有 ${p.position} 项研究 · 已等 ${s(p.queued_s ?? p.elapsed_s)} 秒`
      : T`排队中：服务正在完成另一项研究 · 已等 ${s(p.queued_s ?? p.elapsed_s)} 秒`;
  }
  const pr = p?.progress || {};
  const done = [pr.round ? T`第 ${pr.round} 轮` : "", pr.hypotheses ? T`${pr.hypotheses} 个假说` : "", pr.claims ? T`${pr.claims} 条主张` : ""];
  const quiet = p?.heartbeat_s > 30 ? T` · 服务 ${s(p.heartbeat_s)} 秒没有回应`
    : p?.progress_s > 60 ? T` · ${s(p.progress_s)} 秒没有新进展` : "";
  return `${T("研究进行中")}${done.filter(Boolean).map((x) => ` · ${x}`).join("")}${T` · 已运行 ${s(p?.run_s ?? p?.elapsed_s)} 秒`}${quiet}`;
}

// a corpus by its kind (a runtime's info)
const CORPUS = { full: T("全量语料"), canon: T("要籍语料"), demo: T("演示语料") };

/** A turn's instructions, asked for before each of its requests (agent.js, runTurn's `system`): `prompt(info, change)`
 * for the runtime it began on (`began`: its info) — and from when that runtime could not answer and the browser took
 * over (it has a `backup`: the site's server, app.js inBrowserInstead), for the browser's info, which describes the
 * corpus the calls read from then on, with a word to the model of the change.  The tools stay as they were: both
 * runtimes offer the same ones (the same Python module, taochronos.chat). */
export function turnInstructions(runtime, began, prompt) {
  const first = prompt(began, "");
  let moved = null;
  return async () => {
    const now = runtime?.backup;
    if (!now) return first;
    if (moved?.rt !== now) {
      const info = await now.info().catch(() => null); // (a browser that cannot start fails the calls: they say so)
      const [from, to] = [CORPUS[began?.corpus?.kind] || CORPUS.full, CORPUS[info?.corpus?.kind] || CORPUS.canon];
      const change = T`本轮开始时，工具调用由${runtime.label}回答，读${from}；它现在不能回答，此后的调用改在这个浏览器里运行，读${to}（见上面的“运行环境”）。此前得到的工具结果仍然有效，照常引用；此后的检索只覆盖这个语料，没有检得的内容可能只是不在其中，回答时请说明。`;
      moved = { rt: now, text: prompt(info || began, `\n\n## 运行环境在本轮中的变化\n${change}`) };
    }
    return moved.text;
  };
}

const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

export function isLoopback(url) {
  try { return LOOPBACK.has(new URL(url).hostname); } catch { return false; }
}

/** Why this page cannot reach a server at `url` at all, if it cannot. */
export function unreachable(url) {
  let u;
  try { u = new URL(url); } catch { return T`服务地址无效：${url}`; }
  if (!/^https?:$/.test(u.protocol)) return T`服务地址须以 http:// 或 https:// 开头：${url}`;
  if (location.protocol === "https:" && u.protocol === "http:" && !LOOPBACK.has(u.hostname)) {
    return T`本页经 HTTPS 打开，浏览器不允许它访问其他机器上的 http:// 地址：请直接打开该服务自己的网页（${u.origin}/），或为服务配置 HTTPS`;
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
    this.label = T("浏览器内");
    this.worker = null;
    this.seq = 0;
    this.starting = null; // the worker's start: {id, resolve, reject}
    this.queue = [];      // calls waiting for the worker, in order
    this.busy = null;     // the call it runs: it runs one at a time
    this.stuck = null;    // the watch on a call it runs that no one waits for, while one waits behind it
    this.stuckMs = STUCK_MS;
    this.interrupt = null; // where the worker can be interrupted (a cross-origin isolated page): its flag
    this.listeners = new Set();
    this.state = { status: "idle", progress: 0, message: "", index: null };
    this.ready = null;
    this.boot = null; // runtime/boot.json: {info, catalogs}
  }

  onStatus(fn) { this.listeners.add(fn); fn(this.state); return () => this.listeners.delete(fn); }
  _status(patch) { this.state = { ...this.state, ...patch }; for (const fn of this.listeners) fn(this.state); }

  start() {
    if (this.ready) return this.ready;
    this._status({ status: "loading", progress: 2, message: T("启动运行环境") });
    this.boot ||= fetch(new URL("../runtime/boot.json", import.meta.url), { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const worker = new Worker(new URL(`./worker.js?lang=${LANG}`, import.meta.url), { type: "module", name: "taochronos" });
    this.worker = worker;
    worker.onmessage = (e) => { if (this.worker === worker) this._message(e.data || {}); };
    worker.onerror = (e) => { if (this.worker === worker) this._fail(e.message || T("运行环境出错")); };
    const ready = new Promise((resolve, reject) => {
      this.starting = { id: ++this.seq, resolve, reject };
      worker.postMessage({ id: this.starting.id, method: "init", params: { base: new URL("../", import.meta.url).href } });
    }).then((info) => {
      this._status({ status: "ready", progress: 100, message: "" });
      this.info_ = info;
      this._next();
      return info;
    }).catch((err) => {
      if (this.ready === ready) { // not a worker ended meanwhile (_end): that one's calls have their end already
        this._status({ status: "error", message: err.message });
        this.ready = null;
        for (const job of this.queue.splice(0)) this._settle(job, { error: err.message });
      }
      throw err;
    });
    this.ready = ready;
    return ready;
  }

  stop() { this._end(T("运行环境已切换"), true); }

  /** The worker ended: what it ran, what waited for it, and its start, end with `why`; `all`: the calls waiting too. */
  _end(why, all) {
    this.worker?.terminate();
    this.worker = null;
    this.ready = null;
    this.info_ = null;
    this.interrupt = null;
    this.stuck?.stop();
    this.stuck = null;
    this.starting?.reject(new Error(why));
    this.starting = null;
    const job = this.busy;
    this.busy = null;
    if (job) this._settle(job, { error: why });
    if (all) for (const j of this.queue.splice(0)) this._settle(j, { error: why });
  }

  /** The worker failed (an error it did not catch): what it ran and what waited end with it; the next call starts a
   * new one. */
  _fail(message) {
    this._end(message, true);
    this._status({ status: "error", message });
  }

  /** Started again: the one way to stop a call the worker runs when it cannot be interrupted.  The call it ran ends
   * with `why`; the calls waiting go to the new worker.  What the runtime held only in memory goes with the old one
   * (research sessions, and the user's datasets this browser could not keep); what it kept is read again. */
  restart(why) {
    this._end(why, false);
    this._status({ status: "loading", progress: 2, message: why });
    this.start().catch(() => { /* the calls waiting have the error */ });
  }

  _message(msg) {
    if (msg.type === "progress") { this._status({ status: "loading", progress: msg.progress, message: msg.message }); return; }
    if (msg.type === "index") { this._status({ index: { ...this.state.index, ...msg } }); return; }
    if (msg.type === "interrupt") { this.interrupt = new Int32Array(msg.buffer); return; }
    if (this.starting?.id === msg.id) {
      const s = this.starting;
      this.starting = null;
      if (msg.error) s.reject(new Error(msg.error));
      else s.resolve(msg.result);
      return;
    }
    const job = this.busy;
    if (!job || job.id !== msg.id) return;
    this.busy = null;
    this._settle(job, msg);
    this._next();
  }

  /** A call's end: given to the caller still waiting for it, and dropped otherwise. */
  _settle(job, { result, error }) {
    if (!job.wanted) return;
    job.wanted = false;
    job.done();
    if (error) job.reject(new Error(error));
    else job.resolve(result);
  }

  /** A call to the worker, after those before it (the worker runs one at a time).  `signal` ends the wait: a call not
   * yet begun is never sent; one begun is let run — or interrupted, where the worker can be — and what it returns is
   * dropped.  `giving`: it may give way to the calls behind it.  `onStart()` when it is sent. */
  _call(method, params, transfer = [], { signal, giving, onWait, onStart } = {}) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) return reject(aborted());
      const job = { id: ++this.seq, method, params, transfer, resolve, reject, wanted: true, giving: Boolean(giving?.aborted), onStart };
      const drop = () => this._drop(job);
      const give = () => { job.giving = true; this._watch(); };
      signal?.addEventListener("abort", drop, { once: true });
      giving?.addEventListener("abort", give, { once: true });
      job.done = () => {
        signal?.removeEventListener("abort", drop);
        giving?.removeEventListener("abort", give);
      };
      this.queue.push(job);
      if (this.busy) onWait?.("queued");
      this._next();
      this._watch();
    });
  }

  _next() {
    if (this.busy || !this.worker || !this.info_ || !this.queue.length) return;
    const job = this.queue.shift();
    this.busy = job;
    if (this.interrupt) Atomics.store(this.interrupt, 0, 0); // an interrupt meant for the call before is not this one's
    this.worker.postMessage({ id: job.id, method: job.method, params: job.params }, job.transfer);
    job.transfer = [];
    job.onStart?.();
    this._watch();
  }

  /** No one waits for the call any more: one not yet sent is never sent; one the worker runs is interrupted where it
   * can be (SIGINT: Python raises KeyboardInterrupt), and let run where not — what it returns is dropped. */
  _drop(job) {
    if (!job.wanted) return;
    job.wanted = false;
    job.done();
    const at = this.queue.indexOf(job);
    if (at >= 0) this.queue.splice(at, 1);
    else if (this.busy === job && this.interrupt) Atomics.store(this.interrupt, 0, 2);
    job.reject(aborted());
    this._watch();
  }

  /** The worker runs a call no one waits for (or one that may give way) while a call waits behind it: given `stuckMs`
   * of the time the page runs, then the worker is started again. */
  _watch() {
    const job = this.busy;
    const blocking = job && (!job.wanted || job.giving) && this.queue.length > 0;
    if (!blocking) { this.stuck?.stop(); this.stuck = null; return; }
    if (this.stuck?.job === job) return;
    this.stuck?.stop();
    const watch = limit(this.stuckMs, () => {
      if (this.busy === job && this.queue.length) this.restart(T("运行环境被一个不再等待的调用占住，已重新启动"));
    });
    this.stuck = { job, stop: () => watch.stop() };
  }

  /** A call once the worker has started (the time it takes to load does not count: `onWait("loading")`). */
  async call_(method, params, options = {}) {
    if (!this.info_) options.onWait?.("loading");
    await until(this.start(), options.signal);
    return this._call(method, params, [], options);
  }
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
  call(name, args, { maxChars, ...options } = {}) { return this.call_("call", { name, arguments: args, max_chars: maxChars }, options); }
  passage(id) { return this.call_("passage", { id }); }
  session(id, what, extra = {}) { return this.call_("session", { session_id: id, what, ...extra }); }
  get local() { return true; }
  /** A file of the user's (an ArrayBuffer, handed over to the worker): {ok, dataset} or {ok: false, error}. */
  async addData(name, buffer) { await this.start(); return this._call("data_add", { name, bytes: buffer }, [buffer]); }
  listData() { return this.call_("data_list"); }
  removeData(id) { return this.call_("data_remove", { id }); }
  clearData() { return this.call_("data_clear"); }
  async research(args, { onProgress, ...options } = {}) {
    let started = 0;
    const timer = setInterval(() => started && onProgress?.({ status: "running", elapsed_s: (Date.now() - started) / 1000 }), 500);
    const onStart = () => { started = Date.now(); options.onStart?.(); };
    try { return await this.call("taochronos_research", args, { ...options, onStart }); } finally { clearInterval(timer); }
  }
}

export class ServerRuntime {
  /** `fallback` (the site's own server): a runtime to answer instead when this server cannot — asleep past waiting, or
   * down — called once, with the error. */
  constructor(url, token = "", { label = "", fallback = null } = {}) {
    this.kind = "server";
    this.url = url.replace(/\/+$/, "");
    this.token = token || "";
    this.label = label || (isLoopback(this.url) ? T("本地服务") : T("远程服务"));
    this.state = { status: "idle", progress: 0, message: "" };
    this.listeners = new Set();
    this.ready = null;
    this.fallback = fallback;
    this.backup = null;
    this.running = 0;  // calls under way
    this.waiting = []; // calls waiting for one of SERVER_SLOTS
    this.pollEvery = POLL_EVERY;
    this.lostAfter = LOST_MS;
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

  /** A request to the server, ended by the caller's `init.signal` (an AbortError) or by `timeout` (the server did not
   * answer in time: unavailable), whichever comes first. */
  async _fetch(path, init = {}, timeout = 0) {
    const bad = unreachable(this.url);
    if (bad) throw new Error(bad);
    const ctl = new AbortController();
    const outer = init.signal;
    let late = false;
    const t = timeout ? setTimeout(() => { late = true; ctl.abort(); }, timeout) : null;
    const stop = () => ctl.abort();
    if (outer?.aborted) ctl.abort();
    else outer?.addEventListener("abort", stop, { once: true });
    try {
      const r = await until(fetch(this.url + path, { ...init, headers: { ...tokenHeaders(this.token), ...(init.headers || {}) }, signal: ctl.signal }), ctl.signal);
      const j = await until(r.json(), ctl.signal).catch((err) => { if (ctl.signal.aborted) throw err; return {}; });
      if ([502, 503, 504].includes(r.status)) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), { unavailable: true });
      // the site's own server refused this visitor (an address it restricts, or the day's reads spent): the page carries
      // on in the browser, on its public files, and says why; the server is not asked again this visit
      if (this.fallback && refusal(r, j)) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), { unavailable: true, refused: j.blocked ? "blocked" : "daily" });
      if (r.status === 401 && j.token_required) {
        throw Object.assign(new Error(this.token
          ? T("访问令牌不对：请核对 taochronos serve 启动时打印的令牌（设置 → 运行环境）")
          : T("这个服务需要访问令牌：请填写 taochronos serve 启动时打印的令牌（设置 → 运行环境）")), { tokenRequired: true });
      }
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      return j;
    } catch (err) {
      if (outer?.aborted) throw aborted();
      if (late) throw Object.assign(new Error(T`连接 ${this.url} 超时`), { unavailable: true });
      if (err instanceof TypeError) {
        throw Object.assign(new Error(this.fallback ? T`无法连接 ${this.url}` : T`无法连接 ${this.url}：请确认 taochronos serve 正在运行（网页由 HTTPS 打开时，浏览器可能会询问是否允许访问本机网络）`), { unavailable: true });
      }
      throw err;
    } finally {
      if (t) clearTimeout(t);
      outer?.removeEventListener("abort", stop);
    }
  }

  /** One of SERVER_SLOTS for a call (waiting, `onWait("queued")`, while all are taken); returns what frees it. */
  async _slot(signal, onWait) {
    if (this.running < SERVER_SLOTS) {
      this.running++;
    } else {
      onWait?.("queued");
      await new Promise((resolve, reject) => {
        const entry = { resolve: () => { signal?.removeEventListener("abort", leave); resolve(); } };
        const leave = () => { this.waiting.splice(this.waiting.indexOf(entry), 1); reject(aborted()); };
        if (signal?.aborted) return reject(aborted());
        signal?.addEventListener("abort", leave, { once: true });
        this.waiting.push(entry);
      });
    }
    let freed = false;
    return () => {
      if (freed) return;
      freed = true;
      const next = this.waiting.shift();
      if (next) next.resolve(); // the slot passes to the next call
      else this.running--;
    };
  }

  start() {
    if (this.ready) return this.ready;
    this._status({ status: "loading", progress: 30, message: T`连接${this.label}` });
    this.ready = this._fetch("/api/info", {}, 30000)
      .then((info) => { this.info_ = info; this._status({ status: "ready", progress: 100, message: "" }); return info; })
      .catch((err) => { this._status({ status: "error", message: err.message }); this.ready = null; throw err; });
    return this.ready;
  }

  async info() { return this.info_ || (await this.start()); }
  catalog(mode) { return this._fetch(`/api/catalog?mode=${encodeURIComponent(mode)}`); }
  /** A server on this machine may keep the user's data; one elsewhere is never sent it (the page uses the browser). */
  get local() { return isLoopback(this.url); }
  addData(name, buffer) {
    return this._fetch("/api/data", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, data: base64(buffer) }) });
  }
  listData() { return this._fetch("/api/data"); }
  removeData(id) { return this._fetch("/api/data/remove", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) }); }
  clearData() { return this._fetch("/api/data/clear", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); }
  async call(name, args, options = {}) {
    if (this.backup) return this.backup.call(name, args, options);
    const { maxChars, signal, onStart } = options;
    let free = await this._slot(signal, options.onWait);
    try {
      onStart?.();
      return await this._fetch("/api/call", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, arguments: args, max_chars: maxChars }), signal });
    } catch (err) {
      free();
      free = null;
      return this._or(err, (rt) => rt.call(name, args, options));
    } finally {
      free?.();
    }
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
  /** A research run this server began before — the page that asked for it was closed, or reloaded — followed again to
   * its end, as `research` follows one (its options; `job`: the run's id, as onJob gave it). */
  followResearch(job, options = {}) { return this._research(null, { ...options, job }); }
  /** Ask the server to stop a run: no one waits for it, and it would hold the queue of runs behind it. */
  cancelResearch(job) {
    return this._fetch(`/api/research/${encodeURIComponent(job)}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 10000)
      .catch(() => null); // a server that cannot be reached, or of an earlier version: the run ends by its own limits
  }
  /** A research run on the server: started (`onJob({id, url})` once it has an id, by which the page can follow it again on
   * this server), or, given `job`, one started before; then looked at until it ends.  Each look has a limit of its own
   * (limits.poll); looks that fail — a network gone a while, a server restarting — are borne for lostAfter, less and
   * less often, the run said meanwhile to await recovery (onProgress({state: "lost"})), and a run the server stopped as
   * it restarted is taken up again from its last checkpoint.  The run is "queued" while it waits for its turn, and runs once the server says so (onWait / onStart).
   * Its start has no limit: a server slow to answer may have begun the run, which is not begun again in the browser.
   * The run's own deadline and a stop end the wait, and the server is asked to stop the run: no one waits for it. */
  async _research(args, { onProgress, signal, onWait, onStart, limits, onJob, job: given } = {}) {
    const lim = { ...LIMITS, ...limits };
    const job = given || (await this._fetch("/api/research", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args), signal })).job;
    if (!given) onJob?.({ id: job, url: this.url });
    let running = false;
    let lost = 0; // since when the looks fail
    let wait = this.pollEvery;
    let resumed = 0;
    try {
      for (;;) {
        await pause(wait, signal);
        let st;
        try {
          st = await this._fetch(`/api/research/${encodeURIComponent(job)}`, { signal }, lim.poll);
        } catch (err) {
          if (signal?.aborted) throw aborted();
          // not "unavailable": the run is the server's, and is not started again in the browser; a refusal is not borne
          lost ||= Date.now();
          if (err.tokenRequired || err.refused || Date.now() - lost >= this.lostAfter) throw new Error(T`与研究任务失去联系：${err.message}`);
          wait = Math.min(wait * 2, POLL_SLOWEST);
          onProgress?.({ state: "lost", lost_s: (Date.now() - lost) / 1000 });
          continue;
        }
        lost = 0;
        wait = this.pollEvery;
        const state = jobState(st);
        if (state === "queued") onWait?.("queued");
        else if (!running && (state === "running" || state === "cancel_requested")) { running = true; onStart?.(); }
        onProgress?.(st);
        if (state === "interrupted" && resumed < RESUMES) { // the server restarted: from its last checkpoint
          resumed++;
          await this._fetch(`/api/research/${encodeURIComponent(job)}/resume`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", signal }, lim.poll)
            .catch(() => { if (signal?.aborted) throw aborted(); });
          continue;
        }
        if (ENDED.has(state) || state === "interrupted") return st.outcome;
        if (state === "unknown") throw new Error(T("研究任务已丢失（服务是否重启过？）"));
      }
    } catch (err) {
      if (signal?.aborted && err?.name === "AbortError") this.cancelResearch(job);
      throw err;
    }
  }
}

/** A refusal by the site's own server (cloud/site/src/site.js): 403 for an address it restricts, 429 for a day spent —
 * not a minute's rate limit (that one passes), not an error of the call's own. */
export const refusal = (r, j) => r.headers.get("X-TC-Corpus") === "refused" && ((r.status === 403 && j?.blocked === true) || (r.status === 429 && j?.daily === true));

/** Bytes as base64, a slice at a time (a whole file at once would overflow the arguments of fromCharCode). */
export function base64(buffer) {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

/** Is a TaoChronos server answering at this origin (the client served by `taochronos serve`)? */
export async function sameOriginServer(token = "") {
  if (!/^https?:$/.test(location.protocol) || location.hostname.endsWith("github.io")) return null;
  const here = new URL(".", location.href).href;
  return (await probeServer(here, token, 8000)) ? here : null;
}
