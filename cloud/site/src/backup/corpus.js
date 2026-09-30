// The full corpus in D1, as the backup's tools read it (the layout: taochronos.chat.d1).  Database 0 (binding D1_0) has
// the meta, the books, the lexicon and the precomputed results, and every database (D1_0, D1_1, …) a range of chunks
// with its full-text index.  A Worker has 10 ms of CPU a request: the searching and filtering happen in SQL, which costs
// the Worker none, and what comes back is small.  What the corpus says of itself (its statistics, the chunk ranges,
// the first chunk of each year) is read once per isolate and kept.

import { cpLength, cpSlice } from "./results.js";
import { periodLabel, periodOf, rangeLabel, temporalJson, yearOf } from "./text.js";

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
    const m = /^([^.\s]+)\.(?:(\d+)\.)?(\d{5,})$/.exec(String(pid || ""));
    if (!m) return null;
    const [, bookId, mid, seqText] = m;
    const seq = Number(seqText);
    const part = Math.floor(seq / SEQMAP_PART);
    const [books, seqmap] = await this.batch(0, [
      ["SELECT card, map FROM books WHERE id = ?", [bookId]],
      ["SELECT marks, counts FROM seqmap WHERE book = ? AND part = ?", [bookId, part]],
    ]);
    if (!books.length) return null;
    const card = { id: bookId, ...JSON.parse(books[0].card) };
    if (seq >= (card.span ?? card.passages)) return null;
    const map = JSON.parse(books[0].map);
    const groups = map.C;
    let g = 0;
    let rank = seq;
    if (map.S) {
      // several temporal groups, or gaps: which group the passage is in, and how many of that group come before it
      if (!seqmap.length) return null;
      const marks = seqmap[0].marks;
      const at = seq - part * SEQMAP_PART;
      const ch = marks[at];
      g = ch ? MARKS.indexOf(ch) : -1;
      if (g < 0) return null;
      rank = JSON.parse(seqmap[0].counts)[g];
      const code = ch.charCodeAt(0);
      for (let i = 0; i < at; i++) if (marks.charCodeAt(i) === code) rank++;
    }
    const chunks = groups[g] || [];
    let lo = 0;
    let hi = chunks.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid2 = (lo + hi) >> 1;
      if (chunks[mid2][0] <= rank) {
        found = mid2;
        lo = mid2 + 1;
      } else hi = mid2 - 1;
    }
    if (found < 0) return null;
    const [rank0, cid] = chunks[found];
    const got = await this.fetch([[cid, rank - rank0]]);
    const hit = got.get(`${cid}:${rank - rank0}`);
    if (!hit || hit.p.q !== seq || (hit.p.m || undefined) !== (mid || undefined) || hit.book !== bookId) return null;
    this.cache.kept.cards.set(bookId, card);
    return { ...hit, card };
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

/** tools.common.passage_card: the passage as every tool cites it (the text cut at 120 characters unless full). */
export function passageCard(hit, card, { full = false } = {}) {
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
    text: full || cpLength(text) <= 120 ? text : `${cpSlice(text, 120)}…`,
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

/** The layer tag a passage carries (StoreCorpus: "layer:…" unless 正文). */
export const layerOf = (hit) => (hit.Y || [])[hit.p.y || 0] || "";

export const bookLabel = (card) => rangeLabel(card?.composition);
