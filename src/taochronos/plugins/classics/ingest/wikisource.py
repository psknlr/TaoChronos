"""维基文库 (zh.wikisource.org) from the Wikimedia dumps, without the API (which rate-limits shared addresses).

``fetch`` finds the members of the categories (中醫, and 醫書 for the medical books filed outside its tree) and
their subcategories in the ``linktarget`` and ``categorylinks`` tables, adds every subpage of each member work
(``本草綱目/序例上``) from the multistream index, and downloads only the bz2 streams that hold those pages (HTTP Range
requests on the multistream dump) — about 200 MB instead of the 7.9 GB dump.  The pages are kept as
``pages.jsonl`` (title, id, revision, wikitext); a new selection fetches only the pages not yet downloaded.

``read`` turns each work (main page + subpages, in the order the main page links them) into a document:
headers give title, author, dynasty and year; ``{{*|…}}`` and ``<small>`` notes become （…）; ``{{參|原|讀}}``
keeps the original graph; ``{{?}}`` / ``{{PUA}}`` become 〓; tables of contents made of links are dropped.
Texts are CC BY-SA 4.0 (the originals are in the public domain); each book records its page and revision.
"""

from __future__ import annotations

import bisect
import bz2
import gzip
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Iterator

from .documents import Block, Document, chartype, strip_modern_paratext

SOURCE = {
    "id": "wikisource", "name": "维基文库（zh.wikisource.org）· Category:中醫、Category:醫書",
    "url": "https://zh.wikisource.org/wiki/Category:中醫",
    "license": "CC BY-SA 4.0（维基文库录文与标点；古籍原文属公有领域）",
    "transcription": "维基文库志愿者录入与标点，部分页面为网络本批量导入（简体），未经本项目校勘",
    "acquisition": "Wikimedia dump (multistream, range requests)", "edition_name": "维基文库本",
}
DUMPS = "https://dumps.wikimedia.org/zhwikisource/latest/"
# Category:中醫 and its tree; Category:醫書 files a few medical books (醫方類聚, 鄕藥集成方 …) outside it
CATEGORIES = ("中醫", "醫書")
_NS_SKIP = ("Author:", "Index:", "Template:", "Category:", "Page:", "Wikisource:", "File:", "Help:", "Portal:", "Module:",
            "Translation:", "Transwiki:", "MediaWiki:", "Special:")
Log = Callable[[str], None]


# ------------------------------------------------------------------ fetching from the dumps
def _download(name: str, dest: Path, log: Log) -> Path:
    path = dest / name
    if not path.exists():
        for attempt in range(4):
            p = subprocess.run(["curl", "-sS", "--fail", "-C", "-", "-o", str(path), DUMPS + name], capture_output=True, text=True)
            if p.returncode == 0:
                break
            time.sleep(2 ** (attempt + 1))
        else:
            raise RuntimeError(f"download failed: {name}: {p.stderr[-300:]}")
        log(f"  downloaded {name} ({path.stat().st_size} bytes)")
    return path


def _unesc(b: bytes) -> str:
    return re.sub(rb"\\(.)", rb"\1", b).decode("utf-8", "replace")


def category_members(dump: Path, category: str | tuple[str, ...] | list[str], log: Log = print
                     ) -> tuple[list[tuple[str, int, int]], dict[str, list[str]]]:
    """(title, page id, stream offset) of the pages in the categories and their subcategories; the subcategory tree."""
    categories = [category] if isinstance(category, str) else list(category)
    lt_re = re.compile(rb"\((\d+),(-?\d+),'((?:[^'\\]|\\.)*)'\)")
    cats: dict[int, str] = {}
    with gzip.open(dump / "zhwikisource-latest-linktarget.sql.gz", "rb") as f:
        for line in f:
            if line.startswith(b"INSERT"):
                for m in lt_re.finditer(line):
                    if m.group(2) == b"14":
                        cats[int(m.group(1))] = _unesc(m.group(3))
    by_title = {v: k for k, v in cats.items()}
    cl_re = re.compile(rb"\((\d+),'(?:[^'\\]|\\.)*','[^']*','(?:[^'\\]|\\.)*','(page|subcat|file)',\d+,(\d+)\)")
    subcats: dict[int, list[int]] = {}
    pages_of: dict[int, list[int]] = {}
    with gzip.open(dump / "zhwikisource-latest-categorylinks.sql.gz", "rb") as f:
        for line in f:
            if line.startswith(b"INSERT"):
                for m in cl_re.finditer(line):
                    frm, typ, tgt = int(m.group(1)), m.group(2), int(m.group(3))
                    (subcats if typ == b"subcat" else pages_of).setdefault(tgt, []).append(frm)
    index = read_index(dump)
    roots = [by_title[c] for c in categories if c in by_title]
    seen, queue, tree = set(roots), list(roots), {}
    while queue:
        t = queue.pop()
        for child in subcats.get(t, []):
            title = index.get(child, (0, ""))[1]
            name = title.split(":", 1)[1] if ":" in title else title
            tree.setdefault(cats[t], []).append(name)
            lt = by_title.get(name)
            if lt and lt not in seen:
                seen.add(lt)
                queue.append(lt)
    members = sorted({(index[p][1], p, index[p][0]) for t in seen for p in pages_of.get(t, []) if p in index})
    log(f"  {'、'.join(categories)}: {len(seen)} categories, {len(members)} member pages")
    return members, tree


def read_index(dump: Path) -> dict[int, tuple[int, str]]:
    out: dict[int, tuple[int, str]] = {}
    with bz2.open(dump / "zhwikisource-latest-pages-articles-multistream-index.txt.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            off, pid, title = line.rstrip("\n").split(":", 2)
            out[int(pid)] = (int(off), title)
    return out


_DUMP_TABLES = ("zhwikisource-latest-pages-articles-multistream-index.txt.bz2", "zhwikisource-latest-linktarget.sql.gz",
                "zhwikisource-latest-categorylinks.sql.gz")


def _dump_meta(dump: Path) -> dict[str, Any]:
    """Size and Last-Modified of the dump files used (the dated dump they come from)."""
    out: dict[str, Any] = {}
    for name in (*_DUMP_TABLES, "zhwikisource-latest-pages-articles-multistream.xml.bz2"):
        p = subprocess.run(["curl", "-sSI", "--fail", DUMPS + name], capture_output=True, text=True)
        head = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in p.stdout.splitlines() if ":" in l)}
        out[name] = {"bytes": int(head["content-length"]) if head.get("content-length", "").isdigit() else None,
                     "last_modified": head.get("last-modified")}
    return out


def _selected(dest: Path) -> list[str] | None:
    path = dest / "members.json"
    if not path.exists() or not (dest / "pages.jsonl").exists():
        return None
    info = json.loads(path.read_text(encoding="utf-8"))
    return list(info.get("categories") or [info["category"]])


def fetch(dest: str | Path, categories: str | tuple[str, ...] | list[str] = CATEGORIES, log: Log = print,
          refresh: bool = False) -> dict[str, Any]:
    """Download the dump tables, select the categories' works and their subpages, fetch their streams and write
    ``pages.jsonl`` and ``members.json``; returns facts for the lockfile.  An existing download is kept unless
    ``refresh``; a new selection of categories fetches only the pages not downloaded yet (from the same dump)."""
    dest = Path(dest)
    dump = dest / "dump"
    cats = [categories] if isinstance(categories, str) else list(categories)
    if refresh or _selected(dest) != cats:
        dump.mkdir(parents=True, exist_ok=True)
        kept: dict[int, dict[str, Any]] = {}
        if not refresh and (dest / "pages.jsonl").exists():
            recorded = (json.loads((dest / "members.json").read_text(encoding="utf-8")).get("dump") or {}).get(
                "zhwikisource-latest-pages-articles-multistream.xml.bz2", {}).get("last_modified")
            current = _dump_meta(dump)["zhwikisource-latest-pages-articles-multistream.xml.bz2"]["last_modified"]
            if recorded and current != recorded:
                raise SystemExit(f"the Wikisource dump changed ({recorded} → {current}): the stream offsets of the local index "
                                 "no longer hold; fetch again from the new dump (refresh)")
            with open(dest / "pages.jsonl", encoding="utf-8") as f:
                kept = {pg["id"]: pg for pg in map(json.loads, f)}
        for name in _DUMP_TABLES:
            if refresh and (dump / name).exists():
                (dump / name).unlink()
            _download(name, dump, log)
        members, tree = category_members(dump, cats, log)
        index = read_index(dump)
        works = {t for t, _, _ in members if not t.startswith(_NS_SKIP)}
        wanted: dict[int, str] = {p: t for t, p, _ in members if t in works}
        for pid, (off, title) in index.items():
            parts = title.split("/")
            for i in range(len(parts) - 1, 0, -1):
                if "/".join(parts[:i]) in works:
                    wanted[pid] = title
                    break
        offsets = sorted({off for off, _ in index.values()})
        pages: dict[int, dict[str, Any]] = {p: kept[p] for p in wanted if p in kept}
        need = sorted({index[p][0] for p in wanted if p not in pages})
        url = DUMPS + "zhwikisource-latest-pages-articles-multistream.xml.bz2"
        fetched = 0
        for off in need:
            i = bisect.bisect_right(offsets, off)
            end = str(offsets[i] - 1) if i < len(offsets) else ""
            for attempt in range(4):
                p = subprocess.run(["curl", "-sS", "--fail", "-r", f"{off}-{end}", url], capture_output=True)
                if p.returncode == 0 and p.stdout:
                    break
                time.sleep(2 ** (attempt + 1))
            else:
                raise RuntimeError(f"stream at {off} could not be fetched")
            fetched += len(p.stdout)
            for page in _pages(bz2.decompress(p.stdout).decode("utf-8")):
                if page["id"] in wanted:
                    pages[page["id"]] = page
        with open(dest / "pages.jsonl", "w", encoding="utf-8") as f:
            for pid in sorted(pages):
                f.write(json.dumps(pages[pid], ensure_ascii=False) + "\n")
        with open(dest / "members.json", "w", encoding="utf-8") as f:
            json.dump({"category": cats[0], "categories": cats, "tree": tree, "works": sorted(works), "streams": len(need),
                       "stream_bytes": fetched, **({"dump": _dump_meta(dump)} if not refresh and kept else {})},
                      f, ensure_ascii=False, indent=1)
        log(f"  {len(pages)} pages ({len(kept)} kept, {len(need)} streams fetched, {fetched} bytes)")
    info = json.loads((dest / "members.json").read_text(encoding="utf-8"))
    if "dump" not in info:
        info["dump"] = _dump_meta(dump)
        (dest / "members.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    n, latest = 0, ""
    with open(dest / "pages.jsonl", encoding="utf-8") as f:
        for line in f:
            n += 1
            ts = json.loads(line).get("ts") or ""
            latest = max(latest, ts)
    return {"category": info["category"], "categories": info.get("categories") or [info["category"]],
            "subcategories": info.get("tree", {}), "works": len(info["works"]), "pages": n,
            "latest_revision": latest or None, "dump": info["dump"]}


def _pages(xml: str) -> Iterator[dict[str, Any]]:
    for m in re.finditer(r"<page>.*?</page>", xml, re.S):
        e = ET.fromstring(m.group(0))
        rev = e.find("revision")
        red = e.find("redirect")
        yield {"title": e.findtext("title"), "ns": e.findtext("ns"), "id": int(e.findtext("id")), "rev": rev.findtext("id"),
               "ts": rev.findtext("timestamp"), "redirect": red.get("title") if red is not None else None,
               "text": rev.findtext("text") or ""}


# ------------------------------------------------------------------ wikitext → blocks
_DROP = {"header", "header2", "footer", "textquality", "醫療", "医疗", "未校訂", "未校订", "pd-old", "missing image", "novel", "novel-f",
         "檢索", "检索", "wikipedia", "传统汉字", "傳統漢字", "split", "未排版", "zth", "参见", "參見", "wwc", "wjd", "s2t", "width",
         "image label small", "css image crop", "templatestyles", "正體化", "正体化", "gap", "中醫", "醫書", "東漢度量衡", "東漢度量衡",
         "vtext2start", "vtext2end", "檢查", "clear", "vpad", "dotted toc page listing", "sic", "image label begin",
         "image label end", "image label", "image label small", "annotated image"}
_NOTE = {"*", "小字", "注", "註", "small", "sub", "夾注", "夹注", "批", "眉批"}
_FIRST = {"參", "参", "!", "另", "quote", "yl", "cbox", "專", "专", "color", "**", "+", "dl", "big", "larger", "ruby", "lang", "nowrap",
          "center", "c", "r", "l", "underline", "u", "del", "ins", "國", "國名", "書名"}
_UNKNOWN_CHAR = {"?", "？", "pua"}


def _split_args(inner: str) -> list[str]:
    """Split a template call on the pipes that are not inside a link."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(inner):
        two = inner[i:i + 2]
        if two == "[[":
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two == "]]" and depth:
            depth -= 1
            cur.append(two)
            i += 2
            continue
        if inner[i] == "|" and not depth:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(inner[i])
        i += 1
    parts.append("".join(cur))
    return parts


def _template(inner: str) -> str:
    parts = _split_args(inner)
    name = parts[0].strip()
    lname = name.lower()
    args = [a for a in parts[1:] if "=" not in a.split("|")[0][:12] or re.match(r"^\s*\d+\s*=", a)]
    args = [re.sub(r"^\s*\d+\s*=", "", a) for a in args]
    if lname.endswith("作品") or lname in _DROP or name.endswith("注") and not args:
        return ""
    if lname in _UNKNOWN_CHAR:
        return "〓" if not args or not args[0].strip() or lname != "pua" else args[0].strip()
    if lname == "*s":
        return "（"
    if lname == "*e":
        return "）"
    if lname in _NOTE:
        return "（" + args[0].strip() + "）" if args and args[0].strip() else ""
    if lname in _FIRST:
        if lname == "color" and len(args) > 1:
            return args[1]
        return args[0] if args else ""
    return ""


def _conversion(body: str) -> str:
    """-{…}- language-conversion markup: T|/H| rules are dropped; A|/R| show their text; variants keep the
    traditional form."""
    m = re.match(r"^\s*([A-Za-z])\s*\|(.*)$", body, re.S)
    if m:
        if m.group(1).upper() in ("T", "H", "-"):
            return ""
        body = m.group(2)
    if re.search(r"zh-(hant|hans|tw|hk|cn|mo|sg)\s*:", body):
        pairs = dict((k.strip(), v) for k, v in re.findall(r"(zh-[a-z]+)\s*:\s*([^;]*)", body))
        for k in ("zh-hant", "zh-tw", "zh-hk", "zh-mo", "zh-hans", "zh-cn"):
            if k in pairs:
                return pairs[k].strip()
    return body


def _expand_templates(text: str) -> str:
    # innermost first: {{...}} without braces inside
    pattern = re.compile(r"\{\{([^{}]*)\}\}")
    for _ in range(12):
        new = pattern.sub(lambda m: _template(m.group(1)), text)
        if new == text:
            break
        text = new
    return re.sub(r"\{\{|\}\}", "", text)


def _links(text: str) -> str:
    # innermost first: a file link may carry a caption with links of its own
    inner = re.compile(r"\[\[([^\[\]]*)\]\]")

    def link(m: re.Match) -> str:
        body = m.group(1)
        if re.match(r"\s*:?\s*(Category|分類|分类|File|Image|文件|圖像|图像|Media|Index|Author|作者)\s*:", body, re.I):
            return ""
        if "|" in body:
            return body.rsplit("|", 1)[1]
        return body.split("#")[0].split("/")[-1].split(":")[-1]

    for _ in range(4):
        new = inner.sub(link, text)
        if new == text:
            break
        text = new
    text = re.sub(r"\[(?:https?|ftp)://\S+\s*([^\]]*)\]", r"\1", text)
    return re.sub(r"\[\[(?:[^\]|]*:)?|\]\]", "", text)  # a link left unclosed


def wikitext_blocks(text: str, page: str | None = None, level_offset: int = 1) -> list[Block]:
    t = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    t = re.sub(r"\\x|KT(?=\s)", "", t)  # debris of the 中医世家 text files pasted into some pages
    t = re.sub(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>|<references\s*/?>", "", t, flags=re.S)
    t = re.sub(r"-\{(.*?)\}-", lambda m: _conversion(m.group(1)), t, flags=re.S)
    t = re.sub(r"<sup[^>]*>.*?</sup>", "", t, flags=re.S)
    for _ in range(4):  # innermost first
        new = re.sub(r"<(small|sub)[^>]*>((?:(?!<(?:small|sub)[\s>]).)*?)</\1>", r"（\2）", t, flags=re.S | re.I)
        if new == t:
            break
        t = new
    t = re.sub(r"\{\{\{[^{}|]*(?:\|([^{}]*))?\}\}\}", lambda m: m.group(1) or "", t)  # {{{width|400}}}: parameter defaults
    t = re.sub(r"\{\}", "", t)
    t = _expand_templates(t)
    t = _links(t)
    t = re.sub(r"<br\s*/?>|</?(p|div|center|blockquote|poem|pre)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"</?(span|font|big|u|b|i|strong|em|nowiki|onlyinclude|noinclude|includeonly|td|tr|th|table|tbody|h\d)[^>]*>", "", t, flags=re.I)
    t = re.sub(r"<pages[^>]*/?>", "", t)
    t = re.sub(r"'''?", "", t)
    blocks: list[Block] = []
    para: list[str] = []

    def flush() -> None:
        s = "".join(x.strip() for x in para).strip("　 ")
        para.clear()
        if s:
            blocks.append(Block("para", s, page=page))

    for line in t.split("\n"):
        s = line.strip()
        if not s or re.fullmatch(r"-{4,}", s):  # blank line, horizontal rule
            flush()
            continue
        # pages pasted from the 中医世家 text files: <篇名> / <目录> headings, 书名： … metadata, 内容： prefixes
        tab = re.match(r"^<(篇名|目录|目錄)>\s*(.*)$", s)
        if tab:
            flush()
            if tab.group(2):
                blocks.append(Block("heading", tab.group(2), level=level_offset + (1 if tab.group(1) == "篇名" else 0), page=page))
            continue
        if re.match(r"^(书名|書名|作者|朝代|年份)[：:]", s):
            continue
        s = re.sub(r"^(内容|內容|属性|屬性)[：:]", "", s)
        h = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", s)
        if h:
            flush()
            if h.group(2):
                blocks.append(Block("heading", h.group(2), level=len(h.group(1)) - 1 + level_offset, page=page))
            continue
        if re.match(r"^(\{\||\|\}|\|-)", s):
            flush()
            continue
        cell = s[:1] in ("|", "!")
        s = re.sub(r"^[*#:;!|]+\s*", "", s)
        s = re.sub(r"^=+\s*|\s*=+$", "", s)  # a heading mark left unbalanced
        if cell:  # table cells: drop their attributes (width="200" style="…"|text)
            s = "　".join(re.sub(r"^(?:\s*[\w-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s|]+))+\s*\|", "", c)
                         for c in re.split(r"\s*\|\|\s*|\s*!!\s*", s))
        s = re.sub(r"\s*\|\|\s*|\s*!!\s*", "　", s)
        if re.match(r"^(（[^）]*）\s*)+$", s) and len(s) < 3:
            continue
        para.append(s)
        if re.search(r"[。！？」』）]$", s):
            flush()
    flush()
    return blocks


def _balanced(text: str, start: int) -> int:
    """End of the template opening at ``start`` (the index after its closing braces)."""
    depth, i = 0, start
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    return len(text)


def _header(text: str) -> dict[str, str]:
    m = re.search(r"\{\{\s*(?:[Hh]eader2?|[Cc]ollection header)\s*\|", text)
    out: dict[str, str] = {}
    if not m:
        return out
    body = text[m.end():_balanced(text, m.start()) - 2]
    body = _expand_templates(body)
    for part in re.split(r"\n\s*\||\|(?=\s*[\w年]+\s*=)", body):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            if k == "section":  # 草之十<br>[[…|雜草]]: the section's own name comes first
                v = re.split(r"<br\s*/?>", v)[0]
            out[k] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|'''?", " ", _links(v))).strip()
    return out


# a line of the main page's table of contents: list items, or lines made of links to the subpages only
_TOC_LINE = re.compile(r"^\s*([*#]+.*|:*(\s*\[\[[^\]]+\]\][\s　、，,·|（）()]*)+)$")


def _natural(title: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", title)]


def read(dest: str | Path) -> list[Document]:
    dest = Path(dest)
    pages = [json.loads(l) for l in open(dest / "pages.jsonl", encoding="utf-8")]
    members = set(json.load(open(dest / "members.json", encoding="utf-8"))["works"])
    # a member that is a subpage of another member (肘後備急方/卷1) belongs to that work
    works = {w for w in members if not any("/".join(w.split("/")[:i]) in members for i in range(1, w.count("/") + 1))}
    by_title = {p["title"]: p for p in pages if not p.get("redirect")}
    subs: dict[str, list[str]] = {}
    for title in by_title:
        parts = title.split("/")
        for i in range(len(parts) - 1, 0, -1):
            anc = "/".join(parts[:i])
            if anc in works:
                subs.setdefault(anc, []).append(title)
                break
    docs: list[Document] = []
    for work in sorted(works):
        main = by_title.get(work)
        if main is None:
            continue
        head = _header(main["text"])
        children = subs.get(work, [])
        linked = []
        for m in re.finditer(r"\[\[(/[^\]|#]+|" + re.escape(work) + r"/[^\]|#]+)", main["text"]):
            target = m.group(1)
            full = work + target if target.startswith("/") else target
            full = full.rstrip("/")
            if full in by_title and full not in linked:
                linked.append(full)
        order = linked + sorted((c for c in children if c not in linked), key=_natural)
        main_text = main["text"]
        if children or re.search(r"^\s*[*#]+\s*\[\[/", main["text"], re.M):  # the main page lists its subpages (written or
            # not yet): that list is a table of contents
            main_text = "\n".join(l for l in main_text.split("\n") if not _TOC_LINE.match(l))
        blocks = wikitext_blocks(main_text, page=None)
        revs = [main["rev"]]
        last = None
        for title in order:
            p = by_title[title]
            h2 = _header(p["text"])
            suffix = title[len(work) + 1:]
            section = re.sub(r"\s+", " ", h2.get("section") or "").strip()
            if not section or section == last:  # a header copied from the previous subpage
                section = suffix
            last = section
            blocks.append(Block("heading", section, level=1, page=suffix))
            blocks.extend(wikitext_blocks(p["text"], page=suffix, level_offset=1))
            revs.append(p["rev"])
        blocks = strip_modern_paratext([b for b in blocks if b.text.strip()])
        if not any(b.kind != "heading" for b in blocks):
            continue  # nothing but a header (a scan index or a transclusion shell)
        text = "".join(b.text for b in blocks[:400])
        year = head.get("year") or head.get("年") or head.get("y") or ""
        meta = {"作者": head.get("author", ""), "朝代": head.get("times", "") or head.get("dynasty", ""),
                "年份": (year if re.search(r"(公元|西元)", year) else (f"公元{year}年" if re.fullmatch(r"-?\d{1,4}", year.strip()) else "")),
                "notes": re.sub(r"\s+", " ", re.sub(r"\{\{[^{}]*\}\}", "", head.get("notes", ""))).strip()[:200]}
        authors = [a for a in re.split(r"[、，,；;\s]+", re.sub(r"[(（].*?[)）]", "", meta["作者"])) if a]
        docs.append(Document(source=SOURCE["id"], code=work, title=head.get("title") or work, blocks=blocks, meta=meta,
                             authors=authors, url="https://zh.wikisource.org/wiki/" + work.replace(" ", "_"),
                             ref=f"page {main['id']} rev {main['rev']}" + (f" (+{len(order)} subpages)" if order else ""),
                             chartype=chartype(text)))
    return docs


__all__ = ["SOURCE", "category_members", "fetch", "read", "read_index", "wikitext_blocks"]
