// The D1 backup (cloud/site/src/backup; docs/adr/0017-d1-backup.md) against a small D1 made by the exporter itself:
// `python -m taochronos.chat.d1 fixture cloud/.d1-fixture` (ten books of the committed 要籍 pack over five databases,
// seven precomputed results), read through a D1-compatible adapter over node:sqlite.  The API answers in the shapes of
// the Python server; each call stays within a Worker's limits (its CPU time here, the SQL apart; ≤ 50 D1 statements).

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { handle } from "../site/src/site.js";
import { call as backupCall, classification } from "../site/src/backup/api.js";
import { CANON, CATALOG } from "../site/src/backup/tables.js";
import { closestNames, coerce, fitArguments, resolveName, signature } from "../site/src/backup/catalog.js";
import { Corpus, passageCard } from "../site/src/backup/corpus.js";
import { forInterface, forModel } from "../site/src/backup/results.js";
import { clauseKey } from "../site/src/backup/precomputed.js";
import { effective, ftsForm, normalize, normalizeWithRecords, parseConstraint } from "../site/src/backup/text.js";
import { collate } from "../site/src/backup/difflib.js";
import { ENV as MADE_UP, warmUp } from "../site/src/backup/warm.js";
import { analyze, search, SERVED_ROUTES, warming } from "../site/src/backup/search.js";
import { verifyQuote } from "../site/src/backup/tools.js";
import { compoundTerms, D1Adapter, workerCpu } from "./d1-adapter.js";
import { unionAll } from "../site/src/backup/search.js";
import { AliasIndex, aliasIndex, assemble, Cp, gateForm, placeless, round4, unsearched } from "../site/src/backup/aliases.js";
import { Lexicon } from "../site/src/backup/lexicon.js";
import { ALIAS_PARAMS } from "../site/src/backup/tables.js";
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

/** A call through the backup's API, with the Worker's CPU (SQL excluded) and its D1 statements.  A shared runner's
 * one-off pause (a collection, the scheduler) is not the tool's: a call over the limit is timed once more and the better
 * time kept — a tool that is slow is slow both times. */
async function measured(name, args) {
  const once = async () => {
    const corpus = new Corpus(env);
    const { value, ms } = await workerCpu(dbs, async () => {
      const pre = new Set(Object.keys((await corpus.stats()).precomputed || {}));
      return backupCall(corpus, name, args, 16000, pre);
    });
    return { out: value, ms, queries: corpus.queries };
  };
  const first = await once();
  if (first.ms < LIMIT_MS) return first;
  return { ...first, ms: Math.min(first.ms, (await once()).ms) };
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
  // and it does run the tools through: a search over the made-up databases finds, fuses and cites
  for (const [query, extra] of [["消渴的认识如何演变", {}], ["湿热与消渴", {}], ["桂枝汤", { books: ["warm"] }]]) {
    const res = await search(new Corpus(MADE_UP, { cache: { kept: null } }), { query, k: 10, ...extra });
    assert.ok(res.hits.length > 0 && res.hits[0].passage_id.startsWith("warm."), query);
  }
  const quote = await verifyQuote(new Corpus(MADE_UP, { cache: { kept: null } }), { quote: "桂枝湯主之" });
  assert.ok(quote.length > 0);
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

test("every tool of the server's catalog (92) is live, precomputed, or unavailable with its reason — once", () => {
  const { live, precomputed, unavailable } = classification();
  const every = [...CATALOG.tools.map((t) => t.tool), ...CATALOG.engine.map((e) => e.name)];
  const classed = [...live, ...precomputed, ...Object.keys(unavailable)];
  assert.equal(every.length, 92);
  assert.deepEqual([...classed].sort(), [...every].sort());
  assert.equal(new Set(classed).size, classed.length);
  assert.deepEqual([live.length, precomputed.length, Object.keys(unavailable).length], [14, 16, 62]);
  assert.ok(Object.keys(unavailable).filter((t) => t.startsWith("mydata.")).every((t) => unavailable[t].includes("本机"))); // never the site's
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
  // a run the container started is not known here: as a run the page has lost, in the words of either version
  assert.deepEqual(await (await site("/api/research/job_1")).json(), { id: "job_1", state: "unknown", status: "unknown" });
  for (const act of ["cancel", "resume"]) {
    assert.deepEqual(await (await post(`/api/research/job_1/${act}`, {})).json(), { id: "job_1", state: "unknown", status: "unknown" });
  }
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

test("D1 unavailable mid-call (its daily allowance used up) is a 503 the page falls back on; a statement's own error is not", { skip }, async () => {
  const failing = (message) => {
    const out = { ...env };
    for (let k = 0; k < dbs.length; k++) {
      out[`D1_${k}`] = { prepare: (sql) => (sql.includes("fts MATCH") ? { bind: () => ({ all: async () => { throw new Error(message); },
        raw: async () => { throw new Error(message); } }) } : dbs[k].prepare(sql)), batch: (list) => dbs[k].batch(list) };
    }
    return out;
  };
  const request = () => new Request("https://chat.impf.ai/api/call", { method: "POST", headers: { "Content-Type": "application/json",
    Origin: "https://chat.impf.ai" }, body: JSON.stringify({ name: "classics.search", arguments: { query: "桂枝汤" } }) });
  let res = await handle(request(), failing("D1_ERROR: Exceeded maximum daily rows read"), {});
  assert.equal(res.status, 503);
  assert.equal((await res.json()).corpus, "none");
  res = await handle(request(), failing("D1_ERROR: no such column: x: SQLITE_ERROR"), {});
  assert.equal(res.status, 200);
  const out = await res.json();
  assert.equal(out.ok, false);
  assert.match(out.error, /no such column/);
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

// ------------------------------------------------------------------ the alias layer in the search (ADR 0023)
/** The places (1-based) of a result's side queue: passages found under an expansion (route alias) or on an asked drug's
 * other lexicon form (labelled from the lexicon). */
const sidePlaces = (hits) => hits.map((h, i) => (h.routes.includes("alias") || h.via?.some((v) => v.source.includes("词表")) ? i + 1 : 0)).filter(Boolean);

test("classics.search with the alias layer: an alias's drug in the side places, labelled; within a Worker's limits", { skip }, async () => {
  assert.equal(ALIAS_PARAMS.enabled, true); // the full-corpus profile's: the backup searches as the server does
  assert.ok(SERVED_ROUTES.includes("alias"));
  for (const query of ["国老", "鬼督邮是什么药"]) { // an alias, a name of two drugs
    await measured("classics.search", { query, k: 10 }); // warm
    const { out, ms, queries } = await measured("classics.search", { query, k: 10 });
    assert.equal(out.ok, true, out.error);
    assert.ok(queries <= 50, `${query}: ${queries} D1 statements`);
    assert.ok(ms < LIMIT_MS, `${query}: ${ms.toFixed(1)} ms`);
  }
  const { out } = await measured("classics.search", { query: "国老", k: 10 });
  const { query, hits } = out.result;
  assert.deepEqual(query.aliases.expansions.map((e) => [e.surface, e.for, e.direction, e.searched]), [["甘草", "国老", "alias→drug", true]]);
  assert.equal(hits.length, 10); // the fixture writes 国老 nowhere: the side queue fills every place
  for (const h of hits) {
    assert.deepEqual([h.routes, h.matched], [["alias"], ["甘草"]]);
    const [v] = h.via;
    assert.deepEqual([h.via.length, v.surface, v.for, v.referent, v.direction, v.kind, v.status], [1, "甘草", ["国老"], "甘草", "alias→drug", "异名", "open"]);
    assert.ok(v.source.includes("别名录（中醫笈成）") && v.witness, JSON.stringify(v));
    assert.ok(normalize(h.text).includes("甘草"), h.text); // the card shows the name it was found under
  }
  assert.deepEqual(hits.map((h) => h.score), hits.map((_, i) => Math.round(10000 * 1000 * 0.5 / (61 + i)) / 10000));
});

test("a fresh isolate's first drug questions stay within a Worker's limits: the start runs the alias search too", { skip }, async () => {
  // what search.js runs as it loads (warm.js asks no drug): the question read as a drug's, both queues, the labels
  const warm = await warming;
  assert.ok(warm.questions >= 2 && warm.tiers.includes("A") && warm.tiers.includes("B") && warm.side > 0, JSON.stringify(warm));
  // a fresh process for a fresh isolate: the modules loaded and the start's warm-ups run, a first question without the
  // layer (the corpus's statistics and lexicon read, as any first request reads them), then the first drug question of
  // each kind — an alias whose drug needs its context, a drug with blockers, an origin question
  const url = (p) => JSON.stringify(pathToFileURL(resolve(here, p)).href);
  const script = [`import { D1Adapter, workerCpu } from ${url("d1-adapter.js")};`, `import { Corpus } from ${url("../site/src/backup/corpus.js")};`,
    `import { search, warming } from ${url("../site/src/backup/search.js")};`, `import { warmUp } from ${url("../site/src/backup/warm.js")};`,
    "await warming; await warmUp();",
    `const dbs = ${JSON.stringify(dbs.map((_, k) => `${dir}/db-${k}.sqlite`))}.map((f) => new D1Adapter(f, { readOnly: true }));`,
    "const env = Object.fromEntries(dbs.map((d, k) => [`D1_${k}`, d]));",
    "await search(new Corpus(env), { query: '消渴', aliases: 'off' });", "const out = [];",
    "for (const query of ['将军', '甘草', '人参最早见于哪部书']) out.push([query, (await workerCpu(dbs, () => search(new Corpus(env), { query }))).ms]);",
    "console.log(JSON.stringify(out));"].join("\n");
  const first = () => {
    const run = spawnSync(process.execPath, ["--no-warnings", "--input-type=module", "-e", script], { encoding: "utf8" });
    assert.equal(run.status, 0, run.stderr);
    return JSON.parse(run.stdout);
  };
  let times = first();
  if (times.some(([, ms]) => ms >= LIMIT_MS)) times = first().map(([q, ms], i) => [q, Math.min(ms, times[i][1])]); // a shared runner's pause
  for (const [query, ms] of times) assert.ok(ms < LIMIT_MS, `${query}, first: ${ms.toFixed(1)} ms`);
});

test("classics.search with the alias layer: a long question within a Worker's limits — the question's gate form indexed once", { skip }, async () => {
  // the gates read the whole question once per name and per blocker: indexed afresh at each read, a question with a
  // character above U+FFFF (㑮 normalises to one) rebuilt its code-point tables each time, quadratic in its length
  const index = aliasIndex();
  const lex = new Lexicon(new Corpus(env));
  for (const query of ["㑮人言可畏", "大黄将军", "红豆"]) {
    const whole = gateForm(normalize(query));
    const read = [];
    const spy = Object.create(index);
    for (const m of ["covers", "drugContext", "freeOffsets", "named"]) {
      spy[m] = function (g, ...rest) {
        if ((g instanceof Cp ? g.text : g) === whole) read.push(g);
        return index[m].call(this, g, ...rest);
      };
    }
    await analyze(lex, query, { aliases: true, cfg: ALIAS_PARAMS, index: spy });
    assert.ok(read.length > 0, query);
    assert.ok(read.every((g) => g instanceof Cp), `${query}: the question's gate form read as a string`);
    assert.equal(new Set(read).size, 1, query);
  }
  // as long as the layer reads (ALIAS_MAX_CHARS, 200 code points), the reading within a Worker's limits
  for (const query of ["㑮" + "人言".repeat(99) + "人", "人言𠀀".repeat(66) + "人言"]) {
    assert.equal([...normalize(query)].length, 200);
    await measured("classics.search", { query, k: 10 }); // warm
    const { out, ms, queries } = await measured("classics.search", { query, k: 10 });
    assert.equal(out.ok, true, out.error);
    assert.ok(queries <= 50, `${queries} D1 statements`);
    assert.ok(ms < LIMIT_MS, `${[...query].length} characters: ${ms.toFixed(1)} ms`);
  }
});

test("classics.search with the alias layer: a question longer than the layer reads (a prescription pasted in) is read without it, as today, within a Worker's limits", { skip }, async () => {
  // read name by name, 400 characters of names took more than a request's 10 ms; past ALIAS_MAX_CHARS (200 code
  // points of the normalised question, as hybrid.py counts) nothing is asked, expanded or labelled, the hits today's
  const unit = "国老二两，将军三两，桂枝三两，人言少许，";
  const question = (n) => [...unit.repeat(Math.ceil(n / [...unit].length))].slice(0, n).join("");
  const at = await measured("classics.search", { query: question(200), k: 10 });
  assert.ok(at.out.result.query.aliases?.expansions.some((e) => e.surface === "甘草" && e.for === "国老"), "read at 200");
  for (const n of [201, 400, 800, 1200]) {
    const query = question(n);
    assert.equal([...normalize(query)].length, n);
    await measured("classics.search", { query, k: 10 }); // warm
    const { out, ms, queries } = await measured("classics.search", { query, k: 10 });
    assert.equal(out.ok, true, out.error);
    assert.ok(queries <= 50, `${n} characters: ${queries} D1 statements`);
    assert.ok(ms < LIMIT_MS, `${n} characters: ${ms.toFixed(1)} ms`);
    assert.equal(out.result.query.aliases, undefined, `${n} characters`);
    const off = (await measured("classics.search", { query, k: 10, aliases: "off" })).out.result;
    assert.deepEqual(out.result.query.terms, off.query.terms, `${n} characters`);
    assert.deepEqual(out.result.hits.map((h) => h.passage_id), off.hits.map((h) => h.passage_id), `${n} characters`);
    assert.ok(out.result.hits.every((h) => !h.via && !h.flags), `${n} characters`);
  }
});

test("classics.search with the alias layer: the asked name keeps 7 of 10 places, the side queue takes 4, 7 and 10", { skip }, async () => {
  for (const [k, places] of [[10, [4, 7, 10]], [3, []]]) {
    const { result } = await callTool("classics.search", { query: "辰砂", k });
    assert.deepEqual(sidePlaces(result.hits), places, `k ${k}`);
    if (k === 3) assert.ok(result.query.aliases.expansions.every((e) => !e.searched && e.why === "share"));
    for (const h of result.hits.filter((x) => !x.routes.includes("alias"))) assert.deepEqual([h.matched, h.via], [["辰砂"], undefined]);
  }
  const { result } = await callTool("classics.search", { query: "辰砂", k: 10 });
  const side = result.hits.filter((h) => h.routes.includes("alias"));
  assert.deepEqual(side.map((h) => [h.via[0].for, h.via[0].referent]), Array(3).fill([["辰砂"], "丹砂"]));
  assert.ok(side.every((h) => ["丹砂", "朱砂"].includes(h.via[0].surface) && h.matched[0] === h.via[0].surface));
  // a drug's other lexicon forms share the side places with the passages found under its other names, the lexicon's first
  const yam = (await callTool("classics.search", { query: "山药", k: 10 })).result;
  assert.deepEqual(sidePlaces(yam.hits), [4, 7, 10]);
  const labels = yam.hits.filter((_, i) => [4, 7, 10].includes(i + 1)).map((h) => [h.via[0].surface, h.via[0].direction, h.via[0].source]);
  assert.deepEqual(labels.map(([, , source]) => source[0] === "词表"), [true, false, true]);
  assert.ok(labels.every(([, direction]) => direction === "drug→alias"));
});

test("classics.search with the alias layer: periods, a name of two drugs, the layer off or without its route", { skip }, async () => {
  // an origin question within a period: the other names valid then, by year, each labelled with the drug
  const early = (await callTool("classics.search", { query: "唐以前的木通", k: 10 })).result;
  assert.equal(early.query.before, 618);
  assert.ok(early.hits.length > 0 && early.hits.every((h) => h.year < 618 && h.via[0].for[0] === "木通" && h.via[0].referent === "木通"));
  assert.deepEqual(early.hits.map((h) => h.year), [...early.hits.map((h) => h.year)].sort((a, b) => a - b));
  // in the Qing 通草 is no 木通: left out, and the passages that write it read as 通脱木
  const late = (await callTool("classics.search", { query: "清代的通草", k: 10 })).result;
  assert.deepEqual(late.query.aliases.excluded, [{ surface: "木通", for: "通草", why: "period" }]);
  assert.ok(late.hits.length > 0 && late.hits.every((h) => h.via[0].direction === "asked" && h.via[0].reading === "通脱木"));
  // a name of two drugs: listed with both, never read as one where nothing in the passage says which
  const ghost = (await callTool("classics.search", { query: "鬼督邮是什么药", k: 10 })).result;
  const [asked] = ghost.query.aliases.asked;
  assert.equal(asked.ambiguous, true);
  assert.ok(["徐长卿", "赤箭"].every((d) => asked.referents.some((r) => r.head === d)));
  for (const h of ghost.hits.filter((x) => x.via?.[0].direction === "asked")) {
    assert.equal(h.flags?.includes("homonym:鬼督邮") ?? false, h.via[0].reading === null, h.passage_id);
  }
  const drugs = ghost.hits.filter((h) => h.routes.includes("alias")).map((h) => h.via[0].referent);
  assert.deepEqual(new Set(drugs.slice(0, 2)), new Set(["徐长卿", "赤箭"])); // the side places dealt round-robin over the drugs
  // off: today's search; without the alias route: no side queue, the expansions said to be unsearched for it
  const off = (await callTool("classics.search", { query: "辰砂", k: 10, aliases: "off" })).result;
  assert.ok(!("aliases" in off.query) && off.hits.every((h) => !h.via && !h.flags && !h.routes.includes("alias")));
  const routes = (await callTool("classics.search", { query: "辰砂", k: 10, routes: ["bm25", "temporal"] })).result;
  assert.ok(routes.query.aliases.expansions.every((e) => !e.searched && e.why === "routes"));
  assert.ok(routes.hits.length > 0 && routes.hits.every((h) => !h.routes.includes("alias")));
});

test("classics.search with the alias layer: the queues — retention, round-robin, years, the demoted last, no drug as before", { skip }, async () => {
  const run = async (args) => (await callTool("classics.search", { k: 10, ...args })).result;
  // a drug asked beside a formula: the drug's own name keeps the first 7 places, the formula's passages follow
  const mixed = await run({ query: "麻黄汤中的甘草" });
  assert.ok(mixed.hits.slice(0, 7).every((h) => h.matched.includes("甘草")), JSON.stringify(mixed.hits.map((h) => h.matched)));
  assert.ok(mixed.hits.slice(7).some((h) => !h.matched.includes("甘草")));
  // a name of two drugs: the side places dealt round-robin over them
  const side = (await run({ query: "百枝" })).hits.filter((h) => h.routes.includes("alias")).map((h) => h.via[0].referent);
  assert.ok(side.length >= 4 && side.slice(1, 4).every((d, i) => d !== side[i]), side.join(" "));
  // an origin question: each queue by year in its own places, the demoted after everything else
  for (const query of ["人参最早见于哪部书", "唐以前的通草", "唐以前的木通"]) {
    const { hits } = await run({ query });
    for (const queue of [hits.filter((h) => h.routes.includes("alias")), hits.filter((h) => !h.routes.includes("alias") && !h.flags?.length)]) {
      assert.deepEqual(queue.map((h) => h.year), queue.map((h) => h.year).sort((a, b) => a - b), query);
    }
  }
  for (const query of ["唐以前的通草", "通草", "大黄", "红豆", "止行"]) {
    const demoted = (await run({ query })).hits.map((h) => (h.flags || []).some((f) => f.startsWith("demoted:")));
    assert.ok(!demoted.some((d, i) => d && demoted.slice(i).includes(false)), `${query}: ${demoted}`);
  }
  // a side passage writes none of the names asked (those are the main queue's); every card shows a name it was found under
  for (const [query, names] of [["栝楼实的功效", ["栝楼实"]], ["流星草与甘草", ["流星草", "甘草"]], ["辰砂", ["辰砂"]], ["山药", ["山药"]], ["鬼督邮是什么药", ["鬼督邮"]]]) {
    const { hits } = await run({ query });
    for (const h of hits) {
      assert.ok(h.matched.some((m) => normalize(h.text).includes(normalize(m))), `${query}: ${h.passage_id} ${h.text}`);
      if (!h.routes.includes("alias")) continue;
      const text = normalize((await callTool("classics.get_passage", { passage_id: h.passage_id })).result.text);
      assert.ok(names.every((s) => !text.includes(s)), `${query}: ${h.passage_id}`);
    }
  }
  // a question that asks no drug: today's answer
  for (const query of ["宋代以前的消渴", "消渴的认识如何演变", "太阳之为病脉浮头项强痛而恶寒", "桂枝汤"]) {
    const [on, off] = [await run({ query }), await run({ query, aliases: "off" })];
    assert.deepEqual(on.hits.map((h) => [h.passage_id, h.score]), off.hits.map((h) => [h.passage_id, h.score]), query);
  }
});

test("classics.search with the alias layer: a drug's side passages that give its name nothing beside it come after the others", { skip }, async () => {
  const corpus = new Corpus(env);
  const index = aliasIndex();
  let bare = 0;
  for (const query of ["辰砂", "红豆"]) {
    const q = await analyze(new Lexicon(corpus), query, { aliases: true, cfg: ALIAS_PARAMS, index });
    const exps = new Map(q.expansions.filter((e) => e.searched).map((e) => [e.surface, e]));
    const byDrug = new Map();
    for (const h of (await callTool("classics.search", { query, k: 20 })).result.hits.filter((x) => x.routes.includes("alias"))) {
      const p = await corpus.passage(h.passage_id);
      const yr = effective(p.T, p.card.dating_basis || "composition") ?? [null, null];
      const flag = index.bare(gateForm(normalize(p.p.t)), exps.get(h.via[0].surface), yr, ALIAS_PARAMS); // bare: an order, never a gate
      if (!byDrug.has(h.via[0].referent)) byDrug.set(h.via[0].referent, []);
      byDrug.get(h.via[0].referent).push(flag);
    }
    for (const [drug, flags] of byDrug) assert.ok(!flags.some((b, i) => b && flags.slice(i).includes(false)), `${query} ${drug}: ${flags}`);
    bare += [...byDrug.values()].flat().filter(Boolean).length;
  }
  assert.ok(bare > 0); // the fixture has some
});

test("a card centres on the name a hit was found under, as passage_card(focus=…) does", () => {
  const hit = (t) => ({ book: "b", p: { q: 1, t }, L: [[]], T: { t_composition: [1, 2] } });
  const card = { title: "书", dynasty: "", dating_basis: "composition" };
  const text = `${"甲".repeat(150)}甘草${"乙".repeat(200)}`;
  assert.equal(passageCard(hit(text), card).text, `${"甲".repeat(120)}…`);
  assert.equal(passageCard(hit(text), card, { focus: ["国老", "甘草"] }).text, `…${"甲".repeat(40)}甘草${"乙".repeat(78)}…`);
  assert.equal(passageCard(hit(`${"甲".repeat(99)}甘草${"乙".repeat(30)}`), card, { focus: ["甘草"] }).text, `${"甲".repeat(99)}甘草${"乙".repeat(19)}…`);
  assert.equal(passageCard(hit(`${"甲".repeat(110)}甘草${"乙".repeat(20)}`), card, { focus: ["甘草"] }).text, `…${"甲".repeat(40)}甘草${"乙".repeat(20)}`);
  assert.equal(passageCard(hit(`${"𠀀".repeat(110)}甘草${"乙".repeat(20)}`), card, { focus: ["甘草"] }).text, `…${"𠀀".repeat(40)}甘草${"乙".repeat(20)}`);
  assert.equal(passageCard(hit(`${"甲".repeat(110)}甘草${"乙".repeat(20)}`), card, { focus: ["甘草"], full: true }).text.length, 132);
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
  assert.equal(invalid.error, "invalid arguments: $: missing required property 'passage_id' · classics.get_passage takes: passage_id (string, required)");
  const books = await callTool("classics.list_books", {});
  assert.equal(books.result.length, 10);
  const sorted = books.result.map((b) => [b.composition || "", b.book_id]);
  assert.deepEqual(sorted, [...sorted].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1)));
  const dyn = await callTool("classics.list_books", { dynasty: "清" });
  assert.ok(dyn.result.length > 0 && dyn.result.every((b) => b.dynasty.includes("清")));
  const canon = await callTool("classics.canon", { limit: 5 });
  assert.equal(canon.result.listed, CANON.works.length); // the 要籍 list as corpus/catalog/canon.yaml holds it
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
  const unknown = await callTool("classics.get_pasage", {});
  assert.ok(unknown.error.startsWith("unknown tool 'classics.get_pasage'; closest: classics.get_passage {passage_id (string, required)} · "));
  assert.ok(unknown.error.endsWith("; use taochronos_catalog to see what exists"));
});

test("a model's call as it wrote it: a name in another form, arguments repaired, refused with what the tool takes", { skip }, async () => {
  for (const written of ["get_passage", "classics__get_passage", "Classics.Get-Passage", "study__get_passage"]) {
    const out = await callTool(written, { passage_id: "cm_shanghan_npm.00279" });
    assert.deepEqual([out.ok, out.tool], [true, "classics.get_passage"], written);
  }
  const repaired = await callTool("classics.list_books", { dynasty: "清", limit: "2" });
  assert.deepEqual([repaired.ok, repaired.result.length, repaired.repaired], [true, 2, ['$.limit: "2" → 2']]);
  assert.equal((await callTool("classics.list_books", { dynasty: "清", limit: 2 })).repaired, undefined);
  const meta = await callTool("taochronos.catalog", { family: ["classics"] });
  assert.deepEqual([meta.ok, meta.tool, meta.repaired], [true, "taochronos_catalog", ['$.family: ["classics"] → "classics"']]);
  assert.ok(meta.result.matched.every((t) => t.tool.startsWith("classics.")));
  const via = await callTool("taochronos_call", { tool: "get_passage", arguments: '{"passage_id": ["cm_shanghan_npm.00279"]}' });
  assert.deepEqual([via.ok, via.tool, via.via, via.repaired], [true, "classics.get_passage", "taochronos_call", ['$.passage_id: ["cm_shanghan_npm.00279"] → "cm_shanghan_npm.00279"']]);
  const nested = await callTool("taochronos_call", { tool: "taochronos_call", arguments: { tool: "classics.list_books", arguments: { limit: 1 } } });
  assert.deepEqual([nested.ok, nested.result.length], [true, 1]);
  // a parameter the tool does not take was ignored before: now it is refused, with what the tool takes
  const extra = await callTool("kg.term", { surface: "消渴", lang: "en" });
  assert.equal(extra.error, "invalid arguments: $: unknown parameter 'lang' · kg.term takes: surface (string, required)");
  const wrong = await callTool("taochronos_call", { name: "kg.term", args: { surface: "消渴" } });
  assert.ok(wrong.error.startsWith("invalid arguments: $: missing required property 'tool'; $: unknown parameter 'name'; $: unknown parameter 'args' · taochronos_call takes: tool (string, required); arguments (object)"));
  assert.equal((await callTool("kg.term", ["消渴"])).error, "invalid arguments: $: expected object, got list · kg.term takes: surface (string, required)");
  // what the backup does not serve is said so, under any name; an unknown name is answered with tools it serves
  assert.match((await callTool("taochronos.research", { question: "消渴" })).error, /taochronos_research 在本站的备份服务/);
  assert.match((await callTool("study__casefind", { query: "耳鸣" })).error, /study\.casefind 在本站的备份服务/);
  const served = new Set((await (await site("/api/catalog?mode=all")).json()).tools.map((t) => t.tool));
  for (const written of ["search", "nothing.here", "kg.propose_change", "KG.Propose-Change", "propose_change", "kg.propose", "run_code", "research.run-code"]) {
    const out = await callTool(written, {});
    const [, near] = out.error.split("; closest: ");
    const suggested = near.split(" · ").map((x) => x.split(" {")[0]);
    assert.equal(out.ok, false, written);
    assert.ok(suggested.length === 3 && suggested.every((t) => served.has(t) || ["taochronos_catalog", "taochronos_call"].includes(t)), `${written}: ${suggested}`);
    assert.ok(!/propose_change|run_code/.test(near), written);
  }
});

test("a model's calls are read as protocol/schema.py and kernel/tools.py read them (Python's answers in the fixture)", { skip }, () => {
  const { schema, arguments: args, entries, names } = fixture.calls;
  assert.ok(args.length >= 40 && names.length >= 25);
  for (const c of args) {
    const { value, repairs } = coerce(c.args, schema);
    assert.deepEqual([value, repairs], c.coerced, JSON.stringify(c.args));
    const fit = fitArguments(c.args, schema, "t");
    assert.deepEqual([fit.args, fit.repaired, fit.problem], c.fitted, JSON.stringify(c.args));
  }
  const all = entries.map(([name]) => name);
  for (const c of names) {
    assert.equal(resolveName(c.name, all), c.resolved, c.name);
    assert.deepEqual(closestNames(c.name, entries, entries.length), c.ranked, c.name);
  }
  // and what the catalog's own tools take, as the server's errors say it
  assert.equal(signature(CATALOG.tools.find((t) => t.tool === "classics.search").parameters), "query (string, required); k (integer); " +
    "after (number); before (number); routes (list of string); books (list of string); aliases (string: auto | off)");
  assert.equal(signature({ type: "object", properties: {} }), "no parameters");
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

test("parity: the live tools answer as the Python tools answered on the same store (a search: its query analysis, and the labels of the passages both found)", { skip }, async () => {
  assert.ok(fixture.reference.length >= 30);
  let labelled = 0;
  for (const ref of fixture.reference) {
    const { out } = await measured(ref.name, ref.args);
    const label = `${ref.name} ${JSON.stringify(ref.args)}`;
    assert.equal(out.ok, ref.ok, `${label}: ${out.error}`);
    assert.deepEqual(out.repaired ?? null, ref.repaired ?? null, label);
    if (!ref.ok) assert.equal(out.error, ref.error, label);
    else if (ref.name === "classics.search") {
      assert.deepEqual(out.result.query, ref.result.query, label);
      assert.equal(out.result.hits.length > 0, ref.result.hits.length > 0, label);
      // the routes differ (no dense route here), so the passages found may: those both found carry the same labels
      const python = new Map(ref.result.hits.map((h) => [h.passage_id, h]));
      for (const h of out.result.hits.filter((x) => python.has(x.passage_id))) {
        const p = python.get(h.passage_id);
        assert.deepEqual([h.via, h.flags], [p.via, p.flags], `${label}: ${h.passage_id}`);
        if (p.via || p.flags) labelled++;
      }
    } else assert.deepEqual(out.result, ref.result, label);
  }
  assert.ok(labelled >= 30, `${labelled} labelled passages compared`);
});

/** The gates of aliases.js on passages, as Python gave them (d1fixture._gate_case). */
function aliasGates(index, cases, cfg) {
  for (const c of cases) {
    const G = new Cp(c.g);
    const every = [];
    for (let i = 0; i < G.length; i++) if (G.startsWith(c.s, i)) every.push(i);
    const free = index.freeOffsets(c.g, c.s, c.b, c.yr);
    const [ref, p] = index.reading(c.g, c.s, c.yr, cfg);
    assert.deepEqual({
      free,
      covers: c.out.covers.map(([i, b]) => [i, b, index.covers(c.g, i, c.s, b, c.yr)]),
      covering: index.covering(c.g, c.s, c.b, c.yr),
      context: index.drugContext(c.g, c.s, free, c.cues, cfg),
      named: index.named(c.g, c.s, free, c.cues, cfg),
      context_every: index.drugContext(c.g, c.s, every, c.cues, cfg),
      reading: [ref?.h ?? null, ref?.g ?? null, p],
      floor: index.floorFlag(c.s, c.yr, c.edition),
    }, c.out, `${c.s} in ${c.g} ${JSON.stringify(c.yr)}`);
  }
}

/** The side queue's gates and order (accept, bare), and accept with the gates and windows lifted. */
function aliasAccept(index, cases, cfg) {
  const lifted = { ...cfg, ablate: ["gates", "period"] };
  for (const c of cases) {
    const label = `${c.exp.surface} (for ${c.exp.for}) in ${c.g} ${JSON.stringify(c.yr)}`;
    assert.deepEqual(index.accept(c.g, c.exp, c.yr, cfg), c.out, label);
    assert.deepEqual(index.accept(c.g, c.exp, c.yr, lifted), c.lifted, label);
    assert.equal(index.bare(c.g, c.exp, c.yr, cfg), c.bare, label);
  }
}

/** A question's expansions and query.aliases view; for a search, the searched ones unsearched where the side queue has
 * no place (routes, share). */
async function aliasQuestion(index, lex, c, cfg, { k = null, routes = null, load = true } = {}) {
  if (lex && load) await lex.loadIds([...c.q.asked.flat(), ...c.q.stops.flat()]);
  const q = { asked: c.q.asked, stops: c.q.stops, after: c.q.after, before: c.q.before, allSurfaces: c.q.surfaces, groups: c.q.groups };
  const p = { ...cfg, ...c.cfg };
  const exps = index.expansions(q, lex, p);
  if (k !== null) unsearched(exps, placeless(routes, k, p));
  const label = `${c.text} ${JSON.stringify(c.q.asked)} ${JSON.stringify(c.cfg)}`;
  assert.deepEqual(exps, c.expansions, label);
  assert.deepEqual(index.view(q, p, lex, exps), c.view, `${label}: view`);
  for (const [s, stop, refs] of c.referents || []) {
    const term = (stop ? c.q.stops : c.q.asked).find(([x]) => x === s)[1];
    assert.deepEqual(index.referents(s, term, lex, { stop }), refs, `${label}: referents of ${s}`);
  }
}

function aliasRecords(index, cases) {
  for (const c of cases) {
    assert.deepEqual(index.readings(c.s), c.readings, c.s);
    for (const [g, names] of Object.entries(c.names)) assert.deepEqual(index.names(g), names, `${c.s}: ${g}`);
    for (const [g, names] of Object.entries(c.by_group)) assert.deepEqual(index.byGroup(g).map(([a]) => a), names, `${c.s}: ${g}`);
    assert.deepEqual(index.groupsFor(index.record(c.s).r[0]?.t ?? null, [c.s]), c.groups_for, c.s);
  }
}

test("parity: the alias layer's functions (aliases.js) give what Python gave on the shipped layer", { skip }, async () => {
  const cases = fixture.alias_cases;
  assert.ok(cases, "no alias_cases in the fixture: python -m taochronos.chat.d1 fixture");
  assert.deepEqual(cases.params, ALIAS_PARAMS); // tables.js is this checkout's
  const cfg = cases.params;
  const index = new AliasIndex();
  for (const [x, out] of cases.gate_form) assert.equal(gateForm(x), out, x);
  for (const [x, out] of cases.scan) assert.deepEqual(index.scan(x), out, x);
  assert.ok(cases.gates.length >= 100 && cases.accept.length >= 100 && cases.expansions.length >= 100);
  assert.ok(cases.accept.some((c) => c.out[1] === "rival") && cases.accept.some((c) => c.bare));
  aliasGates(index, cases.gates, cfg);
  aliasAccept(index, cases.accept, cfg);
  const lex = new Lexicon(new Corpus(env));
  for (const c of cases.expansions) await aliasQuestion(index, lex, c, cfg);
  for (const c of cases.searches) await aliasQuestion(index, lex, c, cfg, c);
  assert.deepEqual(cases.searches.map((c) => c.expansions[0]?.why ?? null), [null, "share", "routes", "share", null, "share", null]);
  aliasRecords(index, cases.records);
  for (const c of cases.assemble) assert.deepEqual(assemble(c.M, c.S, c.k, c.num, c.den), c.out, JSON.stringify(c));
  for (const [x, out] of cases.round4) assert.equal(round4(x), out, String(x));
});

test("parity: the alias layer's functions on a made-up layer — astral names, windowed and chained blockers, stops", { skip }, async () => {
  const cases = fixture.alias_cases;
  const cfg = cases.params;
  const syn = cases.synthetic;
  const index = new AliasIndex(syn.records, syn.context, syn.sources);
  for (const [x, out] of syn.scan) assert.deepEqual(index.scan(x), out, x);
  aliasGates(index, syn.gates, cfg);
  aliasAccept(index, syn.accept, cfg);
  const lex = new Lexicon(null); // the made-up lexicon's buckets, as D1's lex table holds them
  for (const [s, entries] of Object.entries(syn.lexicon)) {
    const first = String.fromCodePoint(s.codePointAt(0));
    if (!lex.buckets.has(first)) lex.buckets.set(first, {});
    lex.buckets.get(first)[s] = entries;
  }
  for (const c of syn.expansions) await aliasQuestion(index, c.lexicon ? lex : null, c, cfg, { load: false });
  aliasRecords(index, syn.record_cases);
  assert.ok(syn.expansions.some((c) => c.expansions.some((e) => e.also.length > 1)));
  assert.ok(syn.expansions.some((c) => c.view.asked?.some((a) => a.note)));
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

test("a result's figures and tables are for the page: the model reads their titles, never their data or raw values", () => {
  const chart = { type: "box", title: "甲 · 用量", rows: [{ q1: 1 }] }, table = { title: "各时期", columns: [{ key: "a", label: "甲" }], rows: [{ a: "1" }] };
  assert.deepEqual(forModel({ x: 1, charts: [chart], tables: [table], _raw: { grams: [1, 2] } }), { x: 1, charts_shown: ["甲 · 用量"], tables_shown: ["各时期"] });
  assert.deepEqual(forModel({ x: 1, _raw: [1] }), { x: 1 });
  const shown = forInterface({ rows: Array(400).fill("长".repeat(500)), tables: [table] }, 30000);
  assert.deepEqual(shown.tables, [table]);
  assert.ok(shown.rows.length < 400);
});
