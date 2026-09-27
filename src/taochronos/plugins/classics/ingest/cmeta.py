"""數位中醫校書郎 CMETA (cmeta.lctseng.csie.org): rare editions transcribed and collated page by page against their images.

The site publishes its catalog (``library/catalog.json``), one Markdown text per edition (``library/texts/*.md``: the
text re-cut at the page boundaries of the images, ``<!-- Page N -->``) and the structure of each text
(``library/meta/<text>/volumes.json``, ``sections.json``, ``paratexts.json``: the 卷, 篇 and front matter of every edition,
each with the page it starts on and the words it starts with).  Only the editions the site opens to every visitor
are taken: those collated in full (精校) and not held back for its allow-list — its excavated bamboo and silk texts are
modern transcriptions under copyright, and texts still being collated (粗校, 待校) are shown to allow-listed users only.

Reading: every line of a page is a paragraph located at that page; a paragraph cut by a page break (the page ends
mid-sentence) is joined to the next page's first line and located at its first page, and a note the page break cut
(closed ``）`` and reopened ``（``) is made whole again; ``＝`` (the repetition mark, 重文號) is written out; in the lines
of a composition the doses and preparations, the print's small characters (桂枝（三兩去皮）), are written inline as in
the other transcriptions (they are not notes).  Formula names are not added where the print has none (宋本: 方一 …).  The 卷 and
篇 headings come from the structure files, placed where their first words are found on their page; front matter
(prefaces, colophons, the table of contents) is filed under 序跋 so that it is dated as paratext.  Where the site
shows an edition's page images to every visitor, each passage links the image of its page (``Locator.image_uri``).

Licence: the site's collation and editing are CC BY 4.0 (attribution: 數位中醫校書郎 CMETA); the texts of the
editions are in the public domain; the images follow their holders (國立故宮博物院 Open Data, Staatsbibliothek zu
Berlin Public Domain Mark 1.0, Wikimedia Commons public domain).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .documents import Block, Document

BASE = "https://cmeta.lctseng.csie.org/"
SOURCE = {
    "id": "cmeta",
    "name": "數位中醫校書郎 CMETA（中醫善本典籍協作校訂平台）",
    "url": BASE,
    "license": "CC BY 4.0（本站校訂與編輯成果，須標示「數位中醫校書郎 CMETA」）；底本文字屬公有領域；"
               "影像依各典藏機構（故宮 Open Data、柏林國家圖書館 PDM 1.0、Wikimedia Commons 公有領域）",
    "transcription": "CMETA 據善本影像逐頁精校（精校級）之純文字，按影像頁界重切；有新式標點",
    "acquisition": "HTTPS（library/catalog.json、texts/*.md、meta/*.json；僅取站方對所有訪客開放之精校本）",
    "edition_name": "CMETA 精校本",
}
# the site's rule (prototype/app.js): 精校 texts are open to every visitor, other levels to its allow-list only
OPEN_LEVEL = "精校"
# books whose page images the site shows to every visitor (GUEST_VISIBLE_IMAGE_BOOKS in prototype/app.js,
# read again at every fetch; this list is the fallback)
GUEST_IMAGES = {"shanghan_zhao_kaimei", "shanghan_npm", "nanjing_jizhu_keian", "kanhei_shanghan_vision_ocr",
                "suwen_gucongde", "lingshu_sibucongkan", "gujin_yian_an", "mingyi_leian"}
Log = Callable[[str], None]

_PAGE = re.compile(r"<!--\s*Page\s+(\d+)\s*-->")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SENTENCE_END = tuple("。！？」』")


def open_to_all(book: dict[str, Any]) -> bool:
    access = book.get("access") or {}
    if isinstance(access, str):  # the catalog as some tools print it
        access = {}
    return (book.get("textAccess") != "whitelist" and book.get("collationLevel") == OPEN_LEVEL
            and access.get("allowTextDisplay", True) is not False and bool(book.get("textUrl")))


# ------------------------------------------------------------------ fetching
def _get(url: str, dest: Path | None = None) -> bytes:
    args = ["curl", "-sS", "--fail", "-L", "-m", "120", "-A", "TaoChronos corpus fetch (research; contact via GitHub)", url]
    for attempt in range(4):
        p = subprocess.run(args, capture_output=True)
        if p.returncode == 0:
            if dest is not None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(p.stdout)
            return p.stdout
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"download failed: {url}: {p.stderr.decode('utf-8', 'replace')[-300:]}")


def _url(rel: str) -> str:
    return BASE + urllib.parse.quote(rel)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(root: Path, log: Log = print) -> dict[str, Any]:
    """Download the catalog, the open editions' texts and their structure files; returns facts for the lockfile."""
    root.mkdir(parents=True, exist_ok=True)
    catalog = _get(_url("library/catalog.json"), root / "catalog.json")
    books = json.loads(catalog)
    try:  # which books show their images to every visitor
        app = _get(_url("prototype/app.js")).decode("utf-8", "replace")
        m = re.search(r"GUEST_VISIBLE_IMAGE_BOOKS\s*=\s*new Set\(\[(.*?)\]\)", app, re.S)
        guest = sorted(set(re.findall(r"\"([^\"]+)\"", m.group(1)))) if m else sorted(GUEST_IMAGES)
    except RuntimeError:
        guest = sorted(GUEST_IMAGES)
    (root / "guest_images.json").write_text(json.dumps(guest, ensure_ascii=False), encoding="utf-8")
    texts: dict[str, Any] = {}
    metas: set[str] = set()
    for b in books:
        if not open_to_all(b):
            continue
        data = _get(_url("library/" + b["textUrl"]), root / "texts" / Path(b["textUrl"]).name)
        texts[b["id"]] = {"file": b["textUrl"], "bytes": len(data), "sha256": _sha256(data)}
        es = b.get("editionStructure") or {}
        if isinstance(es, dict) and es.get("metaDir"):
            metas.add(es["metaDir"])
        log(f"  {b['id']}: {len(data)} bytes")
        time.sleep(0.5)
    for meta in sorted(metas):
        for name in ("volumes.json", "sections.json", "paratexts.json"):
            try:
                _get(_url(f"library/{meta}/{name}"), root / meta / name)
            except RuntimeError:
                log(f"  {meta}/{name}: not published")
    return {"catalog": BASE + "library/catalog.json", "catalog_sha256": _sha256(catalog), "editions": len(texts),
            "texts": texts, "guest_images": guest, "fetched": time.strftime("%Y-%m-%d")}


# ------------------------------------------------------------------ reading
def _structure(root: Path, book: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(sections with their volume name, front/back paratexts) of this edition, in page order."""
    es = book.get("editionStructure") or {}
    if not isinstance(es, dict) or not es.get("metaDir"):
        return [], []

    def load(name: str, key: str) -> list[dict[str, Any]]:
        path = root / es["metaDir"] / name
        return list(json.loads(path.read_text(encoding="utf-8")).get(key, [])) if path.exists() else []

    edition = es.get("editionId")
    volumes = {v["id"]: v for v in load("volumes.json", "volumes") if v.get("edition") == edition}
    sections = [{**s, "volume": volumes[s["volumeId"]].get("name", "")} for s in load("sections.json", "sections")
                if s.get("volumeId") in volumes]
    paratexts = [p for p in load("paratexts.json", "paratexts") if p.get("edition") == edition]
    return sorted(sections, key=lambda s: (s["page"], s.get("id", ""))), sorted(paratexts, key=lambda p: (p["page"], p.get("sequence", 0)))


def _pages(md: str) -> list[tuple[int, list[str]]]:
    parts = _PAGE.split(md)
    out: list[tuple[int, list[str]]] = []
    for i in range(1, len(parts), 2):
        body = _COMMENT.sub("", parts[i + 1])
        out.append((int(parts[i]), [ln.rstrip() for ln in body.split("\n") if ln.strip(" 　\t")]))
    return out


def expand_repeats(line: str) -> str:
    """辟＝燥 → 辟辟燥: the repetition mark stands for the character before it."""
    return re.sub(r"(.)＝", lambda m: m.group(1) * 2 if m.group(1) not in "＝ 　" else m.group(0), line)


_COMPOSITION = re.compile(r"(?:[^（）。，；\s　]{1,10}（[^（）]{1,24}）[\s　]*)+")


def unbracket_doses(line: str) -> str:
    """桂枝（三兩去皮）　芍藥（三兩） → 桂枝三兩去皮　芍藥三兩: in a composition line the doses and preparations are the
    print's small characters, not notes — written inline, as the other transcriptions write them."""
    core = line.strip(" 　")
    if not _COMPOSITION.fullmatch(core):
        return line
    return re.sub(r"（([^（）]{1,24})）", r"\1", line)


def _key(s: str) -> str:
    return re.sub(r"[\s　，。、：；！？「」『』（）()〔〕【】．.]", "", s)


def _locate(pages: list[tuple[int, list[str]]], page: int, anchor: str, taken: set[tuple[int, int]]) -> tuple[int, int] | None:
    """(page, line) where a unit starts: its first words at the head of a line, on its page or a neighbour (the
    structure files and the page markers can differ by one); the anchor's second line when the first is not a line
    of its own (辨脉法第一 inside 辨脉法第一　平脉法第二)."""
    lines_of = {p: ls for p, ls in pages}
    for part in [x for x in anchor.split("\n") if _key(x)][:2]:
        first = _key(part)[:8]
        for p in sorted({page, page - 1, page + 1, page - 2, page + 2}, key=lambda x: (abs(x - page), x)):
            for idx, line in enumerate(lines_of.get(p, [])):
                if (p, idx) not in taken and _key(expand_repeats(line)).startswith(first):
                    return p, idx
    return None


def read_book(root: Path, book: dict[str, Any], guest: set[str]) -> Document:
    md = (root / "texts" / Path(book["textUrl"]).name).read_text(encoding="utf-8")
    sections, paratexts = _structure(root, book)
    pages = _pages(md)
    image_dir = str(book.get("imageDir") or "").replace("../", "")
    images = book["id"] in guest and bool(image_dir) and bool(book.get("imageCount"))
    pad = int(book.get("imagePad") or 6)
    ext = book.get("imageExt") or "jpg"
    # the units of the edition, in reading order: (page, kind, level, name, anchor)
    units: list[tuple[int, str, int, str, str]] = []
    for p in paratexts:
        units.append((int(p["page"]), "back" if p.get("kind") == "back" else "front", 2, p.get("name") or "", p.get("anchorText") or ""))
    last_volume = None
    for s in sections:
        if s["volume"] != last_volume:
            units.append((int(s["page"]), "volume", 1, s["volume"], s.get("anchorText") or ""))
            last_volume = s["volume"]
        units.append((int(s["page"]), "section", 2, s.get("displayName") or s.get("name") or "", s.get("anchorText") or ""))
    placed: dict[tuple[int, int], list[tuple[str, int, str]]] = {}
    taken: set[tuple[int, int]] = set()
    for page, kind, level, name, anchor in units:
        at = _locate(pages, page, anchor, set()) if anchor else None
        if at is None:  # not found: at the head of its page
            at = (page, 0)
        placed.setdefault(at, []).append((kind, level, name))
        taken.add(at)
    known = {_key(x) for x in [book.get("citationTitle") or "", *(s["volume"] for s in sections),
                                *(s.get("anchorText", "").split("\n")[0] for s in sections)] if _key(x)}
    first_section = min((p for (p, _), ms in placed.items() if any(k in ("volume", "section") for k, *_ in ms)), default=None)
    blocks: list[Block] = []
    open_para: Block | None = None
    in_front = False

    def emit(kind: str, level: int, name: str) -> None:
        nonlocal in_front
        if kind in ("front", "back"):
            if not in_front:
                blocks.append(Block("heading", "序跋" if kind == "front" else "跋", level=1))
                in_front = True
            blocks.append(Block("heading", name, level=2))
        else:
            if kind == "volume":
                in_front = False
            blocks.append(Block("heading", name, level=level))

    for page, lines in pages:
        image = f"{BASE}{urllib.parse.quote(image_dir)}/{page:0{pad}d}.{ext}" if images and page >= 1 else None
        if first_section is not None and page < first_section and not in_front and lines \
                and not any(k in ("front", "back") for k, *_ in placed.get((page, 0), [])):
            emit("front", 1, "卷首")  # front matter the structure files do not name (a title page, a table of contents)
        for idx, raw in enumerate(lines):
            for kind, level, name in placed.get((page, idx), []):
                emit(kind, level, name)
                open_para = None
            line = expand_repeats(raw.strip(" \t"))
            core = _key(line)
            if core and _only_headings(core, known):
                continue  # a line that only repeats headings (卷第一 · 辨脉法第一　平脉法第二): the headings stand for it
            if open_para is not None and idx == 0 and not line.startswith("　"):
                # a paragraph cut by the page break: join, rejoining a note the break cut
                text = open_para.text
                if text.endswith("）") and line.startswith("（"):
                    text, line = text[:-1], line[1:]
                open_para.text = text + line
                open_para = open_para if not open_para.text.endswith(_SENTENCE_END) else None
                continue
            block = Block("para", unbracket_doses(line) if line.startswith("　") else line, page=str(page), image=image)
            blocks.append(block)
            open_para = block if not line.endswith(_SENTENCE_END) else None
        for (p, idx), marks in sorted(placed.items()):  # units placed past the last line of their page
            if p == page and idx >= len(lines):
                for kind, level, name in marks:
                    emit(kind, level, name)
                    open_para = None
    title = str(book.get("title") or book.get("citationTitle") or book["id"])
    return Document(source="cmeta", code=book["id"], title=title, blocks=blocks,
                    meta={"notes": re.sub(r"\s+", " ", str(book.get("source") or ""))[:400]},
                    punctuation="editorial", url=f"{BASE}prototype/", ref=book["textUrl"], chartype="traditional",
                    extra={"images": images})


def _only_headings(core: str, known: set[str]) -> bool:
    """Is the line a run of known headings (傷寒論卷第一 = 傷寒論 + 卷第一; 辨脉法第一平脉法第二)?"""
    if len(core) > 40:
        return False
    ok = [False] * (len(core) + 1)
    ok[0] = True
    for i in range(len(core)):
        if ok[i]:
            for k in known:
                if core.startswith(k, i):
                    ok[i + len(k)] = True
    return ok[len(core)]


def read(root: Path) -> list[Document]:
    books = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    guest_path = root / "guest_images.json"
    guest = set(json.loads(guest_path.read_text(encoding="utf-8"))) if guest_path.exists() else set(GUEST_IMAGES)
    return [read_book(root, b, guest) for b in books if open_to_all(b) and (root / "texts" / Path(b["textUrl"]).name).exists()]


__all__ = ["BASE", "GUEST_IMAGES", "SOURCE", "expand_repeats", "fetch", "open_to_all", "read", "read_book", "unbracket_doses"]
