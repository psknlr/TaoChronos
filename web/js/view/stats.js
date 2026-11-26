// The 统计 pane of the settings: how much the site is used and from where — the pages opened and their visitors (the
// site's counts, /api/stats) and the questions asked of 道乃久默认服务 and who asked (the relay's, /v1/stats) — over the
// last 7, 30 or 90 days, all of them, or the days between two dates, by country and by China's provinces
// (security/usage.js; docs/web.md).  Where the site keeps an activity ledger (security/ledger.js, /api/activity/stats),
// its counts come first: the different visitors of the whole stretch (never the days' counts added up), their visits,
// every question — recorded or not, whoever answered —, the model calls and their tokens, who came back, and what the
// site's features are used for.  The counts are read with a token kept in this browser only; no address is ever among
// them.
// Charts are drawn here as SVG: one validated blue for the marks (--viz-1), the page's own ink and lines for the rest;
// one series a chart (a card that can show several lets the reader choose which), every chart also a table.

import { h, icon, storage } from "../util.js";
import { LOCALE, T } from "../i18n.js";

const TOKEN_KEY = "tc.statsToken";
const RANGES = [[7, T("近 7 天")], [30, T("近 30 天")], [90, T("近 90 天")], ["all", T("全部")]];
const SVG = "http://www.w3.org/2000/svg";
const ALL_DAYS = 366; // the daily counts keep a year and a month: "all" of them is the last 366 days
// days: 7 | 30 | 90 | "all" | "custom" (from … to); data, ledger: the last counts, kept on screen, dimmed, while the
// next arrive; what each card that can show several things shows
const state = { days: 30, from: "", to: "", data: null, ledger: null, noLedger: false, trend: "active", use: "tools", who: "devices" };
const DAY = /^\d{4}-\d{2}-\d{2}$/;

// China's first-level divisions by their ISO 3166-2 codes, as Cloudflare gives them
const PROVINCES = {
  AH: T("安徽"), BJ: T("北京"), CQ: T("重庆"), FJ: T("福建"), GD: T("广东"), GS: T("甘肃"), GX: T("广西"), GZ: T("贵州"), HA: T("河南"), HB: T("湖北"), HE: T("河北"),
  HI: T("海南"), HK: T("香港"), HL: T("黑龙江"), HN: T("湖南"), JL: T("吉林"), JS: T("江苏"), JX: T("江西"), LN: T("辽宁"), MO: T("澳门"), NM: T("内蒙古"), NX: T("宁夏"),
  QH: T("青海"), SC: T("四川"), SD: T("山东"), SH: T("上海"), SN: T("陕西"), SX: T("山西"), TJ: T("天津"), TW: T("台湾"), XJ: T("新疆"), XZ: T("西藏"), YN: T("云南"), ZJ: T("浙江"),
};
let regionNames = null;
const countryName = (code) => {
  if (!code || code === "XX") return T("未知");
  try { regionNames ||= new Intl.DisplayNames([LOCALE], { type: "region" }); return regionNames.of(code) || code; } catch { return code; }
};
const provinceName = (code) => PROVINCES[code] || code || T("未知");
const fmt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString(LOCALE));
let compact = null;
/** A large number in a few characters (1.2M), in the page's language. */
const short = (n) => {
  if (n === null || n === undefined) return "—";
  try { compact ||= new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 }); return compact.format(n); } catch { return fmt(n); }
};
const pct = (part, whole) => (whole > 0 ? `${Math.round((part / whole) * 100)}%` : "—");
const span = (seconds) => (seconds < 60 ? T`${Math.round(seconds)} 秒` : seconds < 3600 ? T`${Math.round(seconds / 60)} 分钟` : T`${(seconds / 3600).toFixed(1)} 小时`);
const shortDay = (d) => d.slice(5);
const longDay = (d) => T`${Number(d.slice(5, 7))}月${Number(d.slice(8, 10))}日`;

/** The pane: built at once, filled when the counts arrive. */
export function statsPane(d, S) {
  const root = h("div.stats");
  render(root, S);
  return root;
}

async function render(root, S) {
  const token = storage.get(TOKEN_KEY, "");
  if ((state.data || state.ledger) && root.childElementCount) root.classList.add("busy"); // the last counts stay, dimmed
  else root.replaceChildren(h("h3", T("统计")), h("p.lead", T("正在读取统计……")));
  const relay = S.relay?.url || "";
  // the daily counts reach back from today: of a stretch that ends earlier there are none to show
  const today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
  const custom = state.days === "custom";
  const back = custom ? (state.to && state.to < today ? 0 : Math.round((Date.parse(today) - Date.parse(state.from)) / 86400000) + 1) : state.days === "all" ? ALL_DAYS : state.days;
  const days = Math.min(Math.max(back, 0), ALL_DAYS);
  const query = custom ? `from=${state.from}${state.to ? `&to=${state.to}` : ""}` : state.days === "all" ? "range=all" : `days=${state.days}`;
  // (a site without a ledger says so once: it is not asked again by this page)
  const [site, rel, led] = await Promise.all([days ? read(`api/stats?days=${days}`, token) : null, relay && days ? read(`${relay}/v1/stats?days=${days}`, token) : null,
    state.noLedger ? null : read(`api/activity/stats?${query}`, token)]);
  if (led?.status === 404) state.noLedger = true;
  root.classList.remove("busy");
  const ok = (r) => r && r.status === 200 && r.body && Array.isArray(r.body.days);
  const ledger = ok(led) && led.body.totals ? led.body : null;
  if (!ok(site) && !ok(rel) && !ledger) return root.replaceChildren(...closed(root, S, site || led, rel, token).filter(Boolean));
  state.data = ok(site) || ok(rel) ? merge(ok(site) ? site.body : null, ok(rel) ? rel.body : null) : null;
  state.ledger = ledger;
  const has = { site: ok(site), relay: ok(rel), relayAsked: Boolean(relay), days };
  root.replaceChildren(...[h("h3", T("统计")), filters(root, S, token), ...(ledger ? ledgerView(ledger) : []),
    ...(state.data ? dashboard(state.data, has, Boolean(ledger)) : ledger ? [] : [h("div.notice", icon("info"), h("div.grow", T("这段时间没有按日计数：它只从今天往前数。")))])]
    .filter(Boolean)); // replaceChildren writes a null as "null"
}

async function read(url, token) {
  try {
    const r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: "no-store" });
    let body = null;
    try { body = await r.json(); } catch { /* not JSON: no counts here */ }
    return { status: r.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

/** The site's kinds from the site, the relay's from the relay; a side that did not answer is null (shown as —). */
function merge(site, relay) {
  const base = site || relay;
  const from = { view: site, visitor: site, question: relay, call: relay, asker: relay };
  const pick = (k, part) => (from[k] ? from[k][part][k] : null);
  const out = { days: base.days, asOf: base.asOf, offset: base.offset, daily: {}, totals: {}, previous: {}, today: {} };
  for (const k of Object.keys(from)) {
    out.daily[k] = from[k] ? base.days.map((day) => from[k].daily[k][from[k].days.indexOf(day)] ?? 0) : null;
    out.totals[k] = pick(k, "totals");
    out.previous[k] = pick(k, "previous");
    out.today[k] = pick(k, "today");
  }
  const places = new Map();
  for (const [src, kinds] of [[site, ["view", "visitor"]], [relay, ["question", "call", "asker"]]]) {
    for (const p of src?.places || []) {
      const key = `${p.country}|${p.region}`;
      if (!places.has(key)) places.set(key, { country: p.country, region: p.region, view: 0, visitor: 0, question: 0, call: 0, asker: 0 });
      for (const k of kinds) places.get(key)[k] += Number(p[k]) || 0;
    }
  }
  out.places = [...places.values()];
  out.has = { site: Boolean(site), relay: Boolean(relay) };
  return out;
}

// ------------------------------------------------------------------ when the counts cannot be read
// A visitor is told no more than that they are not open, or asked for the token; how they are opened is in the docs.
function closed(root, S, site, rel, token) {
  const bodies = [site?.body, rel?.body].filter(Boolean);
  const unset = bodies.some((b) => b.configured === false) && !bodies.some((b) => b.configured === true);
  const asked = bodies.some((b) => b.token_required);
  const head = h("h3", T("统计"));
  if (!asked || unset) return [head, h("div.notice", icon("info"), h("div.grow", T("统计尚未开放。")))];
  const input = h("input", { type: "password", autocomplete: "off", spellcheck: "false", "aria-label": T("统计令牌") });
  const go = () => {
    const v = input.value.trim();
    if (!v) return input.focus();
    storage.set(TOKEN_KEY, v);
    render(root, S);
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  return [head,
    h("div.form-grid",
      h("div.field", h("label", T("统计令牌")),
        h("div.inline", input, h("button.btn", { type: "button", on: { click: go } }, T("查看"))),
        token ? h("div.help.err", T("令牌不对，请重新输入。")) : null))];
}

// ------------------------------------------------------------------ the stretch of days
function filters(root, S, token) {
  const go = (next) => { Object.assign(state, next); render(root, S); };
  const range = h("div.seg", { role: "radiogroup", "aria-label": T("时间范围") });
  for (const [n, label] of RANGES) {
    range.append(h("button", { type: "button", role: "radio", "aria-checked": String(n === state.days), class: n === state.days ? "on" : "",
      on: { click: () => { if (state.days !== n) go({ days: n }); } } }, label));
  }
  // between two dates: the first is needed, the last is today when left empty
  const from = h("input", { type: "date", value: state.from, "aria-label": T("起始日期") });
  const to = h("input", { type: "date", value: state.to, "aria-label": T("结束日期") });
  const between = () => {
    if (!DAY.test(from.value)) return from.focus();
    go({ days: "custom", from: from.value, to: DAY.test(to.value) && to.value >= from.value ? to.value : "" });
  };
  for (const input of [from, to]) input.addEventListener("keydown", (e) => { if (e.key === "Enter") between(); });
  // (a stretch between two dates is the ledger's alone: the daily counts reach back from today only)
  return h("div.stats-filters", range,
    state.noLedger ? null : h("span.stats-dates", { class: state.days === "custom" ? "on" : "" }, from, h("span.muted", "–"), to,
      h("button.btn-ghost", { type: "button", on: { click: between } }, T("查看"))),
    h("button.btn-ghost", { type: "button", title: T("重新读取"), on: { click: () => render(root, S) } }, icon("redo", "sm"), T("刷新")),
    token ? h("button.btn-ghost", { type: "button", title: T("在本浏览器忘记统计令牌"), on: { click: () => { storage.remove(TOKEN_KEY); state.data = null; state.ledger = null; render(root, S); } } },
      icon("key", "sm"), T("忘记令牌")) : null);
}

// ------------------------------------------------------------------ the daily counts
function dashboard(data, has, under) {
  const period = T`较前 ${has.days} 天`;
  const tiles = h("div.stat-tiles",
    tile(T("页面访问"), data, "view", period),
    tile(T("访客"), data, "visitor", period, T("每日去重")),
    tile(T("提问"), data, "question", period, data.totals.call === null ? null : T`模型调用 ${fmt(data.totals.call)} 次`),
    tile(T("提问的人"), data, "asker", period, T("每日去重")));
  const trends = h("div.viz-grid",
    data.daily.view ? lineCard(T("每日页面访问"), data.days, data.daily.view, T("页面访问")) : null,
    data.daily.question ? lineCard(T("每日提问"), data.days, data.daily.question, T("提问")) : null);
  const metric = data.has.site ? "view" : "question";
  const metricName = metric === "view" ? T("页面访问") : T("提问");
  const byCountry = new Map();
  for (const p of data.places) {
    const c = byCountry.get(p.country) || { country: p.country, region: "", view: 0, visitor: 0, question: 0, call: 0, asker: 0 };
    for (const k of ["view", "visitor", "question", "call", "asker"]) c[k] += p[k];
    byCountry.set(p.country, c);
  }
  const countries = [...byCountry.values()].map((p) => ({ label: countryName(p.country), p }));
  const provinces = data.places.filter((p) => p.country === "CN").map((p) => ({ label: provinceName(p.region), p }));
  const regions = h("div.viz-grid",
    barCard(T("国家/地区"), countries, metric, metricName, 8),
    barCard(T("中国各省份"), provinces, metric, metricName, 10));
  const missing = !data.has.site ? T("网站的计数没有读到（页面访问、访客显示为 —）。") : has.relayAsked && !data.has.relay ? T("默认服务的计数没有读到（提问显示为 —）。") : "";
  return [
    // under the ledger's counts these are the older ones: by the day, a visitor counted anew each day
    under ? h("h4.stats-part", T("按日计数")) : null,
    h("p.lead", T`截至 ${longDay(data.asOf)}（北京时间）：网页打开的次数与访客、向道乃久默认服务提的问题，以及来自哪些国家和省份。`),
    missing ? h("div.notice", icon("info"), h("div.grow", missing)) : null,
    tiles,
    trends,
    regions,
    h("p.stats-note",
      T("说明：地区按 Cloudflare 对访问来源的判断（国家与省级行政区），本站不记录网络地址；访客按日去重；页面访问只计浏览器打开网页，"),
      T("不含爬虫与脚本；提问只计道乃久默认服务（使用自己的 API Key 时不经本站，不计入）；日期按北京时间。")),
  ];
}

/** A stat tile: the label, the number over the range, its change against the range before, and today's. */
function tile(label, data, kind, period, note = null) {
  const v = data.totals[kind];
  const prev = data.previous[kind];
  let delta = null;
  if (v !== null && prev !== null) {
    if (prev === 0) delta = v > 0 ? h("span.delta", T`${period}：新增`) : h("span.delta", T`${period}：持平`);
    else {
      const pct = Math.round(((v - prev) / prev) * 100);
      delta = pct === 0 ? h("span.delta", T`${period}：持平`)
        : h(`span.delta.${pct > 0 ? "up" : "down"}`, `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}%`, h("span.muted", ` ${period}`));
    }
  }
  return h("div.stat-tile",
    h("div.label", label),
    h("div.value", fmt(v)),
    delta,
    h("div.sub", T`今天 ${fmt(data.today[kind])}`, note ? ` · ${note}` : ""));
}

// ------------------------------------------------------------------ cards, tooltips, tables
function card(title, chart, table) {
  let showTable = false;
  const body = h("div.viz-body");
  const toggle = h("button.btn-ghost.viz-toggle", { type: "button", "aria-pressed": "false" }, T("表格"));
  const show = () => {
    body.replaceChildren(showTable ? table() : chart);
    toggle.textContent = showTable ? T("图表") : T("表格");
    toggle.setAttribute("aria-pressed", String(showTable));
  };
  toggle.addEventListener("click", () => { showTable = !showTable; show(); });
  show();
  return h("figure.viz-card", h("figcaption", h("span.title", title), toggle), body);
}

function table(head, rows) {
  return h("div.viz-table-wrap", h("table.viz-table",
    h("thead", h("tr", ...head.map((t, i) => h(i ? "th.num" : "th", t)))),
    h("tbody", ...rows.map((r) => h("tr", ...r.map((c, i) => h(i ? "td.num" : "td", typeof c === "number" ? fmt(c) : c)))))));
}

function tip(host) {
  const el = h("div.viz-tip", { role: "status", "aria-live": "polite", hidden: true });
  host.append(el);
  return {
    show(lines, x, y) {
      el.replaceChildren(...lines.map(([value, name]) => h("div.row", h("b", value), h("span", name))));
      el.hidden = false;
      const w = host.clientWidth;
      const tw = el.offsetWidth;
      el.style.left = `${Math.max(4, Math.min(w - tw - 4, x - tw / 2))}px`;
      el.style.top = `${Math.max(0, y - el.offsetHeight - 10)}px`;
    },
    hide() { el.hidden = true; },
  };
}

const svg = (tag, attrs = {}, ...children) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, String(v));
  for (const c of children) if (c) el.append(c);
  return el;
};

/** The top of a scale: a round number at or above the largest value. */
function niceMax(v) {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

// ------------------------------------------------------------------ a day-by-day line
function lineCard(title, days, values, name) {
  const host = h("div.viz-line");
  const watch = new ResizeObserver(() => { if (host.isConnected) drawLine(host, days, values, name); else if (drawn) watch.disconnect(); });
  let drawn = false;
  const draw = () => { drawn = true; drawLine(host, days, values, name); };
  watch.observe(host);
  queueMicrotask(draw); // the observer fires once the card is in the page; a pane closed before then lets it go
  return card(title, host, () => table([T("日期"), name], days.map((d, i) => [longDay(d), values[i]]).reverse()));
}

function drawLine(host, days, values, name) {
  const width = Math.max(240, host.clientWidth || 0);
  if (host.dataset.w === String(width)) return;
  host.dataset.w = String(width);
  const H = 150, top = 14, bottom = 22, left = 34, right = 14;
  const pw = width - left - right, ph = H - top - bottom;
  const max = niceMax(Math.max(...values, 0));
  const n = values.length;
  const x = (i) => left + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
  const y = (v) => top + ph - (v / max) * ph;
  const grid = [0, max / 2, max].filter((t) => Number.isInteger(t)).map((t) => svg("g", {},
    svg("line", { x1: left, x2: width - right, y1: y(t), y2: y(t), class: t === 0 ? "axis" : "grid" }),
    svg("text", { x: left - 6, y: y(t) + 4, "text-anchor": "end", class: "tick" }, document.createTextNode(fmt(Math.round(t))))));
  const labels = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i && n > 1)
    .map((i) => svg("text", { x: x(i), y: H - 6, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle", class: "tick" },
      document.createTextNode(shortDay(days[i]))));
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = svg("path", { d: `M${pts.join("L")}`, class: "line" });
  const area = svg("path", { d: `M${x(0).toFixed(1)},${y(0)}L${pts.join("L")}L${x(n - 1).toFixed(1)},${y(0)}Z`, class: "area" });
  const last = n - 1;
  const end = svg("circle", { cx: x(last), cy: y(values[last]), r: 4, class: "dot" });
  const endLabel = svg("text", { x: x(last) - 6, y: y(values[last]) - 9, "text-anchor": "end", class: "end" }, document.createTextNode(fmt(values[last])));
  const cross = svg("line", { y1: top, y2: top + ph, class: "cross", visibility: "hidden" });
  const hoverDot = svg("circle", { r: 4, class: "dot", visibility: "hidden" });
  const hit = svg("rect", { x: left, y: top, width: pw, height: ph, class: "hit" });
  const chart = svg("svg", { width, height: H, viewBox: `0 0 ${width} ${H}`, role: "img", tabindex: 0,
    "aria-label": T`${name}，${days.length} 天，最近一天 ${fmt(values[last])}；可切换表格查看每天的数字` },
  area, ...grid, ...labels, line, end, endLabel, cross, hoverDot, hit);
  host.replaceChildren(chart);
  const tooltip = tip(host);
  let at = -1;
  const show = (i) => {
    at = Math.max(0, Math.min(n - 1, i));
    for (const [el, k] of [[cross, "x1"], [cross, "x2"]]) el.setAttribute(k, x(at));
    cross.setAttribute("visibility", "visible");
    hoverDot.setAttribute("cx", x(at));
    hoverDot.setAttribute("cy", y(values[at]));
    hoverDot.setAttribute("visibility", "visible");
    tooltip.show([[fmt(values[at]), `${name} · ${longDay(days[at])}`]], x(at), y(values[at]));
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); hoverDot.setAttribute("visibility", "hidden"); tooltip.hide(); };
  hit.addEventListener("pointermove", (e) => {
    const box = chart.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * width;
    show(n === 1 ? 0 : Math.round(((px - left) / pw) * (n - 1)));
  });
  hit.addEventListener("pointerleave", hide);
  chart.addEventListener("focus", () => show(at < 0 ? last : at));
  chart.addEventListener("blur", hide);
  chart.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); show((at < 0 ? last : at) + (e.key === "ArrowLeft" ? -1 : 1)); }
  });
}

// ------------------------------------------------------------------ places as bars
function barCard(title, rows, metric, metricName, top) {
  const sorted = rows.filter((r) => r.p[metric] > 0 || r.p.question > 0 || r.p.view > 0).sort((a, b) => (b.p[metric] - a.p[metric]) || (b.p.question - a.p.question));
  const shown = sorted.slice(0, top);
  const rest = sorted.slice(top);
  if (rest.length) {
    const other = { country: "", region: "", view: 0, visitor: 0, question: 0, call: 0, asker: 0 };
    for (const r of rest) for (const k of Object.keys(other)) if (typeof other[k] === "number") other[k] += r.p[k];
    shown.push({ label: T`其他 ${rest.length} 处`, p: other });
  }
  const host = h("div.hbars");
  const tooltip = tip(host);
  if (!shown.length) host.append(h("div.viz-empty", T("这段时间还没有数据")));
  const max = Math.max(1, ...shown.map((r) => r.p[metric]));
  for (const r of shown) {
    const v = r.p[metric];
    const lines = [[fmt(r.p.view), T("页面访问")], [fmt(r.p.visitor), T("访客")], [fmt(r.p.question), T("提问")], [fmt(r.p.asker), T("提问的人")]];
    const row = h("div.hbar", { tabindex: 0, role: "listitem", "aria-label": T`${r.label}：${lines.map(([v2, n]) => `${n} ${v2}`).join(T("，"))}` },
      h("span.name", { title: r.label }, r.label),
      h("span.track", h("i", { style: { width: v > 0 ? `max(2px, ${(v / max) * 100}%)` : "0" } })),
      h("span.val", fmt(v)));
    const show = () => {
      const box = row.getBoundingClientRect();
      const hb = host.getBoundingClientRect();
      tooltip.show([[r.label, ""], ...lines], box.left - hb.left + box.width / 2, box.top - hb.top);
    };
    row.addEventListener("pointerenter", show);
    row.addEventListener("pointerleave", () => tooltip.hide());
    row.addEventListener("focus", show);
    row.addEventListener("blur", () => tooltip.hide());
    host.append(row);
  }
  host.setAttribute("role", "list");
  host.setAttribute("aria-label", T`${title}，按${metricName}排列`);
  return card(T`${title} · 按${metricName}`, host,
    () => table([T("地区"), T("页面访问"), T("访客"), T("提问"), T("提问的人")], sorted.map((r) => [r.label, r.p.view, r.p.visitor, r.p.question, r.p.asker])));
}

// ------------------------------------------------------------------ the activity ledger's counts
// what the ledger's own words are on the page
const CLASSES = { human: T("访客的浏览器"), suspect: T("被标记的浏览器"), crawler: T("爬虫"), automation: T("脚本与扫描器"), own: T("本项目自己的检查"),
  cross_site: T("别的网站的页面带来的"), unknown: T("其他") };
const ACTIONS = { flagged: T("已标记"), shadow: T("本应拒绝"), blocked: T("已拒绝"), honeypot: T("扫描器路径"), rate_limited: T("超出限额"), cross_site: T("跨站请求，已拒绝") };
const DEVICES = { desktop: T("电脑"), mobile: T("手机"), tablet: T("平板"), other: T("其他") };
const MODULES = { chat: T("古籍问答"), diet: T("饮食与体重管理"), mydata: T("分析我的资料"), research: T("研究"), "": T("未说明") };
const PROVIDERS = { impf: T("道乃久默认服务"), fixed: T("网页自己的回复"), custom: T("自设的接口"), other: T("其他") };
const LENGTHS = { "0-10s": T("不到 10 秒"), "10-60s": T("10 秒至 1 分钟"), "1-5m": T("1 至 5 分钟"), "5-15m": T("5 至 15 分钟"), "15-60m": T("15 分钟至 1 小时"), "60m+": T("1 小时以上") };
const TRENDS = [["active", T("每日活跃访客")], ["active_7", T("7 日活跃访客")], ["active_30", T("30 日活跃访客")], ["new_visitors", T("每日新访客")],
  ["page_views", T("每日页面访问")], ["sessions", T("每日访问次数")], ["questions", T("每日提问")], ["model_calls", T("每日模型调用")]];
const named = (map, key) => map[key] || key || T("未知");
/** A model as the ledger names it: the default service's by its own name, a visitor's own by its service. */
const modelName = (provider, model) => (provider === "impf" ? model || PROVIDERS.impf : model ? `${named(PROVIDERS, provider)} · ${model}` : named(PROVIDERS, provider));

function ledgerView(L) {
  const t = L.totals;
  const tokens = t.tokens_in + t.tokens_out;
  const tiles = h("div.stat-tiles.nine",
    kpi(T("访客"), t.visitors, T`新访客 ${fmt(t.new_visitors)}`),
    kpi(T("访问次数"), t.visits, t.visitors ? T`每位访客 ${(t.visits / t.visitors).toFixed(1)} 次` : null),
    kpi(T("页面访问"), t.page_views, T`${pct(L.coverage.page_views_identified, t.page_views)} 有访客编号`),
    kpi(T("提问"), t.questions, T`已存档 ${fmt(t.questions_archived)}`),
    kpi(T("未存档的提问"), t.questions_unarchived, T`占提问的 ${pct(t.questions_unarchived, t.questions)}`),
    kpi(T("模型调用"), t.model_calls, T`默认服务 ${fmt(t.model_calls_relay)} · 自备模型 ${fmt(t.model_calls_reported)}`),
    kpi(T("Token 用量"), tokens, T`输入 ${short(t.tokens_in)} · 输出 ${short(t.tokens_out)}`, short(tokens)),
    kpi(T("回访的访客"), t.returning_visitors, T`占访客的 ${pct(t.returning_visitors, t.visitors)}`),
    kpi(T("国家/地区"), t.countries, T`省级地区 ${fmt(t.regions)}`));
  const lines = (p) => [[fmt(p.visitors), T("访客")], [fmt(p.page_views), T("页面访问")], [fmt(p.questions), T("提问")]];
  const provinces = L.places.filter((p) => p.country === "CN" && !p.folded).map((p) => ({ label: provinceName(p.region), value: p.visitors, lines: lines(p) }));
  const byCountry = new Map();
  for (const p of L.places) {
    const key = p.folded ? "" : p.country;
    const c = byCountry.get(key) || { country: p.country, region: "", visitors: 0, page_views: 0, questions: 0, folded: p.folded };
    c.visitors += p.visitors; c.page_views += p.page_views; c.questions += p.questions;
    byCountry.set(key, c);
  }
  const countries = [...byCountry.values()].map((p) => ({ label: p.folded ? T`其他 ${p.folded} 处` : countryName(p.country), value: p.visitors, lines: lines(p) }));
  const columns = [T("访客"), T("页面访问"), T("提问")];
  const use = {
    tools: [T("工具（调用次数）"), L.features.tools.map(([k, v]) => ({ label: k, value: v }))],
    models: [T("模型（提问数）"), L.questions.by_model.map(([p, m, v]) => ({ label: modelName(p, m), value: v }))],
    modules: [T("板块（提问数）"), L.questions.by_module.map(([k, v]) => ({ label: named(MODULES, k), value: v }))],
    runtimes: [T("运行环境与语料（提问数）"), L.features.runtimes.map(([r, c, v]) => ({ label: [r, c].filter(Boolean).join(" · "), value: v }))],
    refusals: [T("被限额拒绝的调用"), L.questions.refusals.map(([k, v]) => ({ label: k, value: v }))],
  };
  const who = {
    devices: [T("设备（页面访问）"), L.audience.devices.map(([k, v]) => ({ label: named(DEVICES, k), value: v }))],
    browsers: [T("浏览器（页面访问）"), L.audience.browsers.map(([k, v]) => ({ label: k, value: v }))],
    systems: [T("系统（页面访问）"), L.audience.systems.map(([k, v]) => ({ label: k, value: v }))],
    languages: [T("浏览器语言（页面访问）"), L.audience.languages.map(([k, v]) => ({ label: k || T("未知"), value: v }))],
    referrers: [T("来自哪些网站（页面访问）"), L.audience.referrers.map(([k, v]) => ({ label: k.replace(/^https?:\/\//, ""), value: v }))],
  };
  const visits = L.sessions;
  return [
    h("p.lead", T`活动账本，${longDay(L.from)} 至 ${longDay(L.to)}（北京时间）`, L.first_day ? T`；自 ${longDay(L.first_day)} 起累计访客 ${fmt(L.lifetime.visitors)} 位` : "",
      T("。访客按匿名编号计，整段时间内去重，不是把每天的人数相加。")),
    tiles,
    h("div.viz-grid",
      choiceCard(TRENDS, "trend", (key) => lineBody(L.days, L.daily[key], TRENDS.find(([k]) => k === key)[1]),
        (key) => table([T("日期"), TRENDS.find(([k]) => k === key)[1]], L.days.map((d, i) => [longDay(d), L.daily[key][i]]).reverse())),
      retentionCard(L.retention)),
    h("div.viz-grid",
      rankCard(T("国家/地区 · 按访客"), countries, { top: 8, columns }),
      rankCard(T("中国各省份 · 按访客"), provinces, { top: 10, columns })),
    h("div.viz-grid",
      choiceCard(Object.entries(use).map(([k, [name]]) => [k, name]), "use", (key) => rankBody(use[key][1], { top: 10 }), (key) => table([T("名称"), T("次数")], use[key][1].map((r) => [r.label, r.value]))),
      choiceCard(Object.entries(who).map(([k, [name]]) => [k, name]), "who", (key) => rankBody(who[key][1], { top: 8 }), (key) => table([T("名称"), T("次数")], who[key][1].map((r) => [r.label, r.value])))),
    h("div.viz-grid",
      rankCard(T("每次访问的时长"), visits.lengths.map(([k, v]) => ({ label: named(LENGTHS, k), value: v })), { top: 6, ordered: true,
        sub: visits.count ? T`中位数 ${span(visits.median_s)} · 平均 ${span(visits.seconds / visits.count)}` : null }),
      factsCard(T("请求的类别与数据的完整度"), [
        ...L.security.classes.map(([k, v]) => [named(CLASSES, k), fmt(v)]),
        ...L.security.actions.filter(([k]) => k && k !== "none").map(([k, v]) => [named(ACTIONS, k), fmt(v)]),
        [T("网页加载后自报的页面访问"), `${fmt(L.coverage.page_ready)}（${pct(L.coverage.page_ready, t.page_views)}）`],
        [T("发出后没有带回的访客编号"), fmt(L.coverage.unconfirmed)],
        [T("提问的来源：默认服务 / 网页自报 / 对话记录"), [L.coverage.questions_relay, L.coverage.questions_client, L.coverage.questions_record].map(fmt).join(" / ")],
        L.coverage.pending_days ? [T("尚未汇总的天数"), fmt(L.coverage.pending_days)] : null,
        L.lifetime.removed ? [T("已删除的访客（按本人要求或到期）"), fmt(L.lifetime.removed)] : null,
      ].filter(Boolean))),
    h("p.stats-note", T("说明：访客是浏览器带回过一次的匿名编号（发出后再没带回的不算）；一次访问是同一访客间隔不超过 30 分钟的连续活动；"),
      T("提问按轮计，一轮无论调用多少次模型都只算一次，包括未同意记录的和使用自己模型的（后者由网页自报次数，不含内容）；"),
      T("账本不保存网络地址，也无法得知哪位访客问了什么。")),
  ];
}

/** A stat tile of the ledger's: the label, the number (shown: as it is to be read, when not in full), a line under it. */
function kpi(label, value, sub = null, shown = null) {
  return h("div.stat-tile", h("div.label", label), h("div.value", { title: shown ? fmt(value) : null }, shown || fmt(value)), sub ? h("div.sub", sub) : null);
}

/** A card that shows one of several things, chosen in its caption (one series a chart: the choice names it). */
function choiceCard(options, key, chart, asTable) {
  if (!options.some(([k]) => k === state[key])) state[key] = options[0][0];
  let showTable = false;
  const body = h("div.viz-body");
  const select = h("select.viz-choice", { "aria-label": T("显示哪一项") }, ...options.map(([k, name]) => h("option", { value: k, selected: k === state[key] }, name)));
  const toggle = h("button.btn-ghost.viz-toggle", { type: "button", "aria-pressed": "false" }, T("表格"));
  const show = () => {
    body.replaceChildren(showTable ? asTable(state[key]) : chart(state[key]));
    toggle.textContent = showTable ? T("图表") : T("表格");
    toggle.setAttribute("aria-pressed", String(showTable));
  };
  select.addEventListener("change", () => { state[key] = select.value; show(); });
  toggle.addEventListener("click", () => { showTable = !showTable; show(); });
  show();
  return h("figure.viz-card", h("figcaption", select, toggle), body);
}

/** A day-by-day line, as a card's body. */
function lineBody(days, values, name) {
  const host = h("div.viz-line");
  const watch = new ResizeObserver(() => { if (host.isConnected) drawLine(host, days, values, name); else if (drawn) watch.disconnect(); });
  let drawn = false;
  watch.observe(host);
  queueMicrotask(() => { drawn = true; drawLine(host, days, values, name); });
  return host;
}

/** Ranked bars, one hue: rows {label, value, lines?} — the largest first unless they have an order of their own; past
 * `top`, the rest as one row. */
function rankBody(rows, { top = 8, ordered = false } = {}) {
  const sorted = ordered ? rows : rows.filter((r) => r.value > 0).sort((a, b) => b.value - a.value);
  const shown = sorted.slice(0, top);
  const rest = sorted.slice(top);
  if (rest.length) shown.push({ label: T`其他 ${rest.length} 处`, value: rest.reduce((n, r) => n + r.value, 0) });
  const host = h("div.hbars", { role: "list" });
  const tooltip = tip(host);
  if (!shown.some((r) => r.value > 0)) host.append(h("div.viz-empty", T("这段时间还没有数据")));
  else {
    const max = Math.max(1, ...shown.map((r) => r.value));
    for (const r of shown) {
      const lines = r.lines || [[fmt(r.value), ""]];
      const row = h("div.hbar", { tabindex: 0, role: "listitem", "aria-label": `${r.label}：${lines.map(([v, n]) => `${n} ${v}`.trim()).join(T("，"))}` },
        h("span.name", { title: r.label }, r.label),
        h("span.track", h("i", { style: { width: r.value > 0 ? `max(2px, ${(r.value / max) * 100}%)` : "0" } })),
        h("span.val", fmt(r.value)));
      const show = () => {
        const box = row.getBoundingClientRect();
        const hb = host.getBoundingClientRect();
        tooltip.show([[r.label, ""], ...lines], box.left - hb.left + box.width / 2, box.top - hb.top);
      };
      row.addEventListener("pointerenter", show);
      row.addEventListener("pointerleave", () => tooltip.hide());
      row.addEventListener("focus", show);
      row.addEventListener("blur", () => tooltip.hide());
      host.append(row);
    }
  }
  return host;
}

function rankCard(title, rows, { top = 8, ordered = false, columns = null, sub = null } = {}) {
  const sorted = ordered ? rows : [...rows].sort((a, b) => b.value - a.value);
  const figure = card(title, rankBody(rows, { top, ordered }),
    () => (columns ? table([T("地区"), ...columns], sorted.map((r) => [r.label, ...r.lines.map(([v]) => v)])) : table([T("名称"), T("次数")], sorted.map((r) => [r.label, r.value]))));
  if (sub) figure.append(h("div.viz-foot", sub));
  return figure;
}

/**
 * Who came back: a row a week of new visitors, a column a week after — the share of that week's new visitors seen
 * again, each cell tinted by its share (one hue, more is darker; the number is in every cell: this is a table).
 */
function retentionCard(r) {
  const weeks = r.weekly.filter((c) => c.size > 0).slice(-8);
  const most = Math.min(6, Math.max(0, ...weeks.map((c) => c.back.length)));
  const body = h("div.viz-table-wrap");
  if (!weeks.length) body.append(h("div.viz-empty", T("这段时间还没有数据")));
  else {
    body.append(h("table.viz-table.retention",
      h("thead", h("tr", h("th", T("首次来访")), h("th.num", T("新访客")), ...Array.from({ length: most }, (_, i) => h("th.num", T`${i + 1} 周后`)))),
      h("tbody", ...weeks.map((c) => h("tr", h("td", T`${shortDay(c.week)} 起`), h("td.num", fmt(c.size)),
        ...Array.from({ length: most }, (_, i) => (i < c.back.length
          ? h("td.num.share", h("i", { style: { opacity: String(Math.min(1, c.back[i] / c.size) * 0.45) } }), h("span", pct(c.back[i], c.size)))
          : h("td.num.muted", ""))))))));
  }
  const day = (n, d) => (d.cohort ? T`第 ${n} 天 ${pct(d.back, d.cohort)}` : null);
  const days = [day(1, r.d1), day(7, r.d7), day(30, r.d30)].filter(Boolean);
  return h("figure.viz-card", h("figcaption", h("span.title", T("留存：新访客在之后几周回来的比例"))), body,
    days.length ? h("div.viz-foot", T("首次来访后回来的比例："), days.join(T("，"))) : null);
}

/** Facts in two columns: what, and how many. */
function factsCard(title, rows) {
  return h("figure.viz-card", h("figcaption", h("span.title", title)),
    h("div.viz-table-wrap", h("table.viz-table", h("tbody", ...rows.map(([name, value]) => h("tr", h("td", name), h("td.num", value)))))));
}
