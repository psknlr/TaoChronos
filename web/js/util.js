// Small helpers shared by the client: DOM building, icons, formatting, storage-safe wrappers.

import { LANG, LOCALE, T } from "./i18n.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** h("div.cls#id", {attrs, on: {click}}, ...children) — a tiny DOM builder (never parses HTML). */
export function h(tag, attrs, ...children) {
  const m = /^([a-z0-9-]+)?((?:[.#][\w-]+)*)$/i.exec(tag) || [];
  const el = document.createElement(m[1] || "div");
  for (const part of (m[2] || "").match(/[.#][\w-]+/g) || []) {
    if (part[0] === ".") el.classList.add(part.slice(1));
    else el.id = part.slice(1);
  }
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "class") el.className = [el.className, v].filter(Boolean).join(" ");
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

/** Replace an element's children (arrays flattened, null/false skipped). */
export function replace(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** A progress bar at `pct` (0–100). */
export const progressBar = (pct) =>
  moveBar(h("span.progress", { role: "progressbar", "aria-label": T("加载进度"), "aria-valuemin": "0", "aria-valuemax": "100" }, h("i")), pct);

/** Move the progress bar in `root` (or `root` itself) to `pct` where it is, so that it slides there (its CSS transition)
 * instead of being drawn anew; null when there is none. */
export function moveBar(root, pct) {
  const bar = root.classList.contains("progress") ? root : root.querySelector(".progress");
  if (!bar) return null;
  const p = Math.min(100, Math.max(0, Math.round(pct || 0)));
  bar.setAttribute("aria-valuenow", String(p));
  bar.firstChild.style.width = `${Math.max(4, p)}%`;
  return bar;
}

const PATHS = {
  plus: "M12 5v14M5 12h14",
  send: "M5 12h14M13 6l6 6-6 6",
  up: "M12 19V5M6 11l6-6 6 6",
  down: "M12 5v14M6 13l6 6 6-6",
  stop: "M7 7h10v10H7z",
  menu: "M4 7h16M4 12h16M4 17h16",
  sidebar: "M4 5h16v14H4zM9 5v14",
  panel: "M4 5h16v14H4zM15 5v14",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-3.5-3.5",
  copy: "M9 9h10v10H9zM5 15V5h10",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  edit: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  redo: "M4 12a8 8 0 0 1 13.7-5.6L20 9M20 4v5h-5M20 12a8 8 0 0 1-13.7 5.6L4 15",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  pin: "M9 4h6l-1 6 4 3H6l4-3-1-6zM12 13v7",
  dots: "M5 12h.01M12 12h.01M19 12h.01",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  upload: "M12 20V9M7 14l5-5 5 5M5 4h14",
  image: "M4 5h16v14H4zM4 15l4-4 4 4 3-3 5 5M15.5 9.5h.01",
  file: "M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6",
  table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  shield: "M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z",
  book: "M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5zM4 20.5A2.5 2.5 0 0 0 6.5 23H20",
  flask: "M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3M7 15h10",
  tools: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.4-.4-2.4z",
  chev: "M9 6l6 6-6 6",
  chevdown: "M6 9l6 6 6-6",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  key: "M15 7a4 4 0 1 1-3.9 5H3v3h3v3h3v-3h2.1A4 4 0 0 1 15 7zM16.5 9.5h.01",
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  chip: "M7 7h10v10H7zM9.5 2v3M14.5 2v3M9.5 19v3M14.5 19v3M2 9.5h3M2 14.5h3M19 9.5h3M19 14.5h3",
  chart: "M4 20h16M7 16v-5M12 16V6M17 16v-8",
  globe: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  warn: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  scroll: "M8 21h12a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v3h4M19 17V5a2 2 0 0 0-2-2H4",
  quote: "M7 7h4v4c0 3-2 5-4 6M15 7h4v4c0 3-2 5-4 6",
  play: "M7 4l12 8-12 8z",
  text: "M4 6h16M4 12h10M4 18h13",
  vertical: "M8 4v16M12 4v16M16 4v10",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  sparkle: "M12 3l1.8 4.9L19 9.5l-5.2 1.6L12 16l-1.8-4.9L5 9.5l5.2-1.6zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
};

/** An inline SVG icon (stroke paths above). */
export function icon(name, cls = "") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `icon ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", PATHS[name] || PATHS.info);
  svg.append(path);
  return svg;
}

export const uid = (p = "") => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const clamp = (x, a, b) => Math.min(b, Math.max(a, x));

export function fmtMs(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return T`${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} 秒`;
  return T`${Math.floor(ms / 60000)} 分 ${Math.round((ms % 60000) / 1000)} 秒`;
}

/** A count with its unit, large ones in 万 and 亿: count(2053597, "段") → "205 万段". */
export function count(n, unit = "") {
  if (n === null || n === undefined || n === "" || Number.isNaN(Number(n))) return `? ${unit}`.trim();
  n = Number(n);
  if (!LANG.startsWith("zh")) return `${new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 1 }).format(n)} ${unit}`.trim();
  const [v, big] = n >= 1e8 ? [n / 1e8, T("亿")] : n >= 1e4 ? [n / 1e4, T("万")] : [n, ""];
  return `${big ? Number(v.toFixed(v >= 100 ? 0 : 1)) : n} ${big}${unit}`.trim();
}

export function dateGroup(ts) {
  const d = new Date(ts), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  if (diff < 1) return T("今天");
  if (diff < 2) return T("昨天");
  if (diff < 7) return T("近 7 天");
  if (diff < 30) return T("近 30 天");
  return T`${d.getFullYear()} 年 ${d.getMonth() + 1} 月`;
}

export function throttleFrame(fn) {
  let queued = false, lastArgs;
  return (...args) => {
    lastArgs = args;
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; fn(...lastArgs); });
  };
}

export function debounce(fn, ms = 200) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { /* nothing more to try */ }
    ta.remove();
    return ok;
  }
}

export function download(name, text, type = "text/plain") {
  downloadBlob(name, new Blob([text], { type: `${type};charset=utf-8` }));
}

/** Save a Blob (an image, say) as a file. */
export function downloadBlob(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

let toastRoot;
export function toast(message, kind = "", ms = 2600) {
  toastRoot ||= document.body.appendChild(h("div.toasts", { role: "status", "aria-live": "polite" }));
  const t = h("div.toast", { class: kind }, message);
  toastRoot.append(t);
  setTimeout(() => t.remove(), ms);
}

export const storage = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch { /* private mode */ }
  },
};

/** Letters and digits only, for comparing a quotation with its source regardless of punctuation and spacing. */
export function bare(text) {
  return String(text || "")
    .normalize("NFKC")
    .replace(/[\s\p{P}\p{S}]/gu, "")
    .toLowerCase();
}

export function truncate(s, n) {
  s = String(s ?? "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/** A short label for a passage: its book and place, e.g. 伤寒论·第12条. */
export function passageLabel(card, pid) {
  if (!card) return pid;
  const title = card.title || card.book_id || "";
  let loc = String(card.locator || "").replace(/^《[^》]*》/, "");
  loc = loc.split(/\s*[·•]\s*/).filter(Boolean).pop() || "";
  return [title, loc].filter(Boolean).join("·") || pid;
}

export function yearLabel(card) {
  if (!card) return "";
  const y = card.year;
  const when = typeof y === "number" ? (y < 0 ? T`前 ${Math.round(-y)} 年` : T`约 ${Math.round(y)} 年`) : "";
  return [card.dynasty, when].filter(Boolean).join(" · ");
}

// a search hit's flags in plain words (docs/adr/0023-alias-layer.md), with what they mean as the title
const FLAG_WORDS = [
  [/^anachronism:(.+)<(-?\d+):(edition|layer)$/u, (m) => ({ text: T("年代存疑"),
    title: T`「${m[1]}」约 ${m[2]} 年后才通行，此段年代更早：${m[3] === "edition" ? T("其字或经后世刊本改动") : T("或为后人增补，或其年代须再考")}` })],
  [/^homonym:(.+)$/u, (m) => ({ text: T("同名异物"), title: T`「${m[1]}」可指不止一味药，此段未能判定所指` })],
  [/^demoted:inside (.+)$/u, (m) => (m[1] === "?" // the longer name was not told: no name to show
    ? { text: T("仅见于他名之中"), title: T("此段只在另一个较长的名字中写到所问之名，未必指所问之药，排在后面") }
    : { text: T`仅见于「${m[1]}」`, title: T`此段只在「${m[1]}」中写到所问之名，未必指所问之药，排在后面` })],
  [/^demoted:no-context$/u, () => ({ text: T("无药物语境"),
    title: T("此段写到所问之名，但不在药物语境中（剂量、炮制、与他药并列等），未必指所问之药，排在后面") })],
  [/^other-referent:(.+)$/u, (m) => ({ text: T("所指不同"), title: T`「${m[1]}」在此段的年代指另一味药` })],
];

function flagWord(flag) {
  if (typeof flag !== "string") return null; // an imported conversation's stray value
  for (const [re, word] of FLAG_WORDS) {
    const m = re.exec(flag);
    if (m) return word(m);
  }
  return null; // a flag the page has no words for is not shown
}

const strings = (v) => (Array.isArray(v) ? v : [v]).filter((x) => typeof x === "string" && x);
const quoted = (names) => names.map((s) => T`「${s}」`).join("");

/** The asked names an other-name `via` stood for: its own `for`, else those of the query's expansions searched under
 * that name, else the asked names — then the expansions' asked names — whose drug is the via's; [] when none is known
 * (the label then names no asked name rather than every one of them). */
function askedNames(v, ctx) {
  for (const names of [strings(v.for), ctx.byName.get(`${v.direction}|${v.surface}`), ctx.askedOf.get(v.referent),
    ctx.forOf.get(v.referent)]) {
    if (names?.length) return names;
  }
  return [];
}

/** One `via` of a hit as the page reads it: the badge it belongs to (`key`) and what goes into it.  A name read as one
 * of its drugs is 读作：鬼督邮→徐长卿.  As in the evidence ledger's words (agents/procedures/evidence.py _via_notes),
 * only an asked name stands before an arrow: a passage found under the drug an asked name is another name of is
 * 别名：国老→甘草 · 别名录（中醫笈成） — the kind when it is not a plain 异名, the asked names, the drug, the first
 * source; a passage that writes another name of the drug asked has no arrow, the drug and then what it writes,
 * 别名：川楝子（写作金铃子） · 词表, and, where that drug was searched for another asked name (鳢肠 asked, 莲子草
 * written, both 旱莲草), that name after it, in a badge of its own: 别名：旱莲草（写作莲子草；所问鳢肠）.  The kind is how
 * the name before the arrow, or the written one, relates to the drug, not which became which.  A false friend asked
 * (stop) says so in the title, as the evidence note does. */
function viaEntry(v, ctx) {
  if (!v || typeof v !== "object" || typeof v.referent !== "string" || !v.referent || typeof v.surface !== "string") return null;
  const source = strings(v.source);
  const witness = strings(v.witness);
  if (v.direction === "asked") {
    const p = typeof v.p === "number" ? T`（p = ${v.p}）` : "";
    return { key: `asked|${v.surface}|${v.referent}`, label: T`读作：${v.surface}→${v.referent}`, source, witness,
      lead: T`据上下文，此段的「${v.surface}」读作${v.referent}${p}` };
  }
  const kind = typeof v.kind === "string" && v.kind ? v.kind : null; // none: a term the lexicon only relates
  const word = kind === null ? T("相关") : kind === "异名" ? T("别名") : kind;
  const writes = v.direction === "drug→alias";
  const asked = writes ? strings(v.for).filter((s) => s !== v.referent) : []; // the asked names it was searched for
  const others = (writes ? [v.surface] : askedNames(v, ctx)).filter((s) => s !== v.referent);
  // its status in words (evidence.py STATUS_WORDS): a false friend is the asked name's (a lexicon via's `for`), a
  // candidate the pair's; open and cue (a gate the passage passed) say nothing
  const concerned = asked.length ? asked : others.length ? others : [v.surface];
  const caveat = v.status === "stop" ? T`${quoted(concerned)}多作普通词语，罕作药名` : v.status === "candidate" ? T("此为候选别名，未经确认") : "";
  // the asked names before an arrow, or the drug with what the passage writes (and the asked names): never one badge
  const form = writes ? (asked.length ? "writes-asked" : "writes") : "asked";
  return { key: `${word}|${v.referent}|${source[0] || ""}|${caveat}|${form}`, word, kind, referent: v.referent, writes,
    surfaces: [v.surface], others, asked, caveat, source, witness };
}

const MAX_NAMES = 4; // other names a badge lists; its title lists all

/** The badge of the vias that share a key: the names merged (别名：屏风、百枝、百蜚、茴草→防风 · 词表 for those asked,
 * 别名：防风（写作屏风、百枝、百蜚、茴草等） · 词表 for those a passage writes), the title saying what the passage writes,
 * how the names relate, which asked names it was searched for, a caveat, the sources and witnesses. */
function viaBadge(entries) {
  const [e] = entries;
  const all = (f) => [...new Set(entries.flatMap(f))];
  const from = all((x) => x.source);
  const tail = [from.length ? T`依据：${from.join(T("、"))}` : "", all((x) => x.witness).map((w) => T`书证 ${w}`).join(T("、"))];
  if (e.lead) return { text: e.label, title: [e.lead, ...tail].filter(Boolean).join(T("；")) };
  const others = all((x) => x.others);
  const written = all((x) => x.surfaces);
  const asked = all((x) => x.asked);
  const names = others.length > MAX_NAMES ? T`${others.slice(0, MAX_NAMES).join(T("、"))}等` : others.join(T("、"));
  const same = others.length === written.length && others.every((s) => written.includes(s)); // the names it writes
  const who = same ? "" : others.length ? quoted(others) : T("所问之名");
  const relation = e.kind === null ? T`${who}与${e.referent}相关`
    : e.kind === "异名" ? T`${who}即${e.referent}（异名）` : T`${who}与${e.referent}：${e.kind}`;
  const lead = T`此段写作${quoted(written)}`;
  const searched = asked.length ? T`为所问${quoted(asked)}检索${e.referent}` : "";
  const told = [names ? T`写作${names}` : "", asked.length ? T`所问${asked.join(T("、"))}` : ""].filter(Boolean).join(T("；"));
  const text = e.writes ? T`${e.word}：${e.referent}${told ? T`（${told}）` : ""}` : T`${e.word}：${names ? `${names}→` : ""}${e.referent}`;
  return { text: [text, e.source[0]].filter(Boolean).join(" · "),
    title: [same ? T`${lead}，${relation}` : T`${lead}；${relation}`, searched, e.caveat, ...tail].filter(Boolean).join(T("；")) };
}

/** What each passage of a search result was found under, for the page (ADR 0023): {passage_id: {labels: [{text,
 * title}], flags: [{text, title}]}} for the hits that carry a `via` (a drug's other name, or the reading of an
 * ambiguous name) or flags (年代存疑, 同名异物 …) — one label per badge, vias of one kind, drug and source merged;
 * {} for any other result. */
export function hitNotes(result) {
  const hits = Array.isArray(result?.hits) ? result.hits : [];
  const view = result?.query?.aliases && typeof result.query.aliases === "object" ? result.query.aliases : {};
  const ctx = { byName: new Map(), askedOf: new Map(), forOf: new Map() };
  const add = (map, key, name) => map.set(key, [...new Set([...(map.get(key) || []), name])]);
  for (const a of Array.isArray(view.asked) ? view.asked : []) {
    if (typeof a?.surface !== "string") continue;
    for (const r of Array.isArray(a.referents) ? a.referents : []) if (typeof r?.head === "string") add(ctx.askedOf, r.head, a.surface);
  }
  for (const e of Array.isArray(view.expansions) ? view.expansions : []) {
    if (typeof e?.surface !== "string" || typeof e.for !== "string" || !e.for) continue;
    add(ctx.byName, `${e.direction}|${e.surface}`, e.for);
    if (typeof e.referent === "string") add(ctx.forOf, e.referent, e.for);
  }
  const out = {};
  for (const hit of hits) {
    if (!hit?.passage_id) continue;
    const groups = new Map();
    for (const v of Array.isArray(hit.via) ? hit.via : []) {
      const e = viaEntry(v, ctx);
      if (e) groups.set(e.key, [...(groups.get(e.key) || []), e]);
    }
    const labels = [...groups.values()].map(viaBadge);
    const flags = (Array.isArray(hit.flags) ? hit.flags : []).map(flagWord).filter(Boolean);
    if (labels.length || flags.length) out[hit.passage_id] = { labels, flags };
  }
  return out;
}

const VIA_LABEL = /^(?:via|读作) /u; // a label's via (via 国老→甘草（…）, via 川楝子（写作金铃子；…）) or reading (读作 …)
const FLAG_HEAD = /^(年代存疑|同名异物|所指不同)（/u; // a flag's word, before what its parenthesis says

/** A card's `labels` — what a taochronos_ask source was found under, in the evidence ledger's words (ADR 0023:
 * agents/procedures/evidence.py hit_note) — as its `found`: each via or reading a label, each flag one in warn, by its
 * word (年代存疑, 同名异物, 仅见于「…」 …) as a search's badges show it, the whole label in its title; null without one. */
function labelsFound(labels) {
  const all = strings(labels);
  if (!all.length) return null;
  const legend = T("via 甲→乙：所问为甲，经乙（所指之药）检出；via 乙（写作丙）：检索乙本身（或未记所问之名）时检出，此段写作丙；")
    + T("读作 甲→乙：多义之名甲在此段的读法");
  return {
    labels: all.filter((s) => VIA_LABEL.test(s)).map((s) => ({ text: s, title: T`${s}。${legend}` })),
    flags: all.filter((s) => !VIA_LABEL.test(s)).map((s) => ({ text: FLAG_HEAD.exec(s)?.[1] || s, title: s })),
  };
}

/** The passage cards of a tool's result, each hit of a search (a result with `hits` and a parsed `query`) with what
 * the search found it under: `found` from hitNotes, or null for a hit found as asked — so that the latest search to
 * return a passage says what it was found under.  A card with `labels` (a taochronos_ask source the workflow's search
 * found under another name of a drug, or flagged) has them as its `found` instead, and an unlabelled one is left as
 * it is (it may not be a search's).  Any other card as it is. */
export function withFound(cards, result) {
  const query = result?.query;
  const search = Array.isArray(result?.hits) && query && typeof query === "object" && Array.isArray(query.terms);
  if (!search && !(cards || []).some((c) => c && typeof c === "object" && "labels" in c)) return cards;
  const notes = search ? hitNotes(result) : {};
  const hit = new Set(search ? result.hits.map((x) => x?.passage_id).filter(Boolean) : []);
  return (cards || []).map((c) => {
    if (!c?.passage_id) return c;
    const { labels, ...card } = c; // the labels live on as `found`, which the latest search to return the passage sets
    if (hit.has(c.passage_id)) return { ...card, found: notes[c.passage_id] || null };
    if (!("labels" in c)) return c;
    const found = labelsFound(labels);
    return found ? { ...card, found } : card;
  });
}

const WRAP = { whiteSpace: "normal", maxWidth: "100%" }; // a long label wraps where a drawer or a phone is narrow

/** A card's `found` as badges: each label, then each flag (warn); what they mean in their titles.  [] without one. */
export function foundBadges(found) {
  if (!found || typeof found !== "object") return [];
  const items = (list) => (Array.isArray(list) ? list : []).filter((x) => x && typeof x === "object" && typeof x.text === "string" && x.text);
  const badge = (tag) => (x) => h(tag, { title: typeof x.title === "string" && x.title ? x.title : x.text, style: WRAP }, x.text);
  return [...items(found.labels).map(badge("span.badge")), ...items(found.flags).map(badge("span.badge.warn"))];
}

export function prettyJSON(value, limit = 60000) {
  let s;
  try { s = JSON.stringify(value, null, 2); } catch { s = String(value); }
  return s && s.length > limit ? s.slice(0, limit) + T`\n…（已截断，共 ${s.length} 字符）` : s;
}
