// Downloads and unpacks the 要籍语料 for the runtime's worker, on a thread of its own, so that unpacking runs alongside
// Python's start instead of taking turns with it.  {url, size} → {got} / {unpacked} as it goes, then {buffer}
// (transferred, not copied) or {error}.

import { readAll, spool, unxz } from "./unpack.js";

const every = (ms, fn) => { let last = 0; return (n) => { const now = performance.now(); if (now - last >= ms) { last = now; fn(n); } }; };

self.onmessage = async ({ data: { url, size } }) => {
  try {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok || !r.body) throw new Error(`下载 ${url} 失败（HTTP ${r.status}）`);
    const got = every(150, (n) => self.postMessage({ got: n }));
    const unpacked = every(150, (n) => self.postMessage({ unpacked: n }));
    const buf = await readAll(await unxz(spool(r.body, got)), size, unpacked);
    self.postMessage({ unpacked: size, buffer: buf.buffer }, [buf.buffer]);
  } catch (err) {
    self.postMessage({ error: String(err?.message || err) });
  }
};
