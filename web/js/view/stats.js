// The 统计 pane of the settings: how much the site is used and from where — the pages opened and their visitors (the
// site's counts, /api/stats) and the questions asked of 道乃久默认服务 and who asked (the relay's, /v1/stats) — over the
// last 7, 30 or 90 days, by country and by China's provinces (security/usage.js; docs/web.md).  The counts are read with
// a token kept in this browser only; no address is ever among them.
// Charts are drawn here as SVG: one validated blue for the marks (--viz-1), the page's own ink and lines for the rest.

import { h, icon, storage } from "../util.js";

const TOKEN_KEY = "tc.statsToken";
const RANGES = [[7, "近 7 天"], [30, "近 30 天"], [90, "近 90 天"]];
const SVG = "http://www.w3.org/2000/svg";
const state = { days: 30, data: null }; // the last counts: kept on screen, dimmed, while the next arrive

// China's first-level divisions by their ISO 3166-2 codes, as Cloudflare gives them
const PROVINCES = {
  AH: "安徽", BJ: "北京", CQ: "重庆", FJ: "福建", GD: "广东", GS: "甘肃", GX: "广西", GZ: "贵州", HA: "河南", HB: "湖北", HE: "河北",
  HI: "海南", HK: "香港", HL: "黑龙江", HN: "湖南", JL: "吉林", JS: "江苏", JX: "江西", LN: "辽宁", MO: "澳门", NM: "内蒙古", NX: "宁夏",
  QH: "青海", SC: "四川", SD: "山东", SH: "上海", SN: "陕西", SX: "山西", TJ: "天津", TW: "台湾", XJ: "新疆", XZ: "西藏", YN: "云南", ZJ: "浙江",
};
let regionNames = null;
const countryName = (code) => {
  if (!code || code === "XX") return "未知";
  try { regionNames ||= new Intl.DisplayNames(["zh-CN"], { type: "region" }); return regionNames.of(code) || code; } catch { return code; }
};
const provinceName = (code) => PROVINCES[code] || code || "未知";
const fmt = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("zh-CN"));
const shortDay = (d) => d.slice(5);
const longDay = (d) => `${Number(d.slice(5, 7))}月${Number(d.slice(8, 10))}日`;

/** The pane: built at once, filled when the counts arrive. */
export function statsPane(d, S) {
  const root = h("div.stats");
  render(root, S);
  return root;
}

async function render(root, S) {
  const token = storage.get(TOKEN_KEY, "");
  if (state.data && root.childElementCount) root.classList.add("busy"); // the last counts stay, dimmed
  else root.replaceChildren(h("h3", "统计"), h("p.lead", "正在读取统计……"));
  const relay = S.relay?.url || "";
  const [site, rel] = await Promise.all([read(`api/stats?days=${state.days}`, token), relay ? read(`${relay}/v1/stats?days=${state.days}`, token) : null]);
  root.classList.remove("busy");
  const ok = (r) => r && r.status === 200 && r.body && Array.isArray(r.body.days);
  if (!ok(site) && !ok(rel)) return root.replaceChildren(...closed(root, S, site, rel, token).filter(Boolean));
  state.data = merge(ok(site) ? site.body : null, ok(rel) ? rel.body : null);
  root.replaceChildren(...dashboard(root, S, state.data, token, { site: ok(site), relay: ok(rel), relayAsked: Boolean(relay) }).filter(Boolean)); // replaceChildren writes a null as "null"
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
  const head = h("h3", "统计");
  if (!asked || unset) return [head, h("div.notice", icon("info"), h("div.grow", "统计尚未开放。"))];
  const input = h("input", { type: "password", autocomplete: "off", spellcheck: "false", "aria-label": "统计令牌" });
  const go = () => {
    const v = input.value.trim();
    if (!v) return input.focus();
    storage.set(TOKEN_KEY, v);
    render(root, S);
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  return [head,
    h("div.form-grid",
      h("div.field", h("label", "统计令牌"),
        h("div.inline", input, h("button.btn", { type: "button", on: { click: go } }, "查看")),
        token ? h("div.help.err", "令牌不对，请重新输入。") : null))];
}

// ------------------------------------------------------------------ the dashboard
function dashboard(root, S, data, token, has) {
  const range = h("div.seg", { role: "radiogroup", "aria-label": "时间范围" });
  for (const [n, label] of RANGES) {
    range.append(h("button", { type: "button", role: "radio", "aria-checked": String(n === state.days), class: n === state.days ? "on" : "",
      on: { click: () => { if (state.days !== n) { state.days = n; render(root, S); } } } }, label));
  }
  const filters = h("div.stats-filters", range,
    h("button.btn-ghost", { type: "button", title: "重新读取", on: { click: () => render(root, S) } }, icon("redo", "sm"), "刷新"),
    token ? h("button.btn-ghost", { type: "button", title: "在本浏览器忘记统计令牌", on: { click: () => { storage.remove(TOKEN_KEY); state.data = null; render(root, S); } } },
      icon("key", "sm"), "忘记令牌") : null);
  const period = `较前 ${state.days} 天`;
  const tiles = h("div.stat-tiles",
    tile("页面访问", data, "view", period),
    tile("访客", data, "visitor", period, "每日去重"),
    tile("提问", data, "question", period, data.totals.call === null ? null : `模型调用 ${fmt(data.totals.call)} 次`),
    tile("提问的人", data, "asker", period, "每日去重"));
  const trends = h("div.viz-grid",
    data.daily.view ? lineCard("每日页面访问", data.days, data.daily.view, "页面访问") : null,
    data.daily.question ? lineCard("每日提问", data.days, data.daily.question, "提问") : null);
  const metric = data.has.site ? "view" : "question";
  const metricName = metric === "view" ? "页面访问" : "提问";
  const byCountry = new Map();
  for (const p of data.places) {
    const c = byCountry.get(p.country) || { country: p.country, region: "", view: 0, visitor: 0, question: 0, call: 0, asker: 0 };
    for (const k of ["view", "visitor", "question", "call", "asker"]) c[k] += p[k];
    byCountry.set(p.country, c);
  }
  const countries = [...byCountry.values()].map((p) => ({ label: countryName(p.country), p }));
  const provinces = data.places.filter((p) => p.country === "CN").map((p) => ({ label: provinceName(p.region), p }));
  const regions = h("div.viz-grid",
    barCard("国家/地区", countries, metric, metricName, 8),
    barCard("中国各省份", provinces, metric, metricName, 10));
  const missing = !data.has.site ? "网站的计数没有读到（页面访问、访客显示为 —）。" : has.relayAsked && !data.has.relay ? "默认服务的计数没有读到（提问显示为 —）。" : "";
  return [
    h("h3", "统计"),
    h("p.lead", `截至 ${longDay(data.asOf)}（北京时间）：网页打开的次数与访客、向道乃久默认服务提的问题，以及来自哪些国家和省份。`),
    filters,
    missing ? h("div.notice", icon("info"), h("div.grow", missing)) : null,
    tiles,
    trends,
    regions,
    h("p.stats-note",
      "说明：地区按 Cloudflare 对访问来源的判断（国家与省级行政区），本站不记录网络地址；访客按日去重；页面访问只计浏览器打开网页，",
      "不含爬虫与脚本；提问只计道乃久默认服务（使用自己的 API Key 时不经本站，不计入）；日期按北京时间。"),
  ];
}

/** A stat tile: the label, the number over the range, its change against the range before, and today's. */
function tile(label, data, kind, period, note = null) {
  const v = data.totals[kind];
  const prev = data.previous[kind];
  let delta = null;
  if (v !== null && prev !== null) {
    if (prev === 0) delta = v > 0 ? h("span.delta", `${period}：新增`) : h("span.delta", `${period}：持平`);
    else {
      const pct = Math.round(((v - prev) / prev) * 100);
      delta = pct === 0 ? h("span.delta", `${period}：持平`)
        : h(`span.delta.${pct > 0 ? "up" : "down"}`, `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}%`, h("span.muted", ` ${period}`));
    }
  }
  return h("div.stat-tile",
    h("div.label", label),
    h("div.value", fmt(v)),
    delta,
    h("div.sub", `今天 ${fmt(data.today[kind])}`, note ? ` · ${note}` : ""));
}

// ------------------------------------------------------------------ cards, tooltips, tables
function card(title, chart, table) {
  let showTable = false;
  const body = h("div.viz-body");
  const toggle = h("button.btn-ghost.viz-toggle", { type: "button", "aria-pressed": "false" }, "表格");
  const show = () => {
    body.replaceChildren(showTable ? table() : chart);
    toggle.textContent = showTable ? "图表" : "表格";
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
  return card(title, host, () => table(["日期", name], days.map((d, i) => [longDay(d), values[i]]).reverse()));
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
    "aria-label": `${name}，${days.length} 天，最近一天 ${fmt(values[last])}；可切换表格查看每天的数字` },
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
    shown.push({ label: `其他 ${rest.length} 处`, p: other });
  }
  const host = h("div.hbars");
  const tooltip = tip(host);
  if (!shown.length) host.append(h("div.viz-empty", "这段时间还没有数据"));
  const max = Math.max(1, ...shown.map((r) => r.p[metric]));
  for (const r of shown) {
    const v = r.p[metric];
    const lines = [[fmt(r.p.view), "页面访问"], [fmt(r.p.visitor), "访客"], [fmt(r.p.question), "提问"], [fmt(r.p.asker), "提问的人"]];
    const row = h("div.hbar", { tabindex: 0, role: "listitem", "aria-label": `${r.label}：${lines.map(([v2, n]) => `${n} ${v2}`).join("，")}` },
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
  host.setAttribute("aria-label", `${title}，按${metricName}排列`);
  return card(`${title} · 按${metricName}`, host,
    () => table(["地区", "页面访问", "访客", "提问", "提问的人"], sorted.map((r) => [r.label, r.p.view, r.p.visitor, r.p.question, r.p.asker])));
}
