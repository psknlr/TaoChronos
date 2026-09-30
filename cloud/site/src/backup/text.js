// The text as the corpus's tools read it: the normaliser (plugins/classics/domain.py, VariantTable), the index's form of
// a text (taochronos.chat.d1.fts_form), the periods and the expressions of time (domain.Periods), and Python's own ways
// with numbers where a result shows them.  The tables are generated from the checkout (tables.js): the databases were
// normalised with the same ones (tables.NORMALIZER is checked against the databases' own).

import { CHAR_MAP, CURATED, DYNASTIES, EXPRESSIONS, PERIODS, SCRIPT, WORDS } from "./tables.js";

export const BREAK = "zx"; // the index's token for ASCII punctuation, spaces and control characters
const ALNUM = /^[A-Za-z0-9]$/;

const normalized = new Map(); // short texts normalised in this isolate (queries, surfaces, cues)

/** VariantTable.normalize_text: the character map (curated variants, then script conversion), then the word variants. */
export function normalize(text) {
  const s = String(text ?? "");
  const hit = normalized.get(s);
  if (hit !== undefined) return hit;
  let out = "";
  for (const ch of s) out += CHAR_MAP[ch] ?? ch;
  for (const [from, to] of WORDS) if (out.includes(from)) out = out.split(from).join(to);
  if (s.length <= 64) {
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
/** round(x, n) as Python rounds: the nearest, ties to even (on the value as stored). */
export function pyRound(x, n = 0) {
  if (x === null || x === undefined || !Number.isFinite(x)) return x;
  const m = 10 ** n;
  const y = x * m;
  const f = Math.floor(y);
  const diff = y - f;
  let r;
  if (diff > 0.5) r = f + 1;
  else if (diff < 0.5) r = f;
  else r = f % 2 === 0 ? f : f + 1;
  return r / m;
}

/** Python's float formatting of a year (1911.0) where a result prints one: JSON keeps numbers as numbers. */
export const asFloat = (x) => (x === null || x === undefined ? null : Number(x));
