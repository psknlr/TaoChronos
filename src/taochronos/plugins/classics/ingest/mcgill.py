"""McGill University Library, *Gynaecology in Traditional Chinese Medicine* (public domain): page transcriptions
of Qing prints and one manuscript in the Rare Books and Special Collections.

One XML file per page (``xml-files/<work>_<volume>_<section>_<page>.xml``): a header (title, volume, author, the
edition's date, current page, first/previous/next page) and the page text, characters separated by spaces (for
the original search engine), with ``<sf>`` small characters (doses, interlinear notes — kept as （…）),
``<formula>`` prescriptions, ``<marginalia>`` and ``<cf>`` characters given as entities.  Pages are chained
through the ``next`` links; a paragraph running over a page break is joined and located at its first page.
The texts are unpunctuated (白文).
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterator

from .documents import Block, Document

SOURCE = {
    "id": "mcgill",
    "name": "McGill University Library · Gynaecology in Traditional Chinese Medicine（麦吉尔大学图书馆善本中医妇科文献）",
    "url": "https://github.com/mcgill-digital/gynaecology_in_chinese_medicine",
    "license": "Public Domain Mark 1.0（公有领域；使用时请注明 McGill University Library）",
    "transcription": "麦吉尔大学图书馆据馆藏清刻本与抄本逐页录文（2000年代），无标点",
    "acquisition": "git clone",
    "edition_name": "麦吉尔大学图书馆藏本",
}
WORKS = {  # file prefix → (code, title as printed)
    "Fu": ("fuqingzhu_nuke", "傅青主女科"),
    "jiyingkangmu": ("chongding_jiyin_gangmu", "重訂濟陰綱目"),
    "bao_sheng_sui_shi": ("baosheng_suishi", "保生碎事"),
    "Nukejiyao": ("nuke_jiyao", "女科輯要"),
    "zhencunmifang": ("zhencun_mifang", "珍存秘方"),
}


def _field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""


def _file(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip())


def _work_of(filename: str) -> str | None:
    for prefix in sorted(WORKS, key=len, reverse=True):
        if filename.startswith(prefix):
            return prefix
    return None


def _clean(s: str) -> str:
    s = re.sub(r"<cf>\s*(.*?)\s*</cf>", lambda m: html.unescape(m.group(1)).strip(), s, flags=re.S)
    s = re.sub(r"<sf>\s*(.*?)\s*</sf>", lambda m: "（" + m.group(1) + "）", s, flags=re.S)
    s = re.sub(r"<marginalia>\s*(.*?)\s*</marginalia>", lambda m: "（" + m.group(1) + "）", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("<?>", "〓")  # <?>: an unread character
    s = re.sub(r"<[^<>]{0,6}>|(?<=[\u3400-\u9fff（）])[A-Za-z?](?=[\u3400-\u9fff（）])", "", s)  # escaped marks, stray keys
    s = re.sub(r"[ \t\u00a0]+", "", s)  # characters were spaced out for the old search engine
    # the transcribers' marks: {妊} a variant glyph given in its standard form; 穴[允] a character to be read as
    # the bracketed one; [x] an illegible character
    s = re.sub(r"\{([^{}]{1,4})\}", r"\1", s)
    s = re.sub(r"\[x\]", "〓", s, flags=re.I)
    s = re.sub(r"([\u3400-\u9fff\U00020000-\U0002ffff〓])\[([^\[\]]{1,2})\]", r"\2", s)
    return re.sub(r"\[([^\[\]]{1,4})\]", r"\1", s)


def _page_blocks(xml: str, page: str) -> list[Block]:
    m = re.search(r"<text>(.*)</text>", xml, re.S)
    if not m:
        return []
    body = m.group(1)
    out: list[Block] = []
    pos = 0
    for f in re.finditer(r"<formula>(.*?)</formula>", body, re.S):
        out.extend(_lines(body[pos:f.start()], page))
        text = _clean(f.group(1)).replace("\n", "")
        if text:
            out.append(Block("formula", text, page=page))
        pos = f.end()
    out.extend(_lines(body[pos:], page))
    return out


def _lines(chunk: str, page: str) -> Iterator[Block]:
    for line in chunk.split("\n"):
        text = _clean(line)
        if text:
            yield Block("para", text, page=page)


def read(root: str | Path) -> list[Document]:
    root = Path(root)
    files = {p.name: p for p in (root / "xml-files").glob("*.xml")}
    docs: list[Document] = []
    for prefix, (code, title) in WORKS.items():
        names = sorted(n for n in files if _work_of(n) == prefix)
        if not names:
            continue
        headers = {n: files[n].read_text(encoding="utf-8", errors="replace") for n in names if not n.endswith(("_bad.xml",))}
        # follow the chains of pages (one per volume): a chain starts at a page no other page points to
        nxt = {n: _file(_field(x, "next")) for n, x in headers.items()}
        pointed = set(nxt.values())
        order: list[str] = []
        seen: set[str] = set()
        for head in sorted((n for n in headers if n not in pointed), key=_natural):
            cur = head
            while cur and cur in headers and cur not in seen:
                seen.add(cur)
                order.append(cur)
                cur = nxt.get(cur)
        order += sorted((n for n in headers if n not in seen), key=_natural)  # pages outside every chain
        blocks: list[Block] = []
        meta: dict[str, str] = {}
        volume = None
        for name in order:
            x = headers[name]
            meta.setdefault("作者", _field(x, "author"))
            meta.setdefault("版本年代", _field(x, "date"))
            vol = _field(x, "volume")
            if vol and vol != volume:
                blocks.append(Block("heading", vol.replace(" ", ""), level=1))
                volume = vol
            page = re.sub(r"\s+", " ", _field(x, "currentpage")).strip()
            page = f"{vol} {page}".strip() if vol else page
            for b in _page_blocks(x, page):
                prev = blocks[-1] if blocks else None
                # a page starts mid-paragraph unless the previous page ended a block
                if prev is not None and prev.kind == "para" and b.kind == "para" and not _starts_block(b.text) \
                        and prev.page != b.page and not _is_heading(prev.text):
                    prev.text += b.text
                    continue
                if b.kind == "para" and _is_heading(b.text):
                    blocks.append(Block("heading", b.text, level=3, page=b.page))
                else:
                    blocks.append(b)
        author = re.sub(r"[(（].*?[)）]|\s", "", meta.get("作者", ""))
        docs.append(Document(
            source=SOURCE["id"], code=code, title=title, blocks=blocks,
            meta={"作者": author, "版本": meta.get("版本年代", "")}, authors=[author] if author and author != "不詳" else [],
            punctuation="none", url=SOURCE["url"], ref=f"xml-files/{prefix}*", edition=meta.get("版本年代", ""),
        ))
    return docs


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _is_heading(text: str) -> bool:
    core = re.sub(r"（[^）]*）", "", text)
    return 1 <= len(core) <= 12 and not re.search(r"(方用|治|服|主之)$", core)


def _starts_block(text: str) -> bool:
    return bool(re.match(r"^(又方|一方|治|凡|論|婦人|女子|產後|產前|按)", text))


__all__ = ["SOURCE", "WORKS", "read"]
