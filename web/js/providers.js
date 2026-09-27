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
  toolMode: "core",        // core (a dozen tools + catalog/call) | all (every tool directly)
  maxSteps: 16,
  resultChars: 16000,
  instructions: "",
  theme: "system",
  verifyQuotes: true,
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

export const allProviders = () => providers;
export const providerById = (id) => providers.find((p) => p.id === id) || providers[0];

export function loadSettings() {
  const saved = storage.get("tc.settings", {}) || {};
  return { ...DEFAULTS, ...saved, models: { ...(saved.models || {}) }, baseUrls: { ...(saved.baseUrls || {}) }, keys: { ...(saved.keys || {}) } };
}

export function saveSettings(settings) {
  storage.set("tc.settings", settings);
}

/** The provider as configured now: preset + the user's model, base URL and key. */
export function activeProvider(settings) {
  const p = providerById(settings.provider);
  return {
    ...p,
    model: settings.models[p.id] || p.default_model || (p.examples || [])[0] || "",
    baseUrl: (settings.baseUrls[p.id] || p.base_url || "").replace(/\/+$/, ""),
    apiKey: settings.keys[p.id] || "",
  };
}

export function providerInitial(p) {
  const s = (p?.label || p?.id || "?").replace(/[（(].*$/, "").trim();
  return /^[A-Za-z]/.test(s) ? s.slice(0, 1).toUpperCase() : s.slice(0, 1);
}
