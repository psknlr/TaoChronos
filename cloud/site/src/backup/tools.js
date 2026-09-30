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

/** validation.verify_quote (provenance.find_quote): where a quote is, verbatim, after normalisation, or ignoring
 * punctuation and spacing — never with a character changed or missing.  [{passage_id, start, end}] */
export async function verifyQuote(corpus, a) {
  need(a, "quote");
  const quote = String(a.quote);
  const nq = normalize(quote);
  const bq = bare(nq)[0];
  let targets;
  if (a.passage_id && (await corpus.passage(a.passage_id))) {
    const hit = await corpus.passage(a.passage_id);
    targets = [hit];
  } else {
    targets = await quoteCandidates(corpus, quote, nq);
  }
  const out = [];
  const qlen = cpLength(quote);
  for (const hit of targets) {
    const text = hit.p.t;
    const pid = passageId(hit.book, hit.p);
    let idx = cpIndex(text, quote);
    if (idx >= 0) {
      out.push({ passage_id: pid, start: idx, end: idx + qlen });
      continue;
    }
    const nt = normalize(text);
    idx = cpIndex(nt, nq);
    if (idx >= 0) {
      out.push({ passage_id: pid, start: idx, end: idx + qlen });
      continue;
    }
    if (cpLength(bq) >= 4) {
      const [flat, offsets] = bare(nt);
      const at = cpIndex(flat, bq);
      if (at >= 0 && cpLength(flat) === cpLength(bare(text)[0])) {
        out.push({ passage_id: pid, start: offsets[at], end: offsets[at + cpLength(bq) - 1] + 1 });
      }
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

/** provenance._large_candidates in D1: the passages that write the quote's first 24 characters as they stand (白文 and
 * witnesses punctuated as the quote is), and those that write each of its runs of characters; failing both, those
 * the index ranks first for its three-character pieces. */
async function quoteCandidates(corpus, quote, nq) {
  const head = ftsPhrase(normalize(cpSlice(quote, 24)));
  const runs = [...new Set(nq.match(HAN_RUN) || [])].sort((x, y) => cpLength(y) - cpLength(x)).slice(0, 8).map((r) => cpSlice(r, 24));
  const needles = [];
  if (head) needles.push([head, ftsForm(normalize(cpSlice(quote, 24))).split(" ").filter((t) => [...t].every((c) => isHan(c))).join(" ")]);
  if (runs.length > 1) needles.push([runs.map((r) => ftsPhrase(r)).join(" AND "), ftsForm(runs[0])]);
  let found = [];
  for (const [match, form] of needles) found.push(...(await firstInChunks(corpus, match, form, QUOTE_CANDIDATES)));
  if (!found.length) {
    const chars = [...quote].filter(isAlnum);
    if (chars.length < 4) return [];
    const grams = [...new Set(chars.slice(0, -2).map((_, i) => chars.slice(i, i + 3).join("")))].slice(0, 40);
    const phrases = [...new Set(grams.map((g) => ftsPhrase(normalize(g))).filter(Boolean))];
    if (!phrases.length) return [];
    found = await rankedPassages(corpus, phrases, QUOTE_CANDIDATES / 2);
  }
  const seen = new Set();
  const pairs = [];
  for (const x of found) {
    const key = `${x[0]}:${x[1]}`;
    if (!seen.has(key)) {
      seen.add(key);
      pairs.push(x);
    }
  }
  const got = await corpus.fetch(pairs);
  const cards = await corpus.cards([...new Set([...got.values()].map((h) => h.book))]);
  return pairs.map(([cid, i]) => got.get(`${cid}:${i}`)).filter(Boolean).map((h) => ({ ...h, card: cards.get(h.book) }));
}

/** [cid, i]: in each chunk matching `match` (in the corpus's order, the earliest first), the passage where `form`
 * first occurs — found by counting the passages' separators before it, a row read per chunk. */
async function firstInChunks(corpus, match, form, limit) {
  const st = await corpus.stats();
  const spans = await corpus.spans(1, st.chunks);
  const out = [];
  await Promise.all(spans.map(async ([db, lo, hi]) => {
    const rows = await corpus.all(db, "SELECT cid, (length(pre) - length(replace(pre, '\",\"', ''))) / 3 AS i FROM " +
      "(SELECT c.cid AS cid, substr(c.norm, 1, instr(c.norm, ?4)) AS pre FROM " +
      "(SELECT rowid AS cid FROM fts WHERE fts MATCH ?1 AND rowid BETWEEN ?2 AND ?3 ORDER BY rowid LIMIT ?5) f " +
      "JOIN chunks c ON c.cid = f.cid WHERE instr(c.norm, ?4) > 0)", [match, lo, hi, form, limit]);
    for (const r of rows) out.push([r.cid, r.i]);
  }));
  out.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  return out.slice(0, limit);
}

/** [cid, i] of the passages holding most of the phrases, in the chunks the index ranks first for any of them. */
async function rankedPassages(corpus, phrases, limit) {
  const st = await corpus.stats();
  const spans = await corpus.spans(1, st.chunks);
  const forms = phrases.map((p) => p.slice(1, -1));
  const score = forms.map((f) => `(instr(j.value, '${f.replaceAll("'", "''")}') > 0)`).join(" + ");
  const out = [];
  await Promise.all(spans.map(async ([db, lo, hi]) => {
    const rows = await corpus.all(db, `SELECT c.cid AS cid, CAST(j.key AS INTEGER) AS i, ${score} AS s FROM ` +
      "(SELECT rowid AS cid FROM fts WHERE fts MATCH ?1 AND rowid BETWEEN ?2 AND ?3 ORDER BY rank LIMIT 8) f " +
      `JOIN chunks c ON c.cid = f.cid, json_each(c.norm) j WHERE ${score} > 0 ORDER BY s DESC, c.cid, j.key LIMIT ?4`,
    [phrases.join(" OR "), lo, hi, limit]);
    for (const r of rows) out.push([r.cid, r.i, r.s]);
  }));
  out.sort((x, y) => y[2] - x[2] || x[0] - y[0] || x[1] - y[1]);
  return out.slice(0, limit).map(([cid, i]) => [cid, i]);
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
