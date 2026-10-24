// OpenAI-compatible chat completions, streamed (DeepSeek, Qwen, Kimi, GLM, OpenRouter, Poe, LiteLLM, vLLM …).
//
// Providers differ in how they stream.  Some stream their thinking in delta.reasoning_details, and some send both that
// and delta.content as cumulative text; most send increments.  Every field is therefore accumulated by `Accum`, which
// accepts either.  The assistant message is returned whole — content, tool_calls and the provider's reasoning field —
// because some providers require it back verbatim in the history.

import { outputLimit, publicError } from "../providers.js";
import { aborted, until, watch } from "../limits.js";
import { T } from "../i18n.js";

export class Accum {
  constructor() { this.text = ""; this.mode = null; }
  /** Add a chunk; returns the new part (what a delta-only reader would have received). */
  push(t) {
    if (t === undefined || t === null || t === "") return "";
    t = String(t);
    if (this.mode !== "delta" && this.text && t.length > this.text.length && t.startsWith(this.text)) {
      const add = t.slice(this.text.length);
      this.text = t;
      if (this.text.length >= 12) this.mode = "cumulative";
      return add;
    }
    if (this.mode === "cumulative" && this.text.startsWith(t)) return ""; // a repeat of what we have
    if (this.text && !this.mode) this.mode = "delta";
    this.text += t;
    return t;
  }
}

const THINK_OPEN = "<think>";
const THINK_CLOSE = "</think>";

/** Split a leading <think>…</think> block (a reply whose reasoning was not split out) from the answer. */
export function splitThink(text) {
  const s = text.replace(/^\s+/, "");
  if (!s.startsWith(THINK_OPEN)) return { thinking: "", answer: text, open: false };
  const end = s.indexOf(THINK_CLOSE);
  if (end < 0) return { thinking: s.slice(THINK_OPEN.length), answer: "", open: true };
  return { thinking: s.slice(THINK_OPEN.length, end), answer: s.slice(end + THINK_CLOSE.length).replace(/^\s+/, ""), open: false };
}

export class ProviderError extends Error {
  /** kind: the error's type as the service names it (the default service's daily_limit, rate_limited …); retryAfter: the
   * seconds its refusal asks to wait (Retry-After), or null. */
  constructor(message, { status = 0, body = "", retryable = false, kind = "", retryAfter = null } = {}) {
    super(message);
    this.status = status;
    this.body = body;
    this.retryable = retryable;
    this.kind = kind;
    this.retryAfter = retryAfter;
  }
}

// refusals that asking again soon does not change: the visitor's or the service's allowance for the day spent, an address
// blocked, the default service not set up, its own key refused or its quota spent, a provider's quota spent
const FINAL = new Set(["daily_limit", "total_limit", "blocked", "not_configured", "upstream_auth", "upstream_quota", "insufficient_quota"]);

/** The error's type in a provider's error body ({error: {type}}; the default service's are FINAL's and rate_limited …). */
function errorKind(body) {
  try {
    const j = JSON.parse(body);
    return String(j.error?.type || j.error?.code || "");
  } catch {
    return "";
  }
}

/** The seconds a refusal asks to wait (Retry-After: seconds, or a date), or null. */
export function retryAfter(headers) {
  const v = String(headers?.get?.("Retry-After") ?? "").trim();
  if (!v) return null;
  const s = /^\d+$/.test(v) ? Number(v) : (Date.parse(v) - Date.now()) / 1000;
  return Number.isFinite(s) ? Math.max(0, s) : null;
}

/** A connection that broke off while the reply was read (Chrome's "network error", Safari's "Load failed"), or one a
 * limit of the request's watch ended (`w`, limits.js): the round is asked again from its start, since no tool has run
 * on what it had said. */
function brokenOff(err, w) {
  if (w.expired) return stalled(w);
  if (err?.name === "AbortError" || w.signal.aborted) return err?.name === "AbortError" ? err : aborted();
  return new ProviderError(T`连接在回复途中断开（${err?.message || err}）`, { retryable: true });
}

/** A reply a limit ended: no first byte, a stream that went silent, or one read whole that took too long — asked again
 * like one that broke off. */
export function stalled(w) {
  const s = Math.round(w.ms / 1000);
  const message = w.expired === "firstReply" ? T`模型服务 ${s} 秒没有回应`
    : w.expired === "silence" ? T`回复中断：模型服务 ${s} 秒没有再发来内容` : T`回复 ${s} 秒还没有读完`;
  return new ProviderError(message, { retryable: true, kind: "timeout" });
}

/** A reply whose stream ended before the service said it was complete — no finish_reason, no [DONE], no stop_reason: the
 * connection closing is not the answer's end, and the round is asked again like one that broke off. */
export const unfinished = () => new ProviderError(T("回复没有完整到达：连接在模型说完之前就结束了"), { retryable: true, kind: "unfinished" });

function errorMessage(status, body) {
  let msg = body;
  try {
    const j = JSON.parse(body);
    msg = j.error?.message || j.error?.msg || (typeof j.error === "string" ? j.error : "") || j.base_resp?.status_msg || j.message || body;
  } catch { /* not JSON */ }
  const hint = status === 401 || status === 403 ? T("（API Key 无效或无权限）") : status === 404 ? T("（地址或模型名有误）")
    : status === 429 ? T("（请求过于频繁或额度不足）") : status >= 500 ? T("（服务端暂时不可用）") : "";
  return T`模型服务返回 ${status}${hint}：${String(msg).slice(0, 400)}`;
}

/** Where a request goes: straight to the provider, or through the local server's proxy. */
export function endpoint(url, route) {
  if (!route || route.kind !== "proxy") return { url, headers: {} };
  return { url: `${route.serverUrl.replace(/\/+$/, "")}/api/llm`, headers: { "X-TC-Target": url, ...proxyHeaders(route) } };
}

/** What the server's proxy needs besides the target: its access token, when it has one. */
export const proxyHeaders = (route) => (route?.kind === "proxy" && route.token ? { "X-TC-Token": route.token } : {});

/**
 * Stream one completion.  Returns {message, text, thinking, toolCalls, finishReason, usage}; calls onEvent with
 * {type: "text" | "thinking" | "tool", ...} as the answer arrives.  `limits` (limits.js): how long its first reply, and
 * a silence while it streams, are waited for; `mark`: told when it was sent and its parts came (limits.js, watch).
 */
export async function streamChat({ provider, messages, tools, settings, route, signal, limits, mark, onEvent = () => {} }) {
  const url = provider.full_url ? provider.baseUrl : `${provider.baseUrl}/chat/completions`;
  if (!/^https?:\/\//.test(url)) throw new ProviderError(T`接口地址无效：${url || T("（未填写）")}`);
  const body = { model: provider.model, messages, stream: true };
  if (tools && tools.length) {
    body.tools = tools.map((t) => ({ type: "function", function: { name: t.name, description: t.description, parameters: t.parameters } }));
    body.tool_choice = "auto";
  }
  // a service with its own ceiling (the default service) is asked within it, so it forwards the request unchanged
  body[provider.max_tokens_param || "max_tokens"] = outputLimit(settings, provider);
  if (settings.temperature !== null && settings.temperature !== "" && settings.temperature !== undefined) body.temperature = Number(settings.temperature);
  Object.assign(body, provider.extra_body || {});
  if (settings.thinking === false && provider.thinking_off) Object.assign(body, provider.thinking_off); // what asks for no thinking
  if (provider.stream_usage) body.stream_options = { include_usage: true };

  const target = endpoint(url, route);
  const headers = { "Content-Type": "application/json", Accept: "text/event-stream", ...target.headers };
  if (provider.apiKey) headers.Authorization = `Bearer ${provider.apiKey}`;
  else if (route?.kind === "proxy") headers.Authorization = "Bearer tc-env-key";
  Object.assign(headers, provider.headers || {}); // a hand-set endpoint's own headers (api-key: …, a gateway's routing header)
  if (provider.id === "openrouter") { headers["HTTP-Referer"] = location.origin; headers["X-Title"] = "TaoChronos"; }

  const w = watch(signal, limits, mark);
  try {
    return await send({ provider, route, url, target, headers, body, onEvent }, w);
  } finally {
    w.close();
  }
}

/** The request sent and its reply read, within the limits of its watch `w`. */
async function send({ provider, route, url, target, headers, body, onEvent }, w) {
  let resp;
  try {
    w.sent();
    resp = await until(fetch(target.url, { method: "POST", headers, body: JSON.stringify(body), signal: w.signal }), w.signal);
  } catch (err) {
    if (w.expired) throw stalled(w);
    if (err.name === "AbortError") throw err;
    throw new ProviderError(
      provider.relay
        ? T("无法连接道乃久默认服务：网络不通或服务暂时不可用，请稍后再试，或在“设置 → 模型”里改用自己的 API Key。")
        : route?.kind === "proxy"
        ? T`无法连接 TaoChronos 服务 ${route.serverUrl}：请确认 taochronos serve 正在运行`
        : T`无法连接 ${new URL(url).host}：网络不通，或该服务不允许浏览器直接访问（CORS）。可在设置中改为“经本地服务转发”。`,
      { retryable: true });
  }
  if (!resp.ok) {
    const text = await until(resp.text(), w.signal).catch(() => "");
    const message = errorMessage(resp.status, text);
    const kind = errorKind(text);
    throw new ProviderError(provider.relay ? publicError(message) : message, {
      status: resp.status, body: provider.relay ? "" : text, kind, retryAfter: retryAfter(resp.headers),
      retryable: (resp.status === 429 || resp.status >= 500) && !FINAL.has(kind) });
  }

  const state = {
    content: new Accum(), reasoning: new Accum(), details: new Map(), calls: new Map(), finishReason: null, usage: null,
    final: null, shownThinking: 0,
  };
  const type = resp.headers.get("content-type") || "";
  try {
    if (!type.includes("event-stream")) {
      // a provider that ignored stream: true (or an error delivered with status 200)
      const text = await whole(resp, w);
      let j;
      try { j = JSON.parse(text); } catch { throw new ProviderError(T`无法解析模型服务的回复：${text.slice(0, 300)}`); }
      handleChunk(j, state, onEvent, true);
    } else {
      const done = await readSSE(resp, w, (data) => {
        let j;
        try { j = JSON.parse(data); } catch { return; }
        handleChunk(j, state, onEvent, false);
      });
      if (!done && !state.finishReason) throw unfinished();
    }
    // DeepSeek's word for a reply its servers stopped part-way
    if (state.finishReason === "insufficient_system_resource") throw new ProviderError(T("模型服务资源不足，回复中途停止"), { retryable: true });
  } catch (err) {
    if (provider.relay && err instanceof ProviderError) { err.message = publicError(err.message); err.body = ""; }
    throw err;
  }
  return finish(state, provider);
}

/** A reply's body read whole: it says nothing until it is complete, so it has the time for that, not a silence. */
async function whole(resp, w) {
  w.whole();
  let text;
  try {
    text = await until(resp.text(), w.signal);
  } catch (err) {
    throw brokenOff(err, w);
  }
  w.heard();
  return text;
}

/** The events of a streamed reply, as they arrive; read whole where the browser cannot read a reply as it arrives (an
 * older Safari has no body to read from).  Returns whether the stream said it was done ([DONE]).  `w`: the request's
 * watch, told of everything that arrives (a silence ends the request). */
async function readSSE(resp, w, onData) {
  const decoder = new TextDecoder();
  let buf = "";
  let data = [];
  const dispatch = () => {
    if (!data.length) return false;
    const payload = data.join("\n");
    data = [];
    if (payload.trim() === "[DONE]") return true;
    onData(payload);
    return false;
  };
  // the complete lines read so far, an event dispatched at each blank line; true at [DONE]
  const lines = () => {
    let nl;
    while ((nl = buf.search(/\r?\n/)) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(buf[nl] === "\r" ? nl + 2 : nl + 1);
      if (line === "") { if (dispatch()) return true; continue; }
      if (line.startsWith(":")) continue;
      if (line.startsWith("data:")) data.push(line.slice(line[5] === " " ? 6 : 5));
      else if (line.startsWith("{")) data.push(line); // a provider that streams bare JSON lines
    }
    return false;
  };
  const end = () => {
    if (buf.startsWith("data:")) data.push(buf.slice(buf[5] === " " ? 6 : 5));
    return dispatch();
  };
  if (typeof resp.body?.getReader !== "function") {
    buf = await whole(resp, w);
    return lines() || end();
  }
  const reader = resp.body.getReader();
  w.streaming();
  try {
    for (;;) {
      if (w.signal.aborted) throw brokenOff(null, w);
      let chunk;
      try {
        chunk = await until(reader.read(), w.signal);
      } catch (err) {
        throw brokenOff(err, w);
      }
      if (chunk.done) break;
      w.heard();
      buf += decoder.decode(chunk.value, { stream: true });
      if (lines()) return true;
    }
    buf += decoder.decode();
    return end();
  } finally {
    if (w.signal.aborted) reader.cancel().catch(() => {}); // stopped, or stalled: the rest is not read
    try { reader.releaseLock(); } catch { /* already released */ }
  }
}

function handleChunk(j, state, onEvent, whole) {
  if (j.error || (j.base_resp && j.base_resp.status_code)) {
    const msg = j.error?.message || j.error?.msg || (typeof j.error === "string" ? j.error : "") || j.base_resp?.status_msg || "unknown error";
    throw new ProviderError(T`模型服务报错：${msg}`, { status: j.base_resp?.status_code || 0, body: JSON.stringify(j).slice(0, 2000) });
  }
  if (j.usage) state.usage = j.usage;
  const choice = j.choices?.[0];
  if (!choice) return;
  if (choice.finish_reason) state.finishReason = choice.finish_reason;
  const d = choice.delta || (whole ? choice.message : null) || {};
  if (choice.message && !whole) state.final = choice.message;
  if (whole && choice.message) state.final = choice.message;

  const addThinking = (piece) => { if (piece) onEvent({ type: "thinking", delta: piece }); };
  if (Array.isArray(d.reasoning_details)) {
    d.reasoning_details.forEach((det, k) => {
      const idx = det.index ?? k;
      let slot = state.details.get(idx);
      if (!slot) { slot = { meta: { ...det }, acc: new Accum() }; state.details.set(idx, slot); }
      for (const [key, v] of Object.entries(det)) if (key !== "text" && v !== undefined && v !== null) slot.meta[key] = v;
      if (typeof det.text === "string") addThinking(slot.acc.push(det.text));
      else if (typeof det.summary === "string") addThinking(slot.acc.push(det.summary));
    });
  }
  if (typeof d.reasoning_content === "string") addThinking(state.reasoning.push(d.reasoning_content));
  else if (typeof d.reasoning === "string" && !Array.isArray(d.reasoning_details)) addThinking(state.reasoning.push(d.reasoning));

  if (typeof d.content === "string" && d.content) {
    const piece = state.content.push(d.content);
    if (piece) {
      const { thinking, answer, open } = splitThink(state.content.text);
      if (thinking || open) {
        // reasoning inside <think> tags: shown as thinking, kept verbatim in the message
        if (thinking.length > state.shownThinking) { addThinking(thinking.slice(state.shownThinking)); state.shownThinking = thinking.length; }
        if (!open) onEvent({ type: "text", text: answer });
      } else {
        onEvent({ type: "text", text: state.content.text });
      }
    }
  }
  if (Array.isArray(d.tool_calls)) {
    d.tool_calls.forEach((tc, k) => {
      const idx = tc.index ?? k;
      let slot = state.calls.get(idx);
      if (!slot) { slot = { id: "", name: "", args: new Accum() }; state.calls.set(idx, slot); }
      if (tc.id) slot.id = tc.id;
      const fn = tc.function || {};
      if (fn.name) slot.name = !slot.name ? fn.name : fn.name.startsWith(slot.name) ? fn.name : slot.name.endsWith(fn.name) ? slot.name : slot.name + fn.name;
      if (fn.arguments !== undefined && fn.arguments !== null) {
        slot.args.push(typeof fn.arguments === "string" ? fn.arguments : JSON.stringify(fn.arguments));
      }
      onEvent({ type: "tool", index: idx, name: slot.name, args: slot.args.text });
    });
  }
}

function finish(state, provider) {
  // a closing chunk that carries the whole message (some providers send one) is preferred when it is complete
  const finalText = typeof state.final?.content === "string" ? state.final.content : null;
  const rawContent = finalText !== null && finalText.length >= state.content.text.length ? finalText : state.content.text;
  const { thinking: inlineThinking, answer } = splitThink(rawContent || "");
  let calls = [...state.calls.entries()].sort((a, b) => a[0] - b[0]).map(([, c]) => c);
  if (!calls.length && state.final?.tool_calls?.length) {
    calls = state.final.tool_calls.map((tc) => ({ id: tc.id, name: tc.function?.name || "", args: { text: typeof tc.function?.arguments === "string" ? tc.function.arguments : JSON.stringify(tc.function?.arguments || {}) } }));
  }
  const toolCalls = calls.filter((c) => c.name).map((c, k) => {
    const id = c.id || `call_${Date.now().toString(36)}_${k}`;
    let args = {}, error = null;
    const raw = (c.args.text || "").trim();
    if (raw) {
      try {
        args = JSON.parse(raw);
        if (typeof args !== "object" || args === null || Array.isArray(args)) { error = T("参数必须是 JSON 对象"); args = {}; }
      } catch (e) {
        error = T`参数不是合法的 JSON：${e.message}`;
      }
    }
    return { id, name: c.name, arguments: args, rawArguments: raw || "{}", error };
  });

  const message = { role: "assistant", content: rawContent || "" };
  if (toolCalls.length) {
    message.tool_calls = toolCalls.map((c) => ({ id: c.id, type: "function", function: { name: c.name, arguments: c.rawArguments } }));
  }
  const details = [...state.details.entries()].sort((a, b) => a[0] - b[0]).map(([, s]) => ({ ...s.meta, text: s.acc.text }));
  const finalDetails = state.final?.reasoning_details;
  if (provider.reasoning === "reasoning_details" && (finalDetails?.length || details.length)) message.reasoning_details = finalDetails || details;
  if (provider.reasoning === "reasoning_content" && (state.final?.reasoning_content || state.reasoning.text)) {
    message.reasoning_content = state.final?.reasoning_content || state.reasoning.text;
  }
  const thinking = details.map((x) => x.text).join("\n") || state.reasoning.text || inlineThinking;
  return { message, text: answer, thinking, toolCalls, finishReason: state.finishReason, usage: normalizeUsage(state.usage) };
}

function normalizeUsage(u) {
  if (!u) return null;
  return { input: u.prompt_tokens ?? u.input_tokens ?? 0, output: u.completion_tokens ?? u.output_tokens ?? 0 };
}

/** Tool results go back as role "tool" messages. */
export function toolResultMessages(results) {
  return results.map((r) => ({ role: "tool", tool_call_id: r.id, content: r.text }));
}

/** A user turn in this format (text, and images for a model that reads them). */
export function userMessage(text, images = []) {
  if (!images.length) return { role: "user", content: text };
  return { role: "user", content: [{ type: "text", text }, ...images.map((url) => ({ type: "image_url", image_url: { url } }))] };
}
