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
// 我的资料: a file the page hands over (data_add, its bytes transferred) is read, made anonymous and kept by the runtime;
// what was kept — the anonymous dataset, never the file — is stored here too (IndexedDB, "mydata:<id>") and given back to
// the runtime when it starts at the next visit, until the page removes it (data_remove, data_clear).
//
// Messages: {id, method, params} → {id, result} | {id, error}; while loading {type: "progress", progress, message}; while
// the rest is indexed {type: "index", indexed, total, done, kept}.

import { readAll, spool, unxz } from "./unpack.js";
import { LANG, T } from "./i18n.js";

const CDN = "https://cdn.jsdelivr.net/pyodide/v0.28.2/full/";
const CORPUS = "/home/pyodide/data/corpus/tcm.sqlite";
const SLICE = 3000;          // passages indexed per background step (a few tenths of a second)
const PART = 16 * 1048576;   // bytes per IndexedDB record of the kept store
let py = null;
let rpc = null;
let ready = null;

const progress = (p, message) => self.postMessage({ type: "progress", progress: Math.round(p), message });
const mb = (n) => (n / 1048576).toFixed(1);
/** fn, called at most every `ms` milliseconds (a status line, not a message per chunk). */
const every = (ms, fn) => { let last = 0; return (...a) => { const now = performance.now(); if (now - last >= ms) { last = now; fn(...a); } }; };

// ------------------------------------------------------------------------------------------------ kept between visits
/** IndexedDB, reduced to what this worker needs; every call resolves (undefined / false when storage is unavailable). */
const kept = (() => {
  let opened = null;
  const open = () => (opened ||= new Promise((resolve) => {
    try {
      const req = indexedDB.open("taochronos-runtime", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("files");
      req.onsuccess = () => resolve(req.result);
      req.onerror = req.onblocked = () => resolve(null);
    } catch { resolve(null); }
  }));
  const run = async (mode, fn) => {
    const db = await open();
    if (!db) return { ok: false };
    return new Promise((resolve) => {
      try {
        const tx = db.transaction("files", mode);
        const req = fn(tx.objectStore("files"));
        tx.oncomplete = () => resolve({ ok: true, value: req?.result });
        tx.onerror = tx.onabort = () => resolve({ ok: false });
      } catch { resolve({ ok: false }); }
    });
  };
  return {
    get: async (key) => (await run("readonly", (s) => s.get(key))).value,
    put: async (key, value) => (await run("readwrite", (s) => s.put(value, key))).ok,
    drop: async (key) => (await run("readwrite", (s) => s.delete(key))).ok,
    keys: async (prefix) => (await run("readonly", (s) => s.getAllKeys(IDBKeyRange.bound(prefix, `${prefix}\uffff`)))).value || [],
  };
})();

/** A runtime archive: kept by content (the manifest's sha256), so that a new build is always fetched. */
async function archive(base, name, sha) {
  const hit = sha ? await kept.get(`zip:${name}`) : undefined;
  if (sha && hit?.sha === sha && hit.blob instanceof Blob) return new Uint8Array(await hit.blob.arrayBuffer());
  const url = new URL(`runtime/${name}`, base).href;
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(T`下载 ${url} 失败（HTTP ${r.status}）`);
  const buf = new Uint8Array(await r.arrayBuffer());
  if (sha) kept.put(`zip:${name}`, { sha, blob: new Blob([buf]) }); // best effort, not waited for
  return buf;
}

/** The indexed store kept from an earlier visit: {parts: Blob[], bytes}, or null when there is none for this build. */
async function keptCorpus(sha) {
  const head = await kept.get("corpus");
  if (!head || head.sha !== sha || head.state !== "built") return null;
  const parts = [];
  for (let i = 0; i < head.parts; i++) {
    const blob = await kept.get(`corpus:${sha}:${i}`);
    if (!(blob instanceof Blob)) return null;
    parts.push(blob);
  }
  return { parts, bytes: head.bytes };
}

/** Keep the store (indexed) for the next visit, part by part; its head is written last, so a half-kept store is never read. */
async function keepCorpus(sha) {
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
 * thread would take its turns with Python's start); here as it was when a worker cannot be started from this one. */
function unpackCorpus(url, size, onGot, onUnpacked) {
  return new Promise((resolve, reject) => {
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
    helper.onmessage = ({ data }) => {
      heard = true;
      if (data.got !== undefined) onGot?.(data.got);
      if (data.unpacked !== undefined) onUnpacked?.(data.unpacked);
      if (data.error) { helper.terminate(); reject(new Error(data.error)); }
      if (data.buffer) { helper.terminate(); resolve(new Uint8Array(data.buffer)); }
    };
    helper.postMessage({ url, size });
  });
}

/** The corpus, whole in `buf`, as the file at CORPUS — the file system takes the buffer itself (canOwn). */
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
async function loadPython(base, manifest) {
  const wanted = new URL(manifest.pyodide_base || CDN, base).href;
  const bases = wanted === CDN ? [CDN] : [wanted, CDN];
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

async function keepBytecode(key) {
  try {
    py.runPython(BYTECODE);
    const make = py.globals.get("_bytecode");
    const data = make().toJs();
    make.destroy?.();
    await kept.put(key, { blob: new Blob([data]) });
  } catch { /* a later visit compiles from source, as before */ }
}

/** The rest of the corpus indexed in slices, between the questions the runtime answers; kept once it is all indexed. */
async function indexRest(sha, then) {
  const step = py.globals.get("_index");
  try {
    for (;;) {
      await new Promise((r) => setTimeout(r, 30)); // a question waiting is answered first
      const st = JSON.parse(step("all", SLICE));
      self.postMessage({ type: "index", indexed: st.indexed, total: st.total, done: st.state === "built" });
      if (st.state === "built") break;
      if (!st.indexed_now) return; // nothing moved: leave it (the next visit starts over)
    }
    const keptNow = await keepCorpus(sha);
    self.postMessage({ type: "index", done: true, kept: keptNow });
  } catch (err) {
    self.postMessage({ type: "index", error: String(err?.message || err) });
  } finally {
    step.destroy?.();
    then?.();
  }
}

// ------------------------------------------------------------------------------------------------------ 我的资料
const MINE = "mydata:";

/** A file of the user's: read and kept by the runtime, and its anonymous dataset kept here for the next visit. */
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

async function removeData({ id }) {
  const out = JSON.parse(rpc("data_remove", JSON.stringify({ id })));
  if (out.ok) await kept.drop(MINE + out.removed);
  return out;
}

async function clearData() {
  const out = JSON.parse(rpc("data_clear", "{}"));
  await kept.drop(IDBKeyRange.bound(MINE, `${MINE}\uffff`));
  return out;
}

async function init({ base }) {
  const t0 = performance.now();
  progress(3, T("读取运行清单"));
  const got = await fetch(new URL("runtime/manifest.json", base), { cache: "no-cache" });
  if (!got.ok) throw new Error(T`这里没有浏览器内运行环境（runtime/manifest.json：HTTP ${got.status}）：请用 taochronos web build 构建站点，或连接 taochronos serve`);
  const manifest = await got.json();
  const files = manifest.files || {};
  const meta = files["corpus.sqlite.xz"];

  // Python and the corpus at the same time: the status line shows both
  const view = { step: T("载入 Python 运行时"), frac: 0, got: 0, total: meta?.bytes || 0, downloading: false };
  const show = () => {
    const dl = view.downloading && view.got < view.total ? T` · 下载要籍语料 ${mb(view.got)} / ${mb(view.total)} MB（仅首次）` : "";
    const f = view.downloading ? 0.5 * view.frac + 0.5 * (view.got / view.total) : view.frac;
    progress(5 + 55 * f, view.step + dl);
  };
  const corpusSource = meta ? (async () => {
    const hit = await keptCorpus(meta.sha256);
    if (hit) return { kept: true, whole: new Blob(hit.parts).arrayBuffer().then((b) => new Uint8Array(b)) };
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
  corpusSource.catch(() => {}); // both awaited below; not unhandled rejections meanwhile
  archives.catch(() => {});

  show();
  py = await loadPython(base, manifest);
  view.step = T("载入 PyYAML 与 SQLite"); view.frac = 0.6; show();
  await py.loadPackage(["pyyaml", "sqlite3"], { messageCallback: () => {}, errorCallback: () => {} });
  view.step = T("载入 TaoChronos"); view.frac = 0.8; show();
  const [pkg, home] = await archives;
  const site = py.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
  py.unpackArchive(pkg, "zip", { extractDir: site });
  const pycKey = `pyc:${files["taochronos.zip"]?.sha256 || ""}`;
  const pyc = files["taochronos.zip"]?.sha256 ? await kept.get(pycKey) : undefined;
  if (pyc?.blob instanceof Blob) py.unpackArchive(new Uint8Array(await pyc.blob.arrayBuffer()), "zip", { extractDir: site });
  py.FS.mkdirTree("/home/pyodide/taochronos");
  py.FS.mkdirTree("/home/pyodide/data");
  py.unpackArchive(home, "zip", { extractDir: "/home/pyodide/taochronos" });
  py.runPython(ENV); // before anything reads the home: the indexer below loads the domain pack
  view.step = T("载入 TaoChronos"); view.frac = 1; show();

  let rest = false;
  if (meta) {
    const src = await corpusSource;
    if (src.kept) {
      progress(62, T("载入本机保存的要籍语料"));
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
      py.globals.set("_index_progress", (done, total) => progress(66 + 22 * done / total,
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
  const info = JSON.parse(rpc("info", "{}"));
  info.load_ms = Math.round(performance.now() - t0);
  info.version_manifest = manifest.version;
  progress(100, T("就绪"));
  const compile = pyc || !files["taochronos.zip"]?.sha256 ? null : () => setTimeout(() => keepBytecode(pycKey), 1000);
  if (rest) setTimeout(() => indexRest(meta.sha256, compile), 0);
  else compile?.();
  return info;
}

self.onmessage = async (e) => {
  const { id, method, params } = e.data || {};
  try {
    let result;
    if (method === "init") {
      ready ||= init(params || {});
      result = await ready;
    } else {
      if (!ready) throw new Error(T("运行环境尚未启动"));
      await ready;
      const local = { data_add: addData, data_remove: removeData, data_clear: clearData }[method];
      result = local ? await local(params || {}) : JSON.parse(rpc(method, JSON.stringify(params || {})));
    }
    self.postMessage({ id, result });
  } catch (err) {
    if (method === "init") ready = null;
    const msg = String(err?.message || err);
    self.postMessage({ id, error: msg.includes("Traceback") ? msg.split("\n").filter(Boolean).slice(-3).join(" ") : msg });
  }
};
