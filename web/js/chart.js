// 图表 — the chart specifications the study tools return (taochronos/plugins/classics/study/charts.py) drawn as SVG, with a
// table view and downloads: SVG (a standalone figure, colours and fonts inline), PNG (twice its size), CSV (UTF-8 with a
// byte-order mark, for spreadsheet programs) and the JSON specification.  The same specification, written by the model
// in a ```chart block, is drawn the same way (markdown.js).
//
// The marks follow one specification (as the Python figures do, study/svg.py): hairline, solid, recessive grid and axes;
// bars at most 24 px thick with a 4 px rounded data end; 2 px lines; 8 px markers ringed with the surface; a 2 px surface gap
// between stacked segments; a legend whenever there are two series or more; values and labels in ink, never in a series
// colour; hover and keyboard focus give the numbers, and the table gives every one of them.  Colours are tokens
// (--viz-1 … --viz-8, --viz-other, the --viz-seq ramp; css/app.css, light and dark), validated for colour-vision
// deficiency; a downloaded figure takes the light ones.

import { download, downloadBlob, h, icon, toast } from "./util.js";

const SVG = "http://www.w3.org/2000/svg";
export const TYPES = ["line", "bar", "hbar", "stack", "heatmap", "range", "timeline", "network"];
const FIGURE_WIDTH = 760;
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif";
// the light tokens, for a downloaded figure (css/app.css holds both modes for the page)
export const LIGHT = {
  "viz-1": "#2a78d6", "viz-2": "#eb6834", "viz-3": "#1baf7a", "viz-4": "#eda100", "viz-5": "#e87ba4", "viz-6": "#008300",
  "viz-7": "#6250d6", "viz-8": "#e34948", "viz-other": "#b3b1aa", "viz-surface": "#fcfcfb", "viz-ink": "#0b0b0b",
  "viz-ink-2": "#52514e", "viz-muted": "#898781", "viz-grid": "#e1e0d9", "viz-axis": "#c3c2b7", "viz-empty": "#f0efec",
  ...Object.fromEntries(["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf",
    "#1c5cab", "#184f95", "#104281", "#0d366b"].map((c, i) => [`viz-seq-${i}`, c])),
};
const RAMP = 13;
const v = (name) => `var(--${name})`;

// ------------------------------------------------------------------ checking a specification
/** null when the specification can be drawn, else why not (a model's ```chart block is checked before it is drawn). */
export function invalid(spec) {
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return "图表规格应为 JSON 对象";
  if (!TYPES.includes(spec.type)) return `不支持的图表类型：${spec.type}（可用 ${TYPES.join("、")}）`;
  if (spec.type === "network") {
    if (!Array.isArray(spec.nodes) || !spec.nodes.length) return "网络图需要 nodes";
    if (spec.nodes.length > 400 || (spec.edges || []).length > 4000) return "网络过大（至多 400 个节点、4000 条边）";
    return null;
  }
  if (!Array.isArray(spec.rows) || !spec.rows.length) return "图表需要 rows（数据行）";
  if (spec.rows.length > 2000) return "数据行过多（至多 2000 行）";
  if (["line", "bar", "hbar", "stack", "range"].includes(spec.type) && !spec.x?.key) return "需要 x.key（类别字段）";
  if (["line", "bar", "hbar", "stack"].includes(spec.type) && !(Array.isArray(spec.series) && spec.series.length)) return "需要 series（数值字段）";
  if (spec.type === "heatmap" && !(spec.x?.key && spec.y?.key && spec.value?.key)) return "热图需要 x.key、y.key 与 value.key";
  if (spec.type === "range" && !spec.range?.median) return "区间图需要 range.median 等字段";
  if (spec.type === "timeline" && !spec.rows.some((r) => num(r.start) !== null)) return "时间线需要 rows[].start（年份）";
  return null;
}

/** A model's specification made whole: columns from the rows when it gives none, series labels from their keys. */
export function normalize(spec) {
  const out = { ...spec };
  if (!Array.isArray(out.columns) || !out.columns.length) {
    const keys = [...new Set((out.rows || []).flatMap((r) => Object.keys(r || {})))];
    out.columns = keys.map((k) => ({ key: k, label: k }));
  }
  if (Array.isArray(out.series)) out.series = out.series.map((s) => (typeof s === "string" ? { key: s, label: s } : { label: s.key, ...s }));
  return out;
}

// ------------------------------------------------------------------ numbers and text
const num = (x) => (x === null || x === undefined || x === "" || Number.isNaN(Number(x)) ? null : Number(x));

export function fmt(x, percent = false) {
  const n = num(x);
  if (n === null) return x === null || x === undefined ? "" : String(x);
  if (percent) return `${(n * 100).toFixed(Math.abs(n) >= 0.1 || n === 0 ? 0 : 1)}%`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  if (Number.isInteger(n)) return String(n);
  return String(Number(n.toPrecision(3)));
}

/** Width of a text in px: a CJK character as wide as the font size, others about 0.58 of it. */
export function textWidth(text, size) {
  let w = 0;
  for (const ch of String(text)) w += ch.codePointAt(0) > 0x2e80 ? size : size * 0.58;
  return w;
}

/** The top of an axis: the next of 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8 (× a power of ten) — never far above the data. */
export function niceMax(x) {
  if (!(x > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(x));
  for (const s of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (x <= s * mag + 1e-12) return Number((s * mag).toPrecision(12));
  return 10 * mag;
}

/** Round ticks over [lo, hi]; ``integer``: no fractions (counts). */
export function ticks(lo, hi, n = 5, integer = false) {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const steps = integer ? [1, 2, 5, 10].map((s) => s * Math.max(1, mag)) : [1, 2, 2.5, 5, 10].map((s) => s * mag);
  const step = steps.find((s) => raw <= s + 1e-12) || steps[steps.length - 1];
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) out.push(Number(t.toFixed(10)));
  return out;
}

/** The categorical tokens in order, 其他 in the de-emphasis grey (never a ninth hue). */
export function seriesColors(labels) {
  let k = 0;
  return labels.map((l) => (l === "其他" ? v("viz-other") : k < 8 ? v(`viz-${++k}`) : v("viz-other")));
}

/** Colours by group: by its place in the order the specification gives (groups), so that a category keeps its colour in
 * every chart of a result whichever groups each one shows; groups it does not list follow.  The groups seen, in order. */
function groupColors(spec, seen) {
  const listed = (Array.isArray(spec.groups) ? spec.groups : []).map(String);
  const order = [...listed, ...seen.filter((g) => !listed.includes(g))];
  const colors = seriesColors(order);
  return new Map(order.map((g, i) => [g, colors[i]]).filter(([g]) => seen.includes(g)));
}

// ------------------------------------------------------------------ SVG building
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, val] of Object.entries(attrs)) if (val !== null && val !== undefined && val !== false) node.setAttribute(k, String(val));
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
};
const text = (x, y, s, { size = 11, fill = "viz-ink-2", anchor = "start", weight = null, cls = null } = {}) =>
  el("text", { x: x.toFixed(1), y: y.toFixed(1), "font-size": size, fill: v(fill), "text-anchor": anchor, "font-weight": weight, class: cls }, String(s ?? ""));

function roundedBar(x, y, w, hgt, up = true, r = 4) {
  r = Math.min(r, w / 2, Math.abs(hgt));
  if (!(hgt > 0) || !(w > 0)) return "";
  if (up) return `M${x},${y + hgt}L${x},${y + r}Q${x},${y} ${x + r},${y}L${x + w - r},${y}Q${x + w},${y} ${x + w},${y + r}L${x + w},${y + hgt}Z`;
  return `M${x},${y}L${x + w - r},${y}Q${x + w},${y} ${x + w},${y + r}L${x + w},${y + hgt - r}Q${x + w},${y + hgt} ${x + w - r},${y + hgt}L${x},${y + hgt}Z`;
}

/** The plot of a specification at a width: {svg, height, targets} — targets: the hover points ({x, y, lines}). */
export function plot(spec, width) {
  const draw = { line: series, bar: series, stack: series, hbar, heatmap, range, timeline, network }[spec.type];
  return draw(spec, Math.max(280, width));
}

function legend(items, width, kind = "rect") {
  if (items.length < 2) return { nodes: [], height: 0 };
  const nodes = [];
  let x = 0, y = 12;
  for (const [label, color] of items) {
    const w = 18 + textWidth(label, 11) + 16;
    if (x + w > width && x > 0) { x = 0; y += 18; }
    nodes.push(kind === "line"
      ? el("line", { x1: x, y1: y - 4, x2: x + 12, y2: y - 4, stroke: color, "stroke-width": 2 })
      : el("rect", { x, y: y - 9, width: 10, height: 10, rx: 2, fill: color }));
    nodes.push(text(x + 16, y, label, { size: 11 }));
    x += w;
  }
  return { nodes, height: y + 10 };
}

/** Are these counts (whole numbers)?  Their axis then has no fractions. */
const whole = (values) => values.every((x) => x === null || Number.isInteger(x));

function yAxis(g, left, right, top, bottom, lo, hi, percent, label, integer = false) {
  const scale = (val) => (hi > lo ? bottom - ((val - lo) / (hi - lo)) * (bottom - top) : bottom);
  for (const t of ticks(lo, hi, 5, integer && !percent)) {
    const y = scale(t);
    g.append(el("line", { x1: left, y1: y, x2: right, y2: y, stroke: v("viz-grid"), "stroke-width": 1 }),
      text(left - 6, y + 4, fmt(t, percent), { size: 10.5, fill: "viz-muted", anchor: "end", cls: "tick" }));
  }
  g.append(el("line", { x1: left, y1: bottom, x2: right, y2: bottom, stroke: v("viz-axis"), "stroke-width": 1 }));
  if (label) g.append(text(left, top - 8, label, { size: 10.5, fill: "viz-muted" }));
  return scale;
}

function xLabels(g, cats, xs, bottom, band) {
  const longest = Math.max(0, ...cats.map((c) => textWidth(c, 10.5)));
  if (longest <= band - 4) {
    cats.forEach((c, i) => g.append(text(xs[i], bottom + 16, c, { size: 10.5, anchor: "middle" })));
    return bottom + 22;
  }
  cats.forEach((c, i) => g.append(el("text", { x: xs[i].toFixed(1), y: (bottom + 12).toFixed(1), "font-size": 10.5, fill: v("viz-ink-2"),
    "text-anchor": "end", transform: `rotate(-40 ${xs[i].toFixed(1)} ${(bottom + 12).toFixed(1)})` }, String(c))));
  return bottom + 12 + longest * 0.7;
}

function series(spec, width) {
  const kind = spec.type;
  const rows = spec.rows;
  const xkey = spec.x.key;
  const list = spec.series.slice(0, 8);
  const y = spec.y || {};
  const percent = Boolean(y.percent) || (kind === "stack" && spec.percent);
  const colors = seriesColors(list.map((s) => s.label));
  const g = el("g");
  const lg = legend(list.map((s, i) => [s.label, colors[i]]), width, kind === "line" ? "line" : "rect");
  g.append(...lg.nodes);
  const left = 52, right = width - 16;
  const top = lg.height + 22, bottom = top + Math.min(280, Math.max(180, width * 0.42));
  let lo = 0, hi = 1, integer;
  if (kind === "stack") {
    const totals = rows.map((r) => list.reduce((a, s) => a + (num(r[s.key]) || 0), 0));
    hi = spec.percent ? 1 : niceMax(Math.max(0, ...totals));
    integer = whole(totals);
  } else {
    const vals = rows.flatMap((r) => list.flatMap((s) => [r[s.key], s.hi ? r[s.hi] : null, s.lo ? r[s.lo] : null])).map(num).filter((n) => n !== null);
    hi = num(y.max) ?? niceMax(Math.max(0, ...vals));
    lo = num(y.min) ?? Math.min(0, ...vals);
    integer = whole(vals);
  }
  const scale = yAxis(g, left, right, top, bottom, lo, hi, percent, y.label, integer);
  const band = (right - left) / Math.max(rows.length, 1);
  const xs = rows.map((_, i) => left + band * (i + 0.5));
  const targets = [];
  if (kind === "line") {
    list.forEach((s, i) => {
      if (s.lo && s.hi) {
        const up = rows.map((r, j) => [xs[j], num(r[s.hi])]).filter(([, n]) => n !== null);
        const down = rows.map((r, j) => [xs[j], num(r[s.lo])]).filter(([, n]) => n !== null).reverse();
        if (up.length && down.length) g.append(el("polygon", { points: [...up, ...down].map(([a, b]) => `${a.toFixed(1)},${scale(b).toFixed(1)}`).join(" "), fill: colors[i], "fill-opacity": 0.1 }));
      }
      const pts = rows.map((r, j) => [xs[j], num(r[s.key])]).filter(([, n]) => n !== null);
      if (pts.length >= 2) g.append(el("polyline", { points: pts.map(([a, b]) => `${a.toFixed(1)},${scale(b).toFixed(1)}`).join(" "), fill: "none", stroke: colors[i], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      for (const [a, b] of pts) g.append(el("circle", { cx: a.toFixed(1), cy: scale(b).toFixed(1), r: 4, fill: colors[i], stroke: v("viz-surface"), "stroke-width": 2 }));
      if (pts.length) { const [a, b] = pts[pts.length - 1]; g.append(text(a, scale(b) - 9, fmt(b, percent), { size: 10.5, fill: "viz-ink", anchor: "middle" })); }
    });
    rows.forEach((r, j) => targets.push({ x: xs[j], y: top, crosshair: true, title: String(r[xkey] ?? ""),
      lines: list.map((s) => [fmt(r[s.key], percent) + (s.lo && s.hi && num(r[s.lo]) !== null ? `（${fmt(r[s.lo], percent)}–${fmt(r[s.hi], percent)}）` : ""), s.label]) }));
  } else if (kind === "bar") {
    const n = Math.max(list.length, 1);
    const bw = Math.max(3, Math.min(24, (band - 8) / n - 2));
    rows.forEach((r, j) => {
      const x0 = xs[j] - ((bw + 2) * n) / 2 + 1;
      list.forEach((s, i) => {
        const val = num(r[s.key]);
        if (val === null) return;
        const yv = scale(Math.max(val, lo)), base = scale(Math.max(lo, 0));
        const top_ = Math.min(yv, base), hgt = Math.abs(base - yv);
        g.append(el("path", { d: val >= 0 ? roundedBar(x0 + i * (bw + 2), top_, bw, hgt) : "", fill: colors[i] }));
        if (s.lo && s.hi && num(r[s.lo]) !== null && num(r[s.hi]) !== null) {
          const cx = x0 + i * (bw + 2) + bw / 2;
          g.append(el("line", { x1: cx, y1: scale(num(r[s.lo])), x2: cx, y2: scale(num(r[s.hi])), stroke: v("viz-ink-2"), "stroke-width": 1 }));
        }
        if (n === 1 && rows.length <= 14) g.append(text(x0 + bw / 2, yv - 5, fmt(val, percent), { size: 10, anchor: "middle" }));
      });
      targets.push({ x: xs[j], y: scale(Math.max(0, ...list.map((s) => num(r[s.key]) ?? 0))), col: band / 2, title: String(r[xkey] ?? ""),
        lines: list.map((s) => [fmt(r[s.key], percent), s.label]) });
    });
  } else {
    const bw = Math.min(24, band - 8);
    rows.forEach((r, j) => {
      const total = list.reduce((a, s) => a + (num(r[s.key]) || 0), 0) || 1;
      let acc = 0;
      list.forEach((s, i) => {
        let val = num(r[s.key]) || 0;
        if (spec.percent) val /= total;
        if (val <= 0) return;
        const y1 = scale(acc + val), y2 = scale(acc);
        g.append(el("rect", { x: (xs[j] - bw / 2).toFixed(1), y: y1.toFixed(1), width: bw.toFixed(1), height: Math.max(y2 - y1 - 2, 0.5).toFixed(1), fill: colors[i] }));
        acc += val;
      });
      targets.push({ x: xs[j], y: scale(acc), col: band / 2, title: String(r[xkey] ?? ""),
        lines: list.map((s) => [spec.percent ? fmt((num(r[s.key]) || 0) / total, true) : fmt(r[s.key]), s.label]).filter(([val]) => val && val !== "0" && val !== "0%") });
    });
  }
  const end = xLabels(g, rows.map((r) => String(r[xkey] ?? "")), xs, bottom, band);
  return { svg: g, height: end + 4, targets, plotTop: top, plotBottom: bottom };
}

function hbar(spec, width) {
  const rows = spec.rows;
  const xkey = spec.x.key;
  const s = spec.series[0];
  const percent = Boolean(spec.y?.percent);
  const g = el("g");
  const labelW = Math.min(width * 0.36, Math.max(...rows.map((r) => textWidth(r[xkey] ?? "", 11)), 30) + 12);
  const left = labelW, right = width - 60;
  const top = 8, step = 24;
  const vals = rows.map((r) => num(r[s.key]) || 0);
  const lo = Math.min(0, ...vals), hi = niceMax(Math.max(0, ...vals));
  const scale = (val) => (hi > lo ? left + ((val - lo) / (hi - lo)) * (right - left) : left);
  const bottom = top + step * rows.length;
  for (const t of ticks(lo, hi, 4, whole(vals) && !percent)) {
    const x = scale(t);
    g.append(el("line", { x1: x, y1: top, x2: x, y2: bottom, stroke: v("viz-grid"), "stroke-width": 1 }),
      text(x, bottom + 14, fmt(t, percent), { size: 10.5, fill: "viz-muted", anchor: "middle", cls: "tick" }));
  }
  const targets = [];
  rows.forEach((r, i) => {
    const val = num(r[s.key]) || 0;
    const y = top + i * step + 4;
    g.append(text(left - 8, y + 12, r[xkey] ?? "", { size: 11, anchor: "end" }));
    const x0 = scale(0), x1 = scale(val);
    g.append(x1 >= x0 ? el("path", { d: roundedBar(x0, y, x1 - x0, 16, false), fill: v("viz-1") })
      : el("rect", { x: x1, y, width: x0 - x1, height: 16, fill: v("viz-1") }));
    g.append(text(Math.max(x0, x1) + 6, y + 12, fmt(val, percent), { size: 10.5, fill: "viz-ink" }));
    const extra = (spec.columns || []).filter((c) => c.key !== xkey && c.key !== s.key).map((c) => [fmt(r[c.key]), c.label]).filter(([x]) => x);
    targets.push({ x: Math.max(x0, x1), y: y + 8, row: step / 2, title: String(r[xkey] ?? ""), lines: [[fmt(val, percent), s.label || ""], ...extra] });
  });
  g.append(el("line", { x1: scale(0), y1: top, x2: scale(0), y2: bottom, stroke: v("viz-axis"), "stroke-width": 1 }));
  return { svg: g, height: bottom + 20, targets };
}

function heatmap(spec, width) {
  const rows = spec.rows;
  const xk = spec.x.key, yk = spec.y.key, vk = spec.value.key;
  const xs = spec.x.order || [...new Set(rows.map((r) => r[xk]))];
  const ys = spec.y.order || [...new Set(rows.map((r) => r[yk]))];
  const percent = Boolean(spec.value.percent);
  const cell = new Map(rows.map((r) => [`${r[xk]}\u0000${r[yk]}`, r]));
  const vmax = num(spec.value.max) || Math.max(1e-9, ...rows.map((r) => num(r[vk]) || 0));
  const g = el("g");
  const labelW = Math.min(width * 0.32, Math.max(...ys.map((y) => textWidth(y, 11)), 24) + 12);
  const left = labelW;
  const cw = Math.min(64, (width - 12 - left) / Math.max(xs.length, 1));
  const ch = 24;
  const rotated = xs.some((x) => textWidth(x, 10.5) > cw - 2);
  const top = rotated ? 12 + Math.min(80, Math.max(...xs.map((x) => textWidth(x, 10.5))) * 0.65) : 22;
  xs.forEach((x, i) => {
    const cx = left + cw * (i + 0.5);
    g.append(rotated
      ? el("text", { x: cx.toFixed(1), y: (top - 6).toFixed(1), "font-size": 10.5, fill: v("viz-ink-2"), "text-anchor": "start", transform: `rotate(-40 ${cx.toFixed(1)} ${(top - 6).toFixed(1)})` }, String(x))
      : text(cx, top - 8, x, { size: 10.5, anchor: "middle" }));
  });
  const targets = [];
  ys.forEach((y, j) => {
    const cy = top + ch * j;
    g.append(text(left - 8, cy + ch / 2 + 4, y, { size: 11, anchor: "end" }));
    xs.forEach((x, i) => {
      const r = cell.get(`${x}\u0000${y}`);
      const val = r ? num(r[vk]) : null;
      const k = val === null || val <= 0 ? -1 : Math.min(RAMP - 1, Math.round((val / vmax) * (RAMP - 1)));
      g.append(el("rect", { x: (left + cw * i + 1).toFixed(1), y: (cy + 1).toFixed(1), width: (cw - 2).toFixed(1), height: ch - 2, rx: 2, fill: k < 0 ? v("viz-empty") : v(`viz-seq-${k}`) }));
      if (val !== null && val > 0) {
        const label = fmt(val, percent);
        if (textWidth(label, 10) <= cw - 6) g.append(text(left + cw * (i + 0.5), cy + ch / 2 + 4, label, { size: 10, anchor: "middle", fill: k >= 6 ? "viz-surface" : "viz-ink" }));
      }
      const extra = r ? (spec.columns || []).filter((c) => ![xk, yk, vk].includes(c.key)).map((c) => [fmt(r[c.key]), c.label]).filter(([s]) => s) : [];
      targets.push({ x: left + cw * (i + 0.5), y: cy + ch / 2, box: [cw / 2, ch / 2], title: `${y} · ${x}`, lines: [[val === null ? "—" : fmt(val, percent), spec.value.label || ""], ...extra] });
    });
  });
  const bottom = top + ch * ys.length;
  for (let k = 0; k < RAMP; k++) g.append(el("rect", { x: left + k * 14, y: bottom + 12, width: 14, height: 8, fill: v(`viz-seq-${k}`) }));
  g.append(text(left, bottom + 34, "0", { size: 10, fill: "viz-muted" }), text(left + 14 * RAMP, bottom + 34, fmt(vmax, percent), { size: 10, fill: "viz-muted", anchor: "end" }),
    text(left + 14 * RAMP + 10, bottom + 20, spec.value.label || "", { size: 10.5, fill: "viz-muted" }));
  return { svg: g, height: bottom + 42, targets };
}

function range(spec, width) {
  const rows = spec.rows;
  const keys = spec.range;
  const xkey = spec.x.key;
  const g = el("g");
  const left = 52, right = width - 16, top = 20, bottom = top + Math.min(260, Math.max(170, width * 0.38));
  const vals = rows.flatMap((r) => [num(r[keys.min]), num(r[keys.max])]).filter((n) => n !== null);
  const boxes = rows.flatMap((r) => [num(r[keys.q3]), num(r[keys.median])]).filter((n) => n !== null);
  // the axis reads the boxes: a few very large values would flatten them — it stops at 2.5× the largest upper quartile,
  // longer whiskers are cut there with their value at the top (the table has every number)
  const hi = niceMax(Math.min(Math.max(1, ...vals), Math.max(1, ...boxes) * 2.5));
  const scale = yAxis(g, left, right, top, bottom, 0, hi, false, spec.y?.label);
  const clip = (n) => Math.min(n, hi);
  const band = (right - left) / Math.max(rows.length, 1);
  const xs = rows.map((_, i) => left + band * (i + 0.5));
  const targets = [];
  rows.forEach((r, i) => {
    const [lo_, q1, med, q3, hi_] = ["min", "q1", "median", "q3", "max"].map((k) => num(r[keys[k]]));
    const x = xs[i];
    if (lo_ !== null && hi_ !== null) {
      g.append(el("line", { x1: x, y1: scale(clip(lo_)), x2: x, y2: scale(clip(hi_)), stroke: v("viz-1"), "stroke-width": 1 }));
      if (hi_ > hi) g.append(el("path", { d: `M${x - 4},${top + 6}L${x},${top}L${x + 4},${top + 6}`, fill: "none", stroke: v("viz-1"), "stroke-width": 1 }), text(x + 6, top + 6, `↑${fmt(hi_)}`, { size: 10, fill: "viz-muted" }));
    }
    if (q1 !== null && q3 !== null) {
      const y1 = scale(clip(q3)), y3 = scale(clip(q1));
      g.append(el("rect", { x: x - 10, y: y1, width: 20, height: Math.max(y3 - y1, 1), rx: 3, fill: v("viz-1"), "fill-opacity": 0.25, stroke: v("viz-1"), "stroke-width": 1 }));
    }
    if (med !== null) g.append(el("circle", { cx: x, cy: scale(clip(med)), r: 4.5, fill: v("viz-1"), stroke: v("viz-surface"), "stroke-width": 2 }), text(x + 14, scale(clip(med)) + 4, fmt(med), { size: 10.5, fill: "viz-ink" }));
    targets.push({ x, y: scale(clip(med ?? 0)), col: band / 2, title: String(r[xkey] ?? ""),
      lines: (spec.columns || []).filter((c) => c.key !== xkey).map((c) => [fmt(r[c.key]), c.label]) });
  });
  const end = xLabels(g, rows.map((r) => String(r[xkey] ?? "")), xs, bottom, band);
  return { svg: g, height: end + 4, targets };
}

const yearText = (t) => (t < 0 ? `前${Math.round(-t)}` : String(Math.round(t)));

function timeline(spec, width) {
  const rows = spec.rows.filter((r) => num(r.start) !== null).sort((a, b) => num(a.start) - num(b.start));
  const colors = groupColors(spec, [...new Set(rows.map((r) => String(r.group ?? "")))]);
  const g = el("g");
  const lg = legend([...colors].filter(([k]) => k), width);
  g.append(...lg.nodes);
  const left = 30, right = width - 30;
  const years = rows.map((r) => num(r.start));
  let lo = Math.min(...years), hi = Math.max(...years);
  if (hi - lo < 50) { lo -= 25; hi += 25; }
  const pad = (hi - lo) * 0.04;
  lo -= pad; hi += pad;
  const scale = (t) => left + ((t - lo) / (hi - lo)) * (right - left);
  const lanes = [];
  const placed = rows.map((r) => {
    const x = scale(num(r.start));
    const w = textWidth(r.label ?? "", 10.5) + 14;
    const flip = x + w > width - 6;
    const span = flip ? [x - w, x + 6] : [x - 6, x + w];
    let lane = lanes.findIndex(([a, b]) => b < span[0] - 2 || a > span[1] + 2);
    if (lane < 0) { lanes.push(span); lane = lanes.length - 1; } else lanes[lane] = [Math.min(lanes[lane][0], span[0]), Math.max(lanes[lane][1], span[1])];
    return { r, x, lane, flip };
  });
  const top = lg.height + 18;
  const axis = top + 22 * Math.max(lanes.length, 1) + 10;
  for (const t of ticks(lo, hi, 6)) {
    const x = scale(t);
    g.append(el("line", { x1: x, y1: top, x2: x, y2: axis, stroke: v("viz-grid"), "stroke-width": 1 }), text(x, axis + 16, yearText(t), { size: 10.5, fill: "viz-muted", anchor: "middle", cls: "tick" }));
  }
  g.append(el("line", { x1: left, y1: axis, x2: right, y2: axis, stroke: v("viz-axis"), "stroke-width": 1 }));
  const targets = [];
  for (const { r, x, lane, flip } of placed) {
    const y = top + 22 * lane + 8;
    const c = colors.get(String(r.group ?? ""));
    g.append(el("line", { x1: x, y1: y, x2: x, y2: axis, stroke: c, "stroke-width": 1, "stroke-opacity": 0.35 }),
      el("circle", { cx: x, cy: y, r: 4, fill: c, stroke: v("viz-surface"), "stroke-width": 2 }),
      text(flip ? x - 7 : x + 7, y + 4, r.label ?? "", { size: 10.5, fill: "viz-ink", anchor: flip ? "end" : "start" }));
    targets.push({ x, y, title: String(r.label ?? ""), lines: (spec.columns || []).filter((col) => col.key !== "label").map((col) => [fmt(r[col.key]), col.label]).filter(([s]) => s) });
  }
  return { svg: g, height: axis + 24, targets };
}

function hubOf(nodes, edges) {
  if (!edges?.length || edges.length !== nodes.length - 1) return null;
  const common = edges.map((e) => new Set([e.source, e.target])).reduce((a, b) => new Set([...a].filter((x) => b.has(x))));
  return common.size === 1 ? [...common][0] : null;
}

function network(spec, width) {
  const nodes = spec.nodes || [];
  const edges = spec.edges || [];
  const colors = groupColors(spec, [...new Set(nodes.map((n) => String(n.group ?? "")))]);
  const g = el("g");
  const lg = legend([...colors].filter(([k]) => k), width);
  g.append(...lg.nodes);
  const smax = Math.max(1, ...nodes.map((n) => num(n.size) || 1));
  const rad = (n) => 4 + 8 * Math.sqrt((num(n.size) || 1) / smax);
  const targets = [];
  const hub = hubOf(nodes, edges);
  const top = lg.height + 16;
  if (hub !== null) { // a hub and its spokes: the hub on the left, the others in a column
    const centre = nodes.find((n) => n.id === hub);
    const others = nodes.filter((n) => n.id !== hub);
    const byTarget = new Map(edges.map((e) => [e.source === hub ? e.target : e.source, e]));
    const step = 22, height = step * Math.max(others.length, 1);
    const hx = Math.min(140, width * 0.22), hy = top + height / 2, col = Math.min(360, width * 0.48);
    others.forEach((n, i) => {
      const y = top + step * i + step / 2;
      const e = byTarget.get(n.id) || {};
      g.append(el("path", { d: `M${hx},${hy}C${(hx + col) / 2},${hy} ${(hx + col) / 2},${y} ${col},${y}`, fill: "none", stroke: v("viz-axis"), "stroke-width": 1 }),
        el("circle", { cx: col, cy: y, r: rad(n), fill: colors.get(String(n.group ?? "")), stroke: v("viz-surface"), "stroke-width": 2 }),
        text(col + 14, y + 4, n.label ?? n.id, { size: 11, fill: "viz-ink" }));
      if (e.label && col + 24 + textWidth(n.label ?? "", 11) + textWidth(e.label, 10) < width) g.append(text(col + 24 + textWidth(n.label ?? "", 11), y + 4, e.label, { size: 10, fill: "viz-muted" }));
      targets.push({ x: col, y, title: String(n.label ?? n.id), lines: [[String(n.group ?? ""), "关系"], [fmt(n.size), "权重"], ...(e.label ? [[e.label, "说明"]] : [])] });
    });
    g.append(el("circle", { cx: hx, cy: hy, r: rad(centre) + 2, fill: colors.get(String(centre.group ?? "")), stroke: v("viz-surface"), "stroke-width": 2 }),
      text(hx - rad(centre) - 8, hy + 5, centre.label ?? centre.id, { size: 13, fill: "viz-ink", anchor: "end", weight: 600 }));
    return { svg: g, height: top + height + 8, targets };
  }
  const cx = width / 2, R = Math.min(170, width * 0.34), cy = top + R + 20;
  const pos = new Map(nodes.map((n, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / nodes.length;
    return [n.id, [cx + R * Math.cos(a), cy + R * Math.sin(a), Math.cos(a)]];
  }));
  const wmax = Math.max(1, ...edges.map((e) => num(e.weight) || 1));
  for (const e of edges) {
    const a = pos.get(e.source), b = pos.get(e.target);
    if (a && b) g.append(el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: v("viz-axis"), "stroke-width": (1 + (2 * (num(e.weight) || 1)) / wmax).toFixed(1) }));
  }
  for (const n of nodes) {
    const [x, y, c] = pos.get(n.id);
    g.append(el("circle", { cx: x, cy: y, r: rad(n), fill: colors.get(String(n.group ?? "")), stroke: v("viz-surface"), "stroke-width": 2 }),
      text(x + (rad(n) + 4) * (c >= 0 ? 1 : -1), y + 4, n.label ?? n.id, { size: 10.5, fill: "viz-ink", anchor: c >= 0 ? "start" : "end" }));
    targets.push({ x, y, title: String(n.label ?? n.id), lines: [[String(n.group ?? ""), "类"], [fmt(n.size), "权重"]] });
  }
  return { svg: g, height: cy + R + 30, targets };
}

// ------------------------------------------------------------------ the figure (for downloads) and the table
/** A standalone SVG document of the specification: title, subtitle, the plot, note and source — light colours inline. */
export function figureSVG(spec) {
  const width = FIGURE_WIDTH;
  const head = [];
  let y = 24;
  head.push(text(20, y, spec.title || "", { size: 15, fill: "viz-ink", weight: 600 }));
  y += 8;
  for (const line of wrap(spec.subtitle || "", width - 40, 11.5)) { y += 16; head.push(text(20, y, line, { size: 11.5 })); }
  y += 12;
  const p = plot(spec, width - 40);
  const body = el("g", { transform: `translate(20 ${y})` }, p.svg);
  let bottom = y + p.height + 6;
  const foot = [];
  for (const line of [spec.note, spec.source].filter(Boolean).flatMap((s) => wrap(s, width - 40, 10))) { bottom += 14; foot.push(text(20, bottom, line, { size: 10, fill: "viz-muted" })); }
  const height = Math.ceil(bottom + 16);
  const root = el("svg", { xmlns: SVG, viewBox: `0 0 ${width} ${height}`, width, height, "font-family": FONT, role: "img", "aria-label": spec.title || "chart" },
    el("title", {}, spec.title || "chart"), el("rect", { width: "100%", height: "100%", fill: v("viz-surface") }), ...head, body, ...foot);
  return new XMLSerializer().serializeToString(root).replace(/var\(--([\w-]+)\)/g, (_, name) => LIGHT[name] || "#888888");
}

function wrap(s, width, size) {
  const out = [];
  let cur = "";
  for (const ch of String(s)) {
    if (textWidth(cur + ch, size) > width) { out.push(cur); cur = ch; } else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}

const csvCell = (x) => {
  const s = x === null || x === undefined ? "" : String(x);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** The table behind the chart as CSV (a network: its edges), with a byte-order mark for spreadsheet programs. */
export function toCSV(spec, bom = true) {
  let lines;
  if (spec.type === "network" && spec.edges?.length) {
    const label = new Map((spec.nodes || []).map((n) => [n.id, n.label ?? n.id]));
    lines = [["来源", "目标", "权重", "说明"], ...spec.edges.map((e) => [label.get(e.source) ?? e.source, label.get(e.target) ?? e.target, e.weight ?? "", e.label ?? ""])];
  } else {
    const cols = spec.columns?.length ? spec.columns : Object.keys(spec.rows?.[0] || {}).map((k) => ({ key: k, label: k }));
    lines = [cols.map((c) => c.label), ...(spec.rows || []).map((r) => cols.map((c) => r[c.key]))];
  }
  return (bom ? "﻿" : "") + lines.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function tableView(spec) {
  const network = spec.type === "network" && spec.edges?.length;
  const cols = network ? [{ key: "source", label: "来源" }, { key: "target", label: "目标" }, { key: "weight", label: "权重" }, { key: "label", label: "说明" }]
    : (spec.columns?.length ? spec.columns : Object.keys(spec.rows?.[0] || {}).map((k) => ({ key: k, label: k })));
  const label = new Map((spec.nodes || []).map((n) => [n.id, n.label ?? n.id]));
  const rows = network ? spec.edges.map((e) => ({ ...e, source: label.get(e.source), target: label.get(e.target) })) : spec.rows;
  const isNum = (c) => rows.every((r) => r[c.key] === null || r[c.key] === undefined || r[c.key] === "" || num(r[c.key]) !== null);
  const numeric = cols.map(isNum);
  return h("div.viz-table-wrap", h("table.viz-table",
    h("thead", h("tr", ...cols.map((c, i) => h(numeric[i] ? "th.num" : "th", c.label)))),
    h("tbody", ...rows.map((r) => h("tr", ...cols.map((c, i) => h(numeric[i] ? "td.num" : "td", numeric[i] ? fmt(r[c.key]) : String(r[c.key] ?? ""))))))));
}

// ------------------------------------------------------------------ the card in the page
const safeName = (s) => String(s || "chart").replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "chart";

/** Save the figure as PNG: the SVG drawn on a canvas at twice its size. */
export async function pngBlob(svgText, scale = 2) {
  const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image();
    await new Promise((ok, fail) => { img.onload = ok; img.onerror = () => fail(new Error("图像生成失败")); img.src = url; });
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    const g = canvas.getContext("2d");
    g.scale(scale, scale);
    g.drawImage(img, 0, 0);
    return await new Promise((ok, fail) => canvas.toBlob((b) => (b ? ok(b) : fail(new Error("图像生成失败"))), "image/png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function save(spec, kind) {
  const name = safeName(spec.title);
  try {
    if (kind === "svg") download(`${name}.svg`, figureSVG(spec), "image/svg+xml");
    else if (kind === "png") downloadBlob(`${name}.png`, await pngBlob(figureSVG(spec)));
    else if (kind === "csv") download(`${name}.csv`, toCSV(spec), "text/csv");
    else download(`${name}.json`, JSON.stringify(spec, null, 2), "application/json");
  } catch (err) {
    toast(`下载失败：${err.message || err}`, "err");
  }
}

function tipBox(host) {
  const box = h("div.viz-tip", { role: "status", "aria-live": "polite", hidden: true });
  host.append(box);
  return {
    show(title, lines, x, y) {
      box.replaceChildren(h("div.tt", title), ...lines.map(([value, name]) => h("div.row", h("b", value), h("span", name))));
      box.hidden = false;
      const w = host.clientWidth;
      const tw = box.offsetWidth;
      Object.assign(box.style, { left: `${Math.max(4, Math.min(w - tw - 4, x - tw / 2))}px`, top: `${Math.max(0, y - box.offsetHeight - 10)}px` });
    },
    hide() { box.hidden = true; },
  };
}

/** How far a pointer is from a hover target (Infinity: not on it) — a line's column, a bar's column, a row, a cell, a dot. */
function hit(t, px, py) {
  const dx = Math.abs(t.x - px), dy = Math.abs(t.y - py);
  if (t.crosshair) return dx;
  if (t.col) return dx <= t.col ? dx : Infinity;
  if (t.row) return dy <= t.row ? dy : Infinity;
  if (t.box) return dx <= t.box[0] && dy <= t.box[1] ? 0 : Infinity;
  const d = Math.hypot(dx, dy);
  return d < 36 ? d : Infinity;
}

function drawInto(host, spec) {
  const width = Math.max(280, Math.floor(host.clientWidth || 0) || 640);
  if (host.dataset.w === String(width)) return;
  host.dataset.w = String(width);
  const p = plot(spec, width);
  const svg = el("svg", { width, height: Math.ceil(p.height), viewBox: `0 0 ${width} ${Math.ceil(p.height)}`, role: "img", tabindex: 0, class: "viz-svg",
    "aria-label": `${spec.title || "图表"}；可切换为表格查看全部数字` }, p.svg);
  const cross = el("line", { y1: p.plotTop ?? 0, y2: p.plotBottom ?? 0, stroke: v("viz-muted"), "stroke-width": 1, visibility: "hidden" });
  svg.append(cross);
  host.replaceChildren(svg);
  const tip = tipBox(host);
  const targets = p.targets;
  let at = -1;
  const show = (i) => {
    if (!targets.length) return;
    at = (i + targets.length) % targets.length;
    const t = targets[at];
    if (t.crosshair) { cross.setAttribute("x1", t.x); cross.setAttribute("x2", t.x); cross.setAttribute("visibility", "visible"); } else cross.setAttribute("visibility", "hidden");
    tip.show(t.title, t.lines, t.x, t.y);
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hide(); };
  svg.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * width, py = ((e.clientY - box.top) / box.height) * p.height;
    let best = -1, dist = Infinity;
    targets.forEach((t, i) => {
      const d = hit(t, px, py);
      if (d < dist) { dist = d; best = i; }
    });
    if (best >= 0) show(best); else hide();
  });
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("focus", () => show(at < 0 ? 0 : at));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", (e) => {
    if (["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"].includes(e.key)) {
      e.preventDefault();
      show((at < 0 ? 0 : at) + (e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1));
    } else if (e.key === "Escape") hide();
  });
}

/** A chart card: title, subtitle, the chart (or its table), downloads; null when the specification cannot be drawn. */
export function chartCard(raw) {
  if (invalid(raw)) return null;
  const spec = normalize(raw);
  const host = h("div.viz-plot");
  let showTable = false;
  const body = h("div.viz-body");
  const toggle = h("button.btn-ghost.viz-toggle", { type: "button", "aria-pressed": "false", title: "以表格查看全部数字" }, "表格");
  const watch = new ResizeObserver(() => { if (host.isConnected && !showTable) drawInto(host, spec); });
  const render = () => {
    body.replaceChildren(showTable ? tableView(spec) : host);
    toggle.textContent = showTable ? "图表" : "表格";
    toggle.setAttribute("aria-pressed", String(showTable));
    if (!showTable) { delete host.dataset.w; queueMicrotask(() => drawInto(host, spec)); }
  };
  toggle.addEventListener("click", () => { showTable = !showTable; render(); });
  watch.observe(host);
  const menu = h("div.viz-menu", { hidden: true, role: "menu" },
    ...[["svg", "SVG 矢量图"], ["png", "PNG 图片"], ["csv", "CSV 数据"], ["json", "JSON 规格"]].map(([kind, label]) =>
      h("button", { type: "button", role: "menuitem", on: { click: () => { menu.hidden = true; save(spec, kind); } } }, label)));
  const more = h("button.btn-ghost.viz-toggle", { type: "button", "aria-haspopup": "menu", title: "下载图表或数据" }, icon("download", "sm"), "下载");
  more.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    closeMenus();
    menu.hidden = !open;
    if (open) menu.querySelector("button")?.focus();
  });
  menu.addEventListener("keydown", (e) => { if (e.key === "Escape") { menu.hidden = true; more.focus(); } });
  if (!menusWatched) { menusWatched = true; document.addEventListener("click", closeMenus); }
  const card = h("figure.viz-card.chart",
    h("figcaption", h("div.cap", h("span.title", spec.title || "图表"), spec.subtitle ? h("span.sub", spec.subtitle) : null),
      h("div.tools", toggle, h("div.viz-dl", more, menu))),
    body,
    spec.note || spec.source ? h("div.viz-foot", [spec.note, spec.source].filter(Boolean).join(" · ")) : null);
  render();
  return card;
}

let menusWatched = false;
function closeMenus() {
  for (const m of document.querySelectorAll(".viz-menu:not([hidden])")) m.hidden = true;
}

// one card per specification object: a turn is drawn again on every streamed update, its charts are not
const cards = new WeakMap();
export function cachedCard(spec) {
  if (!spec || typeof spec !== "object") return null;
  if (!cards.has(spec)) cards.set(spec, chartCard(spec));
  return cards.get(spec);
}

/** The charts a tool result carries (at most ``limit``), ready to keep with the call. */
export function chartsOf(result, limit = 8) {
  const list = result && typeof result === "object" && Array.isArray(result.charts) ? result.charts : [];
  return list.filter((c) => !invalid(c)).slice(0, limit);
}

/** Several charts, one at a time: a row of tabs (their titles) over the chosen one; ``state.at`` keeps the choice
 * when the turn is drawn again.  One chart: the card alone. */
export function chartGallery(specs, state = { at: 0 }) {
  const items = (specs || []).map((s) => [s, cachedCard(s)]).filter(([, card]) => card);
  if (!items.length) return null;
  if (items.length === 1) return h("div.charts", items[0][1]);
  const slot = h("div.chart-slot");
  const tabs = items.map(([s], i) => h("button", { type: "button", role: "tab", title: s.title || `图 ${i + 1}` }, `${i + 1}. ${s.title || "图表"}`));
  const pick = (i, focus = false) => {
    state.at = (i + items.length) % items.length;
    tabs.forEach((t, k) => { t.setAttribute("aria-selected", String(k === state.at)); t.tabIndex = k === state.at ? 0 : -1; });
    slot.replaceChildren(items[state.at][1]);
    if (focus) tabs[state.at].focus();
  };
  tabs.forEach((t, i) => t.addEventListener("click", () => pick(i)));
  const row = h("div.chart-tabs", { role: "tablist", "aria-label": `图表（${items.length} 幅）` }, h("span.count", `图表 ${items.length}`), ...tabs);
  row.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); pick(state.at + (e.key === "ArrowRight" ? 1 : -1), true); }
  });
  pick(Math.min(state.at || 0, items.length - 1));
  return h("div.charts", row, slot);
}

/** The table behind a chart in Markdown (for a conversation exported as Markdown): at most ``limit`` rows. */
export function toMarkdown(spec, limit = 60) {
  const lines = [`**${spec.title || "图表"}**${spec.subtitle ? `　${spec.subtitle}` : ""}`, ""];
  const cell = (x) => String(x ?? "").replace(/\|/g, "\\|").replace(/\n/g, " ");
  let cols, rows;
  if (spec.type === "network" && spec.edges?.length) {
    const label = new Map((spec.nodes || []).map((n) => [n.id, n.label ?? n.id]));
    cols = ["来源", "目标", "权重", "说明"];
    rows = spec.edges.map((e) => [label.get(e.source) ?? e.source, label.get(e.target) ?? e.target, e.weight ?? "", e.label ?? ""]);
  } else {
    const c = spec.columns?.length ? spec.columns : Object.keys(spec.rows?.[0] || {}).map((k) => ({ key: k, label: k }));
    cols = c.map((x) => x.label);
    rows = (spec.rows || []).map((r) => c.map((x) => r[x.key]));
  }
  if (!cols.length) return "";
  lines.push(`| ${cols.map(cell).join(" | ")} |`, `| ${cols.map(() => "---").join(" | ")} |`);
  for (const r of rows.slice(0, limit)) lines.push(`| ${r.map(cell).join(" | ")} |`);
  if (rows.length > limit) lines.push("", `（共 ${rows.length} 行，此处列出前 ${limit} 行）`);
  const foot = [spec.note, spec.source].filter(Boolean).join(" · ");
  if (foot) lines.push("", `*${foot}*`);
  return lines.join("\n");
}
