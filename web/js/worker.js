// @ts-check
// The in-browser runtime: Pyodide (CPython compiled to WebAssembly) running the TaoChronos package on the 要籍语料 — the
// ranked works (the first classics whole, the rest in chapters spread through the book), shipped xz-compressed as a
// store without its full-text index — or, on a site built without it, the demonstration corpus.  It runs inside a module
// worker so the page never blocks.
//
// Loading is arranged for the wait a visitor sees:
// * the corpus downloads and is unpacked while Python starts, on a thread of its own (unpack-worker.js), and is handed
//   to Python's file system without a copy;
// * on the first visit the works ranked first are indexed before the runtime answers, the rest in the background,
//   between questions (their text is there from the start; only their search waits);
// * the YAML the runtime reads comes parsed with the site (home.zip, .cache/yaml), the store's counts with the store;
// * what was downloaded and indexed is kept in IndexedDB — which, unlike the Cache API, a page served over http:// has
//   too — so that a later visit loads in seconds, with nothing to download or index; so is the package's bytecode,
//   compiled once after the first visit's indexing.
//
// TaoCore (docs/adr/0036-taocore.md): what a search computes over its candidates — BM25 of its query's tokens, the
// hashed n-gram cosines — runs in a WebAssembly module (runtime/taocore.wasm, of no imports) where it loads: fetched
// beside the archives, instantiated here (the page's own policy compiles no WebAssembly), and handed to Python as
// `_taocore_wasm` before Python imports the package.  It is optional: where it does not load, or gives other numbers
// than Python's own definitions on the self-test Python runs before using it, the search computes the same numbers in
// Python, more slowly.
//
// 我的资料: a file the page hands over (data_add, its bytes transferred) is read, made anonymous and kept by the runtime;
// what was kept — the anonymous dataset, never the file — is stored here too (IndexedDB, "mydata:<id>") and given back to
// the runtime when it starts at the next visit, until the page removes it (data_remove, data_clear).
//
// Messages: {id, method, params} → {id, result} | {id, error}; while loading {type: "progress", progress, message}; while
// the rest is indexed {type: "index", indexed, total, done, kept}.  The page sends one call at a time (runtime.js).
//
// Where the page is cross-origin isolated (it can share memory with this worker), Python can be interrupted: the worker
// hands the page a flag ({type: "interrupt", buffer}), and a call the page no longer waits for is stopped when Python
// next looks at it (KeyboardInterrupt).  Elsewhere a call runs to its end, and the page drops what it returns.

import { listen } from "./inbox.js"; // first: it keeps the page's init while i18n.js waits for its dictionary
import { readAll, spool, unxz } from "./unpack.js";
import { LANG, T } from "./i18n.js";

/** @import { DataAddResult, DataClearResult, DataRemoveResult, RuntimeInfo, UnpackMessage, UnpackRequest, WorkerEvent, WorkerReply, WorkerRequest } from "../../tools/typecheck/types/runtime" */
/**
 * @typedef {object} PyFS  the part of Emscripten's file system this worker uses
 * @property {(path: string) => void} mkdirTree
 * @property {(path: string, data: Uint8Array) => void} writeFile
 * @property {(path: string) => void} unlink
 * @property {(path: string) => { size: number }} stat
 * @property {(path: string, flags: string) => unknown} open
 * @property {(stream: unknown, buffer: Uint8Array, offset: number, length: number, position?: number) => number} read
 * @property {(stream: unknown, buffer: Uint8Array, offset: number, length: number, position?: number, canOwn?: boolean) => number} write
 * @property {(stream: unknown) => void} close
 */
/**
 * @typedef {object} Pyodide  the part of Pyodide's API this worker uses (pyodide.mjs, loadPyodide)
 * @property {(code: string) => any} runPython
 * @property {(names: string[], options?: { messageCallback?: (message: string) => void, errorCallback?: (message: string) => void, checkIntegrity?: boolean }) => Promise<{ name: string }[]>} loadPackage
 *   settles with what it loaded: a package it could not load is left out, and why is said only to errorCallback
 * @property {Record<string, string>} loadedPackages  each package loaded, by name: where from
 * @property {(buffer: Uint8Array, format: string, options?: { extractDir?: string }) => void} unpackArchive
 * @property {(name: string, module: object) => void} registerJsModule
 * @property {(buffer: Int32Array) => void} setInterruptBuffer
 * @property {{ get(name: string): any, set(name: string, value: unknown): void }} globals
 * @property {PyFS} FS
 */
/**
 * @typedef {object} RuntimeFile  a file of the manifest (chat/build.py manifest())
 * @property {number} bytes
 * @property {string} sha256
 * @property {number} [abi]
 */
/**
 * @typedef {RuntimeFile & { raw_bytes: number, passages: number, core_rank: number, core_passages: number, profile?: string }} CorpusFile
 *   the corpus's, with what it holds (webcorpus.site_store_info)
 */
/** @typedef {{ version: string, files?: Record<string, RuntimeFile>, pyodide_base?: string }} Manifest  runtime/manifest.json */

const CDN = "https://cdn.jsdelivr.net/pyodide/v0.28.2/full/";
const CORPUS = "/home/pyodide/data/corpus/tcm.sqlite";
const SLICE = 3000;          // passages indexed per background step (a few tenths of a second)
const PART = 16 * 1048576;   // bytes per IndexedDB record of the kept store
/** @type {Pyodide} */
let py = /** @type {any} */ (null);
/** @type {(method: string, params: string) => string} */
let rpc = /** @type {any} */ (null);
/** @type {Promise<RuntimeInfo> | null} */
let ready = null;
/** @type {Int32Array<SharedArrayBuffer> | null} */
let interrupt = null; // the flag the page sets to interrupt Python (SIGINT, 2), where it can share it
/** @type {Promise<unknown> | null} */
let keepingNow = null; // the store being kept for the next visit (indexRest): a call waits for it, a moment
const KEEP_WAIT_MS = 5000; // at the most

/** @param {number} p @param {string} message */
const progress = (p, message) => self.postMessage(/** @satisfies {WorkerEvent} */ ({ type: "progress", progress: Math.round(p), message }));
/** @param {number} n */
const mb = (n) => (n / 1048576).toFixed(1);
/** fn, called at most every `ms` milliseconds (a status line, not a message per chunk).
 * @param {number} ms @param {(...a: any[]) => void} fn @returns {(...a: any[]) => void} */
const every = (ms, fn) => { let last = 0; return (...a) => { const now = performance.now(); if (now - last >= ms) { last = now; fn(...a); } }; };

// ------------------------------------------------------------------------------------------------ kept between visits
/** IndexedDB, reduced to what this worker needs; every call resolves (undefined / false when storage is unavailable). */
const kept = (() => {
  /** @type {Promise<IDBDatabase | null> | null} */
  let opened = null;
  // a connection the browser closes (storage reclaimed or cleared, another tab's upgrade) is forgotten: the next use
  // opens a new one (store.js does the same for the conversations)
  /** @param {IDBDatabase} db */
  const forget = (db) => { try { db.close(); } catch { /* closed already */ } opened = null; };
  const open = () => (opened ||= new Promise((resolve) => {
    try {
      const req = indexedDB.open("taochronos-runtime", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("files");
      req.onsuccess = () => {
        const db = req.result;
        db.onclose = db.onversionchange = () => forget(db);
        resolve(db);
      };
      req.onerror = req.onblocked = () => resolve(null);
    } catch { resolve(null); }
  }));
  /** @param {IDBDatabase} db @param {IDBTransactionMode} mode @param {(s: IDBObjectStore) => IDBRequest | undefined} fn
   * @returns {Promise<{ ok: boolean, value?: any, gone?: boolean }>} */
  const once = (db, mode, fn) => new Promise((resolve) => {
    try {
      const tx = db.transaction("files", mode);
      const req = fn(tx.objectStore("files"));
      tx.oncomplete = () => resolve({ ok: true, value: req?.result });
      tx.onerror = tx.onabort = () => resolve({ ok: false });
    } catch (err) { resolve({ ok: false, gone: /** @type {any} */ (err)?.name === "InvalidStateError" }); }
  });
  /** @param {IDBTransactionMode} mode @param {(s: IDBObjectStore) => IDBRequest | undefined} fn */
  const run = async (mode, fn) => {
    const db = await open();
    if (!db) return { ok: false };
    const got = await once(db, mode, fn);
    if (!got.gone) return got;
    forget(db); // closed under the worker: once more, on a new connection
    const again = await open();
    return again ? once(again, mode, fn) : { ok: false };
  };
  return {
    /** @param {string} key @returns {Promise<any>} */
    get: async (key) => (await run("readonly", (s) => s.get(key))).value,
    /** @param {string} key @param {unknown} value */
    put: async (key, value) => (await run("readwrite", (s) => s.put(value, key))).ok,
    /** @param {string | IDBKeyRange} key */
    drop: async (key) => (await run("readwrite", (s) => s.delete(key))).ok,
    /** @param {string} prefix @returns {Promise<string[]>} */
    keys: async (prefix) => (await run("readonly", (s) => s.getAllKeys(IDBKeyRange.bound(prefix, `${prefix}\uffff`)))).value || [],
  };
})();

/** The bytes' SHA-256 in hex, or null where this browser offers none (crypto.subtle is a secure context's).
 * @param {Uint8Array<ArrayBuffer>} bytes @returns {Promise<string | null>} */
async function sha256(bytes) {
  try {
    return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

/** A runtime archive: kept by content (the manifest's sha256), so that a new build is always fetched.  Bytes are kept,
 * and a kept copy read, only when they are what the manifest names (`checked`) — a download cut short, or a file older
 * than the manifest (a cache between here and the site), is used this once and fetched anew the next time, where it was
 * once kept for good; a kept copy the browser can no longer read is dropped and fetched anew, where it ended every
 * later start.  Where the browser computes no hash (crypto.subtle: a page served over plain http from another
 * machine), nothing can be checked, so nothing is kept.  `exact` refuses bytes not checked (an optional file: better
 * none than another).
 * @param {string} base @param {string} name @param {string | undefined} sha @param {boolean} [exact]
 * @returns {Promise<{ bytes: Uint8Array<ArrayBuffer>, checked: boolean }>} */
async function archive(base, name, sha, exact = false) {
  const hit = sha ? await kept.get(`zip:${name}`) : undefined;
  if (sha && hit?.sha === sha && hit.blob instanceof Blob) {
    try {
      const bytes = new Uint8Array(await hit.blob.arrayBuffer());
      if ((await sha256(bytes)) === sha) return { bytes, checked: true };
    } catch { /* its bytes can no longer be read (the browser's file of it is gone or damaged) */ }
    kept.drop(`zip:${name}`); // no longer what its name says, or not readable: fetched anew
  }
  const url = new URL(`runtime/${name}`, base).href;
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(T`下载 ${url} 失败（HTTP ${r.status}）`);
  const bytes = new Uint8Array(await r.arrayBuffer());
  const got = sha ? await sha256(bytes) : null;
  const checked = got !== null && got === sha;
  if (checked) kept.put(`zip:${name}`, { sha, blob: new Blob([bytes]) }); // best effort, not waited for
  else if (exact) throw new Error(got === null ? `runtime/${name} cannot be checked here` : `runtime/${name} is not the file the manifest names`);
  return { bytes, checked };
}

/** `fn`, while no other tab of this browser keeps a store ("shared"), or while none keeps or reads one ("exclusive"):
 * two tabs keeping theirs at once would leave parts of each under one head.  Where the browser has no locks (they are a
 * secure context's: an http:// page of another machine), or refuses them (a browser set to keep no site data refuses
 * its locks as it refuses IndexedDB), at once, as before: a lock not had is never why the runtime does not start.
 * @template T @param {"shared" | "exclusive"} mode @param {() => Promise<T>} fn @returns {Promise<T>} */
function keeping(mode, fn) {
  const locks = self.navigator?.locks;
  if (!locks) return fn();
  let began = false;
  /** @type {Promise<T>} */
  let asked;
  try {
    asked = locks.request("taochronos-keep", { mode }, () => { began = true; return fn(); });
  } catch {
    return fn();
  }
  return asked.catch((err) => { if (began) throw err; return fn(); }); // refused before fn began: without the lock
}

/** The indexed store kept from an earlier visit: {parts: Blob[], bytes}, or null when there is none for this build, or
 * when its parts do not add up to the size its head names.
 * @param {string} sha @returns {Promise<{ parts: Blob[], bytes: number } | null>} */
function keptCorpus(sha) {
  return keeping("shared", async () => {
    const head = await kept.get("corpus");
    if (!head || head.sha !== sha || head.state !== "built") return null;
    const parts = [];
    for (let i = 0; i < head.parts; i++) {
      const blob = await kept.get(`corpus:${sha}:${i}`);
      if (!(blob instanceof Blob)) return null;
      parts.push(blob);
    }
    return parts.reduce((n, b) => n + b.size, 0) === head.bytes ? { parts, bytes: head.bytes } : null;
  });
}

/** Keep the store (indexed) for the next visit, part by part; its head is written last, so a half-kept store is never
 * read, and one tab at a time (keeping).
 * @param {string} sha */
function keepCorpus(sha) {
  return keeping("exclusive", () => keepCorpusNow(sha));
}

/** @param {string} sha */
async function keepCorpusNow(sha) {
  await kept.drop("corpus");
  await kept.drop(IDBKeyRange.bound("corpus:", "corpus:\uffff")); // any earlier build's parts, kept or half kept
  // one snapshot, read between two questions with no await in between: a question answered meanwhile may write to the
  // store (the claim cache, committed at once), and a copy taken across it would be torn
  const size = py.FS.stat(CORPUS).size;
  const file = py.FS.open(CORPUS, "r");
  const parts = [];
  try {
    for (let pos = 0; pos < size; pos += PART) {
      const buf = new Uint8Array(Math.min(PART, size - pos));
      py.FS.read(file, buf, 0, buf.length, pos);
      parts.push(new Blob([buf]));
    }
  } finally {
    py.FS.close(file);
  }
  for (let i = 0; i < parts.length; i++) {
    if (!(await kept.put(`corpus:${sha}:${i}`, parts[i]))) return false; // storage full or refused
  }
  return kept.put("corpus", { sha, parts: parts.length, bytes: size, state: "built" });
}

// ------------------------------------------------------------------------------------------------------- download

/** The corpus downloaded and unpacked in a worker of its own, in parallel with Python starting here (unpacking on this
 * thread would take its turns with Python's start); here as it was when a worker cannot be started from this one.
 * @param {string} url @param {number} size @param {(n: number) => void} [onGot] @param {(n: number) => void} [onUnpacked]
 * @returns {Promise<Uint8Array>} */
function unpackCorpus(url, size, onGot, onUnpacked) {
  return new Promise((resolve, reject) => {
    /** @type {Worker | null} */
    let helper = null;
    const here = async () => {
      const r = await fetch(url, { cache: "no-cache" });
      if (!r.ok || !r.body) throw new Error(T`下载 ${url} 失败（HTTP ${r.status}）`);
      return readAll(await unxz(spool(r.body, onGot)), size, onUnpacked);
    };
    const fallback = () => { helper?.terminate(); helper = null; here().then(resolve, reject); };
    try {
      helper = new Worker(new URL(`./unpack-worker.js?lang=${LANG}`, import.meta.url), { type: "module", name: "taochronos-unpack" });
    } catch {
      fallback();
      return;
    }
    let heard = false;
    helper.onerror = (e) => { e.preventDefault?.(); if (!heard) fallback(); else { helper?.terminate(); reject(new Error(T("解压要籍语料失败：请刷新重试"))); } };
    helper.onmessage = (/** @type {MessageEvent<UnpackMessage>} */ { data }) => {
      heard = true;
      if (data.got !== undefined) onGot?.(data.got);
      if (data.unpacked !== undefined) onUnpacked?.(data.unpacked);
      if (data.error) { /** @type {Worker} */ (helper).terminate(); reject(new Error(data.error)); }
      if (data.buffer) { /** @type {Worker} */ (helper).terminate(); resolve(new Uint8Array(data.buffer)); }
    };
    helper.postMessage(/** @satisfies {UnpackRequest} */ ({ url, size }));
  });
}

/** The corpus, whole in `buf`, as the file at CORPUS — the file system takes the buffer itself (canOwn).
 * @param {Uint8Array} buf */
function ownCorpus(buf) {
  py.FS.mkdirTree("/home/pyodide/data/corpus");
  const file = py.FS.open(CORPUS, "w+");
  try {
    py.FS.write(file, buf, 0, buf.length, 0, true);
  } finally {
    py.FS.close(file);
  }
}

// ----------------------------------------------------------------------------------------------------------- Python
/** @param {string} base @param {Manifest} manifest @returns {Promise<Pyodide>} */
async function loadPython(base, manifest) {
  const wanted = new URL(manifest.pyodide_base || CDN, base).href;
  const bases = wanted === CDN ? [CDN] : [wanted, CDN];
  /** @type {any} */
  let lastErr = null;
  for (const b of bases) {
    try {
      const mod = await import(/* @vite-ignore */ b + "pyodide.mjs");
      return await mod.loadPyodide({ indexURL: b, stdout: () => {}, stderr: () => {} });
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(T`无法载入 Python 运行时（${lastErr?.message || lastErr}）`);
}

/** Pyodide's packages the runtime needs, loaded.  loadPackage settles without one it could not load and says why only
 * to its callbacks: here that is the start's end, with the package and why, rather than an import that fails later.
 * @param {Pyodide} py @param {string[]} names */
async function loadPackages(py, names) {
  /** @type {string[]} */
  const why = []; // its causes, without the line that announces each ("The following error occurred while loading …:")
  const said = (/** @type {string} */ m) => { if (!m.startsWith("The following error occurred")) why.push(m); };
  await py.loadPackage(names, { messageCallback: () => {}, errorCallback: said });
  const missing = names.filter((n) => !Object.hasOwn(py.loadedPackages, n)).join(", ");
  if (missing) throw new Error(T`无法载入 Python 运行时（${why.length ? `${missing}: ${why.join(" ")}` : missing}）`);
}

const ENV = `
import os
os.environ["TAOCHRONOS_HOME"] = "/home/pyodide/taochronos"
os.environ["TAOCHRONOS_DATA"] = "/home/pyodide/data"
os.environ["TAOCHRONOS_CACHE"] = "/home/pyodide/taochronos/.cache"  # the YAML it reads, parsed by the build (home.zip)
os.environ["TAOCHRONOS_SQLITE_JOURNAL"] = "DELETE"   # the index is built through a second connection
os.environ["TAOCHRONOS_SQLITE_CACHE_KB"] = "32000"   # the file is in memory already
`;

const BOOT = `
import json
from taochronos.chat import ChatRuntime
_rt = ChatRuntime.create(_profile, kind="browser", ephemeral=True, data_dir="/home/pyodide/data")

def _rpc(method, params):
    p = json.loads(params or "{}")
    if method == "info":
        out = _rt.info()
    elif method == "catalog":
        out = _rt.catalog(p.get("mode") or "core")
    elif method == "call":
        out = _rt.call(p.get("name", ""), p.get("arguments") or {}, max_chars=int(p.get("max_chars") or 16000))
    elif method == "passage":
        out = _rt.passage(p.get("id", ""))
    elif method == "session":
        out = _rt.session_view(p["session_id"], what=p.get("what", "summary"), hypothesis=p.get("hypothesis"),
                               section=p.get("section"))
    elif method == "data_add":
        with open(p["path"], "rb") as f:
            out = _rt.data_add(p.get("name", ""), f.read())
    elif method == "data_list":
        out = _rt.data_list()
    elif method == "data_remove":
        out = _rt.data_remove(p.get("id", ""))
    elif method == "data_clear":
        out = _rt.data_clear()
    elif method == "data_export":
        out = _rt.data_export(p.get("id", ""))
    elif method == "data_restore":
        out = _rt.data_restore(p.get("data") or {})
    else:
        raise ValueError(f"unknown method {method}")
    return json.dumps(out, ensure_ascii=False, default=str)
`;

const INDEX = `
import json
from pathlib import Path
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.webcorpus import index_state, index_store
_normalize = DomainPack(Path("/home/pyodide/taochronos/domains/classics")).variants.normalize_text

def _index(phase, limit=0, progress=None):
    n = index_store(Path("${CORPUS}"), _normalize, phase=phase, limit=limit or None, progress=progress)
    return json.dumps({"indexed_now": n, **index_state(Path("${CORPUS}"))})
`;

// What searches run on, as Python found it: TaoCore's module once it passed the self-test Python runs before using it
// (here, where no search and no indexing has used it yet), or Python's own code and why.
const TAOCORE = `
import json
from taochronos.plugins.retrieval import taocore as _taocore
json.dumps(_taocore.status())
`;

// The package's bytecode, compiled once in this browser and kept (by the package's hash): a later visit imports it
// instead of compiling some 240 modules from source (about a second).  Unchecked-hash .pyc: valid whatever the files'
// times, and only ever next to the very sources they were compiled from.
const BYTECODE = `
import compileall, io, os, py_compile, sysconfig, zipfile
def _bytecode():
    root = sysconfig.get_paths()["purelib"]
    compileall.compile_dir(os.path.join(root, "taochronos"), quiet=1, force=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for d, _, names in os.walk(os.path.join(root, "taochronos")):
            if d.endswith("__pycache__"):
                for n in names:
                    z.write(os.path.join(d, n), os.path.relpath(os.path.join(d, n), root))
    return buf.getvalue()
`;

/** @param {string} key */
async function keepBytecode(key) {
  try {
    py.runPython(BYTECODE);
    const make = py.globals.get("_bytecode");
    const data = make().toJs();
    make.destroy?.();
    await kept.drop(IDBKeyRange.bound("pyc:", "pyc:\uffff")); // an earlier build's: one build's is kept, not each one's
    await kept.put(key, { blob: new Blob([data]) });
  } catch { /* a later visit compiles from source, as before */ }
}

/** The rest of the corpus indexed in slices, between the questions the runtime answers; kept once it is all indexed.
 * @param {string} sha @param {(() => void) | null} [then] */
async function indexRest(sha, then) {
  const step = py.globals.get("_index");
  let again = false;
  try {
    for (;;) {
      await new Promise((r) => setTimeout(r, 30)); // a question waiting is answered first
      const st = JSON.parse(step("all", SLICE));
      self.postMessage(/** @satisfies {WorkerEvent} */ ({ type: "index", indexed: st.indexed, total: st.total, done: st.state === "built" }));
      if (st.state === "built") break;
      if (!st.indexed_now) return; // nothing moved: leave it (the next visit starts over)
    }
    // a call that began while the store is kept would hold its lock, and its open transaction, for as long as Python
    // ran it — up to a research run's half hour, during which another tab's start waited: calls wait for the keep
    // instead (the handler below), which takes a fraction of a second
    const saved = keepCorpus(sha);
    keepingNow = saved.catch(() => {}).finally(() => { keepingNow = null; });
    const keptNow = await saved;
    self.postMessage(/** @satisfies {WorkerEvent} */ ({ type: "index", done: true, kept: keptNow }));
  } catch (err) {
    // an interrupt meant for a call that ended as this slice began: the slice, not committed, is indexed again
    if (/KeyboardInterrupt/.test(String(/** @type {any} */ (err)?.message || err))) again = true;
    else self.postMessage(/** @satisfies {WorkerEvent} */ ({ type: "index", error: String(/** @type {any} */ (err)?.message || err) }));
  } finally {
    step.destroy?.();
    if (again) setTimeout(() => indexRest(sha, then), 0);
    else then?.();
  }
}

// ------------------------------------------------------------------------------------------------------ 我的资料
const MINE = "mydata:";

/** A file of the user's: read and kept by the runtime, and its anonymous dataset kept here for the next visit.
 * @param {{ name: string, bytes: ArrayBuffer }} file @returns {Promise<DataAddResult>} */
async function addData({ name, bytes }) {
  const path = `/tmp/mydata-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  py.FS.writeFile(path, new Uint8Array(bytes));
  try {
    const out = JSON.parse(rpc("data_add", JSON.stringify({ name, path })));
    if (out.ok) out.kept = await kept.put(MINE + out.dataset.id, rpc("data_export", JSON.stringify({ id: out.dataset.id })));
    return out;
  } finally {
    try { py.FS.unlink(path); } catch { /* gone already */ }
  }
}

/** The datasets kept by earlier visits, given back to the runtime; one it cannot read any more is dropped. */
async function restoreData() {
  for (const key of await kept.keys(MINE)) {
    const text = await kept.get(key);
    let ok = false;
    try { ok = typeof text === "string" && JSON.parse(rpc("data_restore", `{"data":${text}}`)).ok; } catch { ok = false; }
    if (!ok) await kept.drop(key);
  }
}

/** @param {{ id: string }} dataset @returns {Promise<DataRemoveResult>} */
async function removeData({ id }) {
  const out = JSON.parse(rpc("data_remove", JSON.stringify({ id })));
  if (out.ok) await kept.drop(MINE + out.removed);
  return out;
}

/** @returns {Promise<DataClearResult>} */
async function clearData() {
  const out = JSON.parse(rpc("data_clear", "{}"));
  await kept.drop(IDBKeyRange.bound(MINE, `${MINE}\uffff`));
  return out;
}

/** @param {{ base: string }} params @returns {Promise<RuntimeInfo>} */
async function init({ base }) {
  const t0 = performance.now();
  progress(3, T("读取运行清单"));
  const got = await fetch(new URL("runtime/manifest.json", base), { cache: "no-cache" });
  if (!got.ok) throw new Error(T`这里没有内置运行环境（runtime/manifest.json：HTTP ${got.status}）：请用 taochronos web build 构建站点，或连接 taochronos serve`);
  const manifest = /** @type {Manifest} */ (await got.json());
  /** @type {Record<string, RuntimeFile>} */
  const files = manifest.files || {};
  const meta = /** @type {CorpusFile | undefined} */ (files["corpus.sqlite.xz"]);

  // Python and the corpus at the same time: the status line shows both
  /** @type {{ step: string, frac: number, got: number, total: number, downloading: boolean, unpacked?: number }} */
  const view = { step: T("载入 Python 运行时"), frac: 0, got: 0, total: meta?.bytes || 0, downloading: false };
  const show = () => {
    const dl = view.downloading && view.got < view.total ? T` · 下载要籍语料 ${mb(view.got)} / ${mb(view.total)} MB（仅首次）` : "";
    const f = view.downloading ? 0.5 * view.frac + 0.5 * (view.got / view.total) : view.frac;
    progress(5 + 55 * f, view.step + dl);
  };
  const corpusSource = meta ? (async () => {
    const hit = await keptCorpus(meta.sha256);
    if (hit) {
      // read here, not later: a kept store whose bytes the browser can no longer read (a part's file gone from its
      // profile) is forgotten and downloaded again, where it ended this start and every one after it
      try {
        return { kept: true, whole: Promise.resolve(new Uint8Array(await new Blob(hit.parts).arrayBuffer())) };
      } catch {
        kept.drop("corpus");
      }
    }
    const url = new URL("runtime/corpus.sqlite.xz", base).href;
    view.downloading = true;
    const showSoon = every(200, show);
    // downloaded and unpacked as it arrives, while Python starts
    const whole = unpackCorpus(url, meta.raw_bytes, (g) => { view.got = g; showSoon(); }, (n) => { view.unpacked = n; });
    whole.catch(() => {});
    return { whole };
  })() : Promise.resolve(null);
  const archives = Promise.all([
    archive(base, "taochronos.zip", files["taochronos.zip"]?.sha256),
    archive(base, "home.zip", files["home.zip"]?.sha256),
  ]);
  // TaoCore: the module and its loader, imported only now (a static import that failed would take this worker with it)
  const kernel = files["taocore.wasm"];
  const taocore = kernel
    ? Promise.all([archive(base, "taocore.wasm", kernel.sha256, true), import("./taocore.js")]).then(([a, m]) => m.loadTaoCore(a.bytes))
    : Promise.reject(new Error("the site carries no runtime/taocore.wasm"));
  corpusSource.catch(() => {}); // all awaited below; not unhandled rejections meanwhile
  archives.catch(() => {});
  taocore.catch(() => {});

  show();
  py = await loadPython(base, manifest);
  if (self.crossOriginIsolated && typeof SharedArrayBuffer === "function") {
    interrupt = new Int32Array(new SharedArrayBuffer(4));
    py.setInterruptBuffer(interrupt);
    self.postMessage(/** @satisfies {WorkerEvent} */ ({ type: "interrupt", buffer: interrupt.buffer }));
  }
  view.step = T("载入 PyYAML 与 SQLite"); view.frac = 0.6; show();
  await loadPackages(py, ["pyyaml", "sqlite3"]);
  view.step = T("载入 TaoChronos"); view.frac = 0.8; show();
  const [pkg, home] = await archives;
  const site = py.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
  py.unpackArchive(pkg.bytes, "zip", { extractDir: site });
  // the bytecode kept is that of the package the manifest names: laid over that package alone, and made only from it
  // (made from another — an older file a cache gave — it would be that one's, kept under this one's name)
  const pycKey = `pyc:${files["taochronos.zip"]?.sha256 || ""}`;
  let pyc = pkg.checked ? await kept.get(pycKey) : undefined;
  try {
    if (pyc?.blob instanceof Blob) py.unpackArchive(new Uint8Array(await pyc.blob.arrayBuffer()), "zip", { extractDir: site });
  } catch {
    pyc = undefined; // not readable any more: Python compiles from the sources, and the bytecode is kept again below
  }
  py.FS.mkdirTree("/home/pyodide/taochronos");
  py.FS.mkdirTree("/home/pyodide/data");
  py.unpackArchive(home.bytes, "zip", { extractDir: "/home/pyodide/taochronos" });
  py.runPython(ENV); // before anything reads the home: the indexer below loads the domain pack
  // before Python imports the package; a download that stalls does not hold the runtime up
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let timer;
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("runtime/taocore.wasm did not load in time")), 10000); });
  /** @type {{ module?: object, err?: any }} */
  const core = await Promise.race([taocore, late]).then((module) => ({ module }), (err) => ({ err }));
  clearTimeout(timer);
  if (core.module) py.registerJsModule("_taocore_wasm", core.module);
  view.step = T("载入 TaoChronos"); view.frac = 1; show();

  let rest = false;
  if (meta) {
    const src = /** @type {{ kept?: boolean, whole: Promise<Uint8Array> }} */ (await corpusSource);
    if (src.kept) {
      progress(62, T("载入已保存的要籍语料"));
      ownCorpus(await src.whole);
    } else {
      py.runPython(INDEX); // the indexer's code, while the download may still be running
      const unpacking = setInterval(() => {
        const dl = view.got < view.total ? T`下载要籍语料 ${mb(view.got)} / ${mb(view.total)} MB · ` : "";
        progress(60 + 6 * (view.unpacked || 0) / meta.raw_bytes, T`${dl}解压（仅首次）`);
      }, 200);
      try {
        ownCorpus(await src.whole);
      } finally {
        clearInterval(unpacking);
      }
      const what = meta.core_rank && meta.core_passages < meta.passages ? T`前 ${meta.core_rank} 部要籍` : T("要籍语料");
      py.globals.set("_index_progress", /** @param {number} done @param {number} total */ (done, total) => progress(66 + 22 * done / total,
        T`为${what}建立全文索引 ${Math.round(100 * done / total)}%（仅首次）`));
      py.runPython(`_index("core", progress=lambda done, total: _index_progress(done, total))`);
      rest = true;
    }
  }
  py.globals.set("_profile", meta ? meta.profile || "web-canon" : "full-discovery");
  progress(90, T("建立工具网格"));
  py.runPython(BOOT);
  rpc = py.globals.get("_rpc");
  await restoreData();
  const info = /** @type {RuntimeInfo} */ (JSON.parse(rpc("info", "{}")));
  info.load_ms = Math.round(performance.now() - t0);
  info.version_manifest = manifest.version;
  try {
    info.taocore = core.module ? JSON.parse(py.runPython(TAOCORE)) : { kernel: null, reason: String(core.err?.message || core.err) };
  } catch (err) {
    info.taocore = { kernel: null, reason: String(/** @type {any} */ (err)?.message || err) };
  }
  progress(100, T("就绪"));
  const compile = pyc || !pkg.checked ? null : () => setTimeout(() => keepBytecode(pycKey), 1000);
  if (rest) setTimeout(() => indexRest(/** @type {CorpusFile} */ (meta).sha256, compile), 0);
  else compile?.();
  return info;
}

listen(async (/** @type {MessageEvent<WorkerRequest>} */ e) => {
  const { id, method, params } = /** @type {WorkerRequest} */ (e.data || {});
  try {
    let result;
    if (method === "init") {
      ready ||= init(params || {});
      result = await ready;
    } else {
      if (!ready) throw new Error(T("运行环境尚未启动"));
      await ready;
      // the store is being kept: after it — or after KEEP_WAIT_MS, should the browser's storage be that slow
      if (keepingNow) await Promise.race([keepingNow, new Promise((r) => setTimeout(r, KEEP_WAIT_MS))]);
      if (interrupt) Atomics.store(interrupt, 0, 0); // one set for the call before this one is not for this one
      const local = /** @type {Record<string, ((params: any) => Promise<unknown>) | undefined>} */ ({ data_add: addData, data_remove: removeData, data_clear: clearData })[method];
      result = local ? await local(params || {}) : JSON.parse(rpc(method, JSON.stringify(params || {})));
    }
    self.postMessage(/** @satisfies {WorkerReply} */ ({ id, result }));
  } catch (err) {
    if (method === "init") ready = null;
    const msg = String(/** @type {any} */ (err)?.message || err);
    self.postMessage(/** @satisfies {WorkerReply} */ ({ id, error: msg.includes("Traceback") ? msg.split("\n").filter(Boolean).slice(-3).join(" ") : msg }));
  }
});
