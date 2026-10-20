// 三线表 — the tables the study tools return (taochronos/plugins/classics/study/tables.py), and the tables of an answer,
// printed as a journal prints them: the number and title above (表 1　…), a rule over the column heads, a rule under
// them (and a short one under each group head), a rule under the last row, no vertical lines; the notes below.
// Statistical symbols are set in italics (P, n, z, H, t, r, ρ, q, x̄, s).  Each table copies into Word or Excel (HTML with
// its rules inline, and tab-separated text) and downloads as Word (.docx), LaTeX (booktabs), CSV (with a byte-order mark)
// and Markdown — the same files `taochronos study … --charts` writes (study/tablefmt.py).

import { zip } from "./bytes.js";
import { downloadBlob, download, h, icon, toast } from "./util.js";
import { T } from "./i18n.js";

const SYMBOL = /(?<![A-Za-z])(P|n|z|H|t|r|q|s|x̄|ρ)(?![A-Za-z̄])/g;

/** Text cut into [piece, italic]: the statistical symbols italic. */
export function runs(text) {
  const s = String(text ?? "");
  const out = [];
  let at = 0;
  for (const m of s.matchAll(SYMBOL)) {
    if (m.index > at) out.push([s.slice(at, m.index), false]);
    out.push([m[0], true]);
    at = m.index + m[0].length;
  }
  if (at < s.length) out.push([s.slice(at), false]);
  return out.length ? out : [["", false]];
}

/** null when the specification can be printed, else why not. */
export function invalidTable(spec) {
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return T("表格规格应为 JSON 对象");
  if (!Array.isArray(spec.columns) || !spec.columns.length || !spec.columns.every((c) => c && typeof c.key === "string")) return T("表格需要 columns");
  if (!Array.isArray(spec.rows) || !spec.rows.length) return T("表格需要 rows");
  if (spec.rows.length > 2000 || spec.columns.length > 40) return T("表格过大");
  return null;
}

/** The tables a tool result carries (at most ``limit``). */
export function tablesOf(result, limit = 8) {
  const list = result && typeof result === "object" && Array.isArray(result.tables) ? result.tables : [];
  return list.filter((t) => !invalidTable(t)).slice(0, limit);
}

export const caption = (spec, number) => (number !== undefined && number !== null && number !== "" ? T`表${number}　${spec.title || ""}` : String(spec.title || ""));

const cells = (spec) => spec.rows.map((r) => spec.columns.map((c) => String(r[c.key] ?? "")));
const flatHeads = (spec) => spec.columns.map((c) => (c.group ? `${c.group} · ${c.label}` : c.label));
const notesOf = (spec) => [...(spec.notes || []).map((n, i) => (i ? n : T`注：${n}`)), ...(spec.source ? [T`资料来源：${spec.source}`] : [])];

/** The column heads as rows of cells {label, span, rows, col, group}: one row, or two when columns have groups. */
export function headRows(spec) {
  const cols = spec.columns;
  if (!cols.some((c) => c.group)) return [cols.map((c, i) => ({ label: c.label, span: 1, rows: 1, col: i }))];
  const top = [], bottom = [];
  for (let i = 0; i < cols.length;) {
    const g = cols[i].group;
    if (!g) { top.push({ label: cols[i].label, span: 1, rows: 2, col: i }); i++; continue; }
    let j = i;
    while (j + 1 < cols.length && cols[j + 1].group === g) j++;
    top.push({ label: g, span: j - i + 1, rows: 1, col: i, group: true });
    for (let k = i; k <= j; k++) bottom.push({ label: cols[k].label, span: 1, rows: 1, col: k });
    i = j + 1;
  }
  return [top, bottom];
}

// ------------------------------------------------------------------ the files
/** A cell a spreadsheet would read as a formula (=, +, -, @ … that is not a number) is kept as text: an answer's table could
 * otherwise carry a formula into Excel. */
export const defuse = (x) => { const s = String(x ?? ""); return /^[=+\-@\t\r]/.test(s) && !/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s) ? `'${s}` : s; };
const csvCell = (x) => { const s = defuse(x); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };

export function toCSV(spec, bom = true) {
  return (bom ? "﻿" : "") + [flatHeads(spec), ...cells(spec)].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

/** Tab-separated text (for a spreadsheet's paste). */
export function toTSV(spec) {
  const clean = (x) => defuse(String(x ?? "").replace(/[\t\r\n]+/g, " "));
  return [flatHeads(spec), ...cells(spec)].map((r) => r.map(clean).join("\t")).join("\n");
}

export function toMarkdown(spec, number) {
  const cell = (x) => String(x ?? "").replace(/\|/g, "\\|").replace(/\n/g, " ");
  const align = { left: ":---", right: "---:", center: ":---:" };
  const lines = [`**${caption(spec, number)}**`, "", `| ${flatHeads(spec).map(cell).join(" | ")} |`,
    `| ${spec.columns.map((c) => align[c.align] || "---").join(" | ")} |`, ...cells(spec).map((r) => `| ${r.map(cell).join(" | ")} |`)];
  for (const n of notesOf(spec)) lines.push("", n);
  return lines.join("\n") + "\n";
}

const TEX = { "\\": "\\textbackslash{}", "&": "\\&", "%": "\\%", $: "\\$", "#": "\\#", _: "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}" };
const TEX_SYMBOL = { "x̄": "$\\bar{x}$", "ρ": "$\\rho$" };

export function tex(text) {
  return runs(text).map(([p, it]) => {
    const esc = [...p].map((ch) => TEX[ch] ?? ch).join("");
    return it ? TEX_SYMBOL[p] || `\\textit{${esc}}` : esc;
  }).join("");
}

export function toLaTeX(spec, number) {
  const cols = spec.columns;
  const heads = headRows(spec);
  const lines = [T`% ${caption(spec, number)} — 需 \\usepackage{booktabs}${heads.length === 2 ? T("、\\usepackage{multirow}") : ""}；中文用 ctex 宏包，以 XeLaTeX 编译`,
    "\\begin{table}[htbp]", "\\centering", `\\caption{${tex(spec.title || "")}}`, `\\label{tab:${String(spec.id || "table").replace(/[^A-Za-z0-9-]/g, "-")}}`,
    `\\begin{tabular}{${cols.map((c) => ({ left: "l", right: "r", center: "c" })[c.align] || "l").join("")}}`, "\\toprule"];
  if (heads.length === 2) {
    lines.push(heads[0].map((c) => (c.group ? `\\multicolumn{${c.span}}{c}{${tex(c.label)}}` : `\\multirow{2}{*}{${tex(c.label)}}`)).join(" & ") + " \\\\",
      heads[0].filter((c) => c.group).map((c) => `\\cmidrule(lr){${c.col + 1}-${c.col + c.span}}`).join(" "));
    const bottom = new Map(heads[1].map((c) => [c.col, c]));
    lines.push(cols.map((_, i) => (bottom.has(i) ? tex(bottom.get(i).label) : "")).join(" & ") + " \\\\");
  } else lines.push(heads[0].map((c) => tex(c.label)).join(" & ") + " \\\\");
  lines.push("\\midrule", ...cells(spec).map((r) => r.map(tex).join(" & ") + " \\\\"), "\\bottomrule", "\\end{tabular}");
  const notes = notesOf(spec);
  if (notes.length) lines.push("\\par\\smallskip", "\\begin{minipage}{\\linewidth}\\footnotesize", ...notes.map((n) => `${tex(n)}\\par`), "\\end{minipage}");
  lines.push("\\end{table}");
  return lines.join("\n") + "\n";
}

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const htmlText = (s) => runs(s).map(([p, it]) => (it ? `<i>${esc(p)}</i>` : esc(p))).join("");

/** The table as HTML with its rules inline — what Word and WPS keep when it is pasted. */
export function toHTML(spec, number) {
  const rule = "1.5pt solid #000", thin = "0.75pt solid #000", pad = "padding:3pt 7pt;vertical-align:middle;";
  const heads = headRows(spec);
  const out = [`<p style="text-align:center;font-weight:bold;margin:12pt 0 4pt;font-size:10.5pt">${htmlText(caption(spec, number))}</p>`,
    `<table style="border-collapse:collapse;margin:0 auto;border-top:${rule};border-bottom:${rule};font-size:10.5pt;font-family:'Times New Roman',SimSun,'Songti SC',serif">`, "<thead>"];
  for (const row of heads) {
    out.push(`<tr>${row.map((c) => `<th${c.span > 1 ? ` colspan="${c.span}"` : ""}${c.rows > 1 ? ` rowspan="${c.rows}"` : ""} style="${pad}text-align:center;font-weight:normal;border-bottom:${thin}">${htmlText(c.label)}</th>`).join("")}</tr>`);
  }
  out.push("</thead><tbody>");
  for (const r of cells(spec)) out.push(`<tr>${r.map((x, i) => `<td style="${pad}text-align:${spec.columns[i].align || "left"}">${htmlText(x)}</td>`).join("")}</tr>`);
  out.push("</tbody></table>");
  const notes = notesOf(spec);
  if (notes.length) out.push(`<div style="font-size:9pt;margin:4pt 0 12pt">${notes.map((n) => `<p style="margin:0">${htmlText(n)}</p>`).join("")}</div>`);
  return out.join("\n");
}

// ------------------------------------------------------------------ Word (.docx): the same document study/tablefmt.py writes
const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const CONTENT_TYPES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
  + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
  + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
  + '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>';
const RELS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
  + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>';
const DOC_RELS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
  + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>';
const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles xmlns:w="${W}"><w:docDefaults><w:rPrDefault><w:rPr>`
  + '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体" w:cs="Times New Roman"/><w:sz w:val="21"/><w:szCs w:val="21"/>'
  + '<w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
  + '</w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
  + '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar><w:top w:w="0" w:type="dxa"/>'
  + '<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style></w:styles>';
const TEXT_WIDTH = 9026;
const width1 = (t) => { let w = 0; for (const ch of String(t).replace(/→/g, "汉")) w += ch.codePointAt(0) > 0x2e80 ? 1 : 0.58; return w; };

const wRuns = (text, { bold = false, size = null } = {}) => runs(text).map(([p, it]) => {
  const props = (bold ? "<w:b/>" : "") + (it ? "<w:i/>" : "") + (size ? `<w:sz w:val="${size}"/><w:szCs w:val="${size}"/>` : "");
  return `<w:r>${props ? `<w:rPr>${props}</w:rPr>` : ""}<w:t xml:space="preserve">${esc(p).replace(/&quot;/g, '"')}</w:t></w:r>`;
}).join("");

const wPara = (text, { align = "left", bold = false, size = null, before = 0, after = 0, keep = false } = {}) =>
  `<w:p><w:pPr>${keep ? "<w:keepNext/>" : ""}<w:spacing w:before="${before}" w:after="${after}"/><w:jc w:val="${align === "right" ? "right" : align === "center" ? "center" : "left"}"/></w:pPr>${wRuns(text, { bold, size })}</w:p>`;

function wTable(spec) {
  const cols = spec.columns;
  const body = cells(spec);
  const longest = cols.map((c, i) => Math.max(3, Math.min(30, Math.max(width1(c.label), ...body.map((r) => width1(r[i]))))));
  const total = longest.reduce((a, b) => a + b, 0);
  const scale = Math.min(TEXT_WIDTH / total, 210);
  const widths = longest.map((w) => Math.max(600, Math.floor(w * scale * 1.12) + 260));
  const heads = headRows(spec);
  const rule = 'w:val="single" w:sz="12" w:space="0" w:color="000000"', thin = 'w:val="single" w:sz="6" w:space="0" w:color="000000"';
  const out = [`<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:jc w:val="center"/><w:tblBorders><w:top ${rule}/><w:left w:val="nil"/><w:bottom ${rule}/>`
    + '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders><w:tblLayout w:type="autofit"/>'
    + '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>',
  `<w:tblGrid>${widths.map((w) => `<w:gridCol w:w="${w}"/>`).join("")}</w:tblGrid>`];
  const covered = new Set();
  heads.forEach((row, k) => {
    const last = k === heads.length - 1;
    const at = new Map(row.map((c) => [c.col, c]));
    const tcs = [];
    for (let col = 0; col < cols.length;) {
      const c = at.get(col);
      if (!c && covered.has(col)) {
        tcs.push(`<w:tc><w:tcPr><w:tcW w:w="${widths[col]}" w:type="dxa"/><w:vMerge/><w:tcBorders><w:bottom ${thin}/></w:tcBorders><w:vAlign w:val="center"/></w:tcPr><w:p/></w:tc>`);
        col++;
        continue;
      }
      const w = widths.slice(col, col + c.span).reduce((a, b) => a + b, 0);
      const border = last || c.group || c.rows === heads.length ? `<w:tcBorders><w:bottom ${thin}/></w:tcBorders>` : "";
      tcs.push(`<w:tc><w:tcPr><w:tcW w:w="${w}" w:type="dxa"/>${c.span > 1 ? `<w:gridSpan w:val="${c.span}"/>` : ""}${c.rows > 1 ? '<w:vMerge w:val="restart"/>' : ""}${border}<w:vAlign w:val="center"/></w:tcPr>${wPara(c.label, { align: "center" })}</w:tc>`);
      if (c.rows > 1) covered.add(col);
      col += c.span;
    }
    out.push(`<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>${tcs.join("")}</w:tr>`);
  });
  for (const r of body) {
    out.push(`<w:tr><w:trPr><w:cantSplit/></w:trPr>${r.map((x, i) => `<w:tc><w:tcPr><w:tcW w:w="${widths[i]}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>${wPara(x, { align: cols[i].align })}</w:tc>`).join("")}</w:tr>`);
  }
  out.push("</w:tbl>");
  return out.join("");
}

export function documentXML(specs, numbers) {
  const body = specs.map((spec, i) => [
    wPara(caption(spec, numbers ? numbers[i] : i + 1), { align: "center", bold: true, before: 240, after: 80, keep: true }),
    wTable(spec), ...notesOf(spec).map((n) => wPara(n, { size: 18, before: 40 })), "<w:p/>"].join("")).join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="${W}"><w:body>${body}`
    + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="851" w:footer="992" w:gutter="0"/></w:sectPr></w:body></w:document>';
}

/** A Word document of the tables, each numbered (表 1 …) with its notes: the bytes of the .docx. */
export function docxBytes(specs, numbers) {
  return zip([{ name: "[Content_Types].xml", data: CONTENT_TYPES }, { name: "_rels/.rels", data: RELS },
    { name: "word/_rels/document.xml.rels", data: DOC_RELS }, { name: "word/styles.xml", data: STYLES },
    { name: "word/document.xml", data: documentXML(specs, numbers) }]);
}

const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const safeName = (s) => String(s || "table").replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "table";

export function saveTable(spec, kind, number) {
  const name = safeName(caption(spec, number));
  try {
    if (kind === "docx") downloadBlob(`${name}.docx`, new Blob([docxBytes([spec], [number ?? 1])], { type: DOCX }));
    else if (kind === "tex") download(`${name}.tex`, toLaTeX(spec, number), "application/x-tex");
    else if (kind === "csv") download(`${name}.csv`, toCSV(spec), "text/csv");
    else if (kind === "md") download(`${name}.md`, toMarkdown(spec, number), "text/markdown");
  } catch (err) {
    toast(T`下载失败：${err.message || err}`, "err");
  }
}

/** All the tables of a result in one Word document. */
export function saveTables(specs, name = T("表格")) {
  try { downloadBlob(`${safeName(name)}.docx`, new Blob([docxBytes(specs)], { type: DOCX })); } catch (err) { toast(T`下载失败：${err.message || err}`, "err"); }
}

/** Copy the table as HTML with its rules (Word, WPS) and as tab-separated text (Excel, plain text). */
export async function copyTable(spec, number) {
  const html = toHTML(spec, number), text = toTSV(spec);
  try {
    if (navigator.clipboard?.write && typeof ClipboardItem !== "undefined") {
      await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([text], { type: "text/plain" }) })]);
    } else await navigator.clipboard.writeText(text);
    toast(T("已复制：粘贴到 Word 为三线表，粘贴到 Excel 为单元格"));
  } catch {
    toast(T("复制失败：浏览器未允许访问剪贴板，可改用下载"), "err");
  }
}

// ------------------------------------------------------------------ in the page
const italic = (text) => runs(text).map(([p, it]) => (it ? h("i", p) : p));

/** A three-line table: <table> with its heads (grouped when the columns are) and rows. */
export function sciTable(spec) {
  const heads = headRows(spec);
  return h("table.sci-table",
    h("thead", ...heads.map((row) => h("tr", ...row.map((c) => h(c.group ? "th.group" : "th", { colSpan: c.span, rowSpan: c.rows, scope: c.span > 1 ? "colgroup" : "col" }, italic(c.label)))))),
    h("tbody", ...cells(spec).map((r) => h("tr", ...r.map((x, i) => h("td", { class: `a-${spec.columns[i].align || "left"}` }, italic(x)))))));
}

let menusWatched = false;
function closeMenus() { for (const m of document.querySelectorAll(".viz-menu:not([hidden])")) m.hidden = true; }

/** A menu of downloads behind a button: [[label, fn]] items. */
export function menuButton(label, items, title) {
  const menu = h("div.viz-menu", { hidden: true, role: "menu" },
    ...items.map(([text, fn]) => h("button", { type: "button", role: "menuitem", on: { click: () => { menu.hidden = true; fn(); } } }, text)));
  const btn = h("button.btn-ghost.viz-toggle", { type: "button", "aria-haspopup": "menu", "aria-expanded": "false", title }, icon("download", "sm"), label);
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    closeMenus();
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) menu.querySelector("button")?.focus();
  });
  menu.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { menu.hidden = true; btn.focus(); }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const list = [...menu.querySelectorAll("button")];
      const i = list.indexOf(document.activeElement);
      list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length].focus();
    }
  });
  if (!menusWatched) { menusWatched = true; document.addEventListener("click", (e) => { if (e.isTrusted) closeMenus(); }); } // a download's own click is not one
  return h("div.viz-dl", btn, menu);
}

/** The downloads and copy of a table. */
export function tableTools(spec, number) {
  return [
    h("button.btn-ghost.viz-toggle", { type: "button", title: T("复制：粘贴到 Word 为三线表，粘贴到 Excel 为单元格"), on: { click: () => copyTable(spec, number) } }, icon("copy", "sm"), T("复制")),
    menuButton(T("下载"), [[T("Word 文档（.docx）"), () => saveTable(spec, "docx", number)], [T("LaTeX（booktabs）"), () => saveTable(spec, "tex", number)],
      [T("CSV 数据"), () => saveTable(spec, "csv", number)], ["Markdown", () => saveTable(spec, "md", number)]], T("下载表格")),
  ];
}

/** A table card: 表 n and its title, the three-line table, its notes and source, copy and downloads. */
export function tableCard(spec, number) {
  if (invalidTable(spec)) return null;
  return h("figure.tbl-card",
    h("figcaption", h("div.cap", h("span.title", number !== undefined ? h("b", T`表${number}`) : null, number !== undefined ? T("　") : "", spec.title || T("表格"))),
      h("div.tools", ...tableTools(spec, number))),
    h("div.tbl-wrap", { tabindex: 0, role: "region", "aria-label": caption(spec, number) }, sciTable(spec)),
    notesOf(spec).length ? h("div.tbl-notes", ...notesOf(spec).map((n) => h("p", italic(n)))) : null);
}

// one card per specification and number: a turn is drawn again on every streamed update
const cards = new WeakMap();
export function cachedTable(spec, number) {
  if (!spec || typeof spec !== "object") return null;
  let byNumber = cards.get(spec);
  if (!byNumber) cards.set(spec, (byNumber = new Map()));
  if (!byNumber.has(number)) byNumber.set(number, tableCard(spec, number));
  return byNumber.get(number);
}

/** A table of an answer (Markdown) as a specification: its heads and cells as written, the title from a "表1 …" line
 * above it and the notes from a "注：…" line below. */
export function specFromTable(table, title = "", notes = []) {
  const heads = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
  const align = [...table.querySelectorAll("thead th")].map((th) => th.style.textAlign || "left");
  const columns = heads.map((label, i) => ({ key: `c${i}`, label, align: align[i] }));
  const rows = [...table.querySelectorAll("tbody tr")].map((tr) => Object.fromEntries([...tr.children].map((td, i) => [`c${i}`, td.textContent.trim()])));
  const m = /^表\s*([\dA-Za-z.-]+)[\s　:：.、]*(.*)$/.exec(title.trim());
  return { spec: { version: 1, id: "answer-table", title: m ? m[2] : title, columns, rows, notes: notes.map((n) => n.replace(/^注[：:]\s*/, "")) }, number: m ? m[1] : undefined };
}
