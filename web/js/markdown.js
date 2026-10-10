// A small, safe Markdown renderer: it builds DOM nodes and never parses HTML, so a model's answer cannot inject markup.
// Blocks: headings, paragraphs, lists (nested), block quotes, fenced code, GFM tables, rules, and ```chart blocks — a
// chart specification in JSON, drawn by chart.js (while it is still being written, a placeholder).  Inline: code, bold,
// italic, strike, links (http/https/mailto only), bare URLs, 「quotations」 and [[passage_id]] citations.  Each
// citation is paired with the quotation just before it (「…」[[id]]), so the client can check the words against the
// passage.

import { chartCard, invalid } from "./chart.js";
import { append, h, icon } from "./util.js";

const FENCE = /^(\s{0,3})(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const ITEM = /^(\s*)([-*+•]|\d{1,3}[.)、])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const CITE_ID = /^[\w.:\-/]{1,120}$/;

export function renderMarkdown(text, opts = {}) {
  const frag = document.createDocumentFragment();
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  blocks(lines, frag, opts);
  if (opts.streaming) {
    // the caret follows the last words written: descend into the last list item or quotation
    let target = frag.lastElementChild;
    while (target && ["UL", "OL", "LI", "BLOCKQUOTE"].includes(target.nodeName)) {
      const child = target.lastChild;
      if (child && child.nodeType === 1 && ["UL", "OL", "LI", "BLOCKQUOTE", "P"].includes(child.nodeName)) target = child;
      else break;
    }
    const caret = h("span.caret", { "aria-hidden": "true" });
    if (target && !["PRE", "TABLE", "HR", "FIGURE", "DIV"].includes(target.nodeName)) target.append(caret);
    else frag.append(h("p", caret));
  }
  return frag;
}

function blocks(lines, parent, opts) {
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = FENCE.exec(line))) {
      const fence = m[2], lang = m[3];
      const body = [];
      let closed = false;
      i++;
      while (i < lines.length) {
        const t = lines[i].trim();
        if (t.startsWith(fence[0].repeat(fence.length)) && !t.slice(fence.length).trim()) { closed = true; break; }
        body.push(lines[i]);
        i++;
      }
      i++;
      if (lang.toLowerCase() === "chart") parent.append(...chartBlock(body.join("\n"), closed, opts));
      else parent.append(codeBlock(body.join("\n"), lang));
      continue;
    }
    if ((m = HEADING.exec(line))) {
      parent.append(h(`h${Math.min(m[1].length + 1, 4)}`, inline(m[2], opts)));
      i++;
      continue;
    }
    if (RULE.test(line)) { parent.append(h("hr")); i++; continue; }
    if (QUOTE.test(line)) {
      const inner = [];
      while (i < lines.length && lines[i].trim() && QUOTE.test(lines[i])) inner.push(QUOTE.exec(lines[i++])[1]);
      const bq = h("blockquote");
      blocks(inner, bq, opts);
      parent.append(bq);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const rows = [line];
      const sep = lines[i + 1];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(lines[i++]);
      parent.append(table(rows, sep, opts));
      continue;
    }
    if (ITEM.test(line)) {
      const block = [];
      while (i < lines.length) {
        const l = lines[i];
        if (!l.trim()) {
          const next = lines.slice(i + 1).find((x) => x.trim());
          if (next !== undefined && (ITEM.test(next) || /^\s{2,}\S/.test(next))) { block.push(""); i++; continue; }
          break;
        }
        if (ITEM.test(l) || /^\s{2,}\S/.test(l) || (block.length && !startsBlock(l, lines[i + 1]))) { block.push(l); i++; continue; }
        break;
      }
      parent.append(list(block, opts));
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !(para.length && startsBlock(lines[i], lines[i + 1]))) para.push(lines[i++]);
    parent.append(h("p", inline(para.join("\n"), opts)));
  }
}

function startsBlock(line, next) {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) || ITEM.test(line) ||
    (line.includes("|") && next !== undefined && TABLE_SEP.test(next) && next.includes("-"));
}

function codeBlock(code, lang) {
  const pre = h("pre", h("code", { dataset: { lang: lang || "" } }, code));
  if (lang) pre.append(h("span.lang", lang));
  pre.append(h("button.icon-btn.copy", { type: "button", title: "复制代码", "aria-label": "复制代码", dataset: { copy: "code" } }, icon("copy", "sm")));
  return pre;
}

// a chart block's JSON → its card: an answer is drawn again on every streamed update, its charts are not
const drawn = new Map();

function chartBlock(code, closed, opts) {
  if (!closed && opts.streaming) return [h("div.chart-wait", h("span.spinner"), "正在绘制图表…")];
  let spec = null, why;
  try { spec = JSON.parse(code); why = invalid(spec); } catch (err) { why = `规格不是合法的 JSON（${err.message}）`; }
  if (why) return [codeBlock(code, "chart"), h("p.viz-note", `未能绘制此图：${why}`)];
  let card = drawn.get(code);
  if (!card || card.isConnected) { // the same chart twice on the page: a second card
    card = chartCard(spec);
    drawn.set(code, card);
    if (drawn.size > 60) drawn.delete(drawn.keys().next().value);
  }
  return [card];
}

function splitRow(row) {
  let s = row.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells = [];
  let cur = "", code = false;
  for (let k = 0; k < s.length; k++) {
    const c = s[k];
    if (c === "`") code = !code;
    if (c === "\\" && s[k + 1] === "|") { cur += "|"; k++; continue; }
    if (c === "|" && !code) { cells.push(cur.trim()); cur = ""; continue; }
    cur += c;
  }
  cells.push(cur.trim());
  return cells;
}

function table(rows, sep, opts) {
  const aligns = splitRow(sep).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : ""));
  const head = splitRow(rows[0]);
  const t = h("table");
  const tr = h("tr");
  head.forEach((c, k) => tr.append(h("th", { style: aligns[k] ? { textAlign: aligns[k] } : null }, inline(c, opts))));
  t.append(h("thead", tr));
  const body = h("tbody");
  for (const r of rows.slice(1)) {
    const cells = splitRow(r);
    const row = h("tr");
    head.forEach((_, k) => row.append(h("td", { style: aligns[k] ? { textAlign: aligns[k] } : null }, inline(cells[k] ?? "", opts))));
    body.append(row);
  }
  t.append(body);
  return t;
}

function list(block, opts) {
  // items at the smallest indent belong to this list; deeper lines belong to the item above them
  const items = [];
  const base = Math.min(...block.filter((l) => ITEM.test(l)).map((l) => ITEM.exec(l)[1].length));
  for (const l of block) {
    const m = ITEM.exec(l);
    if (m && m[1].length <= base + 1) items.push({ marker: m[2], lines: [m[3]] });
    else if (items.length) items[items.length - 1].lines.push(l.replace(new RegExp(`^\\s{0,${base + 4}}`), ""));
  }
  const ordered = /\d/.test(items[0]?.marker || "");
  const el = h(ordered ? "ol" : "ul");
  if (ordered) {
    const start = parseInt(items[0].marker, 10);
    if (start > 1) el.setAttribute("start", String(start));
  }
  for (const it of items) {
    const li = h("li");
    const [first, ...rest] = it.lines;
    if (rest.some((l) => l.trim())) {
      const sub = document.createDocumentFragment();
      blocks([first, ...rest], sub, opts);
      // a single paragraph stays inline in the item
      if (sub.firstChild && sub.firstChild.nodeName === "P") {
        const p = sub.firstChild;
        while (p.firstChild) li.append(p.firstChild);
        p.remove();
      }
      li.append(sub);
    } else {
      append(li, inline(first, opts));
    }
    el.append(li);
  }
  return el;
}

// ------------------------------------------------------------------ inline
const INLINE = [
  { re: /`([^`\n]+)`/y, make: (m) => h("code", m[1]) },
  { re: /\[\[([^\[\]\n]{1,300})\]\]/y, make: (m, ctx) => citeNodes(m[1], ctx) },
  { re: /\[([^\]\n]{1,300})\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/y, make: (m, ctx) => h("a", { href: m[2], target: "_blank", rel: "noopener noreferrer" }, inlineInner(m[1], ctx)) },
  { re: /https?:\/\/[^\s<>「」（）()，。、；！？"'\]]+[^\s<>「」（）()，。、；！？"'\].,;:!?]/y, make: (m) => h("a", { href: m[0], target: "_blank", rel: "noopener noreferrer" }, m[0]) },
  { re: /\*\*(?=\S)([^\n]+?)(?<=\S)\*\*/y, make: (m, ctx) => h("strong", inlineInner(m[1], ctx)) },
  { re: /__(?=\S)([^\n]+?)(?<=\S)__(?![\w])/y, make: (m, ctx) => h("strong", inlineInner(m[1], ctx)) },
  { re: /~~(?=\S)([^\n]+?)(?<=\S)~~/y, make: (m, ctx) => h("s", inlineInner(m[1], ctx)) },
  { re: /\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*/y, make: (m, ctx) => h("em", inlineInner(m[1], ctx)) },
  { re: /「([^「」\n]{1,600})」/y, make: (m, ctx) => h("q.yin", inlineInner(m[1], ctx)) },
];
const TRIGGER = /[`[\]*_~「h]/;

function inline(text, opts) {
  const ctx = { opts, quotes: pairQuotes(text), n: 0 };
  return inlineInner(text, ctx);
}

/** For each citation in the text, in order: the quotation that ends just before it (「…」[[id]]), if any. */
function pairQuotes(text) {
  const scan = text.replace(/`[^`\n]+`/g, (s) => " ".repeat(s.length));
  const out = [];
  let last = null;
  for (const m of scan.matchAll(/「([^「」\n]{1,600})」|\[\[([^\[\]\n]{1,300})\]\]/g)) {
    if (m[1] !== undefined) { last = { text: m[1], end: m.index + m[0].length }; continue; }
    const near = last && m.index - last.end <= 40 && !scan.slice(last.end, m.index).includes("\n") ? last.text : null;
    out.push(near);
    if (last) last.end = m.index + m[0].length; // 「…」[[a]][[b]]: the same words, two witnesses
  }
  return out;
}

function inlineInner(text, ctx) {
  const out = [];
  let buf = "";
  let i = 0;
  const flush = () => {
    if (!buf) return;
    const parts = buf.split("\n");
    parts.forEach((p, k) => { if (k) out.push(h("br")); if (p) out.push(document.createTextNode(p)); });
    buf = "";
  };
  while (i < text.length) {
    const c = text[i];
    if (c === "\\" && i + 1 < text.length && /[\\`*_\[\]()#+\-.!|~「」]/.test(text[i + 1])) { buf += text[i + 1]; i += 2; continue; }
    if (TRIGGER.test(c)) {
      let matched = false;
      for (const rule of INLINE) {
        if (c === "h" && !rule.re.source.startsWith("https?")) continue;
        rule.re.lastIndex = i;
        const m = rule.re.exec(text);
        if (m) {
          if (rule.re.source.startsWith("__") && i > 0 && /\w/.test(text[i - 1])) continue;
          flush();
          out.push(rule.make(m, ctx));
          i += m[0].length;
          matched = true;
          break;
        }
      }
      if (matched) continue;
    }
    buf += c;
    i++;
  }
  flush();
  return out;
}

function citeNodes(inner, ctx) {
  const ids = inner.split(/[,，;；、\s]+/).map((s) => s.trim()).filter(Boolean);
  const quote = ctx.quotes[ctx.n++] ?? null;
  if (!ids.length || !ids.every((id) => CITE_ID.test(id))) return document.createTextNode(`[[${inner}]]`);
  const make = ctx.opts.cite;
  return ids.map((id) => (make ? make(id, quote) : h("span.cite", id)));
}

/** The citations of an answer, in order, each with the quotation it follows: [{pid, quote}]. */
export function extractCitations(text) {
  const out = [];
  for (const block of String(text || "").split(/\n\s*\n/)) {
    const quotes = pairQuotes(block);
    let n = 0;
    for (const m of block.replace(/`[^`\n]+`/g, (x) => " ".repeat(x.length)).matchAll(/\[\[([^\[\]\n]{1,300})\]\]/g)) {
      const quote = quotes[n++] ?? null;
      const ids = m[1].split(/[,，;；、\s]+/).map((x) => x.trim()).filter(Boolean);
      if (!ids.length || !ids.every((id) => CITE_ID.test(id))) continue;
      for (const pid of ids) out.push({ pid, quote });
    }
  }
  return out;
}
