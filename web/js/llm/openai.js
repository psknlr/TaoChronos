// OpenAI-compatible chat completions, streamed (MiniMax, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Poe, LiteLLM, vLLM …).
//
// Providers differ in how they stream.  MiniMax, with reasoning_split, streams its thinking in delta.reasoning_details and
// its own examples read both that and delta.content as cumulative text; most providers send increments.  Every field
// is therefore accumulated by `Accum`, which accepts either.  The assistant message is returned whole — content,
// tool_calls and the provider's reasoning field — because MiniMax requires it back verbatim in the history.

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
  constructor(message, { status = 0, body = "", retryable = false } = {}) {
    super(message);
    this.status = status;
    this.body = body;
    this.retryable = retryable;
  }
}

function errorMessage(status, body) {
  let msg = body;
  try {
    const j = JSON.parse(body);
    msg = j.error?.message || j.error?.msg || (typeof j.error === "string" ? j.error : "") || j.base_resp?.status_msg || j.message || body;
  } catch { /* not JSON */ }
  const hint = status === 401 || status === 403 ? "（API Key 无效或无权限）" : status === 404 ? "（地址或模型名有误）"
    : status === 429 ? "（请求过于频繁或额度不足）" : status >= 500 ? "（服务端暂时不可用）" : "";
  return `模型服务返回 ${status}${hint}：${String(msg).slice(0, 400)}`;
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
 * {type: "text" | "thinking" | "tool", ...} as the answer arrives.
 */
export async function streamChat({ provider, messages, tools, settings, route, signal, onEvent = () => {} }) {
  const url = `${provider.baseUrl}/chat/completions`;
  const body = { model: provider.model, messages, stream: true };
  if (tools && tools.length) {
    body.tools = tools.map((t) => ({ type: "function", function: { name: t.name, description: t.description, parameters: t.parameters } }));
    body.tool_choice = "auto";
  }
  if (settings.maxTokens) body[provider.max_tokens_param || "max_tokens"] = Number(settings.maxTokens);
  if (settings.temperature !== null && settings.temperature !== "" && settings.temperature !== undefined) body.temperature = Number(settings.temperature);
  Object.assign(body, provider.extra_body || {});
  if (provider.id.startsWith("minimax") && settings.thinking === false) body.thinking = { type: "disabled" };
  if (provider.stream_usage) body.stream_options = { include_usage: true };

  const target = endpoint(url, route);
  const headers = { "Content-Type": "application/json", Accept: "text/event-stream", ...target.headers };
  if (provider.apiKey) headers.Authorization = `Bearer ${provider.apiKey}`;
  else if (route?.kind === "proxy") headers.Authorization = "Bearer tc-env-key";
  if (provider.id === "openrouter") { headers["HTTP-Referer"] = location.origin; headers["X-Title"] = "TaoChronos"; }

  let resp;
  try {
    resp = await fetch(target.url, { method: "POST", headers, body: JSON.stringify(body), signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ProviderError(
      route?.kind === "proxy"
        ? `无法连接 TaoChronos 服务 ${route.serverUrl}：请确认 taochronos serve 正在运行`
        : `无法连接 ${new URL(url).host}：网络不通，或该服务不允许浏览器直接访问（CORS）。可在设置中改为“经本地服务转发”。`,
      { retryable: true });
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ProviderError(errorMessage(resp.status, text), { status: resp.status, body: text, retryable: resp.status === 429 || resp.status >= 500 });
  }

  const state = {
    content: new Accum(), reasoning: new Accum(), details: new Map(), calls: new Map(), finishReason: null, usage: null,
    final: null, shownThinking: 0,
  };
  const type = resp.headers.get("content-type") || "";
  if (!type.includes("event-stream")) {
    // a provider that ignored stream: true (or an error delivered with status 200)
    const text = await resp.text();
    let j;
    try { j = JSON.parse(text); } catch { throw new ProviderError(`无法解析模型服务的回复：${text.slice(0, 300)}`); }
    handleChunk(j, state, onEvent, true);
  } else {
    await readSSE(resp.body, signal, (data) => {
      let j;
      try { j = JSON.parse(data); } catch { return; }
      handleChunk(j, state, onEvent, false);
    });
  }
  return finish(state, provider);
}

async function readSSE(stream, signal, onData) {
  const reader = stream.getReader();
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
  try {
    for (;;) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.search(/\r?\n/)) >= 0) {
        const line = buf.slice(0, nl);
        buf = buf.slice(buf[nl] === "\r" ? nl + 2 : nl + 1);
        if (line === "") { if (dispatch()) return; continue; }
        if (line.startsWith(":")) continue;
        if (line.startsWith("data:")) data.push(line.slice(line[5] === " " ? 6 : 5));
        else if (line.startsWith("{")) data.push(line); // a provider that streams bare JSON lines
      }
    }
    buf += decoder.decode();
    if (buf.startsWith("data:")) data.push(buf.slice(buf[5] === " " ? 6 : 5));
    dispatch();
  } finally {
    try { reader.releaseLock(); } catch { /* already released */ }
  }
}

function handleChunk(j, state, onEvent, whole) {
  if (j.error || (j.base_resp && j.base_resp.status_code)) {
    const msg = j.error?.message || j.error?.msg || (typeof j.error === "string" ? j.error : "") || j.base_resp?.status_msg || "unknown error";
    throw new ProviderError(`模型服务报错：${msg}`, { status: j.base_resp?.status_code || 0, body: JSON.stringify(j).slice(0, 2000) });
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
        if (typeof args !== "object" || args === null || Array.isArray(args)) { error = "参数必须是 JSON 对象"; args = {}; }
      } catch (e) {
        error = `参数不是合法的 JSON：${e.message}`;
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
