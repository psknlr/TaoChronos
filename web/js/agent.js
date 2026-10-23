// The agent loop: the model answers or asks for tools; the runtime runs them; their results go back; until the model
// answers.  The model is the user's own (their key, their provider); the tools are TaoChronos's.
//
// History discipline.  Each assistant turn keeps the exact messages its provider produced (`wire`) — some providers
// require their reasoning_details back, Claude its thinking blocks — and is replayed verbatim to the same provider.  A
// turn made by another provider is replayed as plain text; reasoning fields a provider does not understand are dropped;
// a tool call that never got its result (a stopped turn) is answered with a note; and tool results of earlier turns are
// shortened.

import * as openai from "./llm/openai.js";
import * as claude from "./llm/anthropic.js";
import { dataNote } from "./mydata.js";
import { sleep } from "./util.js";
import { T } from "./i18n.js";

const OLD_RESULT_CHARS = 2500;
const MAX_EXTRA_ROUNDS = 1;

export const formatOf = (provider) => (provider.format === "anthropic" ? "anthropic" : "openai");

/** A user message as the model reads it: its text, and what it knows of the datasets the message carries (the page
 * shows them as chips; the model reads their shape, and the 我的资料 tools read the rest). */
export const userText = (m) => (m.text || "") + dataNote(m.data);
const lib = (format) => (format === "anthropic" ? claude : openai);

/** The messages of earlier turns, in the wire format of `provider`. */
export function buildHistory(messages, provider) {
  const format = formatOf(provider);
  const out = [];
  for (const m of messages) {
    if (m.role === "user") { out.push(lib(format).userMessage(userText(m), m.images || [])); continue; }
    if (m.role !== "assistant") continue;
    if (m.wire?.length && m.wireFormat === format) {
      out.push(...prepareWire(m.wire, format, m.wireProvider === provider.id ? provider : null));
    } else { // the answer that stands: not one the self-check had rewritten (自查)
      const text = (m.segments || []).filter((s) => s.type === "text" && !s.superseded).map((s) => s.text).join("\n\n").trim();
      if (text) out.push({ role: "assistant", content: text });
    }
  }
  return out;
}

function prepareWire(wire, format, sameProvider) {
  const copy = structuredClone(wire);
  for (const msg of copy) {
    if (format === "openai" && msg.role === "assistant") {
      if (!(sameProvider && sameProvider.reasoning === "reasoning_details")) delete msg.reasoning_details;
      delete msg.reasoning_content; // earlier turns' reasoning is not sent back (DeepSeek requires this)
      delete msg.reasoning;
    }
    if (format === "openai" && msg.role === "tool") msg.content = shorten(msg.content);
    if (format === "anthropic" && msg.role === "user" && Array.isArray(msg.content)) {
      for (const block of msg.content) if (block.type === "tool_result" && typeof block.content === "string") block.content = shorten(block.content);
    }
  }
  return answerDangling(copy, format);
}

function shorten(text) {
  if (typeof text !== "string" || text.length <= OLD_RESULT_CHARS) return text;
  return text.slice(0, OLD_RESULT_CHARS) + T`…［早先的工具结果已截短，原长 ${text.length} 字符；需要细节时请重新调用工具］`;
}

/** A turn's messages without the model's reasoning: reasoning fields, thinking blocks, a leading <think>…</think>. */
export function withoutReasoning(wire) {
  return structuredClone(wire || []).map((msg) => {
    if (msg.role !== "assistant") return msg;
    delete msg.reasoning_details;
    delete msg.reasoning_content;
    delete msg.reasoning;
    if (typeof msg.content === "string") msg.content = msg.content.replace(/^\s*<think>[\s\S]*?(<\/think>\s*|$)/, "");
    if (Array.isArray(msg.content)) msg.content = msg.content.filter((b) => b.type !== "thinking" && b.type !== "redacted_thinking");
    return msg;
  });
}

/** Every tool call must have its result before the conversation goes on. */
export function answerDangling(msgs, format) {
  const out = [];
  for (let i = 0; i < msgs.length; i++) {
    const msg = msgs[i];
    out.push(msg);
    if (format === "openai" && msg.role === "assistant" && msg.tool_calls?.length) {
      const answered = new Set();
      let j = i + 1;
      while (j < msgs.length && msgs[j].role === "tool") { answered.add(msgs[j].tool_call_id); out.push(msgs[j]); j++; }
      for (const tc of msg.tool_calls) if (!answered.has(tc.id)) out.push({ role: "tool", tool_call_id: tc.id, content: T("（此调用已中止，没有结果）") });
      i = j - 1;
    }
    if (format === "anthropic" && msg.role === "assistant" && Array.isArray(msg.content)) {
      const ids = msg.content.filter((b) => b.type === "tool_use").map((b) => b.id);
      if (!ids.length) continue;
      const next = msgs[i + 1];
      const got = new Set(next?.role === "user" && Array.isArray(next.content) ? next.content.filter((b) => b.type === "tool_result").map((b) => b.tool_use_id) : []);
      const missing = ids.filter((id) => !got.has(id));
      if (!missing.length) continue;
      const blocks = missing.map((id) => ({ type: "tool_result", tool_use_id: id, content: T("（此调用已中止，没有结果）"), is_error: true }));
      if (next?.role === "user" && Array.isArray(next.content)) next.content = [...next.content, ...blocks];
      else out.push({ role: "user", content: blocks });
    }
  }
  return out;
}

// the self-check (自查) asks for a rewrite only while the turn has this many rounds of tools left: room to look it up
const REVIEW_ROOM = 2;

/** The self-check's note to the model: the passages its answer cites that the corpus has not, and what to do with
 * them — look each up with the tools, or drop what rests on it — before it answers again, whole. */
export function reviewNote(missing) {
  return T`［自查：回答所引的 ${missing.map((pid) => `[[${pid}]]`).join(T("、"))} 在语料中查无此段。请用工具检索核实：找到原文的，改引工具返回的段落号，并照原文引用；找不到的，删去依据它的论断，或说明本语料未检得。然后重新给出完整的回答。］`;
}

/**
 * Run one user turn.  `hooks` receive the answer as it forms:
 *   round(n) · thinking(delta) · text(fullText) · toolPending(index, name) · toolStart(call) · toolProgress(call, p) ·
 *   toolEnd(call, outcome) · retry(attempt, error) · usage(u) · review(missing) · reviewCut(error)
 * `review(text)`, when given, is the page's self-check of an answer (自查): the passages it cites that the corpus has
 * not.  Once a turn, while REVIEW_ROOM rounds of tools are left, the model is told of them and answers again; a rewrite
 * that does not come — an error, a stop, the limit — is taken out of the turn, and the answer it was about stands.
 * Returns {wire, rounds, usage, model}.
 */
export async function runTurn({ provider, settings, route, runtime, tools, system, history, user, signal, hooks, sink, review }) {
  const format = formatOf(provider);
  const L = lib(format);
  const userWire = L.userMessage(userText(user), user.images || []);
  const turn = sink || []; // the caller keeps what finished, even if the turn is stopped
  const usage = { input: 0, output: 0 };
  let round = 0;
  let model = provider.model;
  const maxSteps = Math.max(1, Number(settings.maxSteps) || 16);
  let checked = -1; // while the model rewrites an answer for the self-check: where the note to it went into the turn
  const cut = (err) => { turn.length = checked; checked = -1; hooks.reviewCut?.(err); };

  for (;;) {
    if (signal.aborted) break;
    round++;
    hooks.round?.(round);
    const messages = format === "openai"
      ? [{ role: "system", content: system }, ...history, userWire, ...turn]
      : [...history, userWire, ...turn];
    let res;
    try {
      res = await withRetry(() => (format === "anthropic" ? claude.streamClaude : openai.streamChat)({
        provider, system, messages, tools, settings, route, signal,
        onEvent: (ev) => {
          if (ev.type === "thinking") hooks.thinking?.(ev.delta);
          else if (ev.type === "text") hooks.text?.(ev.text);
          else if (ev.type === "tool") hooks.toolPending?.(ev.index, ev.name);
        },
      }), { signal, onRetry: hooks.retry });
    } catch (err) {
      if (checked < 0) throw err;
      const stopped = err?.name === "AbortError" || signal.aborted;
      cut(stopped ? null : err); // a rewrite that failed ends the turn with the answer it was about
      if (stopped) throw err;
      break;
    }
    turn.push(res.message);
    if (res.model) model = res.model;
    if (res.usage) { usage.input += res.usage.input || 0; usage.output += res.usage.output || 0; hooks.usage?.(usage); }
    hooks.assistant?.(res, round);
    if (!res.toolCalls.length && !signal.aborted) {
      if (checked >= 0) { checked = -1; break; } // rewritten
      const missing = review && maxSteps - round >= REVIEW_ROOM ? (await review(res.text || "").catch(() => null)) || [] : [];
      if (missing.length && !signal.aborted) {
        checked = turn.length;
        hooks.review?.(missing);
        turn.push(L.userMessage(reviewNote(missing)));
        continue;
      }
    }
    if (!res.toolCalls.length || signal.aborted) break;

    const over = round > maxSteps;
    const results = await Promise.all(res.toolCalls.map((tc) => execute(tc, { runtime, settings, hooks, signal, over })));
    turn.push(...L.toolResultMessages(results));
    if (round > maxSteps + MAX_EXTRA_ROUNDS) {
      hooks.limit?.(maxSteps);
      break;
    }
  }
  if (checked >= 0) cut(null); // stopped, or out of rounds, before the rewrite came
  return { wire: turn, rounds: round, usage, model };
}

async function withRetry(fn, { signal, onRetry }) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (err) {
      if (err?.name === "AbortError" || signal.aborted) throw err;
      if (!err?.retryable || attempt >= 2) throw err;
      onRetry?.(attempt + 1, err);
      await sleep(attempt ? 4000 : 1500);
    }
  }
}

async function execute(tc, { runtime, settings, hooks, signal, over }) {
  const call = { id: tc.id, name: tc.name, args: tc.arguments, started: Date.now(), status: "running" };
  hooks.toolStart?.(call);
  let out;
  try {
    if (over) {
      out = { ok: false, error: T("已达到本轮工具调用的上限：请根据已有结果直接作答。"), text: T("ERROR: 已达到本轮工具调用的上限：请根据已有结果直接作答。") };
    } else if (tc.error) {
      out = { ok: false, error: tc.error, text: T`ERROR: ${tc.error}（原始参数：${tc.rawArguments.slice(0, 300)}）` };
    } else if (tc.name === "taochronos_research") {
      out = await runtime.research(tc.arguments, {
        maxChars: settings.resultChars, signal,
        onProgress: (p) => hooks.toolProgress?.(call, p),
      });
    } else {
      out = await runtime.call(tc.name, tc.arguments, { maxChars: settings.resultChars, signal });
    }
  } catch (err) {
    if (err?.name === "AbortError") out = { ok: false, error: T("已停止"), text: T("ERROR: 调用已停止") };
    else out = { ok: false, error: err.message || String(err), text: `ERROR: ${err.message || err}` };
  }
  out ||= { ok: false, error: T("没有结果"), text: T("ERROR: 没有结果") };
  hooks.toolEnd?.(call, out);
  return { id: tc.id, ok: Boolean(out.ok), text: out.text || (out.ok ? "{}" : `ERROR: ${out.error}`) };
}

/** Tool definitions in the neutral form both clients take: {name, description, parameters}. */
export function toolDefs(catalog) {
  return (catalog?.tools || []).map((t) => ({ name: t.name, description: t.description, parameters: t.parameters }));
}
