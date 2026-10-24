// The full corpus in D1, as the backup's tools read it (the layout: taochronos.chat.d1).  Database 0 (binding D1_0) has
// the meta, the books, the lexicon and the precomputed results, and every database (D1_0, D1_1, …) a range of chunks
// with its full-text index.  A Worker has 10 ms of CPU a request: the searching and filtering happen in SQL, which costs
// the Worker none, and what comes back is small.  What the corpus says of itself (its statistics, the chunk ranges,
// the first chunk of each year) is read once per isolate and kept.

import { cpLength, cpSlice } from "./results.js";
import { normalize, periodLabel, periodOf, rangeLabel, temporalJson, yearOf } from "./text.js";

const MARKS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const SEQMAP_PART = 30_000; // d1.SEQMAP_PART
const KEEP_MS = 10 * 60 * 1000;
const CARDS = 2000; // book cards kept per isolate

const ISOLATE = { kept: null }; // what this isolate keeps of the corpus: {at, stats, cards: Map, works}

export class CorpusError extends Error {}

export class Corpus {
  /** env: the Worker's bindings (D1_0 …); `cache`: where what is kept per isolate is kept (the start's warm-up over
   * made-up databases keeps its own: warm.js).  `queries` counts the D1 statements of this request. */
  constructor(env, { now = () => Date.now(), cache = ISOLATE } = {}) {
    this.env = env;
    this.now = now;
    this.cache = cache;
    this.queries = 0;
  }

  db(k) {
    const db = this.env[`D1_${k}`];
    if (!db) throw new CorpusError(`database ${k} is not bound`);
    return db;
  }

  async all(k, sql, params = []) {
    this.queries++;
    const { results } = await this.db(k).prepare(sql).bind(...params).all();
    return results || [];
  }

  async first(k, sql, params = []) {
    this.queries++;
    return (await this.db(k).prepare(sql).bind(...params).first()) ?? null;
  }

  /** Several statements in one round trip (one transaction, read-only here). */
  async batch(k, statements) {
    this.queries += statements.length;
    const db = this.db(k);
    const out = await db.batch(statements.map(([sql, params]) => db.prepare(sql).bind(...(params || []))));
    return out.map((r) => r.results || []);
  }

  // -------------------------------------------------------------- what the corpus says of itself
  async stats() {
    const kept = this.cache.kept;
    if (kept && this.now() - kept.at < KEEP_MS) return kept.stats;
    const rows = await this.all(0, "SELECT k, v FROM meta WHERE k IN ('stats', 'complete')");
    const meta = Object.fromEntries(rows.map((r) => [r.k, r.v]));
    if (!meta.stats || !meta.complete) throw new CorpusError("the D1 backup is not complete");
    const stats = JSON.parse(meta.stats);
    stats.complete = meta.complete;
    this.cache.kept = { at: this.now(), stats, cards: kept?.cards || new Map(), works: null, lex: kept?.lex || new Map() };
    return stats;
  }

  /** The database a chunk is in. */
  async dbOf(cid) {
    const { ranges } = await this.stats();
    for (let k = 0; k < ranges.length; k++) if (cid >= ranges[k][0] && cid <= ranges[k][1]) return k;
    return -1;
  }

  /** The chunk range [lo, hi] a time bound allows (after: year ≥ after; before: year < before; either may be null). */
  async bounds(after, before) {
    const st = await this.stats();
    const last = st.chunks;
    if ((after === null || after === undefined) && (before === null || before === undefined)) return [1, last];
    const firstAtLeast = (y) => {
      const ys = st.years;
      let lo = 0;
      let hi = ys.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (ys[mid][0] >= y) hi = mid;
        else lo = mid + 1;
      }
      return lo < ys.length ? ys[lo][1] : (st.null_years_from || last + 1);
    };
    const dated = (st.null_years_from || last + 1) - 1; // chunks without a year are in neither bound
    const lo = after === null || after === undefined ? 1 : firstAtLeast(Number(after));
    const hi = before === null || before === undefined ? dated : Math.min(dated, firstAtLeast(Number(before)) - 1);
    return [lo, hi];
  }

  /** The databases holding chunks in [lo, hi], each with its part of the range. */
  async spans(lo, hi) {
    const { ranges } = await this.stats();
    const out = [];
    ranges.forEach(([a, b], k) => {
      const s = Math.max(a, lo);
      const e = Math.min(b, hi);
      if (s <= e) out.push([k, s, e]);
    });
    return out;
  }

  /** The lexicon's buckets read so far (first character → the parsed bucket, never changed by a reader), kept per
   * isolate with the statistics. */
  async lexicon() {
    await this.stats();
    return this.cache.kept.lex;
  }

  /** The works this corpus holds (a witness of each), kept per isolate. */
  async works() {
    await this.stats();
    const kept = this.cache.kept;
    if (!kept.works) {
      const row = await this.first(0, "SELECT v FROM meta WHERE k = 'works'");
      kept.works = new Set(row ? JSON.parse(row.v) : []);
    }
    return kept.works;
  }

  // -------------------------------------------------------------- books
  /** A book's whole record (books.data), or null. */
  async bookData(id) {
    const row = await this.first(0, "SELECT data FROM books WHERE id = ?", [id]);
    return row ? JSON.parse(row.data) : null;
  }

  /** Book cards (title, dynasty, dating basis …) by id, kept per isolate. */
  async cards(ids) {
    await this.stats();
    const cache = this.cache.kept.cards;
    const want = [...new Set(ids)].filter((id) => !cache.has(id));
    if (want.length) {
      const rows = await this.all(0, "SELECT id, card FROM books WHERE id IN (SELECT value FROM json_each(?))", [JSON.stringify(want)]);
      for (const r of rows) {
        if (cache.size > CARDS) cache.delete(cache.keys().next().value);
        cache.set(r.id, { id: r.id, ...JSON.parse(r.card) });
      }
    }
    const out = new Map();
    for (const id of ids) if (cache.has(id)) out.set(id, cache.get(id));
    return out;
  }

  // -------------------------------------------------------------- passages
  /** A passage by id: {pid, book, card, p, T, L, Y, cid, year} or null (no such passage). */
  async passage(pid) {
    return (await this.around(pid, { neighbours: false }))?.exact ?? null;
  }

  /** StoreCorpus.around: in the book `pid` names (documents.book_of: its longest head, up to a ".", that is a book
   * here), the passage at its place — its seq: the passage's own, or the number the id ends in — and the nearest before
   * and after it: {book, card, exact, at, before, after}, each a passage as `passage` gives it or null, `exact` the
   * passage `pid` is; null where `pid` names no book here.  With `neighbours: false`, `at` and `exact` only. */
  async around(pid, { neighbours = true } = {}) {
    const id = String(pid ?? "");
    const heads = [];
    for (let at = id.lastIndexOf("."); at > 0; at = id.lastIndexOf(".", at - 1)) heads.push(id.slice(0, at));
    if (!heads.length) return null;
    const seq = passageNumber(id);
    const pivot = seq === null ? 0 : Math.floor(Math.min(seq, Number.MAX_SAFE_INTEGER) / SEQMAP_PART);
    const [books, seqmap] = await this.batch(0, [
      ["SELECT id, card, map FROM books WHERE id IN (SELECT value FROM json_each(?))", [JSON.stringify(heads)]],
      ["SELECT book, part, marks, counts FROM seqmap WHERE book IN (SELECT value FROM json_each(?)) AND part = ?",
        [JSON.stringify(heads), pivot]],
    ]);
    const row = heads.map((h) => books.find((b) => b.id === h)).find(Boolean);
    if (!row) return null;
    const book = row.id;
    const card = { id: book, ...JSON.parse(row.card) };
    const out = { book, card, exact: null, at: null, before: null, after: null };
    if (seq === null) return out;
    const map = JSON.parse(row.map);
    const span = card.span ?? card.passages;
    // a book of several temporal groups, or with gaps: which group each seq's passage is in ("-": none), by part — the
    // part of `pid`'s seq read with the book, any other (a neighbour across a part's edge) when it is needed
    const parts = new Map(seqmap.filter((r) => r.book === book).map((r) => [r.part, r]));
    const part = async (k) => {
      if (!parts.has(k)) parts.set(k, await this.first(0, "SELECT marks, counts FROM seqmap WHERE book = ? AND part = ?", [book, k]));
      return parts.get(k);
    };
    const has = async (q) => {
      if (q < 0 || q >= span) return false;
      if (!map.S) return true;
      const ch = (await part(Math.floor(q / SEQMAP_PART)))?.marks[q % SEQMAP_PART];
      return Boolean(ch) && ch !== "-";
    };
    // the first passage numbered q, q + step, q + 2·step … in the book, or null
    const nearest = async (q, step) => {
      if (!map.S) return q >= 0 && q < span ? q : null;
      while (q >= 0 && q < span) {
        const k = Math.floor(q / SEQMAP_PART);
        const marks = (await part(k))?.marks || "";
        for (let i = q - k * SEQMAP_PART; i >= 0 && i < SEQMAP_PART; i += step, q += step) {
          if (q < 0 || q >= span) return null;
          if (marks[i] && marks[i] !== "-") return q;
        }
      }
      return null;
    };
    // where the passage numbered q is: [cid, its index in the chunk] (its group's chunks, by its rank in the group)
    const locate = async (q) => {
      let g = 0;
      let rank = q;
      if (map.S) {
        const k = Math.floor(q / SEQMAP_PART);
        const { marks, counts } = await part(k);
        const at = q - k * SEQMAP_PART;
        const code = marks.charCodeAt(at);
        g = MARKS.indexOf(marks[at]);
        rank = JSON.parse(counts)[g];
        for (let i = 0; i < at; i++) if (marks.charCodeAt(i) === code) rank++;
      }
      const chunks = map.C[g] || [];
      let lo = 0;
      let hi = chunks.length - 1;
      let found = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (chunks[mid][0] <= rank) {
          found = mid;
          lo = mid + 1;
        } else hi = mid - 1;
      }
      return found < 0 ? null : [chunks[found][1], rank - chunks[found][0]];
    };
    const want = {
      at: (await has(seq)) ? seq : null,
      before: neighbours ? await nearest(Math.min(seq, span) - 1, -1) : null,
      after: neighbours ? await nearest(seq + 1, 1) : null,
    };
    const where = {};
    for (const [k, q] of Object.entries(want)) if (q !== null) where[k] = await locate(q);
    const got = await this.fetch(Object.values(where).filter(Boolean));
    for (const [k, w] of Object.entries(where)) {
      const hit = w && got.get(`${w[0]}:${w[1]}`);
      if (hit && hit.book === book && hit.p.q === want[k]) out[k] = { ...hit, card };
    }
    if (out.at && passageId(book, out.at.p) === id) out.exact = out.at;
    if (out.exact) this.cache.kept?.cards.set(book, card);
    return out;
  }

  /** Passages by (cid, index in the chunk), from their databases: Map "cid:i" → {cid, i, book, year, p, T, L, Y}. */
  async fetch(pairs) {
    const byDb = new Map();
    for (const [cid, i] of pairs) {
      const k = await this.dbOf(cid);
      if (k < 0) continue;
      if (!byDb.has(k)) byDb.set(k, []);
      byDb.get(k).push([cid, i]);
    }
    const out = new Map();
    await Promise.all([...byDb].map(async ([k, list]) => {
      const rows = await this.all(k,
        "SELECT c.cid AS cid, CAST(j.value ->> 1 AS INTEGER) AS i, c.book AS book, c.year AS year, " +
        "json_extract(c.body, '$.p[' || (j.value ->> 1) || ']') AS p, json_extract(c.body, '$.T') AS T, " +
        "json_extract(c.body, '$.L') AS L, json_extract(c.body, '$.Y') AS Y " +
        "FROM json_each(?) j JOIN chunks c ON c.cid = j.value ->> 0", [JSON.stringify(list)]);
      for (const r of rows) {
        if (r.p === null) continue;
        out.set(`${r.cid}:${r.i}`, { cid: r.cid, i: r.i, book: r.book, year: r.year, p: JSON.parse(r.p), T: JSON.parse(r.T),
          L: JSON.parse(r.L), Y: JSON.parse(r.Y) });
      }
    }));
    return out;
  }
}

// ------------------------------------------------------------------ a passage as the tools cite it
export const passageId = (book, p) => `${book}.${p.m ? `${p.m}.` : ""}${String(p.q).padStart(5, "0")}`;

/** documents.passage_number: the number a passage id ends in — a store's ids end in the passage's seq — or null; one
 * of more than 18 digits is 10¹⁸, past any book's end. */
export function passageNumber(pid) {
  const m = /[0-9]+$/.exec(String(pid));
  if (!m) return null;
  const digits = m[0].replace(/^0+/, "") || "0";
  return digits.length <= 18 ? Number(digits) : 1e18;
}

/** Locator.label: 卷 · 篇 · 节, or the book's id. */
export function locatorLabel(hit) {
  const loc = hit.L[hit.p.l || 0] || [];
  const parts = loc.filter((x) => x);
  return parts.length ? parts.join(" · ") : hit.book;
}

/** The passage's locator as documents.Locator serialises it. */
export function locatorJson(hit, card) {
  const [volume = null, chapter = null, section = null] = hit.L[hit.p.l || 0] || [];
  return { book_id: hit.book, edition_id: card?.edition ?? null, volume, chapter, section, page: hit.p.g ?? null,
    line: hit.p.n ?? null, region: null, image_uri: hit.p.u ?? null, precision: hit.p.r || "exact" };
}

export const passageYear = (hit, card) => yearOf(hit.T, card?.dating_basis || "composition");

/** tools.common.passage_card: the passage as every tool cites it — its first 120 characters unless full, or, when the
 * first of the `focus` surfaces the text writes (a search hit's matched names) starts at character 100 or later of the
 * normalised text, the 120 from 40 before it, so that a passage found under a drug's other name shows that name. */
export function passageCard(hit, card, { full = false, focus = null } = {}) {
  const year = passageYear(hit, card);
  const text = hit.p.t;
  const out = {
    passage_id: passageId(hit.book, hit.p),
    book_id: hit.book,
    title: card?.title ?? hit.book,
    dynasty: card?.dynasty ?? "",
    year,
    period: periodLabel(periodOf(year) || ""),
    locator: locatorLabel(hit),
    text: full || cpLength(text) <= 120 ? text : excerpt(text, focus),
  };
  if (full) {
    const ex = hit.p.x || {};
    out.variants = (ex.variants || []).map((v, i) => ({ id: v.id || `${out.passage_id}.v${i + 1}`, passage_id: out.passage_id,
      start: v.start, end: v.end, base: v.base, reading: v.reading, witness: v.witness, kind: v.kind || "variant_char",
      witness_type: v.witness_type || "edition", note: v.note || "" }));
    out.collation_status = ex.collation_status || "unverified";
    out.notes = ex.notes || "";
    out.temporal = temporalJson(hit.T);
  }
  return out;
}

/** common._excerpt: 120 characters of a passage longer than that, from its start, or from 40 before the first focus
 * surface it writes (found in the normalised text, which keeps the offsets; code points) when that starts at character
 * 100 or later. */
function excerpt(text, focus) {
  const norm = focus?.length ? normalize(text) : "";
  let pos = -1;
  for (const surface of focus || []) {
    const u = surface ? norm.indexOf(normalize(surface)) : -1;
    pos = u < 0 ? -1 : cpLength(norm.slice(0, u));
    if (pos >= 0) break;
  }
  if (pos < 100) return `${cpSlice(text, 120)}…`;
  const chars = Array.from(text);
  const start = pos - 40;
  return `…${chars.slice(start, start + 120).join("")}${start + 120 < chars.length ? "…" : ""}`;
}

/** The layer tag a passage carries (StoreCorpus: "layer:…" unless 正文). */
export const layerOf = (hit) => (hit.Y || [])[hit.p.y || 0] || "";

export const bookLabel = (card) => rangeLabel(card?.composition);
