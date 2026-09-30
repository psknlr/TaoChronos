// TaoChronos web client: conversations with a model that uses TaoChronos's tools, every quotation checked.

import { buildHistory, formatOf, runTurn, toolDefs, withoutReasoning } from "./agent.js";
import { streamClaude } from "./llm/anthropic.js";
import { streamChat } from "./llm/openai.js";
import { extractCitations, renderMarkdown } from "./markdown.js";
import { AGENT, MODEL as ASSISTANT, PUBLISHER, PUBLISHER_EN } from "./brand.js";
import { FIXED_ID, fixedReply, touchesIdentity } from "./fixed.js";
import { activeProvider, allProviders, loadProviders, loadSettings, modelLabel, RELAY_ID, saveSettings, setRelay } from "./providers.js";
import { consent, NOTICE, setConsent } from "./records.js";
import { BrowserRuntime, probeServer, sameOriginServer, ServerRuntime } from "./runtime.js";
import * as store from "./store.js";
import {
  $, bare, copyText, count, dateGroup, debounce, download, fmtMs, h, icon, passageLabel, replace, sleep, storage, throttleFrame, toast,
  truncate, uid, yearLabel,
} from "./util.js";
import { renderDrawer, reportNode } from "./view/drawer.js";
import { openSettings } from "./view/settings.js";
import { answerText, fillAssistant, renderedCites, renderThread, toolFamily, verifyBar } from "./view/thread.js";

// ------------------------------------------------------------------ state
const S = {
  settings: loadSettings(),
  runtime: null,
  here: null,              // the TaoChronos server that served this page, if one did
  runtimeInfo: null,
  runtimeState: { status: "idle", progress: 0, message: "" },
  relay: null,             // 道乃久默认服务: {url, ok, model, models, logs, limits, pending} when the site has one (site.json)
  relayReady: null,
  relayRetry: null,
  catalogs: {},
  catalogAll: null,
  catalogIndex: new Map(),
  list: [],
  conv: null,
  running: null,
  researchRunning: null,
  drawer: { open: false, tab: "evidence", pid: null, quote: null, vertical: false, tool: null, toolQuery: "", famOpen: new Set(), toolArgs: {} },
  ui: { editing: null, openThink: new Set(), openSteps: new Set(), closedSteps: new Set(), openTools: new Set(), search: "", attachments: [] },
  passages: new Map(),
  verify: new Map(),
  stick: true,
};

const el = {
  app: $("#app"), sidebar: $("#sidebar"), convs: $("#convs"), search: $("#search"), pill: $("#runtime-pill"), theme: $("#theme-btn"),
  settingsBtn: $("#settings-btn"), newChat: $("#new-chat"), newChatTop: $("#new-chat-top"), collapse: $("#collapse-sidebar"),
  main: $("#main"), toggleSidebar: $("#toggle-sidebar"), modelChip: $("#model-chip"), title: $("#conv-title"),
  toggleDrawer: $("#toggle-drawer"), thread: $("#thread"), inner: $("#thread-inner"), toBottom: $("#to-bottom"),
  composer: $("#composer"), input: $("#input"), send: $("#send"), attach: $("#attach"), file: $("#file"), attachments: $("#attachments"),
  hint: $("#hint"), drawer: $("#drawer"), scrim: $("#scrim"), settings: $("#settings"), report: $("#report"), consent: $("#consent"),
};

const mobile = () => matchMedia("(max-width: 980px)").matches;

// ------------------------------------------------------------------ runtime
// Auto: the server that served this page (the site's own, on Cloudflare: the full corpus; or `taochronos serve`); else
// the server this browser last worked with (the full corpus), when it answers; else TaoChronos in this browser (the
// 要籍语料).  When the site's own server cannot answer, the page carries on in the browser.
const KNOWN_SERVER = "tc.server";

async function chooseRuntime() {
  const { runtime: pref, serverUrl, serverToken: token } = S.settings;
  if (pref === "server") return new ServerRuntime(serverUrl, token);
  if (pref === "browser") return new BrowserRuntime();
  S.here = await sameOriginServer(token);
  if (S.here) return new ServerRuntime(S.here, token, { label: siteServer() ? "本站服务" : "", fallback: inBrowserInstead });
  const known = storage.get(KNOWN_SERVER, null);
  if (known) {
    S.runtimeState = { status: "loading", progress: 12, message: `寻找 TaoChronos 服务 ${known.replace(/^https?:\/\//, "")}` };
    renderPill();
    if (await probeServer(known, token)) return new ServerRuntime(known, token);
  }
  return new BrowserRuntime();
}

/** Is this page served by the site's own server (not `taochronos serve` on this or another machine)? */
function siteServer() {
  return !isLoopbackHost(location.hostname) && !/^\d+\.\d+\.\d+\.\d+$|^\[/.test(location.hostname) && !location.port;
}
const isLoopbackHost = (host) => ["localhost", "127.0.0.1", "[::1]", "::1"].includes(host);

/** The site's own server cannot answer: the page carries on with TaoChronos in this browser (the 要籍语料). */
function inBrowserInstead(err) {
  const rt = new BrowserRuntime();
  toast(`全量语料服务暂不可用（${truncate(err?.message || "", 40)}），改用浏览器内的要籍语料`, "err");
  switchRuntime(rt);
  return rt;
}

let runtimeSwitch = null;
/** Use `ready` (a runtime already connected) or choose one; the previous runtime is stopped. */
function switchRuntime(ready = null) {
  runtimeSwitch = (async () => {
    const rt = ready || (await chooseRuntime());
    if (S.runtime && S.runtime !== rt) S.runtime.stop?.();
    S.runtime = rt;
    S.runtimeInfo = null;
    S.catalogs = {};
    S.catalogAll = null;
    S.passages.clear();
    S.verify.clear();
    folds.clear();
    foldsNow.clear();
    rt.onStatus((st) => {
      if (S.runtime !== rt) return;
      S.runtimeState = st;
      renderPill();
      renderComposerHint();
      if (!S.conv?.messages.length) renderMain();
    });
    rt.start().then((info) => {
      if (S.runtime !== rt) return;
      S.runtimeInfo = info;
      if (rt.kind === "server") storage.set(KNOWN_SERVER, rt.url); // auto mode tries it first from now on
      renderPill();
      renderComposerHint();
      if (!S.conv?.messages.length) renderMain();
      refreshAllCites();
    }).catch((err) => {
      if (S.runtime === rt && rt.fallback && !rt.backup && err?.unavailable) rt.backup = rt.fallback(err); // else shown in the pill
    });
  })();
  return runtimeSwitch;
}

const corpusLabel = (c) => c?.label || (c?.demo ? "演示语料" : "全量语料");

/** "全量语料 966 部书、205 万段、1.2 亿字 · 88 项工具" */
function describeRuntime(info, sep = "、") {
  const c = info?.corpus || {};
  const books = c.kind === "canon" && c.canon?.held ? `${c.canon.held} 部要籍` : count(c.books, "部书");
  return `${corpusLabel(c)} ${[books, count(c.passages, "段"), c.characters ? count(c.characters, "字") : null].filter(Boolean).join(sep)} · ${info?.tools?.offered ?? "?"} 项工具`;
}

async function ensureRuntime() {
  if (!S.runtime) await (runtimeSwitch || switchRuntime());
  try {
    await S.runtime.start();
  } catch (err) {
    if (await fellBack(err)) return ensureRuntime();
    throw new Error(`TaoChronos 运行环境不可用：${err.message}`);
  }
  S.runtimeInfo = await S.runtime.info();
  return S.runtime;
}

/** The site's own server could not be reached: the page has carried on in the browser (true), or it had no other way. */
async function fellBack(err) {
  const rt = S.runtime;
  if (rt?.kind !== "server" || !rt.fallback || !err?.unavailable) return false;
  rt.backup ||= rt.fallback(err);
  await runtimeSwitch;
  return S.runtime !== rt;
}

/** The runtime a turn runs on.  A browser runtime still loading describes itself from its boot file, so that the model
 * is asked at once; the tools it calls wait for the runtime (runtime.call waits until it is ready). */
async function turnRuntime() {
  if (!S.runtime) await (runtimeSwitch || switchRuntime());
  if (S.runtime.kind !== "browser" || S.runtime.state?.status === "error") {
    try {
      await S.runtime.start();
    } catch (err) {
      if (await fellBack(err)) return turnRuntime();
      throw new Error(`TaoChronos 运行环境不可用：${err.message}`);
    }
    S.runtimeInfo = await S.runtime.info();
    return S.runtime;
  }
  S.runtimeInfo ||= await S.runtime.info();
  return S.runtime;
}

async function getCatalog(mode) {
  if (!S.catalogs[mode]) {
    S.catalogs[mode] = await S.runtime.catalog(mode);
    for (const t of S.catalogs[mode].tools) S.catalogIndex.set(t.name, t);
  }
  return S.catalogs[mode];
}

function routeFor(settings = S.settings) {
  const server = S.runtime?.kind === "server" ? S.runtime : null;
  const p = activeProvider(settings);
  if (p.relay) return { kind: "direct" }; // the default service is reached directly, never through a local server
  const custom = p.custom; // a hand-set endpoint goes direct unless told otherwise (the proxy lists hosts)
  // a server started without its model proxy (the site's own) forwards no model calls
  if (settings.route === "proxy" || (settings.route === "auto" && server && !custom && S.runtimeInfo?.proxy !== false)) {
    return { kind: "proxy", serverUrl: server ? server.url : settings.serverUrl, token: server ? server.token : settings.serverToken || "" };
  }
  return { kind: "direct" };
}

function needsKey() {
  if (S.relay?.pending) return false; // the default service is being checked: sending waits for it
  const p = activeProvider(S.settings);
  if (p.apiKey || p.key_optional) return false;
  return !(routeFor().kind === "proxy" && S.runtimeInfo?.env_keys);
}

/** The runtime's standing instructions (they end with 运行环境) and the user's own instructions.  The model underneath is
 * not named in them: asked what it is built on, 道乃久 neither names nor denies it (fixed.js, 身份). */
function systemPrompt() {
  const base = S.runtimeInfo?.system_prompt || "";
  const extra = (S.settings.instructions || "").trim();
  return `${base}${extra ? `\n\n## 用户的附加指令\n${extra}` : ""}`;
}

// ------------------------------------------------------------------ passages and citations
function getPassage(pid) {
  if (!S.passages.has(pid)) {
    const p = S.runtime.passage(pid)
      .then((card) => { S.passages.set(pid, card); return card; })
      .catch((err) => { const card = { ok: false, passage_id: pid, error: err.message }; S.passages.delete(pid); return card; });
    S.passages.set(pid, p);
  }
  return Promise.resolve(S.passages.get(pid));
}

function passageNow(pid) {
  const v = S.passages.get(pid);
  return v && typeof v.then !== "function" ? v : null;
}

const toolTextCache = new WeakMap();
function toolText(conv) {
  if (!conv) return "";
  const stamp = `${conv.updated}:${conv.messages.length}`;
  const hit = toolTextCache.get(conv);
  if (hit && hit.stamp === stamp) return hit.text;
  const parts = [];
  for (const m of conv.messages) {
    for (const w of m.wire || []) {
      if (w.role === "tool" && typeof w.content === "string") parts.push(w.content);
      if (Array.isArray(w.content)) for (const b of w.content) if (b.type === "tool_result") parts.push(typeof b.content === "string" ? b.content : JSON.stringify(b.content));
    }
    for (const seg of m.segments || []) for (const c of seg.calls || []) if (c.preview) parts.push(c.preview);
  }
  for (const r of conv.research || []) parts.push(JSON.stringify(r.result?.hypotheses || []));
  const text = parts.join("\n");
  toolTextCache.set(conv, { stamp, text });
  return text;
}

const folds = new Map();
const foldsNow = new Map();
/** A text in the harness's normalised forms (繁→简, 异体, 通假), for comparing a quotation with its passage. */
function normalized(text, pid) {
  const key = pid ? `p:${pid}` : `q:${text}`;
  if (!folds.has(key)) {
    folds.set(key, S.runtime.call("philology.normalize", { text }, { maxChars: 1000 })
      .then((out) => { const v = out?.ok ? out.result?.normalized ?? null : null; foldsNow.set(key, v); return v; })
      .catch(() => null));
  }
  return folds.get(key);
}

const citeKey = (pid, quote) => `${S.conv?.id || ""}|${pid}|${quote || ""}`;

function statusFor(pid, quote) {
  const v = S.verify.get(citeKey(pid, quote));
  return v && typeof v.then !== "function" ? v : null;
}

function queueVerify(pid, quote) {
  const key = citeKey(pid, quote);
  if (S.verify.has(key) || !S.runtime) return;
  const conv = S.conv;
  const job = (async () => {
    const card = await getPassage(pid);
    let res;
    if (!card?.ok) {
      res = { status: "bad", label: "查无此段", mark: "✕", title: "当前语料中没有这个段落号：可能是模型编造的出处，或它来自另一个语料" };
    } else {
      const grounded = toolText(conv).includes(pid);
      if (quote && S.settings.verifyQuotes !== false) {
        let ok = bare(card.text).includes(bare(quote));
        let folded = false;
        if (!ok) { // another script or variant forms of the same words: compare after the harness's own normalisation
          const [q, t] = await Promise.all([normalized(quote), normalized(card.text, pid)]);
          folded = ok = Boolean(q && t && bare(t).includes(bare(q)));
        }
        const unseen = grounded ? "" : "（此段未经本轮工具返回）";
        res = ok
          ? { status: "ok", label: "原文一致", mark: "✓", title: folded ? `引文与《${card.title}》原文在繁简、异体归一后一致${unseen}` : `引文与《${card.title}》原文逐字一致${unseen}` }
          : { status: "warn", label: "与原文不符", mark: "≠", title: "引文与原文未能逐字对应（繁简、异体归一后亦然）：可能是节引、改写或误引，请点开核对" };
      } else {
        res = grounded
          ? { status: "ok", label: "出处已检", mark: "○", title: "出处经本轮工具返回（没有直接引文可逐字核对）" }
          : { status: "warn", label: "未经检索", mark: "?", title: "出处存在于语料，但未经本轮工具返回" };
      }
    }
    S.verify.set(key, res);
    refreshCites(pid);
    return res;
  })();
  S.verify.set(key, job);
}

function citeChip(pid, quote, card) {
  card = card || S.conv?.evidence?.[pid] || passageNow(pid);
  const st = quote === undefined ? null : statusFor(pid, quote);
  const b = h("button.cite", {
    type: "button", class: st?.status || (quote === undefined ? "" : "pending"),
    title: st?.title || (quote === undefined ? "查看原文" : "核对中…"),
    dataset: { pid, quote: quote || "", cite: quote === undefined ? "card" : "text" },
  }, st ? h("span.mk", st.mark) : null, passageLabel(card?.ok === false ? null : card, pid));
  b.addEventListener("click", (e) => { e.stopPropagation(); openPassage(pid, quote || null); });
  if (!st && quote !== undefined) queueVerify(pid, quote);
  return b;
}

function refreshCites(pid) {
  for (const b of document.querySelectorAll(`.cite[data-pid="${CSS.escape(pid)}"][data-cite="text"]`)) {
    const st = statusFor(pid, b.dataset.quote || null);
    if (!st) continue;
    b.className = `cite ${st.status}`;
    b.title = st.title;
    let mk = b.querySelector(".mk");
    if (!mk) { mk = h("span.mk"); b.prepend(mk); }
    mk.textContent = st.mark;
    const card = S.conv?.evidence?.[pid] || passageNow(pid);
    if (card && card.ok !== false) b.lastChild.textContent = passageLabel(card, pid);
  }
  refreshVerifyBars();
  if (S.drawer.open && S.drawer.tab === "evidence") renderDrawerSoon();
}

const refreshVerifyBars = debounce(() => {
  if (!S.conv) return;
  for (const bar of document.querySelectorAll(".verify-bar[data-verify]")) {
    const m = S.conv.messages.find((x) => x.id === bar.dataset.verify);
    const body = bar.closest(".body");
    const next = m && body ? verifyBar(m, threadCtx, renderedCites(body)) : null;
    if (next) bar.replaceWith(next); else bar.remove();
  }
}, 60);

function refreshAllCites() {
  for (const b of document.querySelectorAll(".cite[data-cite='text']")) queueVerify(b.dataset.pid, b.dataset.quote || null);
}

function bestStatus(pid) {
  if (!S.conv) return null;
  const found = [];
  for (const [k, v] of S.verify) if (k.startsWith(`${S.conv.id}|${pid}|`) && v && typeof v.then !== "function") found.push(v);
  if (!found.length) return null;
  return found.find((v) => v.status === "bad") || found.find((v) => v.status === "warn") || found[0];
}

function citesOf(m) {
  return extractCitations(answerText(m));
}

function registerEvidence(conv, cards) {
  if (!conv || !cards?.length) return;
  conv.evidence ||= {};
  for (const c of cards) {
    if (!c?.passage_id) continue;
    const old = conv.evidence[c.passage_id];
    if (!old) conv.evidence[c.passage_id] = { ...c };
    else for (const [k, v] of Object.entries(c)) if (v !== undefined && v !== null && v !== "" && (old[k] === undefined || (k === "text" && String(v).length > String(old.text || "").length))) old[k] = v;
  }
}

// ------------------------------------------------------------------ conversations
function newConversation(title = "新对话") {
  return { id: uid("c_"), title, created: Date.now(), updated: Date.now(), pinned: false, messages: [], evidence: {}, research: [] };
}

const persistNow = async (conv) => {
  if (!conv) return;
  try {
    await store.putConversation(conv);
  } catch (err) {
    toast(`保存失败：${err.message}`, "err");
  }
};
const persistSoon = debounce((conv) => persistNow(conv), 600);

function touch(conv) {
  conv.updated = Date.now();
  if (!S.list.includes(conv)) S.list.unshift(conv);
}

async function openConversation(id) {
  if (S.running && S.running.convId !== id) { /* a turn keeps running in the background; its conversation keeps updating */ }
  const conv = S.list.find((c) => c.id === id) || (await store.getConversation(id));
  if (!conv) return newChat();
  S.conv = conv;
  S.ui.editing = null;
  S.drawer.pid = null;
  location.hash = `#/c/${conv.id}`;
  closeSidebarOnMobile();
  renderAll();
  scrollToBottom(false);
}

function newChat() {
  S.conv = null;
  S.ui.editing = null;
  S.ui.attachments = [];
  S.drawer.pid = null;
  history.replaceState(null, "", location.pathname + location.search);
  closeSidebarOnMobile();
  renderAll();
  el.input.focus();
}

async function deleteConversation(conv) {
  if (!confirm(`删除对话「${truncate(conv.title, 30)}」？此操作不可撤销。`)) return;
  if (S.running?.convId === conv.id) stop();
  await store.deleteConversation(conv.id);
  S.list = S.list.filter((c) => c !== conv);
  if (S.conv === conv) newChat(); else renderSidebar();
}

// ------------------------------------------------------------------ sending
async function send(text, images = []) {
  text = (text || "").trim();
  if (!text && !images.length) return;
  if (S.running) return;
  if (!fixedReply(text, images)) { // a question the page answers itself needs no model, so no key
    if (S.relay?.pending) await S.relayReady;
    if (needsKey() && S.relay?.url && !S.relay.ok) await recheckRelay([15000]); // the default service, once more
    if (needsKey()) {
      el.input.value = text;
      autosize();
      toast(`请先为 ${ASSISTANT} 配置底层模型的 API Key`);
      openSettings(S, settingsCtx, "model");
      return;
    }
  }
  if (S.relay?.ok && S.relay.logs && consent() === null) await askConsent();
  let conv = S.conv;
  if (!conv) {
    conv = newConversation(truncate(text.replace(/\s+/g, " "), 30) || "图片");
    S.conv = conv;
    location.hash = `#/c/${conv.id}`;
  }
  conv.messages.push({ id: uid("m_"), role: "user", text, images, created: Date.now() });
  const msg = { id: uid("m_"), role: "assistant", created: Date.now(), status: "streaming", segments: [] };
  conv.messages.push(msg);
  touch(conv);
  el.input.value = "";
  S.ui.attachments = [];
  autosize();
  renderAttachments();
  renderAll();
  scrollToBottom(true);
  await runAssistant(conv, msg);
}

async function runAssistant(conv, msg) {
  const idx = conv.messages.indexOf(msg);
  const user = conv.messages[idx - 1];
  const fixed = fixedReply(user.text, user.images);
  if (fixed) return answerFixed(conv, msg, fixed);
  // asked, even in passing, who answers or what it runs on: no thinking is asked for, and none is shown or kept
  const hidden = touchesIdentity(user.text);
  const controller = new AbortController();
  S.running = { controller, convId: conv.id, msgId: msg.id };
  renderComposer();
  const provider = activeProvider(S.settings);
  msg.model = provider.model;
  msg.provider = provider.id;
  const started = Date.now();
  const sink = [];
  msg.wire = hidden ? [] : sink; // a hidden turn's messages are kept only once their reasoning is removed
  if (hidden) msg.hideThinking = true;
  msg.wireFormat = formatOf(provider);
  msg.wireProvider = provider.id;
  try {
    const runtime = await turnRuntime();
    const catalog = await getCatalog(S.settings.toolMode);
    const history = buildHistory(conv.messages.slice(0, idx - 1), provider);
    const result = await runTurn({
      provider, settings: hidden ? { ...S.settings, thinking: false } : S.settings, route: routeFor(), runtime,
      tools: toolDefs(catalog), system: systemPrompt(), history, user, signal: controller.signal, hooks: makeHooks(conv, msg), sink,
    });
    msg.rounds = result.rounds;
    msg.usage = result.usage;
    if (result.model) msg.model = result.model;
    msg.status = controller.signal.aborted ? "stopped" : "done";
  } catch (err) {
    if (err?.name === "AbortError" || controller.signal.aborted) msg.status = "stopped";
    else { msg.status = "error"; msg.error = err?.message || String(err); }
  } finally {
    msg.ms = Date.now() - started;
    if (hidden) msg.wire = withoutReasoning(sink);
    for (const seg of msg.segments) for (const c of seg.calls || []) if (c.status === "running" || c.status === "preparing") { c.status = "error"; c.summary = "已停止"; }
    S.running = null;
    touch(conv);
    await persistNow(conv);
    if (S.conv === conv) {
      renderAll();
      if (S.stick) scrollToBottom(false);
    } else {
      renderSidebar();
    }
    renderComposer();
    recordTurn(conv, msg);
  }
}

/** A question the page answers itself (fixed.js): the same reply every time, without a model or tools. */
async function answerFixed(conv, msg, text) {
  Object.assign(msg, { status: "done", provider: FIXED_ID, rounds: 0, segments: [{ type: "text", round: 1, text }] });
  touch(conv);
  await persistNow(conv);
  if (S.conv === conv) {
    renderAll();
    if (S.stick) scrollToBottom(false);
  } else {
    renderSidebar();
  }
  recordTurn(conv, msg);
}

function makeHooks(conv, msg) {
  let round = 0;
  let refs = {};
  const update = () => { if (S.conv === conv) renderMessageSoon(msg); persistSoon(conv); };
  const segment = (type) => {
    if (!refs[type]) {
      refs[type] = type === "tools" ? { type, round, calls: [] } : { type, round, text: "" };
      msg.segments.push(refs[type]);
    }
    return refs[type];
  };
  const findCall = (id) => {
    for (const seg of msg.segments) for (const c of seg.calls || []) if (c.id === id) return c;
    return null;
  };
  return {
    round(n) { round = n; refs = {}; msg.rounds = n; },
    thinking(delta) {
      if (msg.hideThinking) return;
      const s = segment("thinking");
      s.started ||= Date.now();
      s.text += delta;
      s.ms = Date.now() - s.started;
      update();
    },
    text(full) { segment("text").text = full; update(); },
    toolPending(index, name) {
      const s = segment("tools");
      const key = `p${index}`;
      let c = s.calls.find((x) => x.pending === key);
      if (!c) { c = { pending: key, name: name || "…", status: "preparing", family: toolFamily(name || "", S.catalogIndex) }; s.calls.push(c); }
      else if (name && c.name === "…") { c.name = name; c.family = toolFamily(name, S.catalogIndex); }
      update();
    },
    toolStart(call) {
      const s = segment("tools");
      s.calls = s.calls.filter((c) => !c.pending);
      s.calls.push({ id: call.id, name: call.name, args: call.args, status: "running", family: toolFamily(call.name, S.catalogIndex), started: call.started });
      msg.toolCount = (msg.toolCount || 0) + 1;
      update();
    },
    toolProgress(call, p) {
      const c = findCall(call.id);
      if (!c) return;
      const pr = p?.progress || {};
      c.progress = `研究进行中${pr.round ? ` · 第 ${pr.round} 轮` : ""}${pr.hypotheses != null ? ` · ${pr.hypotheses} 个假说` : ""}${pr.claims != null ? ` · ${pr.claims} 条主张` : ""} · ${Math.round(p?.elapsed_s || 0)} 秒`;
      update();
    },
    toolEnd(call, out) {
      const c = findCall(call.id);
      if (!c) return;
      c.status = out.ok ? "ok" : "error";
      c.ms = Date.now() - (c.started || Date.now());
      c.summary = out.ok ? out.summary || "完成" : truncate(out.error || "失败", 120);
      c.error = out.ok ? null : out.error;
      c.preview = (out.text || "").slice(0, 8000);
      c.citations = (out.citations || []).slice(0, 80);
      if (out.tool && out.tool !== call.name) c.resolved = out.tool;
      toolTextCache.delete(conv); // what the tools returned has grown: citations are checked against it
      registerEvidence(conv, out.citations);
      if (out.ok && (call.name === "taochronos_research" || out.tool === "taochronos_research") && out.result?.session_id) {
        const run = addResearch(conv, out.result, c.ms);
        c.research = run.id;
        if (!mobile() && S.conv === conv) { S.drawer.open = true; S.drawer.tab = "research"; renderLayout(); renderDrawerSoon(); }
      }
      update();
      if (S.drawer.open && S.conv === conv) renderDrawerSoon();
    },
    retry(attempt) {
      msg.segments = msg.segments.filter((s) => s.round !== round || s.type === "tools");
      refs = Object.fromEntries(Object.entries(refs).filter(([k]) => k === "tools"));
      toast(`连接中断，正在重试（第 ${attempt} 次）…`);
      update();
    },
    usage(u) { msg.usage = { ...u }; },
    assistant(res) {
      if (res.thinking && !refs.thinking && !msg.hideThinking) segment("thinking").text = res.thinking;
      if (res.text && (!refs.text || refs.text.text !== res.text)) segment("text").text = res.text;
      update();
    },
    limit(max) { msg.error = `已达到每轮最多 ${max} 步工具调用的上限，回答可能不完整。可在设置中调高上限。`; },
  };
}

function addResearch(conv, result, ms) {
  conv.research ||= [];
  const run = { id: uid("r_"), session_id: result.session_id, question: result.question, created: Date.now(), ms, result };
  conv.research.push(run);
  toolTextCache.delete(conv);
  for (const hy of result.hypotheses || []) registerEvidence(conv, [...(hy.supporting || []), ...(hy.contradicting || [])].map((e) => ({ ...e, text: e.quote })));
  return run;
}

function stop() {
  S.running?.controller.abort();
}

async function regenerate(msgId) {
  const conv = S.conv;
  if (!conv || S.running) return;
  const idx = conv.messages.findIndex((m) => m.id === msgId);
  if (idx < 1) return;
  conv.messages.splice(idx);
  const msg = { id: uid("m_"), role: "assistant", created: Date.now(), status: "streaming", segments: [] };
  conv.messages.push(msg);
  touch(conv);
  renderAll();
  scrollToBottom(true);
  await runAssistant(conv, msg);
}

async function submitEdit(msgId, text) {
  const conv = S.conv;
  if (!conv || S.running) return;
  text = text.trim();
  if (!text) return;
  const idx = conv.messages.findIndex((m) => m.id === msgId);
  if (idx < 0) return;
  conv.messages[idx].text = text;
  conv.messages.splice(idx + 1);
  S.ui.editing = null;
  const msg = { id: uid("m_"), role: "assistant", created: Date.now(), status: "streaming", segments: [] };
  conv.messages.push(msg);
  touch(conv);
  renderAll();
  scrollToBottom(true);
  await runAssistant(conv, msg);
}

// ------------------------------------------------------------------ research and tools without a model
async function runResearchDirect(args) {
  if (S.researchRunning) return;
  let conv = S.conv;
  if (!conv) {
    conv = newConversation(`研究：${truncate(args.question, 24)}`);
    S.conv = conv;
    touch(conv);
    location.hash = `#/c/${conv.id}`;
  }
  const started = Date.now();
  S.researchRunning = "研究进行中…";
  renderDrawerSoon();
  try {
    await ensureRuntime();
    const out = await S.runtime.research(args, {
      maxChars: S.settings.resultChars,
      onProgress: (p) => {
        const pr = p?.progress || {};
        S.researchRunning = `研究进行中${pr.round ? ` · 第 ${pr.round} 轮` : ""}${pr.hypotheses != null ? ` · ${pr.hypotheses} 个假说` : ""} · ${Math.round(p?.elapsed_s || 0)} 秒`;
        renderDrawerSoon();
      },
    });
    if (!out?.ok) throw new Error(out?.error || "研究失败");
    addResearch(conv, out.result, Date.now() - started);
    touch(conv);
    await persistNow(conv);
    toast("研究完成");
  } catch (err) {
    toast(err.message, "err", 5000);
  } finally {
    S.researchRunning = null;
    renderAll();
  }
}

async function runTool(name, args) {
  try {
    await ensureRuntime();
    const out = await S.runtime.call(name, args, { maxChars: S.settings.resultChars });
    if (out.ok && S.conv) registerEvidence(S.conv, out.citations);
    for (const c of out.citations || []) if (!S.passages.has(c.passage_id)) { /* fetched on demand */ }
    return out;
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

// ------------------------------------------------------------------ drawer
function openPassage(pid, quote) {
  S.drawer.open = true;
  S.drawer.tab = "evidence";
  S.drawer.pid = pid;
  S.drawer.quote = quote;
  renderLayout();
  renderDrawer(el.drawer, S, drawerCtx);
  el.drawer.querySelector(".drawer-body")?.scrollTo({ top: 0 });
  getPassage(pid).then(() => { if (S.drawer.pid === pid) renderDrawerSoon(); });
}

const renderDrawerSoon = throttleFrame(() => { if (S.drawer.open) renderDrawer(el.drawer, S, drawerCtx); });

function openReport(run) {
  const body = h("div.modal-body", reportNode(run, threadCtx));
  el.report.replaceChildren(h("div.modal.wide",
    h("div.modal-head", icon("scroll"), h("h2", truncate(run.result?.question || "研究报告", 60)),
      h("button.icon-btn", { type: "button", "aria-label": "关闭", on: { click: () => el.report.close() } }, icon("x"))),
    body,
    h("div.modal-foot",
      h("span.muted", { style: { flex: 1, fontSize: "12.5px", alignSelf: "center" } }, "假说是计算推断，须经专家核验（G7）；不构成医学结论。"),
      h("button.btn.secondary", { type: "button", on: { click: () => downloadReport(run) } }, icon("download", "sm"), "下载 Markdown"),
      h("button.btn", { type: "button", on: { click: () => el.report.close() } }, "关闭"))));
  el.report.onclick = (e) => { if (e.target === el.report) el.report.close(); };
  el.report.showModal();
}

function downloadReport(run) {
  download(`TaoChronos-研究-${run.result?.session_id || run.id}.md`, run.result?.report_markdown || "", "text/markdown");
}

const drawerCtx = {
  setTab(tab) { S.drawer.tab = tab; renderDrawer(el.drawer, S, drawerCtx); },
  close() { S.drawer.open = false; renderLayout(); },
  openPassage,
  passageNow,
  folded: (pid, quote) => ({ text: foldsNow.get(`p:${pid}`) ?? null, quote: quote ? foldsNow.get(`q:${quote}`) ?? null : null }),
  loadPassage(pid) { getPassage(pid).then(() => renderDrawerSoon()); },
  citeStatus: statusFor,
  bestStatus,
  toggleVertical() { S.drawer.vertical = !S.drawer.vertical; renderDrawer(el.drawer, S, drawerCtx); },
  copy: (text) => copyText(text).then((ok) => toast(ok ? "已复制" : "复制失败")),
  runResearch: runResearchDirect,
  openReport,
  downloadReport,
  askAbout(run) {
    el.input.value = `关于研究会话 ${run.result?.session_id}（${run.result?.question}）：`;
    autosize();
    el.input.focus();
    if (mobile()) { S.drawer.open = false; renderLayout(); }
  },
  async loadCatalogAll() {
    try {
      await ensureRuntime();
      S.catalogAll = await S.runtime.catalog("all");
      for (const t of S.catalogAll.tools) S.catalogIndex.set(t.name, t);
    } catch (err) {
      S.catalogAll = { tools: [], families: {} };
      toast(err.message, "err");
    }
    renderDrawerSoon();
  },
  rerenderTools() {
    const body = el.drawer.querySelector(".drawer-body");
    const top = body?.scrollTop || 0;
    const focused = document.activeElement?.type === "search";
    renderDrawer(el.drawer, S, drawerCtx);
    const nb = el.drawer.querySelector(".drawer-body");
    if (nb) nb.scrollTop = top;
    if (focused) { const s = el.drawer.querySelector("input[type=search]"); s?.focus(); s?.setSelectionRange(s.value.length, s.value.length); }
  },
  pickTool(name) { S.drawer.tool = name; renderDrawer(el.drawer, S, drawerCtx); el.drawer.querySelector(".drawer-body")?.scrollTo({ top: 0 }); },
  runTool,
  cite: (pid, quote) => citeChip(pid, quote),
  citeCard: (card) => citeChip(card.passage_id, undefined, card),
};

// ------------------------------------------------------------------ rendering
const threadCtx = {
  get runtimeInfo() { return S.runtimeInfo; },
  get runtimeState() { return S.runtimeState; },
  get needsKey() { return needsKey(); },
  get relayActive() { return Boolean(S.relay?.ok && activeProvider(S.settings).relay); },
  get editing() { return S.ui.editing; },
  get running() { return Boolean(S.running); },
  openThink: S.ui.openThink,
  openSteps: S.ui.openSteps,
  closedSteps: S.ui.closedSteps,
  openTools: S.ui.openTools,
  onStarter(prompt) {
    if (needsKey()) { el.input.value = prompt; autosize(); el.input.focus(); openSettings(S, settingsCtx, "model"); return; }
    send(prompt);
  },
  onOpenSettings: () => openSettings(S, settingsCtx, "model"),
  onOpenRuntime: () => openSettings(S, settingsCtx, "runtime"),
  describeRuntime,
  get runtimeLabel() { return S.runtime?.label || "运行环境"; },
  onCopy: (text) => copyText(text).then((ok) => toast(ok ? "已复制" : "复制失败")),
  onEdit(id) { S.ui.editing = id; renderMain(); },
  onEditCancel() { S.ui.editing = null; renderMain(); },
  onEditSubmit: submitEdit,
  onRegenerate: regenerate,
  onOpenResearch(runId) {
    const run = S.conv?.research?.find((r) => r.id === runId);
    S.drawer.open = true;
    S.drawer.tab = "research";
    renderLayout();
    renderDrawer(el.drawer, S, drawerCtx);
    if (run && mobile()) { /* the panel is the full screen on phones */ }
  },
  cite: (pid, quote) => citeChip(pid, quote),
  citeCard: (card) => citeChip(card.passage_id, undefined, card),
  citesOf,
  citeStatus: statusFor,
};

function renderAll() {
  renderLayout();
  renderSidebar();
  renderTopbar();
  renderMain();
  renderComposer();
  renderPill();
  if (S.drawer.open) renderDrawer(el.drawer, S, drawerCtx);
}

function renderLayout() {
  el.app.classList.toggle("drawer-open", S.drawer.open);
  el.toggleDrawer.classList.toggle("on", S.drawer.open);
}

function renderMain() {
  const keep = el.thread.scrollTop;
  renderThread(el.inner, S.conv, threadCtx);
  el.thread.scrollTop = keep;
  renderTopbar();
}

const pendingRenders = new Set();
const flushRenders = throttleFrame(() => {
  for (const msg of pendingRenders) {
    const node = el.inner.querySelector(`.msg[data-id="${CSS.escape(msg.id)}"] .body`);
    if (!node) continue;
    const last = S.conv?.messages.at(-1) === msg;
    fillAssistant(node, msg, threadCtx, last);
    const live = node.querySelector(".think.live .tx");
    if (live) live.scrollTop = live.scrollHeight;
  }
  pendingRenders.clear();
  if (S.stick) scrollToBottom(false);
});
function renderMessageSoon(msg) {
  pendingRenders.add(msg);
  flushRenders();
}

function renderTopbar() {
  const p = activeProvider(S.settings);
  const warn = needsKey();
  el.modelChip.classList.toggle("warn", warn);
  replace(el.modelChip, h("img.seal", { src: "assets/logo.svg", alt: "" }), h("span.nm", ASSISTANT), warn ? h("span.tag", "未配置") : null, icon("chevdown", "sm"));
  el.modelChip.title = `${ASSISTANT} · ${modelLabel(p)}${warn ? " · 尚未配置 API Key" : ""}`;
  el.modelChip.setAttribute("aria-label", `${ASSISTANT} 的模型设置`);
  el.title.textContent = S.conv?.title || "";
  document.title = S.conv?.title ? `${S.conv.title} · ${AGENT}` : `${AGENT} · 中医古籍研究智能体`;
}

function renderSidebar() {
  S.list.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.updated - a.updated);
  const q = S.ui.search.trim().toLowerCase();
  const list = S.list.filter((c) => !q || c.title.toLowerCase().includes(q) ||
    c.messages.some((m) => (m.text || answerText(m)).toLowerCase().includes(q)));
  el.convs.replaceChildren();
  if (!list.length) {
    el.convs.append(h("div.empty-convs", q ? "没有匹配的对话" : "还没有对话。问一个问题开始吧。"));
    return;
  }
  let group = null;
  for (const c of list) {
    const g = c.pinned ? "置顶" : dateGroup(c.updated);
    if (g !== group) { group = g; el.convs.append(h("div.group-label", g)); }
    el.convs.append(convItem(c));
  }
}

function convItem(c) {
  const active = S.conv?.id === c.id;
  const running = S.running?.convId === c.id;
  const item = h("div.conv", { class: active ? "active" : "", role: "button", tabindex: 0, "aria-current": active ? "page" : null },
    c.pinned ? icon("pin", "sm pin") : null,
    h("span.t", c.title),
    running ? h("span.spinner") : null);
  const more = h("button.more", { type: "button", "aria-label": "更多操作", "aria-haspopup": "menu" }, icon("dots", "sm"));
  more.addEventListener("click", (e) => { e.stopPropagation(); convMenu(c, more, item); });
  item.append(more);
  item.addEventListener("click", () => openConversation(c.id));
  item.addEventListener("keydown", (e) => { if (e.key === "Enter") openConversation(c.id); });
  return item;
}

let openMenu = null;
function closeMenu() { openMenu?.remove(); openMenu = null; }
function convMenu(c, anchor, item) {
  closeMenu();
  const r = anchor.getBoundingClientRect();
  const menu = h("div.menu", { role: "menu", style: { top: `${Math.min(r.bottom + 4, innerHeight - 200)}px`, left: `${Math.min(r.left, innerWidth - 190)}px` } },
    h("button", { type: "button", role: "menuitem", on: { click: () => { closeMenu(); rename(c, item); } } }, icon("edit", "sm"), "重命名"),
    h("button", { type: "button", role: "menuitem", on: { click: async () => { closeMenu(); c.pinned = !c.pinned; await persistNow(c); S.list.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.updated - a.updated); renderSidebar(); } } }, icon("pin", "sm"), c.pinned ? "取消置顶" : "置顶"),
    h("button", { type: "button", role: "menuitem", on: { click: () => { closeMenu(); exportMarkdown(c); } } }, icon("download", "sm"), "导出 Markdown"),
    h("hr"),
    h("button.danger", { type: "button", role: "menuitem", on: { click: () => { closeMenu(); deleteConversation(c); } } }, icon("trash", "sm"), "删除"));
  document.body.append(menu);
  openMenu = menu;
  menu.querySelector("button")?.focus();
}

function rename(c, item) {
  const input = h("input", { value: c.title, "aria-label": "对话标题" });
  const t = item.querySelector(".t");
  t.replaceWith(input);
  input.focus();
  input.select();
  const done = async (save) => {
    if (save && input.value.trim()) { c.title = input.value.trim(); await persistNow(c); }
    renderSidebar();
    renderTopbar();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); e.stopPropagation(); });
  input.addEventListener("blur", () => done(true));
  input.addEventListener("click", (e) => e.stopPropagation());
}

function renderPill() {
  const st = S.runtimeState || {};
  const info = S.runtimeInfo;
  const kind = S.runtime?.label || "运行环境";
  const dot = st.status === "ready" ? "ok" : st.status === "error" ? "bad" : "busy";
  const ready = st.status === "ready" && info;
  const ix = st.index;
  const indexing = ready && ix && !ix.done && !ix.error && ix.total
    ? ` · 其余要籍检索索引 ${Math.floor(100 * (ix.indexed || 0) / ix.total)}%` : "";
  const detail = ready ? describeRuntime(info, " · ") + indexing
    : st.status === "error" ? truncate(st.message || "出错", 40) : (st.message || "准备中…");
  el.pill.replaceChildren(h("span.dot", { class: dot }),
    h("span.rt", h("b", `${kind}${st.status === "ready" ? "" : st.status === "error" ? " · 未就绪" : " · 载入中"}`), h("span", detail),
      ready && info.corpus?.demo ? h("span.cta", "接入全部古籍 →") : null,
      st.status === "loading" ? h("div.progress", h("i", { style: { width: `${Math.max(4, st.progress || 0)}%` } })) : null));
  el.pill.title = st.status === "error" ? st.message : ready && info.corpus?.demo ? "接入全部古籍：连接 taochronos serve（全量语料）" : "运行环境设置";
}

function renderComposer() {
  const running = Boolean(S.running);
  el.send.classList.toggle("stop", running);
  el.send.replaceChildren(running ? h("span.sq") : icon("up"));
  el.send.title = running ? "停止 (Esc)" : "发送 (Enter)";
  el.send.setAttribute("aria-label", running ? "停止生成" : "发送");
  el.send.disabled = !running && !el.input.value.trim() && !S.ui.attachments.length;
  const p = activeProvider(S.settings);
  el.attach.hidden = !p.vision;
  renderComposerHint();
}

function renderComposerHint() {
  const p = activeProvider(S.settings);
  const info = S.runtimeInfo;
  el.hint.textContent = `${ASSISTANT} · ${S.runtime?.label || "运行环境"}${info ? ` · ${corpusLabel(info.corpus)}` : ""}`;
  el.hint.title = modelLabel(p);
}

function renderAttachments() {
  el.attachments.hidden = !S.ui.attachments.length;
  el.attachments.replaceChildren(...S.ui.attachments.map((src, k) => h("div.attachment", h("img", { src, alt: "附图" }),
    h("button", { type: "button", "aria-label": "移除图片", on: { click: () => { S.ui.attachments.splice(k, 1); renderAttachments(); renderComposer(); } } }, "×"))));
}

// ------------------------------------------------------------------ scrolling
function nearBottom() {
  return el.thread.scrollHeight - el.thread.scrollTop - el.thread.clientHeight < 140;
}
function scrollToBottom(smooth) {
  el.thread.scrollTo({ top: el.thread.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}
el.thread.addEventListener("scroll", () => {
  S.stick = nearBottom();
  el.toBottom.classList.toggle("show", !S.stick && Boolean(S.conv?.messages.length));
  el.main.classList.toggle("scrolled", el.thread.scrollTop > 4);
}, { passive: true });

// ------------------------------------------------------------------ composer
function autosize() {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, innerHeight * 0.38)}px`;
  el.send.disabled = !S.running && !el.input.value.trim() && !S.ui.attachments.length;
}

async function addImages(files) {
  const p = activeProvider(S.settings);
  if (!p.vision) { toast("当前模型不支持图片输入"); return; }
  for (const f of [...files].filter((x) => x.type.startsWith("image/")).slice(0, 4)) {
    try { S.ui.attachments.push(await shrink(f)); } catch { toast(`无法读取图片 ${f.name}`, "err"); }
  }
  renderAttachments();
  renderComposer();
}

function shrink(file, max = 1600) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale);
      c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.88));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("bad image")); };
    img.src = url;
  });
}

el.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  if (S.running) { stop(); return; }
  send(el.input.value, [...S.ui.attachments]);
});
el.input.addEventListener("input", autosize);
el.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    if (!S.running) send(el.input.value, [...S.ui.attachments]);
  }
  if (e.key === "Escape" && S.running) stop();
});
el.input.addEventListener("paste", (e) => {
  const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
  if (files.length) { e.preventDefault(); addImages(files); }
});
el.attach.addEventListener("click", () => el.file.click());
el.file.addEventListener("change", () => { addImages(el.file.files || []); el.file.value = ""; });
for (const ev of ["dragenter", "dragover"]) el.composer.addEventListener(ev, (e) => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); el.composer.classList.add("drag"); } });
for (const ev of ["dragleave", "drop"]) el.composer.addEventListener(ev, () => el.composer.classList.remove("drag"));
el.composer.addEventListener("drop", (e) => { if (e.dataTransfer?.files?.length) { e.preventDefault(); addImages(e.dataTransfer.files); } });

// ------------------------------------------------------------------ 道乃久默认服务 and conversation records
/** site.json (written by the build) names the site's relay; its health says whether it is up and collects records. */
async function loadRelay() {
  let url = "";
  try {
    const r = await fetch("site.json", { cache: "no-cache" });
    if (r.ok) url = String((await r.json())?.relay || "").trim().replace(/\/+$/, "");
  } catch { /* no site.json: a local server's page, or a site built without a relay */ }
  if (!/^https?:\/\//.test(url)) return;
  S.relay = { url, ok: false, logs: false, pending: true };
  setRelay(S.relay);
  recheckRelay([10000, 15000]);
}

const RELAY_RETRIES = 4; // after the first check fails: tried again 20, 40, 60 and 80 seconds later

/** Check the relay again (its health, with the timeouts given, one after another until one answers).  A page that is
 * loading its runtime shares a slow link with this request, so it is patient, and a relay that did not answer is tried
 * again a few times: until it answers, a visitor without a key of their own is asked for one. */
function recheckRelay(timeouts, retry = 0) {
  S.relay.pending = true;
  S.relayReady = checkRelay(timeouts).finally(() => {
    renderTopbar(); renderMain(); renderComposer();
    if (!S.relay.ok && retry < RELAY_RETRIES) {
      clearTimeout(S.relayRetry);
      S.relayRetry = setTimeout(() => { if (!S.relay.ok && !S.relay.pending) recheckRelay([15000], retry + 1); }, 20000 * (retry + 1));
    }
  });
  return S.relayReady;
}

async function checkRelay(timeouts) {
  const url = S.relay.url;
  let j = null;
  for (let i = 0; i < timeouts.length && !j?.ok; i++) {
    if (i) await new Promise((r) => setTimeout(r, 1500));
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeouts[i]);
    try {
      const r = await fetch(`${url}/v1/health`, { cache: "no-store", signal: ctl.signal });
      j = r.ok ? await r.json() : null;
    } catch { j = null; /* down, not deployed yet, or the link too slow this time */ }
    clearTimeout(timer);
  }
  if (j?.ok) {
    Object.assign(S.relay, { ok: true, model: j.model, models: j.models, logs: Boolean(j.logs), limits: j.limits,
      maxOutput: Number(j.max_output_tokens) || null });
  }
  delete S.relay.pending;
  setRelay(S.relay);
  // a visitor without a model of their own asks through it; one who chose it falls back while it is down
  if (S.relay.ok && needsKey()) S.settings.provider = RELAY_ID;
  else if (!S.relay.ok && S.settings.provider === RELAY_ID) S.settings.provider = allProviders(S.settings).find((p) => !p.relay)?.id;
}

function askConsent() {
  return new Promise((resolve) => {
    const dlg = el.consent ||= document.body.appendChild(h("dialog#consent", { "aria-label": "对话记录说明" })); // an index.html cached from before
    const done = (agreed) => {
      setConsent(agreed);
      dlg.close();
      toast(agreed ? "已同意记录。可随时在“设置 → 数据”里更改" : "不记录。可随时在“设置 → 数据”里更改");
      resolve(agreed);
    };
    dlg.oncancel = (e) => { e.preventDefault(); done(false); };
    dlg.replaceChildren(h("div.modal.consent", { role: "document" },
      h("div.modal-head", h("h2", "对话记录说明")),
      h("div.consent-body", ...NOTICE.map((t) => h("p", t)),
        h("p.muted", "你的选择只保存在本浏览器，可随时在“设置 → 数据”里更改；不记录也可以照常使用。")),
      h("div.modal-foot",
        h("button.btn.secondary", { type: "button", on: { click: () => done(false) } }, "不记录"),
        h("button.btn", { type: "button", on: { click: () => done(true) } }, "同意并继续"))));
    dlg.showModal();
  });
}

const recording = () => Boolean(S.relay?.ok && S.relay.logs && consent() === true);

/** How the answer's citations were checked: waits for the checks under way (15 s at most). */
async function citationSummary(conv, msg) {
  const cites = extractCitations(answerText(msg));
  const out = { total: cites.length, ok: 0, warn: 0, bad: 0, pending: 0, pids: [...new Set(cites.map((c) => c.pid))].slice(0, 60) };
  const deadline = Date.now() + 15000;
  for (const c of cites) {
    let v = S.verify.get(`${conv.id}|${c.pid}|${c.quote || ""}`);
    if (v && typeof v.then === "function") v = await Promise.race([v, sleep(Math.max(0, deadline - Date.now())).then(() => null)]);
    out[["ok", "warn", "bad"].includes(v?.status) ? v.status : "pending"]++;
  }
  return out;
}

/** One finished turn, compact (no key, no settings, no address), to the relay — only when the visitor agreed. */
async function recordTurn(conv, msg) {
  if (!recording()) return;
  try {
    const idx = conv.messages.indexOf(msg);
    const user = conv.messages[idx - 1];
    if (!user || user.role !== "user") return;
    const tools = [];
    for (const seg of msg.segments || []) {
      for (const c of seg.calls || []) {
        tools.push({ name: c.resolved || c.name, ok: c.status === "ok", ms: c.ms, args: truncate(JSON.stringify(c.args ?? {}), 300) });
      }
    }
    const record = {
      v: 1, id: msg.id, conversation: conv.id, turn: conv.messages.slice(0, idx).filter((m) => m.role === "user").length,
      started: new Date(msg.created).toISOString(), finished: new Date().toISOString(), ms: msg.ms, rounds: msg.rounds,
      question: (user.text || "").slice(0, 4000), images: user.images?.length || undefined, answer: answerText(msg).slice(0, 12000),
      status: msg.status, error: msg.error ? String(msg.error).slice(0, 500) : undefined,
      model: msg.model, provider: msg.provider, runtime: S.runtimeInfo?.runtime || S.runtime?.kind, corpus: S.runtimeInfo?.corpus?.kind,
      app: S.runtimeInfo?.version, usage: msg.usage || undefined, tools: tools.slice(0, 40), citations: await citationSummary(conv, msg),
    };
    let body = JSON.stringify(record);
    const size = () => new TextEncoder().encode(body).length;
    while (size() > 60000 && record.answer.length > 400) { // within the relay's limit: the answer is shortened
      record.answer = record.answer.slice(0, Math.floor(record.answer.length * 0.7));
      body = JSON.stringify(record);
    }
    // text/plain: a simple request, no preflight (the relay reads the body as JSON whatever its type)
    await fetch(`${S.relay.url}/v1/logs`, { method: "POST", headers: { "Content-Type": "text/plain;charset=UTF-8" }, body, keepalive: true });
  } catch { /* a record that did not arrive is not the visitor's concern */ }
}

// ------------------------------------------------------------------ settings
const settingsCtx = {
  save(draft) {
    const before = S.settings;
    S.settings = draft;
    saveSettings(draft);
    applyTheme();
    if (before.runtime !== draft.runtime || before.serverUrl !== draft.serverUrl || before.serverToken !== draft.serverToken) switchRuntime();
    if (before.verifyQuotes !== draft.verifyQuotes) S.verify.clear();
    renderAll();
    toast("设置已保存");
  },
  async testModel(draft) {
    const p = activeProvider(draft);
    if (!p.apiKey && !p.key_optional && !(draft.route === "proxy" && S.runtimeInfo?.env_keys)) return { ok: false, message: "请先填写 API Key" };
    const started = Date.now();
    const settings = { ...draft, maxTokens: 400, thinking: false };
    const route = routeFor(draft);
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 45000);
    try {
      const messages = [{ role: "user", content: "请只回复两个字：可以" }];
      const res = p.format === "anthropic"
        ? await streamClaude({ provider: p, system: "你是一个连接测试。", messages, tools: [], settings, route, signal: ctl.signal })
        : await streamChat({ provider: p, messages: [{ role: "system", content: "你是一个连接测试。" }, ...messages], tools: [], settings, route, signal: ctl.signal });
      return { ok: true, message: `连接成功 · ${p.relay ? p.label : res.model || p.model} · ${fmtMs(Date.now() - started)} · 回复「${truncate(res.text || res.thinking || "（空）", 40)}」` };
    } catch (err) {
      return { ok: false, message: err.name === "AbortError" ? "请求超时" : err.message };
    } finally {
      clearTimeout(timer);
    }
  },
  /** Connect to a TaoChronos server and use it now; this browser remembers it (auto mode tries it first). */
  async connectServer(draft) {
    const rt = new ServerRuntime((draft.serverUrl || "").trim() || "http://localhost:8765", (draft.serverToken || "").trim());
    try {
      const info = await rt.start();
      draft.serverUrl = rt.url;
      draft.serverToken = rt.token;
      // a page served by another server would keep choosing that one in auto mode: name this one
      if (draft.runtime !== "server") draft.runtime = S.here && S.here.replace(/\/+$/, "") !== rt.url ? "server" : "auto";
      S.settings = { ...S.settings, serverUrl: rt.url, serverToken: rt.token, runtime: draft.runtime };
      saveSettings(S.settings);
      storage.set(KNOWN_SERVER, rt.url);
      await switchRuntime(rt);
      S.runtimeInfo = info;
      renderAll();
      return { ok: true, message: `已接入${rt.label} ${rt.url.replace(/^https?:\/\//, "")}：${describeRuntime(info)}${info.env_keys ? " · 可使用服务端环境变量中的模型密钥" : ""}` };
    } catch (err) {
      return { ok: false, message: err.message, tokenRequired: Boolean(err.tokenRequired) };
    }
  },
  describeRuntime,
  consent,
  setConsent(agreed) { setConsent(agreed); toast(agreed ? "已同意记录" : "已停止记录"); },
  exportAll() {
    download(`TaoChronos-对话-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify({ app: "TaoChronos", version: 1, exported: new Date().toISOString(), conversations: S.list }, null, 1), "application/json");
  },
  async importAll(text) {
    try {
      const data = JSON.parse(text);
      const list = Array.isArray(data) ? data : data.conversations;
      if (!Array.isArray(list)) throw new Error("文件里没有对话列表");
      let n = 0;
      for (const c of list) {
        if (!c?.id || !Array.isArray(c.messages)) continue;
        c.evidence ||= {};
        c.research ||= [];
        await store.putConversation(c);
        S.list = S.list.filter((x) => x.id !== c.id);
        S.list.push(c);
        n++;
      }
      S.list.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.updated - a.updated);
      renderSidebar();
      toast(`已导入 ${n} 个对话`);
    } catch (err) {
      toast(`导入失败：${err.message}`, "err");
    }
  },
  exportMarkdown,
  async clearAll() {
    if (!confirm("删除本浏览器中的全部对话？此操作不可撤销。")) return;
    stop();
    await store.clearConversations();
    S.list = [];
    el.settings.close();
    newChat();
    toast("已删除全部对话");
  },
  toast,
};

function exportMarkdown(conv) {
  const lines = [`# ${conv.title}`, "", `> 导出自${AGENT}（${ASSISTANT}）· ${PUBLISHER}（${PUBLISHER_EN}）· ${new Date(conv.updated).toLocaleString("zh-CN")}`, ""];
  for (const m of conv.messages) {
    if (m.role === "user") lines.push("## 问", "", m.text, "");
    else {
      const tools = (m.segments || []).flatMap((s) => s.calls || []).map((c) => `\`${c.name}\``);
      lines.push(`## ${AGENT}`, "");
      const about = [m.provider === RELAY_ID ? "道乃久默认服务" : m.model ? `底层模型 ${m.model}` : null,
        tools.length ? `工具 ${[...new Set(tools)].join("、")}` : null].filter(Boolean);
      if (about.length) lines.push(`*${about.join("；")}*`, "");
      lines.push(answerText(m) || "（无回答）", "");
    }
  }
  const cited = new Set(conv.messages.flatMap((m) => extractCitations(answerText(m)).map((c) => c.pid)));
  if (cited.size) {
    lines.push("## 引用的段落", "");
    for (const pid of cited) {
      const c = conv.evidence?.[pid] || passageNow(pid);
      lines.push(`- **[[${pid}]]** ${c?.title ? `《${c.title}》` : ""}${String(c?.locator || "").replace(/^《[^》]*》/, "")}${yearLabel(c) ? `（${yearLabel(c)}）` : ""}${c?.text ? `：${c.text}` : ""}`);
    }
    lines.push("");
  }
  download(`${conv.title.replace(/[\\/:*?"<>|]+/g, "_")}.md`, lines.join("\n"), "text/markdown");
}

// ------------------------------------------------------------------ theme and chrome
function applyTheme() {
  const t = S.settings.theme || "system";
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const next = { system: ["monitor", "跟随系统"], light: ["sun", "浅色"], dark: ["moon", "深色"] }[t];
  el.theme.replaceChildren(icon(next[0], "sm"), next[1]);
}

function closeSidebarOnMobile() {
  if (mobile()) el.app.classList.remove("sidebar-open");
}

function toggleSidebar() {
  if (mobile()) { el.app.classList.toggle("sidebar-open"); return; }
  document.documentElement.classList.remove("pre-collapsed");
  const collapsed = el.app.classList.toggle("sidebar-collapsed");
  storage.set("tc.sidebar", collapsed ? "collapsed" : "open");
}

function toggleDrawer(tab) {
  if (tab) { S.drawer.open = true; S.drawer.tab = tab; } else S.drawer.open = !S.drawer.open;
  renderLayout();
  if (S.drawer.open) renderDrawer(el.drawer, S, drawerCtx);
}

function wireChrome() {
  el.newChat.querySelector("#new-chat-icon").replaceWith(icon("plus"));
  $("#search-icon").replaceWith(icon("search", "sm"));
  el.collapse.append(icon("sidebar"));
  el.toggleSidebar.append(icon("menu"));
  el.toggleDrawer.append(icon("panel"));
  el.newChatTop.append(icon("plus"));
  el.toBottom.append(icon("down"));
  el.attach.append(icon("image"));
  el.settingsBtn.append(icon("gear", "sm"), "设置");

  el.newChat.addEventListener("click", newChat);
  el.newChatTop.addEventListener("click", newChat);
  el.collapse.addEventListener("click", toggleSidebar);
  el.toggleSidebar.addEventListener("click", toggleSidebar);
  el.toggleDrawer.addEventListener("click", () => toggleDrawer());
  el.scrim.addEventListener("click", () => { el.app.classList.remove("sidebar-open"); S.drawer.open = false; renderLayout(); });
  el.modelChip.addEventListener("click", () => openSettings(S, settingsCtx, "model"));
  el.settingsBtn.addEventListener("click", () => openSettings(S, settingsCtx, "model"));
  el.pill.addEventListener("click", () => openSettings(S, settingsCtx, "runtime"));
  el.theme.addEventListener("click", () => {
    const order = ["system", "light", "dark"];
    S.settings.theme = order[(order.indexOf(S.settings.theme || "system") + 1) % order.length];
    saveSettings(S.settings);
    applyTheme();
  });
  el.toBottom.addEventListener("click", () => scrollToBottom(true));
  el.search.addEventListener("input", debounce(() => { S.ui.search = el.search.value; renderSidebar(); }, 120));

  // code blocks' copy buttons, anywhere in the thread or a report
  document.addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-copy='code']");
    if (btn) copyText(btn.parentElement.querySelector("code")?.textContent || "").then((ok) => toast(ok ? "已复制代码" : "复制失败"));
    if (openMenu && !openMenu.contains(e.target)) closeMenu();
  });
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); newChat(); }
    else if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); toggleSidebar(); }
    else if (mod && e.key.toLowerCase() === "j") { e.preventDefault(); toggleDrawer(); }
    else if (e.key === "Escape") {
      if (openMenu) closeMenu();
      else if (S.running && document.activeElement === el.input) stop();
      else if (mobile() && (el.app.classList.contains("sidebar-open") || S.drawer.open)) { el.app.classList.remove("sidebar-open"); S.drawer.open = false; renderLayout(); }
    } else if (e.key === "/" && !mod && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "") && !document.querySelector("dialog[open]")) {
      e.preventDefault();
      el.input.focus();
    }
  });
  addEventListener("hashchange", () => {
    const m = /^#\/c\/(.+)$/.exec(location.hash);
    if (m && m[1] !== S.conv?.id) openConversation(m[1]);
  });
  addEventListener("beforeunload", (e) => { if (S.running) { e.preventDefault(); e.returnValue = ""; } });
}

// ------------------------------------------------------------------ start
/** A server started beyond this machine prints its address with the access token: #token=… (taken once, then removed). */
function takeToken() {
  const m = /^#(?:.*&)?token=([^&]+)/.exec(location.hash);
  if (!m) return;
  S.settings.serverToken = decodeURIComponent(m[1]);
  saveSettings(S.settings);
  history.replaceState(null, "", location.pathname + location.search);
}

async function main() {
  takeToken();
  switchRuntime(); // at once: Python and the corpus load in the worker while the page sets itself up
  if (document.documentElement.classList.contains("pre-collapsed")) el.app.classList.add("sidebar-collapsed");
  applyTheme();
  wireChrome();
  await loadProviders();
  await loadRelay(); // site.json only; the relay's health is checked meanwhile
  if (!allProviders(S.settings).some((p) => p.id === S.settings.provider)) {
    S.settings.provider = allProviders(S.settings).find((p) => !p.relay)?.id || allProviders(S.settings)[0].id;
  }
  S.list = await store.listConversations().catch(() => []);
  const m = /^#\/c\/(.+)$/.exec(location.hash);
  S.conv = m ? S.list.find((c) => c.id === m[1]) || null : null;
  renderAll();
  scrollToBottom(false);
  if (!(await store.persistent())) toast("此浏览器无法保存对话（隐私模式？）：关闭页面后对话将丢失", "", 5000);
  el.input.focus();
}

main().catch((err) => {
  console.error(err);
  toast(`启动失败：${err.message}`, "err", 8000);
});
