// Model providers (providers.json, written from the harness's own presets) and the user's settings.
// API keys are kept in this browser's localStorage only, and sent only to the provider (or your local server's proxy).

import { storage } from "./util.js";


const FALLBACK = [{
  id: "minimax", label: "MiniMax（国内站）", format: "openai", base_url: "https://api.minimax.cn/v1", key_env: "MINIMAX_API_KEY",
  key_optional: false, max_tokens_param: "max_completion_tokens", extra_body: { reasoning_split: true },
  examples: ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5"], default_model: "MiniMax-M3",
  reasoning: "reasoning_details", vision: true, stream_usage: true, note: "",
}];

export const DEFAULTS = {
  provider: "minimax",
  models: {},              // provider id → model name
  baseUrls: {},            // provider id → base URL override
  keys: {},                // provider id → API key (this browser only)
  temperature: null,       // null: the provider's default (MiniMax-M3: 1.0)
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

export async function loadProviders() {
  try {
    const r = await fetch("providers.json", { cache: "no-cache" });
    if (r.ok) {
      const list = await r.json();
      if (Array.isArray(list) && list.length) providers = list;
    }
  } catch { /* the embedded MiniMax preset is enough to start */ }
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

export const allProviders = (settings) => [...providers, ...(settings?.customProviders || []).map(customPreset)];
export const providerById = (id, settings) => allProviders(settings).find((p) => p.id === id) || providers[0];

export function loadSettings() {
  const saved = storage.get("tc.settings", {}) || {};
  return { ...DEFAULTS, ...saved, models: { ...(saved.models || {}) }, baseUrls: { ...(saved.baseUrls || {}) }, keys: { ...(saved.keys || {}) },
    customProviders: Array.isArray(saved.customProviders) ? saved.customProviders.map((c) => ({ ...c })) : [] };
}

export function saveSettings(settings) {
  storage.set("tc.settings", settings);
}

/** The provider as configured now: preset + the user's model, base URL and key. */
export function activeProvider(settings) {
  const p = providerById(settings.provider, settings);
  return {
    ...p,
    model: (p.custom ? p.default_model : settings.models[p.id] || p.default_model) || (p.examples || [])[0] || "",
    baseUrl: ((p.custom ? p.base_url : settings.baseUrls[p.id] || p.base_url) || "").trim().replace(/\/+$/, ""),
    apiKey: settings.keys[p.id] || "",
  };
}
