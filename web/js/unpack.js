// @ts-check
// Downloading and unpacking the 要籍语料 (xz): shared by the runtime's worker and the worker that unpacks for it.

import { T } from "./i18n.js";

/** The response body read at full speed into memory, as a stream its consumer drains whenever it is ready: the download
 * never waits for the unpacking.
 * @param {ReadableStream<Uint8Array>} body @param {(n: number) => void} [onBytes]
 * @returns {ReadableStream<Uint8Array>} */
export function spool(body, onBytes) {
  /** @type {Uint8Array[]} */
  const queue = [];
  let done = false;
  /** @type {unknown} */
  let failed = null;
  /** @type {((value?: unknown) => void) | null} */
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
        /** @type {(() => void) | null} */ (wake)?.(); // (tsc reads this function as run before pull() sets it)
      }
    } catch (err) {
      failed = err;
    }
    done = true;
    /** @type {(() => void) | null} */ (wake)?.();
  })();
  return new ReadableStream({
    async pull(ctl) {
      while (!queue.length && !done) await new Promise((r) => { wake = r; });
      wake = null;
      if (queue.length) ctl.enqueue(/** @type {Uint8Array} */ (queue.shift()));
      else if (failed) ctl.error(failed);
      else ctl.close();
    },
  });
}

/** @type {any} */
let XzStream = null; // xzwasm's XzReadableStream, once loaded (vendor/: a module without types)
/** @param {ReadableStream<Uint8Array>} stream @returns {Promise<ReadableStream<Uint8Array>>} */
export async function unxz(stream) {
  if (!XzStream) {
    // a UMD bundle: tsc reads its CommonJS branch, while in a browser it sets self.xzwasm
    const mod = /** @type {any} */ (await import("./vendor/xzwasm.min.js"));
    XzStream = (mod.default || /** @type {any} */ (self).xzwasm).XzReadableStream;
  }
  return new XzStream(stream);
}

/** A stream of bytes read whole into one buffer of the size it will have: the corpus is unpacked while Python starts,
 * not after it, and handed to Python's file system without a copy (ownCorpus).
 * @param {ReadableStream<Uint8Array>} stream @param {number} size @param {(n: number) => void} [onBytes]
 * @returns {Promise<Uint8Array<ArrayBuffer>>} */
export async function readAll(stream, size, onBytes) {
  const buf = new Uint8Array(size);
  const reader = stream.getReader();
  let pos = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (pos + value.length > size) throw new Error(T("要籍语料比清单所记的大：请刷新重试"));
    buf.set(value, pos);
    pos += value.length;
    onBytes?.(pos);
  }
  if (pos !== size) throw new Error(T`要籍语料不完整（${pos} / ${size} 字节）：请刷新重试`);
  return buf;
}
