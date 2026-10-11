"""Table specifications (``tables.py``) as files a paper takes: Word, LaTeX, CSV, Markdown and HTML.

Every writer prints the three-line table (三线表) a journal prints: the title above with its number (表 1　…), a rule
above the column heads, a rule under them (and a short rule under each group head, as booktabs' ``\\cmidrule``), a rule
under the last row, no vertical lines; the notes below.  Statistical symbols are set in italics where the format has
italics (P, n, z, H, t, r, ρ, q, x̄, s — as journals set them).  The web client writes the same files from the same
specification (``web/js/table.js``).

* Word (.docx): a document of the tables, each a real Word table with its borders, its header row repeated on a new
  page, 宋体 and Times New Roman at 10.5 pt — written from the standard library (``zipfile``).
* LaTeX: ``booktabs`` (``\\toprule``, ``\\midrule``, ``\\cmidrule``, ``\\bottomrule``) in a ``table`` float with its
  ``\\caption`` and ``\\label``; Chinese needs ``ctex`` (XeLaTeX).
* CSV (UTF-8 with a byte-order mark, so that spreadsheet programs read the Chinese), Markdown and HTML (inline
  styles, so that it pastes into Word as a three-line table).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape

SYMBOL = re.compile(r"(?<![A-Za-z])(P|n|z|H|t|r|q|s|x̄|ρ)(?![A-Za-z\u0304])")


def runs(text: str) -> list[tuple[str, bool]]:
    """``text`` cut into (piece, italic): the statistical symbols italic."""
    out: list[tuple[str, bool]] = []
    at = 0
    for m in SYMBOL.finditer(text):
        if m.start() > at:
            out.append((text[at: m.start()], False))
        out.append((m.group(0), True))
        at = m.end()
    if at < len(text):
        out.append((text[at:], False))
    return out or [("", False)]


_FORMULA = re.compile(r"^[=+\-@\t\r]")
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def defuse(x: Any) -> str:
    """A cell a spreadsheet would read as a formula (=, +, -, @ … that is not a number) kept as text."""
    s = "" if x is None else str(x)
    return "'" + s if _FORMULA.match(s) and not _NUMBER.match(s) else s


def caption(spec: dict[str, Any], number: int | str | None = None) -> str:
    """表 1　title."""
    return f"表{number}　{spec.get('title', '')}" if number not in (None, "") else str(spec.get("title", ""))


def head_rows(spec: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """The column heads as rows of cells {label, span, rows, align, group}: one row, or two when columns have groups —
    a group's head over its columns, an ungrouped head spanning both rows."""
    cols = spec.get("columns", [])
    if not any(c.get("group") for c in cols):
        return [[{"label": c["label"], "span": 1, "rows": 1, "col": i} for i, c in enumerate(cols)]]
    top: list[dict[str, Any]] = []
    bottom: list[dict[str, Any]] = []
    i = 0
    while i < len(cols):
        g = cols[i].get("group")
        if not g:
            top.append({"label": cols[i]["label"], "span": 1, "rows": 2, "col": i})
            i += 1
            continue
        j = i
        while j + 1 < len(cols) and cols[j + 1].get("group") == g:
            j += 1
        top.append({"label": g, "span": j - i + 1, "rows": 1, "col": i, "group": True})
        bottom += [{"label": cols[k]["label"], "span": 1, "rows": 1, "col": k} for k in range(i, j + 1)]
        i = j + 1
    return [top, bottom]


def _cells(spec: dict[str, Any]) -> list[list[str]]:
    cols = spec.get("columns", [])
    return [[str(r.get(c["key"], "")) for c in cols] for r in spec.get("rows", [])]


def _flat_heads(spec: dict[str, Any]) -> list[str]:
    """One head per column: a grouped column's group and its own head ("折合克数（g）· M (P25, P75)")."""
    return [f"{c['group']} · {c['label']}" if c.get("group") else c["label"] for c in spec.get("columns", [])]


# ------------------------------------------------------------------ CSV, Markdown
def to_csv(spec: dict[str, Any], *, bom: bool = True) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([defuse(x) for x in _flat_heads(spec)])
    w.writerows([[defuse(x) for x in row] for row in _cells(spec)])
    return ("\ufeff" if bom else "") + buf.getvalue()


def to_markdown(spec: dict[str, Any], number: int | str | None = None) -> str:
    cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    aligns = {"left": ":---", "right": "---:", "center": ":---:"}
    cols = spec.get("columns", [])
    lines = [f"**{caption(spec, number)}**", "", "| " + " | ".join(cell(h) for h in _flat_heads(spec)) + " |",
             "| " + " | ".join(aligns.get(c.get("align", "left"), "---") for c in cols) + " |"]
    lines += ["| " + " | ".join(cell(x) for x in row) + " |" for row in _cells(spec)]
    for note in _notes(spec):
        lines += ["", note]
    return "\n".join(lines) + "\n"


def _notes(spec: dict[str, Any]) -> list[str]:
    notes = list(spec.get("notes") or [])
    out = [("注：" if i == 0 else "") + n for i, n in enumerate(notes)]
    if spec.get("source"):
        out.append(f"资料来源：{spec['source']}")
    return out


# ------------------------------------------------------------------ LaTeX (booktabs)
_TEX = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


_TEX_SYMBOL = {"x̄": r"$\bar{x}$", "ρ": r"$\rho$"}


def tex(text: str) -> str:
    """Text for LaTeX: its special characters escaped, the statistical symbols in italics (x̄ and ρ in math)."""
    out = []
    for piece, italic in runs(str(text)):
        esc = "".join(_TEX.get(ch, ch) for ch in piece)
        out.append(_TEX_SYMBOL.get(piece) or rf"\textit{{{esc}}}" if italic else esc)
    return "".join(out)


def to_latex(spec: dict[str, Any], number: int | str | None = None) -> str:
    cols = spec.get("columns", [])
    align = "".join({"left": "l", "right": "r", "center": "c"}.get(c.get("align", "left"), "l") for c in cols)
    lines = [f"% {caption(spec, number)} — 需 \\usepackage{{booktabs}}；中文用 ctex 宏包，以 XeLaTeX 编译",
             r"\begin{table}[htbp]", r"\centering", rf"\caption{{{tex(spec.get('title', ''))}}}",
             rf"\label{{tab:{re.sub(r'[^A-Za-z0-9-]', '-', str(spec.get('id') or 'table'))}}}",
             rf"\begin{{tabular}}{{{align}}}", r"\toprule"]
    heads = head_rows(spec)
    if len(heads) == 2:
        top = []
        rules = []
        for c in heads[0]:
            if c.get("group"):
                top.append(rf"\multicolumn{{{c['span']}}}{{c}}{{{tex(c['label'])}}}")
                rules.append(rf"\cmidrule(lr){{{c['col'] + 1}-{c['col'] + c['span']}}}")
            else:
                top.append(rf"\multirow{{2}}{{*}}{{{tex(c['label'])}}}")
        lines += [" & ".join(top) + r" \\", " ".join(rules)]
        bottom = {c["col"]: c for c in heads[1]}
        lines.append(" & ".join(tex(bottom[i]["label"]) if i in bottom else "" for i in range(len(cols))) + r" \\")
    else:
        lines.append(" & ".join(tex(c["label"]) for c in heads[0]) + r" \\")
    lines.append(r"\midrule")
    lines += [" & ".join(tex(x) for x in row) + r" \\" for row in _cells(spec)]
    lines += [r"\bottomrule", r"\end{tabular}"]
    notes = _notes(spec)
    if notes:
        lines += [r"\par\smallskip", r"\begin{minipage}{\linewidth}\footnotesize"] + [tex(n) + r"\par" for n in notes] + [r"\end{minipage}"]
    lines.append(r"\end{table}")
    if len(heads) == 2:
        lines[0] += r"；\multirow 需 \usepackage{multirow}"
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ HTML (inline styles: it pastes into Word as is)
def _html_text(text: str) -> str:
    return "".join(f"<i>{escape(p)}</i>" if it else escape(p) for p, it in runs(str(text)))


def to_html(spec: dict[str, Any], number: int | str | None = None, *, standalone: bool = False) -> str:
    rule = "1.5pt solid #000"
    thin = "0.75pt solid #000"
    cell = "padding:3pt 7pt;vertical-align:middle;"
    cols = spec.get("columns", [])
    heads = head_rows(spec)
    parts = [f'<p style="text-align:center;font-weight:bold;margin:12pt 0 4pt;font-size:10.5pt">{_html_text(caption(spec, number))}</p>',
             f'<table style="border-collapse:collapse;margin:0 auto;border-top:{rule};border-bottom:{rule};font-size:10.5pt;'
             f"font-family:'Times New Roman',SimSun,'Songti SC',serif\">", "<thead>"]
    for k, row in enumerate(heads):
        last = k == len(heads) - 1
        tr = []
        for c in row:
            border = thin if (last or c.get("rows", 1) == len(heads) - k) else (thin if c.get("group") else "none")
            attrs = (f' colspan="{c["span"]}"' if c["span"] > 1 else "") + (f' rowspan="{c["rows"]}"' if c.get("rows", 1) > 1 else "")
            tr.append(f'<th{attrs} style="{cell}text-align:center;font-weight:normal;border-bottom:{border}">{_html_text(c["label"])}</th>')
        parts.append("<tr>" + "".join(tr) + "</tr>")
    parts.append("</thead><tbody>")
    for row in _cells(spec):
        parts.append("<tr>" + "".join(f'<td style="{cell}text-align:{c.get("align", "left")}">{_html_text(x)}</td>'
                                      for c, x in zip(cols, row)) + "</tr>")
    parts.append("</tbody></table>")
    notes = _notes(spec)
    if notes:
        parts.append('<div style="font-size:9pt;margin:4pt 0 12pt">' + "".join(f"<p style=\"margin:0\">{_html_text(n)}</p>" for n in notes) + "</div>")
    body = "\n".join(parts)
    if not standalone:
        return body + "\n"
    title = escape(caption(spec, number))
    return (f'<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title></head>\n'
            f'<body style="background:#fff;color:#000;margin:24px">\n{body}\n</body></html>\n')


# ------------------------------------------------------------------ Word (.docx)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="xml" ContentType="application/xml"/>'
                  '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                  '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                  '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '</Relationships>')
_DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
             '</Relationships>')
_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
           '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体" w:cs="Times New Roman"/>'
           '<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault>'
           '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
           '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr>'
           '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/>'
           '<w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style></w:styles>')
TEXT_WIDTH = 9026  # twips: A4 with 2.54 cm margins


def _w_runs(text: str, *, bold: bool = False, size: int | None = None) -> str:
    out = []
    for piece, italic in runs(str(text)):
        props = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "")
        out.append(f"<w:r>{f'<w:rPr>{props}</w:rPr>' if props else ''}<w:t xml:space=\"preserve\">{escape(piece)}</w:t></w:r>")
    return "".join(out)


def _w_para(text: str, *, align: str = "left", bold: bool = False, size: int | None = None, before: int = 0, after: int = 0,
            keep: bool = False) -> str:
    jc = {"left": "left", "right": "right", "center": "center"}.get(align, "left")
    ppr = f'<w:pPr>{"<w:keepNext/>" if keep else ""}<w:spacing w:before="{before}" w:after="{after}"/><w:jc w:val="{jc}"/></w:pPr>'
    return f"<w:p>{ppr}{_w_runs(text, bold=bold, size=size)}</w:p>"


def _widths(spec: dict[str, Any]) -> list[int]:
    """Column widths in twips, by the longest text of each column (a CJK character as wide as two Latin ones)."""
    from .svg import text_width

    cols = spec.get("columns", [])
    longest = []
    for i, c in enumerate(cols):
        texts = [c["label"]] + [row[i] for row in _cells(spec)]
        longest.append(max(3.0, min(30.0, max(text_width(t.replace("→", "汉"), 1) for t in texts))))  # an arrow is as wide as a character
    total = sum(longest)
    scale = min(TEXT_WIDTH / total, 210.0) if total else 1.0  # 10.5 pt ≈ 210 twips a CJK character
    return [max(600, int(w * scale * 1.12) + 260) for w in longest]  # with room to spare, and the cell's margins


def _w_table(spec: dict[str, Any]) -> str:
    cols = spec.get("columns", [])
    widths = _widths(spec)
    heads = head_rows(spec)
    rule = 'w:val="single" w:sz="12" w:space="0" w:color="000000"'
    thin = 'w:val="single" w:sz="6" w:space="0" w:color="000000"'
    out = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:jc w:val="center"/>'
           f"<w:tblBorders><w:top {rule}/><w:left w:val=\"nil\"/><w:bottom {rule}/><w:right w:val=\"nil\"/>"
           '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders><w:tblLayout w:type="autofit"/>'
           '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>',
           "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"]
    covered: dict[int, dict[str, Any]] = {}  # in the second head row: the columns an ungrouped head spans down into
    for k, row in enumerate(heads):
        last = k == len(heads) - 1
        tcs = []
        cells = {c["col"]: c for c in row}
        col = 0
        while col < len(cols):
            c = cells.get(col)
            if c is None and col in covered:  # the continuation of a head that spans both rows
                tcs.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[col]}" w:type="dxa"/><w:vMerge/>'
                           f"<w:tcBorders><w:bottom {thin}/></w:tcBorders><w:vAlign w:val=\"center\"/></w:tcPr><w:p/></w:tc>")
                col += 1
                continue
            span = c["span"]
            width = sum(widths[col: col + span])
            border = thin if last or c.get("group") or c.get("rows", 1) == len(heads) else None
            props = (f'<w:tcW w:w="{width}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "")
                     + ('<w:vMerge w:val="restart"/>' if c.get("rows", 1) > 1 else "")
                     + (f"<w:tcBorders><w:bottom {border}/></w:tcBorders>" if border else "") + '<w:vAlign w:val="center"/>')
            tcs.append(f"<w:tc><w:tcPr>{props}</w:tcPr>{_w_para(c['label'], align='center')}</w:tc>")
            if c.get("rows", 1) > 1:
                covered[col] = c
            col += span
        out.append(f'<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>{"".join(tcs)}</w:tr>')
    for row in _cells(spec):
        tcs = [f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>{_w_para(x, align=c.get("align", "left"))}</w:tc>'
               for c, x, w in zip(cols, row, widths)]
        out.append(f'<w:tr><w:trPr><w:cantSplit/></w:trPr>{"".join(tcs)}</w:tr>')
    out.append("</w:tbl>")
    return "".join(out)


def document_xml(specs: list[dict[str, Any]], numbers: list[int | str] | None = None) -> str:
    numbers = numbers or list(range(1, len(specs) + 1))
    body = []
    for spec, number in zip(specs, numbers):
        body.append(_w_para(caption(spec, number), align="center", bold=True, before=240, after=80, keep=True))
        body.append(_w_table(spec))
        for line in _notes(spec):
            body.append(_w_para(line, size=18, before=40))
        body.append("<w:p/>")
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
            'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W}"><w:body>'
            + "".join(body) + sect + "</w:body></w:document>")


def to_docx(specs: list[dict[str, Any]] | dict[str, Any], numbers: list[int | str] | None = None) -> bytes:
    """A Word document of the tables (one or several), each numbered (表 1 …) with its notes."""
    specs = [specs] if isinstance(specs, dict) else list(specs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/document.xml", document_xml(specs, numbers))
    return buf.getvalue()


# ------------------------------------------------------------------ files
def write(tables: list[dict[str, Any]], out_dir: Any, stem: str) -> list[str]:
    """Each table as <stem>-<id>.csv, .tex and .md, and all of them in <stem>-tables.docx; the paths written."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, t in enumerate(tables, 1):
        name = f"{stem}-{t.get('id') or f'table{i}'}"
        for ext, text in (("csv", to_csv(t)), ("tex", to_latex(t, i)), ("md", to_markdown(t, i))):
            path = out / f"{name}.{ext}"
            path.write_text(text, encoding="utf-8")
            written.append(str(path))
    if tables:
        path = out / f"{stem}-tables.docx"
        path.write_bytes(to_docx(tables))
        written.append(str(path))
    return written


__all__ = ["caption", "document_xml", "head_rows", "runs", "tex", "to_csv", "to_docx", "to_html", "to_latex", "to_markdown", "write"]
