// What the D1 backup offers a model (taochronos.chat.catalog): only the tools it really serves — those computed here
// (LIVE) and those whose results were precomputed on the full corpus and imported (PRECOMPUTED, as far as the
// databases hold them) — in the server's two modes, and the taochronos_catalog meta-tool over them.  A model's call is
// read as the server reads it (ChatRuntime.call): a name written in another form is the tool's it denotes, and arguments
// whose form only is wrong are repaired (protocol/schema.py and kernel/tools.py, ported below).

import { opcodes } from "./difflib.js";
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

// ------------------------------------------------------------------ a model's names for tools (kernel/tools.py)
const ENGINE = new Map(CATALOG.engine.map((e) => [e.name, e]));
const META = new Map(CATALOG.meta.map((m) => [m.name, m]));
// every name a model may write for a tool, as the server's: the catalog (kg.propose_change and Code Mode are not in it),
// the engine and the meta-tools
const NAMES = [...BY_NAME.keys(), ...ENGINE.keys(), ...META.keys()];

/** The parameters of a tool of the catalog, the engine or the meta-tools. */
export const parametersOf = (tool) => (BY_NAME.get(tool) || ENGINE.get(tool) || META.get(tool)).parameters;

/** ChatRuntime._canonical: the tool a model's name denotes — the name itself (its model name too, dots as "__"), or the
 * one tool whose name it writes in another form (get_passage, taochronos.catalog); null where none is. */
export function canonical(name) {
  if (ENGINE.has(name) || META.has(name)) return name;
  const entry = toolEntry(name) || toolEntry(name.replaceAll("__", "."));
  return entry ? entry.tool : resolveName(name, NAMES);
}

/** What UnknownTool says of a name no tool has: the closest tools served, each with what it takes. */
export function closest(name, precomputed) {
  const entries = [...served(precomputed).map((t) => [t.tool, t.family]), ...CATALOG.meta.map((m) => [m.name, m.family])];
  return closestNames(name, entries).map((n) => `${n} {${signature(parametersOf(n), { limit: 6 })}}`).join(" · ");
}

/** name_key: a tool's name with case and separators set aside (Classics.Get-Passage and classics__get_passage are both
 * classics.get.passage). */
export const nameKey = (name) => String(name).toLowerCase().split(/[^0-9a-z]+/).filter(Boolean).join(".");

const partition = (key) => {
  const i = key.indexOf(".");
  return i < 0 ? [key, ""] : [key.slice(0, i), key.slice(i + 1)];
};

/** resolve_name: the one of `names` a model's name denotes by its form alone — in another case or with other separators,
 * with something written before it, without its family or under another one where only one tool has what follows the
 * family; null where none fits, or more than one does. */
export function resolveName(name, names) {
  const key = nameKey(name);
  const keys = new Map([...names].map((n) => [n, nameKey(n)]));
  const after = partition(key)[1];
  const rules = [(k) => k === key, (k) => key.endsWith(`.${k}`), (k) => partition(k)[1] === key,
    (k) => Boolean(after) && partition(k)[1] === after];
  for (const rule of key ? rules : []) {
    const found = [...keys].filter(([, k]) => rule(k)).map(([n]) => n);
    if (found.length) return found.length === 1 ? found[0] : null;
  }
  return null;
}

/** SequenceMatcher(None, a, b, autojunk=False).ratio() */
function ratio(a, b) {
  const { ops, A, B } = opcodes(a, b);
  if (!A.length && !B.length) return 1;
  return (2 * ops.reduce((m, [tag, i1, i2]) => (tag === "equal" ? m + i2 - i1 : m), 0)) / (A.length + B.length);
}

/** closest_names: the n names of `entries` ([name, family]) closest to a name no tool has — by the whole name or what
 * follows its family, whichever is nearer, and nearer still in the family the name begins with. */
export function closestNames(name, entries, n = 3) {
  const key = nameKey(name);
  const [head, rest] = partition(key);
  const verb = rest || head;
  const score = ([candidate, family]) => {
    const cand = nameKey(candidate);
    const [chead, cverb] = partition(cand);
    return Math.max(ratio(key, cand), ratio(verb, cverb || chead)) + (head && (head === chead || head === nameKey(family)) ? 0.2 : 0);
  };
  return [...entries].map((e) => [e[0], score(e)])
    .sort((x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0))
    .slice(0, n).map(([found]) => found);
}

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
    if (!types.some((t) => TYPES[t]?.(instance))) {
      return [`${path}: expected ${typeof schema.type === "string" ? schema.type : pyRepr(schema.type)}, got ${pyType(instance)}`];
    }
  }
  if (schema.enum && !schema.enum.includes(instance)) errors.push(`${path}: ${pyRepr(instance)} not in ${pyRepr(schema.enum)}`);
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

// Python's repr of a JSON value, as its messages write one: 'none', ['auto', 'off'], True, None
const UNPRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

export function pyRepr(v) {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) return `[${v.map(pyRepr).join(", ")}]`;
  if (typeof v === "object") return `{${Object.entries(v).map(([k, x]) => `${pyRepr(k)}: ${pyRepr(x)}`).join(", ")}}`;
  const s = String(v);
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = "";
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === quote || ch === "\\") out += `\\${ch}`;
    else if (ch === "\t" || ch === "\n" || ch === "\r") out += { "\t": "\\t", "\n": "\\n", "\r": "\\r" }[ch];
    else if (c < 0x20 || c === 0x7f || (c > 0x7f && c <= 0xff && UNPRINTABLE.test(ch))) out += `\\x${c.toString(16).padStart(2, "0")}`;
    else if (c > 0xff && UNPRINTABLE.test(ch)) out += c <= 0xffff ? `\\u${c.toString(16).padStart(4, "0")}` : `\\U${c.toString(16).padStart(8, "0")}`;
    else out += ch;
  }
  return quote + out + quote;
}

// ------------------------------------------------------------------ a model's arguments (protocol/schema.py)
const INTEGER = /^[+-]?[0-9]+(?:\.0*)?$/;
const NUMBER = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;
// a text that lists several values (「消渴、口渴」) is not one value of a list: it is left for the model to write as a list
const LIST_MARKS = /[,，、;；\n]/;
const WRAPPER = "item"; // how some models' tool grammars write a list, or a value: {"item": […]}, {"item": "消渴"}
const NO = Symbol("no");

const parsed = (text) => {
  try {
    return JSON.parse(text);
  } catch {
    return NO;
  }
};

function show(value) {
  const text = [...JSON.stringify(value)];
  return text.length <= 60 ? text.join("") : `${text.slice(0, 59).join("")}…`;
}

const unwrap = (value) => (TYPES.object(value) && Object.keys(value).length === 1 && Object.hasOwn(value, WRAPPER) ? value[WRAPPER] : value);

/** `value` written as JSON type `t`, where only its form differs from it; NO where more than its form does. */
function asType(value, t) {
  if (t === "array") {
    const inner = unwrap(value);
    if (inner !== value) return Array.isArray(inner) ? inner : [inner];
    if (typeof value === "string") {
      const text = value.trim();
      if (text.startsWith("[")) {
        const list = parsed(text);
        return Array.isArray(list) ? list : NO;
      }
      return text && !LIST_MARKS.test(text) ? [value] : NO;
    }
    return typeof value === "number" ? [value] : NO;
  }
  if (t === "object") {
    const object = typeof value === "string" && value.trim().startsWith("{") ? parsed(value) : NO;
    return TYPES.object(object) ? object : NO;
  }
  let inner = unwrap(value); // one value, written inside {"item": …} or as a list of one
  if (Array.isArray(inner) && inner.length === 1) [inner] = inner;
  if (inner === null || typeof inner === "object") return NO;
  const text = typeof inner === "string" ? inner.trim() : null;
  if (t === "integer") {
    if (typeof inner === "number") return Number.isInteger(inner) ? inner : NO;
    return text !== null && INTEGER.test(text) ? Number(text) : NO;
  }
  if (t === "number") {
    if (typeof inner === "number") return inner;
    return text !== null && NUMBER.test(text) && Number.isFinite(Number(text)) ? Number(text) : NO;
  }
  if (t === "boolean") {
    if (typeof inner === "boolean") return inner;
    return text !== null && ["true", "false"].includes(text.toLowerCase()) ? text.toLowerCase() === "true" : NO;
  }
  if (t === "string") {
    if (typeof inner === "string") return inner;
    if (typeof inner === "number") return Number.isInteger(inner) ? BigInt(inner).toString() : String(inner);
  }
  return NO;
}

/** An enumerated word written in another case ("OFF" for off). */
function enumerated(value, schema, path, repairs) {
  const members = schema.enum;
  if (typeof value !== "string" || !Array.isArray(members) || members.includes(value)) return value;
  const same = members.filter((m) => typeof m === "string" && m.toLowerCase() === value.trim().toLowerCase());
  if (same.length !== 1) return value;
  repairs.push(`${path}: ${show(value)} → ${show(same[0])}`);
  return same[0];
}

/** `value` with its properties or items coerced (the same object when none changes). */
function within(value, schema, path, repairs) {
  if (TYPES.object(value)) {
    const props = schema.properties || {};
    const extra = schema.additionalProperties;
    let out = null;
    for (const [key, item] of Object.entries(value)) {
      const sub = Object.hasOwn(props, key) ? props[key] : TYPES.object(extra) ? extra : null;
      if (sub === null) continue;
      const fixed = coerceAt(item, sub, `${path}.${key}`, repairs);
      if (fixed !== item) (out ||= { ...value })[key] = fixed;
    }
    return out || value;
  }
  if (Array.isArray(value) && TYPES.object(schema.items)) {
    let out = null;
    value.forEach((item, i) => {
      const fixed = coerceAt(item, schema.items, `${path}[${i}]`, repairs);
      if (fixed !== item) (out ||= [...value])[i] = fixed;
    });
    return out || value;
  }
  return value;
}

function coerceAt(value, schema, path, repairs) {
  if (!TYPES.object(schema)) return value;
  if (schema.anyOf) {
    if (schema.anyOf.some((s) => !validate(value, s, path).length)) return value;
    for (const branch of schema.anyOf) {
      const found = [];
      const fixed = coerceAt(value, branch, path, found);
      if (fixed !== value && !validate(fixed, branch, path).length) {
        repairs.push(...found);
        return fixed;
      }
    }
    return value;
  }
  const expected = schema.type;
  const types = typeof expected === "string" ? [expected] : Array.isArray(expected) ? expected.filter((t) => typeof t === "string") : [];
  if (types.length && !types.some((t) => TYPES[t]?.(value))) {
    for (const t of types) {
      let fixed = asType(value, t);
      if (fixed === NO) continue;
      const found = [];
      fixed = enumerated(within(fixed, schema, path, found), schema, path, found);
      if (!validate(fixed, schema, path).length) {
        repairs.push(`${path}: ${show(value)} → ${show(fixed)}`, ...found.filter((r) => !r.startsWith(`${path}: `)));
        return fixed;
      }
    }
    return value;
  }
  return enumerated(within(value, schema, path, repairs), schema, path, repairs);
}

/** coerce: `instance` in the form `schema` declares where only its form differs, and what was repaired, one line a value
 * ($.limit: "40" → 40) — never its meaning: whatever else is wrong is left as it is (the same object when nothing
 * changes), for validate to report. */
export function coerce(instance, schema) {
  const repairs = [];
  return { value: coerceAt(instance, schema, "$", repairs), repairs };
}

function label(schema) {
  if (!TYPES.object(schema)) return "any";
  if (schema.anyOf) return [...new Set(schema.anyOf.map(label))].join(" or ");
  const t = schema.type;
  let out = String(t || "any");
  if (Array.isArray(t)) out = t.map(String).join(" or ");
  else if (t === "array") out = TYPES.object(schema.items) ? `list of ${label(schema.items)}` : "list";
  const members = schema.enum;
  if (Array.isArray(members) && members.length) {
    const shown = members.slice(0, 6).map((m) => (typeof m === "string" ? m : JSON.stringify(m)));
    out += `: ${shown.join(" | ")}${members.length > 6 ? " | …" : ""}`;
  }
  return out;
}

/** signature: what an object schema takes, as a model reads it in an error — the required parameters first, then the
 * others in their order (passage_id (string, required); k (integer); aliases (string: auto | off)). */
export function signature(schema, { limit = 14 } = {}) {
  const props = schema.properties || {};
  const required = (schema.required || []).filter((k) => Object.hasOwn(props, k));
  const names = [...required, ...Object.keys(props).filter((k) => !required.includes(k))];
  if (!names.length) return "no parameters";
  const parts = names.slice(0, limit).map((k) => `${k} (${label(props[k])}${required.includes(k) ? ", required" : ""})`);
  if (names.length > limit) parts.push(`… ${names.length - limit} more`);
  return parts.join("; ");
}

/** The keys of `instance` that an object schema naming its properties does not name (and takes no others). */
export function unknownProperties(instance, schema) {
  const props = schema.properties;
  if (!TYPES.object(instance) || !TYPES.object(props) || ![undefined, null, false].includes(schema.additionalProperties)) return [];
  return Object.keys(instance).filter((k) => !Object.hasOwn(props, k));
}

/** fit_arguments: a model's arguments for `tool`, repaired where only their form was wrong, what was repaired, and the
 * error to send back where they still do not fit — what validate finds, then the parameters the tool does not have —
 * followed by what the tool takes, so that the model can correct the call in one step. */
export function fitArguments(args, schema, tool) {
  const takes = () => `${tool} takes: ${signature(schema)}`;
  if (!TYPES.object(args)) return { args: {}, repaired: [], problem: `invalid arguments: $: expected object, got ${pyType(args)} · ${takes()}` };
  const { value, repairs } = coerce(args, schema);
  const errors = [...validate(value, schema), ...unknownProperties(value, schema).map((k) => `$: unknown parameter '${k}'`)];
  return { args: value, repaired: repairs, problem: errors.length ? `invalid arguments: ${errors.slice(0, 5).join("; ")} · ${takes()}` : null };
}
