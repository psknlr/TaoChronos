// The alias layer (plugins/classics/aliases.py, AliasIndex; docs/adr/0023-alias-layer.md) for the D1 backup: the
// records the full-corpus profile reads (tables.js ALIASES, in the file's compact form) and the pure functions the
// search decides with — the gates, the readings, the one-hop expansions and the query.aliases view, the slots — ported
// line for line, so that the Worker decides as the server does from the same data.  As in Python: offsets, lengths and
// slices count code points (`Cp`), strings sort by code point (`cmp`), ties break on explicit keys, the slots are
// integer arithmetic, a p is rounded half up to 4 places (`round4`), sums run left to right and 0.35 is multiplied in
// once per anti-cue.  Records, referents and expansions keep the Python field names (`for_` is `for`); a witness stays
// the file's [pid, y0, y1, kind, web], a window [from, to) with null for an open side, a blocker a string or
// [text, from, to].  The parity test (cloud/test/backup.test.js) replays the cases Python computed (d1fixture.py).
// The isolate's start reads no record: tables.js holds them as lines, each read when first used, and the lookups by
// group, head and term read ALIAS_INDEX (aliases.layout), as AliasIndex reads a file's header index.

import { ALIAS_CONTEXT, ALIAS_INDEX, ALIAS_PARAMS, ALIAS_SOURCES, ALIASES } from "./tables.js";
import { surfaces as entrySurfaces } from "./lexicon.js";

// kind → how an answer names it
export const KINDS = {
  alias: "异名", taboo_rename: "避讳改名", part_name: "药用部位名", processing_variant: "炮制/加工名", abbreviation: "简称",
  variety: "品种/产地名", spelling: "异写", old_name: "古名", folk: "俗名",
};
export const STATUSES = ["open", "cue", "candidate"];
export const DIRECTIONS = ["alias→drug", "drug→alias"];
export const BARE_REST = 4;
export const FORMULA_ENDS = "汤散丸膏丹圆饮";
export const STOP_NOTE = "此名多作普通词语，罕作药名：所列药物只是候选，未按其名检索";
export const STOP_NOTE_LEXICON = "此名多作普通词语，罕作药名：所列药物只是候选，仅按词表检索其同条之名";

const OFF_GATE = /[^㐀-鿿豈-﫿\u{20000}-\u{3134f}〇〓A-Za-z0-9]/gu; // isHan, ASCII alnum
const SURROGATE = /[\uD800-\uDFFF]/;

// ------------------------------------------------------------------ code points
/** A string indexed by code point, as a Python str is: `find`, `startsWith` and `slice` take and give code-point
 * offsets.  A text without astral characters is its own index; only one with them pays for the tables. */
export class Cp {
  constructor(text) {
    this.text = text;
    this.at = null; // code point → UTF-16 offset (astral text only)
    this.back = null; // UTF-16 offset → code point
    if (SURROGATE.test(text)) {
      this.at = [];
      for (let u = 0; u < text.length; u += text.codePointAt(u) > 0xffff ? 2 : 1) this.at.push(u);
      this.at.push(text.length);
      this.back = new Map(this.at.map((u, i) => [u, i]));
    }
    this.length = this.at ? this.at.length - 1 : text.length;
  }

  unit(i) {
    return this.at ? this.at[Math.min(Math.max(i, 0), this.length)] : i;
  }

  /** str.find(sub, start) */
  find(sub, start = 0) {
    if (start > this.length) return -1;
    const u = this.text.indexOf(sub, this.unit(start));
    return u < 0 ? -1 : this.at ? this.back.get(u) : u;
  }

  /** str.startswith(sub, i) */
  startsWith(sub, i) {
    return i <= this.length && this.text.startsWith(sub, this.unit(i));
  }

  /** text[i:j], 0 ≤ i */
  slice(i, j = this.length) {
    return this.at ? this.text.slice(this.unit(i), this.unit(j)) : this.text.slice(i, j);
  }

  includes(sub) {
    return this.text.includes(sub);
  }
}

const cp = (x) => (x instanceof Cp ? x : new Cp(x));
/** len(s) */
export const cpLen = (s) => (SURROGATE.test(s) ? [...s].length : s.length);

/** Python's order of strings: by code point (a UTF-16 surrogate, of a character above U+FFFF, sorts after U+FFFF). */
export function cmp(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    let x = a.charCodeAt(i), y = b.charCodeAt(i);
    if (x === y) continue;
    if (x >= 0xd800 && y >= 0xd800) {
      x = x >= 0xe000 ? x - 0x800 : x + 0x2000;
      y = y >= 0xe000 ? y - 0x800 : y + 0x2000;
    }
    return x < y ? -1 : 1;
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}

const sorted = (xs) => [...xs].sort(cmp);
/** A tuple's order, item by item: numbers by value, strings by code point. */
const cmpTuple = (a, b) => {
  for (let i = 0; i < a.length; i++) {
    const c = typeof a[i] === "string" ? cmp(a[i], b[i]) : a[i] - b[i];
    if (c) return c < 0 ? -1 : 1;
  }
  return 0;
};
/** (a, b) of a Map, an array of pairs or an object, in order. */
const pairs = (x) => (x instanceof Map ? [...x] : Array.isArray(x) ? x : Object.entries(x || {}));
/** a // b for whole a and b > 0, exactly (floored, as Python's: -3 // 10 is -1) */
const idiv = (a, b) => (a - ((a % b) + b) % b) / b;

// ------------------------------------------------------------------ gates
/** gate_form: normalised text as the gates read it — Han and ASCII letters and digits kept, anything else "|"; the
 * same length in code points. */
export function gateForm(norm) {
  return norm.replace(OFF_GATE, "|");
}

/** Python's None: null, or a value left out. */
const none = (x) => x === null || x === undefined;

/** overlaps: whether a passage's range [y0, y1] meets a window [from, to). */
export function overlaps(window, yr) {
  if (none(window) || none(yr)) return true;
  const [lo, hi] = window;
  const [y0, y1] = yr;
  return (none(hi) || none(y0) || y0 < hi) && (none(lo) || none(y1) || y1 >= lo);
}

/** meets: whether a window meets a query's [after, before). */
export function meets(window, after, before) {
  if (none(window)) return true;
  const [lo, hi] = window;
  return (none(hi) || none(after) || after < hi) && (none(lo) || none(before) || before > lo);
}

/** aliases._gap: years between a passage's range and a window it misses — from its last year to the window's first,
 * or from the window's last (to − 1) to its first (a passage of 960 is a year past a window to 960). */
function gap(window, yr) {
  const [lo, hi] = window;
  const [y0, y1] = yr;
  return !none(lo) && !none(y1) && y1 < lo ? lo - y1 : y0 - hi + 1;
}

/** Whether the occurrence of `s` at `i` lies within an occurrence of the longer `b`. */
function inside(g, i, s, b) {
  const B = cp(b);
  let j = B.find(s);
  while (j >= 0) {
    if (j <= i && g.startsWith(b, i - j)) return true;
    j = B.find(s, j + 1);
  }
  return false;
}

/** The blockers of `s` that may cover it in a passage of range `yr`: those holding it whose window meets `yr`. */
function live(blockers, s, yr) {
  const out = [];
  for (const b of blockers) {
    const [text, window] = typeof b === "string" ? [b, null] : [b[0], [b[1], b[2]]];
    if (text.includes(s) && text !== s && overlaps(window, yr)) out.push(text);
  }
  return out;
}

/** The `width` characters on each side of g[i:j], joined by a break so nothing matches across the name. */
function around(g, i, j, width) {
  return g.slice(Math.max(0, i - width), i) + "|" + g.slice(j, j + width);
}

/** The parameters: the profile's (ALIAS_PARAMS, DEFAULT_ALIAS under full-corpus's retrieval.alias) under a call's. */
export const params = (cfg) => ({ ...ALIAS_PARAMS, ...(cfg || {}) });

function ablations(p) {
  const value = p.ablate || [];
  return new Set(typeof value === "string" ? [value] : value);
}

/** _round4: x ≥ 0 to 4 places, halves up (0.65625 → 0.6563). */
export function round4(x) {
  const y = x * 10000;
  const f = Math.floor(y);
  return (y - f >= 0.5 ? f + 1 : f) / 10000;
}

/** A witness's year as answers show it: the middle of its range. */
export function witnessYear(w) {
  const [, y0 = null, y1 = null] = w;
  if (none(y0) || none(y1)) return none(y1) ? y0 : y1;
  return (y0 + y1) / 2;
}

/** The slots: the places p where ⌊num·p/den⌋ steps up (4, 7, 10, 14 … at 3/10) take the side queue's next hit, the
 * others the main queue's, and either queue fills in when the other runs out. */
export function assemble(M, S, k, num = 3, den = 10) {
  const out = [];
  let i = 0, j = 0;
  for (let p = 1; p <= k; p++) {
    const reserved = idiv(num * p, den) > idiv(num * (p - 1), den);
    if (reserved && j < S.length) out.push(S[j++]);
    else if (i < M.length) out.push(M[i++]);
    else if (j < S.length) out.push(S[j++]);
    else break;
  }
  return out;
}

/** Why no expansion is searched where the side queue has no place (HybridRetriever._alias_search): "routes" when the
 * routes leave out alias, "share" when ⌊num·k/den⌋ = 0 (but under the slots ablation); else null. */
export function placeless(routes, k, cfg) {
  const p = params(cfg);
  const [num, den] = p.share;
  if (routes && !routes.includes("alias")) return "routes";
  return idiv(num * k, den) === 0 && !ablations(p).has("slots") ? "share" : null;
}

/** The searched expansions marked unsearched for `why`; whether there was any (the view is then made again). */
export function unsearched(exps, why) {
  if (!why || !exps.some((e) => e.searched)) return false;
  for (const e of exps) {
    if (e.searched) {
      e.searched = false;
      e.why = why;
    }
  }
  return true;
}

// ------------------------------------------------------------------ the listing
// lists of names that cite no passage (aliases.LIST_SOURCES): a candidate only they give, no passage witnessing it, is
// listed and nothing else — no rival; listed after the others, at most LIST_ONLY_CAP for a name that is no drug of its
// own with no other drug to list, none beside one (its own lexicon entry is none: listing)
export const LIST_SOURCES = new Set(["ntu40k", "hurb", "bielu-gb"]);
export const LIST_ONLY_CAP = 3;

function listed(ref) {
  return !ref.w.length && ref.src.length > 0 && ref.src.every((src) => LIST_SOURCES.has(src));
}

/** aliases.list_candidate: a candidate only lists give and no passage witnesses (credited or not). */
export function listCandidate(ref) {
  return ref.st === "candidate" && listed(ref);
}

function listingRank(ref) {
  if (!listed(ref)) return 0;
  return (ref.st === "candidate" ? 3 : 1) + (ref.cr === null ? 1 : 0);
}

/** aliases.listing: the referents query.aliases lists for a name, by rank (stable within each): the candidates only
 * lists give at most LIST_ONLY_CAP, none when the name is a drug of its own (`headed`) or another is listed that shows
 * the name — with `own`, the referents of the name's record, one of them or two drugs (the view shows a name for
 * nothing less: its own lexicon entry alone shows nothing, so 彼子 lists the table's 榧子 beside it); without, any. */
export function listing(refs, headed = false, own = null) {
  const out = [0, 1, 2].flatMap((k) => refs.filter((r) => listingRank(r) === k));
  if (headed || (out.length && (own === null || new Set(out.map((r) => r.g)).size > 1 || out.some((r) => own.includes(r))))) return out;
  return [...out, ...[3, 4].flatMap((k) => refs.filter((r) => listingRank(r) === k)).slice(0, LIST_ONLY_CAP)];
}

// ------------------------------------------------------------------ records
function referent(d) {
  return { h: d.h, g: d.g || d.h, t: d.t ?? null, k: d.k || "alias", st: d.st || "open", v: d.v || null,
    c: d.c || [d.h], a: d.a || [], src: d.src || [], w: d.w || [], cr: d.cr || null };
}

/** A record (aliases.AliasRecord, less what no decision reads): `s` and `stop` are known without reading it (the
 * index's stops), its other fields read from its line when first looked into — so that a walk over every record that
 * looks only at those reads none (search.js's warm-up). */
class Rec {
  constructor(s, item, stop) {
    this.s = s;
    this.stop = stop;
    this.item = item; // its line's JSON, or the compact record itself
    this.data = null;
  }

  get fields() {
    if (this.data === null) {
      const d = typeof this.item === "string" ? JSON.parse(this.item) : this.item;
      if (Boolean(d.stop) !== this.stop) throw new Error(`aliases: the index says ${this.s} is${this.stop ? "" : " not"} a stop name`);
      this.data = { n: d.n || 0, sh: d.sh || 0, b: d.b || [], fl: d.fl ?? null, ho: d.ho ?? null, r: (d.r || []).map(referent) };
      this.item = null;
    }
    return this.data;
  }

  get n() { return this.fields.n; }
  get sh() { return this.fields.sh; }
  get b() { return this.fields.b; }
  get fl() { return this.fields.fl; }
  get ho() { return this.fields.ho; }
  get r() { return this.fields.r; }
}

/** The records by surface, in code-point order, as a Map reads them (get, has, size, keys, values, entries): each
 * made when first asked for. */
class Records {
  constructor(keys, items, stops) {
    this.list = keys;
    this.items = items;
    this.stops = stops; // positions
    this.at = new Map();
    for (let i = 0; i < keys.length; i++) this.at.set(keys[i], i);
    this.made = new Array(keys.length);
  }

  get size() {
    return this.list.length;
  }

  has(s) {
    return this.at.has(s);
  }

  get(s) {
    const i = this.at.get(s);
    return i === undefined ? undefined : this.nth(i);
  }

  nth(i) {
    return (this.made[i] ??= new Rec(this.list[i], this.items[i], this.stops.has(i)));
  }

  keys() {
    return this.list.values();
  }

  *values() {
    for (let i = 0; i < this.list.length; i++) yield this.nth(i);
  }

  *entries() {
    for (let i = 0; i < this.list.length; i++) yield [this.list[i], this.nth(i)];
  }

  [Symbol.iterator]() {
    return this.entries();
  }
}

/** aliases.layout: what the lookups read of records in this order (positions count them from 0) — groups (the
 * positions of the records with a referent in each group, ascending), headless (the groups no referent of their own
 * id heads), heads (the groups of each other head), owners (the surfaces whose ho is another group), terms (the
 * groups of each lexicon term id), stops; lists sorted.  For records given as objects; tables.js carries Python's. */
export function layout(recs) {
  const groups = Object.create(null), heads = Object.create(null), owners = Object.create(null), terms = Object.create(null);
  const selfHeaded = new Set(), stops = [];
  recs.forEach((rec, i) => {
    if (rec.stop) stops.push(i);
    if (rec.ho !== null && rec.ho !== rec.s) (owners[rec.ho] ??= []).push(rec.s);
    for (const ref of rec.r) {
      const at = (groups[ref.g] ??= []);
      if (at[at.length - 1] !== i) at.push(i);
      if (ref.h === ref.g) selfHeaded.add(ref.g);
      else (heads[ref.h] ??= new Set()).add(ref.g);
      if (ref.t) (terms[ref.t] ??= new Set()).add(ref.g);
    }
  });
  const lists = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, sorted(v)]));
  return { groups: { ...groups }, headless: sorted(Object.keys(groups).filter((g) => !selfHeaded.has(g))), heads: lists(heads),
    owners: { ...owners }, terms: lists(terms), stops };
}

/** obj[key] when obj holds it (not from its prototype), else undefined. */
const own = (obj, key) => (Object.hasOwn(obj, key) ? obj[key] : undefined);

/** An expansion (aliases.Expansion), its defaults filled in. */
export function expansion(surface, for_, direction, group, head, fields = {}) {
  return { surface, for: for_, direction, group, head, kind: "alias", status: "open", valid: null, shared: false,
    cues: [], own: [], rivals: [], src: [], wit: [], n: 0, searched: false, why: null, also: [], ...fields };
}

// ------------------------------------------------------------------ the index
export class AliasIndex {
  /** records: tables.js's lines ("surface\tcompact record", in code-point order) with `index` (aliases.layout over
   * them), or {surface: compact record} (its index made here); context: context.json (the patterns, the herb set);
   * sources: [{id, label}]. */
  constructor(records = ALIASES, context = ALIAS_CONTEXT, sources = ALIAS_SOURCES, index = ALIAS_INDEX) {
    if (typeof records === "string") {
      const lines = records ? records.split("\n") : [];
      const keys = new Array(lines.length), items = new Array(lines.length);
      for (let i = 0; i < lines.length; i++) {
        const tab = lines[i].indexOf("\t");
        keys[i] = lines[i].slice(0, tab);
        items[i] = lines[i].slice(tab + 1);
      }
      this.records = new Records(keys, items, new Set(index.stops));
      this.index = index;
    } else {
      const keys = sorted(Object.keys(records));
      const items = keys.map((s) => records[s]);
      this.records = new Records(keys, items, new Set(keys.flatMap((s, i) => (items[i].stop ? [i] : []))));
      this.index = layout([...this.records.values()]);
    }
    this.headless = new Set(this.index.headless);
    this.pairsOf = new Map(); // group → [[surface, referent]], read once
    this.context = context;
    this.labels = Object.fromEntries(sources.map((x) => [x.id, x.label]));
    this.maxLen = 0; // in code points, which a name's UTF-16 length bounds
    for (const s of this.records.list) if (s.length > this.maxLen) this.maxLen = Math.max(this.maxLen, cpLen(s));
    this.enabled = this.records.size > 0;
    // dose, each, prep and named match where the text starts (re.match), nameof anywhere (re.search)
    const start = (p) => new RegExp(`^(?:${p})`, "u");
    this.patterns = { dose: start(context.dose), each: start(context.each), prep: start(context.prep),
      named: start(context.named), nameof: new RegExp(context.nameof, "u") };
    this.herbs = new Set(context.herbs || []);
    this.herbLens = new Map(); // first character → the lengths of the herb names of two or more it starts, longest first
    for (const h of this.herbs) {
      const len = cpLen(h);
      if (len < 2) continue;
      const first = String.fromCodePoint(h.codePointAt(0));
      (this.herbLens.get(first) || this.herbLens.set(first, new Set()).get(first)).add(len);
    }
    for (const [first, lens] of this.herbLens) this.herbLens.set(first, [...lens].sort((a, b) => b - a));
  }

  // what the lookups read (aliases.AliasIndex._pairs, _heads_of, _group_heads_of): per group, its [surface, referent]
  // pairs by surface; per name, the groups it heads — its record's ho, and the groups whose referents it heads; per
  // group, its heads — the referents' and the names whose ho it is; per lexicon term id, its groups
  pairs(g) {
    let out = this.pairsOf.get(g);
    if (out === undefined) {
      out = [];
      const n = this.records.size;
      for (const i of own(this.index.groups, g) || []) {
        if (!(Number.isInteger(i) && i >= 0 && i < n)) throw new Error(`aliases: the index of the records is damaged (${g})`);
        const s = this.records.list[i];
        for (const ref of this.records.nth(i).r) if (ref.g === g) out.push([s, ref]);
      }
      this.pairsOf.set(g, out);
    }
    return out;
  }

  headsOf(s) {
    const out = new Set();
    const rec = this.record(s);
    if (rec && rec.ho !== null) out.add(rec.ho);
    if (Object.hasOwn(this.index.groups, s) && !this.headless.has(s)) out.add(s);
    for (const g of own(this.index.heads, s) || []) out.add(g);
    return out;
  }

  groupHeadsOf(g) {
    const out = new Set(this.pairs(g).map(([, ref]) => ref.h));
    const rec = this.record(g);
    if (rec && rec.ho === g) out.add(g);
    for (const s of own(this.index.owners, g) || []) out.add(s);
    return out;
  }

  get size() {
    return this.records.size;
  }

  record(s) {
    return this.records.get(s) ?? null;
  }

  /** How an answer credits sources: by the labels the layer's sources carry; an unknown id stands for itself. */
  sourceLabels(ids) {
    return ids.map((i) => this.labels[i] ?? i);
  }

  // ---------------------------------------------------------------- lookup
  /** Every [surface, referent] whose referent is in group `g`, by surface. */
  byGroup(g) {
    return [...this.pairs(g)];
  }

  /** The groups an asked lexicon entry belongs to, by its term id and its surfaces, sorted. */
  groupsFor(termId, surfaces) {
    const out = new Set(termId ? own(this.index.terms, termId) || [] : []);
    for (const s of surfaces) for (const g of this.headsOf(s)) out.add(g);
    return sorted(out);
  }

  /** The names that tell group `g` apart, sorted: its heads and its aliases that name nothing else. */
  names(g) {
    const out = this.groupHeadsOf(g);
    for (const [a, ref] of this.pairs(g)) {
      const rec = this.records.get(a);
      if (ref.st !== "candidate" && !rec.stop && rec.r.every((other) => other.g === g)) out.add(a);
    }
    return sorted([...out].filter((n) => cpLen(n) >= 2));
  }

  /** The drugs an asked surface may name: its record's referents, then the lexicon's herb entries for it (its own entry
   * first, the others by term id) whose group none of them is in, as `lexicon` referents headed by that group.  None
   * for a stop name, unless `stop` asks for the drugs it is listed with when asked on its own.  `lex`: lexicon.js's
   * Lexicon (or one alike), its buckets for `s` and `term` loaded. */
  referents(s, term = null, lex = null, { stop = false } = {}) {
    const rec = this.record(s);
    if (rec && rec.stop && !stop) return [];
    const refs = rec ? [...rec.r] : [];
    if (!lex) return refs;
    const seen = new Set(refs.map((ref) => ref.g));
    const own = term ? lex.resolve(term) : null;
    const done = new Set();
    const rivals = lex.lookup(s).map((x) => x.entry).sort((a, b) => cmp(a.id, b.id));
    for (const entry of [...(own ? [own] : []), ...rivals]) {
      if (entry.cat !== "herb" || done.has(entry.id)) continue;
      done.add(entry.id);
      const groups = this.groupsFor(entry.id, [entry.term]);
      if (groups.some((g) => seen.has(g))) continue;
      const g = groups.length ? groups[0] : entry.term;
      // a member's entry names its group's drug, of that drug's term id (蒺藜, herb:蒺藜 — not herb:蒺藜子)
      const t = g === entry.term ? entry.id : (this.pairs(g).find(([, ref]) => ref.h === g && ref.t)?.[1].t ?? null);
      refs.push(referent({ h: g, t, src: ["lexicon"] }));
      seen.add(g);
    }
    return refs;
  }

  /** Whether `s` names nothing but candidates only lists give (listCandidate): no stop, no head, no floor — a name a
   * question asks only as its one name. */
  listedOnly(s) {
    const rec = this.record(s);
    return rec !== null && !rec.stop && rec.ho === null && rec.fl === null && rec.r.length > 0 &&
      rec.r.every(listCandidate);
  }

  /** Alias and head surfaces in normalised text, [start, end, surface]: longest first, left to right, stop names left
   * out; a record with only a first-use floor names a drug too. */
  scan(norm) {
    const chars = [...norm];
    const out = [];
    let i = 0;
    const n = chars.length;
    while (i < n) {
      let found = false;
      for (let length = Math.min(this.maxLen, n - i); length > 1; length--) {
        const rec = this.records.get(chars.slice(i, i + length).join(""));
        if (rec && !rec.stop && (rec.r.length || rec.ho !== null || rec.fl !== null)) {
          out.push([i, i + length, rec.s]);
          i += length;
          found = true;
          break;
        }
      }
      if (!found) i++;
    }
    return out;
  }

  // ---------------------------------------------------------------- gates
  /** Offsets of `s` in gate-form text `g` not covered by a blocker whose window overlaps `yr`; a blocker written there
   * only inside one of its own blockers covers nothing (one step). */
  freeOffsets(g, s, blockers, yr) {
    const G = cp(g);
    const blocking = live(blockers, s, yr).filter((b) => G.text.includes(b)); // one not written covers nothing
    const out = [];
    let i = s ? G.find(s) : -1;
    while (i >= 0) {
      if (blocking.every((b) => this.covers(G, i, s, b, yr) === null)) out.push(i);
      i = G.find(s, i + 1);
    }
    return out;
  }

  /** The offset of an occurrence of the blocker `b` that covers `s` at `i` — one holding it and free of `b`'s own
   * blockers — or null. */
  covers(g, i, s, b, yr) {
    const G = cp(g);
    const B = cp(b);
    let j = B.find(s);
    while (j >= 0) {
      const k = i - j;
      if (j <= i && G.startsWith(b, k)) {
        const rec = this.records.get(b);
        if (!rec || !live(rec.b, b, yr).some((c) => inside(G, k, b, c))) return k;
      }
      j = B.find(s, j + 1);
    }
    return null;
  }

  /** The blocker a demoted name stands inside (the first that covers an occurrence), for its flag (hybrid._covering). */
  covering(g, s, blockers, yr) {
    const G = cp(g);
    const offs = [];
    for (let i = 0; i < G.length; i++) if (G.startsWith(s, i)) offs.push(i);
    for (const b of blockers) {
      const [text, window] = typeof b === "string" ? [b, null] : [b[0], [b[1], b[2]]];
      if (text.includes(s) && text !== s && overlaps(window, yr) && G.text.includes(text) &&
        offs.some((i) => this.covers(G, i, s, text, yr) !== null)) {
        return text;
      }
    }
    return "?";
  }

  /** Herb-set names in `text`, matched longest first, left to right (only the lengths of the names a character starts
   * are tried). */
  herbCount(text) {
    const chars = [...text];
    let count = 0, i = 0;
    while (i < chars.length) {
      let found = false;
      for (const length of this.herbLens.get(chars[i]) || []) {
        if (length <= chars.length - i && this.herbs.has(chars.slice(i, i + length).join(""))) {
          count++;
          i += length;
          found = true;
          break;
        }
      }
      if (!found) i++;
    }
    return count;
  }

  /** Whether `s` reads as a drug at one of `offs`: a dose, 各, a preparation after it, a 一名 before it, a cue or two herb
   * names near it. */
  drugContext(g, s, offs, cues, cfg = null) {
    const G = cp(g);
    const p = params(cfg);
    cues = cues.filter((c) => c && c !== s);
    const { dose, each, prep } = this.patterns;
    const len = cpLen(s);
    for (const i of offs) {
      const j = i + len;
      const after = G.slice(j, j + 12);
      if (dose.test(after) || each.test(after) || prep.test(after) || this.named(G, s, [i], cues, p)) return true;
      if (this.herbCount(around(G, i, j, p.list_window)) >= 2) return true;
    }
    return false;
  }

  /** Whether `s` is named as the drug at one of `offs`: a 一名 before it, a 之名 after it or a cue near it. */
  named(g, s, offs, cues, cfg = null) {
    const G = cp(g);
    const p = params(cfg);
    cues = cues.filter((c) => c && c !== s);
    const { nameof, named } = this.patterns;
    const len = cpLen(s);
    for (const i of offs) {
      const j = i + len;
      if (nameof.test(G.slice(Math.max(0, i - 4), i)) || named.test(G.slice(j, j + 4))) return true;
      const near = around(G, i, j, p.cue_window);
      if (cues.some((c) => near.includes(c))) return true;
    }
    return false;
  }

  /** Whether a side-queue passage is taken for an expansion: [taken, reason], the reason "ok" or the gate that refused
   * (absent, candidate, boundary, context, rival, period).  The rival gate counts a rival only where the passage's
   * range meets its window; names are read outside the expansion's own occurrences (木香 in 青木香 is no rival's). */
  accept(g, exp, yr, cfg = null) {
    const G = cp(g);
    const p = params(cfg);
    const ablate = ablations(p);
    const s = exp.surface;
    if (!G.includes(s)) return [false, "absent"];
    const gates = !ablate.has("gates");
    if (exp.status === "candidate" && gates) return [false, "candidate"];
    const rec = this.record(s);
    const offs = this.freeOffsets(G, s, rec && !ablate.has("boundary") ? rec.b : [], yr);
    if (!offs.length) return [false, "boundary"];
    if (exp.status === "cue" && gates && !this.drugContext(G, s, offs, exp.cues, p)) return [false, "context"];
    if (exp.direction === DIRECTIONS[1] && gates) {
      const rivals = exp.rivals.filter(([window]) => ablate.has("period") || overlaps(window, yr)).map(([, names]) => names);
      if (rivals.length) {
        const rest = G.text.split(s).join("|");
        if (!exp.own.some((n) => rest.includes(n)) || rivals.some((names) => names.some((n) => rest.includes(n)))) {
          return [false, "rival"];
        }
      }
    }
    if (!ablate.has("period") && !overlaps(exp.valid, yr)) return [false, "period"];
    return [true, "ok"];
  }

  /** Whether a side passage gives an expansion's name nothing beside it: with the formula names it writes left out,
   * fewer than BARE_REST characters outside the name, and the name in no drug context.  An order, never a gate. */
  bare(g, exp, yr, cfg = null) {
    const s = exp.surface;
    const runs = cp(g).text.split("|");
    let rest = 0;
    for (const run of runs) {
      const left = run.split(s).join("");
      if (left && !this.formula(run, s) && (rest += cpLen(left)) >= BARE_REST) return false;
    }
    const text = runs.map((run) => (this.formula(run, s) ? "|".repeat(cpLen(run)) : run)).join("|");
    const rec = this.record(s);
    const offs = this.freeOffsets(text, s, rec ? rec.b : [], yr);
    return !this.drugContext(text, s, offs, exp.cues, cfg);
  }

  /** Whether a gate-form run reads as a formula's name to `bare`: at most 8 characters ending in one of FORMULA_ENDS,
   * neither ending in the name nor a drug's name itself. */
  formula(run, s) {
    // the last code unit first (an astral last character ends in a surrogate, which is no formula's end)
    if (!run || !FORMULA_ENDS.includes(run[run.length - 1]) || cpLen(run) > 8 || run.endsWith(s) || this.herbs.has(run)) return false;
    const rec = this.records.get(run);
    return !rec || rec.stop || !(rec.r.length || rec.ho !== null);
  }

  /** The drugs a passage may read a name as: its record's referents that are not candidates, then — when the name heads
   * a drug none of them is — that drug, cued by its own names. */
  readings(s) {
    const rec = this.record(s);
    if (!rec || rec.stop) return [];
    const refs = rec.r.filter((ref) => ref.st !== "candidate");
    if (refs.length && rec.ho !== null && refs.every((ref) => ref.g !== rec.ho)) {
      refs.push(referent({ h: s, g: rec.ho, c: this.names(rec.ho) }));
    }
    return refs;
  }

  /** The referent an ambiguous name reads as in a passage, by the Terminology.resolve formula, and its p: [referent or
   * null, p].  fit 1 when a referent's window meets `yr`, else max(0.15, 1 − gap/600); raw = fit · (1 + cues) ·
   * 0.35^anti-cues near a free occurrence; p = raw / Σ raw to 4 places; the best is the reading when its p ≥ 0.5 and no
   * other referent has the same p. */
  reading(g, s, yr, cfg = null) {
    const G = cp(g);
    const rec = this.record(s);
    const refs = this.readings(s);
    if (!refs.length) return [null, 0];
    const width = params(cfg).reading_window;
    const len = cpLen(s);
    const near = this.freeOffsets(G, s, rec.b, yr).map((i) => around(G, i, i + len, width));
    const raw = [];
    for (const ref of refs) {
      const fit = overlaps(ref.v, yr) ? 1.0 : Math.max(0.15, 1.0 - gap(ref.v, yr) / 600.0);
      let cues = 0;
      for (const c of ref.c) if (c && c !== s && near.some((t) => t.includes(c))) cues++;
      let damp = 1.0;
      for (const c of ref.a) if (c && c !== s && near.some((t) => t.includes(c))) damp *= 0.35;
      raw.push(fit * (1.0 + cues) * damp);
    }
    let total = 0.0;
    for (const x of raw) total += x;
    const probs = raw.map((x) => round4(x / (total || 1.0)));
    const best = Math.max(...probs);
    if (best < 0.5 || probs.filter((x) => x === best).length > 1) return [null, best];
    return [refs[probs.indexOf(best)], best];
  }

  /** "anachronism:<s><<floor>:edition|layer" when a passage writes `s` before the name was in use. */
  floorFlag(s, yr, edition) {
    const rec = this.record(s);
    if (!rec || rec.fl === null || none(yr) || none(yr[1]) || yr[1] >= rec.fl) return null;
    const later = !none(edition) && !none(edition[1]) && edition[1] >= rec.fl;
    return `anachronism:${s}<${rec.fl}:${later ? "edition" : "layer"}`;
  }

  // ---------------------------------------------------------------- expansion
  /** The one-hop expansions of a parsed query, ordered and capped.  `q`: {asked: [[surface, term id or null]] (or a
   * Map or an object, in the order asked), after, before, allSurfaces: the query's surfaces (or a function giving
   * them), groups: {term id: [[component …]]}}; `lex`: the lexicon (or null) for `resolve`.  An asked alias reaches its
   * referents' heads and their groups' spellings; an asked drug the other names of its groups; never further.  A stop
   * name reaches no drug; a part name another part's drug is shown, never searched (why part).  Ordered by direction,
   * status, passages (most first) and surface; the first cap attested ones are searched; those whose window misses the
   * query's come next (why period), other parts last (why part). */
  expansions(q, lex, cfg) {
    const p = params(cfg);
    const ablate = ablations(p);
    const { after = null, before = null } = q;
    const asked = pairs(q.asked);
    const searched = [...(typeof q.allSurfaces === "function" ? q.allSurfaces() : q.allSurfaces || [])];
    const taken = new Set([...searched, ...asked.map(([s]) => s)]);
    const found = [], excluded = [], parts = [];
    const add = (e, order, part = false) => {
      const key = [DIRECTIONS.indexOf(e.direction), STATUSES.indexOf(e.status), -e.n, e.surface, order, e.group, e.head];
      (part ? parts : meets(e.valid, after, before) ? found : excluded).push([key, e]);
    };
    const otherPart = (name, ref) => {
      const named = this.records.get(name);
      return ref.k === "part_name" && !ablate.has("gates") && (!named || named.ho !== ref.g);
    };
    asked.forEach(([s, term], order) => {
      const rec = this.record(s);
      const refs = rec && !rec.stop ? rec.r : [];
      // alias → drug: the referent's head and its group's spellings (the head alone when the period is missed)
      for (const ref of refs) {
        if (ref.st === "candidate" && !ablate.has("gates")) continue;
        const valid = ablate.has("period") ? null : ref.v;
        const reached = [[ref.h, ref]];
        const part = otherPart(s, ref);
        if (meets(valid, after, before) && !part) {
          for (const [a, other] of this.pairs(ref.g)) {
            if (other.k === "spelling" && other.st !== "candidate") reached.push([a, other]);
          }
        }
        for (const [h, pair] of reached) {
          const hrec = this.record(h);
          if (cpLen(h) < 2 || taken.has(h) || (hrec && hrec.stop)) continue;
          add(expansion(h, s, DIRECTIONS[0], ref.g, ref.h, { kind: pair.k, status: "open", valid,
            shared: Boolean(hrec) && new Set(hrec.r.filter((r) => !listCandidate(r)).map((r) => r.g)).size > 1, cues: [...ref.c], src: [...pair.src],
            wit: [...pair.w], n: hrec ? hrec.n : 0 }), order, part);
        }
      }
      // drug → alias: the other names of the groups the asked name heads
      const groups = new Set(this.groupsFor(null, [s]));
      const entry = lex && term && !(rec && rec.stop) ? lex.resolve(term) : null;
      if (entry && entry.cat === "herb") {
        const own = new Set(refs.filter((ref) => ref.k !== "spelling").map((ref) => ref.g));
        for (const g of this.groupsFor(entry.id, entrySurfaces(entry))) if (!own.has(g)) groups.add(g);
      }
      for (const g of sorted(groups)) {
        const ownNames = this.names(g);
        for (const [a, ref] of this.pairs(g)) {
          const arec = this.records.get(a);
          if (arec.stop || cpLen(a) < 2 || taken.has(a) || (ref.st === "candidate" && !ablate.has("gates"))) continue;
          // the drugs the name may also mean here (a referent whose window misses the query's is none)
          const own = ownNames.filter((n) => n !== a);
          const rivals = [...arec.r].sort((x, y) => cmp(x.g, y.g))
            .filter((r) => r.g !== g && !listCandidate(r) && (ablate.has("period") || meets(r.v, after, before)))
            .map((r) => [ablate.has("period") ? null : r.v, sorted(this.names(r.g).filter((n) => !own.includes(n) && n !== a))]);
          add(expansion(a, s, DIRECTIONS[1], g, ref.h, { kind: ref.k, status: ablate.has("gates") ? "open" : ref.st,
            valid: ablate.has("period") ? null : ref.v, shared: rivals.length > 0, cues: [...ref.c], own, rivals,
            src: [...ref.src], wit: [...ref.w], n: arec.n }), order, otherPart(a, ref));
        }
      }
    });
    const out = [];
    const seen = new Map();
    const bySurface = (e) => (seen.has(e.surface) ? seen.get(e.surface) : seen.set(e.surface, e).get(e.surface));
    for (const [, e] of found.sort((x, y) => cmpTuple(x[0], y[0]))) {
      const kept = bySurface(e);
      if (kept === e) out.push(e);
      else if (e.for !== kept.for && !kept.also.includes(e.for)) kept.also.push(e.for);
    }
    let groupsN = 0;
    for (const gs of Object.values(q.groups || {})) groupsN += gs.length;
    const cap = Math.max(0, Math.min(Math.trunc(Number(p.expansions)), Math.trunc(Number(p.mask_bits)) - searched.length - groupsN));
    let used = 0;
    for (const e of out) {
      if (e.n <= 0) e.why = "unattested";
      else if (used < cap) {
        e.searched = true;
        used++;
      } else e.why = "cap";
    }
    for (const [why, rest] of [["period", excluded], ["part", parts]]) {
      for (const [, e] of rest.sort((x, y) => cmpTuple(x[0], y[0]))) {
        if (bySurface(e) === e) {
          e.why = why;
          out.push(e);
        }
      }
    }
    const place = new Map(asked.map(([s], i) => [s, i]));
    for (const e of out) e.also.sort((a, b) => place.get(a) - place.get(b));
    return out;
  }

  /** The query.aliases block: asked names with their referents (an alias, or a name of several drugs, the lexicon's
   * included), then the stop names asked on their own (`q.stops`, as `q.asked`) with every drug their record or the
   * lexicon gives them, of status stop, and the note; the expansions shown, and those the window left out.  {} when
   * there is nothing to show.  `exps`: those `expansions` gave (computed when null). */
  view(q, cfg, lex = null, exps = null) {
    const p = params(cfg);
    const web = p.witness_scope === "web";
    exps = exps ?? this.expansions(q, lex, p);
    const asked = [];
    for (const [s, term] of pairs(q.asked)) {
      const rec = this.record(s);
      const refs = listing(this.referents(s, term, lex), Boolean(rec) && (rec.ho !== null || rec.fl !== null), rec ? rec.r : []);
      const groups = new Set(refs.map((ref) => ref.g));
      if (!refs.length || ((!rec || !refs.some((ref) => rec.r.includes(ref))) && groups.size < 2)) continue;
      asked.push({ surface: s, term, ambiguous: groups.size > 1, referents: refs.map((ref) => this.referentView(ref, web)) });
    }
    for (const [s, term] of pairs(q.stops)) {
      const rec = this.record(s);
      const refs = rec && rec.stop ? listing(this.referents(s, term, lex, { stop: true }), rec.ho !== null || rec.fl !== null) : [];
      const entry = lex && term ? lex.entry(term) : null;
      if (refs.length) {
        asked.push({ surface: s, term, ambiguous: new Set(refs.map((ref) => ref.g)).size > 1,
          referents: refs.map((ref) => ({ ...this.referentView(ref, web), status: "stop" })),
          note: entry && entry.cat === "herb" ? STOP_NOTE_LEXICON : STOP_NOTE });
      }
    }
    const shown = exps.filter((e) => e.why !== "period").map((e) => ({ surface: e.surface, for: e.for,
      direction: e.direction, referent: e.head, kind: KINDS[e.kind] ?? e.kind, status: e.status, searched: e.searched,
      why: e.why }));
    const excluded = exps.filter((e) => e.why === "period").map((e) => ({ surface: e.surface, for: e.for, why: e.why }));
    if (!(asked.length || shown.length || excluded.length)) return {};
    return { asked, expansions: shown, excluded };
  }

  referentView(ref, web) {
    const wit = ref.w.find((w) => w[4] || !web) ?? null;
    const head = this.record(ref.h);
    return { head: ref.h, kind: KINDS[ref.k] ?? ref.k, status: ref.st, valid: ref.v ? [...ref.v] : null,
      floor: head ? head.fl : null, source: this.sourceLabels(ref.src), witness: wit ? wit[0] : null,
      witness_year: wit ? witnessYear(wit) : null, credited: ref.cr ? [...ref.cr] : null };
  }
}

let shared = null;
/** The index over tables.js, made once per isolate. */
export function aliasIndex() {
  return (shared ??= new AliasIndex());
}
