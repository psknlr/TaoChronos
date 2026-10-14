"""Readers for the lists of other names of drugs (ADR 0023): the 本草纲目别名录 — store book ``jc_c030`` (CC0 1.0 via
中醫笈成) and its GB18030 copy on GitHub — hurbTable and the NTU table "Large List of Chinese Drug Names 40K".

The 别名录 gives ``head（a1　a2 …）`` per drug: the store's copy one entry per passage, names separated by full-width
spaces; the GitHub copy in the 中医世家 layout (``\\x甘露\\x（膏露 天酒 …）``, ASCII spaces, hard-wrapped at a fixed
width).  Both lost every character outside GB2312 to a blank or ``KT`` and share word-level conversion errors (野狼 for
狼, 浓 for 厚).  So the names next to a blank slot or a ``KT`` are flagged ``lost_char``; one-character tokens (mostly
fragments: 鱼 of 石斑鱼), a name equal to its head and repeats are kept only as dropped tokens; an ``X名Y`` or ``X曰Y``
note (根名茹根, 雌者曰博带) gives Y as a part, processing or variety name; a hard wrap is joined only when the joined
form is attested and its parts are not (flag ``joined``), and its parts are flagged ``wrap`` when it stays unresolved.
Section labels are ignored: the GitHub copy files everything after the herbs under 草部（下）.

hurbTable (scraped from zhongyoo.com) keeps the botanical source in ``Medicinal_Part`` as often as in ``Source`` and
has a few rows shifted by a column; the NTU table comes from Dataverse as an archival ``.tab``, whose escapes Python's
csv module misreads.  Neither may be shipped (hurbTable states no licence, NTU is CC BY-NC 4.0): :func:`import_local`
writes them, and the GitHub copy, under ``<data>/aliases/local/`` with a pin, for local research only.

The readers only read and clean.  Every name goes through the caller's normaliser (the pack's, t2s included); statuses,
witnesses and periods are the build's (``plugins/classics/aliasbuild.py``).  Standard library only.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ....protocol.base import canonical_dumps
from ..store import is_han

BOOK = "jc_c030"  # the 别名录 in the store
# word-level conversion errors of both copies, in normalised spelling (curated.yaml ``repairs`` holds the same)
REPAIRS: tuple[tuple[str, str], ...] = (("野狼", "狼"), ("浓朴", "厚朴"), ("浓皮", "厚皮"))
# ``taochronos aliases import <name>`` → <data>/aliases/local/<name>.jsonl, its rows under the sources.yaml id
LOCAL_SOURCES = {"bielu-gb": "bielu-gb", "hurb": "hurb", "ntu": "ntu40k"}

Normalize = Callable[[str], str]
Pairs = Mapping[str, str] | Iterable[tuple[str, str]] | Iterable[Mapping[str, str]]


# --------------------------------------------------------------------------- what the readers give
@dataclass
class AliasToken:
    """One name a list gives for its head, as written and as cleaned.  A token with ``drop`` set is not a name."""

    text: str  # the slot as written: 根名茹根, 鐵KT, 榜孜多乌(藏药)
    raw: str  # the name's own spelling (the Y of a note), repairs applied
    name: str  # normalised and repaired; "" when nothing is left
    kind: str = "alias"  # alias, or from a note: part_name, processing_variant, variety; hurb's ethnic names: folk
    qualifier: str = ""  # the X of an X名Y note: 根, 小者, 秦
    note: str = ""  # a bracketed note (藏药) or the list's note column
    flags: list[str] = field(default_factory=list)  # lost_char, joined, wrap, truncated, repaired, marks
    drop: str | None = None  # lost, one_char, same_as_head, duplicate


@dataclass
class ListEntry:
    """A head and the names a list gives for it: a 别名录 entry, a hurbTable row, an NTU row."""

    head: str  # normalised and repaired; "" when it was lost
    head_raw: str
    tokens: list[AliasToken] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # lost_head, head_repaired, repaired, no_list, unclosed …
    ref: str = ""  # where: a passage id, "line 190", "row 12"
    info: dict[str, Any] = field(default_factory=dict)  # other cells (hurb: english, source; NTU: all four)

    @property
    def aliases(self) -> list[AliasToken]:
        return [t for t in self.tokens if t.drop is None]


BieluEntry = ListEntry  # an entry of the 别名录


def _identity(text: str) -> str:
    return text


def _pairs(value: Pairs | None, key: str, val: str) -> list[tuple[str, str]]:
    """Pairs given as a mapping, as tuples or as curated.yaml rows ``{key: …, val: …}``."""
    if not value:
        return []
    if isinstance(value, Mapping):
        return list(value.items())
    return [(row[key], row[val]) if isinstance(row, Mapping) else tuple(row) for row in value]


def _repair(raw: str, name: str, repairs: list[tuple[str, str]]) -> tuple[str, str, bool]:
    """Apply the repairs to a normalised name, and to its spelling where the normaliser kept the length."""
    hit = False
    for frm, to in repairs:
        i = name.find(frm)
        while i >= 0:
            if len(raw) == len(name):
                raw = raw[:i] + to + raw[i + len(frm):]
            name = name[:i] + to + name[i + len(frm):]
            hit = True
            i = name.find(frm, i + len(to))
    if hit and len(raw) != len(name):
        raw = name
    return raw, name, hit


def _han(text: str) -> str:
    return "".join(ch for ch in text if is_han(ch))


def _finish(tokens: list[AliasToken], head: str) -> list[AliasToken]:
    """Mark what is not a name: nothing left, one character, the head itself, a repeat (the first one stays)."""
    seen: set[str] = set()
    for t in tokens:
        t.drop = None
        if not t.name:
            t.drop = "lost"
        elif len(t.name) < 2:
            t.drop = "one_char"
        elif t.name == head:
            t.drop = "same_as_head"
        elif t.name in seen:
            t.drop = "duplicate"
        else:
            seen.add(t.name)
    return tokens


def summary(entries: Iterable[ListEntry]) -> dict[str, Any]:
    """Counts for a report: entries, tokens, names kept, tokens dropped by reason, flags on kept names and entries."""
    entries = list(entries)
    tokens = [t for e in entries for t in e.tokens]
    return {
        "entries": len(entries), "tokens": len(tokens), "names": sum(t.drop is None for t in tokens),
        "dropped": _count(t.drop for t in tokens if t.drop), "notes": sum(bool(t.qualifier) for t in tokens),
        "flags": _count(f for t in tokens if t.drop is None for f in t.flags),
        "entry_flags": _count(f for e in entries for f in e.flags),
    }


def _count(keys: Iterable[str | None]) -> dict[str, int]:
    return dict(sorted(Counter(keys).items()))


# --------------------------------------------------------------------------- 本草纲目别名录
_SEP = re.compile("[ \u3000，,、]")  # one separator: two in a row leave a blank slot, a lost character
_OPEN, _CLOSE = "（(", "）)"
_PREFACE = re.compile("有[别別]名者")  # （有别名者录之无别名者未录）
_META = re.compile(r"^(?:书名|書名|作者|朝代|年份|年代)[：:]")
_NOTE = re.compile(r"(.{1,8}?)([名曰])(.+)")
_NAMED = ("无名", "無名", "天名")  # names with 名 in them (无名子, 天名精), not notes
_PARTS = set("根苗子实實花叶葉茎莖皮木树樹笋筍母膏骨壳殼厣厴屎核仁蕊须鬚心汁角甲肉乳脂胆膽毛尾粉霜油蒂枝")
_PROCESSED = re.compile("[炼煉酿釀煎制製炙炒煅枯干乾腊臘胶膠]")  # 炼者名砒霜, 法酿过名百药煎, 干者名鲞鱼, 作胶名鳔


def _note_kind(q: str) -> str:
    """The kind a note's qualifier gives its name: 根名茹根 a part, 炼者名砒霜 a processed form, 秦名乌韭 or 小者名苦 a
    variety (产地 or 品种)."""
    if _PROCESSED.search(q):
        return "processing_variant"
    if q in _PARTS or (len(q) == 2 and q[-1] in _PARTS):  # 抱根名茯神
        return "part_name"
    return "variety"


class _Bielu:
    """The cleaning one 别名录 entry goes through."""

    def __init__(self, normalize: Normalize | None, attested: Callable[[str], bool] | None, repairs: Pairs | None):
        self.normalize = normalize or _identity
        self.attested = attested
        self.repairs = [(self.normalize(a), self.normalize(b)) for a, b in _pairs(repairs, "from", "to")]

    def form(self, slot: str) -> str:
        """The name a slot gives (the Y of a note), as attestation is asked about it."""
        return self.token(slot, []).name

    def stands(self, slot: str) -> bool:
        """Whether a slot is a name by itself: two characters or more, undamaged, attested."""
        name = self.form(slot)
        return bool(self.attested) and "KT" not in slot and len(name) >= 2 and self.attested(name)

    def entry(self, lines: list[str], gb: bool, ref: str) -> ListEntry:
        first = lines[0]
        body = first[2:] if gb else first  # \x head \x （…）, the closing \x missing once (仲思枣)
        end = body.find("\\x") if gb else -1
        cut = end if end >= 0 else _cut(body)
        head_raw, rest = body[:cut], body[cut + 2 if end >= 0 else cut:]
        flags: list[str] = []
        head = ""
        if not head_raw.strip(" \u3000") or "KT" in head_raw or _SEP.search(head_raw):
            flags.append("lost_head")  # 「 石」 for 礜石, 「荠 」 for 荠苨, an empty head
        else:
            _, head, hit = _repair(head_raw, self.normalize(_han(head_raw)), self.repairs)
            if hit:
                flags.append("repaired")
        text = "\n".join([rest, *lines[1:]]).lstrip(" \u3000")
        segments: list[str] = []
        if text.startswith(tuple(_OPEN)):
            inner = text[1:]
            close = max(inner.rfind(c) for c in _CLOSE)
            if close < 0:
                flags.append("unclosed")
            segments = (inner[:close] if close >= 0 else inner).split("\n")
        elif text.strip():
            flags.append("unbracketed")  # \x石南藤\x丁公寄
            segments = text.split("\n")
        else:
            flags.append("no_list")
        return ListEntry(head, head_raw, _finish(self.tokens(segments), head), flags, ref)

    def tokens(self, segments: list[str]) -> list[AliasToken]:
        slots: list[str] = []
        marks: list[set[str]] = []
        wraps: list[int] = []  # a slot that starts a new physical line right after a name
        for k, seg in enumerate(segments):
            parts = _SEP.split(seg)
            if k and slots and slots[-1] and parts[0]:
                wraps.append(len(slots))
            slots.extend(parts)
            marks.extend(set() for _ in parts)
        for i in reversed(wraps):  # 野|生姜 is one name, 子芩|尾芩 two
            left, right = slots[i - 1], slots[i]
            fragment = len(self.form(left)) < 2 or len(self.form(right)) < 2  # never a name by itself
            alone = self.stands(left), self.stands(right)
            if self.attested and (fragment or not any(alone)) and self.attested(self.form(left + right)):
                slots[i - 1: i + 1] = [left + right]
                marks[i - 1: i + 1] = [marks[i - 1] | marks[i] | {"joined"}]
            elif not all(alone):
                marks[i - 1].add("wrap")
                marks[i].add("wrap")
        for i, slot in enumerate(slots):  # a blank slot or a KT damages the names on both sides
            if not slot or "KT" in slot:
                for j in (i - 1, i, i + 1):
                    if 0 <= j < len(slots) and slots[j]:
                        marks[j].add("lost_char")
        return [self.token(slot, sorted(mark)) for slot, mark in zip(slots, marks) if slot]

    def token(self, slot: str, flags: list[str]) -> AliasToken:
        clean = slot.replace("KT", "")
        written = _han(clean)
        if written != clean:  # a stray bracket: 蕨（
            flags = sorted({*flags, "lost_char"})
        qualifier, kind, raw = "", "alias", written
        m = None if written.startswith(_NAMED) else _NOTE.fullmatch(written)
        if m:
            qualifier, raw = m.group(1), m.group(3)
            if qualifier == "者":  # 者名绛矾: what it is the name of was lost
                flags = sorted({*flags, "truncated"})
        elif len(written) >= 2 and written[-1] in "名曰" and not written.startswith(_NAMED):
            qualifier, raw = written[:-1], ""  # 雄者名|: the name was lost
            flags = sorted({*flags, "truncated"})
        elif len(written) >= 2 and written[0] in "名曰":
            raw = written[1:]  # 曰糜, 名螵蛸: the qualifier was lost
            flags = sorted({*flags, "truncated"})
        if qualifier:
            qualifier = self.normalize(qualifier)
            kind = _note_kind(qualifier)
        raw, name, hit = _repair(raw, self.normalize(raw), self.repairs)
        if hit:
            flags = sorted({*flags, "repaired"})
        return AliasToken(slot, raw, name, kind, qualifier, flags=flags)


def _cut(text: str) -> int:
    """Where the list starts: the first opening bracket, or the end."""
    found = [i for i in (text.find(c) for c in _OPEN) if i >= 0]
    return min(found) if found else len(text)


def parse_bielu(text: str, *, normalize: Normalize | None = None, attested: Callable[[str], bool] | None = None,
                repairs: Pairs | None = REPAIRS) -> list[ListEntry]:
    """Entries of the 别名录 in text, one ``head（a1　a2 …）`` per line, or the GitHub copy's ``\\x head \\x（…）`` with
    its hard wraps and its title, metadata and section lines.  ``attested(name)`` (a normalised name → whether the
    corpus has it) decides the wraps; without it none is joined.  Each entry's ``ref`` is its line number."""
    bielu = _Bielu(normalize, attested, repairs)
    gb = "\\x" in text
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    for no, line in enumerate(text.splitlines(), 1):
        if gb and line.endswith(" "):
            line = line[:-1]  # every line of the GitHub copy ends with a space
        if line.startswith(("内容：", "內容：")):
            line = line[3:]
        if not line.strip(" \u3000") or line.startswith("<") or _META.match(line) or _PREFACE.search(line):
            current = None
        elif not gb or line.startswith("\\x"):
            current = [line]
            blocks.append((no, current))
        elif current is not None:
            current.append(line)  # a hard wrap
    return [bielu.entry(lines, gb, f"line {no}") for no, lines in blocks]


def read_bielu_gb(path: Path | str, *, encoding: str | None = None, normalize: Normalize | None = None,
                  attested: Callable[[str], bool] | None = None, repairs: Pairs | None = REPAIRS) -> list[ListEntry]:
    """The GitHub copy of the 别名录 (GB18030, or its UTF-8 decoding).  Local only: the repository states no licence."""
    data = Path(path).read_bytes()
    if encoding:
        text = data.decode(encoding)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
    return parse_bielu(text, normalize=normalize, attested=attested, repairs=repairs)


def read_bielu_store(store: Any, *, normalize: Normalize | None = None, attested: Callable[[str], bool] | None = None,
                     repairs: Pairs | None = REPAIRS, head_repairs: Pairs | None = None,
                     book: str = BOOK) -> list[ListEntry]:
    """The 别名录 passages of a store (a ``StoreCorpus`` that does not leave the book out, or passages or their dicts,
    e.g. read from ``corpus/web/passages.jsonl.gz``), in passage order; each entry's ``ref`` is its passage id.
    ``head_repairs`` (passage id → head, or curated.yaml rows ``{passage, head}``) gives back the heads the
    transcription lost or ran together (仲思棗　杏)."""
    bielu = _Bielu(normalize, attested, repairs)
    heads = dict(_pairs(head_repairs, "passage", "head"))
    rows = store.iter_passages(book_ids=[book]) if hasattr(store, "iter_passages") else store
    passages = []
    for p in rows:
        pid, bid, text = (p["id"], p["book_id"], p["text"]) if isinstance(p, Mapping) else (p.id, p.book_id, p.text)
        if bid == book and text and not _PREFACE.search(text):
            passages.append((pid, text))
    out = []
    for pid, text in sorted(passages):
        e = bielu.entry([text], False, pid)
        if pid in heads:
            e.head = _repair(heads[pid], bielu.normalize(heads[pid]), bielu.repairs)[1]
            e.flags = [f for f in e.flags if f != "lost_head"] + ["head_repaired"]
            _finish(e.tokens, e.head)
        out.append(e)
    return out


# --------------------------------------------------------------------------- hurbTable
_HURB_SEP = re.compile("[、，,；; \u3000]")
_BRACKET_NOTE = re.compile(r"(.*?)[（(]([^（）()]*)[）)]")
_NONE = re.compile(r"^(?:无|暂缺|暂无|不详|尚不明确)。?$")
_SOURCE = re.compile(r"科(?:植物|动物|真菌|昆虫)|矿石|矿物|加工品|炮制品|的(?:干燥|新鲜)?[^。]{0,14}?"
                     r"(?:根|茎|叶|果|种子|全草|全株|花|皮|树脂|分泌物|子实体|菌核|虫体|贝壳|角|骨|全体)")
_NAME_LIST = re.compile("[\u3400-\u9fff、，,；; \u3000。]+")


def _latin(cell: str) -> bool:
    return not _han(cell) and re.search("[A-Za-z]{3}", cell) is not None


def _realign(rec: dict[str, str]) -> list[str]:
    """Put hurbTable's shifted cells back (alias, english, part, source), in place; the repairs it made."""
    done = []
    if any(_NONE.match(rec[key]) for key in ("alias", "english")):  # 无。 暂缺。
        rec.update({key: "" for key in ("alias", "english") if _NONE.match(rec[key])})
        done.append("none_word")
    if _latin(rec["alias"]):  # 茜草, 槐花, 冬虫夏草, 草乌: the Latin name in Alias
        rec["english"], rec["alias"] = rec["english"] or rec["alias"], ""
        done.append("latin_in_alias")
    if not rec["alias"] and rec["part"] and _NAME_LIST.fullmatch(rec["part"]) and not _SOURCE.search(rec["part"]):
        rec["alias"], rec["part"] = rec["part"], ""  # 丁公藤: the names in Medicinal_Part
        done.append("aliases_in_part")
    if _han(rec["english"]) and _SOURCE.search(rec["english"]):  # 东风橘: the source in English_Name, the Latin in Source
        if not rec["source"]:
            rec["source"], rec["english"] = rec["english"], ""
        elif _latin(rec["source"]):
            rec["source"], rec["english"] = rec["english"], rec["source"]
        done.append("source_in_english")
    if rec["part"] and not rec["source"]:  # Medicinal_Part holds the 来源 in most rows
        rec["source"], rec["part"] = rec["part"], ""
        done.append("source_in_part")
    return done


def _name_tokens(cell: str, sep: re.Pattern[str], normalize: Normalize, note_kind: str) -> list[AliasToken]:
    """Names of a table cell: split, 。 and quotes stripped, a bracketed note (藏药) kept as the token's note."""
    out = []
    for text in sep.split(cell.strip().rstrip("。.")):
        text = text.strip(" \u3000。“”\"'")
        if not text:
            continue
        m = _BRACKET_NOTE.fullmatch(text)
        written, note = (m.group(1), m.group(2).strip()) if m else (text, "")
        raw = _han(written)
        flags = ["marks"] if raw != written else []
        out.append(AliasToken(text, raw, normalize(raw), note_kind if note else "alias", note=note, flags=flags))
    return out


def read_hurb(path: Path | str, *, normalize: Normalize | None = None, encoding: str | None = None) -> list[ListEntry]:
    """hurbTable.csv, one entry per row, its cells realigned.  Local only: no data licence is stated."""
    normalize = normalize or _identity
    with open(path, encoding=encoding or "utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    col = {name.strip(): i for i, name in enumerate(rows[0])}
    need = {"name": "Name", "medicine": "Medicine_Name", "alias": "Alias", "english": "English_Name",
            "part": "Medicinal_Part", "source": "Source"}
    missing = [c for c in need.values() if c not in col]
    if missing:
        raise ValueError(f"{Path(path).name}: no {', '.join(missing)} column; the header is {rows[0]!r}")
    out = []
    for n, row in enumerate(rows[1:], 1):
        rec = {key: row[col[c]].strip() if col[c] < len(row) else "" for key, c in need.items()}
        flags = _realign(rec)
        head_raw = rec["name"] or re.match(r"[\u3400-\u9fff]*", html.unescape(rec["medicine"]).strip()).group(0)
        head = normalize(_han(head_raw))
        tokens = _name_tokens(rec["alias"], _HURB_SEP, normalize, "folk")  # 榜孜多乌(藏药)
        out.append(ListEntry(head, head_raw, _finish(tokens, head), flags, f"row {n}",
                             {"english": rec["english"], "source": rec["source"]}))
    return out


# --------------------------------------------------------------------------- NTU 40K
_NTU_SEP = re.compile("[、，,；;]")
_NTU_COLUMNS = (("primary", re.compile("primary|主名", re.I)), ("alternate", re.compile("alternate|别名|別名", re.I)),
                ("attribution", re.compile("attribution|出处|出處", re.I)), ("note", re.compile("note", re.I)))
_NTU_ORDER = (".tab", ".tsv", ".csv")
_UNESCAPE = re.compile(r'\\(["nt])')


def table_file(path: Path | str) -> tuple[str, bytes]:
    """The table a download holds, as (file name, bytes): the file itself, or the member of a Dataverse zip chosen by
    extension (``.tab``, then ``.tsv``, then ``.csv``; ``MANIFEST.TXT`` skipped).  An Excel file is refused."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        raise ValueError(f"{path.name}: an Excel workbook; export it as CSV (UTF-8) and import that")
    if ext in _NTU_ORDER:
        return path.name, path.read_bytes()
    if ext != ".zip":
        raise ValueError(f"{path.name}: not a .tab, .tsv, .csv or Dataverse .zip")
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if not i.is_dir() and Path(i.filename).name.upper() != "MANIFEST.TXT"]
        for want in _NTU_ORDER:
            found = sorted((i for i in members if i.filename.lower().endswith(want)), key=lambda i: i.filename)
            if len(found) > 1:
                raise ValueError(f"{path.name}: several {want} tables: {', '.join(i.filename for i in found)}")
            if found:
                return Path(found[0].filename).name, z.read(found[0])
    names = ", ".join(i.filename for i in members) or "nothing"
    excel = any(i.filename.lower().endswith((".xlsx", ".xls")) for i in members)
    hint = "; export the workbook as CSV" if excel else ""
    raise ValueError(f"{path.name}: no .tab, .tsv or .csv table in the zip (it holds {names}){hint}")


def _tab_cell(cell: str) -> str | None:
    """A cell of a Dataverse archival ``.tab``: a quoted string with ``\\"``, ``\\n`` and ``\\t`` escaped; an empty
    cell is a missing value (None), ``""`` an empty string."""
    if len(cell) >= 2 and cell[0] == cell[-1] == '"':
        return _UNESCAPE.sub(lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), cell[1:-1])
    return cell or None


def parse_tab(text: str) -> tuple[list[str], list[list[str | None]]]:
    """Header and rows of a Dataverse archival ``.tab``, read cell by cell (the csv module reads ``\\n`` as ``n`` and
    cannot tell a missing value from an empty string)."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    if not lines or not lines[0]:
        return [], []
    header = [_tab_cell(c) or "" for c in lines[0].split("\t")]
    return header, [[_tab_cell(c) for c in line.split("\t")] for line in lines[1:] if line]


def _ntu_columns(header: list[str], name: str) -> dict[str, int]:
    cols: dict[str, int] = {}
    for role, pattern in _NTU_COLUMNS:
        for i, h in enumerate(header):
            if i not in cols.values() and pattern.search(h):
                cols[role] = i
                break
    missing = [role for role in ("primary", "alternate") if role not in cols]
    if missing:
        raise ValueError(f"{name}: no {' or '.join(missing)} name column; the header is {header!r} (expected names "
                         f"such as Primary/主名, Alternate/别名, Attribution/出处, Note)")
    return cols


def read_ntu(path: Path | str, *, normalize: Normalize | None = None, encoding: str | None = None) -> list[ListEntry]:
    """The NTU "Large List of Chinese Drug Names 40K" (doi:10.21979/N9/V2XBOH, CC BY-NC 4.0): a Dataverse ``.tab`` (or
    the zip holding it), or a ``.csv``/``.tsv``; one entry per row, the columns found by name.  ``info`` keeps the four
    cells as read: None for a missing value (in a ``.csv``/``.tsv``, any empty cell), "" for an empty string.  Local
    only."""
    return _ntu_entries(*table_file(path), normalize=normalize or _identity, encoding=encoding or "utf-8-sig")


def _ntu_entries(name: str, data: bytes, *, normalize: Normalize, encoding: str) -> list[ListEntry]:
    text = data.decode(encoding)
    if name.lower().endswith(".tab"):
        header, rows = parse_tab(text)
    else:
        delimiter = "\t" if name.lower().endswith(".tsv") else ","
        table = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
        header, rows = (table[0] if table else []), [[c or None for c in r] for r in table[1:] if r]
    cols = _ntu_columns([h.strip() for h in header], name)
    out = []
    for n, row in enumerate(rows, 1):
        cells = {role: row[i] if i < len(row) else None for role, i in cols.items()}
        head_raw = (cells["primary"] or "").strip()
        head = normalize(_han(re.sub(r"[（(][^（）()]*[）)]", "", head_raw)))
        alternate = cells["alternate"]
        flags = ["no_head"] if not head else []
        if alternate is None:
            flags.append("missing")
        elif not alternate.strip():
            flags.append("empty")
        tokens = _name_tokens(alternate or "", _NTU_SEP, normalize, "alias")
        out.append(ListEntry(head, head_raw, _finish(tokens, head), flags, f"row {n}",
                             {role: cells.get(role) for role in ("primary", "alternate", "attribution", "note")}))
    return out


# --------------------------------------------------------------------------- the local layer
def local_rows(entries: Iterable[ListEntry], source: str) -> list[dict[str, Any]]:
    """The (head, name) pairs of the entries as ``<data>/aliases/local/<source>.jsonl`` keeps them: one per kept name
    of an entry with a head; ``raw k q nt at fl`` only when they say something."""
    out = []
    for e in entries:
        if not e.head:
            continue
        for t in e.aliases:
            row: dict[str, Any] = {"h": e.head, "s": t.name, "src": source, "ref": e.ref}
            extra = {"raw": t.raw if t.raw != t.name else "", "k": t.kind if t.kind != "alias" else "",
                     "q": t.qualifier, "nt": t.note or e.info.get("note") or "", "at": e.info.get("attribution") or "",
                     "fl": t.flags}
            row.update({k: v for k, v in extra.items() if v})
            out.append(row)
    return out


def import_local(source: str, path: Path | str, out_dir: Path | str, *, normalize: Normalize | None = None,
                 encoding: str | None = None, attested: Callable[[str], bool] | None = None,
                 repairs: Pairs | None = REPAIRS, licence: str = "", attribution: str = "",
                 pin: Mapping[str, Any] | None = None, imported: str | None = None) -> dict[str, Any]:
    """Read a local list (``bielu-gb``, ``hurb`` or ``ntu``), write its pairs to ``<out_dir>/<source>.jsonl`` under
    the source's id in sources.yaml, and record it in ``<out_dir>/manifest.json``: the table's file, sha256, bytes and
    rows, the pairs written, licence, attribution, the date, and warnings where it differs from the pin (``{file,
    rows, sha256}`` of sources.yaml).  Returns that manifest entry."""
    if source not in LOCAL_SOURCES:
        raise ValueError(f"unknown local alias source {source!r}; expected one of {', '.join(LOCAL_SOURCES)}")
    path = Path(path)
    name, data = table_file(path) if source == "ntu" else (path.name, path.read_bytes())
    if source == "ntu":
        entries = _ntu_entries(name, data, normalize=normalize or _identity, encoding=encoding or "utf-8-sig")
    elif source == "hurb":
        entries = read_hurb(path, normalize=normalize, encoding=encoding)
    else:
        entries = read_bielu_gb(path, encoding=encoding, normalize=normalize, attested=attested, repairs=repairs)
    rows = local_rows(entries, LOCAL_SOURCES[source])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{source}.jsonl").write_bytes("".join(canonical_dumps(r) + "\n" for r in rows).encode("utf-8"))
    entry: dict[str, Any] = {"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                             "rows": len(entries), "pairs": len(rows), "licence": licence, "attribution": attribution,
                             "imported": imported or date.today().isoformat()}
    if name != path.name:
        entry["from"] = path.name
    warnings = []
    for key in ("file", "rows", "sha256"):
        if pin and pin.get(key) is not None and pin[key] != entry[key]:
            warnings.append(f"{key} {entry[key]} differs from the pinned {pin[key]}")
    if warnings:
        entry["warnings"] = warnings
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest[source] = entry
    text = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    manifest_path.write_text(text, encoding="utf-8")
    return entry
