"""Parser for Kanripo (漢籍リポジトリ) mandoku texts.

A text is a git repository ``KRxxnnnn`` with one file per 卷 (``KRxxnnnn_JJJ.txt``).  Files carry
``#+PROPERTY:`` headers (ID, BASEEDITION, WITNESS, JUAN), page markers ``<pb:ID_EDITION_JUAN-PAGE>``
and physical lines ending in ``¶``.  Small-character double-column notes (割注) are written ``(A/B)``
per physical line; the reading order of the two columns is ``A`` then ``B`` in most transcriptions and
``B`` then ``A`` in a few (declared per book in the catalog and checked at ingest).  Characters outside
Unicode are written ``&KR0001;`` or as an ideographic description ``[病-丙+(穩-禾)]``; they become 〓
in the reading text and are kept in the passage metadata.

Two page layouts occur: *full-line* (each physical line is a printed column; a paragraph ends on a
short line or an indentation change) and *blank-separated* (paragraphs separated by empty lines, notes
may run across lines without the column separator).

The output is a list of passage rows (``dict``) for ``CorpusStore.add_passages``: the reading text keeps
notes inline as （…） for books whose notes belong to the main layer, or moves them to dated commentary
passages when the catalog gives the notes their own layer (王冰注, 新校正, 四库馆臣按…).  The page and
line of the first physical line are kept in the locator (Claim → Page → Line).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..segment import split_long

GAIJI = re.compile(r"&KR\d+;|\[[^\[\]\n]*[-+*][^\[\]\n]*\]")
PB = re.compile(r"<pb:([^>_]+)_([^>_]+)_([^>]+)>")
HEADING_SUFFIX = re.compile(r"(第[一二三四五六七八九十百〇零]+|[上中下]|之[一二三四五六七八九十]+)$")
FORMULA_HEADING = re.compile(r"(湯|汤|散|丸|圓|圆|飲|饮|丹|膏|煎|方)$")
JUAN_TITLE = re.compile(r"卷[第之]?[一二三四五六七八九十百〇零上中下首末\d]+")
QIANLONG = re.compile(r"乾隆([一二三四五六七八九十]+)年")
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
FULL_SPACE = "　"


def cn_number(text: str) -> int | None:
    """Small Chinese numerals (up to 99): 四十六 → 46."""
    if not text:
        return None
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = CN_NUM.get(head, 1) if head else 1
        return tens * 10 + (CN_NUM.get(tail, 0) if tail else 0)
    return CN_NUM.get(text)


@dataclass
class PhysLine:
    page: str | None
    line: int
    raw: str
    indent: int = 0
    blank: bool = False
    section: str = ""  # the JUAN property in force (a file may hold 提要, 目錄, 序 … one after another)
    gaiji: list[str] = field(default_factory=list)  # originals of the 〓 on this line


@dataclass
class Piece:
    kind: str  # main | note
    text: str
    page: str | None
    line: int


@dataclass
class Paragraph:
    gaiji: list[str] = field(default_factory=list)
    pieces: list[Piece] = field(default_factory=list)
    indent: int = 0
    lines: int = 0
    page: str | None = None
    line: int = 0
    heading: bool = False  # a chapter-title line (may carry notes)

    def main_text(self) -> str:
        return "".join(p.text for p in self.pieces if p.kind == "main")


@dataclass
class KanripoFile:
    path: Path
    props: dict[str, str]
    lines: list[PhysLine]
    gaiji: list[str]  # originals of 〓 in order of appearance


def read_file(path: Path) -> KanripoFile:
    props: dict[str, str] = {}
    lines: list[PhysLine] = []
    gaiji: list[str] = []
    page: str | None = None
    line_no = 0
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("#"):
            m = re.match(r"#\+(?:PROPERTY:\s*)?(\w+):?\s*(.*)$", raw)
            if m:
                key, value = m.group(1).upper(), m.group(2).strip()
                props.setdefault(key, value)
                if key == "JUAN":
                    section = value
            continue
        pb = PB.search(raw)
        if pb and raw.strip().startswith("<pb:"):
            page = pb.group(3)
            line_no = 0
            rest = PB.sub("", raw).replace("¶", "").strip()
            if not rest:
                continue
            raw = PB.sub("", raw)
        text = raw.rstrip("\n").replace("¶", "")
        if PB.search(text):
            text = PB.sub("", text)
        line_no += 1
        found: list[str] = []

        def keep(m: re.Match) -> str:
            found.append(m.group(0))
            return "〓"

        text = GAIJI.sub(keep, text)
        gaiji.extend(found)
        stripped = text.lstrip(FULL_SPACE)
        lines.append(PhysLine(page, line_no, text, len(text) - len(stripped), not text.strip(" " + FULL_SPACE), section, found))
    return KanripoFile(path, props, lines, gaiji)


def split_sections(f: KanripoFile) -> list[KanripoFile]:
    """One file may hold several sections (提要, 目錄, 序, 凡例 …), each under its own JUAN header."""
    groups: list[KanripoFile] = []
    for pl in f.lines:
        if not groups or groups[-1].props.get("JUAN", "") != pl.section:
            groups.append(KanripoFile(f.path, {**f.props, "JUAN": pl.section}, [], []))
        groups[-1].lines.append(pl)
        groups[-1].gaiji.extend(pl.gaiji)
    return groups or [f]


def line_pieces(text: str, in_note: bool, order: str) -> tuple[list[tuple[str, str]], bool]:
    """Split one physical line into (kind, text) pieces; notes may continue across lines."""
    out: list[tuple[str, str]] = []
    buf = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if not in_note and ch == "(":
            if buf:
                out.append(("main", buf))
            buf, in_note = "", True
        elif in_note and ch == ")":
            out.append(("note", _columns(buf, order)))
            buf, in_note = "", False
        else:
            buf += ch
        i += 1
    if buf:
        out.append(("note", _columns(buf, order)) if in_note else ("main", buf))
    return out, in_note


def _columns(note: str, order: str) -> str:
    note = note.replace(" ", "")
    if "/" not in note:
        return note
    parts = note.split("/")
    # BA transcriptions list the left column first: the first segment is read last (A/B → B A, X/Y/Z → Y Z X)
    return "".join(parts[1:] + parts[:1]) if order == "BA" else "".join(parts)


def cells(raw: str) -> int:
    """Printed width of a physical line: main characters plus the wider column of each note."""
    total = 0
    pos = 0
    for m in re.finditer(r"\(([^()]*)(\)|$)|^([^()]*)\)", raw):
        total += len(raw[pos:m.start()])
        body = (m.group(1) if m.group(1) is not None else m.group(3) or "").replace(" ", "")
        total += max((len(c) for c in body.split("/")), default=0)
        pos = m.end()
    return total + len(raw[pos:])


def modal_width(files: list[KanripoFile]) -> int:
    counts: dict[int, int] = {}
    for f in files:
        for pl in f.lines:
            if not pl.blank:
                w = cells(pl.raw)
                counts[w] = counts.get(w, 0) + 1
    if not counts:
        return 0
    return max(counts.items(), key=lambda t: (t[1], t[0]))[0]


def short_threshold(files: list[KanripoFile], width: int) -> float:
    """Width below which a line ends a paragraph.  Regular editions (most lines within ±1 of the modal
    width, e.g. 四库全书 at 21) use ``width − 1``; editions whose small-character notes make the measured
    width irregular (some 四部丛刊 transcriptions) use a looser 70 % so sentences are not cut."""
    total = near = 0
    for f in files:
        for pl in f.lines:
            if not pl.blank:
                total += 1
                near += abs(cells(pl.raw) - width) <= 1
    regular = total == 0 or near / total >= 0.5
    return width - 1 if regular else 0.7 * width


CHAPTER_LINE = re.compile(r"^[^\u3000]{2,16}?(篇|論|论|經|经|門|门|類|类|卷|章|法|病|證|证|方)第[一二三四五六七八九十百〇]+$")
TOC_TOKEN = re.compile(r"(論|论|篇|經|经|門|门|類|类)(第?[一二三四五六七八九十百〇]+)?$")


def _listy(raw: str) -> bool:
    """A printed list line: items separated by runs of full-width spaces."""
    core = re.sub(r"\([^()]*\)?", "", raw).strip(FULL_SPACE + " ")
    return bool(re.search(FULL_SPACE + "+", core))


INSTRUCTION = re.compile(r"^(右|上|已上|巳上|以上)[^\u3000（]{0,4}?(件|為|为|各|等|味|物|㕮咀|剉|擣|搗|捣|細|细|粗|同|並|并|藥|药|末|切|研)")
DOSED_ITEM = re.compile(r"[^\u3000（）]{1,6}（[^）]{1,16}）")


def list_like(text: str) -> bool:
    """A paragraph that continues a prescription: an ingredient list or the 右件… preparation line."""
    core = re.sub(r"（[^）]*）", "", text).strip(FULL_SPACE + " ")
    if INSTRUCTION.match(core):
        return True
    tokens = [t for t in core.split(FULL_SPACE) if t]
    if len(tokens) == 1 and len(core) <= 8 and "（" in text:
        return True  # a single ingredient with its dose / processing note
    units = DOSED_ITEM.findall(text)
    if len(units) >= 2 and sum(len(u) for u in units) >= 0.8 * len(text.replace(FULL_SPACE, "")):
        return True  # 括蔞根（二兩）桂枝（三兩）芍藥（三兩）
    return len(tokens) >= 2 and all(len(t) <= 10 for t in tokens)


def _main_of(raw: str) -> str:
    return re.sub(r"\([^()]*\)?", "", raw).strip(FULL_SPACE + " ")


def paragraphs(f: KanripoFile, order: str, width: int, threshold: float | None = None) -> Iterator[Paragraph]:
    """Group physical lines into paragraphs (layout-aware) and split them into main / note pieces.

    Chapter-title lines (…篇第五) are always paragraphs of their own, and per-卷 contents lines listing
    chapter titles before the first chapter are dropped."""
    blank_layout = sum(1 for pl in f.lines if pl.blank) > 0.3 * max(1, len(f.lines))
    para: Paragraph | None = None
    in_note = False
    prev: PhysLine | None = None
    prev_width = 0.0
    seen_chapter = False
    limit = (width - 1) if threshold is None else threshold
    for pl in f.lines:
        if pl.blank:
            if blank_layout and para is not None and not in_note:
                yield para
                para = None
            continue
        main = _main_of(pl.raw)
        chapter_line = not in_note and bool(CHAPTER_LINE.match(main))
        if not in_note and not seen_chapter and pl.indent >= 2 and "(" not in pl.raw:
            tokens = [t for t in main.split(FULL_SPACE) if t]
            if tokens and all(TOC_TOKEN.search(t) for t in tokens) and not chapter_line:
                continue
        width_here = cells(pl.raw)
        new = para is None or chapter_line
        if not new and not blank_layout and not in_note:
            new = prev_width < limit or pl.indent != (prev.indent if prev else 0)
        if new and para is not None:
            yield para
            para = None
        if para is None:
            para = Paragraph(indent=pl.indent, page=pl.page, line=pl.line)
        body = pl.raw.lstrip(FULL_SPACE)
        if para.lines and not in_note and prev is not None and para.pieces and (_listy(prev.raw) or _listy(body)):
            # items of a printed list: keep them apart across the line break
            if para.pieces[-1].kind == "main":
                para.pieces[-1].text += FULL_SPACE
            else:
                para.pieces.append(Piece("main", FULL_SPACE, pl.page, pl.line))
        pieces, in_note = line_pieces(body, in_note, order)
        for kind, txt in pieces:
            last = para.pieces[-1] if para.pieces else None
            if last is not None and last.kind == kind:
                last.text += txt  # main text continues, or a note runs on (across lines or column pairs)
                continue
            para.pieces.append(Piece(kind, txt, pl.page, pl.line))
        para.lines += 1
        para.gaiji.extend(pl.gaiji)
        prev, prev_width = pl, width_here
        if chapter_line:
            seen_chapter = seen_chapter or not JUAN_TITLE.search(main)
            para.heading = True
            yield para
            para = None
    if para is not None:
        yield para


def is_heading(p: Paragraph, width: int, blank_layout: bool = False) -> bool:
    if p.heading:
        return True
    text = p.main_text().strip(FULL_SPACE)
    if p.lines != 1 or not text or any(x.kind == "note" for x in p.pieces):
        return False
    if JUAN_TITLE.search(text) or text.startswith("︻"):
        return True
    core = text.strip(FULL_SPACE + " ")
    if FULL_SPACE in core or len(core) > 16:
        return False
    if re.search(r"[也矣焉哉乎]$", core):
        return False
    if HEADING_SUFFIX.search(core) and re.search(r"(篇|論|论|經|经|門|门|類|类|卷|章|法|病|證|证)(第|之)", core):
        return True  # 天元紀大論篇第六十六, set flush with the text in some editions
    if INSTRUCTION.match(core) or re.search(r"(服|煮|取|匕|以水|以酒|日[一二三四五]|傅之|塗之|即愈|即差|良)", core):
        return False  # preparation / administration lines are text, however short
    if blank_layout:
        return len(core) <= 12
    return p.indent >= 2 or (p.indent >= 1 and bool(HEADING_SUFFIX.search(core)))


def is_toc_line(p: Paragraph) -> bool:
    """A single line listing chapter titles (the per-卷 contents set at the head of a 卷)."""
    if p.lines != 1 or any(x.kind == "note" for x in p.pieces):
        return False
    tokens = [t for t in p.main_text().split(FULL_SPACE) if t]
    return len(tokens) >= 2 and all(re.search(r"(論|论|篇|經|经|第[一二三四五六七八九十百]+|門|门|類|类)$", t) for t in tokens)


def juan_label(props: dict[str, str], stem: str) -> str:
    juan = props.get("JUAN", "").strip()
    if juan.isdigit():
        return f"卷{int(juan)}"
    return juan or stem.split("_")[-1]


def qianlong_year(text: str) -> int | None:
    m = QIANLONG.search(text)
    if not m:
        return None
    n = cn_number(m.group(1))
    return None if n is None else 1735 + n


@dataclass
class LayerSpec:
    name: str
    year: tuple[int, int]
    attribution: str = ""


@dataclass
class BookSpec:
    """What the catalog says about one Kanripo text (see corpus/catalog/*.yaml)."""

    book_id: str
    kr_id: str
    composition: tuple[int, int]
    edition_id: str
    edition_year: tuple[int, int] | None
    dynasty: str
    author_life: tuple[int, int] | None = None
    note_order: str = "AB"
    notes: LayerSpec | None = None  # None: notes stay inline in the main layer
    markers: list[tuple[str, LayerSpec]] = field(default_factory=list)  # note prefix → layer
    indented_commentary: LayerSpec | None = None  # WYG commentaries: indented blocks are commentary
    mixed: LayerSpec | None = None  # layers cannot be separated: date everything by this layer
    cites: tuple[int, int] | None = None  # date of the older material a mixed witness transmits (t_citation)
    chapter_layers: list[tuple[str, LayerSpec]] = field(default_factory=list)  # chapter-title regex → layer
    section_layers: list[tuple[str, LayerSpec]] = field(default_factory=list)  # heading regex → layer until next chapter
    main_layer: str = "正文"


def _yr(v: tuple[int, int] | None) -> list[int] | None:
    return None if v is None else [int(v[0]), int(v[1])]


DYNASTY_OF: Any = None  # set by the ingest pipeline: year → dynasty label (for layers younger than the work)


def _temporal(spec: BookSpec, layer: LayerSpec | None, citation: tuple[int, int] | None = None) -> dict[str, Any]:
    comp = layer.year if layer is not None else spec.composition
    dynasty = spec.dynasty
    if layer is not None and DYNASTY_OF is not None:
        dynasty = DYNASTY_OF((comp[0] + comp[1]) / 2) or spec.dynasty
    return {
        "dynasty": dynasty,
        "t_author": _yr(spec.author_life) if layer is None else None,
        "t_composition": _yr(comp),
        "t_edition": _yr(spec.edition_year),
        "t_citation": _yr(citation),
    }


def _mid(r: list[int] | None) -> float | None:
    return None if r is None else (r[0] + r[1]) / 2


class KanripoParser:
    def __init__(self, spec: BookSpec) -> None:
        self.spec = spec
        self.report: dict[str, Any] = {"files": 0, "paragraphs": 0, "headings": 0, "notes": 0, "gaiji": 0,
                                        "commentary_passages": 0, "layers": {}}

    def files(self, repo: Path) -> list[KanripoFile]:
        return [part for p in sorted(repo.glob(f"{self.spec.kr_id}_*.txt")) for part in split_sections(read_file(p))]

    @staticmethod
    def note_order_scores(files: list[KanripoFile], bigram: Any) -> tuple[int, float]:
        """(number of notes continuing across lines, AB − BA junction log-probability)."""
        diff = 0.0
        n = 0
        for f in files:
            for x, y in zip(f.lines, f.lines[1:]):
                mx = re.search(r"\(([^()]*)/([^()]*)\)$", x.raw)
                my = re.match(r"\(([^()]*)/([^()]*)\)", y.raw[y.indent:])
                if not (mx and my):
                    continue
                a1, b1 = mx.group(1).replace(" ", ""), mx.group(2).replace(" ", "")
                a2, b2 = my.group(1).replace(" ", ""), my.group(2).replace(" ", "")
                if not (a1 and b1 and a2 and b2):
                    continue
                diff += (bigram(a1[-1], b1[0]) + bigram(b1[-1], a2[0])) - (bigram(b1[-1], a1[0]) + bigram(a1[-1], b2[0]))
                n += 1
        return n, diff

    def split_note(self, note: str) -> list[tuple[LayerSpec | None, str]]:
        """Split a note at layer markers (e.g. 新校正云); text before the first marker keeps the default
        notes layer (None = main layer, i.e. the note stays inline)."""
        cuts: list[tuple[int, LayerSpec]] = []
        for prefix, layer in self.spec.markers:
            for m in re.finditer(prefix, note):
                cuts.append((m.start(), layer))
        cuts.sort(key=lambda t: t[0])
        out: list[tuple[LayerSpec | None, str]] = []
        pos, layer = 0, self.spec.notes
        for at, lay in cuts:
            if at > pos:
                out.append((layer, note[pos:at]))
            pos, layer = at, lay
        if pos < len(note):
            out.append((layer, note[pos:]))
        return out

    def _row(self, rows: list[dict[str, Any]], seq: int, juan_code: str, kind: str, layer: LayerSpec | None,
             text: str, loc: dict[str, Any], extra: dict[str, Any], citation: tuple[int, int] | None = None) -> None:
        spec = self.spec
        temporal = _temporal(spec, layer, citation)
        name = layer.name if layer else spec.main_layer
        rows.append({
            "id": f"{spec.book_id}.{juan_code}.{seq:05d}", "book_id": spec.book_id, "edition_id": spec.edition_id,
            "seq": seq, "kind": kind, "layer": name, "year": _mid(temporal["t_composition"]),
            "y_start": temporal["t_composition"][0], "y_end": temporal["t_composition"][1],
            "locator": loc, "temporal": temporal, "text": text, "punctuation": "none",
            "extra": {"layer": name, **({"attribution": layer.attribution} if layer and layer.attribution else {}), **extra},
        })
        self.report["layers"][name] = self.report["layers"].get(name, 0) + 1

    def parse(self, repo: Path, start_seq: int = 0) -> list[dict[str, Any]]:
        spec = self.spec
        files = self.files(repo)
        width = modal_width(files)
        threshold = short_threshold(files, width)
        rows: list[dict[str, Any]] = []
        seq = start_seq
        self.report["files"] = len(files)
        self.report["line_width"] = width
        self.report["short_line_threshold"] = round(threshold, 1)
        for f in files:
            stem = f.path.stem
            juan_code = stem.split("_")[-1]
            juan = juan_label(f.props, stem)
            blank_layout = sum(1 for pl in f.lines if pl.blank) > 0.3 * max(1, len(f.lines))
            kind_default = "text"
            front_layer: LayerSpec | None = None
            if "提要" in juan:
                kind_default = "preface"
                y = qianlong_year("".join(pl.raw for pl in f.lines))
                front_layer = LayerSpec("四库提要", (y, y) if y else (1773, 1782), "四库馆臣")
            elif "目錄" in juan or "目录" in juan:
                kind_default = "toc"
            elif "序" in juan or "跋" in juan or "凡例" in juan or juan_code == "000":
                kind_default = "preface"
            if kind_default in ("preface", "toc") and front_layer is None:
                # front matter mixes prefaces by several hands with the contents: dated conservatively by the
                # edition, with the work's date as the date of the material it discusses
                front_layer = LayerSpec("卷首", spec.edition_year or spec.composition, "序、目录等")
            chapter: str | None = None
            section: str | None = None
            section_layer: LayerSpec | None = None
            chapter_layer: LayerSpec | None = None
            heads_seen = 0
            block: dict[str, Any] | None = None
            pending_commentary: list[tuple[LayerSpec, str, dict[str, Any], dict[str, Any]]] = []
            for para in paragraphs(f, spec.note_order, width, threshold):
                self.report["paragraphs"] += 1
                gaiji = list(para.gaiji)
                if is_heading(para, width, blank_layout):
                    seq = self._flush(rows, block, seq, juan_code)
                    block = None
                    seq = self._flush_commentary(rows, pending_commentary, seq, juan_code)
                    self.report["headings"] += 1
                    title = para.main_text().strip(FULL_SPACE + " ︻")
                    heading_notes = [pc.text for pc in para.pieces if pc.kind == "note"]
                    if JUAN_TITLE.search(title) or "欽定四庫全書" in title:
                        continue
                    if FORMULA_HEADING.search(title) and chapter is not None:
                        section = title
                    else:
                        chapter, section = title, None
                        section_layer = None
                        chapter_layer = next((lay for pat, lay in spec.chapter_layers if re.search(pat, title)), None)
                    for pat, lay in spec.section_layers:
                        if re.search(pat, title):
                            section_layer = lay
                    for note in heading_notes:  # notes on a chapter title (e.g. its place in other recensions)
                        for lay, body in self.split_note(note):
                            if lay is not None and body.strip(FULL_SPACE):
                                loc = {"volume": juan, "chapter": chapter, "section": section, "page": para.page,
                                       "line": para.line, "precision": "exact"}
                                self._row(rows, seq, juan_code, "commentary", lay, body.strip(FULL_SPACE), loc,
                                          {"source_file": f.path.name, "anchor": None, "on_heading": title})
                                self.report["commentary_passages"] += 1
                                seq += 1
                    heads_seen += 1
                    continue
                if heads_seen <= 2 and para.lines == 1 and para.indent >= 1 and re.search(r"(撰|註|注|校正|校|編|编|輯|辑|著|述|集|改誤|改误|重訂|重订|訂|订|補|补|刊)$", para.main_text().strip(FULL_SPACE + " ")):
                    continue  # credit line under the 卷 title
                if not blank_layout and para.indent >= 6 and para.lines == 1:
                    continue  # credit lines (撰 / 注 / 校正) set far down the column
                if is_toc_line(para):
                    continue
                if "欽定四庫全書" == para.main_text().strip(FULL_SPACE + " "):
                    continue
                self.report["gaiji"] += len(gaiji)
                kind = kind_default
                layer: LayerSpec | None = front_layer or section_layer or chapter_layer
                citation: tuple[int, int] | None = None
                if spec.mixed is not None and front_layer is None and layer is None:
                    layer, citation = spec.mixed, spec.cites or spec.composition
                if spec.indented_commentary is not None and para.indent >= 1 and front_layer is None:
                    layer, kind, citation = spec.indented_commentary, "commentary", None
                # reading text: main text plus the notes that stay in the main layer; notes with a layer of
                # their own become dated commentary passages anchored to this paragraph
                kept: list[str] = []
                commentary: list[tuple[LayerSpec, str]] = []
                anchors: list[int] = []
                for piece in para.pieces:
                    if piece.kind == "main":
                        kept.append(piece.text)
                        continue
                    self.report["notes"] += 1
                    inline: list[str] = []
                    for lay, body in self.split_note(piece.text):
                        if lay is None or kind == "commentary":
                            inline.append(body)
                        else:
                            commentary.append((lay, body))
                            anchors.append(sum(len(k) for k in kept))
                    if inline:
                        kept.append("（" + "".join(inline) + "）")
                text = "".join(kept).strip(FULL_SPACE + " ")
                loc = {"volume": juan, "chapter": chapter, "section": section, "page": para.page, "line": para.line,
                       "precision": "exact"}
                extra: dict[str, Any] = {"source_file": f.path.name}
                if gaiji:
                    extra["gaiji"] = gaiji
                key = (kind, layer.name if layer else None, chapter, section)
                if (block is not None and block["key"] == key and text and list_like(text)
                        and len(block["text"]) + len(text) < 1500):
                    block["text"] += FULL_SPACE + text  # ingredient list / preparation of the same prescription
                    block["extra"].setdefault("gaiji", []).extend(gaiji)
                    if not block["extra"]["gaiji"]:
                        block["extra"].pop("gaiji")
                    first_id = block["first_id"]
                else:
                    seq = self._flush(rows, block, seq, juan_code)
                    seq = self._flush_commentary(rows, pending_commentary, seq, juan_code)
                    block = None
                    first_id = None
                    if text and text.strip("（）" + FULL_SPACE):
                        block = {"key": key, "kind": kind, "layer": layer, "text": text, "loc": loc, "extra": extra,
                                 "citation": citation, "first_id": f"{spec.book_id}.{juan_code}.{seq:05d}"}
                        first_id = block["first_id"]
                grouped: dict[str, tuple[LayerSpec, list[str]]] = {}
                for lay, body in commentary:
                    grouped.setdefault(lay.name, (lay, []))[1].append(body)
                for name, (lay, bodies) in grouped.items():
                    ctext = FULL_SPACE.join(b.strip(FULL_SPACE) for b in bodies if b.strip(FULL_SPACE))
                    if not ctext:
                        continue
                    pending_commentary.append((lay, ctext, loc, {"source_file": f.path.name, "anchor": first_id}))
            seq = self._flush(rows, block, seq, juan_code)
            seq = self._flush_commentary(rows, pending_commentary, seq, juan_code)
        self.report["passages"] = len(rows)
        return rows

    def _flush(self, rows: list[dict[str, Any]], block: dict[str, Any] | None, seq: int, juan_code: str) -> int:
        if block is None:
            return seq
        text = block["text"]
        for s0, e0 in split_long(text):
            chunk = text[s0:e0]
            if not chunk.strip(FULL_SPACE + " （）"):
                continue
            self._row(rows, seq, juan_code, block["kind"], block["layer"], chunk, block["loc"], block["extra"], block["citation"])
            seq += 1
        return seq

    def _flush_commentary(self, rows: list[dict[str, Any]], pending: list, seq: int, juan_code: str) -> int:
        for lay, ctext, loc, extra in pending:
            for s0, e0 in split_long(ctext):
                self._row(rows, seq, juan_code, "commentary", lay, ctext[s0:e0], loc, extra)
                self.report["commentary_passages"] += 1
                seq += 1
        pending.clear()
        return seq
