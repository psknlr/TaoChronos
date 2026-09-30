// The D1 backup (cloud/site/src/backup; docs/adr/0017-d1-backup.md) against a small D1 made by the exporter itself:
// `python -m taochronos.chat.d1 fixture cloud/.d1-fixture` (ten books of the committed 要籍 pack over four databases,
// seven precomputed results), read through a D1-compatible adapter over node:sqlite.  The API answers in the shapes of
// the Python server; each call stays within a Worker's limits (its CPU time here, the SQL apart; ≤ 50 D1 statements).

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { handle } from "../site/src/site.js";
import { call as backupCall, classification } from "../site/src/backup/api.js";
import { CATALOG } from "../site/src/backup/tables.js";
import { Corpus } from "../site/src/backup/corpus.js";
import { clauseKey } from "../site/src/backup/precomputed.js";
import { ftsForm, normalize, normalizeWithRecords, parseConstraint } from "../site/src/backup/text.js";
import { collate } from "../site/src/backup/difflib.js";
import { warmUp } from "../site/src/backup/warm.js";
import { compoundTerms, D1Adapter, workerCpu } from "./d1-adapter.js";
import { unionAll } from "../site/src/backup/search.js";
import { DatabaseSync } from "node:sqlite";

const here = dirname(fileURLToPath(import.meta.url));
const dir = resolve(process.env.D1_FIXTURE || `${here}/../.d1-fixture`);
const present = existsSync(`${dir}/fixture.json`);
if (!present && process.env.REQUIRE_D1_FIXTURE) throw new Error(`no D1 fixture at ${dir}: python -m taochronos.chat.d1 fixture ${dir}`);
const skip = present ? false : `no D1 fixture at ${dir} (python -m taochronos.chat.d1 fixture ${dir})`;

const fixture = present ? JSON.parse(readFileSync(`${dir}/fixture.json`, "utf8")) : null;
const dbs = [];
const env = { ALLOWED_ORIGINS: "https://chat.impf.ai" };
if (present) {
  for (let k = 0; existsSync(`${dir}/db-${k}.sqlite`); k++) {
    const d = new D1Adapter(`${dir}/db-${k}.sqlite`, { readOnly: true });
    dbs.push(d);
    env[`D1_${k}`] = d;
  }
  env.D1_BACKUP = fixture.report.version;
  env.ASSETS = { fetch: async () => new Response("<html>道乃久</html>", { headers: { "Content-Type": "text/html" } }) };
}

const LIMIT_MS = Number(process.env.CPU_LIMIT_MS || 25); // generous for shared CI machines: the budget measured is 10 ms
const site = (path, init = {}) => handle(new Request(`https://chat.impf.ai${path}`, init), env, {});
const post = (path, body) => site(path, { method: "POST", headers: { "Content-Type": "application/json", Origin: "https://chat.impf.ai" }, body: JSON.stringify(body) });

/** A call through the backup's API, with the Worker's CPU (SQL excluded) and its D1 statements. */
async function measured(name, args) {
  const corpus = new Corpus(env);
  const { value, ms } = await workerCpu(dbs, async () => {
    const pre = new Set(Object.keys((await corpus.stats()).precomputed || {}));
    return backupCall(corpus, name, args, 16000, pre);
  });
  return { out: value, ms, queries: corpus.queries };
}

async function callTool(name, args) {
  const res = await post("/api/call", { name, arguments: args, max_chars: 16000 });
  assert.equal(res.status, 200);
  return res.json();
}

// ------------------------------------------------------------------ the endpoints
test("info: the full corpus as the backup, with its own label and the tools it serves", { skip }, async () => {
  const res = await site("/api/info");
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("X-TC-Corpus"), "d1");
  const info = await res.json();
  assert.equal(info.name, "TaoChronos"); // the page's probe (runtime.js) asks for this name
  assert.equal(info.runtime, "d1");
  assert.equal(info.proxy, false);
  assert.equal(info.corpus.kind, "full");
  assert.equal(info.corpus.label, "全量语料（备份）");
  assert.equal(info.corpus.demo, false);
  assert.equal(info.corpus.books, 10);
  assert.equal(info.corpus.passages, fixture.summary.passages);
  assert.ok(info.system_prompt.includes(`当前语料：全量语料（10 部书、${fixture.summary.passages} 段）`));
  assert.ok(info.system_prompt.includes("## 本站备份服务"));
  assert.ok(!info.system_prompt.includes("{books}"));
  const cat = await (await site("/api/catalog?mode=all")).json();
  assert.equal(info.tools.offered, cat.tools.length);
  assert.ok(info.backup.precomputed["study.formula"] >= 1);
});

test("catalog: only the tools served — core with the two meta-tools, never the research engine", { skip }, async () => {
  const core = await (await site("/api/catalog?mode=core")).json();
  const names = core.tools.map((t) => t.tool);
  for (const t of ["classics.search", "classics.get_passage", "validation.verify_quote", "study.formula", "taochronos_catalog", "taochronos_call"]) {
    assert.ok(names.includes(t), t);
  }
  for (const t of ["taochronos_research", "taochronos_session", "taochronos_ask", "study.translate", "audit.claim"]) assert.ok(!names.includes(t), t);
  const all = await (await site("/api/catalog?mode=all")).json();
  assert.ok(all.tools.every((t) => t.name === t.tool.replaceAll(".", "__") && t.parameters.type === "object"));
  assert.ok(!all.tools.some((t) => t.tool === "study.pairs"), "a precomputed tool without results is not offered");
  assert.equal(Object.values(all.families).reduce((a, f) => a + f.count, 0), all.tools.length);
});

test("the start's warm-up runs the tools over made-up databases and leaves the isolate's cache alone", { skip }, async () => {
  await site("/api/info"); // the real corpus kept
  await warmUp(); // over made-up databases (one book), with its own cache
  const info = await (await site("/api/info")).json();
  assert.equal(info.corpus.books, 10);
  assert.equal(info.corpus.passages, fixture.summary.passages);
});

test("D1's own limits (five terms a compound SELECT, found in the emulator): the adapter holds the tools to them", () => {
  const parts = Array.from({ length: 23 }, (_, i) => `SELECT ${i} AS x FROM (SELECT 1 UNION ALL SELECT 2)`);
  assert.equal(compoundTerms(parts.join(" UNION ALL ")), 23);
  assert.equal(compoundTerms("SELECT 'a UNION b UNION c UNION d UNION e UNION f'"), 1);
  const nested = unionAll(parts);
  assert.ok(compoundTerms(nested) <= 5);
  const db = new DatabaseSync(":memory:");
  assert.equal(db.prepare(`SELECT count(*) AS n FROM (${nested})`).get().n, 46); // two rows a part
  assert.equal(db.prepare(`SELECT sum(x) AS s FROM (${nested})`).get().s, 22 * 23); // every part, in any order
});

test("every tool of the server's catalog (74) is live, precomputed, or unavailable with its reason — once", () => {
  const { live, precomputed, unavailable } = classification();
  const every = [...CATALOG.tools.map((t) => t.tool), ...CATALOG.engine.map((e) => e.name)];
  const classed = [...live, ...precomputed, ...Object.keys(unavailable)];
  assert.equal(every.length, 74);
  assert.deepEqual([...classed].sort(), [...every].sort());
  assert.equal(new Set(classed).size, classed.length);
  assert.deepEqual([live.length, precomputed.length, Object.keys(unavailable).length], [14, 16, 44]);
  assert.ok(Object.values(unavailable).every((why) => why.length > 10));
});

test("passage: a passage in full (the page checks quotations against it); an unknown id says so", { skip }, async () => {
  const known = "cm_shanghan_npm.00279";
  const p = await (await site(`/api/passage?id=${known}`)).json();
  assert.equal(p.ok, true);
  assert.equal(p.passage_id, known);
  assert.equal(p.book_id, "cm_shanghan_npm");
  assert.ok(p.text.length > 0 && p.title && "temporal" in p && Array.isArray(p.variants));
  const bad = await (await site("/api/passage?id=cm_shanghan_npm.99999")).json();
  assert.deepEqual([bad.ok, bad.error], [false, "KeyError: 'cm_shanghan_npm.99999'"]);
  const kanripo = await callTool("classics.list_books", { query: "素问" });
  assert.ok(kanripo.result.some((b) => b.book_id === "suwen_wangbing"));
});

test("research and sessions need the server: the page is told why, without leaving the site's server", { skip }, async () => {
  const res = await post("/api/research", { question: "消渴" });
  assert.equal(res.status, 501); // not 502/503/504: the page does not fall back to the browser for it
  assert.match((await res.json()).error, /多智能体研究/);
  const out = await callTool("taochronos_research", { question: "消渴" });
  assert.equal(out.ok, false);
  assert.match(out.error, /备份服务/);
});

test("without the import complete (or with another version) the site says 503, and the page runs the browser corpus", { skip }, async () => {
  const saved = env.D1_BACKUP;
  env.D1_BACKUP = "another-version";
  try {
    const res = await site("/api/info");
    assert.equal(res.status, 503);
    assert.equal((await res.json()).corpus, "none");
  } finally {
    env.D1_BACKUP = saved;
  }
  const { D1_BACKUP, ...without } = env; // eslint-disable-line no-unused-vars
  const res = await handle(new Request("https://chat.impf.ai/api/info"), without, {});
  assert.equal(res.status, 503);
});

// ------------------------------------------------------------------ the live tools
test("classics.search: the passages that write the query, fused as the server fuses them, with their cards", { skip }, async () => {
  const { out, ms, queries } = await measured("classics.search", { query: "桂枝汤", k: 5 });
  assert.equal(out.ok, true);
  assert.deepEqual(out.result.query.terms, ["formula:桂枝汤"]);
  assert.deepEqual(out.result.query.variants, { 桂枝汤: ["桂枝湯"] });
  assert.equal(out.result.hits.length, 5);
  for (const h of out.result.hits) {
    assert.deepEqual(h.matched, ["桂枝汤"]);
    assert.ok(normalize(h.text).includes("桂枝汤") || h.text.endsWith("…"));
    assert.ok(h.routes.every((r) => ["bm25", "temporal", "variant", "sense"].includes(r)));
    assert.ok(h.passage_id && h.title && h.period !== undefined && typeof h.score === "number");
  }
  assert.ok(out.citations.length === 5 && out.summary === "5 条命中");
  assert.ok(queries <= 50, `${queries} D1 statements`);
  assert.ok(ms < LIMIT_MS, `${ms.toFixed(1)} ms`);
});

test("classics.search: a time bound from the question or the arguments; origins sorted by date", { skip }, async () => {
  const before = await callTool("classics.search", { query: "消渴", before: 1000, k: 10 });
  assert.equal(before.ok, true);
  assert.equal(before.result.query.before, 1000);
  assert.ok(before.result.hits.length > 0);
  for (const h of before.result.hits) assert.ok(h.year < 1000, `${h.passage_id} ${h.year}`);
  const worded = await callTool("classics.search", { query: "宋代以前的消渴", k: 5 });
  assert.equal(worded.result.query.before, 960);
  for (const h of worded.result.hits) assert.ok(h.year < 960);
  const origin = await callTool("classics.search", { query: "人参最早见于哪部书", k: 5 });
  assert.equal(origin.result.query.intent, "earliest");
  const years = origin.result.hits.map((h) => h.year);
  assert.deepEqual(years, [...years].sort((a, b) => a - b));
  const books = await callTool("classics.search", { query: "人参", books: ["hejiju_fang"], k: 5 });
  assert.ok(books.result.hits.length > 0 && books.result.hits.every((h) => h.book_id === "hejiju_fang"));
});

test("classics.get_passage, list_books and canon, as the server gives them", { skip }, async () => {
  const p = await callTool("classics.get_passage", { passage_id: "suwen_wangbing.000.00001" });
  assert.equal(p.ok, true, p.error);
  assert.equal(p.result.passage_id, "suwen_wangbing.000.00001");
  assert.deepEqual(Object.keys(p.result), ["passage_id", "book_id", "title", "dynasty", "year", "period", "locator", "text", "variants",
    "collation_status", "notes", "temporal"]);
  const missing = await callTool("classics.get_passage", { passage_id: "nothing.00001" });
  assert.deepEqual([missing.ok, missing.error], [false, "KeyError: 'nothing.00001'"]);
  const invalid = await callTool("classics.get_passage", {});
  assert.equal(invalid.error, "invalid arguments: $: missing required property 'passage_id'");
  const books = await callTool("classics.list_books", {});
  assert.equal(books.result.length, 10);
  const sorted = books.result.map((b) => [b.composition || "", b.book_id]);
  assert.deepEqual(sorted, [...sorted].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1)));
  const dyn = await callTool("classics.list_books", { dynasty: "清" });
  assert.ok(dyn.result.length > 0 && dyn.result.every((b) => b.dynasty.includes("清")));
  const canon = await callTool("classics.canon", { limit: 5 });
  assert.equal(canon.result.listed, 350);
  assert.equal(canon.result.works.length, 5);
  assert.equal(canon.result.works[0].in_this_corpus, true); // 素问
  const held = await callTool("classics.canon", { held: true, limit: 0 });
  assert.equal(held.result.works.length, held.result.held_here);
});

test("kg.term, philology.normalize, assess_passage, collate and inspect_page", { skip }, async () => {
  const term = await callTool("kg.term", { surface: "消渴" });
  assert.equal(term.result.lexicon[0].term_id, "disease:消渴");
  assert.equal(term.result.senses.length, 3);
  assert.ok(term.result.notes.includes("糖尿病"));
  const norm = await callTool("philology.normalize", { text: "桂枝湯主之，黃耆" });
  assert.equal(norm.result.normalized, "桂枝汤主之，黄芪");
  assert.deepEqual(norm.result.normalizations[0], { start: 2, end: 3, from: "湯", to: "汤", kind: "variant_char" });
  const assess = await callTool("philology.assess_passage", { passage_id: "cm_shanghan_npm.00279" });
  assert.equal(assess.result.passage_id, "cm_shanghan_npm.00279");
  assert.equal(assess.result.collation_status, "unverified");
  assert.deepEqual(assess.result.notes, ["manual transcription (no OCR layer)", "not collated against a specific edition"]);
  assert.deepEqual(collate("太阳之为病", "太陽之為病也"), [
    { op: "replace", a: "阳", b: "陽", a_span: [1, 2], b_span: [1, 2] },
    { op: "replace", a: "为", b: "為", a_span: [3, 4], b_span: [3, 4] },
    { op: "insert", a: "", b: "也", a_span: [5, 5], b_span: [5, 6] }]);
  const chain = await callTool("philology.inspect_page", { object_id: "suwen_wangbing.000.00001" });
  assert.deepEqual(chain.result.map((x) => x.level), ["Passage", "Book", "Edition", "Volume", "Chapter", "Section", "Page", "Line", "Region", "Image"]);
  assert.equal((await callTool("validation.provenance_chain", { object_id: "nothing" })).result.length, 0);
});

test("validation.verify_quote: verbatim, after normalisation, or without the punctuation — never a changed character", { skip }, async () => {
  const { out, ms, queries } = await measured("validation.verify_quote", { quote: "太阳之为病，脉浮，头项强痛而恶寒" });
  assert.equal(out.ok, true);
  assert.ok(out.result.length >= 1, JSON.stringify(out.result));
  const first = out.result[0];
  const p = await callTool("classics.get_passage", { passage_id: first.passage_id });
  const span = [...p.result.text].slice(first.start, first.end).join("");
  assert.equal(normalize(span).replace(/[，。、]/g, ""), "太阳之为病脉浮头项强痛而恶寒");
  assert.ok(queries <= 50 && ms < LIMIT_MS, `${queries} statements, ${ms.toFixed(1)} ms`);
  const wrong = await callTool("validation.verify_quote", { quote: "太阳之为病，脉沉，头项强痛而恶寒" });
  assert.deepEqual(wrong.result, []);
});

test("study.metrology, modern.safety and literature.modern_evidence", { skip }, async () => {
  const dose = await callTool("study.metrology", { dose: "三两", year: 200 });
  assert.deepEqual(dose.result.parsed, [{ value: 3, unit: "两", kind: "weight" }]);
  assert.equal(dose.result.reading.text, "约41.4–46.8克（秦汉制）");
  const safety = await callTool("modern.safety", { text: "附子一枚，生用" });
  assert.equal(safety.result[0].material, "附子");
  const ev = await callTool("literature.modern_evidence", { term: "青蒿" });
  assert.ok(ev.result.length >= 1);
});

// ------------------------------------------------------------------ precomputed tools, meta-tools
test("precomputed: the Python tool's own result, by the canonical name; what was not computed is said", { skip }, async () => {
  const formula = await callTool("study.formula", { name: "桂枝汤" });
  assert.equal(formula.ok, true, formula.error);
  const traditional = await callTool("study.formula", { name: "桂枝湯" });
  assert.deepEqual(traditional.result, formula.result);
  const missing = await callTool("study.formula", { name: "不存在汤" });
  assert.equal(missing.ok, false);
  assert.match(missing.error, /未收/);
  const clause = await callTool("study.commentaries", { text: "太陽之為病，脈浮，頭項強痛而惡寒。" });
  assert.equal(clause.ok, true, clause.error);
  assert.equal(clauseKey("太陽之為病，脈浮，頭項強痛而惡寒。"), clauseKey(fixture.clause));
  const claims = await callTool("kg.claims", { terms: ["消渴"] });
  assert.equal(claims.ok, true, claims.error);
  const filtered = await callTool("kg.claims", { terms: ["消渴"], relation: "indicated_for" });
  assert.equal(filtered.ok, false);
});

test("taochronos_call and taochronos_catalog; an unknown tool; a model's name for a tool", { skip }, async () => {
  const via = await callTool("taochronos_call", { tool: "classics.get_passage", arguments: { passage_id: "cm_shanghan_npm.00279" } });
  assert.equal(via.ok, true);
  assert.equal(via.via, "taochronos_call");
  const modelName = await callTool("classics__get_passage", { passage_id: "cm_shanghan_npm.00279" });
  assert.equal(modelName.tool, "classics.get_passage");
  const cat = await callTool("taochronos_catalog", { query: "配伍" });
  assert.ok("families" in cat.result && Array.isArray(cat.result.matched));
  const unknown = await callTool("nothing.here", {});
  assert.equal(unknown.error, "unknown tool 'nothing.here'; use taochronos_catalog to see what exists");
});

// ------------------------------------------------------------------ the text as the index reads it
test("the normaliser and the index form: exactly as the databases were built (Python)", { skip }, () => {
  let n = 0;
  for (const d of dbs) {
    for (const row of d.sqlite.prepare("SELECT body, norm FROM chunks").all()) {
      const body = JSON.parse(row.body);
      const norm = JSON.parse(row.norm);
      body.p.forEach((p, i) => {
        assert.equal(ftsForm(normalize(p.t)), norm[i]);
        n++;
      });
    }
  }
  assert.equal(n, fixture.summary.passages);
  assert.deepEqual(parseConstraint("宋代以前"), [null, 960]);
  assert.deepEqual(parseConstraint("唐以后"), [618, null]);
  assert.equal(normalizeWithRecords("募原").normalized, "膜原");
});

test("parity: the live tools answer as the Python tools answered on the same store (a search: its query analysis)", { skip }, async () => {
  assert.ok(fixture.reference.length >= 30);
  for (const ref of fixture.reference) {
    const { out } = await measured(ref.name, ref.args);
    const label = `${ref.name} ${JSON.stringify(ref.args)}`;
    assert.equal(out.ok, ref.ok, `${label}: ${out.error}`);
    if (!ref.ok) assert.equal(out.error, ref.error, label);
    else if (ref.name === "classics.search") {
      assert.deepEqual(out.result.query, ref.result.query, label);
      assert.equal(out.result.hits.length > 0, ref.result.hits.length > 0, label);
    } else assert.deepEqual(out.result, ref.result, label);
  }
});

test("every live tool within a Worker's limits on the fixture", { skip }, async () => {
  const calls = [["classics.search", { query: "太阳病脉浮头项强痛而恶寒", k: 10 }], ["classics.search", { query: "消渴的认识如何演变", k: 10 }],
    ["classics.get_passage", { passage_id: "suwen_wangbing.000.00001" }], ["classics.list_books", {}], ["classics.canon", {}],
    ["kg.term", { surface: "消渴" }], ["study.formula", { name: "桂枝汤" }], ["study.commentaries", { text: fixture.clause }]];
  for (const [name, args] of calls) {
    await measured(name, args); // warm
    const { out, ms, queries } = await measured(name, args);
    assert.equal(out.ok, true, `${name}: ${out.error}`);
    assert.ok(queries <= 50, `${name}: ${queries} statements`);
    assert.ok(ms < LIMIT_MS, `${name}: ${ms.toFixed(1)} ms`);
  }
});
