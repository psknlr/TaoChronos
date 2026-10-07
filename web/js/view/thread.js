// The conversation: user turns, assistant turns (thinking, tool steps, the answer), citation chips and actions.

import { renderMarkdown } from "../markdown.js";
import { redact, toolWord } from "../redact.js";
import { AGENT, AGENT_EN, MODEL as ASSISTANT, PUBLISHED_BY } from "../brand.js";
import { RELAY_ID } from "../providers.js";
import { fmtMs, h, icon, passageLabel, prettyJSON, progressBar, replace, truncate } from "../util.js";

export const FAMILY = {
  retrieval: "检索", study: "治学", knowledge: "知识", analytics: "发现", philology: "文献", validation: "核验",
  bridge: "古今", literature: "现代", engine: "研究", meta: "目录", research: "代码",
};

export function toolFamily(name, catalogIndex) {
  const entry = catalogIndex?.get(name) || catalogIndex?.get(name.replace(/__/g, "."));
  if (entry) return entry.family;
  if (name.startsWith("taochronos_")) return name === "taochronos_catalog" || name === "taochronos_call" ? "meta" : "engine";
  const prefix = name.split(/__|\./)[0];
  return { classics: "retrieval", kg: "knowledge", analysis: "analytics", study: "study", philology: "philology", vision: "philology",
    validation: "validation", audit: "validation", graph: "validation", bridge: "bridge", modern: "literature", literature: "literature",
    rwd: "literature", research: "research" }[prefix] || "meta";
}

/** A tool as the page names it: in plain words, never by its inside name (redact.js). */
export const displayName = (name) => toolWord(name);

/** The whole thread, or the hero when the conversation is empty. */
export function renderThread(root, conv, ctx) {
  const settled = Boolean(root.querySelector(":scope > .hero"));
  root.replaceChildren();
  if (!conv || !conv.messages.length) {
    const node = hero(ctx);
    if (settled) node.classList.add("settled");
    root.append(node);
    return;
  }
  conv.messages.forEach((m, k) => root.append(messageNode(m, ctx, k === conv.messages.length - 1)));
}

function hero(ctx) {
  const info = ctx.runtimeInfo;
  const st = ctx.runtimeState || {};
  const failed = st.status === "error";
  // while the runtime loads, 加载中 and one bar for the whole load; once it answers, nothing (what runs, on which corpus,
  // is in the settings' 运行环境); what went wrong, when something did, with the way to the settings
  const status = st.status === "ready" && info ? null : failed
    ? h("div.status", h("span.dot.bad"), `运行环境未就绪：${truncate(st.message || "", 60)}`)
    : h("div.status.loading", h("span.dot.busy"), "加载中", progressBar(st.bar));
  const action = failed
    ? h("button.hero-action", { type: "button", on: { click: ctx.onOpenRuntime } }, icon("server", "sm"), h("span", h("b", "设置运行环境")), icon("chev", "sm"))
    : null;
  return h("div.hero",
    h("img.seal", { src: "assets/logo.svg", alt: "" }),
    h("h1", AGENT),
    h("div.model-badge", h("b", ASSISTANT), h("span", `${AGENT_EN} · 中医古籍研究智能体`)),
    h("p.sub", "问古籍，得原文——每一条引文都可溯源、可逐字核对"),
    status,
    action,
    h("div.starters", (info?.starters || DEFAULT_STARTERS).map((s) =>
      h("button.starter", { type: "button", on: { click: () => ctx.onStarter(s.prompt) } }, h("b", s.title), s.prompt))),
    ctx.needsKey
      ? h("p.keyhint", "开始前请先为 ", ASSISTANT, " ", h("button", { type: "button", on: { click: ctx.onOpenSettings } }, "配置底层模型的 API"),
        "。也可以不配置模型，直接在右侧“工具台”使用全部功能。")
      : ctx.relayActive
        ? h("p.keyhint", "已接入道乃久默认服务：无需设置，直接提问 · Enter 发送 · Shift+Enter 换行")
        : h("p.keyhint", "Enter 发送 · Shift+Enter 换行 · ", h("kbd", "Ctrl"), " ", h("kbd", "K"), " 新对话"),
    h("p.publisher", PUBLISHED_BY),
  );
}

const DEFAULT_STARTERS = [
  { title: "方源考", prompt: "桂枝汤的原方组成与剂量出自哪里？后世有哪些重要的加减化裁？" },
  { title: "术语源流", prompt: "「消渴」一词在历代文献中的含义与用法如何演变？请给出各时期的原文证据。" },
  { title: "集注比较", prompt: "比较历代注家对「太阳之为病，脉浮，头项强痛而恶寒」的解释，有哪些分歧？" },
];

export function messageNode(m, ctx, last = false) {
  return m.role === "user" ? userNode(m, ctx, last) : assistantNode(m, ctx, last);
}

function userNode(m, ctx, last) {
  const el = h("div.msg.user", { dataset: { id: m.id }, class: last ? "last" : "" });
  if (ctx.editing === m.id) {
    const ta = h("textarea", { "aria-label": "编辑消息" }, m.text);
    el.append(h("div.edit-box", ta, h("div.row",
      h("button.btn.secondary", { type: "button", on: { click: () => ctx.onEditCancel() } }, "取消"),
      h("button.btn", { type: "button", on: { click: () => ctx.onEditSubmit(m.id, ta.value) } }, "发送"))));
    requestAnimationFrame(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); });
    return el;
  }
  if (m.images?.length) el.append(h("div.imgs", m.images.map((src) => h("img", { src, alt: "附图" }))));
  el.append(h("div.bubble", m.text));
  el.append(h("div.actions",
    h("button.icon-btn", { type: "button", title: "复制", "aria-label": "复制", on: { click: () => ctx.onCopy(m.text) } }, icon("copy", "sm")),
    ctx.running ? null : h("button.icon-btn", { type: "button", title: "编辑后重新发送", "aria-label": "编辑", on: { click: () => ctx.onEdit(m.id) } }, icon("edit", "sm"))));
  return el;
}

function assistantNode(m, ctx, last) {
  const el = h("div.msg.assistant", { dataset: { id: m.id }, class: last ? "last" : "" });
  const body = h("div.body");
  el.append(h("img.avatar", { src: "assets/logo.svg", alt: AGENT }), body);
  fillAssistant(body, m, ctx, last);
  return el;
}

/** (Re)draw an assistant turn's body — called on every streamed update of the turn. */
export function fillAssistant(body, m, ctx, last) {
  body.replaceChildren();
  const live = m.status === "streaming";
  const segs = m.segments || [];
  segs.forEach((seg, k) => {
    const isLast = k === segs.length - 1;
    if (seg.type === "thinking") { if (!m.hideThinking) body.append(thinkingNode(m, seg, k, ctx, live && isLast)); }
    else if (seg.type === "tools") body.append(stepsNode(m, seg, k, ctx, live));
    else if (seg.type === "text" && (seg.text || (live && isLast))) {
      const md = h("div.md");
      md.append(renderMarkdown(redact(seg.text, { streaming: live && isLast }), { streaming: live && isLast, cite: ctx.cite }));
      body.append(md);
    }
  });
  if (live && !segs.length) body.append(h("div.think.live", h("summary", h("span.lbl", "正在思考…"))));
  if (m.error) {
    body.append(h("div.notice.err", icon("warn"), h("div.grow", redact(m.error)),
      ctx.running ? null : h("button.btn.secondary", { type: "button", on: { click: () => ctx.onRegenerate(m.id) } }, "重试")));
  }
  if (m.status === "stopped") body.append(h("div.notice.warn", icon("info"), h("div.grow", "已停止生成。")));
  if (!live) {
    const bar = verifyBar(m, ctx, renderedCites(body));
    if (bar) body.append(bar);
    const meta = [ASSISTANT, m.rounds > 1 ? `${m.rounds} 轮` : null, m.toolCount ? `${m.toolCount} 次工具调用` : null,
      m.ms ? fmtMs(m.ms) : null, m.usage?.output ? `${m.usage.input || 0}→${m.usage.output} tokens` : null].filter(Boolean).join(" · ");
    body.append(h("div.actions",
      h("button.icon-btn", { type: "button", title: "复制回答", "aria-label": "复制回答", on: { click: () => ctx.onCopy(answerText(m)) } }, icon("copy", "sm")),
      last && !ctx.running ? h("button.icon-btn", { type: "button", title: "重新生成", "aria-label": "重新生成", on: { click: () => ctx.onRegenerate(m.id) } }, icon("redo", "sm")) : null,
      h("span.meta", { title: m.provider === RELAY_ID ? "道乃久默认服务" : m.model ? `底层模型 ${m.model}` : null }, meta)));
  }
}

/** The answer as the model wrote it — for the model only; what anyone reads of it is answerText. */
export function rawAnswer(m) {
  return (m.segments || []).filter((s) => s.type === "text").map((s) => s.text).join("\n\n").trim();
}

/** The answer as a visitor reads it, copies it and the record keeps it: in plain words (redact.js). */
export function answerText(m) {
  return redact(rawAnswer(m));
}

function thinkingNode(m, seg, k, ctx, live) {
  const key = `${m.id}:${k}`;
  const d = h("details.think", { class: live ? "live" : "" });
  if (ctx.openThink.has(key)) d.open = true;
  d.addEventListener("toggle", () => { if (d.open) ctx.openThink.add(key); else ctx.openThink.delete(key); });
  const secs = seg.ms ? ` · ${fmtMs(seg.ms)}` : "";
  d.append(h("summary", icon("chev", "sm chev"), h("span.lbl", live ? "思考中…" : "思考过程"), h("span", secs)),
    h("div.tx", redact(seg.text, { streaming: live }) || "…"));
  return d;
}

function stepsNode(m, seg, k, ctx, live) {
  const key = `${m.id}:${k}`;
  const calls = seg.calls || [];
  const running = calls.some((c) => c.status === "running" || c.status === "preparing");
  const open = ctx.openSteps.has(key) || (live && running && !ctx.closedSteps.has(key));
  const box = h("div.steps", { class: open ? "open" : "" });
  const fams = [...new Set(calls.map((c) => c.family))].map((f) => h("span.fam", { class: f }, FAMILY[f] || f));
  const errs = calls.filter((c) => c.status === "error").length;
  const label = running ? `正在调用工具（${calls.filter((c) => c.status === "ok" || c.status === "error").length}/${calls.length}）`
    : `调用了 ${calls.length} 个工具${errs ? `，${errs} 个出错` : ""}`;
  const head = h("button.head", { type: "button", "aria-expanded": String(open) },
    running ? h("span.spinner") : icon("tools", "sm"), h("span", label), ...fams, icon("chev", "sm chev"));
  head.addEventListener("click", () => {
    const now = !box.classList.contains("open");
    box.classList.toggle("open", now);
    head.setAttribute("aria-expanded", String(now));
    if (now) { ctx.openSteps.add(key); ctx.closedSteps.delete(key); } else { ctx.openSteps.delete(key); ctx.closedSteps.add(key); }
  });
  const list = h("div.list");
  calls.forEach((c, j) => list.append(toolNode(m, c, `${key}:${j}`, ctx)));
  box.append(head, list);
  return box;
}

function toolNode(m, c, key, ctx) {
  const open = ctx.openTools.has(key);
  const t = h("div.tool", { class: open ? "open" : "" });
  const status = c.status === "running" || c.status === "preparing" ? h("span.st", h("span.spinner"))
    : c.status === "error" ? h("span.st.err", icon("x", "sm")) : h("span.st.ok", icon("check", "sm"));
  const summary = c.status === "preparing" ? "准备参数…" : c.status === "running" ? (c.progress || "运行中…") : (c.summary || "");
  const row = h("button.row", { type: "button" },
    status, h("span.fam", { class: c.family }, FAMILY[c.family] || c.family), h("span.nm", displayName(c.name)),
    h("span.sm", redact(summary)), h("span.ms", c.ms ? fmtMs(c.ms) : ""));
  row.addEventListener("click", () => {
    const now = !t.classList.contains("open");
    t.classList.toggle("open", now);
    if (now) ctx.openTools.add(key); else ctx.openTools.delete(key);
    if (now && !t.querySelector(".detail").childElementCount) fillDetail(t.querySelector(".detail"), c, ctx);
  });
  const detail = h("div.detail");
  if (open) fillDetail(detail, c, ctx);
  t.append(row, detail);
  return t;
}

function fillDetail(el, c, ctx) {
  replace(el,
    h("h5", "参数"), h("pre.json", prettyJSON(c.args ?? {})),
    c.error ? [h("h5", "错误"), h("pre.json", c.error)] : null,
    c.preview ? [h("h5", "结果（模型读到的内容）"), h("pre.json", readable(c.preview))] : null,
    c.citations?.length ? [h("h5", `涉及的段落（${c.citations.length}）`),
      h("div.cites-row", c.citations.slice(0, 40).map((card) => ctx.citeCard(card)))] : null,
    c.research ? h("button.btn.secondary", { type: "button", style: { marginTop: "8px" }, on: { click: () => ctx.onOpenResearch(c.research) } }, icon("flask", "sm"), "在侧栏查看研究结果") : null,
  );
}

/** The citations as rendered in a turn's answer: [{pid, quote}]. */
export function renderedCites(body) {
  return [...body.querySelectorAll(".md .cite[data-cite='text']")].map((b) => ({ pid: b.dataset.pid, quote: b.dataset.quote || null }));
}

export function verifyBar(m, ctx, ids) {
  if (!ids.length) return null;
  const counts = { ok: 0, warn: 0, bad: 0, pending: 0 };
  for (const r of ids) counts[ctx.citeStatus(r.pid, r.quote)?.status || "pending"]++;
  return h("div.verify-bar", { dataset: { verify: m.id } },
    icon("quote", "sm"), "引文核对：",
    counts.ok ? h("span.b.ok", icon("check", "sm"), `${counts.ok} 条与原文一致`) : null,
    counts.warn ? h("span.b.warn", icon("warn", "sm"), `${counts.warn} 条存疑`) : null,
    counts.bad ? h("span.b.bad", icon("x", "sm"), `${counts.bad} 条查无此段`) : null,
    counts.pending ? h("span.b", `${counts.pending} 条核对中`) : null);
}

export function citeLabel(card, pid) {
  return passageLabel(card, pid);
}

/** A tool result as the model read it, indented when it is whole JSON. */
function readable(text) {
  try {
    return prettyJSON(JSON.parse(text), 60000);
  } catch {
    return text;
  }
}
