// What a request sends the model, within a budget (point 6 of the proposal).  Each request of a turn sends the system
// instructions, the tools, the conversation so far, the question and the turn's own messages, and leaves room for the
// reply; a turn of many rounds grows with every result, a conversation with every turn.  Past the budget (设置 → 模型 →
// 上下文预算), a request gives up, in this order, until it fits:
//   1. the calls and results of earlier turns, oldest first: those turns go as their question and answer only;
//   2. the whole of the turn's earlier results, oldest round first: each goes compactly — its shape kept and trimmed
//      evenly, every passage it named still named, and a note saying how long it was and how to have it again;
//   3. earlier turns, oldest first, which the model is told were left out;
//   4. the whole of the last round's results.
// What a request gave up stays given up for the rest of the turn, so that each request differs from the one before only
// where it must.  Calls and their results keep their ids and pairs, and the model's reasoning goes as it was.  The page
// keeps everything whole: its steps show the results, citations are checked against them, and 继续作答 and the turns
// after read them.

import { T } from "./i18n.js";

/** The budget, in tokens, where the visitor set none: what Claude's models take, and most other services' models (a
 * hand-set endpoint in Claude's format may serve another's, as outputLimit reckons in providers.js). */
export const CONTEXT_TOKENS = Object.freeze({ claude: 200000, other: 128000 });
const MARGIN = 0.05;        // of the budget, for what the estimate misses
const IMAGE_TOKENS = 1600;  // an image, about, whatever its size as data
const ROOM = 1500;          // the characters a result made compact keeps of itself, about
const IDS = 60;             // the passages a compact result names besides those its trimmed form shows, at most
// how a result is trimmed, from loose to tight — (items kept of a list, characters kept of a string) — as the runtime
// trims one past its own limit (src/taochronos/chat/results.py, LEVELS); an object keeps every field, as there, unless
// it has more than FIELDS (a table, not a record), and a field that says what the result means or lacks (NOTE) keeps
// NOTE_CHARS of its words at least; an identifier is never cut, and a passage met again in the result is named by its
// id and place, with what it is said of there (its fields that are not a card's, CARD, and its words if they differ)
const LEVELS = [[12, 400], [8, 220], [5, 140], [3, 90], [2, 60], [1, 40]];
const FIELDS = 24;
const NOTE = /note|notice|summary|warning|caveat|limit|missing|error|verdict/i;
const NOTE_CHARS = 240;
const ID = /(^|_)id$/;
const CARD = new Set(["passage_id", "book_id", "title", "work", "authors", "dynasty", "year", "years", "period", "category", "kind",
  "layer", "locator", "quote", "text", "span", "source", "license", "punctuation", "labels"]); // tools/common.py, study/base.py

/** Marks the question that begins an earlier turn in a history (agent.js, buildHistory); a symbol, so never sent. */
export const QUESTION = Symbol("question");
/** Marks an earlier turn's first message with the answer that stands, as the page shows it (agent.js, buildHistory): what
 * the turn says as its question and answer — not a first answer the self-check had rewritten (自查). */
export const ANSWER = Symbol("answer");

/** The budget a turn's requests keep within: the number the visitor set, else CONTEXT_TOKENS for its service. */
export function contextBudget(settings, provider) {
  const set = Math.floor(Number(settings?.contextTokens)) || 0;
  if (set > 0) return Math.max(8000, set);
  return CONTEXT_TOKENS[provider?.format === "anthropic" && !provider.custom ? "claude" : "other"];
}

/** The tokens a text takes, estimated high: a Chinese character, or any other wide one, one; three others, one. */
export function tokensOf(text) {
  const s = typeof text === "string" ? text : JSON.stringify(text ?? "") || "";
  let wide = 0;
  for (let i = 0; i < s.length; i++) if (s.charCodeAt(i) >= 0x2e80) wide++;
  return wide + Math.ceil((s.length - wide) / 3);
}

const counted = new WeakMap(); // a message's tokens, once counted: a message is not changed once it is sent

/** The tokens a message takes, estimated high: its JSON, an image counted as IMAGE_TOKENS however long its data. */
export function messageTokens(m) {
  if (counted.has(m)) return counted.get(m);
  let images = 0;
  const text = JSON.stringify(m, (k, v) => {
    if (v && typeof v === "object" && (v.type === "image_url" || v.type === "image")) { images++; return null; }
    return v;
  });
  const n = tokensOf(text) + images * IMAGE_TOKENS;
  if (m && typeof m === "object") counted.set(m, n);
  return n;
}

const sum = (msgs) => msgs.reduce((a, m) => a + messageTokens(m), 0);

/** The first `n` characters of `s`, a character written as two (outside the BMP, as some rare ones are) not split. */
const head = (s, n) => s.slice(0, /[\ud800-\udbff]/.test(s[n - 1] || "") ? n - 1 : n);

function trim(value, items, chars, seen = new Map(), depth = 0) {
  if (depth > 10) return "…";
  const next = (v, n = chars) => trim(v, items, n, seen, depth + 1);
  if (Array.isArray(value)) { // a short one (a range of years, an interval) whole
    const cut = value.length > items && JSON.stringify(value).length > chars;
    const kept = (cut ? value.slice(0, items) : value).map((v) => next(v));
    if (cut) kept.push(T`…（另有 ${value.length - items} 项未显示）`);
    return kept;
  }
  if (value && typeof value === "object") {
    let fields = Object.entries(value);
    const id = typeof value.passage_id === "string" ? value.passage_id : "";
    if (id && seen.has(id)) { // a passage met again: by its id and place, and what is said of it here
      const words = seen.get(id);
      fields = fields.filter(([k, v]) => k === "passage_id" || k === "locator" || !CARD.has(k)
        || ((k === "quote" || k === "text") && v !== words));
    } else if (id) seen.set(id, value.quote ?? value.text);
    const keep = fields.length > FIELDS ? Math.max(items, 8) : fields.length;
    const kept = Object.fromEntries(fields.slice(0, keep).map(([k, v]) => [k, ID.test(k) && typeof v === "string" ? v
      : next(v, NOTE.test(k) ? Math.max(chars, NOTE_CHARS) : chars)]));
    if (fields.length > keep) kept["…"] = T`另有 ${fields.length - keep} 个字段未显示`;
    return kept;
  }
  if (typeof value === "string" && value.length > chars + 10) return head(value, chars) + T`…（共 ${value.length} 字）`;
  return value;
}

/** The passages a result names (its cards' passage_id, a list's passage_ids), once each, in order. */
function passagesOf(value, out = new Set(), depth = 0) {
  if (depth > 12 || !value || typeof value !== "object") return out;
  for (const [k, v] of Array.isArray(value) ? value.entries() : Object.entries(value)) {
    if (k === "passage_id" && typeof v === "string" && v) out.add(v);
    else if (k === "passage_ids" && Array.isArray(v)) for (const id of v) { if (typeof id === "string" && id) out.add(id); }
    else passagesOf(v, out, depth + 1);
  }
  return out;
}

const parsed = (text) => { try { return JSON.parse(text); } catch { return undefined; } };

/**
 * A tool result as a request sends it once it is made compact, in about `room` characters: a JSON result trimmed evenly
 * (its shape kept, every field, long lists and strings cut to their start), with the passages it named that the trimmed
 * form no longer shows; another (an error, a text) its start.  Then a note: how long it was, and how to have it again;
 * then the notes the page added to it (agent.js: what is left of the turn's tools, a call answered from another), as
 * they were.  A result already within `room` is as it was.
 */
export function compactResult(text, room = ROOM) {
  if (typeof text !== "string" || text.length <= room) return text;
  const at = text.indexOf("\n\n［"); // a JSON result holds no line break: the page's notes begin here
  const data = parsed(at < 0 ? text : text.slice(0, at));
  const json = Boolean(data) && typeof data === "object";
  const whole = json && at >= 0 ? text.slice(0, at) : text;
  const notes = json && at >= 0 ? text.slice(at) : "";
  if (whole.length <= room) return text;
  if (!json) return `${head(whole, room)}\n\n${T`［这条工具结果为节省上下文已截短：原长 ${whole.length} 字符，上面是它的开头。需要细节时，请以同样的参数再调用一次］`}`;
  let trimmed;
  let body;
  for (const [items, chars] of LEVELS) {
    trimmed = trim(data, items, chars);
    body = JSON.stringify(trimmed);
    if (body.length <= room) break;
  }
  if (body.length >= whole.length) return text;
  const shown = passagesOf(trimmed);
  const others = [...passagesOf(data)].filter((id) => !shown.has(id));
  const named = others.length
    ? T`；其中还提到这些段落：${others.slice(0, IDS).join(T("、"))}${others.length > IDS ? T`等 ${others.length} 段` : ""}`
    : "";
  return `${body}\n\n${T`［这条工具结果为节省上下文已精简：原长 ${whole.length} 字符；上面保留了它的结构，长的列表和文字只留开头${named}。需要细节时，可按段落号读原文，或以同样的参数再调用一次］`}${notes}`;
}

/** An earlier turn's messages, one list each, from one question to the next. */
function turnsOf(history) {
  const out = [];
  for (const m of history) {
    if (m[QUESTION] || !out.length) out.push([]);
    out[out.length - 1].push(m);
  }
  return out;
}

const answerOf = (m) => (typeof m.content === "string" ? m.content.replace(/^\s*<think>[\s\S]*?(<\/think>\s*|$)/, "")
  : Array.isArray(m.content) ? m.content.filter((b) => b.type === "text").map((b) => b.text).join("") : "");

/** An earlier turn as its question and what its model answered, without its calls, their results or its reasoning:
 * the answer that stands, where the page said it (ANSWER), else what the model said in it. */
function plainTurn([question, ...rest]) {
  const stands = rest.find((m) => typeof m[ANSWER] === "string");
  const said = stands ? stands[ANSWER]
    : rest.filter((m) => m.role === "assistant").map(answerOf).filter((s) => s.trim()).join("\n\n").trim();
  return [question, { role: "assistant", content: said || T("（这一轮没有留下回答）") }];
}

/** The places a turn's messages hold a tool result, each with its round: {i: message, j: block (-1: the message), round}. */
function resultsOf(turn, format) {
  const out = [];
  let round = 0;
  turn.forEach((m, i) => {
    const calls = format === "anthropic" ? Array.isArray(m.content) && m.content.some((b) => b.type === "tool_use") : m.tool_calls?.length;
    if (m.role === "assistant" && calls) round++;
    if (format === "openai" && m.role === "tool" && typeof m.content === "string") out.push({ i, j: -1, round });
    if (format === "anthropic" && m.role === "user" && Array.isArray(m.content)) {
      m.content.forEach((b, j) => { if (b.type === "tool_result" && typeof b.content === "string") out.push({ i, j, round }); });
    }
  });
  return out;
}

/**
 * The next request's earlier turns and the turn's own messages, within `budget` tokens, `fixed` of which the rest of
 * the request takes (instructions, tools, the question, the room left for the reply) — giving up what it must in the
 * order above.  `state` keeps what the turn's requests gave up ({plain, upTo, dropped}), and grows.  Nothing given is
 * changed: what goes otherwise is a copy.  Returns {history, turn, note (for the system instructions: the turns left
 * out), tokens (the request's, estimated), more (whether this request gave up more than the one before)}.
 */
export function fitRequest({ history = [], turn, format, budget, fixed = 0, state = {} }) {
  const before = `${state.plain || 0}/${state.upTo || 0}/${state.dropped || 0}`;
  state.plain ||= 0;
  state.upTo ||= 0;
  state.dropped ||= 0;
  const room = Math.floor(budget * (1 - MARGIN)) - fixed;
  // earlier turns: whole, as question and answer, or left out
  const groups = turnsOf(history).map((whole) => ({ whole, size: sum(whole), plain: null, small: 0 }));
  const plainOf = (g) => { if (!g.plain) { g.plain = plainTurn(g.whole); g.small = sum(g.plain); } return g; };
  const sizeOf = (g, k) => (k < state.dropped ? 0 : k < state.plain ? plainOf(g).small : g.size);
  let past = groups.reduce((a, g, k) => a + sizeOf(g, k), 0);
  // the turn's own: its results whole, or compact
  const sizes = turn.map(messageTokens);
  let now = sizes.reduce((a, b) => a + b, 0);
  const slots = resultsOf(turn, format);
  const last = slots.length ? slots[slots.length - 1].round : 0;
  const copies = new Map();
  const done = new Set(); // the results made compact (each from its own text: a compact one is not made compact again)
  const shrink = (upTo) => {
    for (const { i, j, round } of slots) {
      if (round > upTo || done.has(`${i}/${j}`)) continue;
      done.add(`${i}/${j}`);
      const text = j < 0 ? turn[i].content : turn[i].content[j].content;
      const short = compactResult(text);
      if (short === text) continue;
      const was = copies.get(i) || turn[i];
      const copy = j < 0 ? { ...was, content: short } : { ...was, content: was.content.map((b, k) => (k === j ? { ...b, content: short } : b)) };
      copies.set(i, copy);
      const size = messageTokens(copy);
      now += size - sizes[i];
      sizes[i] = size;
    }
  };
  shrink(state.upTo);
  const over = () => past + now > room;
  while (over() && state.plain < groups.length) { // 1
    const k = state.plain++;
    if (k >= state.dropped) past += plainOf(groups[k]).small - groups[k].size;
  }
  while (over() && state.upTo < last - 1) shrink(++state.upTo); // 2
  while (over() && state.dropped < groups.length) { // 3
    const k = state.dropped++;
    past -= k < state.plain ? plainOf(groups[k]).small : groups[k].size;
  }
  if (over() && state.upTo < last) shrink((state.upTo = last)); // 4
  return {
    history: groups.flatMap((g, k) => (k < state.dropped ? [] : k < state.plain ? plainOf(g).plain : g.whole)),
    turn: copies.size ? turn.map((m, i) => copies.get(i) || m) : turn,
    note: state.dropped ? T`［对话较长：为节省上下文，最早的 ${state.dropped} 轮问答这次没有发送给你。用户提到其中的内容时，请说明你看不到那部分］` : "",
    tokens: fixed + past + now,
    more: `${state.plain}/${state.upTo}/${state.dropped}` !== before,
  };
}
