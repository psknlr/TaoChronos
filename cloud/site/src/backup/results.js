// A tool's outcome as the page receives it (taochronos.chat.results and ChatRuntime's shape): a compact text for the
// model, the value for the interface, the passages it cites, a few words for the tool card.  Ported line by line: the
// page checks each [[passage_id]] the model writes against these citations.

const CARD_FIELDS = ["passage_id", "book_id", "title", "dynasty", "year", "period", "locator"];
const TEXT_FIELDS = ["quote", "text"];
// (items kept per list, characters kept per string), from loose to tight
const LEVELS = [[40, 1600], [24, 800], [12, 400], [8, 220], [5, 140], [3, 90]];

/** Python's len(): code points, not UTF-16 units. */
export const cpLength = (s) => {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 0xd800 || c > 0xdbff) n++;
  }
  return n;
};
export const cpSlice = (s, end) => (s.length <= end ? s : Array.from(s).slice(0, end).join(""));

function isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function trim(value, items, chars, depth = 0) {
  if (depth > 10) return "…";
  if (Array.isArray(value)) {
    const head = value.slice(0, items).map((v) => trim(v, items, chars, depth + 1));
    if (value.length > items) head.push(`…（另有 ${value.length - items} 项未显示）`);
    return head;
  }
  if (isPlainObject(value)) {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = trim(v, items, chars, depth + 1);
    return out;
  }
  if (typeof value === "string" && value.length > chars) {
    const n = cpLength(value);
    if (n > chars) return `${cpSlice(value, chars)}…（共 ${n} 字）`;
  }
  return value;
}

export const dumps = (value) => JSON.stringify(value);

/** cpLength(text) <= max, counting only when the UTF-16 length leaves it open (a code point is one or two units). */
const fits = (text, max) => text.length <= max || (text.length <= 2 * max && cpLength(text) <= max);

/** The result as the model reads it: JSON, trimmed evenly until it fits maxChars (`dumped`: dumps(value), if made). */
export function compact(value, maxChars = 16000, dumped = null) {
  let text = dumped ?? dumps(value);
  if (fits(text, maxChars)) return text;
  for (const [items, chars] of LEVELS) {
    text = dumps(trim(value, items, chars));
    if (fits(text, maxChars)) return text;
  }
  return `${cpSlice(text, maxChars)}…［截断：原长 ${cpLength(text)} 字符］`;
}

/** The result as the interface shows it: whole when small enough, trimmed (still valid JSON) otherwise. */
export function forInterface(value, maxChars = 400_000, dumped = null) {
  if (fits(dumped ?? dumps(value), maxChars)) return value;
  for (const [items, chars] of [[200, 4000], [80, 2000], [30, 800], [10, 300]]) {
    const trimmed = trim(value, items, chars);
    if (fits(dumps(trimmed), maxChars)) return trimmed;
  }
  return { note: "结果过大，界面只显示摘要", preview: cpSlice(dumped ?? dumps(value), 4000) };
}

/** Every passage a result names: {passage_id, title, dynasty, year, locator, text} as far as the result says. */
export function citations(value, limit = 120) {
  const found = new Map();
  const visit = (node, depth) => {
    if (depth > 14 || found.size >= limit) return;
    if (Array.isArray(node)) {
      for (const child of node.slice(0, 600)) visit(child, depth + 1);
    } else if (isPlainObject(node)) {
      const pid = node.passage_id;
      if (typeof pid === "string" && pid) {
        const card = {};
        for (const k of CARD_FIELDS) if (node[k] !== null && node[k] !== undefined && node[k] !== "") card[k] = node[k];
        for (const k of TEXT_FIELDS) {
          if (typeof node[k] === "string" && node[k]) {
            card.text = cpSlice(node[k], 240);
            break;
          }
        }
        const old = found.get(pid);
        if (!old) found.set(pid, card);
        else {
          for (const [k, v] of Object.entries(card)) {
            if (k !== "text") {
              if (!(k in old)) old[k] = v;
            } else if (cpLength(v) > cpLength(old.text || "")) old.text = v;
          }
        }
      }
      for (const child of Object.values(node)) visit(child, depth + 1);
    }
  };
  visit(value, 0);
  return [...found.values()].slice(0, limit);
}

const LIST_KEYS = ["hits", "groups", "witnesses", "entries", "items", "results", "records", "cases", "passages", "claims", "edges",
  "rows", "senses", "fragments", "pairs", "studies", "statements", "atoms", "nodes"];

/** A few words for the tool card: how much came back. */
export function summarize(result) {
  if (Array.isArray(result)) return `${result.length} 项`;
  if (isPlainObject(result)) {
    if (Array.isArray(result.hits)) return `${result.hits.length} 条命中`;
    for (const key of LIST_KEYS) if (Array.isArray(result[key])) return `${result[key].length} 项（${key}）`;
    const keys = Object.keys(result).filter((k) => !k.startsWith("_"));
    return `字段：${keys.slice(0, 6).join("、")}${keys.length > 6 ? "…" : ""}`;
  }
  if (result === null || result === undefined) return "无结果";
  return cpSlice(String(result), 80);
}

/** ChatRuntime's shape: {ok, tool, duration_ms, text, result, citations, summary, receipt} or the error. */
export function shape(tool, ok, result, error = null, { durationMs = 0, maxChars = 16000, receipt = {}, dumped = null } = {}) {
  const out = { ok, tool, duration_ms: Math.round(durationMs * 10) / 10 };
  if (ok) {
    const text = dumped ?? dumps(result ?? null); // serialised once for the model's text and the interface's check
    Object.assign(out, { text: compact(result, maxChars, text), result: forInterface(result, 400_000, text), citations: citations(result),
      summary: summarize(result), receipt });
  } else {
    Object.assign(out, { text: `ERROR: ${error}`, error, summary: cpSlice(error || "", 160), citations: [] });
  }
  return out;
}
