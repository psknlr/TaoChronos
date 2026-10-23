// Model providers (providers.json, written from the harness's own presets) and the user's settings.
// API keys are kept in this browser's localStorage only, and sent only to the provider (or your local server's proxy).
// 道乃久默认服务 (the site's relay, site.json) needs no key: the relay holds it, and no key is ever sent to it.

import { MODEL, PUBLISHER } from "./brand.js";
import { storage } from "./util.js";
import { T } from "./i18n.js";


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
  maxTokens: null,         // tokens a reply may use, its thinking included; null: as outputLimit decides
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

// what a reply may use where the visitor set no number and the service names no ceiling of its own: Claude (the
// Anthropic preset), which the page always streams, what Anthropic advises for a streamed reply; any other service, and
// an endpoint set by hand, a number most of them accept
const AUTO_TOKENS = { claude: 64000, other: 16000 };
const OLD_DEFAULT = 16000; // what an older page kept as the visitor's number when they had set none

/** The tokens a reply may use, its thinking included: the number the visitor set, within the service's own ceiling (the
 * default service's); with none set, that ceiling, or AUTO_TOKENS for a service that names none. */
export function outputLimit(settings, provider) {
  const set = Math.floor(Number(settings?.maxTokens)) || 0;
  const ceiling = Math.floor(Number(provider?.max_output)) || 0;
  if (ceiling) return set > 0 ? Math.min(set, ceiling) : ceiling;
  return set > 0 ? set : AUTO_TOKENS[provider?.format === "anthropic" && !provider.custom ? "claude" : "other"];
}

export const RELAY_ID = "impf";
let relay = null; // {url, ok, model, models, logs, limits} once the site's relay has answered (or failed to)

export function setRelay(r) { relay = r; }

/** The default service as a provider: the site's relay, no key.  The page knows its model by the name the relay gives
 * (Tao-R1); whatever the model behind it needs besides, the relay adds. */
function relayPreset() {
  if (!relay?.url) return null;
  const models = relay.models?.length ? relay.models : relay.model ? [relay.model] : [];
  return {
    id: RELAY_ID, label: T("道乃久默认服务"), format: "openai", base_url: `${relay.url}/v1`, key_optional: true, relay: true,
    max_tokens_param: "max_completion_tokens", extra_body: {}, thinking_off: { thinking: { type: "disabled" } }, examples: models,
    default_model: relay.model || models[0] || "", reasoning: "reasoning_details", vision: true, stream_usage: true,
    unavailable: !relay.ok, max_output: relay.maxOutput || null,
    note: relay.ok
      ? T`${PUBLISHER}提供，无需 API Key，直接提问${relay.limits?.per_day ? T`；测试期间每人每天约 ${relay.limits.per_day} 次模型调用（一个问题通常用几次）` : ""}。`
      : T("默认服务暂时连不上：请稍后再试，或选择其他服务并填入自己的 API Key。"),
  };
}

export async function loadProviders() {
  try {
    const r = await fetch("providers.json", { cache: "no-cache" });
    if (r.ok) {
      const list = await r.json();
      // their names and notes are written in Chinese (src/taochronos/chat/providers.py): shown in the page's language
      if (Array.isArray(list) && list.length) providers = list.map((x) => ({ ...x, label: T(x.label), note: x.note && T(x.note) }));
    }
  } catch { /* the embedded preset is enough to start */ }
  return providers;
}

/** An endpoint the user set by hand, as a provider the page can call. */
export function customPreset(c) {
  const anthropic = c.format === "anthropic";
  return {
    id: c.id, label: c.label || T("自定义 API"), format: anthropic ? "anthropic" : "openai", base_url: c.base_url || "",
    full_url: Boolean(c.full_url) && !anthropic, key_optional: true, max_tokens_param: c.max_tokens_param || "max_tokens",
    extra_body: c.extra_body || {}, headers: c.headers || {}, examples: c.model ? [c.model] : [], default_model: c.model || "",
    reasoning: anthropic ? "thinking" : c.reasoning || null, vision: Boolean(c.vision), stream_usage: c.stream_usage !== false,
    custom: true, note: "",
  };
}

export function newCustomProvider(n = 1) {
  return { id: `custom-${Date.now().toString(36)}`, label: T`我的 API ${n}`, format: "openai", base_url: "", full_url: false, model: "",
    headers: {}, extra_body: {}, max_tokens_param: "max_tokens", reasoning: null, vision: false };
}

export const allProviders = (settings) => {
  const r = relayPreset();
  return [...(r ? [r] : []), ...providers, ...(settings?.customProviders || []).map(customPreset)];
};
export const providerById = (id, settings) => allProviders(settings).find((p) => p.id === id) || providers[0];

export function loadSettings() {
  const saved = storage.get("tc.settings", {}) || {};
  if (saved.maxTokens === OLD_DEFAULT) delete saved.maxTokens; // the old default, kept by an older page: as outputLimit decides
  return { ...DEFAULTS, ...saved, models: { ...(saved.models || {}) }, baseUrls: { ...(saved.baseUrls || {}) }, keys: { ...(saved.keys || {}) },
    customProviders: Array.isArray(saved.customProviders) ? saved.customProviders.map((c) => ({ ...c })) : [] };
}

export function saveSettings(settings) {
  storage.set("tc.settings", settings);
}

/** How a provider is named on the page: the default service by its own name (the page names no vendor behind it). */
export const modelLabel = (p) => (p.relay ? p.label : T`底层模型 ${p.model || T("未选")}（${p.label}）`);

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

// ------------------------------------------------------------------ what the page keeps of the default service
const PUBLIC_FORMAT = "Tao-";
// the default service words its errors itself, for the visitor; a turn made by an older page may keep other words
const OWN_WORDS = /默认服务|道乃久|对话太长|请求不是有效的 JSON|请求缺少 messages|没有这个接口|太频繁|免费额度/;
const SERVICE_FAILED = T("默认服务出错了，请稍后再试，或在“设置 → 模型”里填入自己的 API Key");
const MODEL_REFUSED = T("默认服务不提供这个模型：请在“设置 → 模型”里选用道乃久默认服务，或改用自己的 API Key");

/** An error of a default-service turn as the page shows it: the service's own words, without the model client's
 * preamble; anything else (what an older relay passed on) as a plain failure. */
export function publicError(text) {
  const m = /^(?:模型服务返回 \d+(?:（[^）]*）)?|模型服务报错|无法解析模型服务的回复)：([\s\S]*)$/.exec(String(text ?? ""));
  if (!m) return text;
  const said = m[1].replace(/API Key（[\s\S]*$/, "API Key").trim();
  if (said.startsWith("默认服务只提供")) return MODEL_REFUSED;
  return OWN_WORDS.test(said) ? said : SERVICE_FAILED;
}

/**
 * A stored conversation as the default service presents itself now (turns kept by an older page named more): its turns
 * carry the service's model name, the reasoning they send back the service's format names, and their errors its own
 * words.  Returns whether anything changed, for the caller to store it again.
 */
export function publicConversation(conv) {
  let changed = false;
  for (const m of Array.isArray(conv?.messages) ? conv.messages : []) {
    if (m?.role !== "assistant" || (m.provider !== RELAY_ID && m.wireProvider !== RELAY_ID)) continue;
    if (m.model !== MODEL) { m.model = MODEL; changed = true; }
    for (const w of Array.isArray(m.wire) ? m.wire : []) {
      for (const d of Array.isArray(w?.reasoning_details) ? w.reasoning_details : []) {
        if (typeof d?.format === "string" && !d.format.startsWith(PUBLIC_FORMAT) && /^[^-]+-./.test(d.format)) {
          d.format = PUBLIC_FORMAT + d.format.replace(/^[^-]+-/, "");
          changed = true;
        }
      }
    }
    if (typeof m.error === "string") {
      const e = publicError(m.error);
      if (e !== m.error) { m.error = e; changed = true; }
    }
  }
  return changed;
}
