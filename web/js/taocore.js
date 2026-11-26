// @ts-check
// TaoCore in the runtime's worker (docs/adr/0036-taocore.md): the WebAssembly module (rust/crates/taocore-wasm, shipped
// as runtime/taocore.wasm) behind the object Python reaches as `import _taocore_wasm` (pyodide.registerJsModule, from
// worker.js), through the facade in src/taochronos/plugins/retrieval/taocore.py.  The module has no imports and a memory
// of its own: each array goes in with one copy (Python's bytes are read where they lie, then copied in), each result
// comes out as a small array.  Anything wrong here — no module, another ABI, a refusal, a trap — is the facade's cue to
// compute in Python, which gives the same numbers.

export const ABI = 1;

/** @typedef {{ getBuffer(type?: string): { data: Uint8Array, release(): void } }} PyBuffer  Python bytes, as Pyodide passes them */
/** @typedef {Uint8Array | PyBuffer} Bytes */
/** @typedef {{ places: number[], scores: number[] }} Ranked  documents' places in the batch, best first, and their scores */

/**
 * @typedef {object} Exports  the module's C ABI (rust/crates/taocore-wasm/src/lib.rs)
 * @property {WebAssembly.Memory} memory
 * @property {() => number} tc_abi
 * @property {(len: number) => number} tc_alloc
 * @property {(ptr: number, len: number) => void} tc_free
 * @property {(ptr: number, len: number, count: number) => number} tc_batch
 * @property {(id: number) => void} tc_batch_free
 * @property {(id: number) => number} tc_total
 * @property {(id: number, ptr: number, len: number, df: number, room: number) => number} tc_count
 * @property {(id: number, idf: number, width: number, avgdl: number, k1: number, b: number, k: number, places: number, scores: number) => number} tc_bm25
 * @property {(id: number, docs: number, count: number, query: number, queryLen: number, dim: number, ngram: number, sizes: number, compensated: number, threshold: number, k: number, places: number, scores: number) => number} tc_dense
 */

/**
 * @typedef {object} Batch  a search's candidates in the module's memory
 * @property {(tokens: Bytes) => { df: number[], total: number }} count  BM25's first step: the query's tokens ("\n"-separated UTF-8) counted
 * @property {(idf: Bytes, avgdl: number, k1: number, b: number, k: number) => Ranked} bm25  BM25's second step, with Python's idf (float64s)
 * @property {(docs: Bytes, query: Bytes, dim: number, ngram: Bytes, compensated: number, threshold: number, k: number) => Ranked} dense  the dense route (docs and ngram as uint32s)
 * @property {() => void} free
 */

/**
 * The module, from its bytes (as the worker keeps them, by sha256, in IndexedDB).
 * @param {BufferSource} bytes
 */
export async function loadTaoCore(bytes) {
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const x = /** @type {Exports} */ (/** @type {unknown} */ (instance.exports));
  if (typeof x.tc_abi !== "function" || x.tc_abi() !== ABI) throw new Error("taocore: the module does not speak this loader's ABI");

  /** @type {Array<[number, number]>} */
  let held = [];
  /** @param {number} len */
  const take = (len) => {
    const p = x.tc_alloc(len);
    if (!p) throw new Error("taocore: the module's memory is full");
    held.push([p, len]);
    return p;
  };
  const giveBack = () => {
    for (const [p, len] of held) x.tc_free(p, len);
    held = [];
  };
  /** Copies bytes into the module's memory: their place and length. @param {Bytes} value @returns {[number, number]} */
  const put = (value) => {
    const view = value instanceof Uint8Array ? { data: value, release() {} } : value.getBuffer("u8");
    try {
      const p = take(view.data.length);
      new Uint8Array(x.memory.buffer, p, view.data.length).set(view.data); // a view made after take: memory may have grown
      return [p, view.data.length];
    } finally {
      view.release();
    }
  };
  /** @param {number} places @param {number} scores @param {number} n @returns {Ranked} */
  const ranked = (places, scores, n) => {
    if (n < 0) throw new Error("taocore: the module refused its input");
    return { places: Array.from(new Uint32Array(x.memory.buffer, places, n)), scores: Array.from(new Float64Array(x.memory.buffer, scores, n)) };
  };
  /** @param {number} k */
  const room = (k) => Math.max(k, 1);

  /** @param {number} id @returns {Batch} */
  const batch = (id) => ({
    count(tokens) {
      try {
        const [p, len] = put(tokens);
        const most = Math.floor(len / 3) + 1; // a token is at least one character of three bytes
        const df = take(8 * most);
        const n = x.tc_count(id, p, len, df, most);
        if (n < 0) throw new Error("taocore: the module refused the query's tokens");
        return { df: Array.from(new Float64Array(x.memory.buffer, df, n)), total: x.tc_total(id) };
      } finally {
        giveBack();
      }
    },
    bm25(idf, avgdl, k1, b, k) {
      try {
        const [p, len] = put(idf);
        const places = take(4 * room(k)), scores = take(8 * room(k));
        return ranked(places, scores, x.tc_bm25(id, p, len / 8, avgdl, k1, b, k, places, scores));
      } finally {
        giveBack();
      }
    },
    dense(docs, query, dim, ngram, compensated, threshold, k) {
      try {
        const [d, dl] = put(docs), [q, ql] = put(query), [g, gl] = put(ngram);
        const places = take(4 * room(k)), scores = take(8 * room(k));
        return ranked(places, scores, x.tc_dense(id, d, dl / 4, q, ql, dim, g, gl / 4, compensated, threshold, k, places, scores));
      } finally {
        giveBack();
      }
    },
    free() {
      x.tc_batch_free(id);
    },
  });

  return {
    abi: ABI,
    /** A search's candidates: their texts ("\u001f"-separated UTF-8) and how many. @param {Bytes} texts @param {number} count */
    batch(texts, count) {
      try {
        const [p, len] = put(texts);
        const id = x.tc_batch(p, len, count);
        if (!id) throw new Error("taocore: the texts are not as many as said, or not UTF-8");
        return batch(id);
      } finally {
        giveBack();
      }
    },
  };
}
