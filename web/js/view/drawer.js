// The side panel: 证据 (the passages of this conversation, one read in full), 研究 (research runs), 工具台 (every tool,
// run by hand — no model needed).

import { renderMarkdown } from "../markdown.js";
import { chartGallery, chartsOf } from "../chart.js";
import { append, bare, fmtMs, h, icon, passageLabel, prettyJSON, truncate, yearLabel } from "../util.js";
import { FAMILY, toolFamily } from "./thread.js";

export function renderDrawer(el, S, ctx) {
  const conv = S.conv;
  const evidence = Object.values(conv?.evidence || {});
  const runs = conv?.research || [];
  const tab = S.drawer.tab;
  const tabs = [
    ["evidence", "证据", evidence.length],
    ["research", "研究", runs.length],
    ["tools", "工具台", null],
  ];
  const head = h("div.drawer-head",
    h("div.tabs", { role: "tablist" }, tabs.map(([id, label, n]) => h("button.tab", {
      type: "button", role: "tab", "aria-selected": String(tab === id), class: tab === id ? "on" : "",
      on: { click: () => ctx.setTab(id) },
    }, label, n ? h("span.n", String(n)) : null))),
    h("button.icon-btn", { type: "button", title: "关闭侧栏", "aria-label": "关闭侧栏", on: { click: ctx.close } }, icon("x")));
  const body = h("div.drawer-body");
  if (tab === "evidence") body.append(evidencePane(S, ctx, evidence));
  else if (tab === "research") body.append(researchPane(S, ctx, runs));
  else body.append(toolsPane(S, ctx));
  el.replaceChildren(head, body);
}

// ------------------------------------------------------------------ evidence
function evidencePane(S, ctx, evidence) {
  const pane = h("div.pane");
  const sel = S.drawer.pid;
  if (sel) pane.append(passageView(S, ctx, sel, S.drawer.quote));
  if (!evidence.length && !sel) {
    pane.append(h("div.pane-empty", icon("book"), h("div", "对话中检索到、引用到的古籍段落会出现在这里。"),
      h("div", "点击回答中的出处标记，可在此阅读全文、逐字核对。")));
    return pane;
  }
  if (evidence.length) {
    pane.append(h("div.section-title", `本对话的证据（${evidence.length}）`));
    for (const card of evidence) {
      const st = ctx.bestStatus(card.passage_id);
      pane.append(h("button.ev-item", {
        type: "button", class: card.passage_id === sel ? "sel" : "",
        on: { click: () => ctx.openPassage(card.passage_id, null) },
      },
      h("div.top", h("b", card.title ? `《${card.title}》` : card.passage_id), h("span.grow", truncate(stripBook(card.locator), 26)),
        st ? h("span.badge", { class: st.status }, st.label) : null),
      h("div.q", card.text || ""),
      h("div.top", h("span", yearLabel(card)), h("span.grow"), h("span.mono", { style: { fontSize: "11px" } }, card.passage_id))));
    }
  }
  return pane;
}

const stripBook = (loc) => String(loc || "").replace(/^《[^》]*》/, "");

function passageView(S, ctx, pid, quote) {
  const box = h("div.passage-view", { class: S.drawer.vertical ? "vertical" : "" });
  const card = ctx.passageNow(pid);
  if (!card) {
    box.append(h("div.ph", h("div.ti", h("b", pid), h("div.loc", "正在读取原文…"))), h("div.text", h("span.spinner")));
    ctx.loadPassage(pid);
    return box;
  }
  if (!card.ok) {
    box.append(h("div.ph", h("div.ti", h("b", pid), h("div.loc", "语料中没有这个段落"))),
      h("div.meta", "模型写出的这个出处在当前语料中不存在：可能是编造的段落号，或它来自另一个语料（例如全量语料）。",
        card.error ? h("div.mono", truncate(card.error, 200)) : null));
    return box;
  }
  const st = ctx.citeStatus(pid, quote);
  let range = quote ? findQuote(card.text, quote) : null;
  if (quote && !range) { // quoted in another script: find it in the normalised text, which keeps the length
    const f = ctx.folded(pid, quote);
    if (f.text && f.quote && f.text.length === card.text.length) range = findQuote(f.text, f.quote);
  }
  const text = h("div.text", { lang: "zh-Hant" });
  if (range) text.append(card.text.slice(0, range[0]), h("mark", card.text.slice(range[0], range[1])), card.text.slice(range[1]));
  else text.append(card.text);
  append(box, [
    h("div.ph",
      h("div.ti", h("b", `《${card.title}》`), h("div.loc", stripBook(card.locator)), h("div.loc", [yearLabel(card), card.period].filter(Boolean).join(" · "))),
      h("button.icon-btn", { type: "button", title: S.drawer.vertical ? "横排" : "竖排", "aria-label": "切换横排竖排", on: { click: ctx.toggleVertical } }, icon(S.drawer.vertical ? "text" : "vertical")),
      h("button.icon-btn", { type: "button", title: "复制原文与出处", "aria-label": "复制原文", on: { click: () => ctx.copy(`${card.text}\n——《${card.title}》${stripBook(card.locator)}（${card.passage_id}）`) } }, icon("copy"))),
    h("div.status-line",
      st ? h("span.badge", { class: st.status }, st.label) : null,
      card.collation_status ? h("span.badge", card.collation_status === "unverified" ? "未经校勘" : `校勘：${card.collation_status}`) : null,
      h("span.badge.mono", pid)),
    text,
    quote && !range ? h("div.meta", h("b", "模型的引文："), h("span.serif", `「${quote}」`), h("div", "与此段原文未能逐字对应：可能是节引、改写或误引，请以原文为准。")) : null,
    card.variants?.length ? h("div.meta", h("b", "异文："), card.variants.slice(0, 6).map((v) => h("div", `${v.reading ?? v.text ?? ""}${v.witness ? `（${v.witness}）` : ""}${v.note ? ` · ${v.note}` : ""}`))) : null,
    card.notes ? h("div.meta", h("b", "注："), typeof card.notes === "string" ? card.notes : prettyJSON(card.notes, 800)) : null,
  ]);
  return box;
}

/** Where the quotation stands in the passage (ignoring punctuation and spacing), as [start, end) of the original. */
export function findQuote(text, quote) {
  const q = bare(quote);
  if (!q) return null;
  const map = [];
  let flat = "";
  for (let i = 0; i < text.length; i++) {
    const b = bare(text[i]);
    if (b) { for (let k = 0; k < b.length; k++) map.push(i); flat += b; }
  }
  const at = flat.indexOf(q);
  if (at < 0) return null;
  return [map[at], map[at + q.length - 1] + 1];
}

// ------------------------------------------------------------------ research
function researchPane(S, ctx, runs) {
  const pane = h("div.pane");
  pane.append(researchForm(S, ctx));
  if (!runs.length) {
    pane.append(h("div.pane-empty", icon("flask"), h("div", "多智能体发现研究：研究契约 → 证据 → 模式挖掘（D1–D5）→ 假说 → 证伪 → 门控。"),
      h("div", "可以在对话中请模型发起，也可以用上面的表单直接运行（无需模型）。")));
    return pane;
  }
  for (const run of [...runs].reverse()) pane.append(runCard(run, ctx));
  return pane;
}

function researchForm(S, ctx) {
  const d = h("details.console-form", { open: S.drawer.researchFormOpen || false });
  d.addEventListener("toggle", () => { S.drawer.researchFormOpen = d.open; });
  const q = h("textarea", { rows: 2, placeholder: "研究问题，如：胸痹的认识与治疗在明代以前如何演变？" });
  const focus = h("input", { type: "text", placeholder: "焦点术语（可选），如：胸痹" });
  const tracks = ["D1", "D2", "D3", "D4", "D5"].map((t) => h("label.check", h("input", { type: "checkbox", checked: true, value: t }), t));
  const rounds = h("input", { type: "number", min: 1, max: 6, value: 2 });
  const forbid = h("input", { type: "text", placeholder: "禁止的时代错置假设（可选），如：胸痹=冠心病" });
  const run = h("button.btn", { type: "button" }, icon("play", "sm"), "运行研究");
  run.addEventListener("click", () => {
    const question = q.value.trim();
    if (!question) { q.focus(); return; }
    const args = { question, max_rounds: Number(rounds.value) || 2 };
    const f = focus.value.split(/[,，、\s]+/).filter(Boolean);
    if (f.length) args.focus_terms = f;
    const tr = tracks.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    if (tr.length && tr.length < 5) args.tracks = tr;
    const fb = forbid.value.split(/[,，；;]+/).map((s) => s.trim()).filter(Boolean);
    if (fb.length) args.forbidden_assumptions = fb;
    ctx.runResearch(args);
  });
  d.append(h("summary", { style: { cursor: "pointer", fontWeight: 600, fontSize: "13.5px" } }, "直接发起一次研究"),
    h("div.form-grid", { style: { marginTop: "10px" } },
      h("div.field", h("label", "研究问题"), q),
      h("div.field", h("label", "焦点术语"), focus),
      h("div.field", h("span.lb", "发现轨道"), h("div.chips", tracks),
        h("div.help", "D1 失传关联 · D2 概念漂移 · D3 方剂演化 · D4 隐含关联 · D5 矛盾")),
      h("div.field", h("label", "轮次"), rounds),
      h("div.field", h("label", "禁止假设"), forbid),
      h("div", run, S.researchRunning ? h("span.muted", { style: { marginLeft: "10px", fontSize: "13px" } }, h("span.spinner", { style: { display: "inline-block", verticalAlign: "-2px", marginRight: "6px" } }), S.researchRunning) : null)));
  return d;
}

const VERDICT = {
  accepted: ["已接受", "ok"], needs_expert: ["需专家判定", "warn"], inconclusive: ["不确定", "warn"], rejected: ["未通过", "bad"],
  execution_finished: ["执行完毕", ""],
};
const STATUS = {
  survived: ["经受证伪", "ok"], proposed: ["提出", ""], needs_revision: ["需修订", "warn"], rejected: ["被证伪", "bad"],
  expert_approved: ["专家认可", "ok"], expert_rejected: ["专家否决", "bad"],
};
const KIND = {
  lost_knowledge: "D1 失传关联", concept_drift: "D2 概念漂移", formula_evolution: "D3 方剂演化", association_rule: "D4 关联规则",
  hidden_association: "D4 隐含关联", contradiction: "D5 矛盾", concept_timeline: "概念演变",
};

function runCard(run, ctx) {
  const r = run.result || {};
  const [vLabel, vCls] = VERDICT[r.acceptance] || [r.acceptance || r.status || "", ""];
  const m = r.metrics || {};
  const wrap = h("div");
  wrap.append(h("div.run-card",
    h("div.q", r.question || run.question),
    h("div.row",
      h("span.badge", { class: vCls }, vLabel),
      h("span.badge", `执行：${r.status || ""}`),
      h("span.badge", `${r.rounds ?? "?"} 轮`),
      run.ms ? h("span.badge", fmtMs(run.ms)) : null,
      h("span.badge.mono", r.session_id || "")),
    h("div.metric-grid",
      metric(m.claims, "主张"), metric(m.evidence_count, "证据"), metric(m.counter_evidence, "反证"),
      metric(m.hypotheses, "假说"), metric(m.hypothesis_survival != null ? `${Math.round(m.hypothesis_survival * 100)}%` : "–", "存活率"),
      metric(m.agents_spawned, "智能体")),
    (r.acceptance_reasons || []).length ? h("div.muted", { style: { fontSize: "12.5px", marginTop: "8px", lineHeight: "1.6" } }, r.acceptance_reasons.join("；")) : null,
    h("div.row",
      r.report_markdown ? h("button.btn.secondary", { type: "button", on: { click: () => ctx.openReport(run) } }, icon("scroll", "sm"), "完整报告") : null,
      r.report_markdown ? h("button.btn-ghost", { type: "button", on: { click: () => ctx.downloadReport(run) } }, icon("download", "sm"), "下载") : null,
      h("button.btn-ghost", { type: "button", on: { click: () => ctx.askAbout(run) } }, icon("sparkle", "sm"), "就此追问"))));
  for (const hy of r.hypotheses || []) wrap.append(hypCard(hy, ctx));
  if (r.rejected) wrap.append(h("div.muted", { style: { fontSize: "12.5px", margin: "4px 2px 16px" } }, `另有 ${r.rejected} 个假说在证伪中被否决（见完整报告）。`));
  if (r.note) wrap.append(h("div.notice", icon("info"), h("div.grow", r.note)));
  return wrap;
}

function metric(v, label) {
  return h("div.metric", h("b", v ?? "–"), h("span", label));
}

function hypCard(hy, ctx) {
  const [sLabel, sCls] = STATUS[hy.status] || [hy.status || "", ""];
  const score = Number(hy.discovery_score) || 0;
  const ev = (list, cls) => (list || []).map((e) => h("div.evq", { class: cls },
    `「${truncate(e.quote, 90)}」`, ctx.citeCard({ passage_id: e.passage_id, title: e.title, locator: e.locator, dynasty: e.dynasty, year: e.year })));
  return h("div.hyp",
    h("div.top", h("span.lbl", hy.label), h("span", KIND[hy.kind] || hy.kind || ""), h("span", { style: { flex: 1 } }),
      h("span.badge", { class: sCls }, sLabel), hy.acceptance ? h("span.badge", (VERDICT[hy.acceptance] || [hy.acceptance])[0]) : null),
    h("div.st", hy.statement),
    h("div.bar", { title: `发现分 D = ${score.toFixed(3)}（优先级，不是真值）` }, h("i", { style: { width: `${Math.round(Math.min(1, score) * 100)}%` } })),
    h("details",
      h("summary", `证据 ${hy.supporting?.length || 0} · 反证 ${hy.contradicting?.length || 0} · 替代解释 ${hy.alternatives?.length || 0}`),
      ev(hy.supporting, ""), ev(hy.contradicting, "con"),
      hy.alternatives?.length ? h("div", { style: { marginTop: "6px" } }, h("b", "替代解释："), hy.alternatives.join("；")) : null,
      hy.prediction ? h("div", { style: { marginTop: "6px" } }, h("b", "可检验预测："), hy.prediction) : null,
      hy.risks ? h("div.muted", { style: { marginTop: "6px" } }, `文献学风险 ${hy.risks.philological || "?"} · 时代错置风险 ${hy.risks.anachronism || "?"}`) : null));
}

export function reportNode(run, ctx) {
  const md = h("div.md.report-md");
  md.append(renderMarkdown(run.result?.report_markdown || "", { cite: ctx.cite }));
  return md;
}

// ------------------------------------------------------------------ tool console
function toolsPane(S, ctx) {
  const pane = h("div.pane");
  const cat = S.catalogAll;
  if (!cat) {
    pane.append(h("div.pane-empty", h("span.spinner", { style: { display: "inline-block" } }), h("div", "正在读取工具目录…")));
    ctx.loadCatalogAll();
    return pane;
  }
  pane.append(h("div.muted", { style: { fontSize: "12.5px", lineHeight: "1.7", marginBottom: "10px" } },
    `TaoChronos 的全部 ${cat.tools.length} 项能力。选一项、填参数、运行——无需模型；结果中的段落可在“证据”中阅读。`));
  const picked = S.drawer.tool && cat.tools.find((t) => t.name === S.drawer.tool);
  if (picked) pane.append(consoleForm(S, ctx, picked));
  const search = h("input.input", { type: "search", placeholder: "查找工具：配伍、避讳、stemma、今译……", value: S.drawer.toolQuery || "" });
  search.addEventListener("input", () => { S.drawer.toolQuery = search.value; ctx.rerenderTools(); });
  pane.append(h("div", { style: { margin: "4px 0 10px" } }, search));
  const q = (S.drawer.toolQuery || "").trim().toLowerCase();
  const byFam = new Map();
  for (const t of cat.tools) {
    if (t.name === "taochronos_catalog" || t.name === "taochronos_call") continue;
    if (q && !(t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q) || (t.tool || "").includes(q))) continue;
    const fam = t.family || toolFamily(t.name);
    if (!byFam.has(fam)) byFam.set(fam, []);
    byFam.get(fam).push(t);
  }
  const fams = cat.families || {};
  for (const [fam, tools] of byFam) {
    const open = q || S.drawer.famOpen?.has(fam);
    const block = h("div.fam-block");
    const btn = h("button", { type: "button" }, icon(open ? "chevdown" : "chev", "sm"), h("span.fam", { class: fam }, fams[fam]?.label || FAMILY[fam] || fam),
      h("span", { style: { fontSize: "13px" } }, truncate(fams[fam]?.blurb || "", 30)), h("span.n", String(tools.length)));
    btn.addEventListener("click", () => {
      S.drawer.famOpen ||= new Set();
      if (S.drawer.famOpen.has(fam)) S.drawer.famOpen.delete(fam); else S.drawer.famOpen.add(fam);
      ctx.rerenderTools();
    });
    block.append(btn);
    if (open) {
      for (const t of tools) {
        block.append(h("button.tool-item", { type: "button", on: { click: () => ctx.pickTool(t.name) } },
          h("code", t.tool || t.name), h("span", t.description)));
      }
    }
    pane.append(block);
  }
  return pane;
}

const LONG = new Set(["text", "claim", "question", "code", "query", "reference"]);

function consoleForm(S, ctx, tool) {
  if (!tool) return null;
  const props = tool.parameters?.properties || {};
  const required = new Set(tool.parameters?.required || []);
  const inputs = {};
  const fields = Object.entries(props).map(([name, sch]) => {
    let input;
    const saved = S.drawer.toolArgs?.[tool.name]?.[name];
    if (sch.enum) input = h("select", h("option", { value: "" }, "（默认）"), sch.enum.map((v) => h("option", { value: v, selected: saved === v }, v)));
    else if (sch.type === "boolean") input = h("input", { type: "checkbox", checked: Boolean(saved) });
    else if (sch.type === "integer" || sch.type === "number") input = h("input", { type: "number", step: sch.type === "integer" ? 1 : "any", value: saved ?? "" });
    else if (sch.type === "array" && (sch.items?.type === "string" || !sch.items)) input = h("input", { type: "text", placeholder: "多个值以逗号或顿号分隔", value: saved ?? "" });
    else if (sch.type === "array" || sch.type === "object") input = h("textarea", { rows: 3, placeholder: "JSON" }, saved ?? "");
    else if (LONG.has(name)) input = h("textarea", { rows: 3 }, saved ?? "");
    else input = h("input", { type: "text", value: saved ?? "" });
    inputs[name] = { input, sch };
    return h("div.field", h("label", name, required.has(name) ? h("span", { style: { color: "var(--accent)" } }, " *") : null,
      sch.type ? h("span.muted", { style: { fontWeight: 400 } }, `  ${sch.type}${sch.items?.type ? `<${sch.items.type}>` : ""}`) : null),
    input, sch.description ? h("div.help", sch.description) : null);
  });
  const out = h("div");
  const run = h("button.btn", { type: "button" }, icon("play", "sm"), "运行");
  const collect = () => {
    const args = {}, raw = {};
    for (const [name, { input, sch }] of Object.entries(inputs)) {
      if (sch.type === "boolean") { if (input.checked) { args[name] = true; raw[name] = true; } continue; }
      const v = input.value.trim();
      raw[name] = input.value;
      if (!v) continue;
      if (sch.type === "integer") args[name] = parseInt(v, 10);
      else if (sch.type === "number") args[name] = Number(v);
      else if (sch.type === "array" && (sch.items?.type === "string" || !sch.items)) args[name] = v.split(/[,，、;；\n]+/).map((s) => s.trim()).filter(Boolean);
      else if (sch.type === "array" || sch.type === "object") args[name] = JSON.parse(v);
      else args[name] = v;
    }
    return { args, raw };
  };
  run.addEventListener("click", async () => {
    let args;
    try {
      const c = collect();
      args = c.args;
      S.drawer.toolArgs ||= {};
      S.drawer.toolArgs[tool.name] = c.raw;
    } catch (e) {
      out.replaceChildren(h("div.notice.err", icon("warn"), h("div.grow", `参数不是合法的 JSON：${e.message}`)));
      return;
    }
    const missing = [...required].filter((k) => args[k] === undefined);
    if (missing.length) { out.replaceChildren(h("div.notice.warn", icon("info"), h("div.grow", `请填写：${missing.join("、")}`))); return; }
    run.disabled = true;
    out.replaceChildren(h("div.muted", { style: { fontSize: "13px" } }, h("span.spinner", { style: { display: "inline-block", verticalAlign: "-2px", marginRight: "6px" } }), "运行中…"));
    const res = await ctx.runTool(tool.name, args);
    run.disabled = false;
    out.replaceChildren(resultView(res, ctx));
  });
  return h("div.console-form",
    h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } },
      h("span.fam", { class: tool.family }, FAMILY[tool.family] || tool.family), h("code.mono", { style: { fontSize: "13px", flex: 1 } }, tool.tool || tool.name),
      h("button.icon-btn", { type: "button", title: "关闭", "aria-label": "关闭", on: { click: () => ctx.pickTool(null) } }, icon("x", "sm"))),
    h("div.desc", tool.description),
    h("div.form-grid", fields.length ? fields : h("div.muted", { style: { fontSize: "13px" } }, "此工具没有参数。")),
    h("div", { style: { marginTop: "10px" } }, run),
    out);
}

function resultView(res, ctx) {
  if (!res.ok) return h("div.notice.err", { style: { marginTop: "10px" } }, icon("warn"), h("div.grow", res.error || "失败"));
  return h("div", { style: { marginTop: "10px" } },
    h("div.muted", { style: { fontSize: "12.5px", marginBottom: "6px" } }, `${res.summary || "完成"} · ${fmtMs(res.duration_ms)}`),
    res.citations?.length ? h("div.cites-row", { style: { marginBottom: "8px" } }, res.citations.slice(0, 30).map((c) => ctx.citeCard(c))) : null,
    chartGallery(chartsOf(res.result)),
    h("pre.json", prettyJSON(res.result, 120000)));
}

export { passageLabel };
