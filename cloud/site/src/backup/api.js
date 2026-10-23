// The page's API answered by the D1 backup (docs/adr/0017-d1-backup.md): GET /api/info, /api/catalog, /api/passage and
// POST /api/call, in the shapes of taochronos.chat.server and ChatRuntime — the page talks to it as to the full corpus's
// container, and its runtime label says it is the backup.  Research runs and sessions need the server: POST
// /api/research answers 501 with the reason (the page shows it and stays on the site's server).

import { canonical, catalog, catalogView, closest, engineNames, fitArguments, LIVE, parametersOf, PRECOMPUTED, pyRepr,
  served } from "./catalog.js";
import { Corpus, CorpusError, passageCard } from "./corpus.js";
import { precomputed } from "./precomputed.js";
import { shape } from "./results.js";
import { INFO, PROMPT } from "./tables.js";
import * as tools from "./tools.js";
import { ToolError } from "./tools.js";
import { warmUp } from "./warm.js";

export const LABEL = "全量语料（备份）";

// the code compiled and warmed as the isolate starts, not in the first request's 10 ms (warm.js: made-up databases in
// memory, so the promises settle before the start is over)
warmUp().catch((err) => console.error("backup warm-up", err?.message || err));

const RUN = {
  "classics.search": tools.search,
  "classics.get_passage": tools.getPassage,
  "classics.list_books": tools.listBooks,
  "classics.canon": tools.canon,
  "kg.term": tools.kgTerm,
  "philology.normalize": tools.normalizeTool,
  "philology.assess_passage": tools.assessPassage,
  "philology.collate": tools.collate,
  "philology.inspect_page": tools.inspectPage,
  "validation.provenance_chain": tools.inspectPage,
  "validation.verify_quote": tools.verifyQuote,
  "study.metrology": tools.metrologyTool,
  "modern.safety": tools.safety,
  "literature.modern_evidence": tools.modernEvidence,
};

// why a tool is not in the backup (the ADR's table: what it needs that a Worker on D1 does not have)
const WHY = {
  engine: "多智能体研究与研究会话需要服务器上的研究引擎（数十个智能体、数分钟的计算）",
  session: "门控 G0–G8 评的是研究会话中的主张、证据与假说，备份服务没有研究会话",
  working_set: "D1–D5 分析与知识谱系读的是研究会话或服务器进程中已检索段落的工作集及其中抽取的主张，备份服务无状态",
  passages: "需要在服务器上对大量段落逐段计算（比对、归类、抽取、统计检验），超出 Worker 每次 10 毫秒的计算；其参数不定，无法预先算好",
  data: "需要服务器上的模型、规则或数据（句读模型、实体与主张抽取规则、现代医学映射与数据库、OCR 版面），Worker 中没有",
  mine: "我的资料只在用户本机读取（浏览器内的运行环境或本机的服务），网站的服务器不经手个人资料：网页把这些工具交给浏览器内的运行环境",
};
const UNAVAILABLE = Object.fromEntries([
  ["engine", ["taochronos_research", "taochronos_session", "taochronos_ask"]],
  ["session", ["validation.gates"]],
  ["working_set", ["analysis.association_rules", "analysis.communities", "analysis.concept_drift", "analysis.contradictions",
    "analysis.formula_evolution", "analysis.link_prediction", "analysis.lost_knowledge", "analysis.missing_sources",
    "analysis.temporal_profile", "classics.lineage"]],
  ["data", ["study.punctuate", "study.translate", "study.entities", "study.clause", "study.argument", "study.protocol", "kg.extract_claims",
    "bridge.map", "bridge.phenotype", "bridge.reverse", "modern.search", "rwd.ask", "vision.compare", "vision.layout",
    "audit.claim", "graph.evidence"]],
  ["passages", ["study.authorship", "study.cards", "study.cases", "study.chain", "study.compare", "study.dating", "study.disputes",
    "study.family", "study.incompat", "study.properties", "study.usage",
    "study.fragments", "study.glosses", "study.layers", "study.places", "study.reuse", "study.stemma", "study.trajectories",
    "study.transmission", "study.variants", "study.casefind", "study.similar", "study.case", "study.casecompare",
    "study.modifications", "study.treatments"]],
  ["mine", ["mydata.list", "mydata.read", "mydata.search", "mydata.describe", "mydata.compare", "mydata.prescriptions"]],
].flatMap(([why, names]) => names.map((n) => [n, WHY[why]])));

const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

/** Is the backup there for this deployment?  (deploy.sh sets D1_BACKUP to the version the import completed.) */
export const ready = (env) => Boolean(env.D1_BACKUP && env.D1_0);

const DOWN = { error: "本站的全量语料备份暂不可用：网页在浏览器里运行要籍语料", corpus: "none" };

/** Is this error D1 being unavailable (its daily allowance used up, overloaded, the network) rather than the call's
 * own?  Then the page is answered 503 and falls back to the browser, as when there is no backup. */
export const unavailableError = (text) => /D1_ERROR|D1 |D1:/.test(String(text || "")) &&
  /exceed|quota|limit (?:reached|exceeded)|daily|free tier|rate.?limit|too many requests|network connection lost|internal error|overloaded|temporarily unavailable|timed? ?out/i
    .test(String(text || ""));

/** method, url, body (an ArrayBuffer for POST) → a Response. */
export async function answer(method, url, body, env) {
  const corpus = new Corpus(env);
  let stats;
  try {
    stats = await corpus.stats();
  } catch (err) {
    console.error("backup", err?.message || err);
    return json(DOWN, 503, { "X-TC-Corpus": "none" });
  }
  if (env.D1_BACKUP !== stats.complete) {
    // the databases hold another version than this deployment was made for (an import in progress): not served
    return json({ error: "本站的全量语料备份正在更新：网页在浏览器里运行要籍语料", corpus: "none" }, 503, { "X-TC-Corpus": "none" });
  }
  const pre = new Set(Object.keys(stats.precomputed || {}));
  const path = url.pathname;
  const headers = { "X-TC-Corpus": "d1" };
  if (method === "GET" || method === "HEAD") {
    if (path === "/api/info") return json(info(stats, pre), 200, headers);
    if (path === "/api/catalog") return json(catalog(url.searchParams.get("mode") || "core", pre), 200, headers);
    if (path === "/api/passage") {
      const out = await passage(corpus, url.searchParams.get("id") || "");
      return out.ok || !unavailableError(out.error) ? json(out, 200, headers) : json(DOWN, 503, { "X-TC-Corpus": "none" });
    }
    if (path.startsWith("/api/research/")) return json({ id: path.split("/").pop(), status: "unknown" }, 200, headers);
    if (path.startsWith("/api/session/")) return json({ error: `本站的备份服务没有研究会话：${WHY.engine}` }, 501, headers);
  }
  if (method === "POST") {
    let data;
    try {
      data = JSON.parse(new TextDecoder().decode(body || new ArrayBuffer(0)) || "{}");
    } catch (err) {
      return json({ error: `invalid JSON: ${err.message}` }, 400, headers);
    }
    if (path === "/api/call") {
      const out = await call(corpus, String(data.name || ""), data.arguments || {}, Number(data.max_chars) || 16000, pre);
      return out.ok || !unavailableError(out.error) ? json(out, 200, headers) : json(DOWN, 503, { "X-TC-Corpus": "none" });
    }
    if (path === "/api/research") return json({ error: `本站的备份服务不能运行多智能体研究：${WHY.engine}。可改用检索与治学工具分步研究。` }, 501, headers);
  }
  return json({ error: `no such endpoint ${path}` }, 404, headers);
}

// ------------------------------------------------------------------ describe
export function info(stats, pre) {
  const tools = served(pre);
  const corpus = { books: stats.books, passages: stats.passages, characters: stats.characters, by_period: stats.by_period, large: true,
    demo: false, kind: "full", label: LABEL, canon: { listed: stats.canon.listed, held: stats.canon.held } };
  const prompt = PROMPT.replaceAll("{books}", String(stats.books)).replaceAll("{passages}", String(stats.passages))
    .replaceAll("{listed}", String(stats.canon.listed)).replaceAll("{held}", String(stats.canon.held)) + backupNote(pre);
  return {
    name: INFO.name, version: INFO.version, runtime: "d1", profile: "full-corpus", corpus,
    tools: { offered: tools.length, families: catalog("all", pre).families },
    assistant_name: INFO.assistant_name, agent_name: INFO.agent_name, publisher: INFO.publisher, engine_model: null,
    code_mode: false, starters: INFO.starters, system_prompt: prompt, proxy: false, env_keys: false,
    backup: { store: "d1", version: stats.complete, databases: stats.databases, live: [...LIVE].sort(),
      precomputed: Object.fromEntries(Object.entries(stats.precomputed || {}).sort()) },
  };
}

function backupNote(pre) {
  const precomputedNames = [...PRECOMPUTED].filter((t) => pre.has(t));
  return "\n\n## 本站备份服务\n当前由本站的备份服务回答：全量语料存于 Cloudflare D1，工具在网站的 Worker 里运行。检索、原文、书目、要籍、" +
    "术语词条、引文核对、溯源、异体规范、校勘、度量衡与安全提示直接计算（classics.search 融合 bm25、temporal、variant、sense 四路，" +
    "dense、graph、citation 三路需服务器）；" +
    (precomputedNames.length ? `${precomputedNames.join("、")} 为在全量语料上预先计算的常见条目，未收的条目会如实说明；` : "") +
    "多智能体研究（taochronos_research、taochronos_session、taochronos_ask）、D1–D5 分析及其余需要服务器计算的工具暂不可用，" +
    "需要时请向用户说明，并用可用的工具检索原文作答。";
}

// ------------------------------------------------------------------ passages
async function passage(corpus, pid) {
  try {
    const hit = await corpus.passage(pid);
    if (!hit) return { ok: false, passage_id: pid, error: `KeyError: '${pid}'` };
    return { ok: true, ...passageCard(hit, hit.card, { full: true }) };
  } catch (err) {
    return { ok: false, passage_id: pid, error: `${err.kind || err.name || "Error"}: ${err.message}` };
  }
}

// ------------------------------------------------------------------ calls
const ENGINE = new Set(engineNames());

/** ChatRuntime.call: one tool the model asked for; never throws — a failure is a result the model can read.  A name written
 * in another form is the tool's it denotes; the arguments are read against its parameters (fitArguments): their form
 * repaired where only that was wrong (the outcome's `repaired` says how), and a call they still do not fit — a parameter
 * the tool does not take, which it would otherwise ignore — answered with what the tool takes. */
export async function call(corpus, name, args, maxChars = 16000, pre = new Set()) {
  const started = Date.now();
  let tool = name;
  let a = args ?? {};
  let via = null;
  let repaired = [];
  const done = (out) => withVia(repaired.length ? { ...out, repaired } : out, via);
  try {
    tool = named(name, pre);
    while (tool === "taochronos_call") {
      const fit = fitArguments(a, parametersOf(tool), tool);
      if (fit.problem) throw new ToolError("invalid", fit.problem);
      const inner = String(fit.args.tool || "");
      if (!inner) throw new ToolError("ValueError", 'taochronos_call needs {"tool": <name>, "arguments": {...}}');
      via = "taochronos_call";
      tool = named(inner, pre);
      a = fit.args.arguments || {};
    }
    if (ENGINE.has(tool)) throw new ToolError("Unavailable", unavailable(tool));
    const meta = tool === "taochronos_catalog";
    if (!meta && !LIVE.has(tool) && !(PRECOMPUTED.has(tool) && pre.has(tool))) throw new ToolError("Unavailable", unavailable(tool));
    const fit = fitArguments(a, parametersOf(tool), tool);
    repaired = fit.repaired;
    if (fit.problem) throw new ToolError("invalid", fit.problem);
    a = fit.args;
    if (meta) {
      const result = catalogView(pre, { family: a.family || null, query: a.query || null });
      return done(shape(tool, true, result, null, { durationMs: Date.now() - started, maxChars, receipt: await receipt(tool, a, result) }));
    }
    const result = LIVE.has(tool) ? await RUN[tool](corpus, a) : await precomputed(corpus, tool, a);
    const dumped = JSON.stringify(result ?? null);
    return done(shape(tool, true, result, null, { durationMs: Date.now() - started, maxChars, dumped,
      receipt: await receipt(tool, a, result, dumped) }));
  } catch (err) {
    return done(shape(tool, false, null, errorText(err), { durationMs: Date.now() - started }));
  }
}

/** The tool a model's name denotes (catalog.js canonical); else UnknownTool, naming the closest tools served. */
function named(name, pre) {
  const text = String(name ?? "");
  const tool = canonical(text);
  if (tool === null) {
    throw new ToolError("UnknownTool", `unknown tool ${pyRepr(text)}; closest: ${closest(text, pre)}; use taochronos_catalog to see what exists`);
  }
  return tool;
}

const withVia = (out, via) => (via ? { ...out, via } : out);

function errorText(err) {
  if (err instanceof ToolError) {
    if (["UnknownTool", "invalid", "Unavailable", "NotPrecomputed"].includes(err.kind)) return err.message;
    return `${err.kind}: ${err.message}`;
  }
  if (err instanceof CorpusError) return `CorpusError: ${err.message}`;
  console.error("backup tool", err?.name, err?.message);
  return `${err?.name || "Error"}: ${err?.message || err}`;
}

function unavailable(tool) {
  const why = PRECOMPUTED.has(tool) ? "它在全量语料上预先计算的结果还没有导入" : UNAVAILABLE[tool] || WHY.passages;
  return `${tool} 在本站的备份服务（全量语料的 D1 备份）中不可用：${why}。` +
    "可用的工具见 taochronos_catalog；全量语料的完整服务恢复后即可使用。";
}

/** Every tool of the catalog is live, precomputed or unavailable for a stated reason (the tests hold the catalog to it). */
export const classification = () => ({ live: [...LIVE], precomputed: [...PRECOMPUTED], unavailable: { ...UNAVAILABLE } });

// ------------------------------------------------------------------ receipts (kernel/tools.py: what was called, what came back)
async function digest(value, dumped = null) {
  const bytes = new TextEncoder().encode(dumped ?? JSON.stringify(value ?? null));
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...hash.slice(0, 12)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** `dumped`: the result serialised (JSON.stringify(result ?? null)), made once for the receipt and the shaping. */
async function receipt(tool, args, result, dumped = null) {
  return { tool, version: "1", actor: "agent:chat", principal: "agent", arguments_sha256: await digest(args),
    result_sha256: await digest(result, dumped), ok: true, quarantined: false, backup: "d1" };
}

export { CorpusError };
