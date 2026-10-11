"""Small Office files built by hand for the tests of 我的资料: a workbook (.xlsx) and a Word document (.docx) as Excel
and Word write them — the parts a reader needs and nothing else (shared strings, inline strings, a number format for
dates; paragraphs and a table)."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape

CT = "http://schemas.openxmlformats.org/package/2006/content-types"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def xlsx(rows: list[list[Any]], *, date_columns: tuple[int, ...] = (), sheets: int = 1, date1904: bool = False,
         inline: bool = False) -> bytes:
    """A workbook whose first sheet holds ``rows`` (the first, the heads): strings shared (or inline), numbers as
    numbers, and the cells of ``date_columns`` as Excel's day numbers with a date format (style 1)."""
    shared: list[str] = []
    index: dict[str, int] = {}
    cells_xml = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_col(c)}{r}"
            if value is None or value == "":
                continue
            if r > 1 and c in date_columns:
                cells.append(f'<c r="{ref}" s="1"><v>{value}</v></c>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif inline:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
            else:
                k = index.setdefault(str(value), len(shared))
                if k == len(shared):
                    shared.append(str(value))
                cells.append(f'<c r="{ref}" t="s"><v>{k}</v></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}"><sheetData>{"".join(cells_xml)}</sheetData></worksheet>'
    strings = (f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{MAIN}" count="{len(shared)}" uniqueCount="{len(shared)}">'
               + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>")
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{MAIN}"><cellXfs count="2"><xf numFmtId="0"/>'
              '<xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>')
    names = "".join(f'<sheet name="Sheet{i}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1, sheets + 1))
    workbook = (f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{MAIN}" xmlns:r="{REL}">'
                + ('<workbookPr date1904="1"/>' if date1904 else "") + f"<sheets>{names}</sheets></workbook>")
    rels = "".join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, sheets + 1))
    wb_rels = (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG_REL}">{rels}'
               f'<Relationship Id="rS" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>'
               f'<Relationship Id="rY" Type="{REL}/styles" Target="styles.xml"/></Relationships>')
    types = (f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="{CT}">'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>')
    root_rels = (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG_REL}">'
                 f'<Relationship Id="r1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/sharedStrings.xml", strings)
        z.writestr("xl/styles.xml", styles)
        for i in range(1, sheets + 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet if i == 1 else
                       f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}"><sheetData/></worksheet>')
    return buf.getvalue()


def docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    """A Word document: the paragraphs, then a table (if given)."""
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{escape(c)}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>"
                       for row in table)
        body += f"<w:tbl>{rows}</w:tbl>"
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    types = (f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="{CT}">'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>')
    rels = (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG_REL}">'
            f'<Relationship Id="r1" Type="{REL}/officeDocument" Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()
