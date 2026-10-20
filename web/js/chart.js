// 图表 — the chart specifications the study tools return (taochronos/plugins/classics/study/charts.py) drawn as SVG, with a
// table view and downloads.  The same specification, written by the model in a ```chart block, is drawn the same way
// (markdown.js).
//
// Two styles of one drawing (as the Python figures, study/svg.py, whose layout this follows):
// * the page's (screen): hairline, solid, recessive grid and axes; bars at most 24 px thick with a 4 px rounded data end;
//   2 px lines; 8 px markers ringed with the surface; a 2 px surface gap between stacked segments; a legend whenever there
//   are two series or more; values and labels in ink, never in a series colour; hover and keyboard focus give the
//   numbers, and the table gives every one of them;
// * a journal's (期刊样式, for a paper): white, black L-shaped axes with outward ticks, no grid, the y-axis title turned
//   along its axis, square bars, error bars with caps, 8 pt text at the printed width — 85 mm a single column, 120 mm one
//   and a half, 175 mm two — and the figure's number and caption under it (图 1　…, its notes, its source); several
//   charts of a result as one figure in panels (A, B …).  Downloaded as SVG, as PNG at 300 or 600 dpi (the resolution
//   written in the file) or as TIFF (what many journals ask for), with the data as CSV and the specification as JSON.
// Colours are tokens (--viz-1 … --viz-8, --viz-other, the --viz-seq ramp; css/app.css, light and dark), validated for
// colour-vision deficiency; a downloaded figure takes the light ones, a journal's its black and white.

import { pngWithDpi, tiff } from "./bytes.js";
import { cachedTable, defuse, menuButton, saveTables } from "./table.js";
import { download, downloadBlob, h, icon, storage, toast } from "./util.js";
import { T } from "./i18n.js";

const SVG = "http://www.w3.org/2000/svg";
export const TYPES = ["line", "bar", "hbar", "stack", "heatmap", "range", "box", "forest", "scatter", "dendrogram", "timeline", "network"];
const FIGURE_WIDTH = 760;
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif";
const FONT_JOURNAL = "Arial, Helvetica, 'Noto Sans CJK SC', 'Source Han Sans SC', 'PingFang SC', 'Microsoft YaHei', SimHei, sans-serif";
const SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
// the light tokens, for a downloaded figure (css/app.css holds both modes for the page)
export const LIGHT = {
  "viz-1": "#2a78d6", "viz-2": "#eb6834", "viz-3": "#1baf7a", "viz-4": "#eda100", "viz-5": "#e87ba4", "viz-6": "#008300",
  "viz-7": "#6250d6", "viz-8": "#e34948", "viz-other": "#b3b1aa", "viz-surface": "#fcfcfb", "viz-ink": "#0b0b0b",
  "viz-ink-2": "#52514e", "viz-muted": "#898781", "viz-grid": "#e1e0d9", "viz-axis": "#c3c2b7", "viz-empty": "#f0efec",
  ...Object.fromEntries(SEQ.map((c, i) => [`viz-seq-${i}`, c])),
};
// a journal's: the same hues on white paper, black axes and text
export const JOURNAL = { ...LIGHT, "viz-surface": "#ffffff", "viz-ink": "#000000", "viz-ink-2": "#1a1a1a", "viz-muted": "#4d4d4d",
  "viz-grid": "#e6e6e6", "viz-axis": "#000000", "viz-empty": "#f2f2f2", "viz-link": "#9a9a9a" };
export const WIDTHS = { single: 85, onehalf: 120, double: 175 }; // a journal's column widths, mm
const PX_PER_MM = 72 / 25.4 / (8 / 10.5); // a journal figure's units: 10.5 of them print as 8 pt
const RAMP = 13;
const v = (name) => `var(--${name})`;
let J = false; // drawing for a journal (figureNode, panelsNode): L axes, outward ticks, no grid, square bars, capped whiskers

// ------------------------------------------------------------------ checking a specification
/** null when the specification can be drawn, else why not (a model's ```chart block is checked before it is drawn). */
export function invalid(spec) {
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return T("图表规格应为 JSON 对象");
  if (!TYPES.includes(spec.type)) return T`不支持的图表类型：${spec.type}（可用 ${TYPES.join(T("、"))}）`;
  if (spec.type === "network") {
    if (!Array.isArray(spec.nodes) || !spec.nodes.length) return T("网络图需要 nodes");
    if (spec.nodes.length > 400 || (spec.edges || []).length > 4000) return T("网络过大（至多 400 个节点、4000 条边）");
    return null;
  }
  if (spec.type === "dendrogram") {
    const n = Array.isArray(spec.labels) ? spec.labels.length : 0;
    if (n < 2 || n > 200) return T("树状图需要 labels（2 至 200 项）");
    if (!Array.isArray(spec.merges) || spec.merges.length !== n - 1) return T("树状图需要 merges（n − 1 次合并）");
    if (!spec.merges.every((m, i) => Array.isArray(m) && m.length >= 3 && [m[0], m[1]].every((c) => Number.isInteger(c) && c >= 0 && c < n + i) && num(m[2]) !== null)) return T("树状图的 merges 不合法");
    return null;
  }
  if (!Array.isArray(spec.rows) || !spec.rows.length) return T("图表需要 rows（数据行）");
  if (spec.rows.length > 2000) return T("数据行过多（至多 2000 行）");
  if (["line", "bar", "hbar", "stack", "range", "box"].includes(spec.type) && !spec.x?.key) return T("需要 x.key（类别字段）");
  if (["line", "bar", "hbar", "stack"].includes(spec.type) && !(Array.isArray(spec.series) && spec.series.length)) return T("需要 series（数值字段）");
  if (spec.type === "heatmap" && !(spec.x?.key && spec.y?.key && spec.value?.key)) return T("热图需要 x.key、y.key 与 value.key");
  if (spec.type === "range" && !spec.range?.median) return T("区间图需要 range.median 等字段");
  if (spec.type === "box" && !boxRows(spec).length) return T("箱线图需要每行的 q1、median、q3，或 values（数值数组）");
  if (spec.type === "forest" && !(spec.y?.key && spec.estimate?.key)) return T("森林图需要 y.key 与 estimate.key（及 estimate.lo、estimate.hi）");
  if (spec.type === "scatter" && !(spec.x?.key && spec.y?.key)) return T("散点图需要 x.key 与 y.key");
  if (spec.type === "timeline" && !spec.rows.some((r) => num(r.start) !== null)) return T("时间线需要 rows[].start（年份）");
  return null;
}

/** A model's specification made whole: columns from the rows when it gives none, series labels from their keys. */
export function normalize(spec) {
  const out = { ...spec };
  if (out.type === "dendrogram" && !Array.isArray(out.rows)) out.rows = out.labels.map((l) => ({ label: l }));
  if (!Array.isArray(out.columns) || !out.columns.length) {
    const keys = [...new Set((out.rows || []).flatMap((r) => Object.keys(r || {}).filter((k) => !Array.isArray(r[k]))))];
    out.columns = keys.map((k) => ({ key: k, label: k }));
  }
  if (Array.isArray(out.series)) out.series = out.series.map((s) => (typeof s === "string" ? { key: s, label: s } : { label: s.key, ...s }));
  if (out.estimate && !out.estimate.label) out.estimate = { ...out.estimate, label: out.estimate.key };
  return out;
}

// ------------------------------------------------------------------ numbers and text
const num = (x) => (x === null || x === undefined || x === "" || typeof x === "boolean" || Number.isNaN(Number(x)) || !Number.isFinite(Number(x)) ? null : Number(x));

export function fmt(x, percent = false) {
  const n = num(x);
  if (n === null) return x === null || x === undefined ? "" : String(x);
  if (percent) return `${(n * 100).toFixed(Math.abs(n) >= 0.1 || n === 0 ? 0 : 1)}%`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  if (Number.isInteger(n)) return String(n);
  return String(Number(n.toPrecision(3)));
}

/** An estimate (an odds ratio) to the precision its size deserves, as the tables print it: 67.6, 2.43, 0.09. */
export function fmtEst(x) {
  const n = num(x);
  if (n === null) return "";
  const a = Math.abs(n);
  return a >= 100 ? n.toFixed(0) : a >= 10 ? n.toFixed(1) : a >= 0.01 || a === 0 ? n.toFixed(2) : n.toFixed(3);
}

const yearText = (t) => (t < 0 ? T`前${Math.round(-t)}` : String(Math.round(t)));

const WIDE = new Set(["…", "—"]); // as wide as a CJK character in the fonts a figure names

/** Width of a text in px: a CJK character (and an ellipsis or a dash) as wide as the font size, others about 0.58 of it. */
export function textWidth(text, size) {
  let w = 0;
  for (const ch of String(text)) w += ch.codePointAt(0) > 0x2e80 || WIDE.has(ch) ? size : size * 0.58;
  return w;
}

/** A label cut to the room it has, with an ellipsis (the table and the hover keep it whole). */
export function clipText(text, size, room) {
  const s = String(text ?? "");
  if (textWidth(s, size) <= room) return s;
  let out = "";
  for (const ch of s) {
    if (textWidth(out + ch + "…", size) > room) break;
    out += ch;
  }
  return (out || [...s][0] || "") + "…";
}

/** The ink of a label set at (x, y): [x0, y0, x1, y1] — its width by textWidth, its height the em box. */
const boxOf = (x, y, w, size, anchor = "start") => {
  const x0 = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
  return [x0, y - 0.84 * size, x0 + w, y + 0.16 * size];
};
const clash = (a, b, gap = 1) => a[0] < b[2] + gap && b[0] < a[2] + gap && a[1] < b[3] + gap && b[1] < a[3] + gap;

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

/** Ticks of a log axis over [lo, hi]: the powers of ten, with 2 and 5 between them when the axis spans little. */
export function logTicks(lo, hi) {
  const a = Math.floor(Math.log10(lo)), b = Math.ceil(Math.log10(hi));
  const mults = b - a <= 2 ? [1, 2, 5] : [1];
  const out = [];
  for (let e = a; e <= b; e++) for (const m of mults) { const t = Number((m * 10 ** e).toPrecision(6)); if (t >= lo * 0.999 && t <= hi * 1.001) out.push(t); }
  return out.length ? out : [lo, hi];
}

/** The categorical tokens in order, 其他 in the de-emphasis grey (never a ninth hue). */
export function seriesColors(labels) {
  let k = 0;
  return labels.map((l) => (l === "其他" || l === T("其他") ? v("viz-other") : k < 8 ? v(`viz-${++k}`) : v("viz-other")));
}

/** Colours by group: by its place in the order the specification gives (groups), so that a category keeps its colour in
 * every chart of a result whichever groups each one shows; groups it does not list follow.  The groups seen, in order. */
function groupColors(spec, seen) {
  const listed = (Array.isArray(spec.groups) ? spec.groups : []).map(String);
  const order = [...listed, ...seen.filter((g) => !listed.includes(g))];
  const colors = seriesColors(order);
  return new Map(order.map((g, i) => [g, colors[i]]).filter(([g]) => seen.includes(g)));
}

/** A box plot's numbers (Tukey): quartiles, whiskers at the furthest values within 1.5 IQR of the box, mean and n. */
export function tukey(values) {
  const s = values.map(num).filter((x) => x !== null).sort((a, b) => a - b);
  if (!s.length) return null;
  const q = (p) => { const k = (s.length - 1) * p, a = Math.floor(k), b = Math.min(a + 1, s.length - 1); return s[a] + (s[b] - s[a]) * (k - a); };
  const q1 = q(0.25), median = q(0.5), q3 = q(0.75);
  const inside = s.filter((x) => x >= q1 - 1.5 * (q3 - q1) && x <= q3 + 1.5 * (q3 - q1));
  const lo = (inside.length ? inside : s)[0], hi = (inside.length ? inside : s).at(-1);
  return { n: s.length, min: s[0], q1, median, q3, lo, hi, max: s.at(-1), mean: s.reduce((a, b) => a + b, 0) / s.length };
}

/** A box plot's rows with their numbers: as the specification gives them, or computed from their values. */
export function boxRows(spec) {
  const xkey = spec.x?.key;
  const points = spec.points && typeof spec.points === "object" ? spec.points : {};
  return (spec.rows || []).flatMap((r) => {
    if (["q1", "median", "q3"].every((k) => num(r[k]) !== null)) return [r];
    const t = tukey(Array.isArray(r.values) ? r.values : points[String(r[xkey])] || []);
    return t ? [{ ...r, ...t }] : [];
  });
}

// ------------------------------------------------------------------ SVG building
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, val] of Object.entries(attrs)) if (val !== null && val !== undefined && val !== false) node.setAttribute(k, String(val));
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
};
const color = (c) => (c.startsWith("var(") || c.startsWith("#") ? c : v(c));
const text = (x, y, s, { size = 11, fill = "viz-ink-2", anchor = "start", weight = null, cls = null, rotate = null } = {}) =>
  el("text", { x: x.toFixed(1), y: y.toFixed(1), "font-size": size, fill: color(fill), "text-anchor": anchor, "font-weight": weight, class: cls,
    transform: rotate === null ? null : `rotate(${rotate} ${x.toFixed(1)} ${y.toFixed(1)})` }, String(s ?? ""));
const line = (x1, y1, x2, y2, stroke = "viz-axis", width = 1, extra = {}) =>
  el("line", { x1: x1.toFixed(1), y1: y1.toFixed(1), x2: x2.toFixed(1), y2: y2.toFixed(1), stroke: color(stroke), "stroke-width": width, ...extra });

function roundedBar(x, y, w, hgt, up = true, r = J ? 0 : 4) {
  r = Math.min(r, w / 2, Math.abs(hgt));
  if (!(hgt > 0) || !(w > 0)) return "";
  if (r <= 0) return `M${x},${y}h${w}v${hgt}h${-w}Z`;
  if (up) return `M${x},${y + hgt}L${x},${y + r}Q${x},${y} ${x + r},${y}L${x + w - r},${y}Q${x + w},${y} ${x + w},${y + r}L${x + w},${y + hgt}Z`;
  return `M${x},${y}L${x + w - r},${y}Q${x + w},${y} ${x + w},${y + r}L${x + w},${y + hgt - r}Q${x + w},${y + hgt} ${x + w - r},${y + hgt}L${x},${y + hgt}Z`;
}

/** An interval as a vertical line, with caps in a journal. */
function whisker(g, x, y1, y2, stroke = "viz-ink-2", cap = 4) {
  g.append(line(x, y1, x, y2, stroke));
  if (J) g.append(line(x - cap, y1, x + cap, y1, stroke), line(x - cap, y2, x + cap, y2, stroke));
}

/** The plot of a specification at a width: {svg, height, targets} — targets: the hover points ({x, y, lines}). */
export function plot(spec, width) {
  const draw = { line: series, bar: series, stack: series, hbar, heatmap, range, box, forest, scatter, dendrogram, timeline, network }[spec.type];
  return draw(spec, Math.max(280, width));
}

function legend(items, width, kind = "rect") {
  if (items.length < 2) return { nodes: [], height: 0 };
  const nodes = [];
  let x = 0, y = 12;
  for (const [full, c] of items) {
    const label = clipText(full, 11, width - 20);
    const w = 18 + textWidth(label, 11) + 16;
    if (x + w > width && x > 0) { x = 0; y += 18; }
    nodes.push(kind === "line" ? line(x, y - 4, x + 12, y - 4, c, 2) : el("rect", { x, y: y - 9, width: 10, height: 10, rx: J ? 0 : 2, fill: c }));
    nodes.push(text(x + 16, y, label, { size: 11 }));
    x += w;
  }
  return { nodes, height: y + 10 };
}

/** Are these counts (whole numbers)?  Their axis then has no fractions. */
const whole = (values) => values.every((x) => x === null || Number.isInteger(x));

/** The room an axis on the left needs: its tick labels, and in a journal its title turned along it. */
function leftFor(tickTexts, label) {
  if (!J) return 52;
  return Math.max(40, Math.max(0, ...tickTexts.map((t) => textWidth(t, 10.5))) + 18 + (label ? 20 : 0));
}

/** A y axis; on screen its title above it, ``head`` over the plot's top. */
function yAxis(g, left, right, top, bottom, lo, hi, percent, label, integer = false, head = 8) {
  const scale = (val) => (hi > lo ? bottom - ((val - lo) / (hi - lo)) * (bottom - top) : bottom);
  const tks = ticks(lo, hi, 5, integer && !percent);
  if (J) {
    g.append(line(left, top, left, bottom));
    for (const t of tks) g.append(line(left - 4, scale(t), left, scale(t)), text(left - 7, scale(t) + 3.5, fmt(t, percent), { size: 10.5, anchor: "end", cls: "tick" }));
    g.append(line(left, bottom, right, bottom));
    if (label) {
      const widest = Math.max(0, ...tks.map((t) => textWidth(fmt(t, percent), 10.5)));
      g.append(text(left - 7 - widest - 9, (top + bottom) / 2, label, { size: 11, fill: "viz-ink", anchor: "middle", rotate: -90 }));
    }
    return scale;
  }
  for (const t of tks) {
    const y = scale(t);
    g.append(line(left, y, right, y, "viz-grid"), text(left - 6, y + 4, fmt(t, percent), { size: 10.5, fill: "viz-muted", anchor: "end", cls: "tick" }));
  }
  g.append(line(left, bottom, right, bottom));
  if (label) g.append(text(left, top - head, label, { size: 10.5, fill: "viz-muted" }));
  return scale;
}

const TURNED = 112; // the longest a turned category label runs before it is cut

/** Category labels under the axis (ticks above them in a journal); when they do not fit their band, turned — at 40°
 * while neighbours clear each other, upright (reading upwards) in a narrower band, and only every k-th of them in a band
 * narrower than a line of text; in a journal the axis title under them.  The y under them. */
function xLabels(g, cats, xs, bottom, band, label = null) {
  if (J) for (const x of xs) g.append(line(x, bottom, x, bottom + 4));
  const longest = Math.max(0, ...cats.map((c) => textWidth(c, 10.5)));
  let end;
  if (longest <= band - 4) {
    cats.forEach((c, i) => g.append(text(xs[i], bottom + 16, c, { size: 10.5, anchor: "middle" })));
    end = bottom + 22;
  } else if (band >= 19) { // at 40° two neighbours are band × sin 40° apart: a line of text needs 12
    const shown = cats.map((c, i) => clipText(c, 10.5, Math.min(TURNED, (xs[i] - 8) / 0.77))); // the first ones: not past the left edge
    shown.forEach((c, i) => g.append(text(xs[i], bottom + 12, c, { size: 10.5, anchor: "end", rotate: -40 })));
    end = bottom + 16 + Math.max(0, ...shown.map((c) => textWidth(c, 10.5))) * 0.65;
  } else {
    const every = Math.max(1, Math.ceil(12.5 / Math.max(band, 1e-9)));
    const shown = cats.map((c) => clipText(c, 10.5, TURNED));
    shown.forEach((c, i) => { if (i % every === 0) g.append(text(xs[i] + 3.6, bottom + 8, c, { size: 10.5, anchor: "end", rotate: -90 })); });
    end = bottom + 14 + Math.max(0, ...shown.map((c) => textWidth(c, 10.5)));
  }
  if (J && label && xs.length) { g.append(text((xs[0] + xs.at(-1)) / 2, end + 12, label, { size: 11, fill: "viz-ink", anchor: "middle" })); end += 16; }
  return end;
}

/** A numeric axis under a plot: its line and ticks, and its title; on screen a light grid up to ``gridTop``. */
function xAxisNumeric(g, left, right, bottom, lo, hi, { label = "", percent = false, year = false, log = false, gridTop = null } = {}) {
  let scale, tks;
  if (log) {
    const a = Math.log10(lo), b = Math.log10(hi);
    scale = (val) => left + ((Math.log10(Math.max(val, 1e-12)) - a) / (b - a)) * (right - left);
    tks = logTicks(lo, hi);
  } else {
    scale = (val) => (hi > lo ? left + ((val - lo) / (hi - lo)) * (right - left) : left);
    tks = ticks(lo, hi, 5);
  }
  const label_ = (t) => (year ? yearText(t) : log ? String(Number(t.toPrecision(6))) : fmt(t, percent));
  g.append(line(left, bottom, right, bottom));
  for (const t of tks) {
    const x = scale(t);
    if (J) g.append(line(x, bottom, x, bottom + 4));
    else if (gridTop !== null) g.append(line(x, gridTop, x, bottom, "viz-grid"));
    g.append(text(x, bottom + 15, label_(t), { size: 10.5, fill: J ? "viz-ink-2" : "viz-muted", anchor: "middle", cls: "tick" }));
  }
  let end = bottom + 20;
  if (label) { g.append(text((left + right) / 2, end + 11, label, { size: J ? 11 : 10.5, fill: J ? "viz-ink" : "viz-muted", anchor: "middle" })); end += 16; }
  return { scale, end };
}

// ------------------------------------------------------------------ the plots
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
  const left = leftFor(ticks(lo, hi, 5, integer && !percent).map((t) => fmt(t, percent)), y.label), right = width - 16;
  const top = lg.height + 22, bottom = top + Math.min(280, Math.max(J ? 170 : 180, width * (J ? 0.5 : 0.42)));
  const scale = yAxis(g, left, right, top, bottom, lo, hi, percent, y.label, integer);
  const band = (right - left) / Math.max(rows.length, 1);
  const xs = rows.map((_, i) => left + band * (i + 0.5));
  const targets = [];
  if (kind === "line") {
    const lines = [], ends = [];
    list.forEach((s, i) => {
      if (s.lo && s.hi) {
        const up = rows.map((r, j) => [xs[j], num(r[s.hi])]).filter(([, n]) => n !== null);
        const down = rows.map((r, j) => [xs[j], num(r[s.lo])]).filter(([, n]) => n !== null).reverse();
        if (up.length && down.length) g.append(el("polygon", { points: [...up, ...down].map(([a, b]) => `${a.toFixed(1)},${scale(b).toFixed(1)}`).join(" "), fill: colors[i], "fill-opacity": J ? 0.12 : 0.1 }));
      }
      const pts = rows.map((r, j) => [xs[j], num(r[s.key])]).filter(([, n]) => n !== null);
      if (pts.length >= 2) g.append(el("polyline", { points: pts.map(([a, b]) => `${a.toFixed(1)},${scale(b).toFixed(1)}`).join(" "), fill: "none", stroke: colors[i], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      for (const [a, b] of pts) g.append(el("circle", { cx: a.toFixed(1), cy: scale(b).toFixed(1), r: 4, fill: colors[i], stroke: v("viz-surface"), "stroke-width": 2 }));
      lines.push(pts.map(([a, b]) => [a, scale(b)]));
      if (pts.length) ends.push([pts.at(-1)[0], scale(pts.at(-1)[1]), fmt(pts.at(-1)[1], percent)]);
    });
    if (!J) g.append(...endLabels(ends, lines, top)); // each line's end value, where it clears the other labels, dots and lines
    rows.forEach((r, j) => targets.push({ x: xs[j], y: top, crosshair: true, title: String(r[xkey] ?? ""),
      lines: list.map((s) => [fmt(r[s.key], percent) + (s.lo && s.hi && num(r[s.lo]) !== null ? T`（${fmt(r[s.lo], percent)}–${fmt(r[s.hi], percent)}）` : ""), s.label]) }));
  } else if (kind === "bar") {
    const n = Math.max(list.length, 1);
    const bw = Math.max(3, Math.min(24, (band - 8) / n - 2));
    // a value over each bar of a single series — when every one of them fits its band (else none: the table has them)
    const labelled = list.length === 1 && rows.length <= 14 && rows.every((r) => num(r[list[0].key]) === null || textWidth(fmt(r[list[0].key], percent), 10) <= band - 3);
    rows.forEach((r, j) => {
      const x0 = xs[j] - ((bw + 2) * n) / 2 + 1;
      list.forEach((s, i) => {
        const val = num(r[s.key]);
        if (val === null) return;
        const yv = scale(Math.max(val, lo)), base = scale(Math.max(lo, 0));
        g.append(el("path", { d: val >= 0 ? roundedBar(x0 + i * (bw + 2), Math.min(yv, base), bw, Math.abs(base - yv)) : "", fill: colors[i] }));
        if (s.lo && s.hi && num(r[s.lo]) !== null && num(r[s.hi]) !== null) whisker(g, x0 + i * (bw + 2) + bw / 2, scale(num(r[s.lo])), scale(num(r[s.hi])), "viz-ink-2", Math.min(4, bw / 2));
        if (labelled) g.append(text(x0 + bw / 2, yv - 5, fmt(val, percent), { size: 10, anchor: "middle" }));
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
  const end = xLabels(g, rows.map((r) => String(r[xkey] ?? "")), xs, bottom, band, spec.x.label);
  return { svg: g, height: end + 4, targets, plotTop: top, plotBottom: bottom };
}

/** The end value of each line: above its last point, else below it, wherever it clears the labels set before it, every
 * dot and every line (sampled along); a value with room in neither place is left to the hover and the table. */
function endLabels(ends, lines, top) {
  const out = [], placed = [];
  const dots = lines.flat();
  const crosses = (pts, b) => pts.slice(1).some(([x2, y2], k) => {
    const [x1, y1] = pts[k];
    const steps = Math.max(2, Math.floor(Math.hypot(x2 - x1, y2 - y1) / 2));
    for (let i = 0; i <= steps; i++) {
      const x = x1 + ((x2 - x1) * i) / steps, y = y1 + ((y2 - y1) * i) / steps;
      if (x >= b[0] - 1 && x <= b[2] + 1 && y >= b[1] - 1 && y <= b[3] + 1) return true;
    }
    return false;
  });
  for (const [x, y, label] of ends) {
    const w = textWidth(label, 10.5);
    for (const by of [y - 9, y + 17]) {
      const b = boxOf(x, by, w, 10.5, "middle");
      if (b[1] < top - 18 || placed.some((p) => clash(b, p)) || dots.some(([dx, dy]) => clash(b, [dx - 6, dy - 6, dx + 6, dy + 6], 0)) || lines.some((pts) => crosses(pts, b))) continue;
      placed.push(b);
      out.push(text(x, by, label, { size: 10.5, fill: "viz-ink", anchor: "middle" }));
      break;
    }
  }
  return out;
}

function hbar(spec, width) {
  const rows = spec.rows;
  const xkey = spec.x.key;
  const s = spec.series[0];
  const percent = Boolean(spec.y?.percent);
  const g = el("g");
  const labelW = Math.min(width * 0.36, Math.max(...rows.map((r) => textWidth(r[xkey] ?? "", 11)), 30) + 12);
  const left = labelW, right = width - 60;
  const top = 8, step = J ? 20 : 24, bh = J ? 13 : 16;
  const vals = rows.map((r) => num(r[s.key]) || 0);
  const lo = Math.min(0, ...vals), hi = niceMax(Math.max(0, ...vals));
  const scale = (val) => (hi > lo ? left + ((val - lo) / (hi - lo)) * (right - left) : left);
  const bottom = top + step * rows.length;
  for (const t of ticks(lo, hi, 4, whole(vals) && !percent)) {
    const x = scale(t);
    g.append(J ? line(x, bottom, x, bottom + 4) : line(x, top, x, bottom, "viz-grid"),
      text(x, bottom + 15, fmt(t, percent), { size: 10.5, fill: J ? "viz-ink-2" : "viz-muted", anchor: "middle", cls: "tick" }));
  }
  const targets = [];
  rows.forEach((r, i) => {
    const val = num(r[s.key]) || 0;
    const y = top + i * step + (step - bh) / 2;
    g.append(text(left - 8, y + bh - 3.5, clipText(r[xkey] ?? "", 11, left - 10), { size: 11, anchor: "end" }));
    const x0 = scale(0), x1 = scale(val);
    g.append(x1 >= x0 ? el("path", { d: roundedBar(x0, y, x1 - x0, bh, false), fill: v("viz-1") }) : el("rect", { x: x1, y, width: x0 - x1, height: bh, fill: v("viz-1") }));
    g.append(text(Math.max(x0, x1) + 6, y + bh - 3.5, fmt(val, percent), { size: 10.5, fill: "viz-ink" }));
    const extra = (spec.columns || []).filter((c) => c.key !== xkey && c.key !== s.key).map((c) => [fmt(r[c.key]), c.label]).filter(([x]) => x);
    targets.push({ x: Math.max(x0, x1), y: y + bh / 2, row: step / 2, title: String(r[xkey] ?? ""), lines: [[fmt(val, percent), s.label || ""], ...extra] });
  });
  g.append(line(scale(0), top, scale(0), bottom));
  let end = bottom + 20;
  if (J) {
    g.append(line(left, bottom, right, bottom));
    if (spec.y?.label) { g.append(text((left + right) / 2, end + 11, spec.y.label, { size: 11, fill: "viz-ink", anchor: "middle" })); end += 16; }
  }
  return { svg: g, height: end, targets };
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
  const ch = J ? 20 : 24;
  const centre = (i) => left + cw * (i + 0.5);
  let top;
  if (xs.every((x) => textWidth(x, 10.5) <= cw - 2)) {
    top = 22;
    xs.forEach((x, i) => g.append(text(centre(i), top - 8, x, { size: 10.5, anchor: "middle" })));
  } else if (cw >= 19) { // turned 40°, each reaching up and to the right: cut where it would leave the figure
    const shown = xs.map((x, i) => clipText(x, 10.5, Math.min(TURNED, (width - 2 - centre(i)) / 0.77)));
    top = 14 + Math.max(0, ...shown.map((x) => textWidth(x, 10.5))) * 0.65;
    shown.forEach((x, i) => g.append(text(centre(i), top - 6, x, { size: 10.5, rotate: -40 })));
  } else { // upright, reading upwards: narrow columns
    const shown = xs.map((x) => clipText(x, 10.5, TURNED));
    top = 14 + Math.max(0, ...shown.map((x) => textWidth(x, 10.5)));
    shown.forEach((x, i) => g.append(text(centre(i) + 3.6, top - 6, x, { size: 10.5, rotate: -90 })));
  }
  const targets = [];
  ys.forEach((y, j) => {
    const cy = top + ch * j;
    g.append(text(left - 8, cy + ch / 2 + 4, clipText(y, 11, left - 10), { size: 11, anchor: "end" }));
    xs.forEach((x, i) => {
      const r = cell.get(`${x}\u0000${y}`);
      const val = r ? num(r[vk]) : null;
      const k = val === null || val <= 0 ? -1 : Math.min(RAMP - 1, Math.round((val / vmax) * (RAMP - 1)));
      g.append(el("rect", { x: (left + cw * i + 1).toFixed(1), y: (cy + 1).toFixed(1), width: (cw - 2).toFixed(1), height: ch - 2, rx: J ? 0 : 2, fill: k < 0 ? v("viz-empty") : v(`viz-seq-${k}`) }));
      if (val !== null && val > 0) {
        const label = fmt(val, percent);
        if (textWidth(label, 10) <= cw - 6) g.append(text(centre(i), cy + ch / 2 + 4, label, { size: 10, anchor: "middle", fill: k >= 6 ? "#ffffff" : "viz-ink" }));
      }
      const extra = r ? (spec.columns || []).filter((c) => ![xk, yk, vk].includes(c.key)).map((c) => [fmt(r[c.key]), c.label]).filter(([t]) => t) : [];
      targets.push({ x: centre(i), y: cy + ch / 2, box: [cw / 2, ch / 2], title: `${y} · ${x}`, lines: [[val === null ? "—" : fmt(val, percent), spec.value.label || ""], ...extra] });
    });
  });
  const bottom = top + ch * ys.length;
  g.append(...ramp(left, bottom, width, fmt(vmax, percent), spec.value.label || ""));
  return { svg: g, height: bottom + 42, targets };
}

/** A heatmap's colour scale under it: the ramp from 0 to its largest value, and what the colour counts after it — the
 * steps narrowed, then the whole moved left, then the label cut, as a narrow figure needs. */
function ramp(x0, bottom, width, topLabel, label) {
  const room = width - 2, lw = textWidth(label, 10.5);
  let seg = 14;
  if (x0 + RAMP * seg + 10 + lw > room) seg = Math.max(7, (room - x0 - 10 - lw) / RAMP);
  if (x0 + RAMP * seg + 10 + lw > room) x0 = Math.max(0, room - lw - 10 - RAMP * seg);
  const end = x0 + RAMP * seg;
  const out = [];
  for (let k = 0; k < RAMP; k++) out.push(el("rect", { x: (x0 + k * seg).toFixed(1), y: bottom + 12, width: seg.toFixed(1), height: 8, fill: v(`viz-seq-${k}`) }));
  out.push(text(x0, bottom + 34, "0", { size: 10, fill: "viz-muted" }), text(end, bottom + 34, topLabel, { size: 10, fill: "viz-muted", anchor: "end" }),
    text(end + 10, bottom + 20, clipText(label, 10.5, room - end - 10), { size: 10.5, fill: "viz-muted" }));
  return out;
}

function range(spec, width) {
  const rows = spec.rows;
  const keys = spec.range;
  const xkey = spec.x.key;
  const g = el("g");
  const vals = rows.flatMap((r) => [num(r[keys.min]), num(r[keys.max])]).filter((n) => n !== null);
  const boxes = rows.flatMap((r) => [num(r[keys.q3]), num(r[keys.median])]).filter((n) => n !== null);
  // the axis reads the boxes: a few very large values would flatten them — it stops at 2.5× the largest upper quartile,
  // longer whiskers are cut there with their value at the top (the table has every number)
  const hi = niceMax(Math.min(Math.max(1, ...vals), Math.max(1, ...boxes) * 2.5));
  const left = leftFor(ticks(0, hi).map((t) => fmt(t)), spec.y?.label), right = width - 16, top = 20, bottom = top + Math.min(260, Math.max(170, width * 0.38));
  const scale = yAxis(g, left, right, top, bottom, 0, hi, false, spec.y?.label);
  const clip = (n) => Math.min(n, hi);
  const band = (right - left) / Math.max(rows.length, 1);
  const xs = rows.map((_, i) => left + band * (i + 0.5));
  const targets = [];
  rows.forEach((r, i) => {
    const [lo_, q1, med, q3, hi_] = ["min", "q1", "median", "q3", "max"].map((k) => num(r[keys[k]]));
    const x = xs[i];
    if (lo_ !== null && hi_ !== null) {
      whisker(g, x, scale(clip(lo_)), scale(clip(hi_)), "viz-1");
      if (hi_ > hi) {
        g.append(el("path", { d: `M${x - 4},${top + 6}L${x},${top}L${x + 4},${top + 6}`, fill: "none", stroke: v("viz-1"), "stroke-width": 1 }));
        if (textWidth(`↑${fmt(hi_)}`, 10) <= band - 14) g.append(text(x + 6, top + 6, `↑${fmt(hi_)}`, { size: 10, fill: "viz-muted" })); // clear of the next whisker
      }
    }
    if (q1 !== null && q3 !== null) {
      const y1 = scale(clip(q3)), y3 = scale(clip(q1));
      g.append(el("rect", { x: x - 10, y: y1, width: 20, height: Math.max(y3 - y1, 1), rx: J ? 0 : 3, fill: v("viz-1"), "fill-opacity": 0.25, stroke: v("viz-1"), "stroke-width": 1 }));
    }
    if (med !== null) {
      g.append(el("circle", { cx: x, cy: scale(clip(med)), r: 4.5, fill: v("viz-1"), stroke: v("viz-surface"), "stroke-width": 2 }));
      if (textWidth(fmt(med), 10.5) <= band - 27) g.append(text(x + 14, scale(clip(med)) + 4, fmt(med), { size: 10.5, fill: "viz-ink" })); // beside its box, clear of the next one
    }
    targets.push({ x, y: scale(clip(med ?? 0)), col: band / 2, title: String(r[xkey] ?? ""),
      lines: (spec.columns || []).filter((c) => c.key !== xkey).map((c) => [fmt(r[c.key]), c.label]) });
  });
  const end = xLabels(g, rows.map((r) => String(r[xkey] ?? "")), xs, bottom, band, spec.x.label);
  return { svg: g, height: end + 4, targets };
}

/** A spread in [−0.5, 0.5) that is the same every time (the golden-ratio sequence). */
const jitter = (i) => ((i * 0.6180339887) % 1) - 0.5;

function box(spec, width) {
  const rows = boxRows(spec);
  const xkey = spec.x.key;
  const points = spec.points && typeof spec.points === "object" ? spec.points : {};
  const valuesOf = (r) => (Array.isArray(r.values) ? r.values : points[String(r[xkey])] || []).map(num).filter((x) => x !== null);
  const cap = Math.max(1e-9, ...rows.map((r) => num(r.hi) ?? num(r.q3) ?? 0));
  const tops = rows.map((r) => Math.max(num(r.hi) ?? 0, num(r.max) ?? 0, ...valuesOf(r)));
  const clip = Math.max(0, ...tops) > cap * 2.5;
  const y = spec.y || {};
  const lo = num(y.min) ?? Math.min(0, ...rows.map((r) => num(r.lo) ?? 0));
  const hi = niceMax(clip ? cap * 2.5 : Math.max(1e-9, ...tops) * 1.04);
  const g = el("g");
  // values past the axis are counted over their box (▲n) in a row of their own, under the axis title and the key to ▲
  const over = clip && rows.some((r) => valuesOf(r).some((val) => val > hi));
  const left = leftFor(ticks(lo, hi).map((t) => fmt(t)), y.label), right = width - 16, top = over ? 40 : 20;
  const bottom = top + Math.min(270, Math.max(170, width * (J ? 0.5 : 0.4)));
  const scale = yAxis(g, left, right, top, bottom, lo, hi, false, y.label, false, over ? top - 12 : 8);
  const band = (right - left) / Math.max(rows.length, 1);
  const xs = rows.map((_, i) => left + band * (i + 0.5));
  const bw = Math.max(8, Math.min(28, band * 0.42));
  const targets = [];
  rows.forEach((r, i) => {
    const x = xs[i];
    const [q1, med, q3, wlo, whi, mean] = ["q1", "median", "q3", "lo", "hi", "mean"].map((k) => num(r[k]));
    const vals = valuesOf(r);
    if (vals.length <= 300 && wlo !== null && whi !== null) vals.filter((val) => val >= wlo && val <= whi).forEach((val, k) =>
      g.append(el("circle", { cx: (x + jitter(k) * bw * 1.2).toFixed(1), cy: scale(Math.min(val, hi)).toFixed(1), r: 1.8, fill: v("viz-1"), "fill-opacity": 0.35 })));
    if (wlo !== null && whi !== null && q1 !== null && q3 !== null) {
      const yh = scale(Math.min(whi, hi)), yl = scale(wlo);
      g.append(line(x, yh, x, scale(q3), "viz-ink-2"), line(x, scale(q1), x, yl, "viz-ink-2"), line(x - bw / 4, yh, x + bw / 4, yh, "viz-ink-2"), line(x - bw / 4, yl, x + bw / 4, yl, "viz-ink-2"));
    }
    if (q1 !== null && q3 !== null) {
      const y1 = scale(Math.min(q3, hi)), y3 = scale(Math.min(q1, hi));
      g.append(el("rect", { x: (x - bw / 2).toFixed(1), y: y1.toFixed(1), width: bw.toFixed(1), height: Math.max(y3 - y1, 1).toFixed(1), fill: v("viz-1"), "fill-opacity": 0.22, stroke: v("viz-1"), "stroke-width": 1.2 }));
    }
    if (med !== null) g.append(line(x - bw / 2, scale(Math.min(med, hi)), x + bw / 2, scale(Math.min(med, hi)), "viz-ink", 2));
    if (mean !== null && mean <= hi) {
      const ym = scale(mean);
      g.append(el("path", { d: `M${x - 3.5},${ym}L${x},${ym - 3.5}L${x + 3.5},${ym}L${x},${ym + 3.5}Z`, fill: v("viz-surface"), stroke: v("viz-ink"), "stroke-width": 1 }));
    }
    let above = 0;
    for (const val of vals) {
      if ((whi !== null && val > whi) || (wlo !== null && val < wlo)) {
        if (val > hi) { above++; continue; }
        g.append(el("circle", { cx: x, cy: scale(val).toFixed(1), r: 2.8, fill: v("viz-surface"), stroke: v("viz-1"), "stroke-width": 1.2 }));
      }
    }
    if (above) g.append(text(x, top - 8, `▲${above}`, { size: 9.5, fill: "viz-muted", anchor: "middle" }));
    targets.push({ x, y: scale(Math.min(med ?? 0, hi)), col: band / 2, title: String(r[xkey] ?? ""),
      lines: [[fmt(r.n), "n"], [fmt(med), T("中位数")], [`${fmt(q1)}–${fmt(q3)}`, T("四分位距")], [`${fmt(wlo)}–${fmt(whi)}`, T("须线")], ...(mean !== null ? [[fmt(mean), T("均数")]] : [])] });
  });
  let end = xLabels(g, rows.map((r) => String(r[xkey] ?? "")), xs, bottom, band, null);
  rows.forEach((r, i) => { if (num(r.n) !== null) g.append(text(xs[i], end + 8, `n = ${num(r.n)}`, { size: 9.5, fill: "viz-muted", anchor: "middle" })); });
  end += 12;
  if (J && spec.x.label) { g.append(text((left + right) / 2, end + 12, spec.x.label, { size: 11, fill: "viz-ink", anchor: "middle" })); end += 16; }
  if (over) g.append(text(right, 12, T("▲：超出纵轴的值的个数"), { size: 9.5, fill: "viz-muted", anchor: "end" }));
  return { svg: g, height: end + 4, targets };
}

/** The domain of a forest plot's axis: every interval and the reference line, with a margin; log when asked and possible. */
export function forestDomain(rows, est, x = {}) {
  const vals = rows.flatMap((r) => [est.key, est.lo, est.hi].filter(Boolean).map((k) => num(r[k]))).filter((n) => n !== null);
  const ref = num(x.ref);
  if (ref !== null) vals.push(ref);
  if (!vals.length) return { lo: 0, hi: 1, log: false };
  const lo = Math.min(...vals), hi = Math.max(...vals);
  if (x.log && vals.every((n) => n > 0)) return { lo: lo / 1.3, hi: hi * 1.3, log: true };
  const pad = (hi - lo) * 0.06 || 1;
  return { lo: lo - pad, hi: hi + pad, log: false };
}

function forest(spec, width) {
  const rows = spec.rows;
  const est = spec.estimate || {};
  const ax = spec.x || {};
  const ykey = spec.y.key;
  const { lo, hi, log } = forestDomain(rows, est, ax);
  const textOf = (r) => (num(r[est.lo]) !== null && num(r[est.hi]) !== null ? `${fmtEst(r[est.key])} (${fmtEst(r[est.lo])}–${fmtEst(r[est.hi])})` : fmtEst(r[est.key]));
  const labelW = Math.min(width * 0.3, Math.max(30, ...rows.map((r) => textWidth(r[ykey] ?? "", 11))) + 12);
  const textW = Math.min(width * 0.4, Math.max(40, textWidth(`${est.label || ""} (95% CI)`, 10.5), ...rows.map((r) => textWidth(textOf(r), 10.5))) + 14);
  const left = labelW, right = width - textW;
  const g = el("g");
  const grey = rows.some((r) => r.sig === false) && rows.some((r) => r.sig !== false);
  const lg = grey ? legend([[T("显著"), v("viz-1")], [T("未达显著"), v("viz-other")]], width) : { nodes: [], height: 0 };
  g.append(...lg.nodes);
  const top = lg.height + 22, step = 20;
  g.append(text(left - 8, top - 8, clipText(spec.y.label || "", 10.5, left - 10), { size: 10.5, fill: J ? "viz-ink" : "viz-muted", anchor: "end", weight: J ? 600 : null }),
    text(right + 10, top - 8, `${est.label || ""} (95% CI)`, { size: 10.5, fill: J ? "viz-ink" : "viz-muted", weight: J ? 600 : null }));
  const bottom = top + step * rows.length;
  const { scale, end } = xAxisNumeric(g, left, right, bottom + 4, lo, hi, { label: ax.label || "", log, gridTop: top });
  const ref = num(ax.ref);
  if (ref !== null && ref >= lo && ref <= hi) g.append(line(scale(ref), top - 4, scale(ref), bottom + 4, J ? "viz-ink-2" : "viz-axis"));
  const targets = [];
  rows.forEach((r, i) => {
    const y = top + step * i + step / 2;
    const c = r.sig === false ? v("viz-other") : v("viz-1");
    g.append(text(left - 8, y + 4, clipText(r[ykey] ?? "", 11, left - 10), { size: 11, anchor: "end" }));
    const e = num(r[est.key]), a = num(r[est.lo]), b = num(r[est.hi]);
    if (a !== null && b !== null) {
      const xa = scale(Math.max(a, lo)), xb = scale(Math.min(b, hi));
      g.append(line(xa, y, xb, y, J ? "viz-ink-2" : c, 1.2));
      for (const [xx, cut, d] of [[xa, a < lo, -1], [xb, b > hi, 1]]) {
        if (cut) g.append(el("path", { d: `M${xx - 5 * d},${y - 3.5}L${xx},${y}L${xx - 5 * d},${y + 3.5}`, fill: "none", stroke: v("viz-ink-2"), "stroke-width": 1.2 }));
        else if (J) g.append(line(xx, y - 3.5, xx, y + 3.5, "viz-ink-2", 1.2));
      }
    }
    if (e !== null && e >= lo && e <= hi) g.append(el("rect", { x: (scale(e) - 4).toFixed(1), y: (y - 4).toFixed(1), width: 8, height: 8, fill: c, stroke: v("viz-surface"), "stroke-width": 1 }));
    g.append(text(right + 10, y + 4, textOf(r), { size: 10.5, fill: "viz-ink" }));
    const extra = (spec.columns || []).filter((col) => ![ykey, est.key, est.lo, est.hi].includes(col.key)).map((col) => [fmt(r[col.key]), col.label]).filter(([t]) => t);
    targets.push({ x: e !== null ? scale(Math.min(Math.max(e, lo), hi)) : left, y, row: step / 2, title: String(r[ykey] ?? ""), lines: [[textOf(r), `${est.label || ""} (95% CI)`], ...extra] });
  });
  return { svg: g, height: end + 4, targets };
}

function scatter(spec, width) {
  const ax = spec.x || {}, ay = spec.y || {};
  const pts = spec.rows.map((r) => [r, num(r[ax.key]), num(r[ay.key])]).filter(([, a, b]) => a !== null && b !== null);
  const sk = spec.size?.key;
  const gk = spec.group?.key;
  const groups = gk ? [...new Set(pts.map(([r]) => String(r[gk] ?? "")))] : [];
  const gc = new Map(groups.map((gname, i) => [gname, i < 3 ? seriesColors(groups.slice(0, 3))[i] : v("viz-other")])); // three groups at most
  const g = el("g");
  const lg = groups.length >= 2 ? legend(groups.map((gname) => [gname, gc.get(gname)]), width) : { nodes: [], height: 0 };
  g.append(...lg.nodes);
  const fit = (spec.fit?.points || []).map(([a, b]) => [num(a), num(b)]).filter(([a, b]) => a !== null && b !== null);
  const xv = pts.map(([, a]) => a), yv = pts.map(([, , b]) => b);
  let xlo = num(ax.min) ?? Math.min(...xv), xhi = Math.max(...xv);
  if (!(xhi > xlo)) { xlo -= 1; xhi += 1; }
  const pad = (xhi - xlo) * 0.04;
  if (num(ax.min) === null) xlo -= pad;
  xhi += pad;
  const ylo = num(ay.min) ?? Math.min(0, ...yv);
  const topY = Math.max(...yv, ...fit.map(([, b]) => b));
  const yhi = num(ay.max) ?? (ay.percent && topY <= 1 ? 1 : niceMax(topY));
  const left = leftFor(ticks(ylo, yhi).map((t) => fmt(t, ay.percent)), ay.label), right = width - 16;
  const head = sk ? 18 : 8; // the axis title and the key to the bubbles clear of a bubble at the top (radius 10 at most)
  const top = lg.height + 14 + head, bottom = top + Math.min(280, Math.max(180, width * (J ? 0.55 : 0.45)));
  const yscale = yAxis(g, left, right, top, bottom, ylo, yhi, Boolean(ay.percent), ay.label, false, head);
  let { scale: xscale, end } = xAxisNumeric(g, left, right, bottom, xlo, xhi, { label: J ? ax.label || "" : "", percent: Boolean(ax.percent), year: Boolean(ax.year), gridTop: top });
  if (!J && ax.label) { g.append(text(right, end + 10, ax.label, { size: 10.5, fill: "viz-muted", anchor: "end" })); end += 14; }
  const smax = sk ? Math.max(1e-9, ...pts.map(([r]) => num(r[sk]) || 0)) : 1;
  const rad = (r) => (sk ? 3 + 7 * Math.sqrt(Math.max(num(r[sk]) || 0, 0) / smax) : 3);
  const dense = pts.length > 200;
  const targets = [];
  for (const [r, a, b] of pts) {
    const c = gk ? gc.get(String(r[gk] ?? "")) : v("viz-1");
    const cx = xscale(a), cy = yscale(Math.min(b, yhi));
    g.append(el("circle", { cx: cx.toFixed(1), cy: cy.toFixed(1), r: rad(r).toFixed(1), fill: c, "fill-opacity": dense ? 0.35 : 0.6, ...(dense ? {} : { stroke: v("viz-surface"), "stroke-width": 1 }) }));
    const extra = (spec.columns || []).filter((col) => ![ax.key, ay.key, spec.label].includes(col.key)).map((col) => [fmt(r[col.key]), col.label]).filter(([t]) => t);
    targets.push({ x: cx, y: cy, title: spec.label ? String(r[spec.label] ?? "") : T`${fmt(a, ax.percent)}，${fmt(b, ay.percent)}`,
      lines: [[ax.year ? yearText(a) : fmt(a, ax.percent), ax.label || ax.key], [fmt(b, ay.percent), ay.label || ay.key], ...extra] });
  }
  if (fit.length >= 2) g.append(el("polyline", { points: fit.map(([a, b]) => `${xscale(a).toFixed(1)},${yscale(Math.min(Math.max(b, ylo), yhi)).toFixed(1)}`).join(" "), fill: "none", stroke: v("viz-ink"), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  if (sk && pts.length) g.append(text(right, top - head, T`点的大小：${spec.size.label || sk}（最大 ${fmt(smax)}）`, { size: 10, fill: "viz-muted", anchor: "end" }));
  return { svg: g, height: end + 4, targets };
}

function dendrogram(spec, width) {
  const labels = spec.labels.map(String);
  const n = labels.length;
  const merges = spec.merges;
  const order = Array.isArray(spec.order) && spec.order.length === n ? spec.order.map(Number) : [...labels.keys()];
  const member = Array.isArray(spec.member) && spec.member.length === n ? spec.member : labels.map(() => 0);
  const names = (spec.groups || []).map(String);
  const nameOf = (c) => names[c] ?? String(c);
  const colors = groupColors(spec, [...new Set(order.map((i) => nameOf(member[i])))]);
  const colorOf = (c) => colors.get(nameOf(c)) || v("viz-ink-2");
  const g = el("g");
  const lg = legend([...colors], width);
  g.append(...lg.nodes);
  const top = lg.height + 14, step = J ? 15 : 18;
  const left = Math.min(width * 0.3, Math.max(24, ...labels.map((l) => textWidth(l, 11))) + 22), right = width - 20;
  const hmax = Math.max(1e-9, ...merges.map((m) => num(m[2])));
  const xscale = (hh) => left + (hh / (hmax * 1.04)) * (right - left);
  const ypos = new Map(order.map((item, k) => [item, top + step * k + step / 2]));
  const clus = new Map(labels.map((_, i) => [i, member[i]]));
  const hgt = new Map(labels.map((_, i) => [i, 0]));
  const cut = num(spec.cut);
  merges.forEach(([a, b, hh], i) => {
    const node = n + i, ya = ypos.get(a), yb = ypos.get(b), hn = num(hh);
    ypos.set(node, (ya + yb) / 2);
    hgt.set(node, hn);
    const same = clus.get(a) !== null && clus.get(a) !== undefined && clus.get(a) === clus.get(b) && (cut === null || hn <= cut) ? clus.get(a) : null;
    clus.set(node, same);
    const x = xscale(hn);
    g.append(el("path", { d: `M${xscale(hgt.get(a)).toFixed(1)},${ya.toFixed(1)}L${x.toFixed(1)},${ya.toFixed(1)}L${x.toFixed(1)},${yb.toFixed(1)}L${xscale(hgt.get(b)).toFixed(1)},${yb.toFixed(1)}`,
      fill: "none", stroke: same !== null ? colorOf(same) : v("viz-ink-2"), "stroke-width": same !== null ? 1.6 : 1.2 }));
  });
  const targets = [];
  const freq = new Map((spec.rows || []).map((r) => [String(r.drug ?? r.label ?? ""), r]));
  for (const item of order) {
    const y = ypos.get(item);
    g.append(el("rect", { x: left - 13, y: y - 4, width: 8, height: 8, fill: colorOf(member[item]) }), text(left - 18, y + 4, clipText(labels[item], 11, left - 20), { size: 11, anchor: "end" }));
    const r = freq.get(labels[item]) || {};
    targets.push({ x: left, y, row: step / 2, title: labels[item], lines: [[nameOf(member[item]), T("类别")], ...(spec.columns || []).filter((c) => !["drug", "label", "cluster"].includes(c.key)).map((c) => [fmt(r[c.key]), c.label]).filter(([t]) => t)] });
  }
  const bottom = top + step * n + 4;
  if (cut !== null) g.append(line(xscale(cut), top, xscale(cut), bottom, "viz-muted"));
  const { end } = xAxisNumeric(g, left, right, bottom, 0, hmax * 1.04, { label: spec.x?.label || "" });
  return { svg: g, height: end + 4, targets };
}

/** The lane (0 at the top) of each label of a timeline, and whether it is turned to the left of its dot (at the right edge,
 * where it would leave the figure).  ``xs`` the dots in order of time, ``widths`` the room each label takes.
 *
 * A label takes the lane, among those where it overlaps no other label, where the fewest stems cross labels — its own
 * stem, from its dot down to the axis, through the labels below it, and the stems from above through its text — the
 * highest of them when several tie; lanes past the compact layout's (each label in the first lane it fits) and two more
 * are taken only when nothing else is free, so that a crowded timeline does not grow into a tall one (the stems that
 * still cross a label are broken around it, stemGaps).  Labels pointing right are placed in order of time, then the
 * turned ones from the right edge inwards, so that each meets the stems it could cross already placed. */
export function timelineLanes(xs, widths, width) {
  const n = xs.length;
  const flip = xs.map((x, i) => x + widths[i] > width - 6);
  const room = xs.map((x, i) => (flip[i] ? [x - widths[i], x + 6] : [x - 6, x + widths[i]]));
  const span = xs.map((x, i) => (flip[i] ? [x - widths[i] + 7, x - 7] : [x + 7, x + widths[i] - 7]));
  const order = [...xs.keys()].filter((i) => !flip[i]).concat([...xs.keys()].filter((i) => flip[i]).reverse());
  const free = (i, k, lane, done) => !done.some((j) => lane[j] === k && room[j][0] < room[i][1] + 2 && room[i][0] < room[j][1] + 2);
  let lane = new Array(n).fill(0), done = [];
  for (const i of order) { // the compact layout: how many lanes the labels need at least
    let k = 0;
    while (!free(i, k, lane, done)) k++;
    lane[i] = k;
    done.push(i);
  }
  const budget = Math.max(0, ...lane) + 1 + 2;
  lane = new Array(n).fill(0);
  done = [];
  for (const i of order) {
    let best = null;
    const last = Math.max(-1, ...done.map((j) => lane[j])) + 1;
    for (let k = 0; k <= last; k++) {
      if (!free(i, k, lane, done)) continue;
      if (k >= budget && best !== null) break;
      let cost = 0;
      for (const j of done) {
        if (lane[j] > k && xs[i] >= span[j][0] - 2 && xs[i] <= span[j][1] + 2) cost++; // its stem through a label below
        if (lane[j] < k && xs[j] >= span[i][0] - 2 && xs[j] <= span[i][1] + 2) cost++; // a stem from above through its text
      }
      if (best === null || cost < best[0]) { best = [cost, k]; if (!cost) break; }
    }
    lane[i] = best ? best[1] : 0;
    done.push(i);
  }
  return { lane, flip };
}

/** A stem from ``top`` down to ``bottom`` at ``x`` as the pieces that clear the labels' ``boxes`` ([x0, y0, x1, y1]) it
 * would cross, 2 px around each. */
export function stemGaps(x, top, bottom, boxes) {
  const cuts = boxes.filter(([x0, y0, x1, y1]) => x >= x0 - 2 && x <= x1 + 2 && y1 > top && y0 < bottom).map(([, y0, , y1]) => [y0 - 2, y1 + 2]).sort((a, b) => a[0] - b[0]);
  const out = [];
  let y = top;
  for (const [a, b] of cuts) { if (a > y) out.push([y, a]); y = Math.max(y, b); }
  if (y < bottom) out.push([y, bottom]);
  return out;
}

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
  const labels = rows.map((r) => clipText(r.label ?? "", 10.5, width * 0.6));
  const xs = rows.map((r) => scale(num(r.start)));
  const { lane, flip } = timelineLanes(xs, labels.map((t) => textWidth(t, 10.5) + 14), width);
  const top = lg.height + 18;
  const axis = top + 22 * (Math.max(0, ...lane) + 1) + 10;
  for (const t of ticks(lo, hi, 6)) { // ticks under the axis (no grid: the stems are the guides, and a line through a label is not)
    const x = scale(t);
    g.append(line(x, axis, x, axis + 4), text(x, axis + 16, yearText(t), { size: 10.5, fill: J ? "viz-ink-2" : "viz-muted", anchor: "middle", cls: "tick" }));
  }
  g.append(line(left, axis, right, axis));
  const ys = lane.map((k) => top + 22 * k + 8);
  const cs = rows.map((r) => colors.get(String(r.group ?? "")));
  const boxes = rows.map((r, i) => boxOf(flip[i] ? xs[i] - 7 : xs[i] + 7, ys[i] + 4, textWidth(labels[i], 10.5), 10.5, flip[i] ? "end" : "start"));
  rows.forEach((r, i) => { // the stems first, broken where they would cross a label
    for (const [a, b] of stemGaps(xs[i], ys[i], axis, boxes.filter((_, j) => j !== i)))
      g.append(el("line", { x1: xs[i], y1: a.toFixed(1), x2: xs[i], y2: b.toFixed(1), stroke: cs[i], "stroke-width": 1, "stroke-opacity": 0.35 }));
  });
  rows.forEach((r, i) => g.append(el("circle", { cx: xs[i], cy: ys[i], r: 4, fill: cs[i], stroke: v("viz-surface"), "stroke-width": 2 })));
  const targets = [];
  rows.forEach((r, i) => {
    g.append(text(flip[i] ? xs[i] - 7 : xs[i] + 7, ys[i] + 4, labels[i], { size: 10.5, fill: "viz-ink", anchor: flip[i] ? "end" : "start" }));
    targets.push({ x: xs[i], y: ys[i], title: String(r.label ?? ""), lines: (spec.columns || []).filter((col) => col.key !== "label").map((col) => [fmt(r[col.key]), col.label]).filter(([s]) => s) });
  });
  let end = axis + 24;
  if (J) { g.append(text((left + right) / 2, end + 6, spec.x?.label || T("年代"), { size: 11, fill: "viz-ink", anchor: "middle" })); end += 16; }
  return { svg: g, height: end, targets };
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
  const link = J ? "viz-link" : "viz-axis";
  const targets = [];
  const hub = hubOf(nodes, edges);
  const top = lg.height + 16;
  if (hub !== null) { // a hub and its spokes: the hub on the left, the others in a column
    const centre = nodes.find((n) => n.id === hub);
    const others = nodes.filter((n) => n.id !== hub);
    const byTarget = new Map(edges.map((e) => [e.source === hub ? e.target : e.source, e]));
    const step = 22, height = step * Math.max(others.length, 1);
    const hubLabel = clipText(centre.label ?? centre.id, 13, width * 0.3);
    const hx = Math.max(Math.min(140, width * 0.22), rad(centre) + 2 + 8 + textWidth(hubLabel, 13) + 4); // its name to its left, inside
    const hy = top + height / 2, col = Math.max(Math.min(360, width * 0.48), hx + 60);
    others.forEach((n, i) => {
      const y = top + step * i + step / 2;
      const e = byTarget.get(n.id) || {};
      const name = clipText(n.label ?? n.id, 11, width - col - 16);
      g.append(el("path", { d: `M${hx},${hy}C${(hx + col) / 2},${hy} ${(hx + col) / 2},${y} ${col},${y}`, fill: "none", stroke: v(link), "stroke-width": 1 }),
        el("circle", { cx: col, cy: y, r: rad(n), fill: colors.get(String(n.group ?? "")), stroke: v("viz-surface"), "stroke-width": 2 }),
        text(col + 14, y + 4, name, { size: 11, fill: "viz-ink" }));
      if (e.label && col + 24 + textWidth(name, 11) + textWidth(e.label, 10) < width) g.append(text(col + 24 + textWidth(name, 11), y + 4, e.label, { size: 10, fill: "viz-muted" }));
      targets.push({ x: col, y, title: String(n.label ?? n.id), lines: [[String(n.group ?? ""), T("关系")], [fmt(n.size), T("权重")], ...(e.label ? [[e.label, T("说明")]] : [])] });
    });
    g.append(el("circle", { cx: hx, cy: hy, r: rad(centre) + 2, fill: colors.get(String(centre.group ?? "")), stroke: v("viz-surface"), "stroke-width": 2 }),
      text(hx - rad(centre) - 8, hy + 5, hubLabel, { size: 13, fill: "viz-ink", anchor: "end", weight: 600 }));
    return { svg: g, height: top + height + 8, targets };
  }
  // a ring: each name along its radius, outwards (turned to read left to right on the left half), so that neighbours
  // never sit on one another however many there are
  const names = new Map(nodes.map((n) => [n.id, clipText(n.label ?? n.id, 10.5, 90)]));
  const reach = Math.max(0, ...[...names.values()].map((t) => textWidth(t, 10.5))) + 4 + 12; // a name and the largest dot
  const cx = width / 2, R = Math.max(40, Math.min(170, width / 2 - reach - 6)), cy = top + reach + R + 6;
  const pos = new Map(nodes.map((n, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / nodes.length;
    return [n.id, [cx + R * Math.cos(a), cy + R * Math.sin(a), a]];
  }));
  const wmax = Math.max(1, ...edges.map((e) => num(e.weight) || 1));
  for (const e of edges) {
    const a = pos.get(e.source), b = pos.get(e.target);
    if (a && b) g.append(line(a[0], a[1], b[0], b[1], link, (1 + (2 * (num(e.weight) || 1)) / wmax).toFixed(1)));
  }
  for (const n of nodes) {
    const [x, y, a] = pos.get(n.id);
    const rightHalf = Math.cos(a) >= -1e-9, d = R + rad(n) + 4;
    // the baseline a third of an em off the radius, so that the glyphs sit on it
    const [ox, oy] = rightHalf ? [-Math.sin(a), Math.cos(a)] : [Math.sin(a), -Math.cos(a)];
    const turn = Math.round(((a * 180) / Math.PI + (rightHalf ? 0 : 180)) * 100) / 100;
    g.append(el("circle", { cx: x, cy: y, r: rad(n), fill: colors.get(String(n.group ?? "")), stroke: v("viz-surface"), "stroke-width": 2 }),
      text(cx + d * Math.cos(a) + 3.6 * ox, cy + d * Math.sin(a) + 3.6 * oy, names.get(n.id), { size: 10.5, fill: "viz-ink", anchor: rightHalf ? "start" : "end", rotate: turn }));
    targets.push({ x, y, title: String(n.label ?? n.id), lines: [[String(n.group ?? ""), T("类")], [fmt(n.size), T("权重")]] });
  }
  return { svg: g, height: cy + R + reach + 8, targets };
}

// ------------------------------------------------------------------ figures: for the page's downloads and for a journal
const CLOSING = new Set("）」』】〕》〉，。、；：！？’”)].,;:!?");

function wrap(s, width, size) {
  const out = [];
  let cur = "";
  for (const ch of String(s)) {
    if (textWidth(cur + ch, size) > width && cur && !CLOSING.has(ch)) { out.push(cur); cur = ch; } else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}

/** A figure's caption after its number: the title and what the subtitle says, as a sentence. */
export function captionText(spec) {
  const title = String(spec.title || "").replace(" · ", T("："));
  const sub = String(spec.subtitle || "").replace(/。$/, "");
  return title + (sub ? T`。${sub}。` : "");
}

/** The caption under a journal figure: 图 n (bold) and its text, then the notes; {nodes, height}. */
function captionNodes(width, number, body, notes) {
  const head = number !== undefined && number !== null && number !== "" ? T`图${number}　` : "";
  const nodes = [];
  let y = 0;
  wrap(head + body, width - 12, 11).forEach((ln, i) => {
    y += 15;
    if (i === 0 && head && ln.startsWith(head)) nodes.push(text(0, y, head.trim(), { size: 11, fill: "viz-ink", weight: 700 }), text(textWidth(head, 11), y, ln.slice(head.length), { size: 11, fill: "viz-ink" }));
    else nodes.push(text(0, y, ln, { size: 11, fill: "viz-ink" }));
  });
  for (const note of notes) for (const ln of wrap(note, width - 11, 10)) { y += 13.5; nodes.push(text(0, y, ln, { size: 10, fill: "viz-muted" })); }
  return { nodes, height: y };
}

/** (mm, design units) of a journal figure: single, onehalf or double column, or millimetres. */
export function journalWidth(width = "onehalf") {
  const mm = typeof width === "number" ? width : WIDTHS[width] || WIDTHS.onehalf;
  return [mm, Math.round(mm * PX_PER_MM)];
}

function svgRoot(width, height, title, mm, ...children) {
  const size = mm ? { width: `${mm}mm`, height: `${((height * mm) / width).toFixed(1)}mm` } : { width, height };
  return el("svg", { xmlns: SVG, viewBox: `0 0 ${Math.round(width)} ${Math.round(height)}`, ...size, "font-family": mm ? FONT_JOURNAL : FONT, role: "img", "aria-label": title || "chart" },
    el("title", {}, title || "chart"), el("rect", { width: "100%", height: "100%", fill: v("viz-surface") }), ...children);
}

/** The figure of a specification as an SVG element (colours as tokens): in the journal style its plot and, with
 * ``caption``, its number and caption under it at a journal's width; in the screen style its title above and its note
 * and source below. */
export function figureNode(spec, { style = "screen", number = null, caption = true, width = "onehalf" } = {}) {
  if (style !== "journal") {
    const w = FIGURE_WIDTH;
    const head = [];
    let y = 24;
    head.push(text(20, y, spec.title || "", { size: 15, fill: "viz-ink", weight: 600 }));
    y += 8;
    for (const ln of wrap(spec.subtitle || "", w - 40, 11.5)) { y += 16; head.push(text(20, y, ln, { size: 11.5 })); }
    y += 12;
    const p = plot(spec, w - 40);
    let bottom = y + p.height + 6;
    const foot = [];
    for (const ln of [spec.note, spec.source].filter(Boolean).flatMap((s) => wrap(s, w - 40, 10))) { bottom += 14; foot.push(text(20, bottom, ln, { size: 10, fill: "viz-muted" })); }
    return svgRoot(w, Math.ceil(bottom + 16), spec.title, null, ...head, el("g", { transform: `translate(20 ${y})` }, p.svg), ...foot);
  }
  const [mm, w] = journalWidth(width);
  const old = J;
  J = true;
  try {
    const pad = 6;
    const p = plot(spec, w - 2 * pad);
    const parts = [el("g", { transform: `translate(${pad} ${pad + 4})` }, p.svg)];
    let y = pad + 4 + p.height;
    if (caption) {
      const cap = captionNodes(w - 2 * pad, number, captionText(spec), [spec.note, spec.source].filter(Boolean));
      parts.push(el("g", { transform: `translate(${pad} ${Math.round(y + 4)})` }, ...cap.nodes));
      y += cap.height + 4;
    }
    return svgRoot(w, Math.ceil(y + pad + 4), spec.title, mm, ...parts);
  } finally {
    J = old;
  }
}

/** What the charts of a result are of: the part of their titles before " · " when they all share it. */
export function commonTitle(specs) {
  const heads = new Set(specs.map((s) => String(s.title || "")).filter((t) => t.includes(" · ")).map((t) => t.split(" · ")[0]));
  return heads.size === 1 && specs.every((s) => String(s.title || "").includes(" · ")) ? [...heads][0] : "";
}

/** Several charts as one journal figure: panels A, B … in two columns, each with its letter and short title, and one
 * caption under them (the figure's title, then (A) …; (B) …, the notes once, the source once). */
export function panelsNode(specs, { number = null, caption = true, width = "double", columns = 2 } = {}) {
  const [mm, w] = journalWidth(width);
  const old = J;
  J = true;
  try {
    const pad = 6, gap = 18;
    const cols = Math.max(1, Math.min(columns, specs.length));
    const pw = (w - 2 * pad - gap * (cols - 1)) / cols;
    const head = commonTitle(specs);
    const short = (s) => { const t = String(s.title || ""); return head && t.startsWith(`${head} · `) ? t.slice(head.length + 3) : t; };
    const letter = (i) => String.fromCharCode(65 + (i % 26));
    const parts = [];
    let y = pad;
    for (let row = 0; row < specs.length; row += cols) {
      const cells = specs.slice(row, row + cols).map((s, k) => {
        const lines = wrap(short(s), pw - 18, 10.5).slice(0, 2);
        const p = plot(s, pw);
        return { lines, p, height: 13 + 13 * lines.length + 6 + p.height, i: row + k };
      });
      const rh = Math.max(...cells.map((c) => c.height));
      cells.forEach((c, k) => {
        const x = pad + k * (pw + gap);
        parts.push(el("g", { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})` }, text(0, 13, letter(c.i), { size: 14, fill: "viz-ink", weight: 700 }),
          ...c.lines.map((ln, j) => text(18, 13 + 13 * j, ln, { size: 10.5 })), el("g", { transform: `translate(0 ${13 * c.lines.length + 6})` }, c.p.svg)));
      });
      y += rh + 14;
    }
    if (caption) {
      const pieces = specs.map((s, i) => T`（${letter(i)}）${short(s)}`).join(T("；"));
      let notes = [...new Set(specs.map((s) => s.note).filter(Boolean))];
      notes = notes.filter((x) => !notes.some((o) => o !== x && o.includes(x)));
      const sources = [...new Set(specs.map((s) => s.source).filter(Boolean))];
      const cap = captionNodes(w - 2 * pad, number, T`${head ? T`${head}。` : ""}${pieces}。`, [...notes, ...(sources.length ? [sources.join(T("；"))] : [])]);
      parts.push(el("g", { transform: `translate(${pad} ${Math.round(y - 6)})` }, ...cap.nodes));
      y += cap.height;
    }
    return svgRoot(w, Math.ceil(y + pad), head || "figure", mm, ...parts);
  } finally {
    J = old;
  }
}

const serialize = (node, colors) => new XMLSerializer().serializeToString(node).replace(/var\(--([\w-]+)\)/g, (_, name) => colors[name] || "#888888");

/** A standalone SVG document of the specification, colours inline (see figureNode). */
export function figureSVG(spec, opts = {}) {
  return serialize(figureNode(spec, opts), opts.style === "journal" ? JOURNAL : LIGHT);
}

export function panelsSVG(specs, opts = {}) {
  return serialize(panelsNode(specs, opts), JOURNAL);
}

const csvCell = (x) => {
  const s = defuse(x === null || x === undefined ? "" : String(x));
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** The table behind the chart as CSV (a network: its edges), with a byte-order mark for spreadsheet programs. */
export function toCSV(spec, bom = true) {
  let lines;
  if (spec.type === "network" && spec.edges?.length) {
    const label = new Map((spec.nodes || []).map((n) => [n.id, n.label ?? n.id]));
    lines = [[T("来源"), T("目标"), T("权重"), T("说明")], ...spec.edges.map((e) => [label.get(e.source) ?? e.source, label.get(e.target) ?? e.target, e.weight ?? "", e.label ?? ""])];
  } else {
    const cols = spec.columns?.length ? spec.columns : Object.keys(spec.rows?.[0] || {}).map((k) => ({ key: k, label: k }));
    lines = [cols.map((c) => c.label), ...(spec.rows || []).map((r) => cols.map((c) => r[c.key]))];
  }
  return (bom ? "﻿" : "") + lines.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function tableView(spec) {
  const net = spec.type === "network" && spec.edges?.length;
  const cols = net ? [{ key: "source", label: T("来源") }, { key: "target", label: T("目标") }, { key: "weight", label: T("权重") }, { key: "label", label: T("说明") }]
    : (spec.columns?.length ? spec.columns : Object.keys(spec.rows?.[0] || {}).map((k) => ({ key: k, label: k })));
  const label = new Map((spec.nodes || []).map((n) => [n.id, n.label ?? n.id]));
  const rows = net ? spec.edges.map((e) => ({ ...e, source: label.get(e.source), target: label.get(e.target) })) : spec.rows;
  const isNum = (c) => rows.every((r) => r[c.key] === null || r[c.key] === undefined || r[c.key] === "" || num(r[c.key]) !== null);
  const numeric = cols.map(isNum);
  return h("div.viz-table-wrap", h("table.viz-table",
    h("thead", h("tr", ...cols.map((c, i) => h(numeric[i] ? "th.num" : "th", c.label)))),
    h("tbody", ...rows.map((r) => h("tr", ...cols.map((c, i) => h(numeric[i] ? "td.num" : "td", numeric[i] ? fmt(r[c.key]) : String(r[c.key] ?? ""))))))));
}

// ------------------------------------------------------------------ rasters: PNG and TIFF at a resolution
const safeName = (s) => String(s || "chart").replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "chart";

async function rasterize(svgText, pixelWidth) {
  const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image();
    await new Promise((ok, fail) => { img.onload = ok; img.onerror = () => fail(new Error(T("图像生成失败"))); img.src = url; });
    const box = /viewBox="0 0 ([\d.]+) ([\d.]+)"/.exec(svgText);
    const [vw, vh] = box ? [Number(box[1]), Number(box[2])] : [img.width, img.height];
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(pixelWidth);
    canvas.height = Math.round((pixelWidth * vh) / vw);
    if (canvas.width * canvas.height > 120e6) throw new Error(T("图像过大：请选较小的宽度或分辨率"));
    const g = canvas.getContext("2d");
    g.fillStyle = "#ffffff";
    g.fillRect(0, 0, canvas.width, canvas.height);
    g.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas;
  } finally {
    URL.revokeObjectURL(url);
  }
}

const canvasBytes = (canvas) => new Promise((ok, fail) => canvas.toBlob((b) => (b ? b.arrayBuffer().then((a) => ok(new Uint8Array(a)), fail) : fail(new Error(T("图像生成失败")))), "image/png"));

/** The figure as PNG at twice its size (the page's figure). */
export async function pngBlob(svgText, scale = 2) {
  const box = /viewBox="0 0 ([\d.]+)/.exec(svgText);
  return new Blob([await canvasBytes(await rasterize(svgText, (box ? Number(box[1]) : FIGURE_WIDTH) * scale))], { type: "image/png" });
}

/** The figure as PNG at a printed width (mm) and resolution, the resolution written in the file. */
export async function pngAtDpi(svgText, mm, dpi) {
  return new Blob([pngWithDpi(await canvasBytes(await rasterize(svgText, (mm / 25.4) * dpi)), dpi)], { type: "image/png" });
}

/** The figure as TIFF (RGB, PackBits) at a printed width (mm) and resolution. */
export async function tiffAtDpi(svgText, mm, dpi) {
  const canvas = await rasterize(svgText, (mm / 25.4) * dpi);
  return new Blob([tiff(canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height), dpi)], { type: "image/tiff" });
}

// ------------------------------------------------------------------ export: the settings and the files
const DEFAULTS = { style: "journal", width: "onehalf", dpi: 300, caption: true };
export const exportSettings = () => ({ ...DEFAULTS, ...(storage.get("tc.figure-export", {}) || {}) });
const keepSettings = (s) => storage.set("tc.figure-export", s);

/** Save a chart (or several, as one figure in panels) in a format: svg, png, tiff — or its data: csv, json. */
export async function save(spec, kind, settings = exportSettings(), number = null) {
  const panels = Array.isArray(spec);
  const first = panels ? spec[0] : spec;
  const journal = panels || settings.style === "journal";
  const name = safeName(panels ? (commonTitle(spec) || T("组图")) : `${number ? T`图${number}-` : ""}${first.title}`);
  try {
    if (kind === "csv") return download(`${safeName(first.title)}.csv`, toCSV(first), "text/csv");
    if (kind === "json") return download(`${safeName(first.title)}.json`, JSON.stringify(first, null, 2), "application/json");
    const opts = { style: journal ? "journal" : "screen", number, caption: settings.caption, width: panels ? "double" : settings.width };
    const svgText = panels ? panelsSVG(spec, opts) : figureSVG(spec, opts);
    const mm = panels ? WIDTHS.double : journal ? journalWidth(settings.width)[0] : WIDTHS[settings.width] || WIDTHS.onehalf;
    if (kind === "svg") download(`${name}.svg`, svgText, "image/svg+xml");
    else if (kind === "png") downloadBlob(`${name}.png`, journal ? await pngAtDpi(svgText, mm, settings.dpi) : await pngBlob(svgText, 2));
    else if (kind === "tiff") downloadBlob(`${name}.tif`, await tiffAtDpi(svgText, mm, settings.dpi));
  } catch (err) {
    toast(T`下载失败：${err.message || err}`, "err");
  }
}

let panelSeq = 0;
/** The export panel: style, width, resolution and caption (kept for the next figure), then the formats. ``onChange``
 * hears the settings change (a card's journal preview follows them). */
function exportPanel(specOrList, { number = null, onChange = null } = {}) {
  const panels = Array.isArray(specOrList);
  const id = `xp${++panelSeq}`;
  const s = exportSettings();
  const radio = (name, value, label, checked) => h("label.opt", h("input", { type: "radio", name: `${id}-${name}`, value, checked }), label);
  const field = (label, ...opts) => h("div.field", { role: "radiogroup", "aria-label": label }, h("span.lbl", label), h("div.opts", ...opts));
  const form = h("form.viz-export-form", { on: { submit: (e) => e.preventDefault() } },
    panels ? h("p.hint", T`${specOrList.length} 幅图合为一图（A–${String.fromCharCode(64 + Math.min(specOrList.length, 26))}），双栏 175 mm，期刊样式`) : field(T("样式"), radio("style", "journal", T("期刊"), s.style === "journal"), radio("style", "screen", T("屏幕"), s.style !== "journal")),
    panels ? null : field(T("宽度"), radio("width", "single", T("单栏 85 mm"), s.width === "single"), radio("width", "onehalf", T("1.5 栏 120 mm"), s.width === "onehalf"), radio("width", "double", T("双栏 175 mm"), s.width === "double")),
    field(T("分辨率"), radio("dpi", "300", "300 dpi", Number(s.dpi) !== 600), radio("dpi", "600", "600 dpi", Number(s.dpi) === 600)),
    h("div.field", h("span.lbl"), h("div.opts", h("label.opt", h("input", { type: "checkbox", name: `${id}-caption`, checked: s.caption !== false }), T("含图号与图注")))));
  const read = () => {
    const pick = (name, fallback) => form.querySelector(`input[name="${id}-${name}"]:checked`)?.value ?? fallback;
    return { style: panels ? "journal" : pick("style", s.style), width: panels ? s.width : pick("width", s.width), dpi: Number(pick("dpi", s.dpi)), caption: form.querySelector(`input[name="${id}-caption"]`).checked };
  };
  form.addEventListener("change", () => { const now = read(); keepSettings(panels ? { ...exportSettings(), dpi: now.dpi, caption: now.caption } : now); onChange?.(now); });
  const fmtBtn = (kind, label, title) => h("button.btn.secondary", { type: "button", title, on: { click: () => save(specOrList, kind, read(), number) } }, label);
  const box = h("div.viz-export", { hidden: true, role: "dialog", "aria-label": panels ? T("导出组图") : T("导出图表") },
    form,
    h("div.viz-export-row", h("span.lbl", T("图片")), fmtBtn("svg", "SVG", T("矢量图，可无损缩放与编辑")), fmtBtn("png", "PNG", T("位图，写明分辨率")), fmtBtn("tiff", "TIFF", T("位图，期刊投稿常用"))),
    panels ? null : h("div.viz-export-row", h("span.lbl", T("数据")), fmtBtn("csv", "CSV", T("图中的数据（Excel 可直接打开）")), fmtBtn("json", "JSON", T("图表规格"))));
  const btn = h("button.btn-ghost.viz-toggle", { type: "button", "aria-haspopup": "dialog", "aria-expanded": "false", title: panels ? T("把这些图合为一幅组图导出") : T("导出图片或数据") },
    icon("download", "sm"), panels ? T("导出组图") : T("导出"));
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = box.hidden;
    closeMenus();
    box.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) box.querySelector("input, button")?.focus();
  });
  box.addEventListener("click", (e) => e.stopPropagation());
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") { box.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); } });
  if (!menusWatched) { menusWatched = true; document.addEventListener("click", (e) => { if (e.isTrusted) closeMenus(); }); } // a download's own click is not one
  return h("div.viz-dl", btn, box);
}

let menusWatched = false;
function closeMenus() {
  for (const m of document.querySelectorAll(".viz-menu:not([hidden]), .viz-export:not([hidden])")) m.hidden = true;
  for (const b of document.querySelectorAll('.viz-dl > button[aria-expanded="true"]')) b.setAttribute("aria-expanded", "false");
}

// ------------------------------------------------------------------ the card in the page
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
  return d < 24 ? d : Infinity;
}

function drawInto(host, spec) {
  const width = Math.max(280, Math.floor(host.clientWidth || 0) || 640);
  if (host.dataset.w === String(width)) return;
  host.dataset.w = String(width);
  const p = plot(spec, width);
  const svg = el("svg", { width, height: Math.ceil(p.height), viewBox: `0 0 ${width} ${Math.ceil(p.height)}`, role: "img", tabindex: 0, class: "viz-svg",
    "aria-label": T`${spec.title || T("图表")}；可切换为表格查看全部数字` }, p.svg);
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

/** The journal figure in the page: what a download in the journal style gives (white paper in either mode). */
function journalPreview(spec, number, settings) {
  const node = figureNode(spec, { style: "journal", number, caption: settings.caption !== false, width: settings.width });
  for (const [k, c] of Object.entries(JOURNAL)) node.style.setProperty(`--${k}`, c);
  node.removeAttribute("width");
  node.removeAttribute("height");
  node.setAttribute("class", "viz-paper-svg");
  return h("div.viz-paper", { style: { maxWidth: `${Math.round(journalWidth(settings.width)[1] * 1.45)}px` } }, node);
}

/** A chart card: 图 n and its title, the chart (or its table, or its journal figure), its exports; null when the
 * specification cannot be drawn. */
export function chartCard(raw, number) {
  if (invalid(raw)) return null;
  const spec = normalize(raw);
  number = number ?? raw.number ?? null;
  const host = h("div.viz-plot");
  let view = "chart"; // chart, table, paper
  const body = h("div.viz-body");
  const tableBtn = h("button.btn-ghost.viz-toggle", { type: "button", "aria-pressed": "false", title: T("以表格查看全部数字") }, T("表格"));
  const paperBtn = h("button.btn-ghost.viz-toggle", { type: "button", "aria-pressed": "false", title: T("按期刊样式显示（即导出所得）") }, T("期刊样式"));
  const watch = new ResizeObserver(() => { if (host.isConnected && view === "chart") drawInto(host, spec); });
  const render = () => {
    body.replaceChildren(view === "table" ? tableView(spec) : view === "paper" ? journalPreview(spec, number, exportSettings()) : host);
    card.classList.toggle("paper", view === "paper"); // the paper has the note and source under it already
    tableBtn.setAttribute("aria-pressed", String(view === "table"));
    paperBtn.setAttribute("aria-pressed", String(view === "paper"));
    if (view === "chart") { delete host.dataset.w; queueMicrotask(() => drawInto(host, spec)); }
  };
  tableBtn.addEventListener("click", () => { view = view === "table" ? "chart" : "table"; render(); });
  paperBtn.addEventListener("click", () => { view = view === "paper" ? "chart" : "paper"; render(); });
  watch.observe(host);
  const card = h("figure.viz-card.chart",
    h("figcaption", h("div.cap", h("span.title", number ? h("b", T`图${number}`) : null, number ? T("　") : "", spec.title || T("图表")), spec.subtitle ? h("span.sub", spec.subtitle) : null),
      h("div.tools", tableBtn, paperBtn, exportPanel(spec, { number, onChange: () => { if (view === "paper") render(); } }))),
    body,
    spec.note || spec.source ? h("div.viz-foot", [spec.note, spec.source].filter(Boolean).join(" · ")) : null);
  render();
  return card;
}

// one card per specification object and number: a turn is drawn again on every streamed update, its charts are not
const cards = new WeakMap();
export function cachedCard(spec, number) {
  if (!spec || typeof spec !== "object") return null;
  let byNumber = cards.get(spec);
  if (!byNumber) cards.set(spec, (byNumber = new Map()));
  if (!byNumber.has(number ?? null)) byNumber.set(number ?? null, chartCard(spec, number));
  return byNumber.get(number ?? null);
}

/** The document a tool result carries to download (a research protocol in Markdown): {name, format, text}, or null. */
export function documentOf(result) {
  const d = result && typeof result === "object" ? result.document : null;
  if (!d || typeof d.text !== "string" || !d.text) return null;
  const name = String(d.name || "document.md").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80);
  return { name: /\.(md|markdown|txt)$/i.test(name) ? name : `${name}.md`, format: d.format || "markdown", text: d.text };
}

/** A button that saves a result's document as a file. */
export function documentButton(doc, label = T("下载研究方案（Markdown）")) {
  if (!doc) return null;
  return h("button.btn.secondary.doc-dl", { type: "button", title: doc.name, on: { click: () => download(doc.name, doc.text, "text/markdown") } },
    icon("download", "sm"), label);
}

/** The charts a tool result carries (at most ``limit``), ready to keep with the call. */
export function chartsOf(result, limit = 8) {
  const list = result && typeof result === "object" && Array.isArray(result.charts) ? result.charts : [];
  return list.filter((c) => !invalid(c)).slice(0, limit);
}

/** The figures and tables of a result, one at a time: a row of tabs (图 1 …, 表 1 …) over the chosen one, and the
 * exports of them all (the figures as one figure in panels, the tables in one Word document); ``state.at`` keeps the
 * choice when the turn is drawn again.  One of them alone: its card. */
export function chartGallery(specs, state = { at: 0 }, tables = []) {
  const charts = (specs || []).map((s, i) => ({ s, n: i + 1, card: cachedCard(s, i + 1), kind: T("图") })).filter((x) => x.card);
  const tbls = (tables || []).map((t, i) => ({ s: t, n: i + 1, card: cachedTable(t, i + 1), kind: T("表") })).filter((x) => x.card);
  const items = [...charts, ...tbls];
  if (!items.length) return null;
  const extras = [];
  if (charts.length >= 2) extras.push(exportPanel(charts.map((x) => x.s), { number: 1 }));
  if (tbls.length >= 2) extras.push(h("button.btn-ghost.viz-toggle", { type: "button", title: T("全部表格存为一个 Word 文档"), on: { click: () => saveTables(tbls.map((x) => x.s), T`${commonTitle(charts.map((x) => x.s)) || T("研究")}-表格`) } }, icon("download", "sm"), T("全部表格（Word）")));
  if (items.length === 1) return h("div.charts", items[0].card);
  const slot = h("div.chart-slot");
  const tabs = items.map((x) => h("button", { type: "button", role: "tab", title: x.s.title || `${x.kind}${x.n}` }, `${x.kind}${x.n} ${x.s.title || (x.kind === T("图") ? T("图表") : T("表格"))}`));
  const pick = (i, focus = false) => {
    state.at = (i + items.length) % items.length;
    tabs.forEach((t, k) => { t.setAttribute("aria-selected", String(k === state.at)); t.tabIndex = k === state.at ? 0 : -1; });
    slot.replaceChildren(items[state.at].card);
    if (focus) tabs[state.at].focus();
  };
  tabs.forEach((t, i) => t.addEventListener("click", () => pick(i)));
  const label = [charts.length ? T`图 ${charts.length}` : "", tbls.length ? T`表 ${tbls.length}` : ""].filter(Boolean).join(" · ");
  const row = h("div.chart-tabs", { role: "tablist", "aria-label": T`图表（${label}）` }, h("span.count", label), ...tabs);
  row.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); pick(state.at + (e.key === "ArrowRight" ? 1 : -1), true); }
  });
  pick(Math.min(state.at || 0, items.length - 1));
  return h("div.charts", h("div.chart-head", row, extras.length ? h("div.chart-all", ...extras) : null), slot);
}

/** The table behind a chart in Markdown (for a conversation exported as Markdown): at most ``limit`` rows. */
export function toMarkdown(spec, limit = 60) {
  const lines = [`**${spec.title || T("图表")}**${spec.subtitle ? T`　${spec.subtitle}` : ""}`, ""];
  const cell = (x) => String(x ?? "").replace(/\|/g, "\\|").replace(/\n/g, " ");
  let cols, rows;
  if (spec.type === "network" && spec.edges?.length) {
    const label = new Map((spec.nodes || []).map((n) => [n.id, n.label ?? n.id]));
    cols = [T("来源"), T("目标"), T("权重"), T("说明")];
    rows = spec.edges.map((e) => [label.get(e.source) ?? e.source, label.get(e.target) ?? e.target, e.weight ?? "", e.label ?? ""]);
  } else {
    const c = spec.columns?.length ? spec.columns : Object.keys(spec.rows?.[0] || {}).map((k) => ({ key: k, label: k }));
    cols = c.map((x) => x.label);
    rows = (spec.rows || []).map((r) => c.map((x) => r[x.key]));
  }
  if (!cols.length) return "";
  lines.push(`| ${cols.map(cell).join(" | ")} |`, `| ${cols.map(() => "---").join(" | ")} |`);
  for (const r of rows.slice(0, limit)) lines.push(`| ${r.map(cell).join(" | ")} |`);
  if (rows.length > limit) lines.push("", T`（共 ${rows.length} 行，此处列出前 ${limit} 行）`);
  const foot = [spec.note, spec.source].filter(Boolean).join(" · ");
  if (foot) lines.push("", `*${foot}*`);
  return lines.join("\n");
}

export { menuButton };
