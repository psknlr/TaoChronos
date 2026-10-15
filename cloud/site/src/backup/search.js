// classics.search in D1 (plugins/retrieval/hybrid.py, HybridRetriever over a large corpus), within a Worker's 10 ms.
//
// The query is analysed as in Python (QueryAnalyzer: normalisation, the lexicon's terms and their surfaces, historical
// related terms, variant spellings, a time constraint, the intent), and the passages are found in three steps, the
// work in SQL:
//   1. candidates: in each database, the chunks the full-text index ranks first for any surface (BM25); and over the
//      whole corpus, the earliest and latest chunks writing each surface (chunk numbers follow the year, across the
//      databases) — one statement a database, its SELECTs nested five to a compound (D1's limit);
//   2. the passages of those chunks that write a surface, with what the routes need — how often each query bigram
//      occurs (BM25), whether a sense's cues are there (the sense route), how often a variant spelling is written;
//   3. the routes and their reciprocal-rank fusion, in JavaScript, over those passages; the cards of the k best.
// Of the seven routes, bm25, temporal, variant and sense are computed as the server computes them (over these
// candidates); dense (hashed n-gram vectors), graph (claims extracted from the passages) and citation (lineage) need
// the server: the backup says so in its result ("routes").
//
// With the alias layer on (ADR 0023; tables.js ALIAS_PARAMS, the full-corpus profile's), the question is read against
// it as _analyze_aliases reads it — the names asked, those asked as drugs, the longer names they stand in, the stop names
// asked on their own, the one-hop expansions and the query.aliases view (aliases.js) — and the search splits today's
// fusion by tier as _alias_search does: the main queue keeps the asked name's places (retention over its own pool: the
// Worker runs no deeper search of the asked name), the side queue deals the other lexicon forms and the passages found
// under the expansions round-robin over the drugs into at most ⌊num·k/den⌋ reserved places, demoted hits come last, an
// origin question reads each queue by year, and the hits are labelled (via, flags).  The side candidates cost no
// statement of their own: one more part per database in step 1 (the expansions' chunks in the side window), and in
// step 2 the expansions as mask bits after the surfaces and groups, a part that keeps the passages writing an expansion
// and no surface, the gate text (`ctx`) only where a gate reads it (elsewhere a bit says which asked drugs a passage
// writes) and the chunk's dates (`T`) only where a range is read.  The side queue reads no passage that cannot reach
// the first k of its drug.  The candidate sets differ from the server's by design (other limits), so only the query
// block is compared (the parity test).  As the module loads, the alias search runs once over made-up passages (the end
// of this file), so that a first drug question does not pay for compiling it.

import { Lexicon, surfaces as entrySurfaces } from "./lexicon.js";
import { passageCard, passageId } from "./corpus.js";
import { CURATED, EXPRESSIONS, TERMS, WORDS } from "./tables.js";
import { BREAK, effective, escapeRe, ftsForm, ftsPhrase, isHan, normalize, parseConstraint, periodOf, pyRound } from "./text.js";
import { aliasIndex, assemble, cmp as cpCmp, Cp, cpLen, DIRECTIONS, gateForm, KINDS, overlaps, params as aliasParams,
  placeless, unsearched } from "./aliases.js";

export const ROUTES = ["bm25", "dense", "graph", "temporal", "citation", "variant", "sense"];
export const SERVED_ROUTES = ["bm25", "temporal", "variant", "sense", "alias"];
export const ALIAS_MODES = ["auto", "on", "off"]; // aliases: the profile's choice, the layer whenever there is one, never
const WEIGHTS = { bm25: 1.0, dense: 0.6, graph: 1.0, temporal: 0.5, citation: 0.5, variant: 0.6, sense: 0.7 };
const RANKED = 24; // chunks the index ranks first, per database
const KEEP = 32; // of those, kept over all databases
const EDGES = 3; // earliest and latest chunks per surface, over the whole corpus
const SENSE_EDGES = 6; // earliest chunks writing a targeted sense's head term, over the whole corpus
const ROWS_RELEVANT = 72; // passages a database returns: the densest in the query's bigrams,
const ROWS_EDGE = 16; //      the latest and the earliest writing a surface, and those a sense may select
const MASK_BITS = 30; // surfaces whose presence is reported (a bit each)
const EDGE_SURFACES = 10; // surfaces whose earliest and latest chunks are candidates
const BIGRAMS = 32; // query bigrams counted per passage
const SIDE_CHUNKS = 16; // the alias side queue: chunks the index ranks first for the expansions searched, over all
//   databases, shared out among them (at least 3 each; and the EDGES earliest of each, for an origin question),
const SIDE_ROWS = 48; //   and the passages a database returns that write one and no surface (the densest in the
//   expansions), shared out among them (at least 4 each; and for an origin question the 4 earliest of each)
const SIDE_ROWS_EDGE = 4;
const share = (total, n, least) => Math.max(least, Math.ceil(total / Math.max(1, n)));
const K1 = 1.4;
const B = 0.75;
const HAN = /[㐀-鿿豈-﫿]/u; // index._KEEP

// how a question asks a name as a drug (hybrid.py): the thresholds, the drug words, the question words a name nobody
// knows never runs over, what follows a period's name
const COMMON_N = 20;
const COMMON_SH = 0.1;
const COMMON_CUE_SH = 0.5;
const DRUG_WORDS = ["药", "本草", "功效", "功用", "性味", "炮制", "一名", "又名", "别名", "异名", "是什么", "是哪", "方书", "方剂",
  "方中", "处方", "配伍", "用量", "剂量"];
const RUN_STOPS = new Set("的之治论何病是与和及或吗呢么什哪怎功效用主");
const PERIOD_TAIL = /^[代朝]?(?:以前|之前|以后|之后|以来|以降|时期|期间|前|后|初|末|至|到)?/u;
// domain.Periods: the expressions of time in a question, longest first; a one-character dynasty only before a cue
const EXPR_RE = new RegExp(`(${Object.keys(EXPRESSIONS).sort((a, b) => cpLen(b) - cpLen(a)).map(escapeRe).join("|")})`, "gu");
const SINGLE_TAIL = /^(代|朝|以前|之前|以后|之后|以来|以降|至|到|—|~|时期|初|末|医家|文献|人)/u;
// DomainPack.synonym_kind_label: a lexicon form's kind as a side hit's label names it ("" for the others)
const SYNONYM_LABELS = { taboo_rename: "避讳改名", part_name: "药用部位名", processing_variant: "炮制/加工名", abbreviation: "简称",
  variety: "品种/产地名", alias: "异名" };

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
const span = (a, b) => Array.from({ length: Math.max(0, b - a) }, (_, x) => a + x);

/** SELECTs joined by UNION ALL as D1 takes them: at most five terms a compound (its SQLITE_LIMIT_COMPOUND_SELECT),
 * so more are nested, five subqueries of at most five, and so on. */
export function unionAll(parts, fanout = 5, op = " UNION ALL ") {
  if (parts.length <= fanout) return parts.join(op);
  const size = Math.ceil(parts.length / fanout);
  const groups = [];
  for (let i = 0; i < parts.length; i += size) groups.push(`SELECT * FROM (${unionAll(parts.slice(i, i + size), fanout, op)})`);
  return groups.join(op);
}

/** QueryAnalyzer.variant_spellings (str.replace: every occurrence, 人参汤即理中汤 → 人参湯即理中湯) */
export function variantSpellings(surface) {
  const forms = new Set([surface]);
  for (const [norm, originals] of REVERSE) {
    if (surface.includes(norm)) for (const orig of originals) forms.add(surface.split(norm).join(orig));
  }
  forms.delete(surface);
  return [...forms].sort();
}

// ------------------------------------------------------------------ the query
/** QueryAnalyzer.analyze: {text, terms, surfaces, variants, decomposition, groups, related, after, before, intent,
 * quoted}; with `aliases` (the layer's parameters in `cfg`) read against the alias layer too, as _analyze_aliases reads
 * it: {asked: Map name → term id or null, drugs, longer: Map, stops, expansions, aliasView} besides. */
export async function analyze(lex, text, { after = null, before = null, aliases = false, cfg = null, index = null } = {}) {
  const norm = normalize(text);
  const [qa, qb] = parseConstraint(norm);
  const q = { text, terms: [], surfaces: {}, variants: {}, decomposition: {}, groups: {}, related: {},
    after: after ?? qa, before: before ?? qb, intent: "general", quoted: [] };
  q.quoted = [...text.matchAll(/[‘'“"「『]([^’'”"」』]{1,12})[’'”"」』]/gu)].map((m) => m[1]);
  if (/最早|起源|源流|出处|首见|以前|之前|早于/u.test(text)) q.intent = "earliest";
  else if (/演变|变化|发展|历史|流变|沿革|转变/u.test(text)) q.intent = "evolution";
  else if (/矛盾|争议|分歧|不同观点|相反/u.test(text)) q.intent = "contradiction";
  await lex.loadText(norm + q.quoted.map(normalize).join(""));
  const raw = lex.match(norm);
  // the entries matched are filed under their own terms (薯蓣 is herb:山药), their components and related terms may
  // live in other buckets: all loaded in one statement
  const wanted = [];
  for (const m of [...raw, ...q.quoted.flatMap((x) => lex.match(normalize(x)))]) {
    const e = m.entry;
    wanted.push(e.id, ...(e.components || []), ...(e.related || []), ...(e.broader || []));
  }
  await lex.loadIds(wanted);
  if (aliases) return analyzeAliases(lex, index ?? aliasIndex(), q, norm, raw, aliasParams(cfg));
  terms(lex, q, raw.filter((m) => !m.weak || cpLen(norm) <= 4));
  spellings(q);
  return q;
}

const season = (m) => m.entry.cat === "condition" && m.entry.kind === "season";

/** QueryAnalyzer._terms: the terms, their searchable surfaces, components and related terms from the mentions (and the
 * quoted strings' own mentions, which are returned with them). */
function terms(lex, q, mentions) {
  for (const quoted of q.quoted) {
    const inner = lex.match(normalize(quoted));
    if (inner.length) {
      q.decomposition[quoted] = inner.map((m) => m.entry.id);
      mentions.push(...inner);
    }
  }
  for (const m of mentions) {
    if (season(m)) continue;
    if (!q.terms.includes(m.entry.id)) q.terms.push(m.entry.id);
  }
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
  return mentions;
}

function spellings(q) {
  for (const s of allSurfaces(q)) {
    const found = variantSpellings(s);
    if (found.length) q.variants[s] = found;
  }
}

export function allSurfaces(q) {
  const out = [];
  for (const forms of Object.values(q.surfaces)) for (const f of forms) if (!out.includes(f)) out.push(f);
  for (const s of q.quoted) if (!out.includes(s)) out.push(s);
  return out;
}

const groupsOf = (q) => Object.values(q.groups).flat();

// ------------------------------------------------------------------ the question read against the alias layer
const at = (i, s) => `${i}\u0000${s}`;
const startsWithAny = (text, words) => words.some((w) => text.startsWith(w));
const endsWithAny = (text, words) => words.some((w) => text.endsWith(w));
/** hybrid._apart: whether the character beside a name leaves it a word of its own. */
const apart = (c, word) => word || !c || !isHan(c) || RUN_STOPS.has(c);
/** hybrid._runs_over: whether an unknown name's run may take in a character. */
const runsOver = (c) => isHan(c) && !RUN_STOPS.has(c);

/** QueryAnalyzer._analyze_aliases (its four rules, in its order): the names asked and those asked as drugs, the longer
 * names asked drugs stand in, the stop names asked on their own, the expansions and the view.  `norm` and the mentions
 * are code points (lexicon.js and aliases.js count them so). */
function analyzeAliases(lex, index, q, norm, raw0, cfg) {
  const N = [...norm];
  const n = N.length;
  const g = gateForm(norm);
  let spans = index.scan(norm);
  const blocked = new Set();
  const written = [];
  for (const [i, s] of [...spans.map(([i, , s]) => [i, s]), ...raw0.map((m) => [m.start, m.surface])]) {
    const cover = coverOf(index, g, i, s);
    if (cover === null) continue;
    blocked.add(at(i, s));
    const [k, b] = cover;
    const end = k + cpLen(b);
    if (namesDrug(lex, index, b) && !written.some(([a, z]) => a < end && k < z)) written.push([k, end, b]);
  }
  const held = (i, j) => written.some(([a, z]) => a < j && i < z);
  const raw = raw0.filter((m) => !held(m.start, m.end));
  const termAt = new Map(raw.map((m) => [at(m.start, m.surface), m.entry.id]));
  const termOf = (i, s) => termAt.get(at(i, s)) ?? null;
  spans = spans.filter(([i, j, s]) => !blocked.has(at(i, s)) && !held(i, j));
  const strong = spans.filter(([i, , s]) => drugReading(lex, index, s, termOf(i, s)) === "drug").map(([i, j]) => [i, j]);
  for (const m of raw) {
    if (!m.weak && !blocked.has(at(m.start, m.surface)) && drugReading(lex, index, m.surface, m.entry.id) === "drug") {
      strong.push([m.start, m.end]);
    }
  }
  spans = spans.filter(([i, j, s]) => asksDrug(lex, index, N, g, i, j, s, termOf(i, s), strong, cfg));
  const mentions = [];
  for (const m of raw) {
    const over = spans.filter(([i, j]) => i < m.end && m.start < j).map(([i, j]) => j - i);
    if (over.length && (m.weak || m.end - m.start < Math.max(...over))) continue; // 山蓟 over the weak 山
    if (!m.weak || n <= 4) mentions.push(m);
  }
  const drop = (o) => mentions.splice(mentions.indexOf(o), 1);
  const runs = [];
  const longer = new Map();
  if (cfg.unknown_runs && n <= 4) {
    // a weak herb character inside a short name nobody knows is not what was asked: 干葛 is not 葛
    const weak = mentions.filter((m) => m.weak && m.entry.cat === "herb");
    const taken = new Set([...spans, ...written].flatMap(([i, j]) => span(i, j)));
    const known = new Set(mentions.flatMap((o) => span(o.start, o.end)));
    const outside = (lo, hi) => N.slice(0, lo).some(runsOver) || N.slice(hi).some(runsOver);
    for (const m of weak) {
      if (!mentions.includes(m)) continue;
      const others = new Set([...taken, ...mentions.filter((o) => !weak.includes(o)).flatMap((o) => span(o.start, o.end))]);
      let lo = m.start;
      let hi = m.end;
      while (lo > 0 && runsOver(N[lo - 1]) && !others.has(lo - 1)) lo--;
      while (hi < n && runsOver(N[hi]) && !others.has(hi)) hi++;
      if (hi - lo >= 2 && hi - lo <= 4 && !outside(lo, hi) && !span(lo, hi).every((x) => known.has(x))) {
        for (const o of weak.filter((o) => lo <= o.start && o.end <= hi && mentions.includes(o))) drop(o);
        runs.push([lo, N.slice(lo, hi).join("")]);
        for (const x of span(lo, hi)) taken.add(x);
      }
    }
    // a drug's name inside a longer one nobody knows is asked as that longer name (慎火草, not every 慎火)
    const names = mentions.filter((m) => !m.weak && m.entry.cat === "herb").map((m) => [m.start, m.end, m.surface, m.entry.id]);
    for (const [i, j, s] of spans) if (!mentions.some((m) => m.start < j && i < m.end)) names.push([i, j, s, null]);
    const heldAt = new Set([...taken, ...runs.flatMap(([i, s]) => span(i, i + cpLen(s))),
      ...mentions.filter((o) => !o.weak).flatMap((o) => span(o.start, o.end))]);
    for (const [i, j, s, term] of names) {
      let lo = i;
      let hi = j;
      while (lo > 0 && runsOver(N[lo - 1]) && !heldAt.has(lo - 1)) lo--;
      while (hi < n && runsOver(N[hi]) && !heldAt.has(hi)) hi++;
      if (j - i < hi - lo && hi - lo <= 4 && !outside(lo, hi) && asksDrug(lex, index, N, g, i, j, s, term, strong, cfg)) {
        for (const o of mentions.filter((o) => o.weak && lo <= o.start && o.end <= hi)) drop(o);
        longer.set(s, [lo, N.slice(lo, hi).join("")]);
      }
    }
  }
  const own = [...mentions];
  const inner = terms(lex, q, mentions).slice(own.length);
  // the names asked, in the order written (a span a kept mention overlaps is the mention's)
  const found = own.filter((m) => !season(m) && !blocked.has(at(m.start, m.surface))).map((m) => [m.start, m.surface, m.entry.id]);
  for (const [i, j, s] of spans) if (!own.some((m) => m.start < j && i < m.end)) found.push([i, s, null]);
  for (const [i, s] of runs) found.push([i, s, null]);
  for (const [i, , s] of written) found.push([i, s, null]);
  for (const [i, s] of longer.values()) found.push([i, s, null]); // searched as written
  q.asked = new Map();
  const where = new Map();
  for (const [i, s, term] of [...found].sort((a, b) => a[0] - b[0])) {
    if (!q.asked.has(s)) q.asked.set(s, term);
    if (!where.has(s)) where.set(s, i);
  }
  for (const m of inner) if (!season(m) && !q.asked.has(m.surface)) q.asked.set(m.surface, m.entry.id);
  const quoted = q.quoted.map(normalize);
  for (const x of quoted) if (!q.asked.has(x)) q.asked.set(x, null);
  for (const [s, term] of [...q.asked]) if (term === null && !quoted.includes(s)) q.quoted.push(s); // searched as written
  spellings(q);
  q.drugs = [];
  const text = new Cp(norm);
  for (const [s, term] of q.asked) {
    const i = where.has(s) ? where.get(s) : Math.max(0, text.find(s));
    if (asksDrug(lex, index, N, g, i, i + cpLen(s), s, term, strong, cfg)) q.drugs.push(s);
  }
  q.longer = new Map([...longer].filter(([s, [, run]]) => q.drugs.includes(s) && !q.drugs.includes(run)).map(([s, [, run]]) => [s, run]));
  q.stops = stopsOf(index, norm, N, g, found.map(([i, s]) => [i, s]));
  q.expansions = index.expansions(drugsOf(q), lex, cfg);
  q.aliasView = index.view(drugsOf(q), cfg, lex, q.expansions);
  return q;
}

/** QueryAnalyzer._drugs: what the layer's expansion and view read of a parsed question. */
function drugsOf(q) {
  return { asked: q.drugs.map((s) => [s, q.asked.get(s) ?? null]), stops: q.stops.map((s) => [s, q.asked.get(s) ?? null]),
    after: q.after, before: q.before, allSurfaces: () => allSurfaces(q), groups: q.groups };
}

/** QueryAnalyzer._cover: the blocker of `s` the question writes it inside at `i`, [offset, text], or null. */
function coverOf(index, g, i, s) {
  const rec = index.record(s);
  for (const b of rec ? rec.b : []) {
    const text = typeof b === "string" ? b : b[0];
    const k = text.includes(s) && text !== s ? index.covers(g, i, s, text, null) : null;
    if (k !== null) return [k, text];
  }
  return null;
}

/** QueryAnalyzer._names_drug: a name the layer's herb set, a record or a lexicon herb holds. */
function namesDrug(lex, index, s) {
  const rec = index.record(s);
  return index.herbs.has(s) || (rec !== null && !rec.stop && (rec.r.length > 0 || Boolean(rec.ho) || rec.fl !== null)) ||
    lex.lookup(s).some(({ entry }) => entry.cat === "herb");
}

/** QueryAnalyzer._drug_reading: "drug", "context" (only where the question reads as one) or null. */
function drugReading(lex, index, s, term) {
  const entry = term ? lex.entry(term) : null;
  if ((entry && entry.cat !== "herb") || cpLen(s) < 2) return null;
  const rec = index.record(s);
  if (rec === null) return entry || index.herbs.has(s) ? "drug" : null;
  if (rec.stop) return entry ? "context" : null;
  const live = rec.r.filter((r) => r.st !== "candidate");
  if (!live.length && rec.ho === null && rec.fl === null) return entry ? "drug" : "context";
  const cue = rec.ho === null && rec.fl === null && live.every((r) => r.st === "cue");
  return rec.n >= COMMON_N && rec.sh < (cue ? COMMON_CUE_SH : COMMON_SH) ? "context" : "drug";
}

/** QueryAnalyzer._asks_drug: whether the question asks the name at N[i:j] as a drug. */
function asksDrug(lex, index, N, g, i, j, s, term, strong, cfg) {
  const reading = drugReading(lex, index, s, term);
  if (reading !== "context") return reading === "drug";
  const rec = index.record(s);
  const before = N.slice(0, i).join("");
  const after = N.slice(j).join("");
  const free = rec === null || !rec.stop ||
    (apart(i > 0 ? N[i - 1] ?? "" : "", endsWithAny(before, DRUG_WORDS)) && apart(N[j] ?? "", startsWithAny(after, DRUG_WORDS)));
  const rest = before + "|".repeat(Math.max(0, j - i)) + after;
  if (free && (!/[^|]/u.test(gateForm(rest)) || DRUG_WORDS.some((w) => rest.includes(w)))) return true;
  if (free && strong.some(([a, b]) => !(a < j && i < b))) return true;
  return index.drugContext(g, gateForm(s), [i], cuesOf(lex, index, s, term), cfg);
}

/** hybrid._cues: what says a name means a drug where it may not. */
function cuesOf(lex, index, s, term) {
  const rec = index.record(s);
  if (rec && rec.stop) {
    const entry = term ? lex.entry(term) : null;
    return entry ? [...new Set(entrySurfaces(entry).map(normalize))].filter((f) => f !== s).sort(cpCmp) : [];
  }
  return [...new Set((rec ? rec.r : []).filter((r) => r.st !== "candidate").flatMap((r) => r.c))].sort(cpCmp);
}

/** Periods._expression_matches, as [start, end) in code points. */
function expressionSpans(norm) {
  const out = [];
  for (const m of norm.matchAll(EXPR_RE)) {
    const expr = m[1];
    if (cpLen(expr) === 1 && !SINGLE_TAIL.test(norm.slice(m.index + expr.length))) continue;
    const start = cpLen(norm.slice(0, m.index));
    out.push([start, start + cpLen(expr)]);
  }
  return out;
}

/** QueryAnalyzer._stops: the curated stop names the question asks on its own. */
function stopsOf(index, norm, N, g, found) {
  const n = N.length;
  const timeless = [...N]; // the question with its periods (and what follows them) blanked out
  for (const [a, e] of expressionSpans(norm)) {
    const end = e + cpLen(PERIOD_TAIL.exec(N.slice(e).join(""))[0]);
    for (let x = a; x < end; x++) timeless[x] = "|";
  }
  const out = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 2; j <= Math.min(n, i + index.maxLen); j++) {
      const s = N.slice(i, j).join("");
      const rec = index.record(s);
      if (rec === null || !rec.stop || out.includes(s) || coverOf(index, g, i, s) !== null ||
        !found.every(([a, x]) => i <= a && a + cpLen(x) <= j)) continue;
      const before = timeless.slice(0, i).join("");
      const after = timeless.slice(j).join("");
      if (!(apart(i > 0 ? timeless[i - 1] : "", endsWithAny(before, DRUG_WORDS)) &&
        apart(timeless[j] ?? "", startsWithAny(after, DRUG_WORDS)))) continue;
      const rest = before + "|".repeat(j - i) + after;
      if (DRUG_WORDS.some((w) => rest.includes(w)) || [...rest].every((c) => !isHan(c) || RUN_STOPS.has(c))) out.push(s);
    }
  }
  return out;
}

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
 * The search as tools/mesh.py's _search returns it: {query: {terms, after, before, intent, decomposition, variants,
 * aliases?}, hits: [passage card + score, routes, matched, note, via?, flags?], timeline}.
 */
export async function search(corpus, args) {
  // k as the server takes it (int(k)): the side queue's place is read from it, and k ≤ 0 gives no hit; at most 50 here
  const given = Number.parseInt(args.k ?? 10, 10);
  const want = Number.isNaN(given) ? 10 : given;
  const k = Math.max(1, Math.min(want, 50));
  const mode = args.aliases || "auto";
  if (!ALIAS_MODES.includes(mode)) throw new Error(`aliases must be one of ${ALIAS_MODES.join(", ")}, not '${mode}'`);
  const index = aliasIndex();
  const cfg = aliasParams();
  const on = index.enabled && (mode === "on" || (mode === "auto" && Boolean(cfg.enabled)));
  const lex = new Lexicon(corpus);
  const q = await analyze(lex, String(args.query ?? ""), { after: numberOrNull(args.after), before: numberOrNull(args.before),
    aliases: on, cfg, index });
  const routes = Array.isArray(args.routes) ? args.routes : null;
  const active = (routes && routes.length ? routes : ROUTES).filter((r) => ROUTES.includes(r));
  if (on && unsearched(q.expansions, placeless(routes, want, cfg))) q.aliasView = index.view(drugsOf(q), cfg, lex, q.expansions);
  const hits = want < 1 ? [] : await find(corpus, q, { k, active, books: Array.isArray(args.books) && args.books.length ? args.books : null,
    alias: on ? { lex, index, cfg, routes } : null });
  const cards = await cardsFor(corpus, hits);
  const out = hits.filter((h) => cards.has(h.key)).map((h) => ({ ...cards.get(h.key), score: h.score,
    routes: Object.keys(h.routes).sort(), matched: h.matched, note: h.note, ...(h.via?.length ? { via: h.via } : {}),
    ...(h.flags?.length ? { flags: h.flags } : {}) }));
  const query = { terms: q.terms, after: q.after, before: q.before, intent: q.intent, decomposition: q.decomposition, variants: q.variants };
  if (on && Object.keys(q.aliasView).length) query.aliases = q.aliasView;
  return { query, hits: out, timeline: timeline(out) };
}

const numberOrNull = (v) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

export function timeline(hits) {
  const periods = {};
  const sorted = [...hits].sort((a, b) => (a.year || 0) - (b.year || 0) || (a.passage_id < b.passage_id ? -1 : a.passage_id > b.passage_id ? 1 : 0));
  for (const h of sorted) (periods[periodOf(h.year) || "?"] ||= []).push(h.passage_id);
  return periods;
}

/** HybridRetriever._side's window: the query's met with the hull of the searched expansions' windows, widened; [lo, hi)
 * in years (null for an open side), or null when it is empty. */
function sideWindow(q, exps, cfg) {
  const widen = Math.trunc(Number(cfg.widen));
  const lows = exps.map((e) => (e.valid === null || e.valid[0] === null ? null : e.valid[0] - widen));
  const highs = exps.map((e) => (e.valid === null || e.valid[1] === null ? null : e.valid[1] + widen));
  const bound = (a, b, pick) => (a === null ? b : b === null ? a : pick(a, b));
  const lo = bound(q.after, lows.includes(null) ? null : Math.min(...lows), Math.max);
  const hi = bound(q.before, highs.includes(null) ? null : Math.max(...highs), Math.min);
  return lo !== null && hi !== null && lo >= hi ? null : [lo, hi];
}

/** The candidate chunks, the passages among them with what the routes read, the routes, the fusion; with the alias
 * layer (`alias`: {lex, index, cfg, routes}) the tiers, the queues and the labels besides. */
export async function find(corpus, q, { k = 10, active = ROUTES, books = null, alias = null } = {}) {
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
  // the side queue's expansions (those searched where the side queue has a place), their window as chunk numbers
  const exps = alias && (alias.routes === null || alias.routes.includes("alias")) ? q.expansions.filter((e) => e.searched) : [];
  const window = exps.length ? sideWindow(q, exps, alias.cfg) : null;
  const [slo, shi] = window ? await corpus.bounds(window[0], window[1]) : [1, 0];
  const sidePhrases = slo <= shi ? unique(exps.map((e) => ftsPhrase(normalize(e.surface))).filter(Boolean)) : [];
  const sideChunks = share(SIDE_CHUNKS, sidePhrases.length, 3); // per expansion
  const earliest = q.intent === "earliest";
  // 1. candidates: the best-ranked chunks, the earliest and latest of each surface, the earliest of a sense's head term;
  //    and the expansions' best-ranked chunks in the side window (the earliest of each, for an origin question)
  const edgeSurfaces = unique(search).filter((s) => [...s].length >= 2 || search.length <= 1).map((s) => ftsPhrase(normalize(s))).filter(Boolean);
  const heads = unique(targets.map((t) => t[0])).map((h) => ftsPhrase(normalize(h))).filter(Boolean);
  const spans = await corpus.spans(lo, hi);
  const ranked = [];
  const sideRanked = new Map(); // "x<i>" (expansion i) → [chunk, rank] …
  const edgeRows = new Map(); // "a<i>" / "d<i>" (surface i, earliest / latest), "h<i>" (head i), "e<i>" (expansion i)
  const inBooks = only ? " AND rowid IN (SELECT value FROM json_each(?4))" : "";
  await Promise.all(spans.map(async ([db, s, e]) => {
    const parts = [`SELECT 'r' AS t, cid, r FROM (SELECT rowid AS cid, rank AS r FROM fts WHERE fts MATCH ?1 AND rowid BETWEEN ?2 AND ?3${inBooks} ORDER BY rank LIMIT ${RANKED})`];
    edgeSurfaces.slice(0, EDGE_SURFACES).forEach((p, i) => {
      for (const [dir, tag] of [["", "a"], [" DESC", "d"]]) {
        parts.push(`SELECT '${tag}${i}' AS t, cid, 0 FROM (SELECT rowid AS cid FROM fts WHERE fts MATCH ${lit(p)} AND rowid BETWEEN ?2 AND ?3${inBooks} ORDER BY rowid${dir} LIMIT ${EDGES})`);
      }
    });
    heads.forEach((p, i) => parts.push(`SELECT 'h${i}' AS t, cid, 0 FROM (SELECT rowid AS cid FROM fts WHERE fts MATCH ${lit(p)} AND rowid BETWEEN ?2 AND ?3${inBooks} ORDER BY rowid LIMIT ${SENSE_EDGES})`));
    const a = Math.max(s, slo);
    const b = Math.min(e, shi);
    if (a <= b) {
      const within = `rowid BETWEEN ${a} AND ${b}${inBooks}`;
      sidePhrases.forEach((p, i) => {
        parts.push(`SELECT 'x${i}' AS t, cid, r FROM (SELECT rowid AS cid, rank AS r FROM fts WHERE fts MATCH ${lit(p)} AND ${within} ORDER BY rank LIMIT ${sideChunks})`);
        if (earliest) parts.push(`SELECT 'e${i}' AS t, cid, 0 FROM (SELECT rowid AS cid FROM fts WHERE fts MATCH ${lit(p)} AND ${within} ORDER BY rowid LIMIT ${EDGES})`);
      });
    }
    const params = [phrases.join(" OR "), s, e];
    if (only) params.push(JSON.stringify(only.filter((c) => c >= s && c <= e)));
    const rows = await corpus.all(db, unionAll(parts), params);
    for (const r of rows) {
      if (r.t === "r") ranked.push([r.cid, r.r]);
      else if (r.t[0] === "x") {
        if (!sideRanked.has(r.t)) sideRanked.set(r.t, []);
        sideRanked.get(r.t).push([r.cid, r.r]);
      } else {
        if (!edgeRows.has(r.t)) edgeRows.set(r.t, []);
        edgeRows.get(r.t).push(r.cid);
      }
    }
  }));
  const byRank = (a, b) => a[1] - b[1] || a[0] - b[0];
  ranked.sort(byRank);
  // the earliest and latest over the whole corpus (chunk numbers follow the year across the databases): of what each
  // database found, the first EDGES (SENSE_EDGES for a head term), or the last
  const edges = [];
  const sideEdges = [];
  for (const [tag, cids] of edgeRows) {
    cids.sort((a, b) => a - b);
    if (tag[0] === "e") sideEdges.push(...cids.slice(0, EDGES));
    else edges.push(...(tag[0] === "d" ? cids.slice(-EDGES) : cids.slice(0, tag[0] === "h" ? SENSE_EDGES : EDGES)));
  }
  const chosen = unique([...ranked.slice(0, KEEP).map((x) => x[0]), ...edges]);
  const main = new Set(chosen);
  const sideBest = [...sideRanked.values()].flatMap((x) => x.sort(byRank).slice(0, sideChunks).map(([cid]) => cid));
  const sideOnly = unique([...sideBest, ...sideEdges]).filter((c) => !main.has(c));
  if (!chosen.length && !sideOnly.length) return [];
  // 2. the passages that write a surface (or a sense's head term), with the routes' measures; with the layer, those
  //    writing an expansion and no surface in the side window, the gate text and the dates where the tiers read them
  const gates = alias ? gatesOf(alias, q) : null;
  const side = alias ? { exps: sidePhrases.length ? exps : [], sideOnly, slo, shi, earliest, ...textForms(alias.index, gates, surfaces) } : null;
  const rows = await passages(corpus, q, [...chosen, ...sideOnly], { search, surfaces, groups, targets, side });
  const cands = rows.filter((c) => c.mn !== 0);
  // 3. the routes and their fusion
  const { fused, ranked: rankings, pool } = fuse(q, cands, { k, active, surfaces, groups, targets });
  if (!alias) return legacy(q, fused, rankings, pool, k);
  // the ranges of the passages whose dates were read, as the gates read them (their books' dating basis: the cards,
  // kept for the hits' own)
  const dated = rows.filter((c) => c.T !== null);
  const cards = dated.length ? await corpus.cards(unique(dated.map((c) => c.book))) : new Map();
  for (const c of dated) c.card = cards.get(c.book) ?? null;
  return aliasSearch(q, { fused, ranked: rankings, pool, side: rows.filter((c) => c.sd === 1) },
    { ...alias, k, gates, exps: side.exps, own: Math.min(surfaces.length + groups.length, MASK_BITS) });
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
 * reads stays small whatever the query.  With the alias layer (`side`): the searched expansions' bits after the
 * surfaces' and groups', the passages of the side window that write an expansion and no surface (the densest in the
 * expansions, and for an origin question the earliest), the gate text of those and of the passages where a gate reads
 * a form the tiers gate (ctx: textForms; as gate_form wants it, BREAK as "|" and no spaces), which of the asked drugs a
 * passage writes (wr, a bit each), the chunk's dates where a range is read (T: with the text, or for a surface with a
 * floor or referents), and whether a passage is the main queue's (mn: it writes what the query searches, in a chunk
 * the query chose) or a side candidate (sd). */
async function passages(corpus, q, chosen, { search, surfaces, groups, targets, side = null }) {
  const forms = (s) => ftsForm(normalize(s));
  const has = (f) => `instr(j.value, ${lit(f)}) > 0`;
  const tokens = unique(surfaces.flatMap((s) => queryTokens(normalize(s))));
  const bigrams = (tokens.length ? tokens : queryTokens(normalize(q.text))).slice(0, BIGRAMS);
  const headForms = unique(targets.map((t) => t[0]));
  const conds = unique([...search.map(forms), ...headForms.map((h) => ftsForm(h))]).filter(Boolean).map(has);
  const all = (g) => `(${g.map((c) => has(forms(c))).join(" AND ")})`;
  for (const g of groups) conds.push(all(g));
  const own = [...surfaces.map((s) => `(${has(forms(s))})`), ...groups.map(all)].slice(0, MASK_BITS);
  const exps = side ? side.exps : [];
  const labels = [...own, ...exps.map((e) => `(${has(forms(e.surface))})`)].slice(0, MASK_BITS);
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
  const head = "WITH m AS MATERIALIZED (SELECT c.cid AS cid, CAST(j.key AS INTEGER) AS i, c.book AS book, c.year AS year, " +
    "json_extract(c.body, '$.p[' || j.key || '].q') AS q, json_extract(c.body, '$.p[' || j.key || '].m') AS mid, " +
    `length(j.value) AS dl, ${mask} AS mask, ${tf} AS tf, ` +
    `${senseCols.length ? senseCols.map((c) => `(${c})`).join(" || ';' || ") : "''"} AS sense, ${variantCol} AS variant, ` +
    `${density} AS rel`;
  let sql;
  if (!side) {
    sql = `${head} FROM json_each(?1) x JOIN chunks c ON c.cid = x.value, json_each(c.norm) j ` +
      `WHERE ${conds.join(" OR ")}) ` +
      "SELECT cid, i, book, year, q, mid, dl, mask, tf, sense, variant FROM (" +
      `SELECT * FROM (SELECT * FROM m ORDER BY rel DESC, cid, i LIMIT ${ROWS_RELEVANT}) UNION ` +
      `SELECT * FROM (SELECT * FROM m WHERE mask > 0 ORDER BY year DESC, cid, i LIMIT ${ROWS_EDGE}) UNION ` +
      `SELECT * FROM (SELECT * FROM m WHERE mask > 0 ORDER BY year, cid, i LIMIT ${ROWS_EDGE}) UNION ` +
      `SELECT * FROM (SELECT * FROM m WHERE sense != '' ORDER BY rel DESC, cid, i LIMIT ${ROWS_EDGE}))`;
  } else {
    // a main row: what the query searches, in a chunk it chose; a side row: an expansion and no surface, in the window
    const main = `(${conds.join(" OR ")}) AND c.cid NOT IN (SELECT value FROM json_each(?2))`;
    const ownMask = 2 ** own.length - 1;
    const named = unique(exps.map((e) => forms(e.surface)));
    const written = unique(surfaces.map(forms)).filter(Boolean).map(has).join(" OR ") || "0";
    const sideRow = exps.length ? `(${named.map(has).join(" OR ")}) AND NOT (${written}) AND c.cid BETWEEN ${side.slo} AND ${side.shi}` : "0";
    const xrel = exps.length ? `(${named.map(count).join(" + ")}) * 1.0 / (length(j.value) + 40)` : "0";
    const reads = side.read.map(([f, blockers]) => (blockers ? `(${has(f)} AND (${blockers.map(has).join(" OR ")}))` : has(f)));
    const gated = [`(${sideRow})`, ...reads].join(" OR ");
    const wr = side.wr.length ? side.wr.map((f, b) => `(${has(f)}) * ${2 ** b}`).join(" + ") : "0";
    const parts = [
      `SELECT * FROM (SELECT * FROM m WHERE mn ORDER BY rel DESC, cid, i LIMIT ${ROWS_RELEVANT})`,
      `SELECT * FROM (SELECT * FROM m WHERE mn AND (mask & ${ownMask}) > 0 ORDER BY year DESC, cid, i LIMIT ${ROWS_EDGE})`,
      `SELECT * FROM (SELECT * FROM m WHERE mn AND (mask & ${ownMask}) > 0 ORDER BY year, cid, i LIMIT ${ROWS_EDGE})`,
      `SELECT * FROM (SELECT * FROM m WHERE mn AND sense != '' ORDER BY rel DESC, cid, i LIMIT ${ROWS_EDGE})`,
    ];
    const sideParts = [];
    exps.forEach((e, n) => {
      const b = own.length + n; // the expansion's bit
      if (b >= MASK_BITS) return;
      const its = `sd AND (mask & ${2 ** b}) > 0`;
      sideParts.push(`SELECT * FROM (SELECT * FROM m WHERE ${its} ORDER BY xr DESC, cid, i LIMIT ${share(SIDE_ROWS, exps.length, 4)})`);
      if (side.earliest) sideParts.push(`SELECT * FROM (SELECT * FROM m WHERE ${its} ORDER BY year, cid, i LIMIT ${SIDE_ROWS_EDGE})`);
    });
    if (!sideParts.length) sideParts.push("SELECT * FROM m WHERE 0");
    sql = `${head}, CASE WHEN ${gated} THEN j.value END AS ctx, ${wr} AS wr, ${xrel} AS xr, (${main}) AS mn, (${sideRow}) AS sd ` +
      "FROM json_each(?1) x JOIN chunks c ON c.cid = x.value, json_each(c.norm) j " +
      `WHERE (${conds.join(" OR ")}) OR (${sideRow})) ` +
      `SELECT u.cid, u.i, u.book, u.year, u.q, u.mid, u.dl, u.mask, u.tf, u.sense, u.variant, replace(replace(u.ctx, ${lit(BREAK)}, '|'), ' ', ''), ` +
      `CASE WHEN u.ctx IS NOT NULL OR (u.mask & ${side.dated}) > 0 THEN (SELECT json_extract(t.body, '$.T') FROM chunks t WHERE t.cid = u.cid) END, ` +
      "u.xr, u.mn, u.sd, u.wr FROM (" +
      `SELECT * FROM (${parts.join(" UNION ")}) UNION SELECT * FROM (${unionAll(sideParts, 5, " UNION ")})) u`;
  }
  const byDb = new Map();
  for (const cid of chosen) {
    const db = await corpus.dbOf(cid);
    if (db < 0) continue;
    if (!byDb.has(db)) byDb.set(db, []);
    byDb.get(db).push(cid);
  }
  const sideOnly = new Set(side ? side.sideOnly : []);
  const out = [];
  await Promise.all([...byDb].map(async ([db, cids]) => {
    corpus.queries++;
    const params = [JSON.stringify(cids)];
    if (side) params.push(JSON.stringify(cids.filter((c) => sideOnly.has(c))));
    const rows = await corpus.db(db).prepare(sql).bind(...params).raw();
    corpus.rows = (corpus.rows || 0) + rows.length;
    for (const [cid, i, book, year, seq, mid, dl, mask, tf, sense, variant, ctx, T, x, mn, sd, wr] of rows) {
      out.push({ key: `${cid}:${i}`, cid, i, book, year, pid: passageId(book, { q: seq, m: mid }), dl: Math.max(1, dl),
        mask, tf: tf === "" || tf === null ? [] : String(tf).split(",").map(Number), sense: String(sense ?? ""), variant: variant || 0,
        ctx: ctx ?? null, T: T ?? null, x: x ?? 0, mn: mn ?? 1, sd: sd ?? 0, wr: wr ?? 0 });
    }
  }));
  for (const c of out) c.bigrams = bigrams;
  return out;
}

const bit = (mask, b) => ((mask >> b) & 1) === 1; // mask < 2 ** MASK_BITS: an int32

/** The routes over the candidates and their reciprocal-rank fusion (HybridRetriever._fuse): every fused hit, each
 * route's ranking, and the pool past the relevance floor. */
export function fuse(q, cands, { k, active, surfaces, groups, targets }) {
  const depth = Math.max(k * 3, 20);
  const ranked = {};
  const labels = [...surfaces, ...groups.map((g) => g.join("+"))].slice(0, MASK_BITS);
  const ownMask = 2 ** labels.length - 1; // the expansions' bits (the side queue's) after these are no surface
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
    const hits = cands.filter((c) => (c.mask & ownMask) > 0);
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
      if (!hit) fused.set(c.key, (hit = { key: c.key, c, score: 0, routes: {}, matched: [], note: "", via: [], flags: [], tier: "" }));
      hit.score += w / (60 + rank + 1);
      hit.routes[route] = rank + 1;
    });
  }
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
  return { fused, ranked, pool };
}

const byScore = (a, b) => b.score - a.score || cmp(a.c.pid, b.c.pid);

/** HybridRetriever._legacy_search's choice: the k best, the three earliest kept for a question of origins, by date. */
function legacy(q, fused, ranked, pool, k) {
  let hits = [...pool].sort(byScore).slice(0, k);
  if (q.intent === "earliest" && ranked.temporal?.length) {
    const earliest = ranked.temporal.slice(0, 3).map((c) => fused.get(c.key)).filter((h) => h && pool.includes(h));
    const keep = hits.filter((h) => !earliest.includes(h)).slice(0, Math.max(0, k - earliest.length));
    hits = [...earliest, ...keep];
  }
  if (q.intent === "earliest") hits.sort(byYear);
  return hits;
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const byYear = (a, b) => (a.year ?? 9999) - (b.year ?? 9999) || b.score - a.score;

// ------------------------------------------------------------------ the alias search (HybridRetriever._alias_search)
const ablations = (cfg) => new Set(typeof cfg.ablate === "string" ? [cfg.ablate] : cfg.ablate || []);
const idiv = (a, b) => Math.floor(a / b);

/** A row's date range as the gates read it ([null, null] when undated), and its edition's (or null). */
function rangeOf(c) {
  if (c.yr === undefined) {
    const T = typeof c.T === "string" ? JSON.parse(c.T) : c.T;
    const r = T ? effective(T, c.card?.dating_basis || "composition") : null;
    c.yr = r ? [r[0], r[1]] : [null, null];
    const ed = T?.t_edition;
    c.edition = Array.isArray(ed) ? [ed[0], ed[1]] : ed && typeof ed === "object" ? [ed.start, ed.end] : null;
  }
  return c.yr;
}

const NO_TEXT = new Cp("");
/** A row's gate text (gate_form of its normalised text, indexed by code point), from the index form SQL handed back
 * with BREAK as "|" and its spaces taken out; empty when it did not hand it back (no gate reads it: textForms). */
function gateOf(c) {
  if (c.g === undefined) c.g = c.ctx ? new Cp(gateForm(c.ctx)) : NO_TEXT;
  return c.g;
}

/** HybridRetriever._gates: per drug asked, [gate form as written, its blockers, the cues of the context it needs or null,
 * whether only a 一名 or a cue makes it, the form as written, whether it names several drugs (its hits read as one:
 * _annotate)]; the query's own forms as `matched` holds them; the asked drugs' lexicon forms → [entry, the asked name]. */
function gatesOf({ lex, index, cfg }, q) {
  const ablate = ablations(cfg);
  const asked = [];
  const drug = new Map();
  for (const s of q.drugs) {
    const rec = index.record(s);
    const term = q.asked.get(s) ?? null;
    let cues = null;
    if (rec && !ablate.has("gates")) {
      const refs = rec.r.filter((r) => r.st !== "candidate");
      if (rec.stop || (rec.ho === null && rec.fl === null && refs.length && refs.every((r) => r.st === "cue"))) cues = cuesOf(lex, index, s, term);
    }
    const form = q.longer.get(s) ?? s;
    const written = form === s ? rec : index.record(form);
    const ambiguous = !(rec && rec.stop) &&
      new Set(index.referents(s, term, lex).filter((r) => r.st !== "candidate").map((r) => r.g)).size > 1;
    asked.push([gateForm(form), written && !ablate.has("boundary") ? [...written.b] : [], cues, Boolean(rec && rec.stop), form, ambiguous]);
    const entry = term ? lex.entry(term) : null;
    if (entry && entry.cat === "herb") for (const f of entrySurfaces(entry)) if (!drug.has(f)) drug.set(f, [entry, s]);
  }
  const forms = new Set([...allSurfaces(q), ...groupsOf(q).map((g) => g.join("+"))]);
  return { asked, forms, drug, boundary: !ablate.has("boundary") };
}

/** What step 2 hands back for the tiers, as index forms.  `read`: [form, blockers] whose passages come with their text
 * (ctx) — an asked drug as written wherever a cue gate or a reading reads it (blockers null), else only where one of
 * the blockers holding it is written too, and so its lexicon forms; a passage without its text writes none of them
 * inside a blocker (tierOf).  `wr`: the asked drugs, a bit each (beyond the bits, read).  `dated`: the bits of the
 * surfaces whose passages' dates are read without their text (a floor's flag, another referent's window). */
function textForms(index, gates, surfaces) {
  const read = [];
  const wr = [];
  // the blockers that may hold a name (a name of other characters than the gates keep is read wherever written)
  const holding = (s, blockers) => unique(blockers.map((b) => (typeof b === "string" ? b : b[0])).filter((b) => b.includes(s) && b !== s));
  gates.asked.forEach(([gs, blockers, cues, , form, ambiguous], n) => {
    const f = ftsForm(form);
    const near = holding(gs, blockers);
    if (cues !== null || ambiguous || gs !== form || n >= MASK_BITS) read.push([f, null]);
    else if (near.length) read.push([f, near.map(ftsForm)]);
    if (n < MASK_BITS) wr.push(f);
  });
  if (gates.boundary) {
    for (const raw of gates.drug.keys()) {
      const s = normalize(raw);
      const blockers = index.record(s)?.b || [];
      const near = holding(s, blockers);
      if (blockers.length && gateForm(s) !== s) read.push([ftsForm(s), null]);
      else if (near.length) read.push([ftsForm(s), near.map(ftsForm)]);
    }
  }
  let dated = 0;
  surfaces.slice(0, MASK_BITS).forEach((raw, b) => {
    const rec = index.record(normalize(raw));
    if (rec && (rec.fl !== null || (!rec.stop && rec.r.length))) dated += 2 ** b;
  });
  return { read, wr, dated };
}

/** HybridRetriever._tier: [tier, flags] — A an asked drug's name free (and as a drug where it must), D when only
 * demoted, O no surface, H only an asked drug's other lexicon forms (D when each stands inside a blocker), L others.  A
 * passage without its text (no gate reads it: textForms) writes the asked drugs its bits say, each free. */
function tierOf(index, h, gates, cfg) {
  const g = gateOf(h.c);
  const read = g !== NO_TEXT;
  if (!read && gates.asked.some((_, n) => n < MASK_BITS && bit(h.c.wr, n))) return ["A", []];
  const present = read ? gates.asked.filter(([s]) => s && g.includes(s)) : [];
  if (present.length) {
    const yr = rangeOf(h.c);
    let why = "";
    for (const [s, blockers, cues, named] of present) {
      const offs = index.freeOffsets(g, s, blockers, yr);
      if (!offs.length) why ||= `demoted:inside ${index.covering(g, s, blockers, yr)}`;
      else if (cues !== null && !(named ? index.named(g, s, offs, cues, cfg) : index.drugContext(g, s, offs, cues, cfg))) {
        why ||= "demoted:no-context";
      } else return ["A", []];
    }
    return ["D", [why]];
  }
  const forms = h.matched.filter((m) => gates.forms.has(m));
  if (!forms.length) return ["O", []];
  const drug = forms.filter((m) => gates.drug.has(m));
  if (drug.length < forms.length) return ["L", []];
  if (gates.boundary) {
    const yr = rangeOf(h.c);
    const covers = [];
    for (const raw of drug) {
      const s = normalize(raw);
      const rec = index.record(s);
      const blockers = rec ? [...rec.b] : [];
      if (!blockers.length || !read || index.freeOffsets(g, gateForm(s), blockers, yr).length) return ["H", []];
      covers.push(index.covering(g, gateForm(s), blockers, yr));
    }
    return ["D", [`demoted:inside ${covers[0]}`]];
  }
  return ["H", []];
}

/** HybridRetriever._asked_groups: the alias groups of the drugs asked. */
function askedGroups({ lex, index }, q) {
  const out = new Set();
  for (const s of q.drugs) {
    for (const g of index.groupsFor(null, [s])) out.add(g);
    const term = q.asked.get(s) ?? null;
    const entry = term ? lex.entry(term) : null;
    if (entry && entry.cat === "herb") for (const g of index.groupsFor(entry.id, entrySurfaces(entry))) out.add(g);
  }
  return out;
}

/** HybridRetriever._other_referent: the forms a lexicon-form hit matched that name an asked drug only in a window the
 * passage misses (通草 for 木通 in a passage of the Qing). */
function otherReferent(index, h, groups) {
  const out = [];
  for (const raw of groups.size ? h.matched : []) {
    const s = normalize(raw);
    const rec = index.record(s);
    const pairs = rec && !rec.stop ? rec.r.filter((r) => groups.has(r.g)) : [];
    if (!pairs.length) continue;
    const yr = rangeOf(h.c);
    if (pairs.every((r) => r.v !== null && !overlaps(r.v, yr))) out.push(s);
  }
  return out;
}

/** HybridRetriever._retain over the pool: when fewer than `m` of the first main places write the asked name, the best
 * hits that do from deeper in the queue take the places of the lowest others, which follow right after. */
function retain(M, m) {
  if (M.slice(0, m).filter((h) => h.tier === "A").length >= m) return M;
  const top = M.slice(0, m);
  const rest = M.slice(m);
  const up = rest.filter((h) => h.tier === "A");
  let places = top.map((h, i) => (h.tier !== "A" ? i : -1)).filter((i) => i >= 0);
  const n = Math.min(places.length, up.length);
  if (!n) return M;
  places = places.slice(places.length - n);
  const down = places.map((i) => top[i]);
  places.forEach((i, x) => {
    top[i] = up[x];
  });
  const moved = new Set(up.slice(0, n));
  return [...top, ...down, ...rest.filter((h) => !moved.has(h))];
}

/** hybrid._in_years: an origin question's answer, each queue in order of years in its own places. */
function inYears(hits) {
  const out = [...hits];
  const side = [];
  const demoted = [];
  const main = [];
  hits.forEach((h, i) => (h.tier === "X" || h.tier === "B" ? side : h.tier === "D" ? demoted : main).push(i));
  const asked = main.map((i) => hits[i]).filter((h) => h.tier === "A").sort(byYear);
  const rest = main.map((i) => hits[i]).filter((h) => h.tier !== "A").sort(byYear);
  for (const [places, ordered] of [[side, side.map((i) => hits[i]).sort(byYear)], [demoted, demoted.map((i) => hits[i]).sort(byYear)],
    [main, [...asked, ...rest]]]) {
    places.forEach((i, x) => {
      out[i] = ordered[x];
    });
  }
  return out;
}

/** hybrid._witness: the first witness, or with witness_scope web the first the site's corpus holds. */
function witnessOf(wits, cfg) {
  const web = cfg.witness_scope === "web";
  return wits.find((w) => w[4] || !web)?.[0] ?? null;
}

/** HybridRetriever._reading: the drug a name with alias referents reads as in a passage, and its p; [null, null] for any
 * other name. */
function readingOf(index, g, s, yr, cfg) {
  const rec = index.record(s);
  if (!rec || rec.stop || !rec.r.length) return [null, null];
  const [ref, p] = index.reading(g, s, yr, cfg);
  return [ref ? ref.h : null, p];
}

/** HybridRetriever._alias_search after the fusion: the tiers, the main queue (pins of an origin question, retention),
 * the side queue (X: the asked drugs' other lexicon forms; B: the expansions' passages), the slots, the demoted last,
 * the years of an origin question, the labels. */
function aliasSearch(q, { fused, ranked, pool, side }, alias) {
  const { index, cfg, k, gates, routes } = alias;
  const ablate = ablations(cfg);
  const [num, den] = cfg.share;
  const P = [...pool].sort(byScore);
  for (const h of P) [h.tier, h.flags] = tierOf(index, h, gates, cfg);
  const first = cfg.asked_first === "all" || (cfg.asked_first === "herbs" && q.drugs.length > 0);
  const sideTiers = new Set(first ? (cfg.asked_first === "all" ? ["H", "L"] : ["H"]) : []);
  const later = new Set([...sideTiers, "D"]);
  const inside = new Set(P.map((h) => h.key));
  let pins = [];
  if (q.intent === "earliest" && ranked.temporal?.length) {
    // as today, the three earliest attestations stay in the answer to an origin question — of the main queue
    pins = ranked.temporal.map((c) => fused.get(c.key)).filter((h) => h && inside.has(h.key) && !later.has(h.tier)).slice(0, 3);
  }
  const pinned = new Set(pins.map((h) => h.key));
  let M = [...pins, ...P.filter((h) => !later.has(h.tier) && !pinned.has(h.key))];
  if (first) M = retain(M, k - idiv(num * k, den));
  const X = [];
  if (sideTiers.size) {
    const groups = ablate.has("period") ? new Set() : askedGroups(alias, q);
    const lexical = P.filter((h) => sideTiers.has(h.tier));
    if (q.intent === "earliest") lexical.sort(byYear);
    for (const h of lexical) {
      const other = otherReferent(index, h, groups);
      h.flags.push(...unique(other).map((s) => `other-referent:${s}`));
      if (other.length && other.length === h.matched.length) {
        M.push(h); // every form it matched means another drug then
      } else {
        h.tier = "X";
        X.push(h);
      }
    }
  }
  const Bq = routes === null || routes.includes("alias") ? sideQueue(q, side, new Set([...M, ...P].map((h) => h.key)), alias) : [];
  const S = [];
  for (let i = 0; i < Math.max(X.length, Bq.length); i++) {
    if (i < X.length) S.push(X[i]);
    if (i < Bq.length) S.push(Bq[i]);
  }
  const D = P.filter((h) => h.tier === "D");
  let hits;
  if (ablate.has("slots")) {
    hits = [...M, ...S, ...D].sort(byScore).slice(0, k);
    if (q.intent === "earliest") hits.sort(byYear);
  } else {
    hits = assemble(M, S, k, num, den);
    hits.push(...D.slice(0, k - hits.length));
    if (q.intent === "earliest") hits = inYears(hits);
  }
  annotate(q, hits, alias);
  return hits;
}

/** HybridRetriever._side over the side rows: each taken by the first searched expansion whose gates it passes, dealt
 * round-robin over the drugs; within a drug, the passages that give the name nothing beside it (bare) last, the order
 * kept within each (here the density of the expansions, the Worker's stand-in for BM25); an origin question by year. */
function sideQueue(q, rows, seen, { index, cfg, exps, k, own }) {
  if (!exps.length) return [];
  const earliest = q.intent === "earliest";
  const claimed = new Map();
  // an answer takes the first k of a drug's queue at most: a passage is not read when, for every drug an expansion it
  // writes (its bits) is of, k passages its queue holds come before it whatever it gives — those not bare (in an origin
  // question, those of an earlier year, and those of its own that are not bare)
  const bits = exps.map((_, n) => own + n);
  const sure = bits.every((b) => b < MASK_BITS);
  const year = (c) => c.year ?? 9999;
  const ahead = (queue, c) => queue.reduce((n, a) => (earliest ? year(a.c) < year(c) || (!a.bare && year(a.c) === year(c)) : !a.bare) ? n + 1 : n, 0);
  const passed = (c) => sure && exps.every((e, n) => {
    const queue = claimed.get(e.group);
    return !bit(c.mask, bits[n]) || (queue !== undefined && queue.length >= k && ahead(queue, c) >= k);
  });
  const order = rows.filter((c) => !seen.has(c.key)).sort((a, b) => b.x - a.x || a.cid - b.cid || a.i - b.i);
  for (const c of order) {
    if (passed(c)) continue;
    const g = gateOf(c);
    const yr = rangeOf(c);
    for (const e of exps) {
      if (index.accept(g, e, yr, cfg)[0]) {
        if (!claimed.has(e.group)) claimed.set(e.group, []);
        claimed.get(e.group).push({ c, e, g, yr, year: c.year ?? null, bare: index.bare(g, e, yr, cfg) });
        break;
      }
    }
  }
  const queues = [...claimed.values()];
  for (const queue of queues) {
    queue.sort(earliest ? (a, b) => (a.year ?? 9999) - (b.year ?? 9999) || a.bare - b.bare : (a, b) => a.bare - b.bare);
  }
  if (earliest) queues.sort((a, b) => (a[0].year ?? 9999) - (b[0].year ?? 9999));
  const dealt = [];
  const most = Math.max(0, ...queues.map((x) => x.length));
  for (let i = 0; i < most; i++) for (const queue of queues) if (i < queue.length) dealt.push(queue[i]);
  // an answer takes the first k at most (the slots, or the scores under the slots' ablation)
  return dealt.slice(0, k).map(({ c, e, g, yr }, i) => {
    const [reading, p] = readingOf(index, g, e.surface, yr, cfg);
    return { key: c.key, c, score: pyRound((1000 * Number(cfg.alias_score)) / (61 + i), 4), routes: { alias: i + 1 },
      matched: [e.surface], note: "", year: c.year, tier: "B", flags: [],
      via: [{ surface: e.surface, for: [e.for, ...e.also], referent: e.head, direction: e.direction, kind: KINDS[e.kind] ?? e.kind,
        status: e.status, source: index.sourceLabels(e.src), witness: witnessOf(e.wit, cfg), reading, p }] };
  });
}

/** HybridRetriever._annotate: via for the side queue's lexicon-form hits and for hits on an asked drug's name that is
 * ambiguous or needs drug context (the reading; homonym when there is none); an anachronism flag for any matched name
 * written before its floor. */
function annotate(q, hits, alias) {
  const { index, cfg, gates } = alias;
  const noted = new Map();
  q.drugs.forEach((s, n) => {
    const [gs, , cues, , , ambiguous] = gates.asked[n];
    const rec = index.record(s);
    if (rec && rec.stop) return; // a false friend asked through the lexicon: a demoted hit's flag says why
    if (ambiguous || cues !== null) noted.set(s, [gs, ambiguous]);
  });
  for (const h of hits) {
    const yr = rangeOf(h.c);
    if (h.tier === "A" && noted.size) {
      const g = gateOf(h.c);
      for (const [s, [gs, ambiguous]] of noted) {
        if (!g.includes(gs)) continue;
        const [reading, p] = readingOf(index, g, s, yr, cfg);
        // the drug it heads itself is no alias pair: it has no kind, status or source of its own
        const ref = index.readings(s).find((r) => r.h === reading && r.h !== s) ?? null;
        h.via.push({ surface: s, for: [s], referent: reading, direction: "asked", kind: ref ? KINDS[ref.k] ?? ref.k : null,
          status: ref ? ref.st : null, source: ref ? index.sourceLabels(ref.src) : [], witness: ref ? witnessOf(ref.w, cfg) : null,
          reading, p });
        if (ambiguous && reading === null) h.flags.push(`homonym:${s}`);
      }
    } else if (h.tier === "X") h.via.push(...lexiconVia(q, h, alias));
    for (const raw of h.matched) {
      const flag = index.floorFlag(normalize(raw), yr, h.c.edition);
      if (flag && !h.flags.includes(flag)) h.flags.push(flag);
    }
  }
}

/** hybrid._lexicon_kind: how a lexicon entry files one of its names. */
function lexiconKind(entry, name, related = null) {
  for (const f of entrySurfaces(entry)) if (f === name || normalize(f) === name) return entry.synonyms?.[f] || "alias";
  return related === null ? "alias" : related;
}

/** HybridRetriever._lexicon_via: the labels of a side hit on lexicon forms. */
function lexiconVia(q, h, { lex, index, gates }) {
  const termOf = new Map();
  for (const [tid, fs] of Object.entries(q.surfaces)) for (const f of fs) termOf.set(f, tid);
  const out = [];
  for (const raw of unique(h.matched)) {
    const s0 = normalize(raw);
    if (q.asked.has(s0) && !q.longer.has(s0)) continue;
    let entry;
    let direction;
    let kind;
    if (gates.drug.has(raw)) {
      const [e, s] = gates.drug.get(raw);
      entry = e;
      const ownName = raw === entry.term || s0 === s;
      const name = ownName ? s : raw;
      direction = ownName ? DIRECTIONS[0] : DIRECTIONS[1];
      kind = lexiconKind(entry, name);
    } else {
      entry = lex.entry(termOf.get(raw) ?? "");
      if (!entry) continue;
      direction = DIRECTIONS[1];
      kind = lexiconKind(entry, raw, "");
    }
    const asked = [...q.asked].filter(([, tid]) => tid === entry.id).map(([x]) => x);
    asked.sort((a, b) => Number(!q.drugs.includes(a)) - Number(!q.drugs.includes(b)));
    const stop = asked.length > 0 && asked.every((x) => Boolean(index.record(x)?.stop));
    out.push({ surface: s0, for: asked, referent: entry.term, direction, kind: SYNONYM_LABELS[kind] || null,
      status: stop ? "stop" : "open", source: index.sourceLabels(["lexicon"]), witness: null, reading: null, p: null });
  }
  return out;
}

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

/** The cards of the hits (their passages and books), each centred on the name it was found under (passage_card's
 * focus: the hit's matched surfaces). */
async function cardsFor(corpus, hits) {
  const got = await corpus.fetch(hits.map((h) => [h.c.cid, h.c.i]));
  const cards = await corpus.cards(unique([...got.values()].map((x) => x.book)));
  const out = new Map();
  for (const h of hits) {
    const x = got.get(h.key);
    if (x) out.set(h.key, passageCard(x, cards.get(x.book), { focus: h.matched }));
  }
  return out;
}

// ------------------------------------------------------------------ the start
// The alias search run over made-up passages as the module loads, at the isolate's start (whose allowance is far larger
// than a request's 10 ms of CPU): warm.js's questions ask no drug and its made-up rows carry no text, so the first drug
// question would pay for compiling the question's reading, the tiers, the side queue, the gates and the labels (13–33
// ms measured on six databases, against 4–9 once run).  Nothing is read: the lexicon is empty, the names are the shipped
// layer's (an alias whose drug needs its context and stands inside blockers, one that needs neither), the passages
// write them as drugs, inside a blocker, without a context, alone and beside an expansion.  `warming` settles on what
// it gave (the tests check that it went through).
const WARM_DATES = [{ t_composition: [200, 219] }, { t_composition: [1100, 1200] }, { t_edition: [1600, 1700] }];
const WARM_CARD = { title: "warm", dynasty: "东汉", composition: [200, 219], dating_basis: "composition" };

async function warmAliases() {
  const index = aliasIndex();
  const cfg = aliasParams();
  const blockerOf = (r) => r.b.map((b) => (typeof b === "string" ? b : b[0])).find((b) => b.includes(r.s) && b !== r.s);
  const named = [...index.records.values()].filter((r) => !r.stop && cpLen(r.s) >= 2 && !/[^㐀-鿿]/u.test(r.s));
  const cue = named.find((r) => blockerOf(r) && r.r.some((x) => x.st === "cue"));
  const open = named.find((r) => !r.b.length && r.fl === null && r.r.some((x) => x.st === "open"));
  const warmed = { questions: 0, tiers: [], side: 0 };
  if (!cue || !open) return warmed;
  const lex = new Lexicon({ all: async () => [] });
  for (let round = 0; round < 3; round++) {
    for (const text of [`${open.s}与${cue.s}是什么药`, `${cue.s}最早见于哪部书`]) {
      const q = await analyze(lex, text, { aliases: true, cfg, index });
      const surfaces = allSurfaces(q);
      const groups = groupsOf(q);
      const exps = q.expansions.filter((e) => e.searched);
      const alias = { lex, index, cfg, routes: null };
      const gates = gatesOf(alias, q);
      textForms(index, gates, surfaces); // what step 2 would be asked for
      const labels = [...surfaces.map((s) => [normalize(s)]), ...groups, ...exps.map((e) => [e.surface])];
      const bigrams = unique(surfaces.flatMap((s) => queryTokens(normalize(s)))).slice(0, BIGRAMS);
      const texts = [[`${cue.s}二两`, 1], [blockerOf(cue), 1], [`${cue.s}之`, 1], [`${open.s}三两，${cue.s}各等分`, 1], [open.s, 1],
        ...exps.flatMap((e) => [[`${e.surface}二两`, 0], [e.surface, 0], [`${e.surface}汤主之，一名${e.surface}`, 0]])];
      const rows = texts.flatMap(([t, mn], n) => WARM_DATES.map((T, y) => ({ key: `${n}:${y}`, cid: n + 1, i: y, book: "warm",
        year: 200 + 500 * y, pid: `warm.${n}.${y}`, dl: cpLen(t), tf: bigrams.map((b) => Number(t.includes(b))), sense: "",
        variant: 0, ctx: t, T: JSON.stringify(T), x: 1 / (n + 1), mn, sd: 1 - mn, bigrams, card: WARM_CARD,
        mask: labels.reduce((m, forms, b) => (b < MASK_BITS && forms.every((f) => t.includes(f)) ? m + 2 ** b : m), 0),
        wr: gates.asked.reduce((m, [gs], b) => (b < MASK_BITS && t.includes(gs) ? m + 2 ** b : m), 0) })));
      const { fused, ranked, pool } = fuse(q, rows.filter((c) => c.mn), { k: 10, active: ROUTES, surfaces, groups, targets: [] });
      const hits = aliasSearch(q, { fused, ranked, pool, side: rows.filter((c) => c.sd) },
        { ...alias, k: 10, gates, exps, own: Math.min(surfaces.length + groups.length, MASK_BITS) });
      warmed.questions++;
      warmed.tiers = unique([...warmed.tiers, ...hits.map((h) => h.tier)]);
      warmed.side += hits.filter((h) => h.tier === "B").length;
    }
  }
  return warmed;
}

export const warming = warmAliases().catch((err) => console.error("alias warm-up", err?.message || err));
