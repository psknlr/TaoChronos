// The agent loop: the model answers or asks for tools; the runtime runs them; their results go back; until the model
// answers.  The model is the user's own (their key, their provider); the tools are TaoChronos's.
//
// History discipline.  Each assistant turn keeps the exact messages its provider produced (`wire`) — some providers
// require their reasoning_details back, Claude its thinking blocks — and is replayed verbatim to the same provider.  A
// turn made by another provider is replayed as plain text; reasoning fields a provider does not understand are dropped;
// a tool call that never got its result (a stopped turn) is answered with a note; and tool results of earlier turns are
// made compact (context.js: their shape and the passages they name kept), as are the turn's own when its requests would
// go past the context budget.
//
// Waiting.  Each thing a turn waits on has a limit of its own (limits.js): a reply's first byte and its silences, each
// tool call (counted while it runs, not while it waits for its runtime or its turn), a research run, and the turn.  A
// call always ends — ok, error, timeout, stopped, skipped, or (a research run) left to go on by itself — so a round of
// tools never waits on one that will not; and the user can ask for the answer before the calls under way are done.

import * as openai from "./llm/openai.js";
import * as claude from "./llm/anthropic.js";
import { dataNote } from "./mydata.js";
import { compactResult, contextBudget, fitRequest, messageTokens, QUESTION, tokensOf } from "./context.js";
import { LIMITS, limit, pause } from "./limits.js";
import { outputLimit } from "./providers.js";
import { truncate } from "./util.js";
import { T } from "./i18n.js";

const OLD_RESULT_CHARS = 2500; // about, of an earlier turn's tool result
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
    if (m.role === "user") { // marked as a question (context.js), unseen by what reads or sends the message
      out.push(Object.defineProperty(lib(format).userMessage(userText(m), m.images || []), QUESTION, { value: true }));
      continue;
    }
    if (m.role !== "assistant") continue;
    if (m.wire?.length && m.wireFormat === format) {
      out.push(...prepareWire(m.wire, format, m.wireProvider === provider.id ? provider : null));
    } else {
      const text = (m.segments || []).filter((s) => s.type === "text").map((s) => s.text).join("\n\n").trim();
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
    if (format === "openai" && msg.role === "tool") msg.content = compactResult(msg.content, OLD_RESULT_CHARS);
    if (format === "anthropic" && msg.role === "user" && Array.isArray(msg.content)) {
      for (const block of msg.content) {
        if (block.type === "tool_result" && typeof block.content === "string") block.content = compactResult(block.content, OLD_RESULT_CHARS);
      }
    }
  }
  return answerDangling(copy, format);
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

/**
 * Run one user turn.  `hooks` receive the answer as it forms:
 *   round(n) · thinking(delta) · text(fullText) · toolPending(index, name) · toolStart(call) · toolWaiting(call, why) ·
 *   toolRunning(call) · toolProgress(call, p) · toolEnd(call, outcome) · toolLater(call, ending) · retry(attempt, error) ·
 *   usage(u) · continued(what) · cut(why) · limit(maxSteps, why)
 * A turn ends on a reply the service says is complete; a reply cut at the output limit is written on ("answer": the next
 * round's text continues this one's) or asked again with less thinking ("thinking": what the round showed goes), up to
 * MAX_CONTINUATIONS times, and is told by cut("answer" | "thinking") when it still stops there; cut("context") tells a
 * reply that filled the model's context window, cut("filtered") one the service's content filter stopped.  No call of a
 * cut reply runs.
 * `hurry` (a signal): the user asks for the answer now — the calls under way are not waited for, no more run, and the
 * model answers from what it has; so it does when the turn has run its time (limits.turn).  limit(maxSteps, why) tells
 * that the turn's tools came to an end before its answer: "asked" or "time" as they do, "steps" (all its rounds used)
 * when the model asks for more anyway.  `limits`: limits.js's, or some of them changed.
 * Once the turn's tools have come to an end — its rounds used, the answer asked for, its time up — the model is asked
 * for its answer with no tool to call (tool choice "none": a service that refuses a request asking it is asked again
 * without, and not asked so again while the page is open), told which of its calls have no result; a service that calls
 * tools all the same is told no, and the turn ends `unanswered` when it still has not answered.  `resume`: the messages
 * of a turn that did not get its answer (an error, a stop), as the page kept them, taken up again after its `rounds` —
 * no tool runs again, and the model is asked for the answer from the results it has.
 * Each request, with the room its reply has (at most half), keeps within the turn's context budget (context.js:
 * settings.contextTokens, or one for its service): past it, earlier turns go as their questions and answers, the turn's
 * earlier results go compactly, then earlier turns are left out, and last the last round's results go compactly.  A
 * lookup of the corpus (REUSABLE) the turn already made with the same arguments, on the same runtime and corpus
 * (`scope()`, a string naming them), is answered from that call and not run again — so the model has a result made
 * compact whole again by asking for it again.
 * `trace` (an object), when given, is filled as the turn runs with where its time went, for the page's record of the turn
 * (the caller keeps it, even if the turn is stopped); its times are the page's clock (Date.now()):
 *   requests — each model request: its round and attempt; when it was sent, its reply began (`open`), its first part,
 *     its first answer text and its last part came, and it ended; how it finished (`finish`, the service's reason) or why
 *     it failed (`failed`: "stopped", "timeout" with the limit that ended it in `expired`, or the service's error kind or
 *     status — never its words — with its HTTP status in `status`); its tokens (`input`, `output`);
 *   tools — each call: its round, id and tool; how it ended (`status`: ok, error, timeout, stopped, skipped, background,
 *     or refused: not run); when it began, began to wait for its runtime or its turn (`waiting`), began to run, and ended;
 *     how long the runtime says its work took (`compute`);
 *   events — `{at, what}`: a cut answer written on ("continued"), a round asked again with less thinking ("lighter"), the
 *     turn's tools come to an end ("asked", "time", "steps"), a reply cut ("cut:answer", "cut:thinking", "cut:context",
 *     "cut:filtered"), a request that gave up more to keep within the budget ("compacted"), a call answered from the
 *     same call before ("reused").
 * Returns {wire, rounds, usage, model, unanswered}.
 */
export async function runTurn({ provider, settings, route, runtime, tools, system, history, user, signal, hurry, limits, hooks, sink, trace,
  resume, rounds, scope }) {
  const lim = { ...LIMITS, ...limits };
  if (trace) for (const k of ["requests", "tools", "events"]) trace[k] ||= [];
  const quick = new AbortController(); // the turn's tools end early: the user asked for the answer, or its time is up
  let quickWhy = null;
  const answerNow = (why) => { if (!quick.signal.aborted) { quickWhy = why; quick.abort(); } };
  const asked = () => answerNow("asked");
  if (hurry?.aborted) asked();
  else hurry?.addEventListener("abort", asked, { once: true });
  const clock = limit(lim.turn, () => answerNow("time"));
  try {
    return await turnOf({ provider, settings, route, runtime, tools, system, history, user, signal, hooks, sink, trace, lim,
      quick: quick.signal, quickWhy: () => quickWhy, resume, rounds, scope });
  } finally {
    clock.stop();
    hurry?.removeEventListener("abort", asked);
  }
}

async function turnOf({ provider, settings, route, runtime, tools, system, history = [], user, signal, hooks, sink, trace, lim, quick,
  quickWhy, resume, rounds, scope }) {
  const format = formatOf(provider);
  const L = lib(format);
  const userWire = L.userMessage(userText(user), user.images || []);
  const turn = sink || []; // the caller keeps what finished, even if the turn is stopped
  const usage = { input: 0, output: 0 };
  let round = resume?.length ? Math.max(0, Number(rounds) || 0) : 0; // a turn taken up again goes on from its rounds
  let model = provider.model;
  const maxSteps = Math.max(1, Number(settings.maxSteps) || 16);
  let continued = 0; // rounds that took up a reply cut at the output limit: they spend none of the turn's rounds of tools
  let lighter = null; // the settings a round is asked again with: the last reply spent its whole output on thinking
  let closing = null; // why the turn's tools came to an end: "steps" (all its rounds used), "asked", "time", "resume"
  let closedAt = 0;   // the round of tools after which they did
  let told = false;   // the model has been told which of its calls have no result
  const close = (why, at) => {
    [closing, closedAt] = [why, at];
    note(why);
    if (why === "asked" || why === "time") hooks.limit?.(maxSteps, why);
  };
  // the calls of the turn that have no result (they ran out of time, were not waited for, went on in the background or
  // were stopped), by what they asked: one run again with the same arguments that then gave one has its result
  const lacking = new Map();
  // the context budget: what the turn's requests gave up to keep within it, and what each sends besides the
  // conversation and the turn's messages (instructions, tools, question; the reply's room is added as each is asked)
  const budget = contextBudget(settings, provider);
  const fit = {};
  const fixed = tokensOf(system) + tokensOf(tools) + messageTokens(userWire);
  const reuse = new Map(); // the lookups the turn made that gave a result, by what they asked (execute)
  const note = (what) => { trace?.events.push({ at: Date.now(), what }); };
  const cutShort = (why) => { note(`cut:${why}`); hooks.cut?.(why); };
  if (resume?.length && !signal.aborted) { // the turn taken up again: what it had, every call with its result, and its answer asked for
    for (const m of resumed(resume, format)) turn.push(m);
    close("resume", round);
  }

  for (;;) {
    if (signal.aborted) break;
    round++;
    hooks.round?.(round);
    const asked = lighter || settings;
    lighter = null;
    // the room left for the reply: what it may write, within half the budget (and asked for no more), so that the
    // request and its reply keep within the budget together
    const reply = outputLimit(asked, provider);
    const room = Math.min(reply, Math.floor(budget / 2));
    const view = fitRequest({ history, turn, format, budget, fixed: fixed + room, state: fit });
    if (view.more) note("compacted");
    const instructions = view.note ? `${system}\n\n${view.note}` : system;
    const messages = format === "openai"
      ? [{ role: "system", content: instructions }, ...view.history, userWire, ...view.turn]
      : [...view.history, userWire, ...view.turn];
    let attempt = 0;
    const service = `${provider.id} ${provider.baseUrl}`;
    const ask = () => withRetry(() => {
      const mark = trace ? { round, attempt: ++attempt } : null; // where this request's time went
      if (mark) trace.requests.push(mark);
      return measured(mark, (format === "anthropic" ? claude.streamClaude : openai.streamChat)({
        provider, system: instructions, messages, tools, settings: room < reply ? { ...asked, maxTokens: room } : asked, route, signal,
        limits: lim, mark,
        toolChoice: closing && !NO_NONE.has(service) ? "none" : undefined,
        onEvent: (ev) => {
          if (ev.type === "thinking") hooks.thinking?.(ev.delta);
          else if (ev.type === "text") { if (mark && !mark.text) mark.text = Date.now(); hooks.text?.(ev.text); }
          else if (ev.type === "tool") hooks.toolPending?.(ev.index, ev.name);
        },
      }));
    }, { signal, onRetry: hooks.retry });
    let res;
    try {
      res = await ask();
    } catch (err) {
      // a service that refuses a request asking for no tool call: asked again as before (its calls refused instead)
      if (!closing || NO_NONE.has(service) || !(err instanceof openai.ProviderError && REFUSED.has(err.status))) throw err;
      NO_NONE.add(service);
      res = await ask();
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
        turn.push(res.message, L.userMessage(T("［提示：上面的回答在输出上限处被截断了。请从截断处接着写下去：不要重复已写的内容，不要加开场白，也不要从头再来。］")));
        hooks.assistant?.(res, round);
        note("continued");
        hooks.continued?.("answer");
      } else {
        lighter = less; // the reply is not kept: its round is asked again
        note("lighter");
        hooks.continued?.("thinking");
      }
      continue;
    }
    turn.push(res.message);
    hooks.assistant?.(res, round);
    // the content filter stopped it, or nothing more fits: its calls do not run, and the turn ends with what it has
    if (res.finishReason === "content_filter" || full) {
      cutShort(full ? "context" : "filtered");
      break;
    }
    if (!res.toolCalls.length || signal.aborted) {
      if (cut) cutShort(answered ? "answer" : "thinking");
      break;
    }

    const steps = round - continued;
    // before these calls run: all the turn's rounds are used, or the user asked for the answer, or its time ran out
    if (!closing && (steps > maxSteps || quick.aborted)) close(steps > maxSteps ? "steps" : quickWhy(), steps - 1);
    const closed = closing; // the calls of a round asked for after the turn's tools came to an end are not run
    const results = await Promise.all(res.toolCalls.map((tc) => execute(tc, {
      runtime, settings, hooks, signal, quick, quickWhy, limits: lim, closing, cut, trace, round, reuse, scope, note })));
    res.toolCalls.forEach((tc, k) => {
      const key = `${tc.name}\u0000${JSON.stringify(tc.arguments ?? null)}`;
      if (results[k].ok) lacking.delete(key);
      else if (LACKING.has(results[k].status) && !closed) lacking.set(key, { name: tc.name, args: tc.arguments, status: results[k].status });
    });
    const last = results[results.length - 1];
    if (!closing && quick.aborted) { // while they ran
      close(quickWhy(), steps);
      last.text += closingNote(closing, lim);
    } else if (!closing && !signal.aborted) { // (a turn stopped is told nothing: it asks no more)
      last.text += budgetNote(maxSteps - steps);
      if (steps >= maxSteps) close("steps", steps); // all its rounds of tools used: the answer comes next, with none to call
    }
    if (closing && !told) { // the answer is asked for next: what it lacks
      told = true;
      last.text += lackingNote([...lacking.values()]);
    }
    turn.push(...L.toolResultMessages(results));
    if (closing && steps > closedAt + MAX_EXTRA_ROUNDS) { // a service that calls tools however it is asked
      if (closing !== "resume") hooks.limit?.(maxSteps, closing);
      return { wire: turn, rounds: round, usage, model, unanswered: true };
    }
  }
  return { wire: turn, rounds: round, usage, model, unanswered: false };
}

// how a call ends with no result the model can answer from: it ran out of time, was not waited for, goes on by itself
// in the background, or was stopped (execute)
const LACKING = new Set(["timeout", "skipped", "background", "stopped"]);
// the lookups a turn may answer from the same call made before (execute): they read the corpus, or reckon from it, and
// change nothing — not the analyses, images, a research run or its sessions, the catalog, Code Mode, or the user's data
// (我的资料), which run each time
const REUSABLE = /^(classics|kg|study|validation|audit|modern)(__|\.)/;
/** A call's arguments as JSON, the fields of each object in order: the same arguments, however a model orders them. */
const stable = (args) => JSON.stringify(args ?? null, (k, v) => (v && typeof v === "object" && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map((f) => [f, v[f]])) : v));
/** What a call asks, when it is a lookup a turn may answer from the same one made before (REUSABLE, called directly or
 * through taochronos_call): its name and arguments; null for any other call. */
const lookupOf = (tc) => (REUSABLE.test(tc.name === "taochronos_call" ? String(tc.arguments?.tool ?? "") : tc.name)
  ? `${tc.name}\u0000${stable(tc.arguments)}` : null);
// the services (by id and address) that refused a request asking for no tool call, while the page is open — not every
// one takes tool choice "none" — and the statuses a request's refusal comes with
const NO_NONE = new Set();
const REFUSED = new Set([400, 422]);

/** What the model is told, as its answer is asked for, of its calls that have no result: each by its name, what it
 * asked (cut short) and how it ended, and that it is to say what is missing rather than make it up. */
export function lackingNote(calls) {
  if (!calls.length) return "";
  const word = (status) => ({ timeout: T("超时"), skipped: T("没有等到"), background: T("仍在后台运行"), stopped: T("已停止") })[status];
  const named = (c) => T`${`${c.name} ${truncate(JSON.stringify(c.args ?? {}), 80)}`}（${word(c.status)}）`;
  return `\n\n${T`［这些调用没有得到结果：${calls.map(named).join(T("、"))}。回答时请说明缺了哪些结果，不要编造它们的内容］`}`;
}

/** What the model is told when the user takes up a turn that did not get its answer (resume). */
export const resumeNote = () => T("［提示：上一次作答没有完成，工具不再调用。请根据上面已有的工具结果直接作答；没有得到的结果，请在回答中说明缺了什么，不要编造］");

/** A turn's messages end on its tools' results (or on a reply whose calls have none, which answerDangling gives them):
 * its answer can be asked for from them (resume). */
export function resumable(wire, format) {
  const last = (wire || []).at(-1);
  if (format === "anthropic") {
    return Array.isArray(last?.content) && last.content.some((b) => b.type === (last.role === "user" ? "tool_result" : "tool_use"));
  }
  return last?.role === "tool" || Boolean(last?.role === "assistant" && last.tool_calls?.length);
}

/** A turn's messages as the page kept them (resumable), taken up again: every call with its result (answerDangling),
 * and after the last of them the note asking for the answer.  What the page kept is not changed. */
export function resumed(wire, format) {
  const msgs = answerDangling(structuredClone(wire), format);
  const note = `\n\n${resumeNote()}`;
  const last = msgs.at(-1);
  if (format === "anthropic") {
    const block = last.content.at(-1);
    block.content = typeof block.content === "string" ? block.content + note : [...(block.content || []), { type: "text", text: note }];
  } else {
    last.content = `${last.content ?? ""}${note}`;
  }
  return msgs;
}

/** A model request, its end told to its `mark` (when it has one): how it finished and its tokens, or why it failed. */
async function measured(mark, request) {
  try {
    const res = await request;
    if (mark) Object.assign(mark, { end: Date.now(), finish: res.finishReason || "", input: res.usage?.input, output: res.usage?.output });
    return res;
  } catch (err) {
    if (mark) Object.assign(mark, { end: Date.now(), failed: failure(err), status: err?.status || undefined });
    throw err;
  }
}

/** Why a model request failed, in a word for the record — the stop, a limit, the service's error kind or its status;
 * never the service's own words. */
function failure(err) {
  if (err?.name === "AbortError") return "stopped";
  if (err?.kind) return String(err.kind).slice(0, 40);
  return err?.status ? `http ${err.status}` : "network";
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

/** What the model is told after the round of tools in which the turn's tools came to an end before their rounds did:
 * the user asked for the answer ("asked"), or the turn ran its time ("time") — it is to answer from what it has, and
 * to say what it is missing. */
export function closingNote(why, limits = LIMITS) {
  return `\n\n${why === "time" ? T`［提示：这一轮回答已经用了 ${Math.round(limits.turn / 60000)} 分钟，请根据已有结果直接作答，不要再调用工具；没有拿到的结果，请在回答中说明缺了什么］`
    : T("［提示：用户想先看到回答，请根据已有结果直接作答，不要再调用工具；没有等到的结果，请在回答中说明缺了什么］")}`;
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

/** One tool call, to an end the model is told: ok or error (the runtime's), timeout (its deadline passed), stopped (the
 * turn was), skipped (the turn did not wait for it: the user asked for the answer, or the turn ran its time), or
 * background (a research run the turn did not wait for, which goes on by itself: hooks.toolLater has its end).  Calls
 * the turn's tools came to an end before (`closing`), of a cut reply (`cut`), or with arguments that did not parse, do
 * not run.  Returns {id, ok, status, text}. */
async function execute(tc, ctx) {
  const { hooks, closing, cut, trace, round, reuse } = ctx;
  const call = { id: tc.id, name: tc.name, args: tc.arguments, started: Date.now(), status: "running" };
  const entry = trace ? { round, id: tc.id, name: tc.name, args: tc.arguments, start: call.started } : null; // its times
  if (entry) trace.tools.push(entry);
  hooks.toolStart?.(call);
  let out;
  let ran = false;
  if (closing) {
    out = refused(closing);
  } else if (cut) {
    // its arguments may have been cut with the reply: never run
    out = { ok: false, error: T("回复在输出上限处被截断，参数可能不完整，没有执行"),
      text: T("ERROR: 这次回复在输出上限处被截断，调用的参数可能不完整，没有执行。请缩短参数重新调用，或分几次调用。") };
  } else if (tc.error) {
    out = { ok: false, error: tc.error, text: T`ERROR: ${tc.error}（原始参数：${tc.rawArguments.slice(0, 300)}）` };
  } else {
    const asks = reuse ? lookupOf(tc) : null;
    const key = asks && `${asks}\u0000${ctx.scope?.() ?? ""}`; // on the same runtime and corpus only
    const was = key ? reuse.get(key) : null;
    if (was) { // the same lookup, made before in the turn: answered from it, not run again
      const note = T`［与本轮第 ${was.round} 轮的同一调用相同：结果取自那一次，没有重新运行］`;
      out = { ...was.out, reused: was.round, text: `${was.out.text || "{}"}\n\n${note}` };
      ctx.note?.("reused");
    } else {
      ran = true;
      out = await follow(tc, call, { ...ctx, entry });
      if (key && out?.ok) reuse.set(key, { out, round });
    }
  }
  out ||= { ok: false, error: T("没有结果"), text: T("ERROR: 没有结果") };
  const status = out.ok ? "ok" : out.status || (ran ? "error" : "refused");
  if (entry) {
    Object.assign(entry, { end: Date.now(), name: out.tool || tc.name, status });
    if (Number.isFinite(out.duration_ms) && ran) entry.compute = Math.round(out.duration_ms); // as long as the runtime says it took
  }
  hooks.toolEnd?.(call, out);
  return { id: tc.id, ok: Boolean(out.ok), status, text: out.text || (out.ok ? "{}" : `ERROR: ${out.error}`) };
}

/** A call after the turn's tools came to an end: not run, and the model told why (a turn taken up again, as when the
 * user asked for the answer). */
function refused(why) {
  if (why === "steps") return { ok: false, error: T("已达到本轮工具调用的上限：请根据已有结果直接作答。"), text: T("ERROR: 已达到本轮工具调用的上限：请根据已有结果直接作答。") };
  const error = why === "time" ? T("这一轮回答的时间已用完，不再调用工具：请根据已有结果直接作答。")
    : T("用户想先看到回答，不再调用工具：请根据已有结果直接作答。");
  return { ok: false, status: "skipped", error, text: `ERROR: ${error}` };
}

/**
 * A call the runtime runs, waited for within its limits: its deadline (limits.tool, or limits.research for a research
 * run), counted while it runs — not while the runtime loads, or the call waits for its turn (the runtime tells,
 * onWait/onStart) —, the turn's stop, and the turn's wish to answer now (`quick`).  The runtime is told when the call
 * is not waited for any more (its signal), and when it may give way to others (`giving`: a research run going on by
 * itself); however it behaves, the call ends here at its deadline.
 */
function follow(tc, call, { runtime, settings, hooks, signal, quick, quickWhy, limits, entry }) {
  const research = tc.name === "taochronos_research";
  const ms = research ? limits.research : limits.tool;
  const own = new AbortController();    // the runtime stops its work on the call, or its wait for it
  const giving = new AbortController(); // no one waits for it now: the runtime may let others go first
  let settle;
  const ending = new Promise((resolve) => { settle = resolve; }); // how the work ended, by its deadline at the latest
  let ended = false;
  const deadline = limit(ms, () => { end(overdue(ms, research)); own.abort(); });
  function end(out) {
    if (ended) return;
    ended = true;
    deadline.stop();
    settle(out);
  }
  const options = {
    maxChars: settings.resultChars, signal: own.signal, giving: giving.signal, limits,
    onWait: (why) => { deadline.pause(); if (entry) entry.waiting ||= Date.now(); hooks.toolWaiting?.(call, why); },
    onStart: () => { deadline.resume(); if (entry) entry.run ||= Date.now(); hooks.toolRunning?.(call); },
  };
  try {
    const work = research
      ? runtime.research(tc.arguments, { ...options, onProgress: (p) => hooks.toolProgress?.(call, p) })
      : runtime.call(tc.name, tc.arguments, options);
    Promise.resolve(work).then((out) => end(out), (err) => end(err?.name === "AbortError" ? halted() : failed(err)));
  } catch (err) {
    end(failed(err)); // a runtime that throws before it begins
  }

  // the turn's wait: the work's end, the turn's stop, or its wish to answer now
  return new Promise((resolve) => {
    let waited = false;
    const done = (out) => {
      if (waited) return;
      waited = true;
      signal.removeEventListener("abort", stop);
      quick?.removeEventListener("abort", hurry);
      resolve(out);
    };
    const stop = () => { end(halted()); own.abort(); };
    const hurry = () => {
      if (ended) return; // it has its end already: the turn has it next
      if (!research) { end(passed(quickWhy())); own.abort(); return; }
      // a research run goes on by itself, and comes to the page when it is done; the turn answers without it
      giving.abort();
      hooks.toolLater?.(call, ending);
      done(later());
    };
    ending.then(done);
    if (signal.aborted) stop();
    else signal.addEventListener("abort", stop, { once: true });
    if (quick?.aborted) hurry();
    else quick?.addEventListener("abort", hurry, { once: true });
  });
}

const halted = () => ({ ok: false, status: "stopped", error: T("已停止"), text: T("ERROR: 调用已停止") });
const failed = (err) => ({ ok: false, error: err?.message || String(err), text: `ERROR: ${err?.message || err}` });

/** A call past its deadline: not waited for any more, and the model told to answer without it, and to say so. */
function overdue(ms, research) {
  if (research) {
    const m = Math.round(ms / 60000);
    return { ok: false, status: "timeout", error: T`研究运行了 ${m} 分钟还没有完成，不再等待`,
      text: `ERROR: ${T`这次研究运行了 ${m} 分钟还没有完成，页面不再等待，结果不可用。请根据已有结果作答，并在回答中说明这项研究没有完成。`}` };
  }
  const s = Math.round(ms / 1000);
  return { ok: false, status: "timeout", error: T`运行了 ${s} 秒还没有完成，不再等待`,
    text: `ERROR: ${T`这个调用运行了 ${s} 秒还没有完成，页面不再等待，结果不可用。请根据已有结果作答，并在回答中说明缺少这一项；需要时可以缩小范围再调用一次。`}` };
}

/** A call the turn did not wait for: the user asked for the answer ("asked"), or the turn ran its time ("time"). */
function passed(why) {
  const text = why === "time" ? T("这一轮回答的时间已用完，这个调用没有等到结果。请根据已有结果作答，并在回答中说明缺少这一项。")
    : T("用户想先看到回答，这个调用没有等到结果。请根据已有结果作答，并在回答中说明缺少这一项。");
  return { ok: false, status: "skipped", error: why === "time" ? T("这一轮的时间已用完，没有等它") : T("没有等它：你选择了先看回答"), text: `ERROR: ${text}` };
}

/** A research run the turn did not wait for: it goes on, and its result comes to the page's research panel. */
const later = () => ({ ok: false, status: "background", error: T("研究在后台继续，完成后显示在研究面板中"),
  text: `ERROR: ${T("这次研究仍在后台进行，结果现在还不能用，完成后会出现在页面的研究面板中。请根据已有结果作答，并告诉用户研究仍在进行、稍后可在研究面板中查看。")}` });

/** Tool definitions in the neutral form both clients take: {name, description, parameters}. */
export function toolDefs(catalog) {
  return (catalog?.tools || []).map((t) => ({ name: t.name, description: t.description, parameters: t.parameters }));
}
