// @ts-check
// Downloads and unpacks the 要籍语料 for the runtime's worker, on a thread of its own, so that unpacking runs alongside
// Python's start instead of taking turns with it.  {url, size} → {got} / {unpacked} as it goes, then {buffer}
// (transferred, not copied) or {error}.

import { listen } from "./inbox.js"; // first: it keeps the request while i18n.js waits for its dictionary
import { readAll, spool, unxz } from "./unpack.js";
import { T } from "./i18n.js";
/** @import { UnpackMessage, UnpackRequest } from "../../tools/typecheck/types/runtime" */

/** @param {number} ms @param {(n: number) => void} fn @returns {(n: number) => void} */
const every = (ms, fn) => { let last = 0; return (n) => { const now = performance.now(); if (now - last >= ms) { last = now; fn(n); } }; };

listen(async (/** @type {MessageEvent<UnpackRequest>} */ { data: { url, size } }) => {
  try {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok || !r.body) throw new Error(T`下载 ${url} 失败（HTTP ${r.status}）`);
    const got = every(150, (n) => self.postMessage(/** @satisfies {UnpackMessage} */ ({ got: n })));
    const unpacked = every(150, (n) => self.postMessage(/** @satisfies {UnpackMessage} */ ({ unpacked: n })));
    const buf = await readAll(await unxz(spool(r.body, got)), size, unpacked);
    self.postMessage(/** @satisfies {UnpackMessage} */ ({ unpacked: size, buffer: buf.buffer }), [buf.buffer]);
  } catch (/** @type {any} */ err) {
    self.postMessage(/** @satisfies {UnpackMessage} */ ({ error: String(err?.message || err) }));
  }
});
