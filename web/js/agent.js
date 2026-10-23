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
import { T } from "./i18n.js";

const OLD_RESULT_CHARS = 2500;
const MAX_EXTRA_ROUNDS = 1;
// the last rounds of tools a turn may run are named to the model, with what it has left, so that it answers in time
const BUDGET_ROUNDS = 3;
// a reply that broke off, a service busy for a moment: the round is asked again, after these waits (or as long as the
// service asks, up to MAX_RETRY_WAIT: a refusal that asks for longer is not waited for)
const RETRY_WAITS = [1500, 4000, 10000];
const MAX_RETRY_WAIT = 30000;
// a reply that stopped at its output limit (finish_reason length, stop_reason max_tokens): an answer is written on from
// where it stopped, and one that spent all of it on thinking is asked again with less of it — this many times a turn
const CUT = new Set(["length", "max_tokens"]);
const MAX_CONTINUATIONS = 2;
// Claude's word for a reply that filled the model's context window: no more of it would fit, so it is not written on
const FULL = "model_context_window_exceeded";

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
 *   toolEnd(call, outcome) · retry(attempt, error) · usage(u) · continued(what) · cut(why) · review(missing) ·
 *   reviewCut(error)
 * A turn ends on a reply the service says is complete; a reply cut at the output limit is written on ("answer": the next
 * round's text continues this one's) or asked again with less thinking ("thinking": what the round showed goes), up to
 * MAX_CONTINUATIONS times, and is told by cut("answer" | "thinking") when it still stops there; cut("context") tells a
 * reply that filled the model's context window, cut("filtered") one the service's content filter stopped.  No call of a
 * cut reply runs.
 * `review(text)`, when given, is the page's self-check of an answer (自查): the passages it cites that the corpus has
 * not — in the whole answer, when it was written on in parts.  Once a turn, while REVIEW_ROOM rounds of tools are left,
 * the model is told of them and answers again; a rewrite that does not come whole — an error, a stop, the limit, a cut
 * at the output limit, the content filter — is taken out of the turn, and the answer it was about stands.
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
  let continued = 0; // rounds that took up a reply cut at the output limit: they spend none of the turn's rounds of tools
  let lighter = null; // the settings a round is asked again with: the last reply spent its whole output on thinking
  let written = ""; // what an answer cut at the output limit said in the rounds before the one writing it on
  let checked = -1; // while the model rewrites an answer for the self-check: where the note to it went into the turn
  const uncheck = (err) => { turn.length = checked; checked = -1; hooks.reviewCut?.(err); };

  for (;;) {
    if (signal.aborted) break;
    round++;
    hooks.round?.(round);
    const asked = lighter || settings;
    lighter = null;
    const messages = format === "openai"
      ? [{ role: "system", content: system }, ...history, userWire, ...turn]
      : [...history, userWire, ...turn];
    let res;
    try {
      res = await withRetry(() => (format === "anthropic" ? claude.streamClaude : openai.streamChat)({
        provider, system, messages, tools, settings: asked, route, signal,
        onEvent: (ev) => {
          if (ev.type === "thinking") hooks.thinking?.(ev.delta);
          else if (ev.type === "text") hooks.text?.(ev.text);
          else if (ev.type === "tool") hooks.toolPending?.(ev.index, ev.name);
        },
      }), { signal, onRetry: hooks.retry });
    } catch (err) {
      if (checked < 0) throw err;
      const stopped = err?.name === "AbortError" || signal.aborted;
      uncheck(stopped ? null : err); // a rewrite that failed ends the turn with the answer it was about
      if (stopped) throw err;
      break;
    }
    if (res.model) model = res.model;
    if (res.usage) { usage.input += res.usage.input || 0; usage.output += res.usage.output || 0; hooks.usage?.(usage); }
    const full = res.finishReason === FULL;
    const cut = full || CUT.has(res.finishReason);
    const answered = Boolean((res.text || "").trim());
    const less = answered ? null : lessThinking(format, provider, asked);
    if (cut && !full && !res.toolCalls.length && !signal.aborted && continued < MAX_CONTINUATIONS && (answered || less)) {
      continued++;
      if (answered) {
        written += res.text || "";
        turn.push(res.message, L.userMessage(T("［提示：上面的回答在输出上限处被截断了。请从截断处接着写下去：不要重复已写的内容，不要加开场白，也不要从头再来。］")));
        hooks.assistant?.(res, round);
        hooks.continued?.("answer");
      } else {
        lighter = less; // the reply is not kept: its round is asked again
        hooks.continued?.("thinking");
      }
      continue;
    }
    turn.push(res.message);
    hooks.assistant?.(res, round);
    const filtered = res.finishReason === "content_filter";
    if (checked >= 0 && (filtered || full || !res.toolCalls.length || signal.aborted)) {
      // the rewrite's end: it stands when it came whole; one cut short, stopped or filtered is taken out, and the answer
      // it was about stands
      if (cut || filtered || signal.aborted) uncheck(null);
      else checked = -1;
      break;
    }
    // the content filter stopped it, or nothing more fits: its calls do not run, and the turn ends with what it has
    if (filtered || full) {
      hooks.cut?.(full ? "context" : "filtered");
      break;
    }
    if (!res.toolCalls.length || signal.aborted) {
      if (cut) {
        hooks.cut?.(answered ? "answer" : "thinking");
      } else if (review && !signal.aborted && maxSteps - (round - continued) >= REVIEW_ROOM) {
        // the self-check, of the whole answer: one that cites passages the corpus has not is told of them, and answers
        // again
        const missing = (await review(written + (res.text || "")).catch(() => null)) || [];
        if (missing.length && !signal.aborted) {
          checked = turn.length;
          written = "";
          hooks.review?.(missing);
          turn.push(L.userMessage(reviewNote(missing)));
          continue;
        }
      }
      break;
    }
    written = "";

    const steps = round - continued;
    const over = steps > maxSteps;
    const results = await Promise.all(res.toolCalls.map((tc) => execute(tc, { runtime, settings, hooks, signal, over, cut })));
    if (!over) results[results.length - 1].text += budgetNote(maxSteps - steps);
    turn.push(...L.toolResultMessages(results));
    if (steps > maxSteps + MAX_EXTRA_ROUNDS) {
      hooks.limit?.(maxSteps);
      break;
    }
  }
  if (checked >= 0) uncheck(null); // stopped, or out of rounds, before the rewrite came
  return { wire: turn, rounds: round, usage, model };
}

/** The settings to ask a round again with when its reply spent all of its output on thinking — none where it cannot be
 * asked with less: a service with its own field for no thinking is asked without it; Claude, which thinks whether asked
 * to or not on its newer models, at low effort. */
export function lessThinking(format, provider, settings) {
  if (format === "anthropic") return settings.effort === "low" ? null : { ...settings, effort: "low" };
  return settings.thinking !== false && provider.thinking_off ? { ...settings, thinking: false } : null;
}

/** What the model is told after a round of tools with `left` rounds of tools to come: nothing before the last
 * BUDGET_ROUNDS, then how many it has left, and at the last that it is to answer. */
export function budgetNote(left) {
  if (left < 0 || left >= BUDGET_ROUNDS) return "";
  return `\n\n${left ? T`［提示：回答这个问题还可再调用 ${left} 轮工具，请在用完之前作答］`
    : T("［提示：回答这个问题的工具调用已用完，请根据已有结果直接作答，不要再调用工具］")}`;
}

/** The milliseconds to wait before asking again after the attempt-th failure (from 0), `err`; null when it is not
 * asked again — it is not retryable, the attempts are spent, or the service asks to wait longer than MAX_RETRY_WAIT.
 * A wait is spread over a quarter either way (`rand`, in [0, 1)), so that pages one failure struck together do not ask
 * again together; never shorter than the service asks. */
export function retryWait(err, attempt, rand = Math.random) {
  if (!err?.retryable || attempt >= RETRY_WAITS.length) return null;
  const asked = Number(err.retryAfter) * 1000 || 0;
  if (asked > MAX_RETRY_WAIT) return null;
  return Math.max(Math.round(RETRY_WAITS[attempt] * (0.75 + 0.5 * rand())), asked);
}

async function withRetry(fn, { signal, onRetry }) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (err) {
      if (err?.name === "AbortError" || signal.aborted) throw err;
      const wait = retryWait(err, attempt);
      if (wait === null) throw err;
      onRetry?.(attempt + 1, err);
      await pause(wait, signal);
      if (signal.aborted) throw new DOMException("aborted", "AbortError"); // stopped while it waited: not asked again
    }
  }
}

/** A wait that ends early when the turn is stopped. */
function pause(ms, signal) {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal?.addEventListener("abort", done, { once: true });
  });
}

async function execute(tc, { runtime, settings, hooks, signal, over, cut }) {
  const call = { id: tc.id, name: tc.name, args: tc.arguments, started: Date.now(), status: "running" };
  hooks.toolStart?.(call);
  let out;
  try {
    if (over) {
      out = { ok: false, error: T("已达到本轮工具调用的上限：请根据已有结果直接作答。"), text: T("ERROR: 已达到本轮工具调用的上限：请根据已有结果直接作答。") };
    } else if (cut) {
      // its arguments may have been cut with the reply: never run
      out = { ok: false, error: T("回复在输出上限处被截断，参数可能不完整，没有执行"),
        text: T("ERROR: 这次回复在输出上限处被截断，调用的参数可能不完整，没有执行。请缩短参数重新调用，或分几次调用。") };
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
