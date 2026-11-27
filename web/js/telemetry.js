// What the page tells the site of its own use, in counts — for the site's activity ledger (security/ledger.js), where
// the site has one (the relay's health says so: activity).  Three things, and nothing a visitor wrote:
//
//   hello     once the page has loaded on the site's own host: the site says who this browser is to the ledger — an id
//             made from a cookie no script reads (shown under 设置 → 数据, where it can be forgotten) and a pass for the
//             relay — and counts a page that loaded
//   the name  of each turn (X-Tao-Turn: the answer's message id), with every call the relay makes for it: a question is
//             counted once however many calls it takes.  With it, the pass (X-Tao-Visitor) — unless the conversation
//             touches the visitor's own health or data: such a turn is counted, and for no one
//   the end   of each turn (POST /v1/activity): how it ended, its rounds, its tools by name, its tokens.  A question
//             asked of a visitor's own model never passes the relay: this is the only word of it.  Never the question,
//             the answer, a tool's arguments, a key, or the name of a model or endpoint the visitor set by hand
//
// The visitor's switch (设置 → 数据 → 访问统计) stops all three: no hello, no pass, no end — the page then sends what it
// sent before there was a ledger, and the site counts what reaches it without a visitor.  A browser that asks not to be
// tracked (Global Privacy Control, Do Not Track) is the switch already off.  Where the site asks first (ids: optin),
// nothing is sent until the switch is on.

import { LANG } from "./i18n.js";
import { storage } from "./util.js";

const KEY = "tc.stats"; // "on" | "off" | absent: the visitor's own choice, in this browser
const state = { relay: null, told: null, asked: null }; // the relay (its url and what it takes), what hello said, the hello under way

/** The relay as the page knows it ({url, ok, activity}), told whenever its health is read. */
export function setRelay(relay) {
  state.relay = relay;
}

const mode = () => (state.relay?.ok && state.relay.activity?.beacon ? state.relay.activity.ids || "off" : null); // null: no ledger here

/** Does the browser ask not to be tracked? */
export const declined = () => Boolean(globalThis.navigator?.globalPrivacyControl) || globalThis.navigator?.doNotTrack === "1";

/** The visitor's choice: "on", "off", or null when they made none (then the site's mode decides). */
export const choice = () => { const v = storage.get(KEY); return v === "on" || v === "off" ? v : null; };

/** May the page send its counts: the site has a ledger, the browser does not decline, and the switch is not off — or,
 * where the site asks first, is on. */
export function sending() {
  const m = mode();
  if (!m || declined()) return false;
  return m === "optin" ? choice() === "on" : choice() !== "off";
}

/** What 设置 → 数据 shows: {ledger, mode, on, declined, visitor, state} — visitor: this browser's id in the ledger, when
 * the site said one. */
export function status() {
  const m = mode();
  return { ledger: Boolean(m), mode: m, on: sending(), declined: declined(), visitor: state.told?.visitor || null, state: state.told?.state || null };
}

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  return r.ok ? r.json() : null;
}

/**
 * Once the page has loaded and the relay has answered: who this browser is to the ledger, asked of the page's own host.
 * A copy of the page elsewhere (the mirror, a local server) has no site behind it: the question goes unanswered, and
 * its turns are counted without a visitor.  Never throws; asked once a page.
 */
export function hello() {
  if (!sending() || state.asked) return state.asked || Promise.resolve(null);
  state.asked = post("api/activity/hello", { v: 1, lang: LANG }).then((told) => { state.told = told?.ledger ? told : null; return state.told; }).catch(() => null);
  return state.asked;
}

/** The pass for the relay while it lasts, or "": the page then names its turns and not its visitor. */
function pass() {
  const t = state.told;
  return sending() && t?.pass && t.expires - Date.now() > 60000 ? t.pass : "";
}

/**
 * The headers a turn's calls to the relay carry: its name, when the relay counts turns (named: it does — its health
 * says so, or the model is one it limits in questions), and the visitor's pass unless the turn is `unnamed` (it touches
 * the visitor's own health or data).
 */
export function turnHeaders(id, { named = Boolean(state.relay?.activity?.turn), unnamed = false } = {}) {
  if (!named) return {};
  const p = unnamed ? "" : pass();
  return { "X-Tao-Turn": id, ...(p ? { "X-Tao-Visitor": p } : {}) };
}

// a tool by the name the site gave it: `classics.search`, through the catalog too
const TOOL = /^[a-z][a-z0-9_.]{1,60}$/;
const toolName = (c) => String(c.name === "taochronos_call" ? c.args?.tool ?? "" : c.name || "").replace(/__/g, ".");

/**
 * A turn's end, as the relay takes it (relay/src/relay.js: normalizeTurn).  provider: the page's provider of the turn
 * ({id, relay, custom, model, examples}); trace: the turn's own (agent.js: runTurn); module: chat | diet | medicinal |
 * mydata | research; consent: whether the visitor agreed to their turns being recorded.  A provider or a model the
 * visitor set by hand is their setting, and is not named: "custom", and no model.
 */
export function turnEnd({ id, provider = {}, status, rounds, usage, ms, trace, module = "chat", turnIndex, consent, runtime, corpus, unnamed = false }) {
  const tools = {};
  let count = 0;
  for (const c of trace?.tools || []) {
    const name = toolName(c);
    count += 1;
    if (TOOL.test(name) && (tools[name] || Object.keys(tools).length < 20)) tools[name] = (tools[name] || 0) + 1;
  }
  const known = provider.relay || (!provider.custom && (provider.examples || []).includes(provider.model));
  const p = unnamed ? "" : pass();
  return JSON.parse(JSON.stringify({
    v: 1, kind: "turn", turn: id, pass: p || undefined,
    provider: provider.fixed ? "fixed" : provider.custom ? "custom" : provider.id, model: known ? provider.model : undefined,
    status: ["done", "error", "stopped"].includes(status) ? status : undefined, rounds: Number.isFinite(rounds) ? rounds : undefined,
    tool_count: count || undefined, tools: count ? tools : undefined, retries: (trace?.requests || []).filter((q) => q.attempt > 1).length || undefined,
    input: usage?.input || undefined, output: usage?.output || undefined, ms: Number.isFinite(ms) ? Math.round(ms) : undefined,
    runtime: runtime === "server" || runtime === "browser" ? runtime : undefined, corpus: typeof corpus === "string" ? corpus : undefined,
    module, turn_index: Number.isFinite(turnIndex) ? turnIndex : undefined, consent: typeof consent === "boolean" ? consent : undefined, lang: LANG,
  }));
}

/** A turn's end to the relay, when the page may send its counts.  Never waited for, never the visitor's concern. */
export function report(end) {
  if (!sending() || !state.relay?.url) return;
  try {
    // text/plain: a simple request, no preflight (the relay reads the body as JSON whatever its type)
    fetch(`${state.relay.url}/v1/activity`, { method: "POST", headers: { "Content-Type": "text/plain;charset=UTF-8" }, body: JSON.stringify(end), keepalive: true })
      .catch(() => {});
  } catch { /* not the visitor's concern */ }
}

/**
 * The visitor's switch.  on: false — no id from now on: the site's cookie says so (where the page has a site behind it)
 * and this browser remembers; true — an id is made.  → what status() then says.
 */
export async function setSending(on) {
  storage.set(KEY, on ? "on" : "off");
  state.asked = null;
  if (mode()) {
    const told = await post("api/activity/choice", { ids: on ? "on" : "off" }).catch(() => null);
    state.told = told?.ledger ? told : null;
  }
  return status();
}

/** Everything the ledger holds of this browser's visitor, deleted — and the count switched off.  → whether there was
 * anything to forget, or null when the site could not be asked. */
export async function forget() {
  storage.set(KEY, "off");
  state.asked = null;
  const told = await post("api/activity/forget", {}).catch(() => null);
  state.told = null;
  return told ? Boolean(told.forgotten) : null;
}
