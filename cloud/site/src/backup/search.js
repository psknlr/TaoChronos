// classics.search in D1 (plugins/retrieval/hybrid.py, HybridRetriever over a large corpus), within a Worker's 10 ms.
//
// The query is analysed as in Python (QueryAnalyzer: normalisation, the lexicon's terms and their surfaces, historical
// related terms, variant spellings, a time constraint, the intent), and the passages are found in three steps, the
// work in SQL:
//   1. candidates: in each database, the chunks the full-text index ranks first for any surface (BM25), and the
//      earliest and latest chunks writing each surface (the corpus's own ordering: chunk numbers follow the year);
//   2. the passages of those chunks that write a surface, with what the routes need — how often each query bigram
//      occurs (BM25), whether a sense's cues are there (the sense route), how often a variant spelling is written;
//   3. the routes and their reciprocal-rank fusion, in JavaScript, over those passages; the cards of the k best.
// Of the seven routes, bm25, temporal, variant and sense are computed as the server computes them (over these
// candidates); dense (hashed n-gram vectors), graph (claims extracted from the passages) and citation (lineage) need
// the server: the backup says so in its result ("routes").

import { Lexicon, surfaces as entrySurfaces } from "./lexicon.js";
import { passageCard, passageId } from "./corpus.js";
import { CURATED, TERMS, WORDS } from "./tables.js";
import { ftsForm, ftsPhrase, normalize, parseConstraint, periodOf, pyRound } from "./text.js";

export const ROUTES = ["bm25", "dense", "graph", "temporal", "citation", "variant", "sense"];
export const SERVED_ROUTES = ["bm25", "temporal", "variant", "sense"];
const WEIGHTS = { bm25: 1.0, dense: 0.6, graph: 1.0, temporal: 0.5, citation: 0.5, variant: 0.6, sense: 0.7 };
const RANKED = 24; // chunks the index ranks first, per database
const KEEP = 32; // of those, kept over all databases
const EDGES = 3; // earliest and latest chunks per surface
const SENSE_EDGES = 6; // earliest chunks writing a targeted sense's head term
const ROWS_RELEVANT = 72; // passages a database returns: the densest in the query's bigrams,
const ROWS_EDGE = 16; //      the latest and the earliest writing a surface, and those a sense may select
const MASK_BITS = 30; // surfaces whose presence is reported (a bit each)
const EDGE_SURFACES = 10; // surfaces whose earliest and latest chunks are candidates
const BIGRAMS = 32; // query bigrams counted per passage
const K1 = 1.4;
const B = 0.75;
const HAN = /[㐀-鿿豈-﫿]/u; // index._KEEP

const TERMINOLOGY = new Map(TERMS.map((t) => [t.id, t]));
const REVERSE = (() => {
  // QueryAnalyzer._reverse_variants: the curated characters and the word variants, target → sources
  const out = new Map();
  for (const [src, [to]] of Object.entries(CURATED)) {
    if (!out.has(to)) out.set(to, []);
    out.get(to).push(src);
  }
  for (const [from, to] of WORDS) {
    if (!out.has(to)) out.set(to, []);
    out.get(to).push(from);
  }
  return out;
})();

const lit = (s) => `'${String(s).replaceAll("'", "''")}'`;
const unique = (xs) => [...new Set(xs)];

/** QueryAnalyzer.variant_spellings */
export function variantSpellings(surface) {
  const forms = new Set([surface]);
  for (const [norm, originals] of REVERSE) {
    if (surface.includes(norm)) for (const orig of originals) forms.add(surface.replace(norm, orig));
  }
  forms.delete(surface);
  return [...forms].sort();
}

// ------------------------------------------------------------------ the query
/** QueryAnalyzer.analyze: {text, terms, surfaces, variants, decomposition, groups, related, after, before, intent, quoted}. */
export async function analyze(lex, text, { after = null, before = null } = {}) {
  const norm = normalize(text);
  const [qa, qb] = parseConstraint(norm);
  const q = { text, terms: [], surfaces: {}, variants: {}, decomposition: {}, groups: {}, related: {},
    after: after ?? qa, before: before ?? qb, intent: "general", quoted: [] };
  q.quoted = [...text.matchAll(/[‘'“"「『]([^’'”"」』]{1,12})[’'”"」』]/gu)].map((m) => m[1]);
  if (/最早|起源|源流|出处|首见|以前|之前|早于/u.test(text)) q.intent = "earliest";
  else if (/演变|变化|发展|历史|流变|沿革|转变/u.test(text)) q.intent = "evolution";
  else if (/矛盾|争议|分歧|不同观点|相反/u.test(text)) q.intent = "contradiction";
  await lex.loadText(norm + q.quoted.map(normalize).join(""));
  const cpLen = [...norm].length;
  const mentions = lex.match(norm).filter((m) => !m.weak || cpLen <= 4);
  for (const quoted of q.quoted) {
    const inner = lex.match(normalize(quoted));
    if (inner.length) {
      q.decomposition[quoted] = inner.map((m) => m.entry.id);
      mentions.push(...inner);
    }
  }
  for (const m of mentions) {
    if (m.entry.cat === "condition" && m.entry.kind === "season") continue;
    if (!q.terms.includes(m.entry.id)) q.terms.push(m.entry.id);
  }
  // the components and related terms of these entries may live in other buckets
  const wanted = [];
  for (const id of q.terms) {
    const e = lex.entry(id);
    if (e) wanted.push(...(e.components || []), ...(e.related || []), ...(e.broader || []));
  }
  await lex.loadIds(wanted);
  for (const id of [...q.terms]) {
    const entry = lex.entry(id);
    if (!entry) continue;
    const forms = [entry.term, ...(entry.aliases || []), ...Object.keys(entry.synonyms || {})];
    const comps = [];
    for (const comp of entry.components || []) {
      const ce = lex.resolve(comp);
      if (ce) {
        (q.decomposition[entry.term] ||= []).push(ce.id);
        comps.push(ce.term);
      }
    }
    if (comps.length) q.groups[id] = [comps];
    const related = [...(entry.related || []), ...(entry.broader || [])];
    const hist = TERMINOLOGY.get(entry.term);
    if (hist) for (const r of hist.related) if (!related.includes(r)) related.push(r);
    if (related.length) {
      q.related[id] = related;
      forms.push(...related);
    }
    q.surfaces[id] = unique(forms.filter(Boolean));
  }
  for (const s of allSurfaces(q)) {
    const spellings = variantSpellings(s);
    if (spellings.length) q.variants[s] = spellings;
  }
  return q;
}

export function allSurfaces(q) {
  const out = [];
  for (const forms of Object.values(q.surfaces)) for (const f of forms) if (!out.includes(f)) out.push(f);
  for (const s of q.quoted) if (!out.includes(s)) out.push(s);
  return out;
}

const groupsOf = (q) => Object.values(q.groups).flat();

/** HybridRetriever.sense_targets: [head term, targeted sense or null, anchor cues]. */
export function senseTargets(q) {
  const surfaces = new Set(q.terms.map((t) => t.slice(t.indexOf(":") + 1)));
  const out = [...surfaces].sort().filter((s) => TERMINOLOGY.has(s)).map((s) => [s, null, []]);
  for (const term of TERMS) {
    for (const sense of term.senses) {
      for (const surface of surfaces) {
        if ([...surface].length < 2 || surface === term.id || !sense.label.includes(surface)) continue;
        const morphemes = new Set([...surface].filter((c) => !"之病证".includes(c)));
        const anchors = (sense.cues || []).filter((c) => [...c].length >= 2 && [...c].some((ch) => morphemes.has(ch)));
        if (anchors.length) out.push([term.id, sense.id, anchors]);
      }
    }
  }
  return out;
}

/** index.query_tokens: the bigrams of a surface's Han characters (the character itself when it has one). */
export function queryTokens(surface) {
  const chars = [...surface].filter((c) => HAN.test(c));
  if (chars.length === 1) return chars;
  const out = [];
  for (let i = 0; i + 1 < chars.length; i++) out.push(chars[i] + chars[i + 1]);
  return out;
}

// ------------------------------------------------------------------ the search
/**
 * The search as tools/mesh.py's _search returns it: {query: {terms, after, before, intent, decomposition, variants},
 * hits: [passage card + score, routes, matched, note], timeline}.
 */
export async function search(corpus, args) {
  const k = Math.max(1, Math.min(Number.parseInt(args.k ?? 10, 10) || 10, 50));
  const lex = new Lexicon(corpus);
  const q = await analyze(lex, String(args.query ?? ""), { after: numberOrNull(args.after), before: numberOrNull(args.before) });
  const active = (Array.isArray(args.routes) && args.routes.length ? args.routes : ROUTES).filter((r) => ROUTES.includes(r));
  const hits = await find(corpus, q, { k, active, books: Array.isArray(args.books) && args.books.length ? args.books : null });
  const cards = await cardsFor(corpus, hits);
  const out = hits.filter((h) => cards.has(h.key)).map((h) => ({ ...cards.get(h.key), score: h.score,
    routes: Object.keys(h.routes).sort(), matched: h.matched, note: h.note }));
  return {
    query: { terms: q.terms, after: q.after, before: q.before, intent: q.intent, decomposition: q.decomposition, variants: q.variants },
    hits: out,
    timeline: timeline(out),
  };
}

const numberOrNull = (v) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

export function timeline(hits) {
  const periods = {};
  const sorted = [...hits].sort((a, b) => (a.year || 0) - (b.year || 0) || (a.passage_id < b.passage_id ? -1 : a.passage_id > b.passage_id ? 1 : 0));
  for (const h of sorted) (periods[periodOf(h.year) || "?"] ||= []).push(h.passage_id);
  return periods;
}

/** The candidate chunks, the passages among them with what the routes read, the routes, the fusion. */
export async function find(corpus, q, { k = 10, active = ROUTES, books = null } = {}) {
  const surfaces = allSurfaces(q);
  const groups = groupsOf(q);
  let search = unique([...surfaces, ...Object.values(q.variants).flat(), ...groups.flat()]);
  if (!search.length) search = [...(normalize(q.text).match(/[㐀-鿿]{2,4}/gu) || [])].slice(0, 8);
  const targets = senseTargets(q);
  const phrases = unique(search.map((s) => ftsPhrase(normalize(s))).filter(Boolean));
  if (!phrases.length) return [];
  let [lo, hi] = await corpus.bounds(q.after, q.before);
  if (lo > hi) return [];
  let only = null;
  if (books) {
    only = await chunksOf(corpus, books);
    if (!only.length) return [];
  }
  // 1. candidates: the best-ranked chunks, the earliest and latest of each surface, the earliest of a sense's head term
  const edgeSurfaces = unique(search).filter((s) => [...s].length >= 2 || search.length <= 1).map((s) => ftsPhrase(normalize(s))).filter(Boolean);
  const heads = unique(targets.map((t) => t[0])).map((h) => ftsPhrase(normalize(h))).filter(Boolean);
  const spans = await corpus.spans(lo, hi);
  const ranked = [];
  const edges = new Set();
  await Promise.all(spans.map(async ([db, s, e]) => {
    const parts = [`SELECT 'r' AS t, cid, r FROM (SELECT rowid AS cid, rank AS r FROM fts WHERE fts MATCH ?1 AND rowid BETWEEN ?2 AND ?3${only ? " AND rowid IN (SELECT value FROM json_each(?4))" : ""} ORDER BY rank LIMIT ${RANKED})`];
    edgeSurfaces.slice(0, EDGE_SURFACES).forEach((p) => {
      for (const dir of ["", " DESC"]) {
        parts.push(`SELECT 'e' AS t, cid, 0 FROM (SELECT rowid AS cid FROM fts WHERE fts MATCH ${lit(p)} AND rowid BETWEEN ?2 AND ?3${only ? " AND rowid IN (SELECT value FROM json_each(?4))" : ""} ORDER BY rowid${dir} LIMIT ${EDGES})`);
      }
    });
    heads.forEach((p) => parts.push(`SELECT 'e' AS t, cid, 0 FROM (SELECT rowid AS cid FROM fts WHERE fts MATCH ${lit(p)} AND rowid BETWEEN ?2 AND ?3${only ? " AND rowid IN (SELECT value FROM json_each(?4))" : ""} ORDER BY rowid LIMIT ${SENSE_EDGES})`));
    const params = [phrases.join(" OR "), s, e];
    if (only) params.push(JSON.stringify(only.filter((c) => c >= s && c <= e)));
    const rows = await corpus.all(db, parts.join(" UNION ALL "), params);
    for (const r of rows) {
      if (r.t === "r") ranked.push([r.cid, r.r]);
      else edges.add(r.cid);
    }
  }));
  ranked.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const chunkRank = new Map(ranked.map(([cid], i) => [cid, i]));
  const chosen = unique([...ranked.slice(0, KEEP).map((x) => x[0]), ...edges]);
  if (!chosen.length) return [];
  // 2. the passages that write a surface (or a sense's head term), with the routes' measures
  const cands = await passages(corpus, q, chosen, { search, surfaces, groups, targets });
  if (!cands.length) return [];
  // 3. the routes and their fusion
  return fuse(q, cands, { k, active, chunkRank, surfaces, groups, targets });
}

/** The chunks of some books (their maps in database 0). */
async function chunksOf(corpus, books) {
  const rows = await corpus.all(0, "SELECT map FROM books WHERE id IN (SELECT value FROM json_each(?))", [JSON.stringify(books.slice(0, 50))]);
  const out = [];
  for (const r of rows) for (const g of JSON.parse(r.map).C) for (const [, cid] of g) out.push(cid);
  return out.sort((a, b) => a - b);
}

/** Step 2: per database, the passages of the chosen chunks writing any surface, head term or group, with: their seq and
 * id part, the length of their index form, which surfaces they write (a bit each), how often each query bigram occurs,
 * each targeted sense's cues and anti-cues present, and how often a variant spelling occurs in the raw text.  SQL keeps
 * the most relevant (by the density of the query's bigrams) and the latest and earliest, so that what the Worker
 * reads stays small whatever the query. */
async function passages(corpus, q, chosen, { search, surfaces, groups, targets }) {
  const forms = (s) => ftsForm(normalize(s));
  const tokens = unique(surfaces.flatMap((s) => queryTokens(normalize(s))));
  const bigrams = (tokens.length ? tokens : queryTokens(normalize(q.text))).slice(0, BIGRAMS);
  const headForms = unique(targets.map((t) => t[0]));
  const conds = unique([...search.map(forms), ...headForms.map((h) => ftsForm(h))]).filter(Boolean).map((f) => `instr(j.value, ${lit(f)}) > 0`);
  for (const g of groups) conds.push(`(${g.map((c) => `instr(j.value, ${lit(forms(c))}) > 0`).join(" AND ")})`);
  const labels = [...surfaces.map((s) => `(instr(j.value, ${lit(forms(s))}) > 0)`),
    ...groups.map((g) => `(${g.map((c) => `instr(j.value, ${lit(forms(c))}) > 0`).join(" AND ")})`)].slice(0, MASK_BITS);
  const mask = labels.length ? labels.map((e, b) => `${e} * ${2 ** b}`).join(" + ") : "0";
  const count = (f) => `((length(j.value) - length(replace(j.value, ${lit(f)}, ''))) / length(${lit(f)}))`;
  const tfCols = bigrams.map((b) => count([...b].join(" ")));
  // the sense route: per (head, sense): the head written, the anchors written, cues and anti-cues found
  const senseCols = [];
  for (const [head, , anchors] of targets) {
    const term = TERMINOLOGY.get(head);
    const parts = [`(instr(j.value, ${lit(ftsForm(head))}) > 0)`,
      anchors.length ? `(${anchors.map((a) => `instr(j.value, ${lit(ftsForm(a))}) > 0`).join(" OR ")})` : "1"];
    for (const s of term.senses) {
      parts.push(s.cues.length ? s.cues.map((c) => `(instr(j.value, ${lit(ftsForm(c))}) > 0)`).join(" + ") : "0");
      parts.push(s.anti_cues.length ? s.anti_cues.map((c) => `(instr(j.value, ${lit(ftsForm(c))}) > 0)`).join(" + ") : "0");
    }
    senseCols.push(parts.join(" || ',' || "));
  }
  const spellings = unique(Object.values(q.variants).flat()).slice(0, 24);
  const raw = "json_extract(c.body, '$.p[' || j.key || '].t')";
  const variantCol = spellings.length
    ? spellings.map((sp) => `((length(${raw}) - length(replace(${raw}, ${lit(sp)}, ''))) / length(${lit(sp)}))`).join(" + ")
    : "0";
  const tf = tfCols.length ? tfCols.join(" || ',' || ") : "''";
  const density = tfCols.length ? `(${tfCols.join(" + ")}) * 1.0 / (length(j.value) + 40)` : "0";
  const sql = "WITH m AS MATERIALIZED (SELECT c.cid AS cid, CAST(j.key AS INTEGER) AS i, c.book AS book, c.year AS year, " +
    "json_extract(c.body, '$.p[' || j.key || '].q') AS q, json_extract(c.body, '$.p[' || j.key || '].m') AS mid, " +
    `length(j.value) AS dl, ${mask} AS mask, ${tf} AS tf, ` +
    `${senseCols.length ? senseCols.map((c) => `(${c})`).join(" || ';' || ") : "''"} AS sense, ${variantCol} AS variant, ` +
    `${density} AS rel ` +
    "FROM json_each(?1) x JOIN chunks c ON c.cid = x.value, json_each(c.norm) j " +
    `WHERE ${conds.join(" OR ")}) ` +
    "SELECT cid, i, book, year, q, mid, dl, mask, tf, sense, variant FROM (" +
    `SELECT * FROM (SELECT * FROM m ORDER BY rel DESC, cid, i LIMIT ${ROWS_RELEVANT}) UNION ` +
    `SELECT * FROM (SELECT * FROM m WHERE mask > 0 ORDER BY year DESC, cid, i LIMIT ${ROWS_EDGE}) UNION ` +
    `SELECT * FROM (SELECT * FROM m WHERE mask > 0 ORDER BY year, cid, i LIMIT ${ROWS_EDGE}) UNION ` +
    `SELECT * FROM (SELECT * FROM m WHERE sense != '' ORDER BY rel DESC, cid, i LIMIT ${ROWS_EDGE}))`;
  const byDb = new Map();
  for (const cid of chosen) {
    const db = await corpus.dbOf(cid);
    if (db < 0) continue;
    if (!byDb.has(db)) byDb.set(db, []);
    byDb.get(db).push(cid);
  }
  const out = [];
  await Promise.all([...byDb].map(async ([db, cids]) => {
    corpus.queries++;
    const rows = await corpus.db(db).prepare(sql).bind(JSON.stringify(cids)).raw();
    corpus.rows = (corpus.rows || 0) + rows.length;
    for (const [cid, i, book, year, seq, mid, dl, mask, tf, sense, variant] of rows) {
      out.push({ key: `${cid}:${i}`, cid, i, book, year, pid: passageId(book, { q: seq, m: mid }), dl: Math.max(1, dl),
        mask, tf: tf === "" || tf === null ? [] : String(tf).split(",").map(Number), sense: String(sense ?? ""), variant: variant || 0 });
    }
  }));
  for (const c of out) c.bigrams = bigrams;
  return out;
}

const bit = (mask, b) => Math.floor(mask / 2 ** b) % 2 === 1;

/** The routes over the candidates and their reciprocal-rank fusion (HybridRetriever.search). */
export function fuse(q, cands, { k, active, chunkRank, surfaces, groups, targets }) {
  const depth = Math.max(k * 3, 20);
  const ranked = {};
  // bm25 (BM25Index over the candidates)
  if (active.includes("bm25")) {
    const bigrams = cands[0]?.bigrams || [];
    const tokens = surfaces.length ? surfaces.flatMap((s) => queryTokens(normalize(s))) : queryTokens(normalize(q.text));
    const col = new Map(bigrams.map((b, i) => [b, i]));
    // the query's tokens (with their repeats, as BM25Index.score sums them) as columns of the counts
    const idx = [];
    for (const t of tokens) {
      const i = col.get(t);
      if (i !== undefined) idx.push(i);
    }
    const n = cands.length;
    let total = 0;
    const df = new Array(bigrams.length).fill(0);
    for (const c of cands) {
      total += c.dl;
      const tf = c.tf;
      for (let i = 0; i < tf.length; i++) if (tf[i] > 0) df[i]++;
    }
    const avgdl = total / Math.max(1, n);
    const idf = df.map((d) => Math.log(1 + (n - d + 0.5) / (d + 0.5)));
    const scored = [];
    for (const c of cands) {
      let s = 0;
      const norm = K1 * (1 - B + (B * c.dl) / avgdl);
      for (let j = 0; j < idx.length; j++) {
        const tf = c.tf[idx[j]];
        if (tf) s += (idf[idx[j]] * tf * (K1 + 1)) / (tf + norm);
      }
      if (s > 0) {
        c.s = s;
        scored.push(c);
      }
    }
    scored.sort((a, b) => b.s - a.s || cmp(a.pid, b.pid));
    ranked.bm25 = scored.slice(0, depth);
  }
  // temporal: the passages writing a surface, latest first (earliest first for a question of origins)
  if (active.includes("temporal")) {
    const reverse = q.intent !== "earliest";
    const hits = cands.filter((c) => c.mask > 0);
    hits.sort((a, b) => ((a.year || 0) - (b.year || 0)) * (reverse ? -1 : 1) || cmp(a.pid, b.pid));
    ranked.temporal = hits.slice(0, depth);
  }
  // variant: how often the raw text writes a variant spelling of a surface
  if (active.includes("variant")) {
    const hits = cands.filter((c) => c.variant > 0).sort((a, b) => b.variant - a.variant || cmp(a.pid, b.pid));
    ranked.variant = hits.slice(0, depth);
  }
  // sense: the period-bound sense the passage's cues and date select (Terminology.resolve)
  if (active.includes("sense") && targets.length) {
    let mid = null;
    if (q.after !== null || q.before !== null) mid = ((q.after ?? -500) + (q.before ?? 1912)) / 2;
    const scored = [];
    for (const c of cands) {
      if (!c.sense.includes("1,1")) continue; // no target's head (and anchors) written
      const per = c.sense.split(";");
      let best = 0;
      for (let t = 0; t < targets.length; t++) {
        const [head, wanted] = targets[t];
        const parts = (per[t] || "").split(",").map(Number);
        if (!parts[0] || !parts[1]) continue;
        const term = TERMINOLOGY.get(head);
        const res = resolveSense(term, parts.slice(2), c.year);
        if (!res) continue;
        let [sense, p] = res;
        if (wanted !== null) {
          p = sense !== wanted ? res[2][wanted] ?? 0 : p;
          if (p < 0.3) continue;
        }
        const target = term.senses.find((s) => s.id === (wanted || sense));
        let fit = 1;
        if (mid !== null && target?.period && !(target.period[0] <= mid && mid <= target.period[1])) fit = 0.5;
        best = Math.max(best, p * fit);
      }
      if (best) {
        c.best = best;
        scored.push(c);
      }
    }
    scored.sort((a, b) => b.best - a.best || cmp(a.pid, b.pid));
    ranked.sense = scored.slice(0, depth);
  }
  const fused = new Map();
  for (const [route, results] of Object.entries(ranked)) {
    const w = WEIGHTS[route] ?? 1;
    results.forEach((c, rank) => {
      let hit = fused.get(c.key);
      if (!hit) fused.set(c.key, (hit = { key: c.key, c, score: 0, routes: {}, matched: [], note: "" }));
      hit.score += w / (60 + rank + 1);
      hit.routes[route] = rank + 1;
    });
  }
  const labels = [...surfaces, ...groups.map((g) => g.join("+"))].slice(0, MASK_BITS);
  for (const hit of fused.values()) {
    hit.year = hit.c.year;
    hit.matched = labels.filter((_, b) => bit(hit.c.mask, b));
    if (!hit.matched.length && "sense" in hit.routes) {
      // a targeted sense's head term, when the passage writes it
      const per = hit.c.sense.split(";");
      hit.matched = unique(targets.filter((t, i) => t[1] !== null && per[i]?.startsWith("1")).map((t) => t[0]));
      hit.note = hit.note || "concept-level match (sense route)";
    }
    hit.score = pyRound(hit.score * 1000, 4);
  }
  // relevance floor: a hit must write a query surface (or match a targeted sense)
  const all = [...fused.values()];
  const relevant = all.filter((h) => h.matched.length);
  const pool = relevant.length || q.terms.length ? relevant : all;
  let hits = [...pool].sort((a, b) => b.score - a.score || cmp(a.c.pid, b.c.pid)).slice(0, k);
  if (q.intent === "earliest" && ranked.temporal?.length) {
    const earliest = ranked.temporal.slice(0, 3).map((c) => fused.get(c.key)).filter((h) => h && pool.includes(h));
    const keep = hits.filter((h) => !earliest.includes(h)).slice(0, Math.max(0, k - earliest.length));
    hits = [...earliest, ...keep];
  }
  if (q.intent === "earliest") hits.sort((a, b) => (a.year ?? 9999) - (b.year ?? 9999) || b.score - a.score);
  return hits;
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** Terminology.resolve on the cues found (per sense: [hits, anti-hits] …) and the passage's year: [sense, p, probs]. */
function resolveSense(term, counts, year) {
  if (!term?.senses?.length) return null;
  const raw = {};
  term.senses.forEach((s, i) => {
    let fit = 1;
    if (year !== null && year !== undefined && s.period && !(s.period[0] <= year && year <= s.period[1])) {
      const distance = Math.min(Math.abs(year - s.period[0]), Math.abs(year - s.period[1]));
      fit = Math.max(0.15, 1 - distance / 600);
    }
    const hits = counts[2 * i] || 0;
    const anti = counts[2 * i + 1] || 0;
    raw[s.id] = fit * (1 + hits) * 0.35 ** anti;
  });
  const total = Object.values(raw).reduce((a, b) => a + b, 0) || 1;
  const probs = Object.fromEntries(Object.entries(raw).map(([id, v]) => [id, pyRound(v / total, 4)]));
  const best = Object.keys(probs).reduce((a, b) => (probs[b] > probs[a] || (probs[b] === probs[a] && b > a) ? b : a));
  return [best, probs[best], probs];
}

/** The cards of the hits (their passages and books). */
async function cardsFor(corpus, hits) {
  const got = await corpus.fetch(hits.map((h) => [h.c.cid, h.c.i]));
  const cards = await corpus.cards(unique([...got.values()].map((x) => x.book)));
  const out = new Map();
  for (const h of hits) {
    const x = got.get(h.key);
    if (x) out.set(h.key, passageCard(x, cards.get(x.book)));
  }
  return out;
}
