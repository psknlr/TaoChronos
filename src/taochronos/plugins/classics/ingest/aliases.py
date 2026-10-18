"""Readers for the lists of other names of drugs (ADR 0023): the 本草纲目别名录 — store book ``jc_c030`` (CC0 1.0 via
中醫笈成) and its GB18030 copy on GitHub — hurbTable and the NTU table "Large List of Chinese Drug Names 40K".

The 别名录 gives ``head（a1　a2 …）`` per drug: the store's copy one entry per passage, names separated by full-width
spaces; the GitHub copy in the 中医世家 layout (``\\x甘露\\x（膏露 天酒 …）``, ASCII spaces, hard-wrapped at a fixed
width).  Both lost every character outside GB2312 to a blank or ``KT`` and share word-level conversion errors (野狼 for
狼, 浓 for 厚).  So the names next to a blank slot or a ``KT``, and a name holding a lost-character mark (〓 □ ■, kept
as 〓 so that its neighbours never run together into another name), are flagged ``lost_char``; one-character tokens
(mostly fragments: 鱼 of 石斑鱼), a name equal to its head and repeats are kept only as dropped tokens; an ``X名Y`` or
``X曰Y`` note (根名茹根, 雌者曰博带) gives Y as a part, processing or variety name; a hard wrap is joined only when the
joined form is attested and its parts are not (flag ``joined``), and its parts are flagged ``wrap`` unless they are two
attested names whose join is not (天精|地节).  Section labels are ignored: the GitHub copy files everything after the
herbs under 草部（下）.

hurbTable (scraped from zhongyoo.com) keeps the botanical source in ``Medicinal_Part`` as often as in ``Source`` and
has a few rows shifted by a column; it states no licence, and neither does the GitHub copy of the 别名录:
:func:`import_local` writes them under ``<data>/aliases/local/`` with a pin, for local research only.

The NTU table (CC BY-NC 4.0) comes as an Excel workbook, which a standard-library reader reads, or from Dataverse as an
archival ``.tab``, whose escapes Python's csv module misreads.  Its Remarks name the books a name is cited from, a
place, an ethnic language (a folk name in it) or a person (:func:`parse_remark`); its names write a character the
GB2312 set lacked by its parts in brackets (鸡（土从）) or in pinyin (水麻tiao), read as a lost character, never as 鸡 or
水麻.  By IMPF-AI's decision of 2026-10-18 it is published, credited, as the committed extract
``corpus/aliases/ntu40k.tsv`` (:func:`publish_ntu`, ``taochronos aliases import ntu FILE --publish``), which
:func:`read_ntu` reads like the original; :func:`import_local` still writes its pairs for the local layer.

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
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from xml.etree import ElementTree as ET

from ....protocol.base import canonical_dumps
from ..store import CorpusStore, is_han

BOOK = "jc_c030"  # the 别名录 in the store
# word-level conversion errors of both copies, in normalised spelling (curated.yaml ``repairs`` holds the same, and a
# test holds the two equal)
REPAIRS: tuple[tuple[str, str], ...] = (("野狼", "狼"), ("浓朴", "厚朴"), ("浓皮", "厚皮"))
# ``taochronos aliases import <name>`` → <data>/aliases/local/<name>.jsonl, its rows under the sources.yaml id
LOCAL_SOURCES = {"bielu-gb": "bielu-gb", "hurb": "hurb", "ntu": "ntu40k"}
# token flags that leave a name in doubt: the build makes such a pair a candidate (ADR 0023, status rule 4)
DOUBT_FLAGS = frozenset({"lost_char", "joined", "truncated", "wrap", "marks"})
_LOST = re.compile("[〓□■]")  # a lost-character mark; the readers keep it as 〓

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
    flags: list[str] = field(default_factory=list)  # lost_char, joined, wrap, truncated, marks (DOUBT_FLAGS), repaired
    drop: str | None = None  # lost, one_char, same_as_head, duplicate


@dataclass
class ListEntry:
    """A head and the names a list gives for it: a 别名录 entry, a hurbTable row, an NTU row."""

    head: str  # normalised and repaired; "" when it was lost
    head_raw: str
    tokens: list[AliasToken] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # lost_head, head_repaired, repaired, no_list, unclosed, no_head …
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


def _decode(data: bytes, encoding: str | None, name: str) -> str:
    """A downloaded file's text: in the encoding given, else UTF-8 (a BOM allowed), else GB18030 (the GB 别名录, and
    a CSV saved by Excel on a Chinese Windows)."""
    for enc in [encoding] if encoding else ["utf-8-sig", "gb18030"]:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    tried = encoding or "UTF-8 or GB18030"
    raise ValueError(f"{name}: not {tried} text; pass the file's encoding (--encoding)")


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
        if not head_raw.strip(" \u3000") or "KT" in head_raw or _SEP.search(head_raw) or _LOST.search(head_raw):
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
        for i in reversed(wraps):  # 野|生姜 is one name, 天精|地节 two, 七叶|一枝花 either as far as the corpus tells
            left, right = slots[i - 1], slots[i]
            fragment = len(self.form(left)) < 2 or len(self.form(right)) < 2  # never a name by itself
            alone = self.stands(left), self.stands(right)
            whole = bool(self.attested) and self.attested(self.form(left + right))
            if whole and (fragment or not any(alone)):
                slots[i - 1: i + 1] = [left + right]
                marks[i - 1: i + 1] = [marks[i - 1] | marks[i] | {"joined"}]
            elif whole or not all(alone):
                marks[i - 1].add("wrap")
                marks[i].add("wrap")
        for i, slot in enumerate(slots):  # a blank slot or a KT damages the names on both sides
            if not slot or "KT" in slot:
                for j in (i - 1, i, i + 1):
                    if 0 <= j < len(slots) and slots[j]:
                        marks[j].add("lost_char")
        return [self.token(slot, sorted(mark)) for slot, mark in zip(slots, marks) if slot]

    def token(self, slot: str, flags: list[str]) -> AliasToken:
        clean = _LOST.sub("〓", slot.replace("KT", ""))
        written = _han(clean)
        if written != clean or "〓" in written:  # a stray bracket (蕨（), a lost-character mark
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
    corpus has it) decides the wraps; without it none is joined.  It must not read the 别名录 itself (store book
    ``jc_c030``, whose names run together once the spaces are normalised away: 猴菽草乌饭草).  Each entry's ``ref`` is
    its line number."""
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
    text = _decode(Path(path).read_bytes(), encoding, Path(path).name)
    return parse_bielu(text, normalize=normalize, attested=attested, repairs=repairs)


def read_bielu_store(store: Any, *, normalize: Normalize | None = None, attested: Callable[[str], bool] | None = None,
                     repairs: Pairs | None = REPAIRS, head_repairs: Pairs | None = None,
                     book: str = BOOK) -> list[ListEntry]:
    """The 别名录 passages of a store (a ``CorpusStore``, a ``StoreCorpus`` that keeps the book, or passages or their
    dicts, e.g. read from ``corpus/web/passages.jsonl.gz``), in passage order; each entry's ``ref`` is its passage id.
    ``head_repairs`` (passage id → head, or curated.yaml rows ``{passage, head}``) gives back the heads the
    transcription lost or ran together (仲思棗　杏).  Raises ValueError when the store has none of the book's entries,
    or lacks a passage ``head_repairs`` names — unless the store is the web edition, an excerpt (778 of the 1,086
    entries) that lacks some by design: compare the ids with the entries' refs to report those."""
    bielu = _Bielu(normalize, attested, repairs)
    heads = dict(_pairs(head_repairs, "passage", "head"))
    passages = []
    for p in _book_rows(store, book):
        pid, bid, text = (p["id"], p["book_id"], p["text"]) if isinstance(p, Mapping) else (p.id, p.book_id, p.text)
        if bid == book and text and not _PREFACE.search(text):
            passages.append((pid, text))
    if not passages:
        raise ValueError(f"the store has no {book} (本草纲目别名录) entries")
    absent = sorted(set(heads) - {pid for pid, _ in passages})
    if absent and _edition(store) != "web":
        raise ValueError(f"head_repairs name passages the store lacks: {', '.join(absent)}")
    out = []
    for pid, text in sorted(passages):
        e = bielu.entry([text], False, pid)
        if pid in heads:
            e.head = _repair(heads[pid], bielu.normalize(heads[pid]), bielu.repairs)[1]
            e.flags = [f for f in e.flags if f != "lost_head"] + ["head_repaired"]
            _finish(e.tokens, e.head)
        out.append(e)
    return out


def _book_rows(store: Any, book: str) -> Iterable[Any]:
    if isinstance(store, CorpusStore):
        with store.lock:
            rows = store.db.execute("SELECT id, book_id, text FROM passages WHERE book_id=?", (book,)).fetchall()
        return [{"id": pid, "book_id": bid, "text": text} for pid, bid, text in rows]
    if hasattr(store, "iter_passages"):
        if book in getattr(store, "exclude_books", ()):
            raise ValueError(f"the corpus leaves {book} out; pass the store, or a corpus that keeps the book")
        return store.iter_passages(book_ids=[book])
    return store


def _edition(store: Any) -> str | None:
    """``web`` for the store of the published site, an excerpt; None for passages handed over as such."""
    if isinstance(store, CorpusStore):
        return store.meta("edition") or "full"
    return getattr(store, "edition", None)


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
    """Names of a table cell: split, 。 and quotes stripped, a bracketed note (藏药) kept as the token's note.  Other
    marks are dropped (flag ``marks``), but one inside a name, or a lost-character mark, makes it ``lost_char``: 山□葡萄
    is not 山葡萄."""
    out = []
    for text in sep.split(cell.strip().rstrip("。.")):
        text = text.strip(" \u3000。“”\"'")
        if text:
            out.append(_name_token(text, normalize, note_kind))
    return out


def _name_token(text: str, normalize: Normalize, note_kind: str) -> AliasToken:
    m = _BRACKET_NOTE.fullmatch(text)
    written, note = (m.group(1), m.group(2).strip()) if m else (text, "")
    written = _LOST.sub("〓", written)
    raw = _han(written)
    han = [i for i, ch in enumerate(written) if is_han(ch)]
    inner = written[han[0]: han[-1] + 1] if han else ""
    flags = ["lost_char"] if "〓" in raw or _han(inner) != inner else ["marks"] if raw != written else []
    return AliasToken(text, raw, normalize(raw), note_kind if note else "alias", note=note, flags=flags)


def _table_head(raw: str, normalize: Normalize) -> str:
    """A table row's head, a bracketed note dropped; "" when a character of it was lost."""
    return "" if _LOST.search(raw) else normalize(_han(re.sub(r"[（(][^（）()]*[）)]", "", raw)))


def read_hurb(path: Path | str, *, normalize: Normalize | None = None, encoding: str | None = None) -> list[ListEntry]:
    """hurbTable.csv, one entry per row, its cells realigned.  Local only: no data licence is stated."""
    normalize = normalize or _identity
    rows = list(csv.reader(io.StringIO(_decode(Path(path).read_bytes(), encoding, Path(path).name), newline="")))
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
        head = _table_head(head_raw, normalize)
        if head_raw and not head:
            flags.append("lost_head")
        tokens = _name_tokens(rec["alias"], _HURB_SEP, normalize, "folk")  # 榜孜多乌(藏药)
        out.append(ListEntry(head, head_raw, _finish(tokens, head), flags, f"row {n}",
                             {"english": rec["english"], "source": rec["source"]}))
    return out


# --------------------------------------------------------------------------- NTU 40K
# The dataset as the committed extract credits it; sources.yaml's ``ntu40k`` entry gives the same DOI and licence (a
# test holds them equal).  The citation's author order and version are as search results gave them, not yet checked.
NTU: dict[str, str] = {
    "id": "ntu40k",
    "title": "Large List of Chinese Drug Names 40K",
    "doi": "10.21979/N9/V2XBOH",
    "publisher": "DR-NTU (Data), Nanyang Technological University",
    "licence": "CC BY-NC 4.0",
    "licence_uri": "https://creativecommons.org/licenses/by-nc/4.0/",
    "citation": 'Chong, William Eng Keat; Stanley-Baker, Michael, 2019, "Large List of Chinese Drug Names 40K", '
                "https://doi.org/10.21979/N9/V2XBOH, DR-NTU (Data), V1",
    "unverified": "author order and version unverified: confirm them with the Cite button of the dataset's page",
}
NTU_EXTRACT = "corpus/aliases/ntu40k.tsv"  # the committed extract, relative to the home
# a row's cells by role; the header names each column (compared without case, spaces or punctuation)
NTU_COLUMNS = ("number", "primary", "dictionary", "alternate", "remarks")
_NTU_HEADERS = {
    "number": {"primarydrugnameno", "number", "no", "编号", "序号"},
    "primary": {"primarydrugname", "primaryname", "primary", "主名", "正名"},
    "dictionary": {"dictionarysource", "dictionary", "出处", "出處"},
    "alternate": {"alternatename", "alternate", "别名", "別名"},
    "remarks": {"remarks", "remark", "notes", "note", "备注", "備註", "備注"},
}
_NTU_ORDER = (".tab", ".tsv", ".csv", ".xlsx")  # a Dataverse zip's table: the archival .tab before the original
_NTU_SEP = re.compile("[、，,；;.．]")  # 无针乌贼.金乌贼: two names
_UNESCAPE = re.compile(r'\\(["nt])')
_HAN_CLASS = "\u3400-\u9fff\uf900-\ufaff\U00020000-\U0003134f"
_OPENERS, _CLOSERS = "（(［[【", "）)］]】"


def table_file(path: Path | str) -> tuple[str, bytes]:
    """The table a download holds, as (file name, bytes): the file itself (``.xlsx``, ``.tab``, ``.tsv``, ``.csv``), or
    the member of a Dataverse zip chosen by extension (``.tab``, then ``.tsv``, ``.csv``, ``.xlsx``; ``MANIFEST.TXT``
    skipped).  An Excel 97–2003 workbook (``.xls``) is refused."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".xls":
        raise ValueError(f"{path.name}: an Excel 97-2003 workbook; save it as .xlsx and import that")
    if ext in _NTU_ORDER or ext == ".xlsm":
        return path.name, path.read_bytes()
    if ext != ".zip":
        raise ValueError(f"{path.name}: not an .xlsx, .tab, .tsv, .csv or Dataverse .zip")
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if not i.is_dir() and Path(i.filename).name.upper() != "MANIFEST.TXT"]
        for want in _NTU_ORDER:
            found = sorted((i for i in members if i.filename.lower().endswith(want)), key=lambda i: i.filename)
            if len(found) > 1:
                raise ValueError(f"{path.name}: several {want} tables: {', '.join(i.filename for i in found)}")
            if found:
                return Path(found[0].filename).name, z.read(found[0])
    names = ", ".join(i.filename for i in members) or "nothing"
    hint = "; save the workbook as .xlsx" if any(i.filename.lower().endswith(".xls") for i in members) else ""
    raise ValueError(f"{path.name}: no .tab, .tsv, .csv or .xlsx table in the zip (it holds {names}){hint}")


# ----------------------------------------------------- the files: a Dataverse .tab, an Excel workbook, the extract
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


_XL_ESCAPE = re.compile("_x([0-9A-Fa-f]{4})_")  # how a workbook writes a control character: _x000D_ (_x005F_ is "_")
_XL_REF = re.compile("([A-Z]{1,3})")
_XL_PART_MAX = 256 * 1024 * 1024  # no part of a real workbook is this large unpacked (a zip bomb is)


def _xl_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xl_part(z: zipfile.ZipFile, name: str, what: str) -> Any:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _XL_PART_MAX:
        raise ValueError(f"{what}: {name} unpacks to {info.file_size} bytes")
    try:
        return ET.fromstring(z.read(info))
    except ET.ParseError as exc:
        raise ValueError(f"{what}: {name} is not well-formed XML ({exc})") from None


def _xl_string(node: Any) -> str:
    """A shared or inline string: its text, or its runs' (rich text), never a phonetic guide's (``rPh``)."""
    parts: list[str] = []
    for child in node:
        tag = _xl_local(child.tag)
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "r":
            parts.extend(t.text or "" for t in child if _xl_local(t.tag) == "t")
    return _XL_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), "".join(parts))


def _xl_number(value: str) -> str:
    """A number as the cell shows it in the General format: 18292, not 18292.0."""
    try:
        x = float(value)
    except ValueError:
        return value
    return str(int(x)) if x.is_integer() and abs(x) < 1e15 else repr(x)


def _xl_rows(root: Any, shared: list[str], what: str) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for row in (e for e in root.iter() if _xl_local(e.tag) == "row"):
        values: dict[int, str] = {}
        for c in row:
            if _xl_local(c.tag) != "c":
                continue
            m = _XL_REF.match(c.get("r", ""))
            col = 0
            if m:
                for ch in m.group(1):
                    col = col * 26 + ord(ch) - 64
                col -= 1
            else:
                col = max(values) + 1 if values else 0
            kind = c.get("t", "n")
            v = next((e.text for e in c if _xl_local(e.tag) == "v"), None)
            if kind == "inlineStr":
                node = next((e for e in c if _xl_local(e.tag) == "is"), None)
                text = _xl_string(node) if node is not None else None
            elif v is None:
                text = None  # a cell with a style and no value: missing
            elif kind == "s":
                if not v.strip().isdigit() or int(v) >= len(shared):
                    raise ValueError(f"{what}: cell {c.get('r', '?')} names shared string {v!r}, which is not there")
                text = shared[int(v)]
            elif kind == "b":
                text = "TRUE" if v.strip() == "1" else "FALSE"
            elif kind == "n":
                text = _xl_number(v)
            else:
                text = v  # str (a formula's text), e (an error: #N/A), d (an ISO date)
            if text is not None:
                values[col] = text
        if values:
            rows.append([values.get(i) for i in range(max(values) + 1)])
    return rows


def xlsx_sheets(data: bytes, name: str = "workbook") -> list[tuple[str, Callable[[], list[list[str | None]]]]]:
    """The sheets of an Excel workbook (``.xlsx``) in their order, as (name, a function reading its rows).  A row is
    the list of its cells' texts as the workbook stores them (shared, inline and rich-text strings; a number as its
    General format shows it; a date as its day number), None for a cell with no value; an empty row is skipped.
    Standard library only (``zipfile`` and ``xml.etree``)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError(f"{name}: not an Excel workbook (.xlsx), or a damaged one") from None
    wb = _xl_part(z, "xl/workbook.xml", name)
    if wb is None:
        raise ValueError(f"{name}: not an Excel workbook (no xl/workbook.xml)")
    rels = _xl_part(z, "xl/_rels/workbook.xml.rels", name)
    links = [r for r in (rels.iter() if rels is not None else ()) if _xl_local(r.tag) == "Relationship"]
    targets = {r.get("Id"): r.get("Target", "") for r in links}

    def part(target: str) -> str:
        return target.lstrip("/") if target.startswith("/") else "xl/" + target

    strings = next((part(r.get("Target", "")) for r in links if r.get("Type", "").endswith("/sharedStrings")),
                   "xl/sharedStrings.xml")
    cache: list[list[str]] = []

    def shared() -> list[str]:
        if not cache:
            sst = _xl_part(z, strings, name)
            cache.append([_xl_string(si) for si in sst if _xl_local(si.tag) == "si"] if sst is not None else [])
        return cache[0]

    def reader(target: str) -> Callable[[], list[list[str | None]]]:
        def read() -> list[list[str | None]]:
            root = _xl_part(z, target, name)
            if root is None:
                raise ValueError(f"{name}: the workbook names a sheet {target} that is not in it")
            return _xl_rows(root, shared(), name)
        return read

    sheets = [e for e in wb.iter() if _xl_local(e.tag) == "sheet"]
    out = []
    for i, sheet in enumerate(sheets, 1):
        rid = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), None)
        out.append((sheet.get("name", f"Sheet{i}"), reader(part(targets.get(rid) or f"worksheets/sheet{i}.xml"))))
    return out


def tsv_escape(cell: str) -> str:
    """A cell for a line of the extract: a backslash, tab, newline or carriage return written ``\\\\ \\t \\n \\r``."""
    return cell.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


_TSV_UNESCAPE = re.compile(r"\\(.)")
_TSV_CODES = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}


def tsv_unescape(cell: str) -> str:
    return _TSV_UNESCAPE.sub(lambda m: _TSV_CODES.get(m.group(1), m.group(0)), cell)


def parse_extract(text: str) -> tuple[list[str], list[str], list[list[str | None]]]:
    """The '#' lines, the header and the rows of an extract written by :func:`publish_ntu` (a tab-separated file with
    the escapes of :func:`tsv_escape`, no quoting); an empty cell is a missing value (None).  ``ValueError`` when it
    does not end with a line end or a row has not the header's cells (a file cut short or edited)."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        i += 1
    notes = [line.rstrip("\r") for line in lines[:i]]
    if i == len(lines) or not lines[i].rstrip("\r"):
        return notes, [], []
    header = [tsv_unescape(c) for c in lines[i].rstrip("\r").split("\t")]
    rows = [[tsv_unescape(c) or None for c in line.rstrip("\r").split("\t")] for line in lines[i + 1:] if line]
    if lines[-1]:
        raise ValueError(f"the extract does not end with a line end: cut short after {len(rows)} rows?")
    short = next((n for n, row in enumerate(rows, 1) if len(row) != len(header)), None)
    if short is not None:
        raise ValueError(f"the extract's row {short} has {len(rows[short - 1])} cells, its header {len(header)}: "
                         f"cut short or edited by hand?")
    return notes, header, rows


@dataclass
class SourceTable:
    """A list's table as read: the file (a zip's member), its bytes, the sheet read and the workbook's sheets (an
    Excel file), the header and the rows as written (None for a missing value), the columns found by role, and the
    '#' lines heading a committed extract."""

    file: str
    data: bytes
    header: list[str]
    rows: list[list[str | None]]
    columns: dict[str, int]
    sheet: str = ""
    sheets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ntu_columns(header: list[str], name: str) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        key = re.sub(r"[\W_]+", "", h or "").lower()
        for role, names in _NTU_HEADERS.items():
            if key in names:
                if role in cols:  # which of the two holds the names is not for the reader to guess
                    raise ValueError(f"{name}: two {role} columns, {header[cols[role]]!r} and {h!r}")
                cols[role] = i
    missing = [role for role in ("primary", "alternate") if role not in cols]
    if missing:
        raise ValueError(f"{name}: no {' or '.join(missing)} name column; the header is {header!r} (expected names "
                         f"such as PrimaryDrugName/主名, AlternateName/别名, DictionarySource/出处, Remarks/备注)")
    return cols


def ntu_table(path: Path | str, *, encoding: str | None = None) -> SourceTable:
    """The NTU table of a download (see :func:`table_file`) or of the committed extract, as written: an Excel
    workbook's first sheet whose first row names the columns (PrimaryDrugName/主名 and AlternateName/别名 at least)."""
    return _ntu_table(*table_file(path), encoding=encoding)


def _ntu_table(name: str, data: bytes, *, encoding: str | None = None) -> SourceTable:
    ext = Path(name).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        sheets = xlsx_sheets(data, name)
        for sheet, read in sheets:
            rows = read()
            if not rows:
                continue
            header = [h or "" for h in rows[0]]
            try:
                cols = _ntu_columns(header, name)
            except ValueError:
                continue
            return SourceTable(name, data, header, rows[1:], cols, sheet, [s for s, _ in sheets])
        raise ValueError(f"{name}: no sheet whose first row names the columns (PrimaryDrugName/主名 and "
                         f"AlternateName/别名); its sheets: {', '.join(s for s, _ in sheets) or 'none'}")
    text = _decode(data, encoding, name)
    notes: list[str] = []
    if ext == ".tab":
        header, rows = parse_tab(text)
    elif ext == ".tsv" and text.startswith("#"):  # the committed extract
        notes, header, rows = parse_extract(text)
    else:
        # a .tsv has no quoting (a stray " is a character of its cell); a .csv quotes cells that hold a comma
        options: dict[str, Any] = {"delimiter": "\t", "quoting": csv.QUOTE_NONE} if ext == ".tsv" else {}
        table = list(csv.reader(io.StringIO(text, newline=""), **options))
        header, rows = (table[0] if table else []), [[c or None for c in r] for r in table[1:] if r]
    header = [h.strip() for h in header]
    return SourceTable(name, data, header, rows, _ntu_columns(header, name), notes=notes)


# ----------------------------------------------------- the remarks: books cited, places, languages, persons
_LANGS = ("藏|傣|蒙古|蒙|维吾尔|维|苗|壮|侗|朝鲜|朝|彝|瑶|土家|布依|哈尼|僾尼|懓尼|佤|景颇|拉祜|纳西|傈僳|黎|畲|羌|"
          "哈萨克|柯尔克孜|白|水|土|回|满|京")
_LANG = re.compile(f"(?P<lang>{_LANGS})(?P<zu>族)?(?P<suffix>名译音|药名|医名|语名|语|文|名|药)?")
_LANG_BARE = {"藏", "傣", "蒙古", "蒙", "维", "维吾尔", "苗", "壮", "侗", "彝", "哈尼", "僾尼", "懓尼"}  # [傣]
_LANG_WITH_ZU = {"白", "水", "土", "回", "满", "京", "黎"}  # 土名 is a local name, not one in the Tu language
_LANG_CANON = {"蒙古": "蒙", "维吾尔": "维", "朝鲜": "朝", "懓尼": "僾尼"}
_LABEL_PREFIX = re.compile(f"(?P<label>(?:{_LANGS})(?:族)?(?:名译音|药名|语|名))[:：]")  # 藏名:榜阿嘎保

_PROVINCES = ("黑龙江", "内蒙古", "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "江苏", "浙江", "安徽",
              "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "四川", "贵州", "云南", "西藏",
              "陕西", "甘肃", "青海", "宁夏", "新疆", "台湾", "香港", "澳门", "内蒙")
_AREAS = ("东北", "西北", "西南", "东南", "华东", "华南", "华北", "华中", "两广", "两湖", "江南", "岭南", "北方", "南方",
          "北方地区", "南方地区")
_TOWNS = ("昆明", "大理", "丽江", "玉溪", "思茅", "红河", "西双版纳", "勐海", "元江", "峨山", "成都", "西昌", "会理",
          "木里", "盐源", "南川", "广州", "厦门", "晋江", "南宁", "博白", "邕宁", "贵县", "苏州", "杭州", "乐清", "东天目",
          "天目山", "金华", "利川", "巴东", "咸宁", "鹤峰", "常德", "湘阴", "南丰", "婺源", "德兴", "围场", "安顺",
          "眉县", "佳木斯", "万宁", "马山", "吊罗山", "太白山", "峨眉山")
_PLACES = frozenset(_PROVINCES + _AREAS + _TOWNS)
_PLACE_PREFIXES = sorted(_PLACES, key=len, reverse=True)
_PLACE_END = re.compile("(?:省|市|县|州|区|山|岛|盟|旗|镇|部|地区)$")
_PLACE_LABELS = ("误称", "俗称", "通称", "土名", "俗名")  # [浙江误称]: a place and what the name is there
_INSTITUTION = re.compile("(?:医学院|学院|大学|医院|部队|空军|海军|研究所|研究院|卫生局|卫生院|药厂|医)$")
_BOOKISH = re.compile("(?:本草|拾遗|图考|图经|别录|本经|纲目|药志|后方)$")  # [植物名实图考], （肘后方)
_SURNAMES_2 = ("司马", "欧阳", "诸葛", "皇甫", "上官", "东方", "尉迟", "长孙", "宇文", "令狐", "慕容", "公孙", "夏侯")
_SURNAMES = frozenset("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏窦章苏潘葛范彭鲁"
                      "韦马方俞任袁柳鲍史唐费廉岑薛雷贺倪汤殷罗毕郝邬安常乐于傅齐康伍余顾孟黄穆萧尹姚邵汪祁毛狄"
                      "伏戴宋庞熊纪舒屈项祝董梁杜阮闵季贾娄江童颜郭梅盛林钟徐邱骆高夏蔡田樊胡凌霍虞万柯管卢莫房裘"
                      "缪解丁宣邓单洪包左石崔吉龚程邢裴陆荣翁荀甄封储靳段焦巴侯全班仲宫宁仇甘厉祖武刘詹龙叶黎白"
                      "蒲邰鄂赖卓屠乔胥党翟谭冉桑寿燕冀尚温庄晏柴瞿阎慕连艾容向易廖耿匡寇聂晁辛饶曾沙鞠巢")
_BOOK_TITLE = re.compile(r"《([^《》]*)》|《([^《》]*?)(?=[）)\]】]|$)")  # 《纲目》, and 《说文）） or 《尔雅 unclosed
_COMMENTATOR = re.compile(f"\\s*([{_HAN_CLASS}]{{2,4}})注(?=[）)\\]】]|$)")  # 《尔雅》郭璞注）
_COMMENTATOR_CELL = re.compile(f"([{_HAN_CLASS}]{{2,3}})注")  # an AlternateName cell that cites a commentator: 高诱注
_REMARK_GROUP = re.compile(r"[（(]([^（）()]*)[）)]?|[\[［【]([^\[\]［］【】]*)[\]］】]?|([^（）()\[\]［］【】]+)")
_ONE_GROUP = re.compile(r"[（(\[［【]([^（）()\[\]［］【】]*)[）)\]］】]")
_REMARK_SEP = re.compile(r"[、，,；;.．:：—\-－/／\s]+")
_REMARK_SEPARATORS = " \u3000、，,；;.．:：—-－/／《》"
_REMARK_PUNCT = _REMARK_SEPARATORS + "（）()[]［］【】"


def _language(label: str) -> str:
    """The language an ethnic-language label names (藏名, [傣], 苗族语, 藏药名, [蒙古] → 藏 傣 苗 藏 蒙); "" for none."""
    m = _LANG.fullmatch(label.strip())
    if not m:
        return ""
    lang = m.group("lang")
    if (lang in _LANG_WITH_ZU and not m.group("zu")) or (not m.group("zu") and not m.group("suffix")
                                                         and lang not in _LANG_BARE):
        return ""
    return _LANG_CANON.get(lang, lang)


def _is_place(text: str) -> bool:
    """A Chinese place: a province, an area (东北, 两广), a town of the list, or one of these and then a known place or
    a place word (云南大理, 四川木里盐源, 广东吊罗山, 贵州南部, 云南红河州)."""
    if text in _PLACES:
        return True
    for prefix in _PLACE_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            rest = text[len(prefix):]
            return _is_place(rest) or (len(rest) <= 4 and _PLACE_END.search(rest) is not None)
    return False


def _is_person(text: str) -> bool:
    """A person's name: two to four characters opening with a surname (陶弘景, 孟诜, 司马彪)."""
    if not 2 <= len(text) <= 4 or _han(text) != text:
        return False
    if text.startswith(_SURNAMES_2):
        return len(text) >= 3
    return text[0] in _SURNAMES and len(text) <= 3


def parse_remark(text: str | None) -> dict[str, Any] | None:
    """A Remarks cell of the NTU table, parsed: ``books`` cited in 《》 (an unclosed 《说文）） too, and a bare title
    such as [植物名实图考]), ``regions`` (places in [] or （）: [云南], [湖北、四川], （江苏）), ``language`` (an
    ethnic-language label: （藏名）, [傣语], [蒙古] → 藏 傣 蒙), ``persons`` (a name in （）: （陶弘景）, （孟诜《必效方》）,
    and a commentator: 《尔雅》郭璞注）), ``other`` (what is none of these: [根名], （通称）, a journal's issue and page)
    and ``raw``, the cell as written.  None for an empty cell."""
    if text is None or not text.strip():
        return None
    out: dict[str, Any] = {"raw": text, "books": [], "regions": [], "language": "", "persons": [], "other": []}
    rest = ""  # the text outside the titles (and the commentators after them)
    pos = 0
    s = text.strip()

    def keep(part: str) -> str:  # what a title stood between stays apart, unless it closes a bracket: （孟诜《必效方》）
        apart = rest and part and rest[-1] not in _OPENERS and part[0] not in _CLOSERS
        return f"{rest}、{part}" if apart else rest + part

    for m in _BOOK_TITLE.finditer(s):
        rest = keep(s[pos:m.start()])
        title = (m.group(1) if m.group(1) is not None else m.group(2)).strip(_REMARK_PUNCT)
        if title:
            out["books"].append(title)
        pos = m.end()
        c = _COMMENTATOR.match(s, pos)
        if c and _is_person(c.group(1)):
            out["persons"].append(c.group(1))
            pos = c.end()
    rest = keep(s[pos:])
    pending: list[str] = []  # text without a Han character (a journal's issue and pages: （5）：57，1959) kept whole

    def flush() -> None:
        left = "".join(pending).strip(_REMARK_SEPARATORS)
        whole = _ONE_GROUP.fullmatch(left)
        left = whole.group(1).strip(_REMARK_SEPARATORS) if whole else left  # [♂], （Ⅱ）
        if left:
            out["other"].append(left)
        pending.clear()

    for m in _REMARK_GROUP.finditer(rest):
        content = next(g for g in m.groups() if g is not None)
        if not _han(content):
            pending.append(m.group(0))
            continue
        flush()
        for piece in _REMARK_SEP.split(content):
            _classify(piece.strip(_REMARK_PUNCT), m.group(1) is not None, out)
    flush()
    for key in ("books", "regions", "persons", "other"):
        out[key] = list(dict.fromkeys(out[key]))
    return out


def _classify(piece: str, round_bracket: bool, out: dict[str, Any]) -> None:
    if not piece:
        return
    lang = _language(piece)
    if lang:
        _add_language(out, lang)
    elif _is_place(piece):
        out["regions"].append(piece)
    elif _INSTITUTION.search(piece):  # （广州部队《常用中草药手册》）, （苏医《中草药手册》）
        out["other"].append(piece)
    elif _BOOKISH.search(piece) and len(piece) >= 3:
        out["books"].append(piece)
    elif round_bracket and _is_person(piece):
        out["persons"].append(piece)
    else:
        for prefix in _PLACE_PREFIXES:  # 勐海傣语, [浙江误称]
            rest = piece[len(prefix):]
            if piece.startswith(prefix) and rest and (_language(rest) or rest in _PLACE_LABELS):
                out["regions"].append(prefix)
                if _language(rest):
                    _add_language(out, _language(rest))
                else:
                    out["other"].append(rest)
                return
        out["other"].append(piece)


def _add_language(out: dict[str, Any], lang: str) -> None:
    if lang not in out["language"].split("、"):
        out["language"] = f"{out['language']}、{lang}" if out["language"] else lang


def dictionaries(cell: str | None) -> list[str]:
    """The dictionaries a DictionarySource cell names: 《中华本草》《中药大辞典》 → 中华本草, 中药大辞典."""
    return [t for t in ((m.group(1) or m.group(2) or "").strip() for m in _BOOK_TITLE.finditer(cell or "")) if t]


# ----------------------------------------------------- the names: characters the GB2312 set lacked, labels, notes
# A character the set lacked is described by its parts in brackets (鸡（土从）, 庵 （艹闾）, （匿/虫）鼻药, 红心灰（艹？）) or
# spelt in pinyin (水麻tiao, 紫 Z H A N木): it becomes 〓 (lost_char), and a head holding one is lost — never 鸡 or 水麻,
# other drugs.  A one-character bracket inside a name gives another reading of the one before it (大茶（柴）药: marks).
_BRACKET = re.compile(r"[（(]([^（）()]{1,4})[）)]")
_LEAD_BRACKET = re.compile(r"[\[［【]([^\]］】]+)[\]］】](.+)")  # [檵木]继木: the spelling and the GB2312 stand-in
_TRAIL_NOTE = re.compile(r"(.+?)\s*[（(\[［【]([^（）()\[\]［］【】]*)[）)\]］】]")
_PINYIN = re.compile(r"\s*[A-Za-z](?:[A-Za-z\s]*[A-Za-z])?\s*")
_HYPHEN = re.compile(f"(?<=[{_HAN_CLASS}])\\s*[-－—‐]\\s*(?=[{_HAN_CLASS}])")  # 铁木尔-地格达: a transliteration
_ANOTHER_NAME = re.compile("又名[:：]?")  # 野山楂又名：小叶山楂: two names


def _is_component_note(content: str, before: str) -> bool:
    """Whether a bracket describes a lost character by its parts (土从, 艹闾, 匿/虫, 艹？) rather than notes the name
    (维名, 广西, 华北大黄, or 鸬鹚 repeating it)."""
    c = content.strip()
    if _language(c) or _is_place(c) or (c and _han(before).endswith(c)):
        return False
    bare = re.sub("[/／？?]", "", c)
    if bare != c:
        return 1 <= len(bare) <= 2 and _han(bare) == bare
    return len(c) == 2 and _han(c) == c


def _ntu_token(piece: str, normalize: Normalize) -> AliasToken | None:
    """One name of an NTU cell, its label (藏名:…, …（维名）) making it a folk name in that language."""
    text = piece.strip(" \u3000\t\r\n。“”\"'")
    if not text:
        return None
    flags: set[str] = set()
    lang, note = "", ""
    m_label = _LABEL_PREFIX.match(text)
    if m_label:
        lang, text = _language(m_label.group("label")), text[m_label.end():]
    m = _LEAD_BRACKET.fullmatch(text)
    if m and len(_han(m.group(1))) >= 2 and _han(m.group(1)) == m.group(1):
        text, note = m.group(1), m.group(2).strip()
    m = _TRAIL_NOTE.fullmatch(text)
    if m and not _is_component_note(m.group(2), m.group(1)):
        text, note = m.group(1), m.group(2).strip()
        lang = lang or _language(note)
    text = _BRACKET.sub(lambda b: "〓" if _is_component_note(b.group(1), text[:b.start()]) else b.group(0), text)

    def variant(b: re.Match[str]) -> str:
        nonlocal note
        if len(b.group(1)) == 1 and _han(b.group(1)) and b.start() > 0 and b.end() < len(text):
            flags.add("marks")
            note = note or b.group(0)
            return ""
        return b.group(0)

    text = _BRACKET.sub(variant, text)
    if _han(text):
        text = _PINYIN.sub("〓", text)
    text, hyphens = _HYPHEN.subn("", text)
    if hyphens:
        flags.add("marks")
    tok = _name_token(text, normalize, "alias")
    tok.text, tok.flags = piece.strip(), sorted(set(tok.flags) | flags)
    tok.note = note or tok.note
    if lang:  # 藏名:榜阿嘎保, 则热克（维名）: the label as written is the note
        tok.kind = "folk"
        tok.note = tok.note or (m_label.group("label") if m_label else f"{lang}名")
    return tok


def _ntu_tokens(cell: str, normalize: Normalize, language: str = "") -> list[AliasToken]:
    out = []
    for piece in _NTU_SEP.split(_ANOTHER_NAME.sub("、", cell)):
        tok = _ntu_token(piece, normalize)
        if tok is None:
            continue
        if language and tok.kind != "folk":  # the row's remark names the language: （藏名）, [傣语]
            tok.kind, tok.note = "folk", f"{language.split('、')[0]}名"
        out.append(tok)
    return out


def _ntu_head(raw: str, normalize: Normalize) -> tuple[str, list[str], str]:
    """A primary name: (the head, the entry's flags, a note it carried: 华北大黄, 藏药名, 继木 of [檵木]继木)."""
    if not raw.strip():
        return "", ["no_head"], ""
    tok = _ntu_token(raw, normalize)
    if tok is None or not tok.name:
        return "", ["no_head"], ""
    if "lost_char" in tok.flags:
        return "", ["lost_head"], tok.note
    return tok.name, (["head_marks"] if "marks" in tok.flags else []), tok.note


def read_ntu(path: Path | str, *, normalize: Normalize | None = None, encoding: str | None = None) -> list[ListEntry]:
    """The NTU "Large List of Chinese Drug Names 40K" (doi:10.21979/N9/V2XBOH, CC BY-NC 4.0): the workbook the
    dataset gives (``.xlsx``), a Dataverse ``.tab`` (or the zip holding it), a ``.csv``/``.tsv``, or the committed
    extract (corpus/aliases/ntu40k.tsv); one entry per row, the columns found by name.  ``info`` keeps the five cells
    as read (``number primary dictionary alternate remarks``: None for a missing value — in a ``.csv``/``.tsv`` or the
    extract, any empty cell), ``dictionaries`` (the titles of DictionarySource) and ``remark`` (:func:`parse_remark`;
    a remark naming a language makes the row's names folk names in it)."""
    return _ntu_entries(ntu_table(path, encoding=encoding), normalize=normalize or _identity)


def _ntu_entries(table: SourceTable, *, normalize: Normalize) -> list[ListEntry]:
    out = []
    for n, row in enumerate(table.rows, 1):
        cells = {role: row[i] if i < len(row) else None for role, i in table.columns.items()}
        head_raw = (cells["primary"] or "").strip()
        head, flags, head_note = _ntu_head(head_raw, normalize)
        alternate = cells["alternate"]
        if alternate is None:
            flags.append("missing")
        elif not alternate.strip():
            flags.append("empty")
        remark = parse_remark(cells.get("remarks"))
        cited = _COMMENTATOR_CELL.fullmatch((alternate or "").strip())
        if cited and _is_person(cited.group(1)):  # 高诱注, 郭璞注: a commentator the cell cites, no name of the drug
            flags.append("commentator")
            tokens = []
        else:
            tokens = _ntu_tokens(alternate or "", normalize, remark["language"] if remark else "")
        info: dict[str, Any] = {role: cells.get(role) for role in NTU_COLUMNS}
        info["dictionaries"] = dictionaries(cells.get("dictionary"))
        info["remark"] = remark
        if head_note:
            info["head_note"] = head_note
        out.append(ListEntry(head, head_raw, _finish(tokens, head), flags, f"row {n}", info))
    return out


def remark_counts(remarks: Iterable[str | None]) -> dict[str, Any]:
    """How the Remarks cells parse: rows with a remark, rows with each field, languages, and rows with nothing but
    ``other``."""
    parsed = [p for p in (parse_remark(r) for r in remarks) if p]
    return {"rows": len(parsed), **{key: sum(bool(p[key]) for p in parsed)
                                    for key in ("books", "regions", "language", "persons", "other")},
            "only_other": sum(bool(p["other"]) and not any(p[k] for k in ("books", "regions", "language", "persons"))
                              for p in parsed),
            "books_cited": sum(len(p["books"]) for p in parsed),
            "distinct_books": len({b for p in parsed for b in p["books"]}),
            "languages": _count(lang for p in parsed for lang in p["language"].split("、") if lang)}


# ----------------------------------------------------- the committed extract
def extract_text(table: SourceTable, *, original: str | None = None) -> tuple[str, int]:
    """The committed extract of a table (the text, and how many cells hold an escaped character): '#' lines giving
    the dataset, its DOI, licence and citation, the original file (name, sha256, rows) and what was changed, then the
    header and one line per row, the columns as the file has them, each cell as written (:func:`tsv_escape`)."""
    width = len(table.header)
    cells = [[(row[i] if i < len(row) and row[i] is not None else "") for i in range(width)] for row in table.rows]
    escaped = sum(tsv_escape(c) != c for row in [table.header, *cells] for c in row)
    original = original or table.file
    held = f"{table.file} (in {original})" if original != table.file else table.file
    sheet = f', sheet "{table.sheet}"' if table.sheet else ""
    others = [s for s in table.sheets if s != table.sheet]
    fmt = Path(table.file).suffix.lstrip(".").lower() or "the original format"
    changes = [f"converted from {fmt} to TSV (UTF-8, LF line ends); columns kept; nothing else changed: each cell "
               f"is written as the file holds it (spaces kept{'; numbers as the cells show them' if table.sheet else ''})"]
    if others:
        changes.append(f"only the sheet \"{table.sheet}\" is extracted: the workbook's other sheet"
                       f"{'s' if len(others) > 1 else ''}, {', '.join(others)}, {'are' if len(others) > 1 else 'is'} not")
    if table.sheet:
        changes.append("cell formatting (fonts, column widths) is not kept")
    wider = sum(any(c not in (None, "") for c in row[width:]) for row in table.rows)
    if wider:
        changes.append(f"{wider} row{'' if wider == 1 else 's'} hold{'s' if wider == 1 else ''} cells beyond the "
                       f"header's columns: they are not kept")
    changes.append("a backslash, tab, newline or carriage return in a cell is written \\\\ \\t \\n \\r: "
                   + (f"{escaped} cell{'' if escaped == 1 else 's'} hold{'s' if escaped == 1 else ''} one" if escaped
                      else "no cell holds one"))
    lines = [
        f"# {NTU['title']}: an extract of the dataset, tab-separated",
        f"# Source: {NTU['publisher']}, https://doi.org/{NTU['doi']}",
        f"# Citation: {NTU['citation']} ({NTU['unverified']})",
        (f"# Licence: {NTU['licence']}, {NTU['licence_uri']} (non-commercial use only; this extract is shared under "
         f"the same licence, with the credit above)"),
        (f"# Original file: {held}{sheet}, sha256 {hashlib.sha256(table.data).hexdigest()}, {len(table.rows)} rows "
         f"(the header row not counted)"),
        *[f"# Modifications: {c}" if i == 0 else f"#   {c}" for i, c in enumerate(changes)],
        ("# Disclaimer: the licensor offers the dataset as-is and as-available, with no warranties (CC BY-NC 4.0, "
         "section 5)"),
        f"# Regenerate: taochronos aliases import ntu {original} --publish (corpus/aliases/README.md)",
        "\t".join(tsv_escape(h) for h in table.header),
        *("\t".join(tsv_escape(c) for c in row) for row in cells),
    ]
    return "\n".join(lines) + "\n", escaped


def publish_ntu(path: Path | str, out: Path | str, *, encoding: str | None = None,
                normalize: Normalize | None = None, pin: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write the committed extract of the NTU table (``corpus/aliases/ntu40k.tsv``, CC BY-NC 4.0, credited in its
    '#' lines) from the dataset's file — the workbook, the Dataverse .tab or its zip — and report it: the file read,
    its sha256 and rows, the lines written, the extract's bytes and sha256, how the remarks parse, and (with
    ``normalize``) the names it gives.  Byte for byte the same on the same file: the pinned one (``pin``'s sha256) is
    named in the header by the pin's file name, whatever the name it was saved under.  Refuses the extract itself."""
    path = Path(path)
    name, data = table_file(path)
    table = _ntu_table(name, data, encoding=encoding)
    if table.notes:
        raise ValueError(f"{path.name}: the extract itself; publish from the dataset's file (the .xlsx or .tab)")
    sha = hashlib.sha256(data).hexdigest()
    pinned = (pin or {}).get("file") if (pin or {}).get("sha256") == sha else None
    # the pinned workbook, under whatever name or in whatever zip it was saved: the header names it as the pin does,
    # so that the same workbook gives the same bytes
    text, escaped = extract_text(replace(table, file=pinned) if pinned else table, original=pinned or path.name)
    _, header, written = parse_extract(text)  # read back: the extract holds the table's cells, every one
    width = len(table.header)
    if header != table.header or written != [[c or None for c in (row + [None] * width)[:width]] for row in table.rows]:
        raise ValueError(f"{path.name}: the extract does not read back as the table")  # a cell the escapes miss
    blob = text.encode("utf-8")
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    col = table.columns.get("remarks")
    report: dict[str, Any] = {
        "source": NTU["id"], "file": table.file, "sheet": table.sheet, "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data), "rows": len(table.rows), "written": len(written), "columns": table.header,
        "wider_rows": sum(any(c not in (None, "") for c in row[width:]) for row in table.rows),
        "escaped_cells": escaped, "output": str(target),
        "extract": {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()},
        "remarks": remark_counts(row[col] if col is not None and col < len(row) else None for row in table.rows),
    }
    if path.name != table.file:
        report["from"] = path.name
    if normalize is not None:
        report["names"] = summary(_ntu_entries(table, normalize=normalize))
    warnings = _pin_warnings(report, pin)
    if warnings:
        report["warnings"] = warnings
    return report


def _pin_warnings(entry: Mapping[str, Any], pin: Mapping[str, Any] | None) -> list[str]:
    """Where a file read differs from the pin; not by its name alone when its bytes are the pinned ones."""
    same = bool(pin) and pin.get("sha256") == entry.get("sha256")
    return [f"{key} {entry[key]} differs from the pinned {pin[key]}" for key in ("file", "rows", "sha256")
            if pin and pin.get(key) is not None and pin[key] != entry[key] and not (key == "file" and same)]


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
                     "q": t.qualifier, "nt": t.note or e.info.get("remarks") or "", "at": e.info.get("dictionary") or "",
                     "fl": t.flags}
            row.update({k: v for k, v in extra.items() if v})
            out.append(row)
    return out


def import_local(source: str, path: Path | str, out_dir: Path | str, *, normalize: Normalize, normalizer: str,
                 encoding: str | None = None, attested: Callable[[str], bool] | None = None,
                 repairs: Pairs | None = REPAIRS, licence: str = "", attribution: str = "",
                 pin: Mapping[str, Any] | None = None, imported: str | None = None) -> dict[str, Any]:
    """Read a local list (``bielu-gb``, ``hurb`` or ``ntu``) through the pack's normaliser (``normalizer`` its
    fingerprint), write its pairs to ``<out_dir>/<source>.jsonl`` under the source's id in sources.yaml, and record it
    in ``<out_dir>/manifest.json``: that id, the table's file, sha256, bytes and rows, the pairs written, the
    normaliser, licence, attribution, the date, and warnings where it differs from the pin (``{file, rows, sha256}``
    of sources.yaml).  Returns that manifest entry."""
    if source not in LOCAL_SOURCES:
        raise ValueError(f"unknown local alias source {source!r}; expected one of {', '.join(LOCAL_SOURCES)}")
    path = Path(path)
    name, data = table_file(path) if source == "ntu" else (path.name, path.read_bytes())
    if source == "ntu":
        entries = _ntu_entries(_ntu_table(name, data, encoding=encoding), normalize=normalize)
    elif source == "hurb":
        entries = read_hurb(path, normalize=normalize, encoding=encoding)
    else:
        entries = read_bielu_gb(path, encoding=encoding, normalize=normalize, attested=attested, repairs=repairs)
    rows = local_rows(entries, LOCAL_SOURCES[source])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{source}.jsonl").write_bytes("".join(canonical_dumps(r) + "\n" for r in rows).encode("utf-8"))
    entry: dict[str, Any] = {"source": LOCAL_SOURCES[source], "file": name, "sha256": hashlib.sha256(data).hexdigest(),
                             "bytes": len(data), "rows": len(entries), "pairs": len(rows), "normalizer": normalizer,
                             "licence": licence, "attribution": attribution,
                             "imported": imported or date.today().isoformat()}
    if name != path.name:
        entry["from"] = path.name
    warnings = _pin_warnings(entry, pin)
    if warnings:
        entry["warnings"] = warnings
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest[source] = entry
    text = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    manifest_path.write_text(text, encoding="utf-8")
    return entry
