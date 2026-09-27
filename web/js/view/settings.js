// Settings: the model (provider, key, model name, thinking, route), where TaoChronos runs, standing instructions,
// the conversations' data, and what this page is.

import { allProviders, DEFAULTS, providerById } from "../providers.js";
import { h, icon, replace } from "../util.js";

const SECTIONS = [
  ["model", "模型", "chip"],
  ["runtime", "运行环境", "server"],
  ["instructions", "指令", "edit"],
  ["data", "数据", "download"],
  ["about", "关于", "info"],
];

export function openSettings(S, ctx, section = "model") {
  const dlg = document.getElementById("settings");
  let current = section;
  const draft = structuredClone(S.settings);
  const nav = h("nav.settings-nav");
  const pane = h("div.settings-pane");
  const draw = () => {
    nav.replaceChildren(...SECTIONS.map(([id, label, ic]) => h("button", { type: "button", class: id === current ? "on" : "", on: { click: () => { current = id; draw(); } } }, icon(ic, "sm"), label)));
    replace(pane, ({ model: modelPane, runtime: runtimePane, instructions: instructionsPane, data: dataPane, about: aboutPane }[current])(draft, S, ctx, draw));
    pane.scrollTop = 0;
  };
  const save = () => { ctx.save(draft); dlg.close(); };
  dlg.replaceChildren(h("div.modal.wide", { role: "document" },
    h("div.modal-head", h("h2", "设置"), h("button.icon-btn", { type: "button", "aria-label": "关闭", on: { click: () => dlg.close() } }, icon("x"))),
    h("div.settings-layout", { style: { minHeight: 0, overflow: "hidden" } }, nav, pane),
    h("div.modal-foot",
      h("span.muted", { style: { flex: 1, fontSize: "12.5px", alignSelf: "center" } }, "密钥只保存在本浏览器，只发送给所选服务（或你的本地服务）。"),
      h("button.btn.secondary", { type: "button", on: { click: () => dlg.close() } }, "取消"),
      h("button.btn", { type: "button", on: { click: save } }, "保存"))));
  draw();
  dlg.onclick = (e) => { if (e.target === dlg) dlg.close(); };
  if (!dlg.open) dlg.showModal();
}

function field(label, input, help) {
  return h("div.field", h("label", label), input, help ? h("div.help", help) : null);
}

function seg(options, value, onChange) {
  const box = h("div.seg", { role: "radiogroup" });
  for (const [v, label] of options) {
    const b = h("button", { type: "button", role: "radio", "aria-checked": String(v === value), class: v === value ? "on" : "" }, label);
    b.addEventListener("click", () => {
      onChange(v);
      for (const x of box.children) { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); }
    });
    box.append(b);
  }
  return box;
}

// ------------------------------------------------------------------ model
function modelPane(d, S, ctx, redraw) {
  const p = providerById(d.provider);
  const grid = h("div.provider-grid", allProviders().map((x) => h("button.provider-opt", {
    type: "button", class: x.id === d.provider ? "on" : "",
    on: { click: () => { d.provider = x.id; redraw(); } },
  }, x.label, h("small", x.default_model || (x.examples || [])[0] || x.base_url.replace(/^https?:\/\//, "")))));
  const model = h("input", { type: "text", list: "model-list", value: d.models[p.id] || p.default_model || "", placeholder: "模型名" });
  model.addEventListener("input", () => { d.models[p.id] = model.value.trim(); });
  const list = h("datalist#model-list", (p.examples || []).map((m) => h("option", { value: m })));
  const base = h("input", { type: "url", value: d.baseUrls[p.id] || "", placeholder: p.base_url });
  base.addEventListener("input", () => { if (base.value.trim()) d.baseUrls[p.id] = base.value.trim(); else delete d.baseUrls[p.id]; });
  const key = h("input", { type: "password", value: d.keys[p.id] || "", placeholder: p.key_optional ? "（可不填）" : "粘贴 API Key", autocomplete: "off", spellcheck: false });
  key.addEventListener("input", () => { if (key.value.trim()) d.keys[p.id] = key.value.trim(); else delete d.keys[p.id]; });
  const eye = h("button.icon-btn", { type: "button", title: "显示/隐藏", "aria-label": "显示或隐藏密钥", on: { click: () => { key.type = key.type === "password" ? "text" : "password"; } } }, icon("key", "sm"));
  const temp = h("input", { type: "number", min: 0, max: 2, step: 0.1, value: d.temperature ?? "", placeholder: "默认" });
  temp.addEventListener("input", () => { d.temperature = temp.value === "" ? null : Number(temp.value); });
  const maxTok = h("input", { type: "number", min: 256, step: 256, value: d.maxTokens });
  maxTok.addEventListener("input", () => { d.maxTokens = Number(maxTok.value) || DEFAULTS.maxTokens; });
  const think = h("input", { type: "checkbox", checked: d.thinking !== false });
  think.addEventListener("change", () => { d.thinking = think.checked; });
  const result = h("div.test-result");
  const test = h("button.btn.secondary", { type: "button" }, icon("bolt", "sm"), "测试连接");
  test.addEventListener("click", async () => {
    test.disabled = true;
    result.className = "test-result";
    result.textContent = "正在请求…";
    const r = await ctx.testModel(d);
    test.disabled = false;
    result.className = `test-result ${r.ok ? "ok" : "err"}`;
    result.textContent = r.message;
  });
  return [
    h("h3", "模型"),
    h("p.lead", "TaoChronos 的工具在本机或浏览器里运行；对话由你选择的模型完成，使用你自己的 API Key。默认 MiniMax 国内站的 MiniMax-M3。"),
    h("div.form-grid",
      h("div.field", h("span.lb", "服务商"), grid, p.note ? h("div.help", p.note) : null),
      h("div.field", h("label", "模型"), model, list, h("div.help", (p.examples || []).length ? `常用：${p.examples.join("、")}` : "填写服务商提供的模型名")),
      h("div.field", h("label", "API Key"), h("div.inline", key, eye),
        h("div.help", p.key_env ? `也可以不在网页里填：本地服务以 --env-keys 启动时，会使用本机环境变量 ${p.key_env}。` : "")),
      field("接口地址（Base URL）", base, `默认 ${p.base_url}${p.format === "anthropic" ? "（经官方 Anthropic SDK 调用）" : "（OpenAI 兼容接口）"}`),
      h("div.field", h("span.lb", "请求路径"),
        seg([["auto", "自动"], ["direct", "浏览器直连"], ["proxy", "经本地服务转发"]], d.route, (v) => { d.route = v; }),
        h("div.help", "直连：浏览器直接请求模型服务（需该服务允许跨域）。转发：由本机的 taochronos serve 代为请求，适用于不允许跨域的服务，也可使用本机环境变量中的密钥。自动：连着本地服务时转发，否则直连。")),
      h("label.check", think, h("span", "启用思考（MiniMax-M3 默认开启自适应思考；Claude 使用 adaptive thinking）")),
      h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" } },
        field("温度", temp, "留空使用服务商默认值（MiniMax-M3 为 1.0）"),
        field("最大输出（tokens）", maxTok, "含思考内容")),
      h("div", test, result)),
  ];
}

// ------------------------------------------------------------------ runtime
function runtimePane(d, S, ctx) {
  const info = S.runtimeInfo;
  const url = h("input", { type: "url", value: d.serverUrl });
  url.addEventListener("input", () => { d.serverUrl = url.value.trim() || DEFAULTS.serverUrl; });
  const result = h("div.test-result");
  const test = h("button.btn.secondary", { type: "button" }, icon("server", "sm"), "连接测试");
  test.addEventListener("click", async () => {
    test.disabled = true;
    result.className = "test-result";
    result.textContent = "正在连接…";
    const r = await ctx.testServer(d.serverUrl);
    test.disabled = false;
    result.className = `test-result ${r.ok ? "ok" : "err"}`;
    result.textContent = r.message;
  });
  const steps = h("input", { type: "number", min: 1, max: 60, value: d.maxSteps });
  steps.addEventListener("input", () => { d.maxSteps = Number(steps.value) || DEFAULTS.maxSteps; });
  const chars = h("input", { type: "number", min: 2000, max: 200000, step: 1000, value: d.resultChars });
  chars.addEventListener("input", () => { d.resultChars = Number(chars.value) || DEFAULTS.resultChars; });
  return [
    h("h3", "运行环境"),
    h("p.lead", "TaoChronos 可以在浏览器里运行（Pyodide，演示语料，开箱即用），也可以连接你本机的 TaoChronos 服务（全量语料）。"),
    h("div.form-grid",
      h("div.field", h("span.lb", "在哪里运行"),
        seg([["auto", "自动"], ["browser", "浏览器内（演示语料）"], ["server", "本地服务（全量语料）"]], d.runtime, (v) => { d.runtime = v; })),
      h("div.field", h("label", "本地服务地址"), h("div.inline", url, test), result,
        h("div.help", "在 TaoChronos 目录中运行下面的命令，然后在这里连接（或直接打开它给出的地址）："),
        h("pre.json", "pip install -e .\ntaochronos serve            # http://localhost:8765\ntaochronos serve --env-keys # 使用本机环境变量中的模型密钥")),
      info ? h("div.notice", icon("info"), h("div.grow",
        `当前：${info.runtime === "server" ? "本地服务" : "浏览器内"} · 画像 ${info.profile} · ${info.corpus?.demo ? "演示语料" : "全量语料"} ${info.corpus?.books} 部书、${info.corpus?.passages} 段 · ${info.tools?.offered} 项工具` +
        (info.engine_model ? ` · 研究引擎模型 ${info.engine_model}` : " · 研究引擎：规则（确定性）") + (info.load_ms ? ` · 载入 ${Math.round(info.load_ms / 100) / 10} 秒` : ""))) : null,
      h("div.field", h("span.lb", "提供给模型的工具"),
        seg([["core", "精选 + 目录（推荐）"], ["all", "全部工具"]], d.toolMode, (v) => { d.toolMode = v; }),
        h("div.help", "精选：直接提供十几个最常用的工具，其余通过 taochronos_catalog / taochronos_call 按需查用，节省上下文。全部：七十余个工具全部直接提供。")),
      h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" } },
        field("每轮最多工具步数", steps, "达到上限后，模型须根据已有结果作答"),
        field("单个工具结果的字符上限", chars, "超出部分按结构均匀截短")),
      h("label.check", (() => { const c = h("input", { type: "checkbox", checked: d.verifyQuotes !== false }); c.addEventListener("change", () => { d.verifyQuotes = c.checked; }); return c; })(),
        h("span", "逐字核对回答中的引文（与原文比对，标出一致、存疑与查无此段）"))),
  ];
}

// ------------------------------------------------------------------ instructions
function instructionsPane(d, S) {
  const ta = h("textarea", { rows: 7, placeholder: "例如：回答时先列出原文，再给出白话解释；引用时注明卷次。" }, d.instructions || "");
  ta.addEventListener("input", () => { d.instructions = ta.value; });
  return [
    h("h3", "指令"),
    h("p.lead", "附加在系统指令之后，对每次对话生效。系统指令规定了证据纪律（先检索再作答、逐字引用并标注出处、不作医疗建议），不可移除。"),
    h("div.form-grid",
      field("我的附加指令", ta),
      h("details", h("summary", { style: { cursor: "pointer", fontSize: "13.5px", color: "var(--ink-2)" } }, "查看系统指令"),
        h("pre.json", { style: { maxHeight: "360px", marginTop: "8px" } }, S.runtimeInfo?.system_prompt || "（运行环境就绪后显示）"))),
  ];
}

// ------------------------------------------------------------------ data
function dataPane(d, S, ctx) {
  const file = h("input", { type: "file", accept: "application/json", hidden: true });
  file.addEventListener("change", async () => {
    const f = file.files?.[0];
    if (f) ctx.importAll(await f.text());
    file.value = "";
  });
  return [
    h("h3", "数据"),
    h("p.lead", "对话保存在本浏览器（IndexedDB），不会上传。换设备或清理浏览器数据前，请先导出。"),
    h("div.form-grid",
      h("div.chips",
        h("button.btn.secondary", { type: "button", on: { click: ctx.exportAll } }, icon("download", "sm"), "导出全部对话（JSON）"),
        h("button.btn.secondary", { type: "button", on: { click: () => file.click() } }, icon("upload", "sm"), "导入对话"), file,
        S.conv ? h("button.btn.secondary", { type: "button", on: { click: () => ctx.exportMarkdown(S.conv) } }, icon("download", "sm"), "导出当前对话（Markdown）") : null),
      h("div.chips",
        h("button.btn.secondary", { type: "button", on: { click: () => { d.keys = {}; ctx.toast("已清除表单中的全部密钥，保存后生效"); } } }, icon("key", "sm"), "清除所有 API Key"),
        h("button.btn.danger", { type: "button", on: { click: ctx.clearAll } }, icon("trash", "sm"), "删除全部对话"))),
  ];
}

// ------------------------------------------------------------------ about
function aboutPane(d, S) {
  const info = S.runtimeInfo;
  return [
    h("h3", "关于 TaoChronos"),
    h("p.lead", "面向中医古籍的可溯源知识发现与治学系统。确定性的研究平台（检索、考据、发现、核验）负责取证与计算；你选择的模型负责理解问题、调用工具、组织回答。"),
    h("div.form-grid",
      h("div.notice", icon("info"), h("div.grow",
        h("div", h("b", "证据纪律："), "回答中的古籍原文应来自工具结果，并以 [[段落号]] 标注出处；页面会把每条引文与原文逐字核对。"),
        h("div", h("b", "非医疗建议："), "本系统不提供诊断、处方或剂量建议；历代度量衡换算只是历史读法。计算得到的关联与假说须经专家核验。"),
        h("div", h("b", "语料："), "浏览器内运行的是演示语料（约二十部古籍的短摘录，未经校勘，仅供方法演示）；全量语料需在本机构建并通过 taochronos serve 连接。"),
        h("div", h("b", "隐私："), "对话与密钥只保存在本浏览器；模型请求直接发往你选择的服务，或经你本机的服务转发。"))),
      h("div.muted", { style: { fontSize: "13px", lineHeight: "1.8" } },
        `版本 ${info?.version || "?"} · 运行环境 ${info?.runtime === "server" ? "本地服务" : "浏览器（Pyodide）"} · `,
        h("a", { href: "https://github.com/psknlr/TaoChronos", target: "_blank", rel: "noopener" }, "GitHub 仓库"), " · ",
        h("a", { href: "https://github.com/psknlr/TaoChronos/blob/main/docs/web.md", target: "_blank", rel: "noopener" }, "网页端说明"))),
  ];
}
