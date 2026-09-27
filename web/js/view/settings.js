// Settings: the model (provider, key, model name, thinking, route), where TaoChronos runs, standing instructions,
// the conversations' data, and what this page is.

import { AGENT, AGENT_EN, MODEL as ASSISTANT, PUBLISHED_BY, PUBLISHER, PUBLISHER_EN } from "../brand.js";
import { allProviders, DEFAULTS, newCustomProvider, providerById } from "../providers.js";
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
  const p = providerById(d.provider, d);
  const custom = p.custom ? d.customProviders.find((c) => c.id === p.id) : null;
  const tile = (x) => h("button.provider-opt", { type: "button", class: x.id === d.provider ? "on" : "", on: { click: () => { d.provider = x.id; redraw(); } } },
    h("span.lbl", x.label, x.custom ? h("span.tag", "自定义") : null),
    h("small", x.default_model || (x.examples || [])[0] || (x.base_url || "").replace(/^https?:\/\//, "") || "未设置"));
  const add = h("button.provider-opt.add", { type: "button", on: { click: () => {
    const c = newCustomProvider(d.customProviders.length + 1);
    d.customProviders.push(c);
    d.provider = c.id;
    redraw();
  } } }, h("span.lbl", icon("plus", "sm"), "自定义 API"), h("small", "手动设置地址、模型与密钥"));
  const grid = h("div.provider-grid", allProviders(d).map(tile), add);
  const key = h("input", { type: "password", value: d.keys[p.id] || "", placeholder: p.key_optional ? "（可不填，视服务而定）" : "粘贴 API Key", autocomplete: "off", spellcheck: false });
  key.addEventListener("input", () => { if (key.value.trim()) d.keys[p.id] = key.value.trim(); else delete d.keys[p.id]; });
  const eye = h("button.icon-btn", { type: "button", title: "显示/隐藏", "aria-label": "显示或隐藏密钥", on: { click: () => { key.type = key.type === "password" ? "text" : "password"; } } }, icon("key", "sm"));
  const keyField = h("div.field", h("label", "API Key"), h("div.inline", key, eye),
    h("div.help", p.key_env ? `也可以不在网页里填：本地服务以 --env-keys 启动时，会使用本机环境变量 ${p.key_env}。`
      : custom ? "以 Authorization: Bearer 发送；服务要求别的请求头时（如 api-key），在“高级”里填请求头，这里留空。" : ""));
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
    h("h3", `${ASSISTANT} 的底层模型`),
    h("p.lead", `${AGENT}的模型 ${ASSISTANT}，是 ${AGENT_EN} 研究平台（七十余项检索、考据、发现与核验工具，引文逐字核对）`,
      "加上你在这里选择的底层语言模型——它理解问题、调用工具、组织回答，使用你自己的 API Key。默认 MiniMax 国内站的 MiniMax-M3；",
      "列表之外的服务（自建网关、私有部署、本地模型）点“自定义 API”手动设置。"),
    h("div.form-grid",
      h("div.field", h("span.lb", "服务商"), grid, p.note ? h("div.help", p.note) : null),
      ...(custom ? customFields(custom, d, redraw) : presetFields(p, d)),
      keyField,
      h("div.field", h("span.lb", "请求路径"),
        seg([["auto", "自动"], ["direct", "浏览器直连"], ["proxy", "经本地服务转发"]], d.route, (v) => { d.route = v; }),
        h("div.help", "直连：浏览器直接请求模型服务（需该服务允许跨域）。转发：由 taochronos serve 代为请求，适用于不允许跨域的服务，",
          "也可使用本机环境变量中的密钥（自定义 API 的主机须以 --allow-host 允许）。自动：连着本地服务时转发（自定义 API 直连），否则直连。")),
      h("label.check", think, h("span", "启用思考（MiniMax-M3 默认开启自适应思考；Claude 使用 adaptive thinking）")),
      h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" } },
        field("温度", temp, "留空使用服务商默认值（MiniMax-M3 为 1.0）"),
        field("最大输出（tokens）", maxTok, "含思考内容")),
      h("div", test, result)),
  ];
}

function presetFields(p, d) {
  const model = h("input", { type: "text", list: "model-list", value: d.models[p.id] || p.default_model || "", placeholder: "模型名" });
  model.addEventListener("input", () => { d.models[p.id] = model.value.trim(); });
  const list = h("datalist#model-list", (p.examples || []).map((m) => h("option", { value: m })));
  const base = h("input", { type: "url", value: d.baseUrls[p.id] || "", placeholder: p.base_url });
  base.addEventListener("input", () => { if (base.value.trim()) d.baseUrls[p.id] = base.value.trim(); else delete d.baseUrls[p.id]; });
  return [
    h("div.field", h("label", "模型"), model, list, h("div.help", (p.examples || []).length ? `常用：${p.examples.join("、")}` : "填写服务商提供的模型名")),
    field("接口地址（Base URL）", base, `默认 ${p.base_url}${p.format === "anthropic" ? "（经官方 Anthropic SDK 调用）" : "（OpenAI 兼容接口）"}`),
  ];
}

/** The form of an endpoint set by hand: everything the page needs to call it. */
function customFields(c, d, redraw) {
  const input = (value, placeholder, on, type = "text") => {
    const el = h("input", { type, value: value ?? "", placeholder, spellcheck: false, autocomplete: "off" });
    el.addEventListener("input", () => on(el.value));
    return el;
  };
  const check = (value, on) => {
    const el = h("input", { type: "checkbox", checked: Boolean(value) });
    el.addEventListener("change", () => on(el.checked));
    return el;
  };
  const json = (value, placeholder, on) => {
    const note = h("div.help");
    const ta = h("textarea", { rows: 3, placeholder, spellcheck: false, class: "mono" }, value && Object.keys(value).length ? JSON.stringify(value, null, 1) : "");
    ta.addEventListener("input", () => {
      const raw = ta.value.trim();
      if (!raw) { on({}); note.textContent = ""; return; }
      try {
        const v = JSON.parse(raw);
        if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("须是一个 JSON 对象");
        on(v);
        note.textContent = "";
        note.className = "help";
      } catch (err) {
        note.textContent = `JSON 有误：${err.message}（未采用）`;
        note.className = "help err";
      }
    });
    return [ta, note];
  };
  const anthropic = c.format === "anthropic";
  const base = input(c.base_url, anthropic ? "https://api.example.com" : "https://api.example.com/v1", (v) => { c.base_url = v.trim(); }, "url");
  const [headers, headersNote] = json(c.headers, '{"api-key": "…"}', (v) => { c.headers = v; });
  const [body, bodyNote] = json(c.extra_body, '{"enable_thinking": true}', (v) => { c.extra_body = v; });
  const remove = h("button.btn.secondary", { type: "button", on: { click: () => {
    if (!confirm(`删除「${c.label}」？`)) return;
    d.customProviders = d.customProviders.filter((x) => x !== c);
    delete d.keys[c.id];
    d.provider = DEFAULTS.provider;
    redraw();
  } } }, icon("trash", "sm"), "删除这个 API");
  return [
    h("div.custom-api",
      h("div.field", h("label", "名称"), input(c.label, "给这个 API 起个名字", (v) => { c.label = v.trim() || "自定义 API"; })),
      h("div.field", h("span.lb", "接口格式"),
        seg([["openai", "OpenAI 兼容"], ["anthropic", "Anthropic Messages"]], c.format || "openai", (v) => { c.format = v; redraw(); }),
        h("div.help", anthropic ? "经官方 Anthropic SDK 请求 …/v1/messages（Claude 或兼容 Anthropic 接口的服务）。"
          : "请求 …/chat/completions，流式；模型须支持工具调用（function calling），智能体才能查古籍。")),
      h("div.field", h("label", "接口地址（Base URL）"), base,
        h("div.help", anthropic ? "填到域名或 /v1 为止。" : "填到 /v1 为止（如 https://api.example.com/v1），页面在后面接 /chat/completions。")),
      anthropic ? null : h("label.check", check(c.full_url, (v) => { c.full_url = v; }),
        h("span", "这是完整的请求地址，原样请求（如 Azure OpenAI：…/deployments/名称/chat/completions?api-version=…）")),
      h("div.field", h("label", "模型"), input(c.model, "服务要求的模型名，如 qwen-max、deepseek-chat、my-model", (v) => { c.model = v.trim(); })),
      h("details.more",
        h("summary", "高级：请求头、请求参数、思考与图片"),
        h("div.form-grid", { style: { marginTop: "8px" } },
          h("div.field", h("label", "附加请求头（JSON）"), headers, headersNote),
          anthropic ? null : h("div.field", h("label", "附加请求参数（JSON，并入请求体）"), body, bodyNote),
          anthropic ? null : h("div.field", h("span.lb", "最大输出的参数名"),
            seg([["max_tokens", "max_tokens"], ["max_completion_tokens", "max_completion_tokens"]], c.max_tokens_param || "max_tokens", (v) => { c.max_tokens_param = v; })),
          anthropic ? null : h("div.field", h("span.lb", "思考内容回传"),
            seg([["", "不回传"], ["reasoning_content", "reasoning_content"], ["reasoning_details", "reasoning_details"]], c.reasoning || "", (v) => { c.reasoning = v || null; }),
            h("div.help", "模型流式返回的思考都会显示；多轮对话中是否把它原样传回，依服务要求（MiniMax 类：reasoning_details；多数服务：不回传）。")),
          h("label.check", check(c.vision, (v) => { c.vision = v; }), h("span", "支持图片输入（可附书影）")))),
      h("div", remove)),
  ];
}

// ------------------------------------------------------------------ runtime
const DOC_FULL = "https://github.com/psknlr/TaoChronos/blob/main/docs/web.md#接入全部古籍";

function runtimePane(d, S, ctx, redraw) {
  const info = S.runtimeInfo;
  const url = h("input", { type: "url", value: d.serverUrl, placeholder: DEFAULTS.serverUrl, "aria-label": "服务地址" });
  url.addEventListener("input", () => { d.serverUrl = url.value.trim() || DEFAULTS.serverUrl; });
  const token = h("input", { type: "password", value: d.serverToken || "", placeholder: "本机服务不需要", autocomplete: "off", spellcheck: false, "aria-label": "访问令牌" });
  token.addEventListener("input", () => { d.serverToken = token.value.trim(); });
  const result = h("div.test-result");
  const connect = h("button.btn", { type: "button" }, icon("server", "sm"), "连接");
  connect.addEventListener("click", async () => {
    connect.disabled = true;
    result.className = "test-result";
    result.textContent = "正在连接…";
    const r = await ctx.connectServer(d);
    connect.disabled = false;
    if (r.ok) { redraw(); return; } // the pane shows the new state
    result.className = "test-result err";
    result.textContent = r.message;
    if (r.tokenRequired) token.focus();
  });
  const steps = h("input", { type: "number", min: 1, max: 60, value: d.maxSteps });
  steps.addEventListener("input", () => { d.maxSteps = Number(steps.value) || DEFAULTS.maxSteps; });
  const chars = h("input", { type: "number", min: 2000, max: 200000, step: 1000, value: d.resultChars });
  chars.addEventListener("input", () => { d.resultChars = Number(chars.value) || DEFAULTS.resultChars; });
  const full = info && !info.corpus?.demo;
  const where = info ? `${S.runtime?.label || ""}${S.runtime?.url ? ` ${S.runtime.url.replace(/^https?:\/\//, "")}` : ""}` : "";
  return [
    h("h3", "运行环境"),
    h("p.lead", "TaoChronos 可以在浏览器里运行（Pyodide，要籍语料：按历代引用排序的 350 部要籍中开放授权的百余部原文，开箱即用），",
      "也可以连接 taochronos serve——在你的电脑或服务器上运行，读全部古籍（全量语料）。"),
    info ? h(`div.notice${full ? ".ok" : ""}`, icon(full ? "check" : "info"), h("div.grow",
      h("b", `当前：${where}`), ` · ${ctx.describeRuntime(info)} · 画像 ${info.profile}`,
      info.engine_model ? ` · 研究引擎模型 ${info.engine_model}` : " · 研究引擎：规则（确定性）",
      info.load_ms ? ` · 载入 ${Math.round(info.load_ms / 100) / 10} 秒` : "")) : null,
    h("section.connect",
      h("h4", icon("book", "sm"), full ? "全量语料已接入" : "接入全部古籍"),
      info && S.runtime?.kind === "server" && info.corpus?.kind === "demo"
        ? h("div.notice.warn", icon("warn"), h("div.grow", "已连接的服务还在用演示语料：它所在的机器尚未构建全量语料。按",
          h("a", { href: DOC_FULL, target: "_blank", rel: "noopener" }, "说明"), "构建后重启 taochronos serve 即可。"))
        : null,
      h("ol.steps-list",
        h("li", "在本机构建全量语料（一次；步骤见", h("a", { href: DOC_FULL, target: "_blank", rel: "noopener" }, "说明「接入全部古籍」"), "），然后启动服务：",
          h("pre.json", "pip install -e .\ntaochronos serve            # http://localhost:8765\ntaochronos serve --env-keys # 模型密钥也可用本机环境变量")),
        h("li", "连接它。这个浏览器会记住：以后打开本页，服务在运行就自动用全量语料，没运行就在浏览器内运行（要籍语料）。",
          h("div.connect-row", url, token, connect), result)),
      h("details.more",
        h("summary", "在另一台机器上运行（服务器、工作站）"),
        h("div.help",
          h("pre.json", "taochronos serve --host 0.0.0.0\n# 启动时打印访问令牌，以及带令牌的地址 http://主机:8765/#token=…"),
          h("p", "最简单的是直接打开它打印的地址：服务自带同一个网页，令牌随地址带入。也可以在上面填地址和令牌。"),
          h("p", "本页经 HTTPS 打开（如 GitHub Pages）时，浏览器只允许它连接本机或 https:// 地址：请为服务配置 HTTPS（反向代理），或直接打开服务自己的网页。"),
          h("p", "令牌也可以用 --token 或环境变量 TAOCHRONOS_TOKEN 指定；令牌只随请求发往该服务。")))),
    h("div.form-grid",
      h("div.field", h("span.lb", "在哪里运行"),
        seg([["auto", "自动"], ["browser", "浏览器内（要籍语料）"], ["server", "指定的服务（全量语料）"]], d.runtime, (v) => { d.runtime = v; }),
        h("div.help", "自动：本页由服务打开时用该服务；否则先试这个浏览器连接过的服务，不在就在浏览器内运行。")),
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
    h("h3", `关于${AGENT}`),
    h("p.lead", `${AGENT}（${AGENT_EN}）是${PUBLISHER}（${PUBLISHER_EN}）发布的中医古籍研究智能体，模型名 ${ASSISTANT}。`,
      `${AGENT_EN} 是面向中医古籍的可溯源知识发现与治学系统：确定性的研究平台（检索、考据、发现、核验）负责取证与计算；`,
      "你选择的底层语言模型负责理解问题、调用工具、组织回答。名字取《道德经》“天乃道，道乃久”。"),
    h("div.form-grid",
      h("div.notice", icon("info"), h("div.grow",
        h("div", h("b", "证据纪律："), "回答中的古籍原文应来自工具结果，并以 [[段落号]] 标注出处；页面会把每条引文与原文逐字核对。"),
        h("div", h("b", "非医疗建议："), "本系统不提供诊断、处方或剂量建议；历代度量衡换算只是历史读法。计算得到的关联与假说须经专家核验。"),
        h("div", h("b", "语料："), "浏览器内运行的是要籍语料：按历代引用排序的 350 部要籍（书目见 classics.canon）中有开放授权录本的百余部原文（CC BY-SA 4.0，",
          h("a", { href: "https://github.com/psknlr/TaoChronos/blob/main/corpus/web/ATTRIBUTION.md", target: "_blank", rel: "noopener" }, "来源与授权"),
          "），重要典籍多为全书，其余为章节节选，未经本项目逐字校勘；全部古籍（全量语料）在本机构建，经 taochronos serve 接入（设置 → 运行环境）。"),
        h("div", h("b", "隐私："), "对话与密钥只保存在本浏览器；模型请求直接发往你选择的服务，或经你本机的服务转发。"))),
      h("div.muted", { style: { fontSize: "13px", lineHeight: "1.8" } },
        `${AGENT} · ${ASSISTANT} · ${AGENT_EN} ${info?.version || "?"} · ${PUBLISHED_BY} · 运行环境 ${info?.runtime === "server" ? S.runtime?.label || "服务" : "浏览器（Pyodide）"} · `,
        h("a", { href: "https://github.com/psknlr/TaoChronos", target: "_blank", rel: "noopener" }, "GitHub 仓库"), " · ",
        h("a", { href: "https://github.com/psknlr/TaoChronos/blob/main/docs/web.md", target: "_blank", rel: "noopener" }, "网页端说明"))),
  ];
}
