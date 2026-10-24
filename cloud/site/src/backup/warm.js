// The backup's code run once over made-up data when the isolate starts, before any request: on the Workers Free plan a
// request may use 10 ms of CPU, and the request that first runs this code pays for compiling it (a first search took
// 10–16 ms, measured, where the next take 2–5; after this run 4–10).  The start of an isolate has its own, far larger
// allowance.  The made-up databases answer the statements the tools send from memory (no D1, no I/O: the promises
// settle at once), and the run keeps what it reads in a cache of its own, never the isolate's: a request always reads
// the real corpus.  The tests check that it goes through every step (candidates, passages, fusion, cards, quotations).

import { Corpus } from "./corpus.js";
import { shape } from "./results.js";
import { search } from "./search.js";
import { ftsForm, normalize, normalizeWithRecords, parseConstraint, pyRound } from "./text.js";
import { getPassage, verifyQuote } from "./tools.js";

const TEXT = "太陽病，頭痛發熱，汗出惡風者，桂枝湯主之。消渴，小便反多，腎氣丸主之。桂枝三兩（去皮）芍藥三兩　甘草二兩（炙）";
const PER_CHUNK = 8;
const STATS = { version: "warm", schema: 1, books: 1, passages: 64, characters: 4000, by_period: {}, chunks: 8, databases: 2,
  ranges: [[1, 4], [5, 8]], years: [[209, 1], [650, 3], [1100, 5], [1600, 7]], null_years_from: null,
  canon: { listed: 1, held: 1 }, normalizer: "", sources: {}, precomputed: {} };
const CARD = { title: "伤寒论", dynasty: "东汉", composition: [200, 219], dating_basis: "composition", passages: 64, span: 64,
  quality: 0.8, category: "伤寒" };
const BUCKETS = {
  桂: { 桂枝汤: [{ id: "formula:桂枝汤", term: "桂枝汤", cat: "formula", aliases: ["桂枝湯"] }] },
  消: { 消渴: [{ id: "disease:消渴", term: "消渴", cat: "disease", related: ["三消"] }] },
  三: { 三消: [{ id: "disease:三消", term: "三消", cat: "disease" }] },
  湿: { 湿热: [{ id: "pathogen:湿热", term: "湿热", cat: "pathogen", components: ["湿", "热"] }],
    湿: [{ id: "pathogen:湿", term: "湿", cat: "pathogen", weak: true }] },
  热: { 热: [{ id: "pathogen:热", term: "热", cat: "pathogen", weak: true }] },
};

const passage = (cid, i) => ({ t: `${TEXT}${i}`, q: (cid - 1) * PER_CHUNK + i, l: 0 });
const chunk = (cid) => ({ T: { dynasty: "东汉", t_composition: [200, 219] }, L: [["卷上", "辨太阳病脉证并治"]], Y: [] });
const yearOf = (cid) => 209 + 180 * (cid - 1);

/** What a statement of the tools gets back from the made-up databases (by what it asks for). */
function answer(sql, params) {
  if (sql.includes("FROM meta WHERE k IN ('stats', 'complete')")) return [{ k: "stats", v: JSON.stringify(STATS) }, { k: "complete", v: "warm" }];
  if (sql.includes("FROM lex WHERE")) return JSON.parse(params[0]).filter((c) => BUCKETS[c]).map((c) => ({ k: c, v: JSON.stringify(BUCKETS[c]) }));
  if (sql.includes("SELECT 'r' AS t, cid, r FROM (SELECT rowid AS cid, rank AS r FROM fts")) { // the candidates' query
    const [, lo, hi] = params;
    const out = [];
    for (let cid = lo; cid <= hi; cid++) out.push({ t: ["r", "a0", "r", "d0", "h0"][cid % 5], cid, r: -cid / 10 });
    return out;
  }
  if (sql.startsWith("WITH m AS MATERIALIZED")) {
    const out = [];
    for (const cid of JSON.parse(params[0])) {
      for (let i = 0; i < PER_CHUNK; i++) {
        out.push([cid, i, "warm", yearOf(cid), (cid - 1) * PER_CHUNK + i, null, 40 + i, 1 + (i % 2) * 2, `${i % 3},${i % 2},1`,
          i % 3 ? "" : "1,1,1,0,0,1,1,0", i % 3]);
      }
    }
    return out;
  }
  if (sql.startsWith("SELECT map FROM books")) return [{ map: JSON.stringify({ C: [[[0, 1], [8, 2], [16, 3], [24, 4]]] }) }];
  if (sql.includes("json_extract(c.body, '$.p[' || (j.value ->> 1) || ']')")) {
    return JSON.parse(params[0]).map(([cid, i]) => ({ cid, i, book: "warm", year: yearOf(cid), p: JSON.stringify(passage(cid, i)),
      T: JSON.stringify(chunk(cid).T), L: JSON.stringify(chunk(cid).L), Y: JSON.stringify(chunk(cid).Y) }));
  }
  if (sql.startsWith("SELECT id, card, map FROM books")) {
    return [{ id: "warm", card: JSON.stringify(CARD), map: JSON.stringify({ C: [[[0, 1], [8, 2], [16, 3], [24, 4]]] }) }];
  }
  if (sql.includes("FROM books WHERE id IN")) return [{ id: "warm", card: JSON.stringify(CARD) }];
  if (sql.startsWith("WITH RECURSIVE")) {
    const out = [];
    for (let cid = params[0]; cid <= params[1]; cid++) {
      out.push({ n: 0, cid, i: cid % PER_CHUNK, book: "warm", year: yearOf(cid), q: cid * PER_CHUNK, m: null, v: cid % 2 ? 0 : 3, w: 5, k: 2,
        t: cid % 3 ? null : TEXT });
    }
    return out;
  }
  return [];
}

const statement = (sql, params = []) => ({
  bind: (...p) => statement(sql, p),
  all: async () => ({ results: answer(sql, params), success: true, meta: {} }),
  first: async () => answer(sql, params)[0] ?? null,
  raw: async () => answer(sql, params).map((r) => (Array.isArray(r) ? r : Object.values(r))),
  sql,
  params,
});
const database = { prepare: (sql) => statement(sql), batch: async (list) => list.map((s) => ({ results: answer(s.sql, s.params), meta: {} })) };
/** The made-up databases, as bindings (the tests check that the warm-up really runs the tools through them). */
export const ENV = { D1_0: database, D1_1: database };

export async function warmUp() {
  const cache = { kept: null }; // its own: never the isolate's
  for (let r = 0; r < 3; r++) {
    const norm = normalize(`${TEXT}${r}`);
    ftsForm(norm);
    normalizeWithRecords(TEXT);
    parseConstraint(`宋代以前${r}`);
    pyRound(55.349999, 1);
    for (const [query, extra] of [["桂枝汤", {}], ["消渴的认识如何演变", {}], ["宋代以前的消渴", {}], ["三消最早见于哪部书", { after: 200 }],
      ["湿热与消渴", {}], ["桂枝汤", { books: ["warm"] }]]) {
      const res = await search(new Corpus(ENV, { cache }), { query, k: 10, ...extra });
      shape("classics.search", true, res, null, { durationMs: 1, maxChars: 16000 });
    }
    await verifyQuote(new Corpus(ENV, { cache }), { quote: "桂枝湯主之" });
    await getPassage(new Corpus(ENV, { cache }), { passage_id: "warm.00009" });
  }
}
