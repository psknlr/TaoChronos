// Model providers (providers.json, written from the harness's own presets) and the user's settings.
// API keys are kept in this browser's localStorage only, and sent only to the provider (or your local server's proxy).
// 道乃久默认服务 (the site's relay, site.json) needs no key: the relay holds it, and no key is ever sent to it.

import { PUBLISHER } from "./brand.js";
import { storage } from "./util.js";


const FALLBACK = [{
  id: "deepseek", label: "DeepSeek", format: "openai", base_url: "https://api.deepseek.com/v1", key_env: "DEEPSEEK_API_KEY",
  key_optional: false, max_tokens_param: "max_tokens", extra_body: {}, examples: ["deepseek-chat", "deepseek-reasoner"],
  default_model: "deepseek-chat", reasoning: "reasoning_content", vision: false, stream_usage: true, note: "",
}];

export const DEFAULTS = {
  provider: "impf",           // 道乃久默认服务 when the site has it; else the first provider listed
  models: {},              // provider id → model name
  baseUrls: {},            // provider id → base URL override
  keys: {},                // provider id → API key (this browser only)
  temperature: null,       // null: the provider's default
  maxTokens: 16000,
  thinking: true,
  route: "auto",           // auto | direct | proxy (through the local server)
  runtime: "auto",         // auto | browser | server
  serverUrl: "http://localhost:8765",
  serverToken: "",         // the access token of a server reachable from other machines (taochronos serve --host …)
  toolMode: "core",        // core (a dozen tools + catalog/call) | all (every tool directly)
  maxSteps: 16,
  resultChars: 16000,
  instructions: "",
  theme: "system",
  verifyQuotes: true,
  customProviders: [],     // endpoints set by hand: {id, label, format, base_url, full_url, model, headers, extra_body, max_tokens_param, reasoning, vision}
};

let providers = FALLBACK;

export const RELAY_ID = "impf";
let relay = null; // {url, ok, model, models, logs, limits} once the site's relay has answered (or failed to)

export function setRelay(r) { relay = r; }

/** The default service as a provider: MiniMax behind the site's relay, no key. */
function relayPreset() {
  if (!relay?.url) return null;
  const models = relay.models?.length ? relay.models : relay.model ? [relay.model] : [];
  return {
    id: RELAY_ID, label: "道乃久默认服务", format: "openai", base_url: `${relay.url}/v1`, key_optional: true, relay: true, family: "minimax",
    max_tokens_param: "max_completion_tokens", extra_body: { reasoning_split: true }, examples: models, default_model: relay.model || models[0] || "",
    reasoning: "reasoning_details", vision: true, stream_usage: true, unavailable: !relay.ok, max_output: relay.maxOutput || null,
    note: relay.ok
      ? `${PUBLISHER}提供，无需 API Key，直接提问${relay.limits?.per_day ? `；测试期间每人每天约 ${relay.limits.per_day} 次模型调用（一个问题通常用几次）` : ""}。`
      : "默认服务暂时连不上：请稍后再试，或选择其他服务并填入自己的 API Key。",
  };
}

export async function loadProviders() {
  try {
    const r = await fetch("providers.json", { cache: "no-cache" });
    if (r.ok) {
      const list = await r.json();
      if (Array.isArray(list) && list.length) providers = list;
    }
  } catch { /* the embedded preset is enough to start */ }
  return providers;
}

/** An endpoint the user set by hand, as a provider the page can call. */
export function customPreset(c) {
  const anthropic = c.format === "anthropic";
  return {
    id: c.id, label: c.label || "自定义 API", format: anthropic ? "anthropic" : "openai", base_url: c.base_url || "",
    full_url: Boolean(c.full_url) && !anthropic, key_optional: true, max_tokens_param: c.max_tokens_param || "max_tokens",
    extra_body: c.extra_body || {}, headers: c.headers || {}, examples: c.model ? [c.model] : [], default_model: c.model || "",
    reasoning: anthropic ? "thinking" : c.reasoning || null, vision: Boolean(c.vision), stream_usage: c.stream_usage !== false,
    custom: true, note: "",
  };
}

export function newCustomProvider(n = 1) {
  return { id: `custom-${Date.now().toString(36)}`, label: `我的 API ${n}`, format: "openai", base_url: "", full_url: false, model: "",
    headers: {}, extra_body: {}, max_tokens_param: "max_tokens", reasoning: null, vision: false };
}

export const allProviders = (settings) => {
  const r = relayPreset();
  return [...(r ? [r] : []), ...providers, ...(settings?.customProviders || []).map(customPreset)];
};
export const providerById = (id, settings) => allProviders(settings).find((p) => p.id === id) || providers[0];

export function loadSettings() {
  const saved = storage.get("tc.settings", {}) || {};
  // MiniMax is no longer listed on the page: it is the default service, which a visitor reaches without a key
  if (/^minimax/.test(saved.provider || "")) saved.provider = RELAY_ID;
  return { ...DEFAULTS, ...saved, models: { ...(saved.models || {}) }, baseUrls: { ...(saved.baseUrls || {}) }, keys: { ...(saved.keys || {}) },
    customProviders: Array.isArray(saved.customProviders) ? saved.customProviders.map((c) => ({ ...c })) : [] };
}

export function saveSettings(settings) {
  storage.set("tc.settings", settings);
}

/** How a provider is named on the page: the default service by its own name (the page names no vendor behind it). */
export const modelLabel = (p) => (p.relay ? p.label : `底层模型 ${p.model || "未选"}（${p.label}）`);

/** The provider as configured now: preset + the user's model, base URL and key. */
export function activeProvider(settings) {
  const p = providerById(settings.provider, settings);
  return {
    ...p,
    model: (p.custom ? p.default_model : (p.relay && !(p.examples || []).includes(settings.models[p.id]) ? "" : settings.models[p.id])
      || p.default_model) || (p.examples || [])[0] || "",
    baseUrl: ((p.custom || p.relay ? p.base_url : settings.baseUrls[p.id] || p.base_url) || "").trim().replace(/\/+$/, ""),
    apiKey: p.relay ? "" : settings.keys[p.id] || "", // the relay holds its own key: none is sent to it
  };
}
