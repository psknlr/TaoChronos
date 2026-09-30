// The tools a Worker cannot compute in 10 ms — a formula's history across the corpus, a drug's properties work by work,
// a term's use by period, the commentaries on a clause … — served from their results, computed ahead of time on the
// full corpus by the Python tools themselves (taochronos.chat.d1results) and imported with it: `results` in database 0,
// "<tool>\t<key>" → the tool's result, gzip-compressed and base64-encoded.  A key is what the result depends on: the
// canonical name of a formula, a drug or a term (as the study layer resolves it: the lexicon, then the normalised
// name), a book, a clause's characters.  What was not precomputed is said, never guessed.

import { Lexicon } from "./lexicon.js";
import { CANON } from "./tables.js";
import { normalize } from "./text.js";
import { ToolError } from "./tools.js";

/** The lexicon's canonical term for a name (StudyBase.surfaces: the name, else its normalised form), else the name. */
async function canonical(lex, name, category = null) {
  const s = String(name ?? "").trim();
  if (!s) return "";
  await lex.loadIds([s, normalize(s)]);
  const e = lex.resolve(s, category) || lex.resolve(normalize(s), category);
  return e ? e.term : normalize(s);
}

const STUDY_HAN = /[㐀-鿿\u{20000}-\u{2ffff}〓□]/u; // study/base.py, HAN

/** A clause as the concordance reads it: its Han characters, normalised, at most 400 (concordance.run, han_only). */
export function clauseKey(text) {
  return [...normalize(String(text ?? ""))].filter((c) => STUDY_HAN.test(c)).slice(0, 400).join("");
}

const WORKS = new Map(CANON.works.flatMap((w) => [[w.work, w.work], [w.title, w.work]]));

/** tool → (lexicon, arguments, corpus) → [key, arguments the result does not depend on or was computed without]. */
export const KEYS = {
  "study.formula": async (lex, a) => [await canonical(lex, a.name, "formula"), ["other_names"]],
  "study.herb": async (lex, a) => [await canonical(lex, a.name, "herb"), []],
  "study.term": async (lex, a) => [await canonical(lex, a.term), ["sample_per_period"]],
  "study.names": async (lex, a) => [await canonical(lex, a.term), []],
  "study.reading": async (lex, a) => [await canonical(lex, a.topic), []],
  "study.senses": async (lex, a) => [String(a.term ?? "").trim(), ["per_period"]],
  "study.network": async (lex, a) => [a.target ? await networkKey(lex, a.target) : "", []],
  "study.pairs": async (lex, a) => [a.herb ? await canonical(lex, a.herb, "herb") : "", ["period"]],
  "study.taboo": async (lex, a) => [String(a.book_id ?? ""), ["min_chars"]],
  "study.citations": async (lex, a) => [String(a.target ?? "").trim(), ["top"]],
  "study.schools": async (lex, a) => [String(a.school ?? "").trim(), ["probes"]],
  "study.witnesses": async (lex, a) => [WORKS.get(String(a.work ?? "").trim()) || String(a.work ?? "").trim(), []],
  "study.commentaries": async (lex, a, corpus) => [clauseKey(await clauseText(corpus, a)), []],
  "study.concordance": async (lex, a, corpus) => [clauseKey(await clauseText(corpus, a)), ["min_coverage", "limit"]],
  "kg.claims": async (lex, a) => [await claimsKey(lex, a), ["limit"]],
  "kg.neighbors": async (lex, a) => [await termId(lex, a.term), ["k"]],
};

async function networkKey(lex, target) {
  const s = String(target).trim();
  await lex.loadIds([s, normalize(s)]);
  const e = lex.resolve(s, "formula") || lex.resolve(normalize(s), "formula") || lex.resolve(s) || lex.resolve(normalize(s));
  return e ? e.term : normalize(s);
}

async function termId(lex, term) {
  const s = String(term ?? "").trim();
  if (s.includes(":")) return s;
  await lex.loadIds([s]);
  return lex.canonical(s) || s;
}

/** kg.claims is precomputed for one term, over all periods and relations (the question a conversation asks). */
async function claimsKey(lex, a) {
  const terms = Array.isArray(a.terms) ? a.terms : [];
  if (terms.length !== 1 || a.relation || a.after !== undefined || a.before !== undefined) return null;
  return termId(lex, terms[0]);
}

async function clauseText(corpus, a) {
  if (a.text) return a.text;
  if (a.passage_id) {
    const hit = await corpus.passage(a.passage_id);
    if (!hit) throw new ToolError("KeyError", `'${a.passage_id}'`);
    return hit.p.t;
  }
  return "";
}

async function inflate(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text());
}

/** The precomputed result of a call, or a ToolError saying why there is none. */
export async function precomputed(corpus, tool, a) {
  const lex = new Lexicon(corpus);
  const [key, ignored] = await KEYS[tool](lex, a, corpus);
  if (key === null) {
    throw new ToolError("NotPrecomputed", "备份服务只预先计算了单个术语、不限关系与年代的 kg.claims；请只给一个术语，或改用 classics.search 检索原文");
  }
  const row = await corpus.first(0, "SELECT v FROM results WHERE k = ?", [`${tool}\t${key}`]);
  if (!row) {
    throw new ToolError("NotPrecomputed", `备份服务（本站全量语料的 D1 备份）预先计算了常见条目的 ${tool} 结果，未收“${key || "（空）"}”：` +
      "可换用其通行名称，或用 classics.search / classics.get_passage 检索原文。全量语料的完整服务恢复后即可直接计算。");
  }
  const result = await inflate(row.v);
  const differs = ignored.filter((k) => a[k] !== undefined && a[k] !== null && a[k] !== "");
  if (differs.length && result && typeof result === "object" && !Array.isArray(result)) {
    result._backup = `预先计算的结果（以默认参数计算，未按 ${differs.join("、")} 调整）`;
  }
  return result;
}
