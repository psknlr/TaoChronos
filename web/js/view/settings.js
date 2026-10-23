// Settings: the model (provider, key, model name, thinking, route), where TaoChronos runs, standing instructions,
// the conversations' data, the site's usage (统计: stats.js), and what this page is.

import { AGENT, AGENT_EN, MODEL as ASSISTANT, PUBLISHED_BY, PUBLISHER, PUBLISHER_EN } from "../brand.js";
import { allProviders, customPreset, DEFAULTS, newCustomProvider, outputLimit, providerById } from "../providers.js";
import { NOTICE } from "../records.js";
import { h, icon, replace } from "../util.js";
import { statsPane } from "./stats.js";
import { T } from "../i18n.js";

const SECTIONS = [
  ["model", T("模型"), "chip"],
  ["runtime", T("运行环境"), "server"],
  ["instructions", T("指令"), "edit"],
  ["data", T("数据"), "download"],
  ["stats", T("统计"), "chart"],
  ["about", T("关于"), "info"],
];

export function openSettings(S, ctx, section = "model") {
  const dlg = document.getElementById("settings");
  let current = section;
  const draft = structuredClone(S.settings);
  const nav = h("nav.settings-nav");
  const pane = h("div.settings-pane");
  const draw = () => {
    nav.replaceChildren(...SECTIONS.map(([id, label, ic]) => h("button", { type: "button", class: id === current ? "on" : "", on: { click: () => { current = id; draw(); } } }, icon(ic, "sm"), label)));
    replace(pane, ({ model: modelPane, runtime: runtimePane, instructions: instructionsPane, data: dataPane, stats: statsPane, about: aboutPane }[current])(draft, S, ctx, draw));
    pane.scrollTop = 0;
  };
  const save = () => { ctx.save(draft); dlg.close(); };
  dlg.replaceChildren(h("div.modal.wide", { role: "document" },
    h("div.modal-head", h("h2", T("设置")), h("button.icon-btn", { type: "button", "aria-label": T("关闭"), on: { click: () => dlg.close() } }, icon("x"))),
    h("div.settings-layout", { style: { minHeight: 0, overflow: "hidden" } }, nav, pane),
    h("div.modal-foot",
      h("span.muted", { style: { flex: 1, fontSize: "12.5px", alignSelf: "center" } }, T("密钥只保存在本浏览器，只发送给所选服务（或你的本地服务）。")),
      h("button.btn.secondary", { type: "button", on: { click: () => dlg.close() } }, T("取消")),
      h("button.btn", { type: "button", on: { click: save } }, T("保存")))));
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
  const sub = (x) => (x.relay ? (x.unavailable ? T("暂时连不上") : T("免密钥 · 直接提问"))
    : x.default_model || (x.examples || [])[0] || (x.base_url || "").replace(/^https?:\/\//, "") || T("未设置"));
  const tiles = new Map();
  const tile = (x) => {
    const el = h("button.provider-opt", { type: "button", class: x.id === d.provider ? "on" : "", on: { click: () => { d.provider = x.id; redraw(); } } },
      h("span.lbl", h("span.name", x.label), x.custom ? h("span.tag", T("自定义")) : x.relay ? h("span.tag", x.unavailable ? T("暂不可用") : T("免密钥")) : null),
      h("small", sub(x)));
    tiles.set(x.id, el);
    return el;
  };
  // the tile of the API being edited follows its form
  const retitle = () => {
    const el = custom && tiles.get(custom.id);
    if (!el) return;
    const x = customPreset(custom);
    el.querySelector(".name").textContent = x.label;
    el.querySelector("small").textContent = sub(x);
  };
  const add = h("button.provider-opt.add", { type: "button", on: { click: () => {
    const c = newCustomProvider(d.customProviders.length + 1);
    d.customProviders.push(c);
    d.provider = c.id;
    redraw();
  } } }, h("span.lbl", icon("plus", "sm"), T("自定义 API")), h("small", T("手动设置地址、模型与密钥")));
  const grid = h("div.provider-grid", allProviders(d).map(tile), add);
  const key = h("input", { type: "password", value: d.keys[p.id] || "", placeholder: p.key_optional ? T("（可不填，视服务而定）") : T("粘贴 API Key"), autocomplete: "off", spellcheck: false });
  key.addEventListener("input", () => { if (key.value.trim()) d.keys[p.id] = key.value.trim(); else delete d.keys[p.id]; });
  const eye = h("button.icon-btn", { type: "button", title: T("显示/隐藏"), "aria-label": T("显示或隐藏密钥"), on: { click: () => { key.type = key.type === "password" ? "text" : "password"; } } }, icon("key", "sm"));
  const keyField = h("div.field", h("label", "API Key"), h("div.inline", key, eye),
    h("div.help", p.key_env ? T`也可以不在网页里填：本地服务以 --env-keys 启动时，会使用本机环境变量 ${p.key_env}。`
      : custom ? T("以 Authorization: Bearer 发送；服务要求别的请求头时（如 api-key），在“高级”里填请求头，这里留空。") : ""));
  const temp = h("input", { type: "number", min: 0, max: 2, step: 0.1, value: d.temperature ?? "", placeholder: T("默认") });
  temp.addEventListener("input", () => { d.temperature = temp.value === "" ? null : Number(temp.value); });
  // left empty, a reply may use what outputLimit decides: the default service's own ceiling, or a default per service
  const maxTok = h("input", { type: "number", min: 256, step: 256, value: d.maxTokens ?? "", placeholder: T`自动（${outputLimit({}, p)}）` });
  maxTok.addEventListener("input", () => { d.maxTokens = Number(maxTok.value) || null; });
  const think = h("input", { type: "checkbox", checked: d.thinking !== false });
  think.addEventListener("change", () => { d.thinking = think.checked; });
  const result = h("div.test-result");
  const test = h("button.btn.secondary", { type: "button" }, icon("bolt", "sm"), T("测试连接"));
  test.addEventListener("click", async () => {
    test.disabled = true;
    result.className = "test-result";
    result.textContent = T("正在请求…");
    const r = await ctx.testModel(d);
    test.disabled = false;
    result.className = `test-result ${r.ok ? "ok" : "err"}`;
    result.textContent = r.message;
  });
  return [
    h("h3", T`${ASSISTANT} 的底层模型`),
    h("p.lead", T`${AGENT}的模型 ${ASSISTANT}，是 ${AGENT_EN} 研究平台（七十余项检索、考据、发现与核验工具，引文逐字核对）`,
      T("加上你在这里选择的底层语言模型——它理解问题、调用工具、组织回答。"),
      S.relay?.ok ? T("默认使用道乃久默认服务（无需 API Key）；也可以选择其他服务，使用你自己的 API Key。")
        : T("使用你自己的 API Key。"),
      T("列表之外的服务（自建网关、私有部署、本地模型）点“自定义 API”手动设置。")),
    h("div.form-grid",
      h("div.field", h("span.lb", T("服务商")), grid, p.note && !p.relay ? h("div.help", p.note) : null), // the default service's in its box
      ...(p.relay ? relayFields(p) : custom ? customFields(custom, d, redraw, retitle) : presetFields(p, d)),
      p.relay ? null : keyField,
      p.relay ? null : h("div.field", h("span.lb", T("请求路径")),
        seg([["auto", T("自动")], ["direct", T("浏览器直连")], ["proxy", T("经本地服务转发")]], d.route, (v) => { d.route = v; }),
        h("div.help", T("直连：浏览器直接请求模型服务（需该服务允许跨域）。转发：由 taochronos serve 代为请求，适用于不允许跨域的服务，"),
          T("也可使用本机环境变量中的密钥（自定义 API 的主机须以 --allow-host 允许）。自动：连着本地服务时转发（自定义 API 直连），否则直连。"))),
      h("label.check", think, h("span", T("启用思考（支持的模型先思考再作答；Claude 使用 adaptive thinking）"))),
      h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" } },
        field(T("温度"), temp, T("留空使用服务商默认值")),
        field(T("最大输出（tokens）"), maxTok, p.max_output ? T`含思考内容；${p.label}每次回复最多 ${p.max_output}` : T("含思考内容"))),
      h("div", test, result)),
  ];
}

function presetFields(p, d) {
  const model = h("input", { type: "text", list: "model-list", value: d.models[p.id] || p.default_model || "", placeholder: T("模型名") });
  model.addEventListener("input", () => { d.models[p.id] = model.value.trim(); });
  const list = h("datalist#model-list", (p.examples || []).map((m) => h("option", { value: m })));
  const base = h("input", { type: "url", value: d.baseUrls[p.id] || "", placeholder: p.base_url });
  base.addEventListener("input", () => { if (base.value.trim()) d.baseUrls[p.id] = base.value.trim(); else delete d.baseUrls[p.id]; });
  return [
    h("div.field", h("label", T("模型")), model, list, h("div.help", (p.examples || []).length ? T`常用：${p.examples.join(T("、"))}` : T("填写服务商提供的模型名"))),
    field(T("接口地址（Base URL）"), base, T`默认 ${p.base_url}${p.format === "anthropic" ? T("（经官方 Anthropic SDK 调用）") : T("（OpenAI 兼容接口）")}`),
  ];
}

/** The form of an endpoint set by hand: everything the page needs to call it. */
function customFields(c, d, redraw, retitle = () => {}) {
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
        if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error(T("须是一个 JSON 对象"));
        on(v);
        note.textContent = "";
        note.className = "help";
      } catch (err) {
        note.textContent = T`JSON 有误：${err.message}（未采用）`;
        note.className = "help err";
      }
    });
    return [ta, note];
  };
  const anthropic = c.format === "anthropic";
  const base = input(c.base_url, anthropic ? "https://api.example.com" : "https://api.example.com/v1", (v) => { c.base_url = v.trim(); retitle(); }, "url");
  const [headers, headersNote] = json(c.headers, '{"api-key": "…"}', (v) => { c.headers = v; });
  const [body, bodyNote] = json(c.extra_body, '{"enable_thinking": true}', (v) => { c.extra_body = v; });
  const remove = h("button.btn.secondary", { type: "button", on: { click: () => {
    if (!confirm(T`删除「${c.label}」？`)) return;
    d.customProviders = d.customProviders.filter((x) => x !== c);
    delete d.keys[c.id];
    d.provider = DEFAULTS.provider;
    redraw();
  } } }, icon("trash", "sm"), T("删除这个 API"));
  return [
    h("div.custom-api",
      h("div.field", h("label", T("名称")), input(c.label, T("给这个 API 起个名字"), (v) => { c.label = v.trim() || T("自定义 API"); retitle(); })),
      h("div.field", h("span.lb", T("接口格式")),
        seg([["openai", T("OpenAI 兼容")], ["anthropic", "Anthropic Messages"]], c.format || "openai", (v) => { c.format = v; redraw(); }),
        h("div.help", anthropic ? T("经官方 Anthropic SDK 请求 …/v1/messages（Claude 或兼容 Anthropic 接口的服务）。")
          : T("请求 …/chat/completions，流式；模型须支持工具调用（function calling），智能体才能查古籍。"))),
      h("div.field", h("label", T("接口地址（Base URL）")), base,
        h("div.help", anthropic ? T("填到域名或 /v1 为止。") : T("填到 /v1 为止（如 https://api.example.com/v1），页面在后面接 /chat/completions。"))),
      anthropic ? null : h("label.check", check(c.full_url, (v) => { c.full_url = v; }),
        h("span", T("这是完整的请求地址，原样请求（如 Azure OpenAI：…/deployments/名称/chat/completions?api-version=…）"))),
      h("div.field", h("label", T("模型")), input(c.model, T("服务要求的模型名，如 qwen-max、deepseek-chat、my-model"), (v) => { c.model = v.trim(); retitle(); })),
      h("details.more",
        h("summary", T("高级：请求头、请求参数、思考与图片")),
        h("div.form-grid", { style: { marginTop: "8px" } },
          h("div.field", h("label", T("附加请求头（JSON）")), headers, headersNote),
          anthropic ? null : h("div.field", h("label", T("附加请求参数（JSON，并入请求体）")), body, bodyNote),
          anthropic ? null : h("div.field", h("span.lb", T("最大输出的参数名")),
            seg([["max_tokens", "max_tokens"], ["max_completion_tokens", "max_completion_tokens"]], c.max_tokens_param || "max_tokens", (v) => { c.max_tokens_param = v; })),
          anthropic ? null : h("div.field", h("span.lb", T("思考内容回传")),
            seg([["", T("不回传")], ["reasoning_content", "reasoning_content"], ["reasoning_details", "reasoning_details"]], c.reasoning || "", (v) => { c.reasoning = v || null; }),
            h("div.help", T("模型流式返回的思考都会显示；多轮对话中是否把它原样传回，依服务要求（有的服务要求以 reasoning_details 原样传回；多数服务：不回传）。"))),
          h("label.check", check(c.vision, (v) => { c.vision = v; }), h("span", T("支持图片输入（可附书影）"))))),
      h("div", remove)),
  ];
}

// ------------------------------------------------------------------ runtime

/** " 535 部" — how many works the 要籍 list holds, as the runtime reports it (nothing before it has answered). */
function canonCount(info) {
  const n = info?.corpus?.canon?.listed;
  return n ? T` ${n} 部` : "";
}

function runtimePane(d, S, ctx, redraw) {
  const info = S.runtimeInfo;
  const url = h("input", { type: "url", value: d.serverUrl, placeholder: DEFAULTS.serverUrl, "aria-label": T("服务地址") });
  url.addEventListener("input", () => { d.serverUrl = url.value.trim() || DEFAULTS.serverUrl; });
  const token = h("input", { type: "password", value: d.serverToken || "", placeholder: T("本机服务不需要"), autocomplete: "off", spellcheck: false, "aria-label": T("访问令牌") });
  token.addEventListener("input", () => { d.serverToken = token.value.trim(); });
  const result = h("div.test-result");
  const connect = h("button.btn", { type: "button" }, icon("server", "sm"), T("连接"));
  connect.addEventListener("click", async () => {
    connect.disabled = true;
    result.className = "test-result";
    result.textContent = T("正在连接…");
    const r = await ctx.connectServer(d);
    connect.disabled = false;
    if (r.ok) { redraw(); return; } // the pane shows the new state: 全量语料已接入, or the warning that the server has only the demonstration corpus
    result.className = "test-result err";
    result.textContent = r.message;
    if (r.tokenRequired) token.focus();
  });
  const steps = h("input", { type: "number", min: 1, max: 60, value: d.maxSteps });
  steps.addEventListener("input", () => { d.maxSteps = Number(steps.value) || DEFAULTS.maxSteps; });
  const chars = h("input", { type: "number", min: 2000, max: 200000, step: 1000, value: d.resultChars });
  chars.addEventListener("input", () => { d.resultChars = Number(chars.value) || DEFAULTS.resultChars; });
  const full = info && !info.corpus?.demo;
  return [
    h("h3", T("运行环境")),
    S.runtime?.label === T("本站服务")
      ? h("p.lead", T("本站服务器（Cloudflare）运行 TaoChronos 的全量语料，打开即用；它暂不可用时，页面自动改在浏览器里运行（Pyodide，要籍语料）。"),
        T("也可以连接你自己运行的 taochronos serve（你构建的全量语料）。"))
      : h("p.lead", T`TaoChronos 可以在浏览器里运行（Pyodide，要籍语料：按历代引用排序的${canonCount(info)}要籍的原文，开箱即用；首次载入后保存在本机），`,
        T("也可以连接 taochronos serve——在你的电脑或服务器上运行，读全部古籍（全量语料）。")),
    h("section.connect",
      h("h4", icon("book", "sm"), full ? T("全量语料已接入") : T("接入全部古籍")),
      info && S.runtime?.kind === "server" && info.corpus?.kind === "demo"
        ? h("div.notice.warn", icon("warn"), h("div.grow", T("已连接的服务还在用演示语料：它所在的机器尚未构建全量语料。按项目文档 docs/web.md"),
          T("「接入全部古籍」构建后重启 taochronos serve 即可。")))
        : null,
      h("ol.steps-list",
        h("li", T("在本机构建全量语料（一次；步骤见项目文档 docs/web.md「接入全部古籍」），然后启动服务："),
          h("pre.json", T("pip install -e .\ntaochronos serve            # http://localhost:8765\ntaochronos serve --env-keys # 模型密钥也可用本机环境变量"))),
        h("li", T("连接它。这个浏览器会记住：以后打开本页，服务在运行就自动用全量语料，没运行就在浏览器内运行（要籍语料）。"),
          h("div.connect-row", url, token, connect), result)),
      h("details.more",
        h("summary", T("在另一台机器上运行（服务器、工作站）")),
        h("div.help",
          h("pre.json", T("taochronos serve --host 0.0.0.0\n# 启动时打印访问令牌，以及带令牌的地址 http://主机:8765/#token=…")),
          h("p", T("最简单的是直接打开它打印的地址：服务自带同一个网页，令牌随地址带入。也可以在上面填地址和令牌。")),
          h("p", T("本页经 HTTPS 打开（如 GitHub Pages）时，浏览器只允许它连接本机或 https:// 地址：请为服务配置 HTTPS（反向代理），或直接打开服务自己的网页。")),
          h("p", T("令牌也可以用 --token 或环境变量 TAOCHRONOS_TOKEN 指定；令牌只随请求发往该服务。"))))),
    h("div.form-grid",
      h("div.field", h("span.lb", T("在哪里运行")),
        seg([["auto", T("自动")], ["browser", T("浏览器内（要籍语料）")], ["server", T("指定的服务（全量语料）")]], d.runtime, (v) => { d.runtime = v; }),
        h("div.help", T("自动：本页由服务打开时用该服务；否则先试这个浏览器连接过的服务，不在就在浏览器内运行。"))),
      h("div.field", h("span.lb", T("提供给模型的工具")),
        seg([["core", T("精选 + 目录（推荐）")], ["all", T("全部工具")]], d.toolMode, (v) => { d.toolMode = v; }),
        h("div.help", T("精选：直接提供十几个最常用的工具，其余通过 taochronos_catalog / taochronos_call 按需查用，节省上下文。全部：七十余个工具全部直接提供。"))),
      h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" } },
        field(T("每轮最多工具步数"), steps, T("达到上限后，模型须根据已有结果作答")),
        field(T("单个工具结果的字符上限"), chars, T("超出部分按结构均匀截短"))),
      h("label.check", (() => { const c = h("input", { type: "checkbox", checked: d.verifyQuotes !== false }); c.addEventListener("change", () => { d.verifyQuotes = c.checked; }); return c; })(),
        h("span", T("逐字核对回答中的引文（与原文比对，标出一致、存疑与查无此段）")))),
  ];
}

// ------------------------------------------------------------------ instructions
function instructionsPane(d, S) {
  const ta = h("textarea", { rows: 7, placeholder: T("例如：回答时先列出原文，再给出白话解释；引用时注明卷次。") }, d.instructions || "");
  ta.addEventListener("input", () => { d.instructions = ta.value; });
  return [
    h("h3", T("指令")),
    h("p.lead", T("附加在系统指令之后，对每次对话生效。系统指令规定了证据纪律（先检索再作答、逐字引用并标注出处、不作医疗建议），不可移除。")),
    h("div.form-grid",
      field(T("我的附加指令"), ta),
      h("details", h("summary", { style: { cursor: "pointer", fontSize: "13.5px", color: "var(--ink-2)" } }, T("查看系统指令")),
        h("pre.json", { style: { maxHeight: "360px", marginTop: "8px" } }, S.runtimeInfo?.system_prompt || T("（运行环境就绪后显示）")))),
  ];
}

// ------------------------------------------------------------------ data
/** 道乃久默认服务: nothing to fill in, and no vendor named. */
function relayFields(p) {
  return [h(`div.notice${p.unavailable ? ".warn" : ".ok"}`, icon(p.unavailable ? "warn" : "check"), h("div.grow", p.note))];
}

function dataPane(d, S, ctx) {
  const file = h("input", { type: "file", accept: "application/json", hidden: true });
  file.addEventListener("change", async () => {
    const f = file.files?.[0];
    if (f) ctx.importAll(await f.text());
    file.value = "";
  });
  const collecting = Boolean(S.relay?.ok && S.relay.logs);
  const agree = h("input", { type: "checkbox", checked: ctx.consent() === true });
  agree.addEventListener("change", () => ctx.setConsent(agree.checked));
  return [
    h("h3", T("数据")),
    h("p.lead", T("对话保存在本浏览器（IndexedDB）。换设备或清理浏览器数据前，请先导出。"),
      collecting ? T("若你同意记录，每轮问答另记录一份到研究院的服务器（见下）；不同意则不会上传。") : T("对话不会上传。")),
    h("div.form-grid",
      collecting ? h("div.field", h("span.lb", T("对话记录（测试期间）")),
        h("label.check", agree, h("span", T("同意记录我的对话，用于测试和改进（立即生效）"))),
        h("div.help", ...NOTICE.map((t) => h("div", t)))) : null,
      h("div.chips",
        h("button.btn.secondary", { type: "button", on: { click: ctx.exportAll } }, icon("download", "sm"), T("导出全部对话（JSON）")),
        h("button.btn.secondary", { type: "button", on: { click: () => file.click() } }, icon("upload", "sm"), T("导入对话")), file,
        S.conv ? h("button.btn.secondary", { type: "button", on: { click: () => ctx.exportMarkdown(S.conv) } }, icon("download", "sm"), T("导出当前对话（Markdown）")) : null),
      h("div.chips",
        h("button.btn.secondary", { type: "button", on: { click: () => { d.keys = {}; ctx.toast(T("已清除表单中的全部密钥，保存后生效")); } } }, icon("key", "sm"), T("清除所有 API Key")),
        h("button.btn.danger", { type: "button", on: { click: ctx.clearAll } }, icon("trash", "sm"), T("删除全部对话")))),
  ];
}

// ------------------------------------------------------------------ about
function aboutPane(d, S) {
  const info = S.runtimeInfo;
  return [
    h("h3", T`关于${AGENT}`),
    h("p.lead", T`${AGENT}（${AGENT_EN}）是${PUBLISHER}（${PUBLISHER_EN}）发布的中医古籍研究智能体，模型名 ${ASSISTANT}。`,
      T`${AGENT_EN} 是面向中医古籍的可溯源知识发现与治学系统：确定性的研究平台（检索、考据、发现、核验）负责取证与计算；`,
      T("你选择的底层语言模型负责理解问题、调用工具、组织回答。名字取《道德经》“天乃道，道乃久”。")),
    h("div.form-grid",
      h("div.notice", icon("info"), h("div.grow",
        h("div", h("b", T("证据纪律：")), T("回答中的古籍原文应来自工具结果，并以 [[段落号]] 标注出处；页面会把每条引文与原文逐字核对。")),
        h("div", h("b", T("非医疗建议：")), T("本系统不提供诊断、处方或剂量建议；历代度量衡换算只是历史读法。计算得到的关联与假说须经专家核验。")),
        h("div", h("b", T("隐私：")), T("对话与密钥保存在本浏览器。使用道乃久默认服务时，你的问题经"), PUBLISHER, T("的服务交由大语言模型处理，该服务不保存请求内容；"),
          T("只有在你同意后，每轮问答才另记录一份到"), PUBLISHER, T("的服务器，用于测试（设置 → 数据）。使用自己的 API Key 时，请求直接发往你选择的服务，或经你本机的服务转发。")))),
      h("div.muted", { style: { fontSize: "13px", lineHeight: "1.8" } },
        T`${AGENT} · ${ASSISTANT} · ${AGENT_EN} ${info?.version || "?"} · ${PUBLISHED_BY} · 运行环境 ${info?.runtime === "server" ? S.runtime?.label || T("服务") : T("浏览器")}`)),
  ];
}
