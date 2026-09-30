// The text as the corpus's tools read it: the normaliser (plugins/classics/domain.py, VariantTable), the index's form of
// a text (taochronos.chat.d1.fts_form), the periods and the expressions of time (domain.Periods), and Python's own ways
// with numbers where a result shows them.  The tables are generated from the checkout (tables.js): the databases were
// normalised with the same ones (tables.NORMALIZER is checked against the databases' own).

import { CHAR_MAP, CURATED, DYNASTIES, EXPRESSIONS, PERIODS, SCRIPT, WORDS } from "./tables.js";

export const BREAK = "zx"; // the index's token for ASCII punctuation, spaces and control characters
const ALNUM = /^[A-Za-z0-9]$/;

const normalized = new Map(); // short texts normalised in this isolate (queries, surfaces, cues)

// The character map as a table of UTF-16 code units, for speed: MAP16[c] is what a BMP character c becomes when that
// is one BMP character, WIDE (marked 0xffff, a code unit no text has) when it becomes an astral one (a surrogate pair);
// an astral character is looked up in CHAR_MAP itself.
const MAP16 = new Uint16Array(65536);
const WIDE = new Map();
for (const [from, to] of Object.entries(CHAR_MAP)) {
  if (from.length !== 1) continue;
  if (to.length === 1) MAP16[from.charCodeAt(0)] = to.charCodeAt(0);
  else {
    MAP16[from.charCodeAt(0)] = 0xffff;
    WIDE.set(from.charCodeAt(0), to);
  }
}
let units = new Uint16Array(4096);

/** VariantTable.normalize_text: the character map (curated variants, then script conversion), then the word variants. */
export function normalize(text) {
  const s = String(text ?? "");
  const n = s.length;
  if (n <= 64) {
    const hit = normalized.get(s);
    if (hit !== undefined) return hit;
  }
  if (units.length < 2 * n) units = new Uint16Array(2 * n + 1024);
  let m = 0;
  for (let i = 0; i < n; i++) {
    const c = s.charCodeAt(i);
    const to = MAP16[c];
    if (to === 0) {
      if (c >= 0xd800 && c <= 0xdbff && i + 1 < n) { // an astral character: a surrogate pair
        const pair = s.slice(i, i + 2);
        const got = CHAR_MAP[pair] ?? pair;
        for (let j = 0; j < got.length; j++) units[m++] = got.charCodeAt(j);
        i++;
      } else units[m++] = c;
    } else if (to !== 0xffff) units[m++] = to;
    else {
      const w = WIDE.get(c);
      for (let j = 0; j < w.length; j++) units[m++] = w.charCodeAt(j);
    }
  }
  let out = "";
  for (let i = 0; i < m; i += 8192) out += String.fromCharCode.apply(null, units.subarray(i, Math.min(m, i + 8192)));
  for (const [from, to] of WORDS) if (out.includes(from)) out = out.split(from).join(to);
  if (n <= 64) {
    if (normalized.size > 5000) normalized.clear();
    normalized.set(s, out);
  }
  return out;
}

/** VariantTable.normalize: the text and the curated and word normalisations applied ({start, end, from, to, kind}),
 * in order of position (script conversions are systematic and not recorded). */
export function normalizeWithRecords(text) {
  const chars = [...String(text ?? "")];
  const applied = [];
  chars.forEach((ch, i) => {
    const hit = CURATED[ch];
    if (hit) {
      chars[i] = hit[0];
      applied.push({ start: i, end: i + 1, from: ch, to: hit[0], kind: "variant_char", note: hit[1] || "" });
    }
  });
  let out = chars.map((ch) => SCRIPT[ch] ?? ch).join("");
  for (const [from, to, kind, note] of WORDS) {
    // Python str.find / slice on code points: work on arrays of code points
    let start = 0;
    for (;;) {
      const idx = indexOfCodePoints(out, from, start);
      if (idx < 0) break;
      const cps = [...out];
      const len = [...to].length;
      out = cps.slice(0, idx).join("") + to + cps.slice(idx + len).join("");
      applied.push({ start: idx, end: idx + len, from, to, kind: kind || "variant", note: note || "" });
      start = idx + len;
    }
  }
  applied.sort((a, b) => a.start - b.start);
  return { normalized: out, normalizations: applied.map(({ start, end, from, to, kind }) => ({ start, end, from, to, kind })) };
}

/** str.find over code points (what a Python offset means). */
export function indexOfCodePoints(text, sub, start = 0) {
  const cps = [...text];
  const needle = [...sub];
  outer: for (let i = start; i <= cps.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (cps[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

/** d1.fts_form: one token per character; ASCII punctuation, spaces and control characters become BREAK. */
export function ftsForm(norm) {
  const out = [];
  for (const ch of norm) out.push(ch.codePointAt(0) >= 128 || ALNUM.test(ch) ? ch : BREAK);
  return out.join(" ");
}

/** store.is_han */
export function isHan(ch) {
  const o = ch.codePointAt(0);
  return (o >= 0x3400 && o <= 0x9fff) || (o >= 0xf900 && o <= 0xfaff) || (o >= 0x20000 && o <= 0x3134f) || o === 0x3007 || o === 0x3013;
}

/** d1.fts_phrase: a normalised surface's Han characters as one FTS5 phrase (null when it has none). */
export function ftsPhrase(normSurface) {
  const chars = [...normSurface].filter(isHan);
  return chars.length ? `"${chars.join(" ")}"` : null;
}

// ------------------------------------------------------------------ periods (domain.Periods)
export const periodIds = () => PERIODS.map((p) => p[0]);

/** The analysis period of a year: years before the first count in it, years from the last period's end in none. */
export function periodOf(year) {
  if (year === null || year === undefined || Number.isNaN(year)) return null;
  if (year >= PERIODS[PERIODS.length - 1][3]) return null;
  for (const [id, , start, end] of PERIODS) if (start <= year && year < end) return id;
  return PERIODS[0][0];
}

export function periodLabel(id) {
  const p = PERIODS.find((x) => x[0] === id);
  return p ? p[1] : id;
}

export function dynastyOf(year) {
  if (year === null || year === undefined) return null;
  const hits = DYNASTIES.filter(([, s, e]) => s <= year && year <= e);
  if (!hits.length) return null;
  return hits.reduce((a, b) => (b[1] > a[1] ? b : a))[0];
}

const EXPR = Object.keys(EXPRESSIONS).sort((a, b) => b.length - a.length);
const EXPR_RE = new RegExp(`(${EXPR.map(escapeRe).join("|")})`, "gu");
const SINGLE_TAIL = /^(代|朝|以前|之前|以后|之后|以来|以降|至|到|—|~|时期|初|末|医家|文献|人)/u;

export function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function expressionMatches(text) {
  const out = [];
  for (const m of text.matchAll(EXPR_RE)) {
    const expr = m[1];
    if ([...expr].length === 1 && !SINGLE_TAIL.test(text.slice(m.index + expr.length))) continue;
    out.push({ expr, start: m.index, end: m.index + expr.length });
  }
  return out;
}

/** Periods.parse_constraint: 宋代以前 / 唐以后 / 汉至宋 / 明清 → [after, before] (either null). */
export function parseConstraint(text) {
  const matches = expressionMatches(text);
  for (let i = 0; i + 1 < matches.length; i++) {
    const a = matches[i];
    const b = matches[i + 1];
    const between = text.slice(a.end, b.start);
    const from = /(从|自)$/u.test(text.slice(Math.max(0, a.start - 1), a.start));
    if (/^代?(至|到|—|-|~)$/u.test(between) || (from && /(至|到)$/u.test(between) && [...between].length <= 8)) {
      return [EXPRESSIONS[a.expr][0], EXPRESSIONS[b.expr][1]];
    }
  }
  for (const m of matches) {
    const [start, end] = EXPRESSIONS[m.expr];
    const tail = [...text.slice(m.end)].slice(0, 3).join("");
    if (/^[代朝]?(以前|之前|前)/u.test(tail)) return [null, start];
    if (/^[代朝]?(以后|之后|以来|以降|后)/u.test(tail)) return [start, null];
    return [start, end];
  }
  return [null, null];
}

// ------------------------------------------------------------------ dates of a passage (documents.TemporalContext)
const ORDER = {
  composition: ["t_composition", "t_author", "t_edition"],
  author: ["t_author", "t_composition", "t_edition"],
  edition: ["t_edition", "t_composition", "t_author"],
  citation: ["t_citation", "t_composition", "t_author"],
  earliest: ["t_citation", "t_author", "t_composition", "t_edition"],
};

/** TemporalContext.effective: the first of the clocks the basis orders, as [start, end]. */
export function effective(temporal, basis = "composition") {
  for (const key of ORDER[basis] || ORDER.composition) {
    const v = temporal?.[key];
    if (Array.isArray(v)) return v;
    if (v && typeof v === "object") return [v.start, v.end];
  }
  return null;
}

export function yearOf(temporal, basis = "composition") {
  const r = effective(temporal, basis);
  return r ? (r[0] + r[1]) / 2 : null;
}

/** to_jsonable(TemporalContext): year ranges as {start, end}. */
export function temporalJson(t) {
  const range = (v) => (Array.isArray(v) ? { start: v[0], end: v[1] } : v ?? null);
  return { dynasty: t?.dynasty ?? null, t_author: range(t?.t_author), t_composition: range(t?.t_composition),
    t_edition: range(t?.t_edition), t_citation: range(t?.t_citation) };
}

/** YearRange.label */
export function rangeLabel(r) {
  if (!r) return null;
  const [s, e] = Array.isArray(r) ? r : [r.start, r.end];
  const fmt = (y) => (y < 0 ? `前${-y}` : String(y));
  return s === e ? fmt(s) : `${fmt(s)}–${fmt(e)}`;
}

// ------------------------------------------------------------------ Python's numbers
/** round(x, n) as Python rounds: to the nearest on the value as stored, ties to even.  x·10ⁿ is itself rounded, so it
 * decides only when clear of a tie; near one, the stored value's own decimal digits do (1.5 × 36.9 is stored just
 * under 55.35: 55.3, as in Python). */
export function pyRound(x, n = 0) {
  if (x === null || x === undefined || !Number.isFinite(x)) return x;
  const m = 10 ** n;
  const y = x * m;
  const f = Math.floor(y);
  const diff = y - f;
  if (Math.abs(y) < 1e9 && Math.abs(diff - 0.5) > 1e-6) return (diff > 0.5 ? f + 1 : f) / m;
  if (Math.abs(x) >= 1e21 || n > 70) return x;
  const [whole, frac = ""] = Math.abs(x).toFixed(n + 25).split(".");
  const next = frac[n];
  let up = next > "5" || (next === "5" && /[1-9]/.test(frac.slice(n + 1)));
  if (next === "5" && !up) up = Number((whole + frac.slice(0, n)).slice(-1)) % 2 === 1; // an exact tie: to even
  const digits = BigInt(whole + frac.slice(0, n)) + (up ? 1n : 0n);
  return (x < 0 ? -1 : 1) * Number(`${digits}e-${n}`);
}

/** Python's float formatting of a year (1911.0) where a result prints one: JSON keeps numbers as numbers. */
export const asFloat = (x) => (x === null || x === undefined ? null : Number(x));
