"""Readers for the plain-text collections of Chinese medical books on GitHub and Hugging Face.

* **TCM-Ancient-Books** (github.com/xiaopangxia/TCM-Ancient-Books): ~700 GB18030 text files in the layout of
  the 中医世家 website — a ``<篇名>`` title line, 书名 / 作者 / 朝代 / 年份 fields, then ``<目录>`` / ``<篇名>``
  section headings with ``内容：`` or ``属性：`` text hard-wrapped at about fifty characters.  Most are the 笈成
  transcriptions converted to simplified characters.
* **tcmoc** (github.com/lab99x/tcmoc): the same text files, and some books reworked into Markdown with a YAML
  front matter (title, author, era, date).
* **classical-tcm-canon** (huggingface.co/datasets/wangekxy/classical-tcm-canon): one Parquet file, one record per
  work (work family, title, author, dynasty, edition type, text); reading it needs ``pyarrow``.

The readers only parse; dating, admission and duplicate detection happen in :mod:`.documents`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .documents import Block, Document, chartype, strip_modern_paratext

TAB_SOURCE = {
    "id": "tcm-ancient-books", "name": "TCM-Ancient-Books（中医药古籍文本，GitHub xiaopangxia）",
    "url": "https://github.com/xiaopangxia/TCM-Ancient-Books",
    "license": "未声明授权（古籍原文属公有领域；多为笈成整理本的简体转换本，经“中医世家”网站流传）；仅供本地研究使用",
    "transcription": "网络流传的简体转换本（中医世家格式），未经校勘", "acquisition": "git clone", "edition_name": "网络简体本",
}
TCMOC_SOURCE = {
    "id": "tcmoc", "name": "中医开源医典 tcmoc（GitHub lab99x）", "url": "https://github.com/lab99x/tcmoc",
    "license": "未声明授权（据 TCM-Ancient-Books 整理，古籍原文属公有领域）；仅供本地研究使用",
    "transcription": "TCM-Ancient-Books 文本的整理与 Markdown 改写本", "acquisition": "git clone", "edition_name": "网络简体本",
}
HF_SOURCE = {
    "id": "hf-tcm-canon", "name": "Classical Chinese Medicine Canon（Hugging Face wangekxy/classical-tcm-canon）",
    "url": "https://huggingface.co/datasets/wangekxy/classical-tcm-canon",
    "license": "数据集卡片声明 license: other（proprietary-commercial），同时称所收为公有领域古籍的忠实录文；仅供本地研究使用，不再分发",
    "transcription": "网络文本与《中华医书集成》等整理本的抽取本（据数据集卡片）", "acquisition": "huggingface download",
    "edition_name": "数据集录文",
}

_META = re.compile(r"^(书名|書名|作者|朝代|年份|年代)[：:]\s*(.*?)\s*$")
_GARBAGE = re.compile(r"KT\s*|\\x")
_FINAL = "。！？」』：”）)；"


def _unwrap(lines: list[str]) -> list[str]:
    """Undo the fixed-width line wrapping: a line ends a paragraph when it ends a sentence and is clearly
    shorter than the wrapping width (or is the last line)."""
    stripped = [ln.rstrip() for ln in lines]
    widths = sorted(len(s) for s in stripped if s)
    width = widths[int(len(widths) * 0.9)] if widths else 0
    paras: list[str] = []
    cur = ""
    for s in stripped:
        if not s.strip():
            if cur:
                paras.append(cur)
                cur = ""
            continue
        cur += s.strip()
        if s.endswith(tuple(_FINAL)) and len(s) < width - 4:
            paras.append(cur)
            cur = ""
    if cur:
        paras.append(cur)
    return paras


_GENERIC_TITLES = {"正文", "目录", "目錄", "序", "前言", "卷一", "卷上"}


def _title_from_name(stem: str) -> str:
    """The title in a file name: 「048-思考中医」, or tcmoc's 「(6.2.3-02511.1).本草-….《本草纲目》(五十二卷).李时珍」."""
    m = re.search(r"《([^》]+)》", stem)
    if m:
        return m.group(1)
    return re.sub(r"^\d+[-.]", "", stem)


def read_tab_file(path: Path, source: str, code: str | None = None) -> Document:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gb18030", errors="replace")
    text = _GARBAGE.sub("", text.replace("\r", ""))
    lines = text.split("\n")
    meta: dict[str, str] = {}
    title = ""
    blocks: list[Block] = []
    body: list[str] = []

    def flush() -> None:
        for p in _unwrap(body):
            blocks.append(Block("para", p))
        body.clear()

    for ln in lines:
        s = ln.strip()
        if s.startswith("<篇名>"):
            flush()
            name = s[4:].strip()
            if not title:
                title = name
                continue
            blocks.append(Block("heading", name, level=2))
            continue
        if s.startswith("<目录>"):
            flush()
            rest = s[4:].strip()
            if rest:
                blocks.append(Block("heading", rest, level=1))
            continue
        m = _META.match(s)
        if m and not blocks and not body:
            key = {"書名": "书名"}.get(m.group(1), m.group(1))
            meta[key] = m.group(2)
            continue
        s2 = re.sub(r"^(内容|屬性|属性)[：:]", "", ln)
        body.append(s2)
    flush()
    if title in _GENERIC_TITLES:
        title = ""
    title = meta.get("书名") or title or _title_from_name(path.stem)
    authors = [a for a in re.split(r"[、，,；;]", meta.get("作者", "")) if a.strip()]
    blocks = strip_modern_paratext(blocks)
    return Document(source=source, code=code or path.stem, title=title, blocks=blocks, meta=meta, authors=authors,
                    ref=path.name, chartype=chartype("".join(b.text for b in blocks[:200])))


def read_tab(root: str | Path) -> list[Document]:
    root = Path(root)
    return [read_tab_file(p, TAB_SOURCE["id"]) for p in sorted(root.glob("*.txt"))]


def read_markdown_file(path: Path, source: str) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        text = text[m.end():]
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", p)
        if h and "\n" not in p:
            blocks.append(Block("heading", h.group(2).strip(), level=len(h.group(1))))
        else:
            blocks.append(Block("para", re.sub(r"\s*\n\s*", "", p)))
    title = str(meta.get("title") or "")
    if blocks and blocks[0].kind == "heading" and blocks[0].text == title:
        blocks = blocks[1:]
    blocks = strip_modern_paratext(blocks)
    date = str(meta.get("date") or "")
    fields = {"书名": title, "作者": str(meta.get("author") or ""), "朝代": str(meta.get("era") or ""),
              "年份": ("公元" + date.replace("~", "-") + "年") if re.match(r"^-?\d{1,4}(~-?\d{1,4})?$", date) else ""}
    return Document(source=source, code=path.stem, title=title or path.stem, blocks=blocks, meta=fields,
                    authors=[fields["作者"]] if fields["作者"] else [], ref=path.name,
                    chartype="simplified" if str(meta.get("chartype") or "") == "简体" else chartype(text[:4000]))


def read_tcmoc(root: str | Path) -> list[Document]:
    """``books/*.txt`` in the TCM-Ancient-Books layout; ``books/*.md`` either in that layout too (the name carrying a
    catalogue number, the category and 《title》) or Markdown with a YAML front matter."""
    root = Path(root) / "books"
    docs = [read_tab_file(p, TCMOC_SOURCE["id"]) for p in sorted(root.glob("*.txt"))]
    for p in sorted(root.glob("*.md")):
        head = p.read_text(encoding="utf-8", errors="replace")[:200].lstrip("\ufeff \n")
        docs.append(read_tab_file(p, TCMOC_SOURCE["id"]) if head.startswith("<篇名>") else read_markdown_file(p, TCMOC_SOURCE["id"]))
    return docs


def read_hf(path: str | Path) -> list[Document]:
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise RuntimeError("reading the Hugging Face Parquet file needs pyarrow: `pip install -e \".[parquet]\"`") from exc
    docs: list[Document] = []
    for r in pq.read_table(str(path)).to_pylist():
        text = r["text"].replace("\r", "")
        blocks: list[Block] = []
        for para in re.split(r"\n\s*\n|\n", text):
            p = re.sub(r"^(属性|屬性)[：:]", "", para.strip("　 \t"))
            if not p:
                continue
            if len(p) <= 16 and not re.search(r"[。，；？！]", p):
                blocks.append(Block("heading", p, level=2))
            else:
                blocks.append(Block("para", p))
        blocks = strip_modern_paratext(blocks)
        meta = {"书名": r.get("title") or "", "作者": r.get("author") or "", "朝代": r.get("dynasty") or "",
                "notes": f"{r.get('work_family', '')}；{r.get('edition_type', '')}；{r.get('rights_basis', '')}；{r.get('validation_status', '')}"}
        title = re.sub(r"(醫家類|医家类)$", "", r.get("title") or "") or r["id"]  # the Siku copies carry their class
        docs.append(Document(source=HF_SOURCE["id"], code=r["id"], title=title, blocks=blocks, meta=meta,
                             authors=[r["author"]] if r.get("author") else [], ref=r["id"],
                             chartype=chartype(text[:4000]), extra={"edition_type": r.get("edition_type")}))
    return docs


__all__ = ["HF_SOURCE", "TAB_SOURCE", "TCMOC_SOURCE", "read_hf", "read_markdown_file", "read_tab", "read_tab_file", "read_tcmoc"]
