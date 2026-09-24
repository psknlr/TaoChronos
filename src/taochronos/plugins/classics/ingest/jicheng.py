"""Parser for the 笈成 (JiCheng) collection — the data of the 笈成檢閱系統 (v1.4.8).

Each book is one UTF-8 text file under ``data/<A–R>/`` with a ``[book]`` metadata block and a tag markup:

* block tags — ``[h1]``…``[h6]`` headings (``title|path title``), ``[p]`` a forced paragraph, ``[box]`` an
  appended block (prescriptions), ``[zb]/[sb]/[jb]`` commentary / sub-commentary / collation blocks,
  ``[dzb]/[dsb]/[djb]`` their full-size variants, ``[wj]`` not yet collated;
* inline tags — ``[b] [i] [u]`` formatting, ``[l]`` small characters (doses), ``[z] [s] [j]`` small-character
  注 / 疏 / 校, ``[dz] [ds] [dj]`` full-size 注 / 疏 / 校 (an author's own notes), ``[id]`` numbering added by
  later editors, ``[c]code[/c]`` a character outside common fonts (resolved through ``config/nclist.txt``),
  ``[img] [url] [media]``; ``[[`` and ``]]`` are literal brackets.

Paragraphs are separated by blank lines.  The texts are punctuated, so claims are extracted without machine
segmentation.  Layers follow the catalog: notes stay inline as （…） unless the book entry gives 注 / 疏 their
own dated layer or a marker (新校正云) separates them; 校 (the editors' collation remarks) and later numbering
never enter the reading text; front matter (序, 跋, 凡例, 目錄) is paratext, dated as undetermined.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..segment import split_long
from .kanripo import LayerSpec

BLOCK_TAGS = ("p", "box", "zb", "sb", "jb", "dzb", "dsb", "djb", "wj", "book")
FRONT = re.compile(r"(序|跋|凡例|題辭|题辞|題詞|题词|弁言|引言|小引|自敘|自叙|提要|例言|讀法|读法|校記|校记|後記|后记|刊誤|目錄|目录|總目|总目|附記|附记|說明|说明)")
TOC = re.compile(r"^(目錄|目录|總目|总目|目次)")
FULL_SPACE = "　"


@dataclass
class NcEntry:
    code: str
    char: str | None  # the Unicode character, when one exists
    common: str | None  # 通用字
    ids: str  # 組字式
    note: str


def read_nclist(path: Path) -> dict[str, NcEntry]:
    out: dict[str, NcEntry] = {}
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8-sig"), flags=re.S)
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        cols = line.split("\t")
        code = cols[0].strip()
        if not code:
            continue
        uni = cols[1].strip() if len(cols) > 1 else ""
        char = None
        if uni:
            try:
                char = chr(int(uni, 16))
            except ValueError:
                char = None
        common = (cols[2].strip() if len(cols) > 2 else "") or None
        ids = cols[3].strip() if len(cols) > 3 else ""
        note = cols[4].split("//")[0].strip() if len(cols) > 4 else ""
        out[code] = NcEntry(code, char, common, ids, note)
    return out


@dataclass
class ListEntry:
    code: str
    path: str
    name: str
    category: str
    remark: str = ""


def read_filelist(root: Path) -> list[ListEntry]:
    text = re.sub(r"/\*.*?\*/", "", (root / "config" / "filelist.txt").read_text(encoding="utf-8-sig"), flags=re.S)
    out: list[ListEntry] = []
    category = ""
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("◎"):
            category = s[1:].strip()
            continue
        remark = ""
        if "//" in s:
            s, remark = s.split("//", 1)
        cols = [c.strip() for c in s.split("\t") if c.strip()]
        if not cols or not cols[0].lower().endswith(".txt"):
            continue
        rel = cols[0]
        code = Path(rel).stem.split("-")[0]
        if not (root / "data" / rel).exists() and (root / "data" / Path(rel).parent / f"{code}.txt").exists():
            rel = (Path(rel).parent / f"{code}.txt").as_posix()  # v1.4.7 renamed the files to plain codes
        name = cols[1] if len(cols) > 1 else code
        name = re.sub(r"^[A-Za-z]+\d*[a-z]?-(?:醫宗金鑑[:-])?", "", name).strip()
        out.append(ListEntry(code, rel, name, category, remark.strip().lstrip("$").strip()))
    # files present in data/ but missing from the list take the category of their directory's listed books
    listed = {e.path for e in out}
    by_dir: dict[str, list[str]] = {}
    for e in out:
        by_dir.setdefault(Path(e.path).parent.as_posix(), []).append(e.category)
    for path in sorted((root / "data").glob("*/*.txt")):
        rel = path.relative_to(root / "data").as_posix()
        if rel in listed:
            continue
        cats = by_dir.get(Path(rel).parent.as_posix()) or [""]
        meta = read_book_block(path.read_text(encoding="utf-8-sig", errors="replace")[:3000])
        out.append(ListEntry(path.stem, rel, meta.get("書名", path.stem), max(set(cats), key=cats.count), "未列入檔案表"))
    return out


def read_book_block(text: str) -> dict[str, str]:
    m = re.search(r"\[book\](.*?)\[/book\]", text, re.S)
    out: dict[str, str] = {}
    if not m:
        return out
    for line in m.group(1).strip().splitlines():
        if "：" in line:
            k, v = line.split("：", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def read_synonym_groups(path: Path) -> list[list[str]]:
    """Variant groups of the viewer's search table, skipping the sections that must not be merged for research:
    easily misjudged characters (乾/干, 云/雲, 耳/爾 …) and one-to-many simplifications (「意義往往不同」)."""
    groups: list[list[str]] = []
    skip = False
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8-sig"), flags=re.S)
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith("//"):
            skip = any(x in s for x in ("易誤判", "易误判", "一對多", "一对多"))
            continue
        if not s or skip:
            continue
        s = s.split("//", 1)[0]
        members = [m.strip() for m in s.split("\t") if m.strip()]
        if len(members) >= 2:
            groups.append(members)
    return groups


# ------------------------------------------------------------------ inline markup
@dataclass
class Segment:
    layer: str  # main | z | s | drop
    text: str


class Inline:
    """Render inline markup into layered segments (``main`` text, ``z`` 注, ``s`` 疏, ``drop``)."""

    TAG = re.compile(r"\[\[|\]\]|\[(/?)([a-z]+\d?)(?:\|[^\]]*)?\]")

    def __init__(self, nc: dict[str, NcEntry]) -> None:
        self.nc = nc
        self.gaiji: list[str] = []
        self.numbers: list[str] = []
        self.unknown_tags: set[str] = set()

    def char(self, code: str) -> str:
        entry = self.nc.get(code.strip())
        if entry is not None and entry.char:
            return entry.char
        self.gaiji.append(f"{code.strip()}|{entry.ids if entry else ''}|{entry.common or '' if entry else ''}")
        return "〓"

    def render(self, text: str) -> list[Segment]:
        out: list[Segment] = []
        stack: list[str] = []
        pos = 0

        def layer() -> str:
            for t in reversed(stack):
                if t in ("j", "dj", "id", "img", "url", "media", "jb", "djb"):
                    return "drop"
                if t in ("z", "zb"):
                    return "z"
                if t in ("s", "sb"):
                    return "s"
            return "main"

        def emit(s: str) -> None:
            if not s:
                return
            if "id" in stack:  # numbering added by later editors: kept for the locator, never in the text
                self.numbers.append(s)
                return
            lay = layer()
            if out and out[-1].layer == lay:
                out[-1].text += s
            else:
                out.append(Segment(lay, s))

        for m in self.TAG.finditer(text):
            if m.start() < pos:
                continue  # inside a [c]…[/c] already consumed
            emit(text[pos:m.start()])
            pos = m.end()
            tok = m.group(0)
            if tok == "[[":
                emit("[")
                continue
            if tok == "]]":
                emit("]")
                continue
            closing, tag = m.group(1), m.group(2)
            if tag == "c" and not closing:
                end = text.find("[/c]", m.end())
                if end >= 0:
                    emit(self.char(text[m.end():end]))
                    pos = end + 4
                continue
            if tag in ("b", "i", "u", "l", "dz", "ds", "dzb", "dsb", "wj", "p", "box", "h1", "h2", "h3", "h4", "h5", "h6"):
                continue  # transparent: formatting, full-size notes of the main layer, a heading inside a [p] block
            if tag in ("z", "s", "j", "dj", "id", "img", "url", "media", "zb", "sb", "jb", "djb"):
                if not closing:
                    stack.append(tag)
                elif tag in stack:
                    idx = len(stack) - 1 - stack[::-1].index(tag)
                    stack.pop(idx)
                continue
            self.unknown_tags.add(tag)
        emit(text[pos:])
        return out


# ------------------------------------------------------------------ blocks
@dataclass
class Block:
    kind: str  # heading | para | box | note
    level: int = 0
    text: str = ""
    layer: str = "main"  # for note blocks: z | s | drop
    uncollated: bool = False


def _own_line(m: re.Match) -> str:
    return "\n" + re.sub(r"\s*\n\s*", "", m.group(0)) + "\n"


def blocks(body: str) -> Iterator[Block]:
    """Headings, [p]/[box]/note blocks and blank-line separated paragraphs.  A heading written inside a line
    (「…日進三服。[h4]肉苛證…[/h4]」) or across lines is moved onto a line of its own first."""
    body = re.sub(r"\[h([1-6])\].*?\[/h\1\]", _own_line, body.replace("\r\n", "\n"), flags=re.S)
    lines = body.split("\n")
    i = 0
    buf: list[str] = []

    def flush() -> Iterator[Block]:
        text = "\n".join(buf).strip("\n")
        buf.clear()
        if text.strip():
            yield Block("para", text=text)

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        hm = re.match(r"^\[h([1-6])\](.*)\[/h\1\]\s*$", s)
        if hm:
            yield from flush()
            yield Block("heading", level=int(hm.group(1)), text=hm.group(2))
            i += 1
            continue
        bm = re.match(r"^\[(p|box|zb|sb|jb|dzb|dsb|djb|wj|book)\]", s)
        if bm:
            tag = bm.group(1)
            yield from flush()
            content: list[str] = [s[len(tag) + 2:]]
            close = f"[/{tag}]"
            while close not in content[-1] and i + 1 < len(lines):
                i += 1
                content.append(lines[i])
            text = "\n".join(content)
            text = text[: text.rfind(close)] if close in text else text
            i += 1
            if tag == "book":
                continue
            kind = {"box": "box", "zb": "note", "sb": "note", "jb": "note", "djb": "note"}.get(tag, "para")
            layer = {"zb": "z", "sb": "s", "jb": "drop", "djb": "drop"}.get(tag, "main")
            for part in (re.split(r"\n\s*\n", text) if tag in ("dzb", "dsb", "wj") else [text]):
                if part.strip():
                    yield Block(kind, text=part.strip("\n"), layer=layer, uncollated=(tag == "wj"))
            continue
        if not s:
            yield from flush()
        else:
            buf.append(line)
        i += 1
    yield from flush()


# ------------------------------------------------------------------ dated prefaces
_MARKUP = re.compile(r"\[(j|dj|id|img|url|media)\].*?\[/\1\]|\[c\].*?\[/c\]|\[/?[a-z0-9]+\]", re.S)
# what follows the date in a signature line: month or season, or the act of writing (normalised forms)
_SIGN = re.compile(r"(月|日|春|夏|秋|冬|朔|望|节|序|叙|敘|识|題|题|跋|书|記|记|撰|谨|謹)")
_SELF = re.compile(r"自(序|叙|敘|题|題|书|書|识|識|记|記|跋)")


def front_paragraphs(body: str) -> Iterator[str]:
    """Paragraphs of the front and back matter (序, 跋, 凡例 …) and before the first heading, markup removed."""
    front, seen = False, False
    for b in blocks(body):
        if b.kind == "heading":
            seen = True
            if b.level <= 3:
                front = bool(FRONT.search(b.text.split("|")[0]))
            continue
        if front or not seen:
            yield _MARKUP.sub("", b.text)


def preface_dates(body: str, chronology: Any, authors: list[str] = ()) -> list[tuple[int, bool, str]]:
    """Dated signature lines of prefaces and postfaces — 「康熙甲戌歲陽月，休寧八十老人訒庵汪昂書」 — as
    (year, by_the_author, context).  A date counts when it closes its paragraph (the last 90 characters) and is
    followed by a month, season or the act of writing; it is the author's when the line says 自序 or names an
    author of the book."""
    n = chronology.normalize
    names = {n(a) for a in authors if len(a) >= 2}
    names |= {x[-2:] for x in names if len(x) >= 3}
    out: list[tuple[int, bool, str]] = []
    for para in front_paragraphs(body):
        norm = n(para)
        for year, start, end in chronology.statements(para):
            if len(norm) - start > 90 or not _SIGN.search(norm[end:end + 16]):
                continue
            ctx = norm[max(0, start - 30): end + 40]
            out.append((year, bool(_SELF.search(ctx)) or any(a in ctx for a in names), para[max(0, start - 6): end + 24].strip()))
    return out


# ------------------------------------------------------------------ parser
@dataclass
class JichengSpec:
    """What the catalog says about one 笈成 book (auto-generated metadata plus curated overrides)."""

    book_id: str
    code: str
    composition: tuple[int, int]
    dynasty: str
    edition_id: str
    z_layer: LayerSpec | None = None  # None: 注 stays inline in the main layer
    s_layer: LayerSpec | None = None
    markers: list[tuple[str, LayerSpec]] = field(default_factory=list)
    mixed: LayerSpec | None = None
    cites: tuple[int, int] | None = None
    chapter_layers: list[tuple[str, LayerSpec]] = field(default_factory=list)
    section_layers: list[tuple[str, LayerSpec]] = field(default_factory=list)
    front_matter: LayerSpec | None = None  # paratext dating (undetermined, never earlier than the work)
    main_layer: str = "正文"


def _t(spec: JichengSpec, layer: LayerSpec | None, citation: tuple[int, int] | None, dynasty_of: Any) -> dict[str, Any]:
    comp = layer.year if layer is not None else spec.composition
    dyn = spec.dynasty
    if layer is not None and dynasty_of is not None:
        dyn = dynasty_of((comp[0] + comp[1]) / 2) or spec.dynasty
    return {"dynasty": dyn, "t_author": None, "t_composition": [comp[0], comp[1]], "t_edition": None,
            "t_citation": [citation[0], citation[1]] if citation else None}


SIGNED_PREFACE = "序跋（按落款年代）"


class JichengParser:
    def __init__(self, spec: JichengSpec, nc: dict[str, NcEntry], dynasty_of: Any = None, chronology: Any = None) -> None:
        self.spec = spec
        self.nc = nc
        self.dynasty_of = dynasty_of
        self.chronology = chronology  # dates signed prefaces; without it all paratext keeps the front-matter date
        self.report: dict[str, Any] = {"paragraphs": 0, "headings": 0, "boxes": 0, "notes": 0, "gaiji": 0,
                                        "dropped_collation": 0, "layers": {}, "unknown_tags": [], "signed_prefaces": 0}

    def date_prefaces(self, rows: list[dict[str, Any]]) -> None:
        """A preface or postface whose closing line is dated (「康熙甲戌歲陽月……汪昂書」) takes that year — the
        date of the paratext itself, which may be earlier than the book as transmitted (an older preface kept
        in a later recension) or later (a reprint's preface)."""
        chron = self.chronology
        groups: list[list[dict[str, Any]]] = []
        prev: tuple | None = None
        for r in rows:
            if r["kind"] != "preface":
                prev = None
                continue
            key = (r["locator"].get("volume"), r["locator"].get("chapter"), r["locator"].get("section"))
            if key != prev:
                groups.append([])
                prev = key
            groups[-1].append(r)
        for group in groups:
            # several prefaces may share a heading: each run of rows ending in a signed line takes its date;
            # rows after the last signature (credits, notes) keep the undetermined front-matter date
            run: list[dict[str, Any]] = []
            for r in group:
                run.append(r)
                year = None
                norm = chron.normalize(r["text"])
                for y, start, end in chron.statements(r["text"]):
                    if len(norm) - start <= 90 and _SIGN.search(norm[end:end + 16]) and -300 <= y <= 1949:
                        year = y
                if year is None:
                    continue
                self.report["signed_prefaces"] += 1
                dyn = (self.dynasty_of(year) if self.dynasty_of else None) or self.spec.dynasty
                for x in run:
                    self.report["layers"][x["layer"]] -= 1
                    self.report["layers"][SIGNED_PREFACE] = self.report["layers"].get(SIGNED_PREFACE, 0) + 1
                    x.update(layer=SIGNED_PREFACE, year=float(year), y_start=year, y_end=year)
                    x["temporal"] = {**x["temporal"], "dynasty": dyn, "t_composition": [year, year]}
                    x["extra"] = {**x["extra"], "layer": SIGNED_PREFACE}
                run = []
        self.report["layers"] = {k: v for k, v in self.report["layers"].items() if v}

    def split_note(self, note: str, default: LayerSpec | None) -> list[tuple[LayerSpec | None, str]]:
        cuts: list[tuple[int, LayerSpec]] = []
        for prefix, layer in self.spec.markers:
            for m in re.finditer(prefix, note):
                cuts.append((m.start(), layer))
        cuts.sort(key=lambda t: t[0])
        out: list[tuple[LayerSpec | None, str]] = []
        pos, layer = 0, default
        for at, lay in cuts:
            if at > pos:
                out.append((layer, note[pos:at]))
            pos, layer = at, lay
        if pos < len(note):
            out.append((layer, note[pos:]))
        return out

    def _row(self, rows: list[dict[str, Any]], seq: int, kind: str, layer: LayerSpec | None, text: str,
             loc: dict[str, Any], extra: dict[str, Any], citation: tuple[int, int] | None = None,
             punctuation: str = "editorial") -> None:
        spec = self.spec
        temporal = _t(spec, layer, citation, self.dynasty_of)
        name = layer.name if layer else spec.main_layer
        rows.append({
            "id": f"{spec.book_id}.{seq:05d}", "book_id": spec.book_id, "edition_id": spec.edition_id, "seq": seq,
            "kind": kind, "layer": name, "year": (temporal["t_composition"][0] + temporal["t_composition"][1]) / 2,
            "y_start": temporal["t_composition"][0], "y_end": temporal["t_composition"][1], "locator": loc,
            "temporal": temporal, "text": text, "punctuation": punctuation,
            "extra": {"layer": name, **({"attribution": layer.attribution} if layer and layer.attribution else {}), **extra},
        })
        self.report["layers"][name] = self.report["layers"].get(name, 0) + 1

    def parse(self, path: Path, start_seq: int = 0) -> list[dict[str, Any]]:
        spec = self.spec
        raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        body = re.sub(r"\[book\].*?\[/book\]", "", raw, count=1, flags=re.S)
        rows: list[dict[str, Any]] = []
        seq = start_seq
        heads: dict[int, str] = {}
        chapter_layer: LayerSpec | None = None
        section_layer: LayerSpec | None = None
        front = False
        toc = False
        for block in blocks(body):
            inline = Inline(self.nc)
            if block.kind == "heading":
                self.report["headings"] += 1
                title_markup = block.text.split("|")[0] if not block.text.startswith("|") else block.text[1:]
                segs = inline.render(title_markup)
                title = "".join(s.text for s in segs if s.layer == "main").strip(FULL_SPACE + " ")
                if not title:
                    continue
                for lvl in [k for k in heads if k >= block.level]:
                    del heads[lvl]
                heads[block.level] = title
                # paratext: under a 序 / 跋 / 凡例 / 目錄 heading (at any enclosing level)
                front = any(FRONT.search(h) and len(h) <= 20 for lvl, h in heads.items() if lvl <= 3)
                toc = any(TOC.match(h) for h in heads.values())
                if block.level <= min(heads):
                    chapter_layer = next((lay for pat, lay in spec.chapter_layers if re.search(pat, title)), None)
                    section_layer = None
                if spec.chapter_layers and chapter_layer is None:
                    chapter_layer = next((lay for pat, lay in spec.chapter_layers if re.search(pat, title)), chapter_layer)
                for pat, lay in spec.section_layers:
                    if re.search(pat, title):
                        section_layer = lay
                # notes attached to a heading (e.g. 新校正 on a title) become commentary of their layer
                for seg in segs:
                    if seg.layer in ("z", "s") and seg.text.strip():
                        default = spec.z_layer if seg.layer == "z" else spec.s_layer
                        for lay, body_text in self.split_note(seg.text, default):
                            if lay is not None and body_text.strip():
                                self._row(rows, seq, "commentary", lay, body_text.strip(), self._loc(heads, None),
                                          {"on_heading": title})
                                seq += 1
                continue
            self.report["paragraphs"] += 1
            segs = inline.render(block.text)
            self.report["gaiji"] += len(inline.gaiji)
            self.report["unknown_tags"] = sorted(set(self.report["unknown_tags"]) | inline.unknown_tags)
            number = inline.numbers[0].strip(" .、．") if inline.numbers else None
            kind = "toc" if toc else ("preface" if front else ("formula" if block.kind == "box" else "text"))
            layer: LayerSpec | None = section_layer or chapter_layer
            citation: tuple[int, int] | None = None
            if front:
                layer = spec.front_matter
            elif spec.mixed is not None and layer is None:
                layer, citation = spec.mixed, spec.cites or spec.composition
            main: list[str] = []
            commentary: list[tuple[LayerSpec, str]] = []
            block_layer = block.layer if block.kind == "note" else None
            for seg in segs:
                seg_layer = block_layer if block_layer in ("z", "s", "drop") and seg.layer == "main" else seg.layer
                if seg_layer == "drop":
                    self.report["dropped_collation"] += 1
                    continue
                if seg_layer == "main":
                    main.append(seg.text)
                    continue
                self.report["notes"] += 1
                default = spec.z_layer if seg_layer == "z" else spec.s_layer
                inline_parts: list[str] = []
                for lay, body_text in self.split_note(seg.text, default):
                    if lay is None or front:
                        inline_parts.append(body_text)
                    elif body_text.strip():
                        commentary.append((lay, body_text.strip()))
                if inline_parts:
                    if block_layer in ("z", "s"):
                        main.append("".join(inline_parts))  # a whole note block kept in the main layer
                    else:
                        main.append("（" + "".join(inline_parts) + "）")
            joined = "".join(main)
            if block.kind == "box":  # name, ingredients and preparation are separate lines of a prescription
                joined = re.sub(r"\s*\n+\s*", FULL_SPACE, joined.strip())
            text = re.sub(r"\n+", "", joined).strip(FULL_SPACE + " \n")
            section = None
            if block.kind == "box":
                bm = re.search(r"\[b\](.*?)\[/b\]", block.text)
                section = re.sub(r"\[/?[a-z]+\d?\]", "", bm.group(1)).strip() if bm else None
                self.report["boxes"] += 1
            loc = self._loc(heads, section, number)
            extra: dict[str, Any] = {}
            if inline.gaiji:
                extra["gaiji"] = list(inline.gaiji)
            if number:
                extra["number"] = number
            if block.uncollated:
                extra["collation_status"] = "unverified"
            first_id = None
            if text and text.strip("（）" + FULL_SPACE):
                for s0, e0 in split_long(text):
                    chunk = text[s0:e0]
                    if chunk.strip("（）" + FULL_SPACE + " "):
                        self._row(rows, seq, kind, layer, chunk, loc, extra, citation)
                        first_id = first_id or rows[-1]["id"]
                        seq += 1
            grouped: dict[str, tuple[LayerSpec, list[str]]] = {}
            for lay, body_text in commentary:
                grouped.setdefault(lay.name, (lay, []))[1].append(body_text)
            for name, (lay, bodies) in grouped.items():
                ctext = FULL_SPACE.join(bodies)
                for s0, e0 in split_long(ctext):
                    self._row(rows, seq, "commentary", lay, ctext[s0:e0], loc, {"anchor": first_id})
                    seq += 1
        if self.chronology is not None:
            self.date_prefaces(rows)
        self.report["passages"] = len(rows)
        return rows

    @staticmethod
    def _loc(heads: dict[int, str], section: str | None, number: str | None = None) -> dict[str, Any]:
        path = [heads[k] for k in sorted(heads)]
        volume = path[0] if len(path) > 2 else None
        rest = path[1:] if len(path) > 2 else path
        chapter = rest[0] if rest else None
        tail = rest[1:] + ([section] if section else []) + ([f"第{number}条"] if number and number.isdigit() else [])
        return {"volume": volume, "chapter": chapter, "section": " · ".join(tail) if tail else None, "precision": "exact"}
