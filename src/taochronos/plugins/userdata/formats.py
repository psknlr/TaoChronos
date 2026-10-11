"""A user's file as text or as a table — TXT and Markdown, Word (.docx), CSV and TSV, Excel (.xlsx), JSON.

Read with the standard library only (it runs in the browser too, in Pyodide): a text file in UTF-8, UTF-16 (with its
byte-order mark: Excel's "Unicode text") or GB18030 (a Chinese Windows file); a CSV's delimiter sniffed; a workbook's
first sheet with its shared strings, inline strings and dates (from the cells' number formats, in the 1900 or the 1904
date system); a Word document's paragraphs, its tables written row by row.  The old binary formats (.xls, .doc) and PDF
are refused with what to save them as.  Sizes are bounded: a file of at most ``MAX_BYTES``, a table of ``MAX_ROWS`` rows
and ``MAX_COLUMNS`` columns, a text of ``MAX_CHARS`` characters.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 200
MAX_CHARS = 2_000_000
TEXT = (".txt", ".text", ".md", ".markdown")
TABLE = (".csv", ".tsv", ".tab")
ACCEPTED = TEXT + TABLE + (".xlsx", ".xlsm", ".docx", ".json")
REFUSED = {".xls": "请在 Excel 中另存为 .xlsx 或 .csv", ".doc": "请在 Word 中另存为 .docx 或 .txt",
           ".pdf": "请先导出为 .txt 或 .docx（PDF 的文字须先提取）", ".wps": "请另存为 .docx", ".et": "请另存为 .xlsx"}


class Unreadable(ValueError):
    """A file that cannot be read as data: the message says why and what to do (shown to the user as it is)."""


@dataclass
class Parsed:
    kind: str  # "text" or "table"
    text: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def read(name: str, data: bytes) -> Parsed:
    """The file ``name`` (its extension decides how it is read) with these bytes, as text or as a table."""
    ext = PurePosixPath(name.lower()).suffix
    if len(data) > MAX_BYTES:
        raise Unreadable(f"文件过大（{len(data) / 1048576:.1f} MB）：单个文件至多 {MAX_BYTES // 1048576} MB")
    if not data.strip():
        raise Unreadable("文件是空的")
    if ext in REFUSED:
        raise Unreadable(f"不能直接读取 {ext} 文件：{REFUSED[ext]}")
    if ext == ".xlsx" or ext == ".xlsm":
        return _xlsx(data)
    if ext == ".docx":
        return _text(_docx(data))
    if ext == ".json":
        return _json(decode(data))
    if ext in TABLE:
        return _csv(decode(data), "\t" if ext in (".tsv", ".tab") else None)
    if ext in TEXT or not ext:
        return _text(decode(data))
    if data[:2] == b"PK":
        raise Unreadable(f"不认识的压缩格式（{ext}）：请上传 .xlsx、.docx、.csv 或 .txt")
    return _text(decode(data))


def decode(data: bytes) -> str:
    """Bytes as text: UTF-16 with a byte-order mark, UTF-8 (with or without one), else GB18030 (GBK, GB2312)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gb18030")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _text(text: str) -> Parsed:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    notes = []
    if len(text) > MAX_CHARS:
        text, notes = text[:MAX_CHARS], [f"文本过长，只读入前 {MAX_CHARS:,} 字"]
    if not text.strip():
        raise Unreadable("文件里没有文字")
    return Parsed("text", text=text, notes=notes)


def _table(header: list[Any], body: list[list[Any]], notes: list[str] | None = None) -> Parsed:
    """A table from its header row and rows: blank rows dropped, every row as long as the header, names made unique."""
    notes = list(notes or [])
    width = max([len(header)] + [len(r) for r in body[:2000]]) if header or body else 0
    if width == 0:
        raise Unreadable("表格是空的")
    if width > MAX_COLUMNS:
        notes.append(f"列数过多，只读入前 {MAX_COLUMNS} 列")
        width = MAX_COLUMNS
    cells = lambda r: [("" if v is None else str(v)).strip() for v in (list(r) + [""] * width)[:width]]  # noqa: E731
    columns, seen = [], set()
    for i, h in enumerate(cells(header)):
        h = re.sub(r"\s+", " ", h) or f"列{i + 1}"
        base, k = h, 2
        while h in seen:
            h, k = f"{base}_{k}", k + 1
        seen.add(h)
        columns.append(h)
    rows = [cells(r) for r in body if any(str(v).strip() for v in r if v is not None)]
    if len(rows) > MAX_ROWS:
        notes.append(f"行数过多，只读入前 {MAX_ROWS:,} 行")
        rows = rows[:MAX_ROWS]
    if not rows:
        raise Unreadable("表格只有表头，没有数据行")
    return Parsed("table", columns=columns, rows=rows, notes=notes)


def _csv(text: str, delimiter: str | None) -> Parsed:
    text = text.replace("\x00", "")
    if delimiter is None:
        sample = "\n".join(text.splitlines()[:50])
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|，").delimiter
        except csv.Error:
            counts = {d: sample.count(d) for d in (",", "\t", ";", "|", "，")}
            delimiter = max(counts, key=lambda d: counts[d]) if max(counts.values()) else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise Unreadable("表格是空的")
    return _table(rows[0], rows[1:])


def _json(text: str) -> Parsed:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Unreadable(f"JSON 格式不对（第 {exc.lineno} 行）") from None
    if isinstance(data, dict) and isinstance(data.get("rows"), list):  # {columns, rows}
        cols = [str(c.get("label") or c.get("key") if isinstance(c, dict) else c) for c in data.get("columns") or []]
        rows = data["rows"]
        if rows and isinstance(rows[0], dict):
            keys = [c.get("key") if isinstance(c, dict) else c for c in data.get("columns") or []] or list(rows[0])
            return _table(cols or [str(k) for k in keys], [[_flat(r.get(k)) for k in keys] for r in rows])
        return _table(cols, [[_flat(v) for v in r] if isinstance(r, list) else [_flat(r)] for r in rows])
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        return _text(data["text"])
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data[:100]):
        keys = list(dict.fromkeys(k for r in data[:2000] for k in r))
        return _table(keys, [[_flat(r.get(k)) for k in keys] for r in data if isinstance(r, dict)])
    if isinstance(data, list) and data and all(isinstance(r, list) for r in data[:100]):
        return _table([_flat(v) for v in data[0]], [[_flat(v) for v in r] for r in data[1:]])
    if isinstance(data, list) and all(isinstance(r, str) for r in data):
        return _text("\n\n".join(data))
    raise Unreadable("JSON 应为记录的数组（[{…}, …]）、{columns, rows} 或 {text}")


def _flat(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "、".join(_flat(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


# ------------------------------------------------------------------ Office Open XML
def _zip(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Unreadable("文件已损坏，或不是 Office 文档") from None


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > 60 * 1024 * 1024:  # a zip bomb: no part of a 10 MB document is this large
        raise Unreadable("文档展开后过大")
    return ET.fromstring(z.read(info))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx(data: bytes) -> str:
    z = _zip(data)
    root = _xml(z, "word/document.xml")
    if root is None:
        raise Unreadable("这不是 Word 文档（缺少 word/document.xml）")
    body = next((c for c in root if _local(c.tag) == "body"), root)
    out: list[str] = []

    def para(p: ET.Element) -> str:
        parts = []
        for node in p.iter():
            t = _local(node.tag)
            if t == "t" and node.text:
                parts.append(node.text)
            elif t == "tab":
                parts.append("\t")
            elif t in ("br", "cr"):
                parts.append("\n")
        return "".join(parts)

    for block in body:
        kind = _local(block.tag)
        if kind == "p":
            out.append(para(block))
        elif kind == "tbl":  # a table: each row a line, its cells apart by tabs
            for tr in (r for r in block if _local(r.tag) == "tr"):
                cells = [" ".join(para(p) for p in tc.iter() if _local(p.tag) == "p").strip() for tc in tr if _local(tc.tag) == "tc"]
                out.append("\t".join(cells))
            out.append("")
    return "\n".join(out)


_REF = re.compile(r"([A-Z]+)(\d+)")
DATE_FORMATS = set(range(14, 23)) | {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _xlsx(data: bytes) -> Parsed:
    z = _zip(data)
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        raise Unreadable("这不是 Excel 工作簿（缺少 xl/workbook.xml）")
    date1904 = any(_local(e.tag) == "workbookPr" and e.get("date1904") in ("1", "true") for e in wb.iter())
    sheets = [e for e in wb.iter() if _local(e.tag) == "sheet"]
    rels = _xml(z, "xl/_rels/workbook.xml.rels")
    target = "xl/worksheets/sheet1.xml"
    notes = []
    if sheets and rels is not None:
        rid = next((v for k, v in sheets[0].attrib.items() if k.endswith("}id")), None)
        rel = next((r for r in rels.iter() if _local(r.tag) == "Relationship" and r.get("Id") == rid), None)
        if rel is not None:
            path = rel.get("Target", "")
            target = path.lstrip("/") if path.startswith("/") else "xl/" + path
        if len(sheets) > 1:
            notes.append(f"工作簿有 {len(sheets)} 个工作表，只读入第一个「{sheets[0].get('name', '')}」")
    shared: list[str] = []
    sst = _xml(z, "xl/sharedStrings.xml")
    if sst is not None:
        for si in (e for e in sst if _local(e.tag) == "si"):
            shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    dates: set[int] = set()  # the cell styles that show a date
    styles = _xml(z, "xl/styles.xml")
    if styles is not None:
        custom = {int(f.get("numFmtId", 0)) for f in styles.iter() if _local(f.tag) == "numFmt"
                  and re.search(r"[ymd]", re.sub(r'"[^"]*"|\[[^\]]*\]', "", f.get("formatCode", "").lower()))}
        xfs = next((e for e in styles.iter() if _local(e.tag) == "cellXfs"), None)
        if xfs is not None:
            for i, xf in enumerate(x for x in xfs if _local(x.tag) == "xf"):
                fmt = int(xf.get("numFmtId", 0))
                if fmt in DATE_FORMATS or fmt in custom:
                    dates.add(i)
    sheet = _xml(z, target)
    if sheet is None:
        raise Unreadable("工作簿里没有工作表")
    epoch = dt.datetime(1904, 1, 1) if date1904 else dt.datetime(1899, 12, 30)
    grid: list[list[str]] = []
    for row in (e for e in sheet.iter() if _local(e.tag) == "row"):
        values: dict[int, str] = {}
        for c in (e for e in row if _local(e.tag) == "c"):
            m = _REF.match(c.get("r", ""))
            col = _col(m.group(1)) if m else len(values)
            if col >= MAX_COLUMNS:
                continue
            kind = c.get("t", "n")
            v = next((e.text for e in c if _local(e.tag) == "v"), None)
            if kind == "s" and v is not None:
                text = shared[int(v)] if v.isdigit() and int(v) < len(shared) else ""
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
            elif kind == "b":
                text = "TRUE" if v == "1" else "FALSE"
            elif v is None:
                text = ""
            elif kind == "n" and int(c.get("s", "0") or 0) in dates:
                try:
                    stamp = epoch + dt.timedelta(days=float(v))
                    text = stamp.date().isoformat() if stamp.time() == dt.time(0) else stamp.isoformat(sep=" ", timespec="minutes")
                except (ValueError, OverflowError):
                    text = v
            elif kind == "n":
                text = _number(v)
            else:
                text = v
            values[col] = text
        if values:
            grid.append([values.get(i, "") for i in range(max(values) + 1)])
        if len(grid) > MAX_ROWS + 1:
            break
    if not grid:
        raise Unreadable("工作表是空的")
    return _table(grid[0], grid[1:], notes)


def _number(v: str) -> str:
    """A number as Excel shows it: 3 rather than 3.0, 0.1 rather than 0.1000000000000001."""
    try:
        x = float(v)
    except ValueError:
        return v
    if x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.10g}"


__all__ = ["MAX_BYTES", "MAX_CHARS", "MAX_COLUMNS", "MAX_ROWS", "Parsed", "Unreadable", "decode", "read"]
