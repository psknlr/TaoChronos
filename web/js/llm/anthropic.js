// Claude through the official Anthropic TypeScript SDK (loaded on first use from jsDelivr, pinned).
//
// Adaptive thinking (summarised, so it can be shown) on models that support it; server-side refusal fallbacks
// (fallbacks: "default") on Claude Opus 5 and Fable 5.1, as the harness's own provider does; the stop reason is checked
// before any tool runs (a refusal or a max_tokens cut can leave a tool input incomplete); the assistant content is
// replayed verbatim so thinking blocks round-trip.  Through the local server the SDK talks to its proxy, which forwards
// to api.anthropic.com.

import { ProviderError, proxyHeaders } from "./openai.js";
import { T } from "../i18n.js";

const SDK_URL = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.128.0/+esm";
const FALLBACK_BETA = "server-side-fallback-2026-07-01";
const FALLBACK_MODELS = new Set(["claude-opus-5", "claude-fable-5-1"]);
let sdk = null;

async function loadSDK() {
  if (!sdk) {
    try {
      sdk = (await import(/* @vite-ignore */ SDK_URL)).default;
    } catch (err) {
      throw new ProviderError(T`无法载入 Anthropic SDK（${err.message}）。请检查网络，或改用 OpenRouter / Poe / LiteLLM 等 OpenAI 兼容通道。`);
    }
  }
  return sdk;
}

export async function streamClaude({ provider, system, messages, tools, settings, route, signal, onEvent = () => {} }) {
  const Anthropic = await loadSDK();
  const base = provider.baseUrl.replace(/\/v1\/?$/, "");
  const viaProxy = route?.kind === "proxy";
  const client = new Anthropic({
    apiKey: provider.apiKey || (viaProxy ? "tc-env-key" : ""),
    baseURL: viaProxy ? `${route.serverUrl.replace(/\/+$/, "")}/api/llm` : base,
    defaultHeaders: { ...(provider.headers || {}), ...(viaProxy ? { "X-TC-Target": base, ...proxyHeaders(route) } : {}) },
    dangerouslyAllowBrowser: true,
    maxRetries: 2,
  });
  if (!provider.apiKey && !viaProxy) throw new ProviderError(T("请先在设置中填写 Anthropic API Key"));

  const params = {
    model: provider.model,
    max_tokens: Number(settings.maxTokens) || 16000,
    system,
    messages,
  };
  if (tools && tools.length) {
    params.tools = tools.map((t) => ({ name: t.name, description: t.description, input_schema: t.parameters, eager_input_streaming: true }));
  }
  if (settings.thinking !== false && !/haiku/.test(provider.model)) params.thinking = { type: "adaptive", display: "summarized" };
  if (settings.temperature !== null && settings.temperature !== "" && settings.temperature !== undefined && !params.thinking) {
    params.temperature = Number(settings.temperature);
  }

  let stream;
  try {
    stream = FALLBACK_MODELS.has(provider.model)
      ? client.beta.messages.stream({ ...params, betas: [FALLBACK_BETA], fallbacks: "default" }, { signal })
      : client.messages.stream(params, { signal });
    const text = [];
    let thinking = "";
    for await (const event of stream) {
      if (event.type === "content_block_start" && event.content_block?.type === "text") text.push("");
      if (event.type !== "content_block_delta") continue;
      const d = event.delta;
      if (d.type === "text_delta") {
        if (!text.length) text.push("");
        text[text.length - 1] += d.text;
        onEvent({ type: "text", text: text.join("\n\n") });
      } else if (d.type === "thinking_delta") {
        thinking += d.thinking;
        onEvent({ type: "thinking", delta: d.thinking });
      } else if (d.type === "input_json_delta") {
        onEvent({ type: "tool", index: event.index, name: "", args: d.partial_json });
      }
    }
    const final = await stream.finalMessage();
    const content = final.content || [];
    const toolUses = content.filter((b) => b.type === "tool_use");
    if (final.stop_reason === "refusal") {
      const cat = final.stop_details?.category;
      throw new ProviderError(T`Claude 拒绝了这次请求${cat ? T`（类别：${cat}）` : ""}。可改写问题后重试。`);
    }
    if (final.stop_reason === "max_tokens" && toolUses.length) {
      throw new ProviderError(T("工具参数在输出上限处被截断，未执行。请在设置中调高“最大输出”后重试。"));
    }
    const toolCalls = toolUses.map((b) => ({
      id: b.id, name: b.name, arguments: b.input && typeof b.input === "object" && !Array.isArray(b.input) ? b.input : {},
      rawArguments: JSON.stringify(b.input ?? {}),
      error: b.input && typeof b.input === "object" && !Array.isArray(b.input) ? null : T("参数必须是 JSON 对象"),
    }));
    const answer = content.filter((b) => b.type === "text").map((b) => b.text).join("\n\n");
    const shownThinking = thinking || content.filter((b) => b.type === "thinking").map((b) => b.thinking || "").join("\n");
    return {
      message: { role: "assistant", content },
      text: answer,
      thinking: shownThinking,
      toolCalls,
      finishReason: final.stop_reason,
      usage: final.usage ? { input: final.usage.input_tokens || 0, output: final.usage.output_tokens || 0 } : null,
      model: final.model,
    };
  } catch (err) {
    if (err?.name === "AbortError" || signal?.aborted) throw new DOMException("aborted", "AbortError");
    if (err instanceof ProviderError) throw err;
    if (err instanceof Anthropic.APIError) {
      const status = err.status || 0;
      const hint = status === 401 ? T("（API Key 无效）") : status === 429 ? T("（请求过于频繁）") : status >= 500 ? T("（服务端暂时不可用）") : "";
      throw new ProviderError(T`Claude API 返回 ${status}${hint}：${err.message}`, { status, retryable: status === 429 || status >= 500 });
    }
    // with eager input streaming, a tool input that is not valid JSON rejects the stream
    throw new ProviderError(T`Claude 回复无法解析：${err?.message || err}`, { retryable: true });
  }
}

export function toolResultMessages(results) {
  return [{
    role: "user",
    content: results.map((r) => ({ type: "tool_result", tool_use_id: r.id, content: r.text, ...(r.ok ? {} : { is_error: true }) })),
  }];
}

export function userMessage(text, images = []) {
  if (!images.length) return { role: "user", content: text };
  const parts = images.map((url) => {
    const m = /^data:([^;]+);base64,(.*)$/.exec(url);
    return m ? { type: "image", source: { type: "base64", media_type: m[1], data: m[2] } } : { type: "image", source: { type: "url", url } };
  });
  return { role: "user", content: [...parts, { type: "text", text }] };
}
