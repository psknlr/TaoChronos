// One answer, exported in one click (⤓ beside 👍 👎 under it): a Word document (.docx) with the question, the answer as
// the page shows it — headings, paragraphs, lists, quotations, code, links, its tables as Word tables and its charts as
// figures —, the figures, tables and documents the turn's tools made, and the passages it cites with how each
// quotation checked against the source; zipped with the figures as PNG and SVG, the tables as CSV, the tools'
// documents and the answer as Markdown.  Everything is made in this browser: nothing is sent anywhere.

import { zip } from "./bytes.js";
import { figureSVG, invalid, journalWidth, normalize, pngBlob, specOf } from "./chart.js";
import { LANG, LANGUAGE, T } from "./i18n.js";
import { renderMarkdown } from "./markdown.js";
import { caption as tableCaption, specFromTable, tableXML, toCSV } from "./table.js";
import { h } from "./util.js";

const RTL = Boolean(LANGUAGE.rtl);
const TEXT_EMU = 5731510; // the text's width on an A4 page with 2.54 cm margins, in EMU (9026 twips)
const EMU_PER_MM = 36000;
const FIGURE = "onehalf"; // a journal's one-and-a-half-column figure: its width in millimetres, as printed
const PNG_SCALE = 3; // figures rasterised at three times their design size: sharp in print

const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
  + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
  + 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
  + 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
  + 'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"';
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

/** Text as XML may carry it: escaped, without the control characters XML 1.0 forbids. */
const xml = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, ""); // eslint-disable-line no-control-regex

// ------------------------------------------------------------------ runs and paragraphs (their children in the schema's order)
/** A run of text with its formatting: f = {bold, italic, strike, code, color, size, underline, style}; a line break in
 * the text, a break in the run. */
export function run(text, f = {}) {
  if (text === undefined || text === null || text === "") return "";
  const rPr = (f.style ? `<w:rStyle w:val="${f.style}"/>` : "")
    + (f.code ? '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>' : "")
    + (f.bold ? "<w:b/><w:bCs/>" : "") + (f.italic ? "<w:i/><w:iCs/>" : "") + (f.strike ? "<w:strike/>" : "")
    + (f.color ? `<w:color w:val="${f.color}"/>` : "") + (f.size ? `<w:sz w:val="${f.size}"/><w:szCs w:val="${f.size}"/>` : "")
    + (f.underline ? '<w:u w:val="single"/>' : "") + (f.code ? '<w:shd w:val="clear" w:color="auto" w:fill="F1EEE8"/>' : "");
  return String(text).split("\n").map((part, i) => `${i ? "<w:r><w:br/></w:r>" : ""}<w:r>${rPr ? `<w:rPr>${rPr}</w:rPr>` : ""}`
    + `<w:t xml:space="preserve">${xml(part)}</w:t></w:r>`).join("");
}

/** A paragraph of runs: o = {style, keep, rule (a line under it), left, hanging, align}. */
export function para(runs, o = {}) {
  const pPr = (o.style ? `<w:pStyle w:val="${o.style}"/>` : "") + (o.keep ? "<w:keepNext/>" : "")
    + (o.rule ? '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="C9C2B4"/></w:pBdr>' : "")
    + (RTL ? "<w:bidi/>" : "")
    + (o.left || o.hanging ? `<w:ind w:left="${o.left || 0}" w:hanging="${o.hanging || 0}"/>` : "")
    + (o.align ? `<w:jc w:val="${o.align}"/>` : "");
  return `<w:p>${pPr ? `<w:pPr>${pPr}</w:pPr>` : ""}${runs}</w:p>`;
}

// ------------------------------------------------------------------ the page's rendering, read as Word
const INLINE = new Set(["STRONG", "B", "EM", "I", "S", "DEL", "CODE", "A", "SPAN", "Q", "BR", "SUB", "SUP", "MARK", "SMALL", "#text"]);

/** The runs of an element's inline content. */
function inlineXML(node, f, doc) {
  let out = "";
  for (const n of node.childNodes) {
    if (n.nodeType === 3) {
      out += run(f.pre ? n.nodeValue : n.nodeValue.replace(/\s*\n\s*/g, " "), f);
      continue;
    }
    if (n.nodeType !== 1) continue;
    const tag = n.nodeName;
    if (n.classList.contains("cite")) {
      const pid = n.dataset.pid || "";
      doc.cite(pid, n.dataset.quote || undefined, n.textContent.trim());
      out += run(`〔${n.textContent.trim() || pid}〕`, { ...f, color: "9B2C1F", size: 18 });
    } else if (tag === "BUTTON" || tag === "svg" || n.classList.contains("caret") || n.classList.contains("spinner")) {
      continue;
    } else if (tag === "BR") out += "<w:r><w:br/></w:r>";
    else if (tag === "STRONG" || tag === "B") out += inlineXML(n, { ...f, bold: true }, doc);
    else if (tag === "EM" || tag === "I") out += inlineXML(n, { ...f, italic: true }, doc);
    else if (tag === "S" || tag === "DEL") out += inlineXML(n, { ...f, strike: true }, doc);
    else if (tag === "CODE") out += run(n.textContent, { ...f, code: true });
    else if (tag === "Q") out += run("「", f) + inlineXML(n, f, doc) + run("」", f); // the page draws the marks itself
    else if (tag === "A" && /^https?:\/\//i.test(n.getAttribute("href") || "")) {
      out += `<w:hyperlink r:id="${doc.link(n.getAttribute("href"))}" w:history="1">${inlineXML(n, { ...f, color: "0563C1", underline: true }, doc)}</w:hyperlink>`;
    } else out += inlineXML(n, f, doc);
  }
  return out;
}

/** The paragraphs, lists, tables and figures of a container, its loose inline content gathered into paragraphs. */
function blocksXML(parent, doc, o = {}) {
  let out = "";
  let loose = "";
  const flush = () => { if (loose.trim()) out += para(loose, o); loose = ""; };
  for (const n of parent.childNodes) {
    if (n.nodeType !== 1 && n.nodeType !== 3) continue;
    if (n.nodeType === 3 ? n.nodeValue.trim() : INLINE.has(n.nodeName) || n.classList.contains("cite")) {
      loose += inlineXML({ childNodes: [n] }, {}, doc);
      continue;
    }
    if (n.nodeType === 3) continue;
    flush();
    out += blockXML(n, doc, o);
  }
  flush();
  return out;
}

function blockXML(n, doc, o) {
  const tag = n.nodeName;
  const level = /^H([1-6])$/.exec(tag);
  if (level) return para(inlineXML(n, {}, doc), { style: `Heading${Math.min(3, Number(level[1]))}`, keep: true });
  if (tag === "P") return para(inlineXML(n, {}, doc), o);
  if (tag === "UL" || tag === "OL") return listXML(n, doc, 0, o);
  if (tag === "BLOCKQUOTE") return blocksXML(n, doc, { ...o, style: "Quote" });
  if (tag === "PRE") {
    const code = (n.querySelector("code") || n).textContent.replace(/\n$/, "");
    return code.split("\n").map((line) => para(run(line || " ", { pre: true }), { style: "Code" })).join("");
  }
  if (tag === "HR") return para("", { rule: true });
  if (n.classList.contains("md-table") || tag === "TABLE") {
    const table = tag === "TABLE" ? n : n.querySelector("table");
    if (!table) return "";
    const cap = n.querySelector?.(".tbl-cap")?.textContent || "";
    const note = n.querySelector?.(".tbl-note")?.textContent;
    const { spec } = specFromTable(table, cap, note ? [note] : []);
    return spec.columns.length ? doc.table(spec) : "";
  }
  if (n.matches?.("figure.viz-card.chart")) {
    const spec = specOf.get(n);
    return spec ? doc.figure(spec) : "";
  }
  if (n.classList.contains("md-table-tools") || n.classList.contains("chart-wait") || tag === "BUTTON" || tag === "svg") return "";
  if (n.classList.contains("viz-note")) return para(run(n.textContent, { size: 18, color: "6B645A" }), o);
  return blocksXML(n, doc, o);
}

/** A list, as indented paragraphs with their bullets or numbers (nested lists further in). */
function listXML(list, doc, depth, o) {
  let out = "";
  let k = Number(list.getAttribute("start")) || 1;
  const left = 420 * (depth + 1), hanging = 300;
  for (const li of list.children) {
    if (li.nodeName !== "LI") continue;
    const mark = list.nodeName === "OL" ? `${k++}.` : depth % 2 ? "◦" : "•";
    let own = "";
    let first = true;
    const flush = () => {
      if (!own.trim() && !first) return;
      out += para(run(first ? `${mark} ` : "", {}) + own, { ...o, left, hanging: first ? hanging : 0 });
      own = "";
      first = false;
    };
    for (const n of li.childNodes) {
      if (n.nodeType === 1 && (n.nodeName === "UL" || n.nodeName === "OL")) { flush(); out += listXML(n, doc, depth + 1, o); continue; }
      if (n.nodeType === 1 && n.nodeName === "P") { if (own.trim()) flush(); own += inlineXML(n, {}, doc); flush(); continue; }
      own += inlineXML({ childNodes: [n] }, {}, doc);
    }
    if (own.trim() || first) flush();
  }
  return out;
}

// ------------------------------------------------------------------ the document
const slug = (s, n = 40) => String(s || "").replace(/[\\/:*?"<>|\s#%&{}$!'`@+=]+/g, "-").replace(/^-+|-+$/g, "").slice(0, n) || "answer";
const stamp = (d) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}-`
  + `${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}`;

/** A PNG's size in pixels, from its header. */
function pngSize(bytes) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return { width: v.getUint32(16), height: v.getUint32(20) };
}

function drawing(rid, n, cx, cy, name) {
  return '<w:p><w:pPr><w:keepNext/>' + (RTL ? "<w:bidi/>" : "") + '<w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
    + `<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="${cx}" cy="${cy}"/><wp:docPr id="${n}" name="${xml(name)}"/>`
    + '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
    + '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
    + `<pic:nvPicPr><pic:cNvPr id="${n}" name="${xml(name)}"/><pic:cNvPicPr/></pic:nvPicPr>`
    + `<pic:blipFill><a:blip r:embed="${rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>`
    + `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>`
    + "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>";
}

const EAST_ASIA = {
  zh: ["宋体", "zh-CN"], "zh-Hant": ["新細明體", "zh-TW"], ja: ["MS Mincho", "ja-JP"], ko: ["Batang", "ko-KR"],
};

function stylesXML() {
  const [east, eastLang] = EAST_ASIA[LANG] || EAST_ASIA.zh; // the classics are quoted in Chinese whatever the page's language
  const heading = (id, name, size, outline) => `<w:style w:type="paragraph" w:styleId="${id}"><w:name w:val="${name}"/><w:basedOn w:val="Normal"/>`
    + `<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="${outline}"/></w:pPr>`
    + `<w:rPr><w:b/><w:bCs/><w:sz w:val="${size}"/><w:szCs w:val="${size}"/></w:rPr></w:style>`;
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    + '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr>'
    + `<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="${east}" w:cs="Arial"/><w:sz w:val="22"/><w:szCs w:val="22"/>`
    + `<w:lang w:val="${xml(LANGUAGE.locale.split("-u-")[0])}" w:eastAsia="${eastLang}" w:bidi="${RTL ? xml(LANGUAGE.locale) : "ar-SA"}"/></w:rPr></w:rPrDefault>`
    + '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
    + '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    + '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
    + '<w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val="34"/><w:szCs w:val="34"/></w:rPr></w:style>'
    + heading("Heading1", "heading 1", 30, 0) + heading("Heading2", "heading 2", 26, 1) + heading("Heading3", "heading 3", 23, 2)
    + '<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr>'
    + '<w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="C9C2B4"/></w:pBdr><w:ind w:left="300"/></w:pPr>'
    + '<w:rPr><w:color w:val="4C473F"/></w:rPr></w:style>'
    + '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr>'
    + '<w:shd w:val="clear" w:color="auto" w:fill="F3F0EA"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
    + '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>'
    + '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
    + '<w:pPr><w:spacing w:before="60" w:after="200"/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>'
    + '<w:style w:type="paragraph" w:styleId="Meta"><w:name w:val="Meta"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/></w:pPr>'
    + '<w:rPr><w:color w:val="6B645A"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>'
    + '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar><w:top w:w="0" w:type="dxa"/>'
    + '<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style></w:styles>';
}

/**
 * The export of one answer: {name, bytes} of the .zip.
 *
 * a = {question, answer (Markdown, as the visitor reads it), charts, tables (the specs the turn's tools made), documents
 * ({name, text}), cite(pid) → a passage's label, status(pid, quote) → {mark, label} of a quotation's check, or null,
 * meta (a line under the title: who answered, when), disclaimer, when (a Date)}.
 */
export async function answerArchive(a) {
  const when = a.when || new Date();
  const rels = []; // [{id, type, target, external}]
  const media = []; // [{name, data}]
  const figures = []; // [{spec, n}]
  const tables = []; // [{spec, n}]
  const cites = new Map(); // pid → {label, quotes: Set}
  const links = new Map();
  const doc = {
    link(href) {
      if (!links.has(href)) {
        const id = `rIdL${links.size + 1}`;
        links.set(href, id);
        rels.push({ id, type: `${REL}/hyperlink`, target: href, external: true });
      }
      return links.get(href);
    },
    cite(pid, quote, label) {
      if (!pid) return;
      const c = cites.get(pid) || { label: label || pid, quotes: new Set() };
      if (quote) c.quotes.add(quote);
      cites.set(pid, c);
    },
    figure(spec) {
      const n = figures.length + 1;
      figures.push({ spec, n });
      return `@@FIGURE:${n}@@`; // drawn once the figures are rasterised (that waits)
    },
    table(spec) {
      const n = tables.length + 1;
      tables.push({ spec, n });
      return `${tableXML(spec, n)}<w:p/>`;
    },
  };
  const md = (text) => renderMarkdown(text, { cite: (pid, quote) => h("span.cite", { dataset: { pid, quote: quote ?? "" } }, a.cite(pid)) });

  let body = para(run(String(a.question || "").split("\n")[0].slice(0, 120) || T("回答")), { style: "Title" });
  if (a.meta) body += para(run(a.meta), { style: "Meta" });
  if (a.question) body += para(run(T("问题")), { style: "Heading1", keep: true }) + blocksXML(md(a.question), doc);
  body += para(run(T("回答")), { style: "Heading1", keep: true }) + blocksXML(md(a.answer), doc);

  // what the turn's tools made: their figures and tables numbered on from the answer's own, their documents after
  const toolCharts = (a.charts || []).filter((s) => !invalid(s)).map((s) => normalize(s));
  if (toolCharts.length || (a.tables || []).length) {
    body += para(run(T("工具生成的图表")), { style: "Heading1", keep: true });
    for (const spec of toolCharts) body += doc.figure(spec);
    for (const spec of a.tables || []) body += doc.table(spec);
  }
  for (const d of a.documents || []) body += para(run(d.name), { style: "Heading1", keep: true }) + blocksXML(md(d.text), doc);

  if (cites.size) {
    body += para(run(T("引文与核对")), { style: "Heading1", keep: true });
    for (const [pid, c] of cites) {
      // each quotation's check, said once however many quotations it holds for
      const checks = [...new Set([...c.quotes].map((q) => a.status?.(pid, q)).filter(Boolean).map((s) => `${s.mark || ""} ${s.label || ""}`.trim()))];
      const said = checks.length ? `  ${checks.join("；")}` : "";
      body += para(run(c.label, { bold: true }) + run(`（${pid}）`, { color: "6B645A", size: 18 }) + run(said, { size: 18 }), { left: 300, hanging: 300 });
    }
  }
  if (a.disclaimer) body += para("", { rule: true }) + para(run(a.disclaimer), { style: "Meta" });

  // the figures: rasterised for the document, and kept beside it as PNG and SVG (with their caption)
  const files = [];
  for (const f of figures) {
    const title = f.spec.title || T("图表");
    const plain = figureSVG(f.spec, { style: "journal", caption: false, number: f.n, width: FIGURE });
    const png = new Uint8Array(await (await pngBlob(plain, PNG_SCALE)).arrayBuffer());
    const { width, height } = pngSize(png);
    const cx = Math.min(TEXT_EMU, Math.round(journalWidth(FIGURE)[0] * EMU_PER_MM)); // printed at the figure's own width
    const cy = Math.round((cx * height) / width);
    const rid = `rIdI${f.n}`;
    media.push({ name: `word/media/figure${f.n}.png`, data: png });
    rels.push({ id: rid, type: `${REL}/image`, target: `media/figure${f.n}.png` });
    const capText = T`图${f.n}` + "　" + title;
    const xmlOf = drawing(rid, f.n, cx, cy, capText)
      + para(run(capText), { style: "Caption" })
      + ([f.spec.subtitle, f.spec.note, f.spec.source].filter(Boolean).length
        ? para(run([f.spec.subtitle, f.spec.note, f.spec.source].filter(Boolean).join(" · ")), { style: "Meta", align: "center" }) : "");
    body = body.replace(`@@FIGURE:${f.n}@@`, () => xmlOf);
    const base = `figures/${slug(T`图${f.n}`, 8)}-${slug(title)}`;
    const captioned = figureSVG(f.spec, { style: "journal", caption: true, number: f.n, width: FIGURE });
    files.push({ name: `${base}.svg`, data: captioned });
    files.push({ name: `${base}.png`, data: new Uint8Array(await (await pngBlob(captioned, PNG_SCALE)).arrayBuffer()) });
  }
  for (const t of tables) files.push({ name: `tables/${slug(tableCaption(t.spec, t.n), 50)}.csv`, data: toCSV(t.spec) });
  for (const d of a.documents || []) files.push({ name: `documents/${slug(d.name.replace(/\.(md|markdown|txt)$/i, ""), 50)}.md`, data: d.text });

  const docXML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document ${NS}><w:body>${body}`
    + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>'
    + "</w:body></w:document>";
  const docRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + `<Relationship Id="rIdS" Type="${REL}/styles" Target="styles.xml"/>`
    + rels.map((r) => `<Relationship Id="${r.id}" Type="${r.type}" Target="${xml(r.target)}"${r.external ? ' TargetMode="External"' : ""}/>`).join("")
    + "</Relationships>";
  const docx = zip([
    { name: "[Content_Types].xml", data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
      + '<Default Extension="png" ContentType="image/png"/>'
      + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      + '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>' },
    { name: "_rels/.rels", data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + `<Relationship Id="rId1" Type="${REL}/officeDocument" Target="word/document.xml"/></Relationships>` },
    { name: "word/_rels/document.xml.rels", data: docRels },
    { name: "word/styles.xml", data: stylesXML() },
    { name: "word/document.xml", data: docXML },
    ...media,
  ], when);

  const base = `TaoChronos-${slug(a.question)}-${stamp(when)}`;
  const answerMd = `# ${String(a.question || "").split("\n")[0]}\n\n${a.meta ? `> ${a.meta}\n\n` : ""}${a.answer}\n`;
  return {
    name: `${base}.zip`,
    bytes: zip([{ name: `${base}.docx`, data: docx }, { name: `${base}.md`, data: answerMd }, ...files], when),
    counts: { figures: figures.length, tables: tables.length, citations: cites.size },
  };
}
