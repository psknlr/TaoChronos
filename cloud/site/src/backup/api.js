// The page's API answered by the D1 backup (docs/adr/0017-d1-backup.md): GET /api/info, /api/catalog, /api/passage and
// POST /api/call, in the shapes of taochronos.chat.server and ChatRuntime — the page talks to it as to the full corpus's
// container, and its runtime label says it is the backup.  Research runs and sessions need the server: POST
// /api/research answers 501 with the reason (the page shows it and stays on the site's server).

import { catalog, catalogView, engineNames, LIVE, PRECOMPUTED, served, toolEntry, validate } from "./catalog.js";
import { Corpus, CorpusError, passageCard } from "./corpus.js";
import { precomputed } from "./precomputed.js";
import { shape } from "./results.js";
import { INFO, PROMPT } from "./tables.js";
import * as tools from "./tools.js";
import { ToolError } from "./tools.js";

export const LABEL = "全量语料（备份）";

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
  working_set: "D1–D5 分析读的是研究会话或服务器进程中已检索段落的工作集与其中抽取的主张，备份服务无状态",
  model: "需要服务器上的统计模型或逐段计算（句读模型、候选数千段的比对与分类），超出 Worker 每次 10 毫秒的计算",
  session: "需要研究会话",
};
const UNAVAILABLE = {
  taochronos_research: WHY.engine, taochronos_session: WHY.engine, taochronos_ask: WHY.engine,
  "validation.gates": WHY.session, "classics.lineage": WHY.working_set, "kg.extract_claims": WHY.model,
};

const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

/** Is the backup there for this deployment?  (deploy.sh sets D1_BACKUP to the version the import completed.) */
export const ready = (env) => Boolean(env.D1_BACKUP && env.D1_0);

/** method, url, body (an ArrayBuffer for POST) → a Response. */
export async function answer(method, url, body, env) {
  const corpus = new Corpus(env);
  let stats;
  try {
    stats = await corpus.stats();
  } catch (err) {
    console.error("backup", err?.message || err);
    return json({ error: "本站的全量语料备份暂不可用：网页在浏览器里运行要籍语料", corpus: "none" }, 503, { "X-TC-Corpus": "none" });
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
    if (path === "/api/passage") return json(await passage(corpus, url.searchParams.get("id") || ""), 200, headers);
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
      return json(await call(corpus, String(data.name || ""), data.arguments || {}, Number(data.max_chars) || 16000, pre), 200, headers);
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

/** ChatRuntime.call: one tool the model asked for; never throws — a failure is a result the model can read. */
export async function call(corpus, name, args, maxChars = 16000, pre = new Set()) {
  const started = Date.now();
  let tool = name;
  let a = args && typeof args === "object" ? args : {};
  let via = null;
  try {
    if (name === "taochronos_call") {
      const inner = String(a.tool || "");
      if (!inner) throw new ToolError("ValueError", 'taochronos_call needs {"tool": <name>, "arguments": {...}}');
      via = "taochronos_call";
      tool = inner;
      a = a.arguments && typeof a.arguments === "object" ? a.arguments : {};
    }
    if (tool === "taochronos_catalog") {
      const result = catalogView(pre, { family: a.family || null, query: a.query || null });
      return withVia(shape(tool, true, result, null, { durationMs: Date.now() - started, maxChars, receipt: await receipt(tool, a, result) }), via);
    }
    if (ENGINE.has(tool) || tool === "taochronos_call") throw new ToolError("Unavailable", unavailable(tool));
    const spec = toolEntry(tool) || toolEntry(tool.replaceAll("__", "."));
    if (!spec) throw new ToolError("UnknownTool", `unknown tool '${tool}'; use taochronos_catalog to see what exists`);
    tool = spec.tool;
    if (!LIVE.has(tool) && !(PRECOMPUTED.has(tool) && pre.has(tool))) throw new ToolError("Unavailable", unavailable(tool));
    const errors = validate(a, spec.parameters);
    if (errors.length) throw new ToolError("invalid", `invalid arguments: ${errors.slice(0, 5).join("; ")}`);
    const result = LIVE.has(tool) ? await RUN[tool](corpus, a) : await precomputed(corpus, tool, a);
    return withVia(shape(tool, true, result, null, { durationMs: Date.now() - started, maxChars, receipt: await receipt(tool, a, result) }), via);
  } catch (err) {
    return withVia(shape(tool, false, null, errorText(err), { durationMs: Date.now() - started }), via);
  }
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
  return `${tool} 在本站的备份服务（全量语料的 D1 备份）中不可用：${UNAVAILABLE[tool] || WHY.model}。` +
    "可用的工具见 taochronos_catalog；全量语料的完整服务恢复后即可使用。";
}

// ------------------------------------------------------------------ receipts (kernel/tools.py: what was called, what came back)
async function digest(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value ?? null));
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...hash.slice(0, 12)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function receipt(tool, args, result) {
  return { tool, version: "1", actor: "agent:chat", principal: "agent", arguments_sha256: await digest(args),
    result_sha256: await digest(result), ok: true, quarantined: false, backup: "d1" };
}

export { CorpusError };
