// The conversation: user turns, assistant turns (thinking, tool steps, the answer), citation chips and actions.

import { chartGallery, documentButton } from "../chart.js";
import { renderMarkdown } from "../markdown.js";
import { redact, toolWord } from "../redact.js";
import { AGENT, AGENT_EN, MODEL as ASSISTANT, PUBLISHED_BY } from "../brand.js";
import { sizeLabel } from "../mydata.js";
import { RELAY_ID } from "../providers.js";
import { fmtMs, foundBadges, h, icon, passageLabel, prettyJSON, progressBar, replace, truncate } from "../util.js";
import { T } from "../i18n.js";

export const FAMILY = {
  retrieval: T("检索"), study: T("治学"), knowledge: T("知识"), analytics: T("发现"), philology: T("文献"), validation: T("核验"),
  bridge: T("古今"), literature: T("现代"), engine: T("研究"), meta: T("目录"), research: T("代码"), mydata: T("我的资料"),
};

export function toolFamily(name, catalogIndex) {
  const entry = catalogIndex?.get(name) || catalogIndex?.get(name.replace(/__/g, "."));
  if (entry) return entry.family;
  if (name.startsWith("taochronos_")) return name === "taochronos_catalog" || name === "taochronos_call" ? "meta" : "engine";
  const prefix = name.split(/__|\./)[0];
  return { classics: "retrieval", kg: "knowledge", analysis: "analytics", study: "study", philology: "philology", vision: "philology",
    validation: "validation", audit: "validation", graph: "validation", bridge: "bridge", modern: "literature", literature: "literature",
    rwd: "literature", research: "research", mydata: "mydata" }[prefix] || "meta";
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
    ? h("div.status", h("span.dot.bad"), T`运行环境未就绪：${truncate(st.message || "", 60)}`)
    : h("div.status.loading", h("span.dot.busy"), T("加载中"), progressBar(st.bar));
  const action = failed
    ? h("button.hero-action", { type: "button", on: { click: ctx.onOpenRuntime } }, icon("server", "sm"), h("span", h("b", T("设置运行环境"))), icon("chev", "sm"))
    : null;
  return h("div.hero",
    h("img.seal", { src: "assets/logo.svg", alt: "" }),
    h("h1", AGENT),
    h("div.model-badge", h("b", ASSISTANT), h("span", T`${AGENT_EN} · 中医古籍研究智能体`)),
    h("p.sub", T("问古籍，得原文——每一条引文都可溯源、可逐字核对")),
    status,
    action,
    h("div.starters", (info?.starters || DEFAULT_STARTERS).map((s) =>
      h("button.starter", { type: "button", on: { click: () => ctx.onStarter(T(s.prompt)) } }, h("b", T(s.title)), T(s.prompt)))),
    ctx.needsKey
      ? h("p.keyhint", T`开始前请先为 ${ASSISTANT} `, h("button", { type: "button", on: { click: ctx.onOpenSettings } }, T("配置底层模型的 API")),
        T("。也可以不配置模型，直接在右侧“工具台”使用全部功能。"))
      : ctx.relayActive
        ? h("p.keyhint", T("已接入道乃久默认服务：无需设置，直接提问 · Enter 发送 · Shift+Enter 换行"))
        : h("p.keyhint", T("Enter 发送 · Shift+Enter 换行 · "), h("kbd", "Ctrl"), " ", h("kbd", "K"), T(" 新对话")),
    h("p.publisher", PUBLISHED_BY),
  );
}

const DEFAULT_STARTERS = [
  { title: T("方源考"), prompt: T("桂枝汤的原方组成与剂量出自哪里？后世有哪些重要的加减化裁？") },
  { title: T("术语源流"), prompt: T("「消渴」一词在历代文献中的含义与用法如何演变？请给出各时期的原文证据。") },
  { title: T("集注比较"), prompt: T("比较历代注家对「太阳之为病，脉浮，头项强痛而恶寒」的解释，有哪些分歧？") },
];

export function messageNode(m, ctx, last = false) {
  return m.role === "user" ? userNode(m, ctx, last) : assistantNode(m, ctx, last);
}

function userNode(m, ctx, last) {
  const el = h("div.msg.user", { dataset: { id: m.id }, class: last ? "last" : "" });
  if (ctx.editing === m.id) {
    const ta = h("textarea", { "aria-label": T("编辑消息") }, m.text);
    el.append(h("div.edit-box", ta, h("div.row",
      h("button.btn.secondary", { type: "button", on: { click: () => ctx.onEditCancel() } }, T("取消")),
      h("button.btn", { type: "button", on: { click: () => ctx.onEditSubmit(m.id, ta.value) } }, T("发送")))));
    requestAnimationFrame(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); });
    return el;
  }
  if (m.images?.length) el.append(h("div.imgs", m.images.map((src) => h("img", { src, alt: T("附图") }))));
  if (m.data?.length) {
    el.append(h("div.data-chips", m.data.map((d) => h("div.data-chip", { title: T`${d.name} · ${sizeLabel(d)} · 已脱敏` },
      icon(d.kind === "table" ? "table" : "file", "sm"), h("span.nm", truncate(d.name, 28)), h("span.sz", sizeLabel(d))))));
  }
  el.append(h("div.bubble", m.text));
  el.append(h("div.actions",
    h("button.icon-btn", { type: "button", title: T("复制"), "aria-label": T("复制"), on: { click: () => ctx.onCopy(m.text) } }, icon("copy", "sm")),
    ctx.running ? null : h("button.icon-btn", { type: "button", title: T("编辑后重新发送"), "aria-label": T("编辑"), on: { click: () => ctx.onEdit(m.id) } }, icon("edit", "sm"))));
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
    else if (seg.type === "tools") {
      body.append(stepsNode(m, seg, k, ctx, live));
      const charts = chartsNode(seg);
      if (charts) body.append(charts);
      const docs = (seg.calls || []).map((c) => documentButton(c.document)).filter(Boolean);
      if (docs.length) body.append(h("div.docs", docs));
    }
    else if (seg.type === "check") body.append(checkNode(seg));
    else if (seg.type === "text" && seg.superseded) { if (seg.text) body.append(draftNode(m, seg, k, ctx)); }
    else if (seg.type === "text" && (seg.text || (live && isLast))) {
      const md = h("div.md");
      md.append(renderMarkdown(redact(seg.text, { streaming: live && isLast }), { streaming: live && isLast, cite: ctx.cite }));
      body.append(md);
    }
  });
  if (live && !segs.length) body.append(h("div.think.live", h("summary", h("span.lbl", T("正在思考…")))));
  // 继续作答: a turn that did not get its answer, taken up again from what its tools gave (not begun again, as 重试 is)
  const resume = () => (ctx.canResume?.(m)
    ? h("button.btn.secondary.resume", { type: "button", title: T("根据已经得到的工具结果接着作答，不再重新调用工具"),
      on: { click: () => ctx.onResume(m.id) } }, T("继续作答"))
    : null);
  if (m.error) {
    body.append(h("div.notice.err", icon("warn"), h("div.grow", redact(m.error)), resume(),
      ctx.running ? null : h("button.btn.secondary", { type: "button", on: { click: () => ctx.onRegenerate(m.id) } }, T("重试"))));
  }
  if (m.status === "stopped") body.append(h("div.notice.warn", icon("info"), h("div.grow", T("已停止生成。")), resume()));
  if (!live) {
    const bar = verifyBar(m, ctx, renderedCites(body));
    if (bar) body.append(bar);
    const meta = [ASSISTANT, m.rounds > 1 ? T`${m.rounds} 轮` : null, m.toolCount ? T`${m.toolCount} 次工具调用` : null,
      m.ms ? fmtMs(m.ms) : null, m.usage?.output ? `${m.usage.input || 0}→${m.usage.output} tokens` : null].filter(Boolean).join(" · ");
    body.append(h("div.actions",
      h("button.icon-btn", { type: "button", title: T("复制回答"), "aria-label": T("复制回答"), on: { click: () => ctx.onCopy(answerText(m)) } }, icon("copy", "sm")),
      last && !ctx.running ? h("button.icon-btn", { type: "button", title: T("重新生成"), "aria-label": T("重新生成"), on: { click: () => ctx.onRegenerate(m.id) } }, icon("redo", "sm")) : null,
      h("span.meta", { title: m.provider === RELAY_ID ? T("道乃久默认服务") : m.model ? T`底层模型 ${m.model}` : null }, meta)));
  }
}

/** The answer as the model wrote it — for the model only; what anyone reads of it is answerText.  An answer the
 * self-check had rewritten (自查) is not part of it: the rewrite stands. */
export function rawAnswer(m) {
  return (m.segments || []).filter((s) => s.type === "text" && !s.superseded).map((s) => s.text).join("\n\n").trim();
}

/** The answer as a visitor reads it, copies it and the record keeps it: in plain words (redact.js). */
export function answerText(m) {
  return redact(rawAnswer(m));
}

/** The self-check's note (自查): the passages the answer cited that the corpus has not, and what came of asking again. */
function checkNode(seg) {
  const ids = (seg.missing || []).join(T("、"));
  const text = !seg.cut ? T`自查：初稿所引的 ${ids} 在语料中查无此段，已请模型检索核实后重新作答。`
    : seg.error ? T`自查：初稿所引的 ${ids} 在语料中查无此段；重新作答未能完成（${seg.error}），上面的回答未经更正。`
      : T`自查：初稿所引的 ${ids} 在语料中查无此段；重新作答未能完成，上面的回答未经更正。`;
  return h("div.notice.check", icon("info"), h("div.grow", text));
}

/** An answer the self-check had rewritten, folded: drawn only when opened, its citations checked as anywhere but not
 * counted under the answer (renderedCites). */
function draftNode(m, seg, k, ctx) {
  const key = `${m.id}:${k}`;
  const d = h("details.draft");
  d.append(h("summary", icon("chev", "sm chev"), h("span.lbl", T("初稿（自查后已重新作答）"))));
  const fill = () => {
    if (d.querySelector(".md")) return;
    const md = h("div.md.superseded");
    md.append(renderMarkdown(redact(seg.text), { cite: ctx.cite }));
    d.append(md);
  };
  if (ctx.openThink.has(key)) { d.open = true; fill(); }
  d.addEventListener("toggle", () => { if (d.open) { ctx.openThink.add(key); fill(); } else ctx.openThink.delete(key); });
  return d;
}

function thinkingNode(m, seg, k, ctx, live) {
  const key = `${m.id}:${k}`;
  const d = h("details.think", { class: live ? "live" : "" });
  if (ctx.openThink.has(key)) d.open = true;
  d.addEventListener("toggle", () => { if (d.open) ctx.openThink.add(key); else ctx.openThink.delete(key); });
  const secs = seg.ms ? ` · ${fmtMs(seg.ms)}` : "";
  d.append(h("summary", icon("chev", "sm chev"), h("span.lbl", live ? T("思考中…") : T("思考过程")), h("span", secs)),
    h("div.tx", redact(seg.text, { streaming: live }) || "…"));
  return d;
}

// a call the turn still waits for; and one it no longer waits for that still runs (a research run going on by itself)
const WAITING = new Set(["preparing", "loading", "queued", "running"]);
const BUSY = new Set([...WAITING, "background"]);

function stepsNode(m, seg, k, ctx, live) {
  const key = `${m.id}:${k}`;
  const calls = seg.calls || [];
  const running = calls.some((c) => WAITING.has(c.status));
  const open = ctx.openSteps.has(key) || (live && running && !ctx.closedSteps.has(key));
  const box = h("div.steps", { class: open ? "open" : "" });
  const fams = [...new Set(calls.map((c) => c.family))].map((f) => h("span.fam", { class: f }, FAMILY[f] || f));
  const errs = calls.filter((c) => c.status === "error" || c.status === "timeout").length;
  const later = calls.filter((c) => c.status === "background").length;
  const label = running ? T`正在调用工具（${calls.filter((c) => !BUSY.has(c.status)).length}/${calls.length}）`
    : T`调用了 ${calls.length} 个工具${(errs ? T`，${errs} 个出错` : "") + (later ? T`，${later} 个仍在后台进行` : "")}`;
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
  // waited on a while: the answer can be had without the calls still running
  const offer = live && running && seg.offer && ctx.onAnswerNow
    ? h("div.offer", h("span", T("还有工具在运行。")),
      h("button.btn.secondary", { type: "button", on: { click: () => ctx.onAnswerNow(m.id) } }, T("不再等待，根据已有结果作答")))
    : null;
  box.append(head, offer, list);
  return box;
}

// which chart of a tools segment is shown, kept while the turn is drawn again
const shown = new WeakMap();

/** The figures and tables the segment's tools made, under its steps: one at a time, with tabs, when there are several. */
function chartsNode(seg) {
  const specs = (seg.calls || []).flatMap((c) => c.charts || []);
  const tables = (seg.calls || []).flatMap((c) => c.tables || []);
  if (!specs.length && !tables.length) return null;
  if (!shown.has(seg)) shown.set(seg, { at: 0 });
  return chartGallery(specs, shown.get(seg), tables);
}

function toolNode(m, c, key, ctx) {
  const open = ctx.openTools.has(key);
  const t = h("div.tool", { class: open ? "open" : "" });
  // ok · error · timeout (not waited for past its deadline) · skipped (not waited for: the answer was asked for) ·
  // stopped · background (a research run going on by itself); and, while it is waited for, its state
  const status = BUSY.has(c.status) ? h("span.st", h("span.spinner"))
    : c.status === "error" ? h("span.st.err", icon("x", "sm"))
    : c.status === "timeout" || c.status === "skipped" ? h("span.st.warn", icon("warn", "sm"))
    : c.status === "stopped" ? h("span.st.off", icon("stop", "sm"))
    : h("span.st.ok", icon("check", "sm"));
  const summary = c.status === "preparing" ? T("准备参数…")
    : c.status === "loading" ? T("等待运行环境载入…")
    : c.status === "queued" ? (c.progress || T("排队中：等前面的调用完成…"))
    : c.status === "running" ? (c.progress || T("运行中…"))
    : c.status === "background" && c.progress ? T`后台继续 · ${c.progress}`
    : (c.summary || "");
  // how long it has run, while it runs (drawn again each second by the page)
  const since = c.status === "running" && c.since ? { dataset: { since: String(c.since) } } : {};
  const row = h("button.row", { type: "button" },
    status, h("span.fam", { class: c.family }, FAMILY[c.family] || c.family), h("span.nm", displayName(c.name)),
    h("span.sm", redact(summary)), h("span.ms", since, c.ms ? fmtMs(c.ms) : c.status === "running" && c.since ? fmtMs(Date.now() - c.since) : ""));
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
    h("h5", T("参数")), h("pre.json", prettyJSON(c.args ?? {})),
    c.error ? [h("h5", T("错误")), h("pre.json", c.error)] : null,
    c.preview ? [h("h5", T("结果（模型读到的内容）")), h("pre.json", readable(c.preview))] : null,
    c.charts?.length ? [h("h5", T`图（${c.charts.length}）`), h("div.muted", { style: { fontSize: "12.5px" } }, c.charts.map((x, i) => T`图${i + 1} ${x.title || T("图表")}`).join(T("；")))] : null,
    c.tables?.length ? [h("h5", T`表（${c.tables.length}）`), h("div.muted", { style: { fontSize: "12.5px" } }, c.tables.map((x, i) => T`表${i + 1} ${x.title || T("表格")}`).join(T("；")))] : null,
    c.citations?.length ? [h("h5", T`涉及的段落（${c.citations.length}）`),
      h("div.cites-row", c.citations.slice(0, 40).map((card) => foundCard(card, ctx.citeCard(card))))] : null,
    c.research ? h("button.btn.secondary", { type: "button", style: { marginTop: "8px" }, on: { click: () => ctx.onOpenResearch(c.research) } }, icon("flask", "sm"), T("在侧栏查看研究结果")) : null,
  );
}

/** A passage's chip, followed — for a search hit found under another name of a drug, or flagged — by what it was
 * found under (别名：国老→甘草 · 别名录（中醫笈成）) and its flags (年代存疑 …). */
function foundCard(card, chip) {
  const badges = foundBadges(card.found);
  if (!badges.length) return chip;
  return h("span", { style: { display: "inline-flex", alignItems: "center", flexWrap: "wrap", gap: "4px", maxWidth: "100%" } }, chip, badges);
}

/** The citations as rendered in a turn's answer — not in a draft the self-check had rewritten: [{pid, quote}]. */
export function renderedCites(body) {
  return [...body.querySelectorAll(".md:not(.superseded) .cite[data-cite='text']")].map((b) => ({ pid: b.dataset.pid, quote: b.dataset.quote || null }));
}

export function verifyBar(m, ctx, ids) {
  if (!ids.length) return null;
  const counts = { ok: 0, warn: 0, bad: 0, pending: 0 };
  for (const r of ids) counts[ctx.citeStatus(r.pid, r.quote)?.status || "pending"]++;
  return h("div.verify-bar", { dataset: { verify: m.id } },
    icon("quote", "sm"), T("引文核对："),
    counts.ok ? h("span.b.ok", icon("check", "sm"), T`${counts.ok} 条与原文一致`) : null,
    counts.warn ? h("span.b.warn", icon("warn", "sm"), T`${counts.warn} 条存疑`) : null,
    counts.bad ? h("span.b.bad", icon("x", "sm"), T`${counts.bad} 条查无此段`) : null,
    counts.pending ? h("span.b", T`${counts.pending} 条核对中`) : null);
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
