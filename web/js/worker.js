// The in-browser runtime: Pyodide (CPython compiled to WebAssembly) running the TaoChronos package on the 要籍语料 —
// the openly licensed texts of the ranked works, shipped as a store without its full-text index, indexed here on the
// first visit and kept (Cache API) — or, on a site built without it, the demonstration corpus.  It runs inside a
// module worker so the page never blocks.  Messages: {id, method, params} → {id, result} | {id, error}; progress while
// loading: {type: "progress", progress, message}.

const CDN = "https://cdn.jsdelivr.net/pyodide/v0.28.2/full/";
let py = null;
let rpc = null;
let ready = null;

const progress = (p, message) => self.postMessage({ type: "progress", progress: p, message });

async function bytes(url, sha) {
  // the runtime archives are cached by content (the manifest's sha256), so a new build is always fetched
  const key = sha ? `${url}#${sha}` : null;
  let cache = null;
  try { cache = key && self.caches ? await caches.open("taochronos-runtime") : null; } catch { cache = null; }
  if (cache) {
    const hit = await cache.match(key).catch(() => null);
    if (hit) return new Uint8Array(await hit.arrayBuffer());
  }
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`下载 ${url} 失败（HTTP ${r.status}）`);
  const buf = new Uint8Array(await r.arrayBuffer());
  if (cache) {
    try {
      for (const old of await cache.keys()) if (old.url.startsWith(url + "#")) await cache.delete(old);
      await cache.put(key, new Response(buf.slice()));
    } catch { /* storage full or unavailable: no cache */ }
  }
  return buf;
}

const CORPUS = "/home/pyodide/data/corpus/tcm.sqlite";
const mb = (n) => (n / 1048576).toFixed(1);

async function openCache() {
  try { return self.caches ? await caches.open("taochronos-runtime") : null; } catch { return null; }
}

async function download(url, total, onBytes) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`下载 ${url} 失败（HTTP ${r.status}）`);
  if (!r.body) return new Uint8Array(await r.arrayBuffer());
  const reader = r.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onBytes?.(got, total || got);
  }
  const out = new Uint8Array(got);
  let at = 0;
  for (const c of chunks) { out.set(c, at); at += c.length; }
  return out;
}

async function gunzip(buf) {
  const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** The 要籍语料 at CORPUS: the indexed store kept from an earlier visit, else downloaded, unpacked and indexed now. */
async function loadCorpus(base, meta) {
  const url = new URL("runtime/corpus.sqlite.gz", base).href;
  const key = `${url}#indexed-${meta.sha256}`;
  const cache = await openCache();
  py.FS.mkdirTree("/home/pyodide/data/corpus");
  const hit = cache ? await cache.match(key).catch(() => null) : null;
  if (hit) {
    progress(72, "载入要籍语料");
    py.FS.writeFile(CORPUS, new Uint8Array(await hit.arrayBuffer()));
    return;
  }
  const gz = await download(url, meta.bytes, (got, total) => progress(62 + 10 * got / total, `下载要籍语料 ${mb(got)} / ${mb(total)} MB（仅首次）`));
  py.FS.writeFile(CORPUS, await gunzip(gz));
  progress(74, "为要籍语料建立全文索引（仅首次）");
  py.globals.set("_index_progress", (done, total) => progress(74 + 12 * done / total, `建立全文索引 ${Math.round(100 * done / total)}%（仅首次）`));
  py.runPython(`
from pathlib import Path
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.webcorpus import index_store
index_store(Path("${CORPUS}"), DomainPack(Path("/home/pyodide/taochronos/domains/classics")).variants.normalize_text,
            progress=lambda done, total: _index_progress(done, total))
`);
  if (cache) {
    try {
      for (const old of await cache.keys()) if (old.url.startsWith(url + "#")) await cache.delete(old);
      await cache.put(key, new Response(py.FS.readFile(CORPUS)));
    } catch { /* storage full or unavailable: indexed again next time */ }
  }
}

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

async function init({ base }) {
  const t0 = performance.now();
  progress(5, "读取运行清单");
  const got = await fetch(new URL("runtime/manifest.json", base), { cache: "no-cache" });
  if (!got.ok) throw new Error(`这里没有浏览器内运行环境（runtime/manifest.json：HTTP ${got.status}）：请用 taochronos web build 构建站点，或连接 taochronos serve`);
  const manifest = await got.json();
  progress(12, "载入 Python 运行时（首次约 10 MB）");
  py = await loadPython(base, manifest);
  progress(45, "载入 PyYAML 与 SQLite");
  await py.loadPackage(["pyyaml", "sqlite3"], { messageCallback: () => {}, errorCallback: () => {} });
  progress(56, "载入 TaoChronos");
  const files = manifest.files || {};
  const [pkg, home] = await Promise.all([
    bytes(new URL("runtime/taochronos.zip", base).href, files["taochronos.zip"]?.sha256),
    bytes(new URL("runtime/home.zip", base).href, files["home.zip"]?.sha256),
  ]);
  const site = py.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
  py.unpackArchive(pkg, "zip", { extractDir: site });
  py.FS.mkdirTree("/home/pyodide/taochronos");
  py.FS.mkdirTree("/home/pyodide/data");
  py.unpackArchive(home, "zip", { extractDir: "/home/pyodide/taochronos" });
  const corpus = files["corpus.sqlite.gz"];
  if (corpus) await loadCorpus(base, corpus);
  py.globals.set("_profile", corpus ? corpus.profile || "web-canon" : "full-discovery");
  progress(88, "建立工具网格");
  py.runPython(BOOT);
  rpc = py.globals.get("_rpc");
  const info = JSON.parse(rpc("info", "{}"));
  info.load_ms = Math.round(performance.now() - t0);
  info.version_manifest = manifest.version;
  progress(100, "就绪");
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
