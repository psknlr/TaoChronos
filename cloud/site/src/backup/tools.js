// The tools the D1 backup computes itself, each ported from its Python implementation (tools/mesh.py and the
// capabilities it calls) with the same arguments and the same result: what they read from the corpus comes from D1
// (corpus.js), what they compute costs a Worker little.  The tools a Worker cannot compute are served from `results`
// (precomputed.js) or not at all (catalog.js says which).

import { collate as collateTexts } from "./difflib.js";
import { Corpus, CorpusError, layerOf, locatorJson, passageCard, passageId } from "./corpus.js";
import { entryView, Lexicon } from "./lexicon.js";
import * as metrology from "./metrology.js";
import { cpLength, cpSlice } from "./results.js";
import { search } from "./search.js";
import { CANON, CROSSWALK, MODERN_RECORDS, SAFETY, TERMS, UNCERTAIN_MASS } from "./tables.js";
import { ftsForm, ftsPhrase, isHan, normalize, normalizeWithRecords, rangeLabel } from "./text.js";

export class ToolError extends Error {
  /** kind: the Python exception the server would name (KeyError, ValueError, PermissionError …). */
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

const keyError = (key) => new ToolError("KeyError", `'${key}'`);
const need = (a, ...keys) => {
  for (const k of keys) if (a[k] === undefined || a[k] === null) throw new ToolError("KeyError", `'${k}'`);
};

async function passageOrThrow(corpus, pid) {
  const hit = await corpus.passage(pid);
  if (!hit) throw keyError(pid);
  return hit;
}

// ------------------------------------------------------------------ retrieval
export async function getPassage(corpus, a) {
  need(a, "passage_id");
  const hit = await passageOrThrow(corpus, a.passage_id);
  return passageCard(hit, hit.card, { full: true });
}

export async function listBooks(corpus, a) {
  const query = String(a.query ?? "").trim();
  const dynasty = String(a.dynasty ?? "").trim();
  const category = String(a.category ?? "").trim();
  // the filters in SQL (a substring of the title, id, aliases or authors; of the dynasty; of the category)
  const where = ["json_extract(card, '$.passages') > 0"];
  const params = [];
  if (query) {
    params.push(query);
    const n = params.length;
    where.push(`(instr(json_extract(card, '$.title'), ?${n}) > 0 OR instr(id, ?${n}) > 0 OR ` +
      `EXISTS (SELECT 1 FROM json_each(card, '$.aliases') WHERE instr(value, ?${n}) > 0) OR ` +
      `EXISTS (SELECT 1 FROM json_each(card, '$.authors') WHERE instr(value, ?${n}) > 0))`);
  }
  if (dynasty) {
    params.push(dynasty);
    where.push(`instr(json_extract(card, '$.dynasty'), ?${params.length}) > 0`);
  }
  if (category) {
    params.push(category);
    where.push(`instr(json_extract(card, '$.category'), ?${params.length}) > 0`);
  }
  const rows = await corpus.all(0, "SELECT id, json_extract(card, '$.title') AS title, json_extract(card, '$.authors') AS authors, " +
    "json_extract(card, '$.dynasty') AS dynasty, json_extract(card, '$.composition') AS composition, " +
    "json_extract(card, '$.category') AS category, json_extract(card, '$.attribution') AS attribution, " +
    `json_extract(card, '$.passages') AS passages FROM books WHERE ${where.join(" AND ")}`, params);
  const out = rows.map((r) => ({ book_id: r.id, title: r.title, authors: JSON.parse(r.authors || "[]").slice(0, 3), dynasty: r.dynasty,
    composition: r.composition ? rangeLabel(JSON.parse(r.composition)) : null, category: r.category, attribution: r.attribution,
    passages: r.passages }));
  out.sort((x, y) => cmp(x.composition || "", y.composition || "") || cmp(x.book_id, y.book_id));
  return a.limit ? out.slice(0, Number(a.limit)) : out;
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export async function canon(corpus, a) {
  const works = CANON.works;
  const here = await corpus.works();
  const query = String(a.query ?? "");
  const dynasty = String(a.dynasty ?? "");
  const category = String(a.category ?? "");
  const held = a.held === undefined || a.held === null ? null : Boolean(a.held);
  const limit = Number.parseInt(a.limit ?? 60, 10);
  const out = [];
  for (const w of works) {
    if (query && ![w.title, w.work, ...(w.authors || [])].some((x) => String(x ?? "None").includes(query))) continue;
    if ((dynasty && !String(w.dynasty ?? "").includes(dynasty)) || (category && !String(w.category ?? "").includes(category))) continue;
    const inCorpus = here.has(w.work);
    if (held !== null && inCorpus !== held) continue;
    out.push({ rank: w.rank, title: w.title, authors: w.authors, dynasty: w.dynasty, composition: w.composition, category: w.category,
      cited_by: w.cited_by, witnesses: w.witnesses, siku: w.siku, in_this_corpus: inCorpus });
  }
  return { listed: works.length, held_here: works.filter((w) => here.has(w.work)).length, matched: out.length, method: CANON.method,
    works: limit ? out.slice(0, limit) : out };
}

// ------------------------------------------------------------------ knowledge
const TERMINOLOGY = new Map(TERMS.map((t) => [t.id, t]));

export async function kgTerm(corpus, a) {
  need(a, "surface");
  const surface = String(a.surface);
  const lex = new Lexicon(corpus);
  await lex.loadIds([surface]);
  let entries = lex.lookup(surface).map((x) => x.entry);
  if (!entries.length) {
    const e = lex.entry(surface);
    if (e) entries = [e];
  }
  const out = { lexicon: entries.map(entryView) };
  const hist = TERMINOLOGY.get(surface.slice(surface.indexOf(":") + 1));
  if (hist) {
    out.senses = hist.senses.map((s) => ({ sense_id: s.id, label: s.label, category: s.category,
      period: s.period ? rangeLabel(s.period) : null, scope: s.scope ?? null, candidates: s.candidates || [] }));
    out.notes = hist.notes;
  }
  return out;
}

// ------------------------------------------------------------------ philology
export function normalizeTool(corpus, a) {
  need(a, "text");
  const { normalized, normalizations } = normalizeWithRecords(String(a.text));
  return { normalized, normalizations };
}

const BASE_BY_STATUS = { unverified: 0.7, collated: 0.86, expert_verified: 0.97 };

/** PhilologyService.assess: normalisations, contested spans (from the passage's variant readings), confidence. */
export async function assessPassage(corpus, a) {
  need(a, "passage_id");
  const hit = await passageOrThrow(corpus, a.passage_id);
  const ex = hit.p.x || {};
  const { normalized, normalizations } = normalizeWithRecords(hit.p.t);
  const quality = hit.card?.quality ?? 0.5;
  const status = ex.collation_status || "unverified";
  const contested = contestedSpans(hit.p.t, ex.variants || [], status);
  const notes = [];
  const ocr = ex.ocr_confidence ?? null;
  if (ocr === null) notes.push("manual transcription (no OCR layer)");
  if (status === "unverified") notes.push("not collated against a specific edition");
  if (ex.abridged) notes.push("abridged excerpt (…)");
  for (const c of contested) {
    notes.push(`contested span “${c.base}”: ${c.options.map((o) => `${o.reading} ${o.probability.toFixed(2)}`).join(" · ")} · uncertain ${c.uncertain.toFixed(2)}`);
  }
  let confidence = (BASE_BY_STATUS[status] ?? 0.7) * (ocr ?? 1) * (0.85 + 0.15 * quality);
  confidence -= Math.min(0.4, 0.15 * contested.length);
  confidence -= ex.abridged ? 0.05 : 0;
  return { passage_id: passageId(hit.book, hit.p), normalized_text: normalized, normalizations, contested, ocr_confidence: ocr,
    collation_status: status, edition_quality: quality, philological_confidence: round4(Math.max(0.05, Math.min(1, confidence))),
    notes };
}

const round4 = (x) => Math.round(x * 10000) / 10000;

/** PhilologyService._contested_spans, without the formula-coherence reading (this store carries no variant readings). */
function contestedSpans(text, variants, status) {
  if (!variants.length) return [];
  const cps = Array.from(text);
  const groups = [];
  for (const v of [...variants].sort((x, y) => x.start - y.start || y.end - x.end)) {
    if (groups.length && v.start < Math.max(...groups.at(-1).map((x) => x.end))) groups.at(-1).push(v);
    else groups.push([v]);
  }
  const uncertain = UNCERTAIN_MASS[status] ?? 0.08;
  return groups.map((group) => {
    const start = Math.min(...group.map((v) => v.start));
    const end = Math.max(...group.map((v) => v.end));
    const base = cps.slice(start, end).join("");
    const cands = [[base, "base text of the edition", "base", 1.0, ""]];
    for (const v of group) {
      const b = Array.from(base);
      cands.push([b.slice(0, v.start - start).join("") + v.reading + b.slice(v.end - start).join(""), v.witness, v.kind || "variant_char",
        { base_edition: 1.0, edition: 0.8, commentator: 0.45, conjecture: 0.3 }[v.witness_type || "edition"] ?? 0.5, v.note || ""]);
    }
    const total = cands.reduce((x, c) => x + c[3], 0) || 1;
    return { start, end, base, options: cands.map(([reading, witness, kind, w, note]) => ({ reading, probability: round4((1 - uncertain) * w / total),
      witness, kind, note })), uncertain, rationale: "" };
  });
}

export async function collate(corpus, a) {
  need(a, "passage_a", "passage_b");
  const [pa, pb] = await Promise.all([passageOrThrow(corpus, a.passage_a), passageOrThrow(corpus, a.passage_b)]);
  return { a: passageId(pa.book, pa.p), b: passageId(pb.book, pb.p), operations: collateTexts(pa.p.t, pb.p.t) };
}

/** verification.provenance.provenance_chain, outside a research session: a passage down to its page and image. */
export async function inspectPage(corpus, a) {
  need(a, "object_id");
  const hit = await corpus.passage(String(a.object_id));
  if (!hit) return [];
  const card = hit.card;
  const loc = locatorJson(hit, card);
  const book = await corpus.bookData(hit.book);
  const edition = (book?.editions || []).find((e) => e.id === loc.edition_id) || (book?.editions || [])[0] || null;
  const chain = [
    { level: "Passage", id: passageId(hit.book, hit.p), label: hit.p.t, available: true },
    { level: "Book", id: hit.book, label: card?.title ?? hit.book, available: Boolean(card) },
    { level: "Edition", id: loc.edition_id, label: edition ? edition.name : null, available: Boolean(edition) },
  ];
  for (const [level, value] of [["Volume", loc.volume], ["Chapter", loc.chapter], ["Section", loc.section], ["Page", loc.page],
    ["Line", loc.line === null ? null : String(loc.line)], ["Region", null], ["Image", loc.image_uri]]) {
    chain.push({ level, id: value ?? null, label: value ?? null, available: value !== null && value !== undefined });
  }
  return chain;
}

// ------------------------------------------------------------------ validation
const HAN_RUN = /[㐀-䶿一-鿿豈-﫿\u{20000}-\u{3134f}]{2,}/gu; // provenance.HAN_RUN
const QUOTE_CANDIDATES = 500;
const isAlnum = (ch) => /[\p{L}\p{N}]/u.test(ch); // str.isalnum
const NOT_ALNUM = /[^\p{L}\p{N}]/gu;
const ASCII_MARK = /[\u0000-/:-@[-`{-\u007f]/u; // what the index form writes as BREAK

/** provenance._bare: the characters of a text without punctuation and spacing, with each one's offset. */
function bare(text) {
  const chars = [];
  const offsets = [];
  let i = 0;
  for (const ch of text) {
    if (isAlnum(ch)) {
      chars.push(ch);
      offsets.push(i);
    }
    i++;
  }
  return [chars.join(""), offsets];
}

/** find_quote's three tests on one passage: the quote verbatim, the normalised quote in the normalised text, the
 * quote's characters (punctuation and spacing aside) in the text's — {start, end} in code points, or null. */
function locate(text, quote, nq, bq) {
  let idx = cpIndex(text, quote);
  if (idx >= 0) return { start: idx, end: idx + cpLength(quote) };
  const nt = normalize(text);
  idx = cpIndex(nt, nq);
  if (idx >= 0) return { start: idx, end: idx + cpLength(quote) };
  if (cpLength(bq) < 4) return null;
  const flat = nt.replace(NOT_ALNUM, "");
  const at = flat.indexOf(bq);
  if (at < 0 || cpLength(flat) !== cpLength(text.replace(NOT_ALNUM, ""))) return null;
  const offsets = bare(nt)[1];
  const k = cpLength(flat.slice(0, at));
  return { start: offsets[k], end: offsets[k + cpLength(bq) - 1] + 1 };
}

/** validation.verify_quote (provenance.find_quote): where a quote is, verbatim, after normalisation, or ignoring
 * punctuation and spacing — never with a character changed or missing.  [{passage_id, start, end}]
 * Over the corpus the first two tests run in D1, on the candidates where the index finds them (on the raw text, and
 * on the passage's index form token for token): the Worker reads the text only of those the third test decides. */
export async function verifyQuote(corpus, a) {
  need(a, "quote");
  const quote = String(a.quote);
  const nq = normalize(quote);
  const bq = bare(nq)[0];
  if (a.passage_id) {
    const hit = await corpus.passage(a.passage_id);
    if (hit) {
      const at = locate(hit.p.t, quote, nq, bq);
      return at ? [{ passage_id: passageId(hit.book, hit.p), ...at }] : [];
    }
  }
  // the second test in SQL needs the quote's index form to stand for the normalised quote exactly: no ASCII marks
  const test = { quote, form: ` ${ftsForm(nq)} `, mode: ASCII_MARK.test(nq) ? 2 : cpLength(bq) >= 4 ? 1 : 0 };
  let rows = await quoteRows(corpus, quote, nq, test);
  if (!rows.length) {
    // provenance._large_candidates, failing the rest: the passages the index ranks first for the quote's 3-grams
    const chars = [...quote].filter(isAlnum);
    if (chars.length < 4) return [];
    const grams = [...new Set(chars.slice(0, -2).map((_, i) => chars.slice(i, i + 3).join("")))].slice(0, 40);
    const phrases = [...new Set(grams.map((g) => ftsPhrase(normalize(g))).filter(Boolean))];
    if (!phrases.length) return [];
    rows = await rankedRows(corpus, phrases, QUOTE_CANDIDATES / 2, test);
  }
  const qlen = cpLength(quote);
  const out = [];
  for (const r of rows) {
    const pid = r.pid ?? passageId(r.book, { q: r.q, m: r.m });
    if (r.v > 0) out.push({ passage_id: pid, start: r.v - 1, end: r.v - 1 + qlen });
    else if (r.w > 0 && test.mode !== 2) out.push({ passage_id: pid, start: r.k, end: r.k + qlen });
    else if (typeof r.t === "string") {
      const at = locate(r.t, quote, nq, bq);
      if (at) out.push({ passage_id: pid, ...at });
    }
  }
  return out;
}

/** str.find, in code points. */
function cpIndex(text, sub) {
  const i = text.indexOf(sub);
  if (i < 0) return -1;
  return cpLength(text.slice(0, i));
}

/** For the candidates p(n, cid, i[, s]): the passage's book and seq, and find_quote's first tests in SQL — v: where the
 * raw text has the quote (instr, from 1); w: where the index form has the normalised quote's, token for token, and
 * k: the tokens (characters) before it; t: the raw text when the Worker must decide (mode 1: the third test, when
 * neither found the quote; mode 2: the second test too). */
const tests = (s = "") => `SELECT ${s}n, cid, i, book, year, q, m, v, w, ` +
  "CASE WHEN w > 0 THEN w - length(replace(substr(pad, 1, w), ' ', '')) - 1 END AS k, " +
  "CASE WHEN v = 0 AND (?9 = 2 OR (?9 = 1 AND w = 0)) THEN t END AS t " +
  `FROM (SELECT ${s}n, cid, i, book, year, q, m, t, pad, instr(t, ?7) AS v, instr(pad, ?8) AS w FROM ` +
  `(SELECT ${s ? "p.s AS s, " : ""}p.n AS n, p.cid AS cid, p.i AS i, c.book AS book, c.year AS year, ` +
  "json_extract(c.body, '$.p[' || p.i || '].q') AS q, json_extract(c.body, '$.p[' || p.i || '].m') AS m, " +
  "json_extract(c.body, '$.p[' || p.i || '].t') AS t, ' ' || json_extract(c.norm, '$[' || p.i || ']') || ' ' AS pad " +
  "FROM p JOIN chunks c ON c.cid = p.cid))";

/** provenance._large_candidates in D1, tested: the passages that write the quote's first 24 characters as they stand
 * (白文), and those that write each of its runs of characters however punctuated — per database, in each chunk the
 * index matches (the earliest first), every occurrence of the needle's form in turn (a recursive query) and the
 * passage it falls in, by the passages' separators before it: a row read per chunk and per occurrence. */
async function quoteRows(corpus, quote, nq, test) {
  const head = ftsPhrase(normalize(cpSlice(quote, 24)));
  const runs = [...new Set(nq.match(HAN_RUN) || [])].sort((x, y) => cpLength(y) - cpLength(x)).slice(0, 8).map((r) => cpSlice(r, 24));
  const needles = [];
  if (head) needles.push([head, ftsForm(normalize(cpSlice(quote, 24))).split(" ").filter((t) => [...t].every((c) => isHan(c))).join(" ")]);
  if (runs.length > 1) needles.push([runs.map((r) => ftsPhrase(r)).join(" AND "), ftsForm(runs[0])]);
  if (!needles.length) return [];
  const st = await corpus.stats();
  const spans = await corpus.spans(1, st.chunks);
  const ctes = [];
  const parts = [];
  needles.forEach((_, j) => {
    const [m, f] = [`?${3 + 2 * j}`, `?${4 + 2 * j}`];
    const at = `o.pos + instr(substr(c.norm, o.pos + 1), ${f})`;
    ctes.push(`f${j}(cid) AS (SELECT rowid FROM fts WHERE fts MATCH ${m} AND rowid BETWEEN ?1 AND ?2 ORDER BY rowid LIMIT ${QUOTE_CANDIDATES})`,
      `o${j}(cid, pos, i) AS (SELECT cid, 0, -1 FROM f${j} UNION ALL SELECT o.cid, ${at}, ` +
      `(length(substr(c.norm, 1, ${at})) - length(replace(substr(c.norm, 1, ${at}), '","', ''))) / 3 ` +
      `FROM o${j} o JOIN chunks c ON c.cid = o.cid WHERE instr(substr(c.norm, o.pos + 1), ${f}) > 0)`);
    parts.push(`SELECT * FROM (SELECT DISTINCT ${j} AS n, cid, i FROM o${j} WHERE i >= 0 ORDER BY cid, i LIMIT ${QUOTE_CANDIDATES})`);
  });
  const sql = `WITH RECURSIVE ${ctes.join(", ")}, p(n, cid, i) AS (${parts.join(" UNION ALL ")}) ${tests()}`;
  const rows = [];
  await Promise.all(spans.map(async ([db, lo, hi]) => {
    const params = [lo, hi, null, null, null, null, test.quote, test.form, test.mode];
    needles.forEach(([m, f], j) => { params[2 + 2 * j] = m; params[3 + 2 * j] = f; });
    rows.push(...(await corpus.all(db, sql, params)));
  }));
  // per needle, the first QUOTE_CANDIDATES passages in (year, id) order, as the store's contains lists them; each
  // passage once, in that order
  for (const r of rows) r.pid = passageId(r.book, { q: r.q, m: r.m });
  rows.sort((x, y) => x.n - y.n || (x.year ?? 9999) - (y.year ?? 9999) || (x.pid < y.pid ? -1 : x.pid > y.pid ? 1 : 0));
  const seen = new Set();
  const counts = [0, 0];
  return rows.filter((r) => {
    if (counts[r.n]++ >= QUOTE_CANDIDATES || seen.has(r.pid)) return false;
    seen.add(r.pid);
    return true;
  });
}

/** The passages holding most of the phrases, in the chunks the index ranks first for any of them, tested. */
async function rankedRows(corpus, phrases, limit, test) {
  const st = await corpus.stats();
  const spans = await corpus.spans(1, st.chunks);
  const score = phrases.map((p) => `(instr(j.value, '${p.slice(1, -1).replaceAll("'", "''")}') > 0)`).join(" + ");
  const sql = `WITH p(s, n, cid, i) AS (SELECT ${score}, 0, c.cid, CAST(j.key AS INTEGER) FROM ` +
    "(SELECT rowid AS cid FROM fts WHERE fts MATCH ?3 AND rowid BETWEEN ?1 AND ?2 ORDER BY rank LIMIT 8) f " +
    `JOIN chunks c ON c.cid = f.cid, json_each(c.norm) j WHERE ${score} > 0 ORDER BY 1 DESC, c.cid, j.key LIMIT ?4) ${tests("s, ")}`;
  const rows = [];
  await Promise.all(spans.map(async ([db, lo, hi]) => {
    rows.push(...(await corpus.all(db, sql, [lo, hi, phrases.join(" OR "), limit, null, null, test.quote, test.form, test.mode])));
  }));
  rows.sort((x, y) => y.s - x.s || x.cid - y.cid || x.i - y.i);
  return rows.slice(0, limit);
}

// ------------------------------------------------------------------ study, computed here
export function metrologyTool(corpus, a) {
  need(a, "dose");
  const year = a.year === undefined ? null : a.year;
  return { dose: a.dose, year, parsed: metrology.parse(a.dose), reading: metrology.convert(a.dose, year), notice: metrology.notice };
}

// ------------------------------------------------------------------ modern
/** ModernEvidence.safety: the materials of the safety table a text names (warnings only). */
export function safety(corpus, a) {
  need(a, "text");
  const text = String(a.text);
  const out = [];
  for (const [name, row] of Object.entries(SAFETY)) {
    const hit = [name, ...(row.aliases || [])].find((f) => f && text.includes(f));
    if (hit) out.push({ material: name, found: hit, risk: row.risk ?? null, ...(row.note ? { note: row.note } : {}) });
  }
  return out;
}

/** literature.modern_evidence: the curated records (corpus/modern/evidence.yaml) for a concept or a term. */
export function modernEvidence(corpus, a) {
  return MODERN_RECORDS.filter((r) => (!a.concept_id || r.concept_id === a.concept_id) && (!a.term || (r.related_terms || []).includes(a.term)));
}

export { search };
export { Corpus, CorpusError, CROSSWALK, layerOf };
