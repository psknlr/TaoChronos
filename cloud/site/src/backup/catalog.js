// What the D1 backup offers a model (taochronos.chat.catalog): only the tools it really serves — those computed here
// (LIVE) and those whose results were precomputed on the full corpus and imported (PRECOMPUTED, as far as the
// databases hold them) — in the server's two modes, and the taochronos_catalog meta-tool over them.

import { CATALOG } from "./tables.js";

// computed by the Worker (tools.js, search.js)
export const LIVE = new Set([
  "classics.search", "classics.get_passage", "classics.list_books", "classics.canon", "kg.term", "philology.normalize",
  "philology.assess_passage", "philology.collate", "philology.inspect_page", "validation.provenance_chain",
  "validation.verify_quote", "study.metrology", "modern.safety", "literature.modern_evidence",
]);

// served from `results` (precomputed.js; taochronos.chat.d1results computes them)
export const PRECOMPUTED = new Set([
  "study.formula", "study.herb", "study.term", "study.network", "study.commentaries", "study.concordance", "study.names",
  "study.pairs", "study.taboo", "study.citations", "study.schools", "study.senses", "study.witnesses", "study.reading",
  "kg.claims", "kg.neighbors",
]);

const BY_NAME = new Map(CATALOG.tools.map((t) => [t.tool, t]));

/** The tools served, given which precomputed tools have results in the databases. */
export function served(precomputed = new Set()) {
  return CATALOG.tools.filter((t) => LIVE.has(t.tool) || (PRECOMPUTED.has(t.tool) && precomputed.has(t.tool)));
}

export function familyCounts(tools) {
  const counts = {};
  for (const t of tools) counts[t.family] = (counts[t.family] || 0) + 1;
  const out = {};
  for (const [fam, meta] of Object.entries(CATALOG.families)) if (counts[fam]) out[fam] = { ...meta, count: counts[fam] };
  return out;
}

/** ChatRuntime.catalog: {mode, tools, families} (core: the core tools served, and the two meta-tools). */
export function catalog(mode, precomputed) {
  const tools = served(precomputed);
  const core = new Set(CATALOG.core);
  const direct = mode === "core" ? tools.filter((t) => core.has(t.tool)) : tools;
  const meta = mode === "core" ? CATALOG.meta.map((m) => ({ ...m, tool: m.name })) : [];
  return { mode, tools: [...direct, ...meta], families: familyCounts(tools) };
}

/** catalog_view: every family with its tools, and full parameters for a family or a query. */
export function catalogView(precomputed, { family = null, query = null } = {}) {
  const tools = served(precomputed);
  const families = {};
  for (const t of tools) {
    const meta = CATALOG.families[t.family] || { label: t.family, blurb: "" };
    families[t.family] ||= { ...meta, tools: [] };
    families[t.family].tools.push({ tool: t.tool, summary: summaryOf(t.description) });
  }
  const out = { families, how: "用 taochronos_call 调用：{\"tool\": \"study.pairs\", \"arguments\": {...}}" };
  if (family || query) {
    const q = String(query || "").toLowerCase();
    const own = (t) => t.description.split(" Returns: ")[0].toLowerCase();
    const matched = tools.filter((t) => (!family || t.family === family) && (!q || t.tool.toLowerCase().includes(q) || own(t).includes(q)));
    out.matched = matched.slice(0, 24).map((t) => ({ tool: t.tool, description: t.description, parameters: t.parameters }));
    if (!matched.length) out.note = `没有匹配的工具；family 可选：${Object.keys(families).sort().join("、")}`;
  }
  return out;
}

/** The first sentence of a description (as catalog_view cuts it from the tool's own description). */
function summaryOf(description) {
  const own = description.split(" Returns: ")[0];
  return [...own.split("。")[0].split(". ")[0]].slice(0, 90).join("");
}

export const toolEntry = (name) => BY_NAME.get(name) || null;
export const engineNames = () => CATALOG.engine.map((e) => e.name);

// ------------------------------------------------------------------ arguments (protocol/schema.py, validate)
const TYPES = {
  object: (v) => v !== null && typeof v === "object" && !Array.isArray(v),
  array: Array.isArray,
  string: (v) => typeof v === "string",
  integer: (v) => typeof v === "number" && Number.isInteger(v),
  number: (v) => typeof v === "number",
  boolean: (v) => typeof v === "boolean",
  null: (v) => v === null,
};

export function validate(instance, schema, path = "$") {
  const errors = [];
  if (schema.anyOf) {
    const branches = schema.anyOf.map((s) => validate(instance, s, path));
    return branches.every((b) => b.length) ? [`${path}: no anyOf branch matched (${branches[0][0] || ""})`] : [];
  }
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((t) => TYPES[t]?.(instance))) return [`${path}: expected ${JSON.stringify(schema.type).replaceAll('"', "'")}, got ${pyType(instance)}`];
  }
  if (schema.enum && !schema.enum.includes(instance)) errors.push(`${path}: ${JSON.stringify(instance)} not in ${JSON.stringify(schema.enum)}`);
  if (TYPES.object(instance)) {
    const props = schema.properties || {};
    for (const key of schema.required || []) if (!(key in instance)) errors.push(`${path}: missing required property '${key}'`);
    for (const [key, value] of Object.entries(instance)) {
      if (key in props) errors.push(...validate(value, props[key], `${path}.${key}`));
      else if (schema.additionalProperties === false) errors.push(`${path}: unexpected property '${key}'`);
    }
  }
  if (Array.isArray(instance) && schema.items) instance.forEach((item, i) => errors.push(...validate(item, schema.items, `${path}[${i}]`)));
  return errors;
}

function pyType(v) {
  if (v === null) return "NoneType";
  if (Array.isArray(v)) return "list";
  if (typeof v === "string") return "str";
  if (typeof v === "boolean") return "bool";
  if (typeof v === "number") return Number.isInteger(v) ? "int" : "float";
  return "dict";
}
