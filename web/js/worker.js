// The in-browser runtime: Pyodide (CPython compiled to WebAssembly) running the TaoChronos package on the 要籍语料 — the
// 350 ranked works (the first classics whole, the rest in chapters spread through the book), shipped xz-compressed as a
// store without its full-text index — or, on a site built without it, the demonstration corpus.  It runs inside a module
// worker so the page never blocks.
//
// Loading is arranged for the wait a visitor sees:
// * the corpus downloads while Python starts, not after;
// * on the first visit the works ranked first are indexed before the runtime answers, the rest in the background,
//   between questions (their text is there from the start; only their search waits);
// * what was downloaded and indexed is kept in IndexedDB — which, unlike the Cache API, a page served over http:// has
//   too — so that a later visit loads in seconds, with nothing to download or index.
//
// Messages: {id, method, params} → {id, result} | {id, error}; while loading {type: "progress", progress, message}; while
// the rest is indexed {type: "index", indexed, total, done, kept}.

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
  };
})();

/** A runtime archive: kept by content (the manifest's sha256), so that a new build is always fetched. */
async function archive(base, name, sha) {
  const hit = sha ? await kept.get(`zip:${name}`) : undefined;
  if (hit?.sha === sha && hit.blob instanceof Blob) return new Uint8Array(await hit.blob.arrayBuffer());
  const url = new URL(`runtime/${name}`, base).href;
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`下载 ${url} 失败（HTTP ${r.status}）`);
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
/** The response body read at full speed into memory, as a stream its consumer drains whenever it is ready: the download
 * runs while Python starts, and what arrived is unpacked from the moment Python is there. */
function spool(body, onBytes) {
  const queue = [];
  let done = false;
  let failed = null;
  let wake = null;
  let got = 0;
  (async () => {
    const reader = body.getReader();
    try {
      for (;;) {
        const { done: end, value } = await reader.read();
        if (end) break;
        queue.push(value);
        got += value.length;
        onBytes?.(got);
        wake?.();
      }
    } catch (err) {
      failed = err;
    }
    done = true;
    wake?.();
  })();
  return new ReadableStream({
    async pull(ctl) {
      while (!queue.length && !done) await new Promise((r) => { wake = r; });
      wake = null;
      if (queue.length) ctl.enqueue(queue.shift());
      else if (failed) ctl.error(failed);
      else ctl.close();
    },
  });
}

let XzStream = null;
async function unxz(stream) {
  if (!XzStream) {
    const mod = await import("./vendor/xzwasm.min.js");
    XzStream = (mod.default || self.xzwasm).XzReadableStream;
  }
  return new XzStream(stream);
}

/** Write a stream of bytes into the Python file system at CORPUS (the file sized first: no growing copies). */
async function streamToCorpus(stream, size, onBytes) {
  py.FS.mkdirTree("/home/pyodide/data/corpus");
  py.FS.writeFile(CORPUS, new Uint8Array(0));
  if (size) py.FS.truncate(CORPUS, size);
  const file = py.FS.open(CORPUS, "r+");
  const reader = stream.getReader();
  let pos = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      py.FS.write(file, value, 0, value.length, pos);
      pos += value.length;
      onBytes?.(pos);
    }
  } finally {
    py.FS.close(file);
  }
  if (size && pos !== size) throw new Error(`要籍语料不完整（${pos} / ${size} 字节）：请刷新重试`);
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
  throw new Error(`无法载入 Python 运行时（${lastErr?.message || lastErr}）`);
}

const BOOT = `
import json, os
os.environ["TAOCHRONOS_HOME"] = "/home/pyodide/taochronos"
os.environ["TAOCHRONOS_DATA"] = "/home/pyodide/data"
os.environ["TAOCHRONOS_CACHE"] = "off"
os.environ["TAOCHRONOS_SQLITE_JOURNAL"] = "DELETE"   # the index is built through a second connection
os.environ["TAOCHRONOS_SQLITE_CACHE_KB"] = "32000"   # the file is in memory already
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

/** The rest of the corpus indexed in slices, between the questions the runtime answers; kept once it is all indexed. */
async function indexRest(sha) {
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
  }
}

async function init({ base }) {
  const t0 = performance.now();
  progress(3, "读取运行清单");
  const got = await fetch(new URL("runtime/manifest.json", base), { cache: "no-cache" });
  if (!got.ok) throw new Error(`这里没有浏览器内运行环境（runtime/manifest.json：HTTP ${got.status}）：请用 taochronos web build 构建站点，或连接 taochronos serve`);
  const manifest = await got.json();
  const files = manifest.files || {};
  const meta = files["corpus.sqlite.xz"];

  // Python and the corpus at the same time: the status line shows both
  const view = { step: "载入 Python 运行时", frac: 0, got: 0, total: meta?.bytes || 0, downloading: false };
  const show = () => {
    const dl = view.downloading && view.got < view.total ? ` · 下载要籍语料 ${mb(view.got)} / ${mb(view.total)} MB（仅首次）` : "";
    const f = view.downloading ? 0.5 * view.frac + 0.5 * (view.got / view.total) : view.frac;
    progress(5 + 55 * f, view.step + dl);
  };
  const corpusSource = meta ? (async () => {
    const hit = await keptCorpus(meta.sha256);
    if (hit) return hit;
    const url = new URL("runtime/corpus.sqlite.xz", base).href;
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok || !r.body) throw new Error(`下载 ${url} 失败（HTTP ${r.status}）`);
    view.downloading = true;
    const showSoon = every(200, show);
    return { stream: spool(r.body, (g) => { view.got = g; showSoon(); }) };
  })() : Promise.resolve(null);
  const archives = Promise.all([
    archive(base, "taochronos.zip", files["taochronos.zip"]?.sha256),
    archive(base, "home.zip", files["home.zip"]?.sha256),
  ]);
  corpusSource.catch(() => {}); // both awaited below; not unhandled rejections meanwhile
  archives.catch(() => {});

  show();
  py = await loadPython(base, manifest);
  view.step = "载入 PyYAML 与 SQLite"; view.frac = 0.6; show();
  await py.loadPackage(["pyyaml", "sqlite3"], { messageCallback: () => {}, errorCallback: () => {} });
  view.step = "载入 TaoChronos"; view.frac = 0.8; show();
  const [pkg, home] = await archives;
  const site = py.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
  py.unpackArchive(pkg, "zip", { extractDir: site });
  py.FS.mkdirTree("/home/pyodide/taochronos");
  py.FS.mkdirTree("/home/pyodide/data");
  py.unpackArchive(home, "zip", { extractDir: "/home/pyodide/taochronos" });
  view.step = "载入 TaoChronos"; view.frac = 1; show();

  let rest = false;
  if (meta) {
    const src = await corpusSource;
    if (src.parts) {
      progress(62, "载入本机保存的要籍语料");
      await streamToCorpus(new Blob(src.parts).stream(), src.bytes);
    } else {
      py.runPython(INDEX); // the indexer's code, while the download may still be running
      const unpacking = every(200, (n) => {
        const dl = view.got < view.total ? `下载要籍语料 ${mb(view.got)} / ${mb(view.total)} MB · ` : "";
        progress(60 + 6 * n / meta.raw_bytes, `${dl}解压（仅首次）`);
      });
      await streamToCorpus(await unxz(src.stream), meta.raw_bytes, unpacking);
      const what = meta.core_rank && meta.core_passages < meta.passages ? `前 ${meta.core_rank} 部要籍` : "要籍语料";
      py.globals.set("_index_progress", (done, total) => progress(66 + 22 * done / total,
        `为${what}建立全文索引 ${Math.round(100 * done / total)}%（仅首次）`));
      py.runPython(`_index("core", progress=lambda done, total: _index_progress(done, total))`);
      rest = true;
    }
  }
  py.globals.set("_profile", meta ? meta.profile || "web-canon" : "full-discovery");
  progress(90, "建立工具网格");
  py.runPython(BOOT);
  rpc = py.globals.get("_rpc");
  const info = JSON.parse(rpc("info", "{}"));
  info.load_ms = Math.round(performance.now() - t0);
  info.version_manifest = manifest.version;
  progress(100, "就绪");
  if (rest) setTimeout(() => indexRest(meta.sha256), 0);
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
      if (!ready) throw new Error("运行环境尚未启动");
      await ready;
      result = JSON.parse(rpc(method, JSON.stringify(params || {})));
    }
    self.postMessage({ id, result });
  } catch (err) {
    if (method === "init") ready = null;
    const msg = String(err?.message || err);
    self.postMessage({ id, error: msg.includes("Traceback") ? msg.split("\n").filter(Boolean).slice(-3).join(" ") : msg });
  }
};
