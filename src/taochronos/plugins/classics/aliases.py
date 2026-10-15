"""The alias layer (别名层): other names of a drug, kept apart from the lexicon (ADR 0023).

A record per normalised surface lists every drug the name denotes — its referents, merged by same-drug group — each
with its kind, its status (``open``: searched as the drug; ``cue``: searched only where the passage reads as a drug;
``candidate``: listed, never searched), a hard window where the name meant this drug only in some periods, its cues and
anti-cues, its sources and up to three witness passages.  A record also carries the strings that contain the name but
are not it (blockers: 将军 in 大将军), a soft first-use floor that only flags (山药 before 1063), and its passage counts.
Every decision is frozen when ``taochronos aliases build`` writes the file, so the server, the browser and the Worker
decide alike from data alone.  Nothing here enters the ``Lexicon``.

The file (``domains/classics/aliases/aliases.jsonl``) is compact JSON lines: a header line, then one record per surface
in code-point order, keys sorted, defaults left out on writing and restored on reading.  Field names are the file's
keys, so this module, the Worker's port and the file read alike.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...protocol.base import canonical_dumps
from .store import is_han

FORMAT = "taochronos-aliases"
VERSION = 1

# kind → how an answer names it
KINDS: dict[str, str] = {
    "alias": "异名",
    "taboo_rename": "避讳改名",
    "part_name": "药用部位名",
    "processing_variant": "炮制/加工名",
    "abbreviation": "简称",
    "variety": "品种/产地名",
    "spelling": "异写",
    "old_name": "古名",
    "folk": "俗名",
}
STATUSES = ("open", "cue", "candidate")
WITNESS_KINDS = {"e": "equation", "g": "gloss", "n": "entry", "m": "釋名", "l": "list"}
DIRECTIONS = ("alias→drug", "drug→alias")
# caps the build keeps to (``aliases check`` enforces them; reading does not)
MAX_RAW, MAX_BLOCKERS, MAX_CUES, MAX_WITNESSES = 4, 24, 12, 3

# retrieval.alias in a profile overrides these
DEFAULT_ALIAS: dict[str, Any] = {
    "enabled": False, "asked_first": "herbs", "share": [3, 10], "expansions": 8, "mask_bits": 30,
    "candidates": 400, "edges": 10, "widen": 150, "list_window": 10, "cue_window": 20, "reading_window": 40,
    "witness_scope": "full", "unknown_runs": True, "alias_score": 0.5, "ablate": [],
}
# the drug-context patterns ``context.json`` carries (a built one overrides them), read on gate-form text; each
# compiles alike in Python ``re`` and JS ``RegExp(…, "u")``
CONTEXT_PATTERNS: dict[str, str] = {
    # 将军二两 · 将军，二两 · 将军六铢 (not across a bracketed note: 将军（川者）二两 is read by none of these)
    "dose": r"^\|?[^|]{0,6}?[一二三四五六七八九十百千半两0-9]+[两钱分斤枚个升合片铢粒]",
    "each": r"^[^|]{0,8}?各[一二三四五六七八九十百半等]",  # 将军芒硝各三两
    "prep": r"^\|[^|]{0,8}?(?:炒|炙|去|研|制|焙|煨|洗|切|熬|烧|酒|醋|锉|碎|捣|浸|蒸)",  # 将军（酒洗） · 将军（炙）三两
    "nameof": r"(?:一名|又名|亦名|俗名|俗呼|名曰)$",  # 大黄一名将军
    "named": r"^(?:之名|之称|之号)",  # 故有神草之名 · 并有鬼督邮之名: the name spoken of as a name
}
# A side passage that gives the name nothing beside it — a heading, a contents line, a list of formula names (炙甘草汤
# 甘草汤, 人参散) — has fewer than BARE_REST Han characters outside the name and the formula names it writes (a run of
# at most 8 characters ending in one of FORMULA_ENDS that is no drug's name: 石膏, 雷丸, 牡丹) and no drug context: it
# follows the others of its drug
BARE_REST = 4
FORMULA_ENDS = "汤散丸膏丹圆饮"
# the note on a stop name asked on its own, whose drugs are listed as candidates (status ``stop``): the layer searches
# none of their names; the lexicon's search, as today, those of the herb entry that files the name (救火 under 景天),
# whose hits say so (status ``stop``)
STOP_NOTE = "此名多作普通词语，罕作药名：所列药物只是候选，未按其名检索"
STOP_NOTE_LEXICON = "此名多作普通词语，罕作药名：所列药物只是候选，仅按词表检索其同条之名"
# source id → how an answer credits it, when the file's header carries no ``labels`` (the build writes them from
# sources.yaml, which the Worker's ALIAS_SOURCES read too); the CC0 别名录 always with 中醫笈成
SOURCE_LABELS: dict[str, str] = {
    "bielu-jc": "别名录（中醫笈成）", "curated": "编者审定", "store": "古籍互证", "shiming": "纲目释名", "taboo": "避讳",
    "lexicon": "词表", "bielu-gb": "别名录（GB本）", "hurb": "hurbTable", "ntu40k": "NTU 40K",
}

Window = tuple[int | None, int | None]  # [from, to) in years; None leaves that side open
Blocker = str | tuple[str, int | None, int | None]  # a string containing a name that is not it, with a year window


# What a field holds is checked on reading and writing alike: a value of the wrong type raises ``ValueError`` (the
# loader adds the file and line), and a whole float is written and read as the int it is, so ``1063.0`` stays 1063.
def _bad(what: str, value: Any) -> ValueError:
    return ValueError(f"{what} is {value!r}")


def _text(value: Any, what: str) -> str:
    if type(value) is not str:
        raise _bad(what, value)
    return value


_STR = frozenset([str])


def _texts(value: Any, what: str) -> list[str]:
    if type(value) not in (list, tuple) or not _STR.issuperset(map(type, value)):
        raise _bad(what, value)
    return list(value)


def _rows(value: Any, what: str) -> list[Any]:
    if type(value) not in (list, tuple):
        raise _bad(what, value)
    return list(value)


def _int(value: Any, what: str, *, null: bool = True) -> int | None:
    """A year or a count: an int, a whole float as its int, or None where ``null`` allows it."""
    if type(value) is int or (value is None and null):
        return value
    if type(value) is float and value.is_integer():
        return int(value)
    raise _bad(what, value)


def _window(value: Any, what: str = "v") -> Window | None:
    """A window as stored: None when it bounds nothing."""
    if value is None:
        return None
    if type(value) not in (list, tuple) or len(value) != 2:
        raise _bad(what, value)
    lo, hi = _int(value[0], what), _int(value[1], what)
    return None if lo is None and hi is None else (lo, hi)


def _blocker(value: Any) -> Blocker:
    """A blocker read from or written to the file: the bare string when its window bounds nothing."""
    if type(value) is str:
        return value
    if type(value) not in (list, tuple) or len(value) != 3:
        raise _bad("b", value)
    text, lo, hi = _text(value[0], "b"), _int(value[1], "b"), _int(value[2], "b")
    return text if lo is None and hi is None else (text, lo, hi)


def _credit(value: Any) -> tuple[str, int | None, int | None] | None:
    if value is None:
        return None
    if type(value) not in (list, tuple) or len(value) != 3:
        raise _bad("cr", value)
    return _text(value[0], "cr"), _int(value[1], "cr"), _int(value[2], "cr")


# --------------------------------------------------------------------------- records
@dataclass
class Witness:
    """A passage that ties the name to its drug; ``[pid, y0, y1, kind, web]`` in the file."""

    pid: str
    y0: int | None = None
    y1: int | None = None
    kind: str = "e"  # e equation · g gloss（…） · n 本草 entry with 一名 · m 釋名 · l the 别名录 itself
    web: bool = False  # the passage is in the committed web pack

    def to_json(self) -> list[Any]:
        return [_text(self.pid, "w"), _int(self.y0, "w"), _int(self.y1, "w"), _text(self.kind, "w"),
                1 if self.web else 0]

    @classmethod
    def from_json(cls, row: Any) -> Witness:
        if (type(row) is not list or len(row) != 5 or type(row[0]) is not str or type(row[3]) is not str
                or row[4] not in (0, 1)):
            raise _bad("w", row)
        pid, y0, y1, kind, web = row
        if type(y0) is not int or type(y1) is not int:  # most witnesses are dated: only the rest pay for the check
            y0, y1 = _int(y0, "w"), _int(y1, "w")
        return cls(pid, y0, y1, kind, bool(web))


@dataclass
class Referent:
    """One drug a name denotes."""

    h: str  # head, normalised
    g: str = ""  # group: the canonical head of its same-drug group (default h)
    t: str | None = None  # the full-corpus lexicon's term id at build
    k: str = "alias"  # KINDS
    st: str = "open"  # STATUSES
    v: Window | None = None  # hard window [from, to) in which the name denotes this drug
    c: list[str] | None = None  # cues (≤ 12): the head, its unambiguous names, curated cues (default [h])
    a: list[str] = field(default_factory=list)  # anti-cues
    src: list[str] = field(default_factory=list)  # source ids (sources.yaml; ``lexicon`` for a lexicon rival)
    w: list[Witness] = field(default_factory=list)  # ≤ 3: the earliest equation, gloss or entry, then the list
    cr: tuple[str, int | None, int | None] | None = None  # the work a 釋名 bracket credits, with its years
    nt: str = ""  # note

    def __post_init__(self) -> None:
        self.g = self.g or self.h
        if self.c is None:
            self.c = [self.h]

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"h": _text(self.h, "h"), "src": _texts(self.src, "src")}
        if self.g != self.h:
            out["g"] = _text(self.g, "g")
        if self.t is not None:
            out["t"] = _text(self.t, "t")
        if self.k != "alias":
            out["k"] = _text(self.k, "k")
        if self.st != "open":
            out["st"] = _text(self.st, "st")
        v = _window(self.v)
        if v is not None:
            out["v"] = list(v)
        if self.c != [self.h]:
            out["c"] = _texts(self.c, "c")
        if self.a:
            out["a"] = _texts(self.a, "a")
        if self.w:
            out["w"] = [w.to_json() for w in self.w]
        cr = _credit(self.cr)
        if cr is not None:
            out["cr"] = list(cr)
        if self.nt:
            out["nt"] = _text(self.nt, "nt")
        return out

    @classmethod
    def from_json(cls, d: Any) -> Referent:
        if type(d) is not dict:
            raise _bad("r", d)
        get = d.get
        h, g, t, k, st, nt = get("h", ""), get("g", ""), get("t"), get("k", "alias"), get("st", "open"), get("nt", "")
        if not (type(h) is str and type(g) is str and type(k) is str and type(st) is str and type(nt) is str
                and (t is None or type(t) is str)):
            for key, value in (("h", h), ("g", g), ("t", "" if t is None else t), ("k", k), ("st", st), ("nt", nt)):
                _text(value, key)
        c, a, w = get("c"), get("a"), get("w")  # a list left out (or null) is its default
        return cls(h=h, g=g, t=t, k=k, st=st, v=_window(get("v")), c=None if c is None else _texts(c, "c"),
                   a=[] if a is None else _texts(a, "a"), src=_texts(get("src", ()), "src"),
                   w=[] if w is None else [Witness.from_json(x) for x in _rows(w, "w")], cr=_credit(get("cr")), nt=nt)


@dataclass
class AliasRecord:
    """A normalised surface and every drug it names."""

    s: str  # the surface, normalised, ≥ 2 Han characters
    raw: list[str] | None = None  # raw spellings seen, ≤ 4 (default [s])
    # a false friend (小便, 月经): never expanded; its drugs (``r``, or the lexicon's) listed only when it is asked on
    # its own, as candidates of status ``stop``
    stop: bool = False
    n: int = 0  # passages with a free occurrence in the build store (jc_c030 left out)
    sh: float = 0.0  # the share of those passages in drug context (2 decimals)
    b: list[Blocker] = field(default_factory=list)  # ordered by store frequency, ≤ 24
    fl: int | None = None  # soft first-use floor: earlier passages are flagged, never filtered
    flb: str | None = None  # the floor's basis: "taboo:<rule id>" or "curated"
    # the group id when s is a head — every member of a same-drug group (丹砂 and 朱砂, 地肤 and 地肤子) carries it,
    # aliases of another member or not, so that the lexicon's separate entries for them read as one drug
    ho: str | None = None
    r: list[Referent] = field(default_factory=list)  # referents (empty when stop or a head only)

    def __post_init__(self) -> None:
        if self.raw is None:
            self.raw = [self.s]

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"s": _text(self.s, "s")}
        if self.raw != [self.s]:
            out["raw"] = _texts(self.raw, "raw")
        if self.stop:
            out["stop"] = True
        if self.n:
            out["n"] = _int(self.n, "n")
        sh = round(self.sh, 2)
        if sh:
            out["sh"] = float(sh)
        if self.b:
            out["b"] = [b if type(b) is str else list(b) for b in map(_blocker, self.b)]
        if self.fl is not None:
            out["fl"] = _int(self.fl, "fl")
        if self.flb is not None:
            out["flb"] = _text(self.flb, "flb")
        if self.ho is not None:
            out["ho"] = _text(self.ho, "ho")
        if self.r:
            out["r"] = [ref.to_json() for ref in self.r]
        return out

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> AliasRecord:
        get = d.get
        stop, sh, flb, ho = get("stop", False), get("sh", 0), get("flb"), get("ho")
        if type(stop) is not bool:
            raise _bad("stop", stop)
        if type(sh) not in (int, float):
            raise _bad("sh", sh)
        raw, b, r = get("raw"), get("b"), get("r")  # a list left out (or null) is its default
        return cls(
            s=_text(get("s", ""), "s"),
            raw=None if raw is None else _texts(raw, "raw"),
            stop=stop,
            n=_int(get("n", 0), "n", null=False),
            sh=float(sh),
            b=[] if b is None else [_blocker(x) for x in _rows(b, "b")],
            fl=_int(get("fl"), "fl"),
            flb=None if flb is None else _text(flb, "flb"),
            ho=None if ho is None else _text(ho, "ho"),
            r=[] if r is None else [Referent.from_json(x) for x in _rows(r, "r")],
        )


@dataclass
class Expansion:
    """A name searched for an asked one, one hop away: the drug an alias names, or another name of an asked drug."""

    surface: str
    for_: str  # the asked surface it serves
    direction: str  # DIRECTIONS
    group: str
    head: str
    kind: str = "alias"
    status: str = "open"
    valid: Window | None = None
    shared: bool = False  # the name may mean another drug too within the query's window
    cues: list[str] = field(default_factory=list)
    own: list[str] = field(default_factory=list)  # the group's other names
    # the other drugs a shared name may mean: per referent, the window in which the name means it (its ``v``) and the
    # names that tell it apart, sorted by group
    rivals: list[tuple[Window | None, list[str]]] = field(default_factory=list)
    src: list[str] = field(default_factory=list)
    wit: list[Witness] = field(default_factory=list)
    n: int = 0
    searched: bool = False
    # why it was not searched: "cap", "unattested", "period" (outside the query's window), "part" (another part of
    # the plant, a drug of its own); the search adds "routes" (its routes leave out ``alias``) and "share" (no place is
    # reserved for the side queue at this k: ⌊num·k/den⌋ = 0)
    why: str | None = None
    also: list[str] = field(default_factory=list)  # the other asked surfaces the same name serves, in the order asked


# --------------------------------------------------------------------------- the file
def _counts(records: list[AliasRecord]) -> dict[str, int]:
    refs = [ref for rec in records for ref in rec.r]
    out = {"surfaces": len(records), "pairs": len(refs), "stop": sum(rec.stop for rec in records)}
    out.update({st: sum(ref.st == st for ref in refs) for st in STATUSES})
    return out


def dumps_records(records: Iterable[AliasRecord], meta: Mapping[str, Any] | None = None) -> str:
    """The file's text: the header, then the records by surface in code-point order.  ``meta`` goes into the header
    (store, normalizer, lexicon, coverage, and the sources' ``labels``); its format, version, sources and counts are
    those of the records."""
    recs = sorted(records, key=lambda rec: rec.s)
    for a, b in zip(recs, recs[1:]):
        if a.s == b.s:
            raise ValueError(f"duplicate alias surface {a.s}")
    header = {**(meta or {}), "format": FORMAT, "version": VERSION,
              "sources": sorted({src for rec in recs for ref in rec.r for src in ref.src}), "counts": _counts(recs)}
    return "".join(canonical_dumps(obj) + "\n" for obj in [{"_header": header}, *(rec.to_json() for rec in recs)])


def write_records(path: Path, records: Iterable[AliasRecord], meta: Mapping[str, Any] | None = None) -> Path:
    """Write an alias file (:func:`dumps_records`), byte for byte the same for the same records."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dumps_records(records, meta).encode("utf-8"))
    return path


def loads_records(text: str, origin: str = "<aliases>") -> tuple[dict[str, Any], list[AliasRecord]]:
    """The header (empty when the text has none) and the records of an alias file.  A line that is not a record or
    holds a value of the wrong type, a header elsewhere than first, or another format or a newer version raises
    ``ValueError`` naming the line; what a well-formed record says is judged by :class:`AliasIndex`."""
    header: dict[str, Any] = {}
    records: list[AliasRecord] = []
    for no, line in enumerate(text.split("\n"), 1):  # only "\n" ends a line: U+2028 or U+0085 may stand in a note
        if not line.strip(" \t\r"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{origin}:{no}: not JSON ({exc.msg})") from None
        if not isinstance(obj, dict):
            raise ValueError(f"{origin}:{no}: not a record")
        if "_header" in obj:
            if header or records:
                raise ValueError(f"{origin}:{no}: a header after the first line")
            header = _header(obj["_header"], f"{origin}:{no}")
            continue
        try:
            records.append(AliasRecord.from_json(obj))
        except ValueError as exc:
            raise ValueError(f"{origin}:{no}: malformed record ({exc})") from None
    return header, records


def _header(value: Any, where: str) -> dict[str, Any]:
    """A header line's object, checked for what the index reads of it: format, version, sources and labels."""
    if type(value) is not dict:
        raise ValueError(f"{where}: the header is not an object")
    fmt, version = value.get("format"), value.get("version", 0)
    if fmt != FORMAT or type(version) is not int or version > VERSION:
        raise ValueError(f"{where}: {fmt} v{version} is not {FORMAT} v{VERSION} or older")
    labels = value.get("labels", {})
    try:
        _texts(value.get("sources", ()), "sources")
        if type(labels) is not dict:
            raise _bad("labels", labels)
        _texts(list(labels.values()), "labels")
    except ValueError as exc:
        raise ValueError(f"{where}: malformed header ({exc})") from None
    return dict(value)


# --------------------------------------------------------------------------- gates
# The gates are pure functions of data, so the Worker's port (``backup/aliases.js``) decides alike: offsets count code
# points (the port walks ``Array.from`` of the text), strings order by code point, ties break on explicit keys, and the
# slots are integer arithmetic.  A passage's range ``yr`` is closed, [y0, y1]; a window is [from, to); None leaves a
# side open.
_OFF_GATE = re.compile("[^\u3400-\u9fff\uf900-\ufaff\U00020000-\U0003134f\u3007\u3013A-Za-z0-9]")  # is_han, ASCII alnum


def gate_form(norm: str) -> str:
    """Normalised text as the gates read it: Han and ASCII letters and digits kept, anything else ``|``; same length."""
    return _OFF_GATE.sub("|", norm)


def overlaps(window: Window | None, yr: Window | None) -> bool:
    """Whether a passage's range meets a window."""
    if window is None or yr is None:
        return True
    lo, hi = window
    y0, y1 = yr
    return (hi is None or y0 is None or y0 < hi) and (lo is None or y1 is None or y1 >= lo)


def meets(window: Window | None, after: float | None, before: float | None) -> bool:
    """Whether a window meets a query's [after, before)."""
    if window is None:
        return True
    lo, hi = window
    return (hi is None or after is None or after < hi) and (lo is None or before is None or before > lo)


def _gap(window: Window, yr: Window) -> float:
    """Years between a passage's range and a window it misses."""
    lo, hi = window
    y0, y1 = yr
    return lo - y1 if lo is not None and y1 is not None and y1 < lo else y0 - hi


def _inside(g: str, i: int, s: str, b: str) -> bool:
    """Whether the occurrence of ``s`` at ``i`` lies within an occurrence of the longer ``b``."""
    j = b.find(s)
    while j >= 0:
        if j <= i and g.startswith(b, i - j):
            return True
        j = b.find(s, j + 1)
    return False


def _live(blockers: Iterable[Blocker], s: str, yr: Window) -> list[str]:
    """The blockers of ``s`` that may cover it in a passage of range ``yr``: those holding it whose window meets
    ``yr``."""
    out = []
    for b in blockers:
        text, window = (b, None) if isinstance(b, str) else (b[0], (b[1], b[2]))
        if s in text and text != s and overlaps(window, yr):
            out.append(text)
    return out


def _around(g: str, i: int, j: int, width: int) -> str:
    """The ``width`` characters on each side of ``g[i:j]``, joined by a break so nothing matches across the name."""
    return g[max(0, i - width):i] + "|" + g[j:j + width]


def _params(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    return {**DEFAULT_ALIAS, **(cfg or {})}


def _ablate(p: Mapping[str, Any]) -> set[str]:
    """The ablations a profile or a call names: a list of them, or one as a string."""
    value = p.get("ablate") or ()
    return {value} if isinstance(value, str) else set(value)


def _round4(x: float) -> float:
    """``x`` ≥ 0 to 4 places as the Worker rounds, ``Math.round(x * 1e4) / 1e4``: halves up (0.65625 → 0.6563), where
    ``round`` would take the even neighbour."""
    y = x * 10000
    f = math.floor(y)
    return (f + 1 if y - f >= 0.5 else f) / 10000


def _year(w: Witness) -> float | int | None:
    """A witness's year as answers show it: the middle of its range."""
    if w.y0 is None or w.y1 is None:
        return w.y0 if w.y1 is None else w.y1
    mid = (w.y0 + w.y1) / 2
    return int(mid) if mid == int(mid) else mid


def source_labels(ids: Iterable[str], labels: Mapping[str, str] | None = None) -> list[str]:
    """How an answer credits sources: by ``labels`` (an index's, from its files' headers), else
    :data:`SOURCE_LABELS`; an unknown id stands for itself."""
    labels = SOURCE_LABELS if labels is None else labels
    return [labels.get(i, SOURCE_LABELS.get(i, i)) for i in ids]


def assemble(M: list, S: list, k: int, num: int = 3, den: int = 10) -> list:
    """The final list of ``k``: the places p where ⌊num·p/den⌋ steps up (4, 7, 10, 14 … at 3/10) take the side queue's
    next hit, the others the main queue's, and either queue fills in when the other runs out — so the side queue holds
    at most ⌊num·k/den⌋ places while the main queue lasts."""
    out, i, j = [], 0, 0
    for p in range(1, k + 1):
        reserved = (num * p) // den > (num * (p - 1)) // den
        if reserved and j < len(S):
            out.append(S[j])
            j += 1
        elif i < len(M):
            out.append(M[i])
            i += 1
        elif j < len(S):
            out.append(S[j])
            j += 1
        else:
            break
    return out


# --------------------------------------------------------------------------- the index
class AliasIndex:
    """The alias records a pack loaded, by surface.  Empty — and so disabled — unless a profile names a layer.

    A record that cannot be used is skipped and counted, never fatal: a blank surface, a surface of fewer than two Han
    characters, a surface met again (the first kept); a referent with a blank head, an unknown kind or status (and its
    record with it when none of its referents is left).  A file whose values have the wrong type is refused whole
    (:func:`loads_records`).  Answers credit sources by the labels the files' headers carry (``labels``: id → label,
    which the build writes from sources.yaml), else by :data:`SOURCE_LABELS`."""

    def __init__(self, records: Iterable[AliasRecord] = (), *, context: Mapping[str, Any] | None = None,
                 headers: Iterable[Mapping[str, Any]] = (), fingerprint: str = "") -> None:
        self.records: dict[str, AliasRecord] = {}
        self.skipped = {"blank": 0, "one_char": 0, "duplicate": 0, "kind": 0, "status": 0}
        for rec in records:
            if not rec.s.strip():
                self.skipped["blank"] += 1
                continue
            if sum(map(is_han, rec.s)) < 2:
                self.skipped["one_char"] += 1
                continue
            if rec.s in self.records:
                self.skipped["duplicate"] += 1
                continue
            refs = []
            for ref in rec.r:
                if not ref.h.strip():
                    self.skipped["blank"] += 1
                elif ref.k not in KINDS:
                    self.skipped["kind"] += 1
                elif ref.st not in STATUSES:
                    self.skipped["status"] += 1
                else:
                    refs.append(ref)
            if len(refs) < len(rec.r):
                if not refs and not rec.stop and rec.ho is None:
                    continue
                rec = replace(rec, r=refs)
            self.records[rec.s] = rec
        self.headers = [dict(h) for h in headers]
        self.context: dict[str, Any] = dict(context or {})
        self.fingerprint = fingerprint
        self.sources = sorted({src for h in self.headers for src in h.get("sources") or ()}
                              | {src for rec in self.records.values() for ref in rec.r for src in ref.src})
        self.labels = {**SOURCE_LABELS, **{i: t for h in self.headers for i, t in (h.get("labels") or {}).items()}}
        self.max_len = max(map(len, self.records), default=0)
        self.enabled = bool(self.records)
        # what the gates read of the context, and the indexes the expansion walks (surfaces in code-point order)
        ctx = {**CONTEXT_PATTERNS, **self.context}
        self._patterns = {key: re.compile(ctx[key]) for key in CONTEXT_PATTERNS}
        self._herbs = frozenset(ctx.get("herbs") or ())
        self._herb_len = max(map(len, self._herbs), default=0)
        self._groups: dict[str, list[tuple[str, Referent]]] = {}  # group → (surface, referent)
        self._group_heads: dict[str, set[str]] = {}  # group → its heads
        self._heads: dict[str, set[str]] = {}  # head → its groups
        self._terms: dict[str, set[str]] = {}  # lexicon term id → its groups
        for s in sorted(self.records):
            rec = self.records[s]
            if rec.ho is not None:
                self._heads.setdefault(s, set()).add(rec.ho)
                self._group_heads.setdefault(rec.ho, set()).add(s)
            for ref in rec.r:
                self._groups.setdefault(ref.g, []).append((s, ref))
                self._heads.setdefault(ref.h, set()).add(ref.g)
                self._group_heads.setdefault(ref.g, set()).add(ref.h)
                if ref.t:
                    self._terms.setdefault(ref.t, set()).add(ref.g)

    @classmethod
    def load(cls, files: Iterable[Path | str], context: Path | str | Mapping[str, Any] | None = None) -> AliasIndex:
        """Read alias files, in order, and the ``context.json`` the gates read.  The fingerprint covers the bytes of
        both; it is empty when no file was read."""
        digest = hashlib.sha256()
        headers: list[dict[str, Any]] = []
        records: list[AliasRecord] = []
        read = 0
        for path in map(Path, files):
            data = path.read_bytes()
            digest.update(data)
            header, recs = loads_records(data.decode("utf-8"), origin=str(path))
            if header:
                headers.append(header)
            records.extend(recs)
            read += 1
        if context is not None and not isinstance(context, Mapping):
            data = Path(context).read_bytes()
            digest.update(data)
            context = json.loads(data.decode("utf-8"))
        return cls(records, context=context, headers=headers, fingerprint=digest.hexdigest()[:12] if read else "")

    @classmethod
    def empty(cls) -> AliasIndex:
        return cls()

    def __len__(self) -> int:
        return len(self.records)

    def record(self, s: str) -> AliasRecord | None:
        return self.records.get(s)

    def source_labels(self, ids: Iterable[str]) -> list[str]:
        """How an answer credits sources: the labels the files' headers carry (a later file's win), else
        :data:`SOURCE_LABELS`."""
        return source_labels(ids, self.labels)

    # ---------------------------------------------------------------- lookup
    def by_group(self, g: str) -> list[tuple[str, Referent]]:
        """Every (surface, referent) whose referent is in group ``g``, by surface."""
        return list(self._groups.get(g, ()))

    def groups_for(self, term_id: str | None, surfaces: Iterable[str]) -> list[str]:
        """The groups an asked lexicon entry belongs to, by its term id and its surfaces, sorted."""
        out = set(self._terms.get(term_id, ())) if term_id else set()
        for s in surfaces:
            out |= self._heads.get(s, set())
        return sorted(out)

    def names(self, g: str) -> list[str]:
        """The names that tell group ``g`` apart, sorted: its heads and its aliases that name nothing else (stop names
        and candidates left out)."""
        out = set(self._group_heads.get(g, ()))
        for a, ref in self._groups.get(g, ()):
            rec = self.records[a]
            if ref.st != "candidate" and not rec.stop and all(other.g == g for other in rec.r):
                out.add(a)
        return sorted(n for n in out if len(n) >= 2)

    def referents(self, s: str, term: str | None = None, lex: Any = None, *, stop: bool = False) -> list[Referent]:
        """The drugs an asked surface may name: its record's referents, then the lexicon's herb entries for it (its own
        entry first, the others by term id) whose group none of them is in, as ``lexicon`` referents (百枝 → 狗脊, 防风)
        headed by that group (止行, filed under 蒺藜子, names 蒺藜).
        An entry is in a group by its term id or by a head's ``ho`` — which is why every same-drug member carries one:
        the lexicon's 地肤子 is otherwise a second drug beside the 地肤 that 地肤子 names.  None for a stop name, unless
        ``stop`` asks for the drugs it is listed with when asked on its own."""
        rec = self.record(s)
        if rec is not None and rec.stop and not stop:
            return []
        refs = list(rec.r) if rec is not None else []
        if lex is None:
            return refs
        seen = {ref.g for ref in refs}
        own = lex.resolve(term) if term else None
        done: set[str] = set()
        rivals = sorted((e for e, _ in lex.lookup(s)), key=lambda e: e.term_id)
        for entry in ([own] if own is not None else []) + rivals:
            if entry.category != "herb" or entry.term_id in done:
                continue
            done.add(entry.term_id)
            groups = self.groups_for(entry.term_id, [entry.term])
            if seen.intersection(groups):
                continue
            g = groups[0] if groups else entry.term
            # a member's entry names its group's drug, of that drug's term id (蒺藜, herb:蒺藜 — not herb:蒺藜子)
            t = entry.term_id if g == entry.term else next(
                (ref.t for _, ref in self._groups.get(g, ()) if ref.h == g and ref.t), None)
            refs.append(Referent(g, t=t, src=["lexicon"]))
            seen.add(g)
        return refs

    def scan(self, norm: str) -> list[tuple[int, int, str]]:
        """Alias and head surfaces in normalised text, ``(start, end, surface)``: longest first, left to right, stop
        names left out.  A record with only a first-use floor (党参) names a drug too."""
        out: list[tuple[int, int, str]] = []
        i, n = 0, len(norm)
        while i < n:
            for length in range(min(self.max_len, n - i), 1, -1):
                rec = self.records.get(norm[i:i + length])
                if rec is not None and not rec.stop and (rec.r or rec.ho is not None or rec.fl is not None):
                    out.append((i, i + length, rec.s))
                    i += length
                    break
            else:
                i += 1
        return out

    # ---------------------------------------------------------------- gates
    def free_offsets(self, g: str, s: str, blockers: Iterable[Blocker], yr: Window) -> list[int]:
        """Offsets of ``s`` in gate-form text ``g`` not covered by a blocker whose window overlaps ``yr``.  A blocker
        written there only inside one of its own blockers covers nothing (one step, no further): in 大黄大戟 the 黄大戟
        that would hide 大戟 is itself the straddle of 大黄 and 大戟."""
        live = _live(blockers, s, yr)
        out = []
        i = g.find(s) if s else -1
        while i >= 0:
            if all(self.covers(g, i, s, b, yr) is None for b in live):
                out.append(i)
            i = g.find(s, i + 1)
        return out

    def covers(self, g: str, i: int, s: str, b: str, yr: Window) -> int | None:
        """The offset of an occurrence of the blocker ``b`` that covers ``s`` at ``i`` — one holding it and free of
        ``b``'s own blockers — or None."""
        j = b.find(s)
        while j >= 0:
            k = i - j
            if j <= i and g.startswith(b, k):
                rec = self.records.get(b)
                if rec is None or not any(_inside(g, k, b, c) for c in _live(rec.b, b, yr)):
                    return k
            j = b.find(s, j + 1)
        return None

    def _herb_count(self, text: str) -> int:
        """Herb-set names in ``text``, matched longest first, left to right."""
        count = i = 0
        while i < len(text):
            for length in range(min(self._herb_len, len(text) - i), 1, -1):
                if text[i:i + length] in self._herbs:
                    count += 1
                    i += length
                    break
            else:
                i += 1
        return count

    def drug_context(self, g: str, s: str, offs: Iterable[int], cues: Iterable[str], *,
                     cfg: Mapping[str, Any] | None = None) -> bool:
        """Whether ``s`` reads as a drug at one of ``offs``: a dose, 各, a preparation after it, a 一名 before it, a cue
        or two herb names near it."""
        p = _params(cfg)
        cues = [c for c in cues if c and c != s]
        dose, each, prep = (self._patterns[key] for key in ("dose", "each", "prep"))
        for i in offs:
            j = i + len(s)
            after = g[j:j + 12]
            if dose.match(after) or each.match(after) or prep.match(after) or self.named(g, s, [i], cues, cfg=p):
                return True
            if self._herb_count(_around(g, i, j, p["list_window"])) >= 2:
                return True
        return False

    def named(self, g: str, s: str, offs: Iterable[int], cues: Iterable[str], *,
              cfg: Mapping[str, Any] | None = None) -> bool:
        """Whether ``s`` is named as the drug at one of ``offs``: a 一名 before it, a 之名 after it or a cue near it —
        the part of :meth:`drug_context` a false friend needs (救火 beside 麻黄 and 桂枝 in 抱薪救火 is no drug's
        name)."""
        p = _params(cfg)
        cues = [c for c in cues if c and c != s]
        nameof, named = self._patterns["nameof"], self._patterns["named"]
        for i in offs:
            j = i + len(s)
            if (nameof.search(g[max(0, i - 4):i]) or named.match(g[j:j + 4])
                    or any(c in _around(g, i, j, p["cue_window"]) for c in cues)):
                return True
        return False

    def accept(self, g: str, exp: Expansion, yr: Window, *, cfg: Mapping[str, Any] | None = None) -> tuple[bool, str]:
        """Whether a side-queue passage is taken for an expansion: boundary, context, rival and validity gates.  The
        reason is ``ok`` or the gate that refused: ``absent``, ``candidate``, ``boundary``, ``context``, ``rival``,
        ``period``.

        The rival gate holds a name another drug may share to an own name in the passage and no rival's, and only
        where a rival may be meant: a referent whose window the passage's range misses is none (通草 in a passage of
        650 is 木通's, 通脱木 being 960 and later).  The ``gates`` ablation lifts the status, context and rival gates
        alike — every pair open, as if the name were nobody else's."""
        p = _params(cfg)
        ablate = _ablate(p)
        s = exp.surface
        if s not in g:
            return False, "absent"
        gates = "gates" not in ablate
        if exp.status == "candidate" and gates:
            return False, "candidate"
        rec = self.record(s)
        offs = self.free_offsets(g, s, rec.b if rec is not None and "boundary" not in ablate else (), yr)
        if not offs:
            return False, "boundary"
        if exp.status == "cue" and gates and not self.drug_context(g, s, offs, exp.cues, cfg=p):
            return False, "context"
        if exp.direction == DIRECTIONS[1] and gates:
            live = [names for window, names in exp.rivals if "period" in ablate or overlaps(window, yr)]
            if live:
                rest = g.replace(s, "|")  # names are read outside the name itself (木香 in 青木香 is no rival's)
                if not any(n in rest for n in exp.own) or any(n in rest for names in live for n in names):
                    return False, "rival"
        if "period" not in ablate and not overlaps(exp.valid, yr):
            return False, "period"
        return True, "ok"

    def bare(self, g: str, exp: Expansion, yr: Window, *, cfg: Mapping[str, Any] | None = None) -> bool:
        """Whether a side passage gives an expansion's name nothing beside it — a heading, a contents line, a list of
        formula names: with the formula names it writes left out (gate-form runs of at most 8 characters ending in one
        of :data:`FORMULA_ENDS`, but for a run that ends in the name or is a drug's own: 黄丹（炒）, 雷丸, 石膏), fewer
        than :data:`BARE_REST` Han characters (or ASCII letters and digits) outside the name, and the name, where it
        stands outside them, in no drug context (the herbs in 甘草干姜汤 are no list of drugs).  An order, never a gate:
        such passages follow the others of their drug in the side queue."""
        s = exp.surface
        runs = ["|" * len(run) if self._formula(run, s) else run for run in g.split("|")]
        if sum(len(run.replace(s, "").replace("|", "")) for run in runs) >= BARE_REST:
            return False
        rest = "|".join(runs)
        rec = self.record(s)
        offs = self.free_offsets(rest, s, rec.b if rec is not None else (), yr)
        return not self.drug_context(rest, s, offs, exp.cues, cfg=cfg)

    def _formula(self, run: str, s: str) -> bool:
        """Whether a gate-form run reads as a formula's name to :meth:`bare`: at most 8 characters ending in one of
        :data:`FORMULA_ENDS`, neither ending in the name ``s`` nor a drug's name itself (the herb set's or a record
        that names a drug: 石膏, 牡丹, 雷丸, 铅丹)."""
        if not (0 < len(run) <= 8 and run[-1] in FORMULA_ENDS) or run.endswith(s) or run in self._herbs:
            return False
        rec = self.records.get(run)
        return rec is None or rec.stop or not (rec.r or rec.ho is not None)

    def readings(self, s: str) -> list[Referent]:
        """The drugs a passage may read a name as: its record's referents that are not candidates (a doubtful pairing
        is listed, never a reading), then — when the name heads a drug none of them is — that drug, cued by its own
        names (乌头 is first 乌头, whatever else it may name).  Empty when no referent is left."""
        rec = self.record(s)
        if rec is None or rec.stop:
            return []
        refs = [ref for ref in rec.r if ref.st != "candidate"]
        if refs and rec.ho is not None and all(ref.g != rec.ho for ref in refs):
            refs.append(Referent(s, g=rec.ho, c=self.names(rec.ho)))
        return refs

    def reading(self, g: str, s: str, yr: Window, *,
                cfg: Mapping[str, Any] | None = None) -> tuple[Referent | None, float]:
        """The referent an ambiguous name reads as in a passage, by the ``Terminology.resolve`` formula, and its p.

        Per referent of :meth:`readings`: fit 1 when its window meets ``yr``, else max(0.15, 1 − gap/600); raw = fit ·
        (1 + cues) · 0.35^anti-cues, counting those within ``reading_window`` of a free occurrence; p = raw / Σ raw,
        to 4 places.  The best referent is the reading when its p is at least 0.5 and no other referent has the same
        rounded p (two at 0.5 are a tie); else None.  For the Worker's sake the arithmetic is spelled out: 0.35
        multiplied in once per anti-cue, Σ added left to right (``sum`` compensates), p rounded half up
        (:func:`_round4`)."""
        rec = self.record(s)
        refs = self.readings(s)
        if not refs:
            return None, 0.0
        width = _params(cfg)["reading_window"]
        near = [_around(g, i, i + len(s), width) for i in self.free_offsets(g, s, rec.b, yr)]
        raw = []
        for ref in refs:
            fit = 1.0 if overlaps(ref.v, yr) else max(0.15, 1.0 - _gap(ref.v, yr) / 600.0)
            cues = sum(1 for c in ref.c if c and c != s and any(c in t for t in near))
            damp = 1.0
            for c in ref.a:
                if c and c != s and any(c in t for t in near):
                    damp *= 0.35
            raw.append(fit * (1.0 + cues) * damp)
        total = 0.0
        for x in raw:
            total += x
        probs = [_round4(x / (total or 1.0)) for x in raw]
        best = max(probs)
        if best < 0.5 or probs.count(best) > 1:
            return None, best
        return refs[probs.index(best)], best

    def floor_flag(self, s: str, yr: Window, edition: Window | None) -> str | None:
        """``anachronism:<s><<floor>:edition|layer`` when a passage writes ``s`` before the name was in use: ``edition``
        when the passage's edition reaches the floor (a later edition's spelling), ``layer`` otherwise."""
        rec = self.record(s)
        if rec is None or rec.fl is None or yr is None or yr[1] is None or yr[1] >= rec.fl:
            return None
        later = edition is not None and edition[1] is not None and edition[1] >= rec.fl
        return f"anachronism:{s}<{rec.fl}:{'edition' if later else 'layer'}"

    # ---------------------------------------------------------------- expansion
    def expansions(self, q: Any, lex: Any, cfg: Mapping[str, Any]) -> list[Expansion]:
        """The one-hop expansions of a parsed query, ordered and capped.

        ``q`` is read for ``asked`` ({surface: term id or None}), ``after``, ``before``, ``all_surfaces()`` and
        ``groups``; ``lex`` (or None) for ``resolve`` and ``lookup``.  An asked alias reaches its referents' heads and
        their groups' spellings; an asked drug — a head, or a lexicon herb the name is not an alias of — reaches the
        other names of its groups; never further (地精 → 何首乌, never on to 夜合 → 合欢).  A stop name reaches no
        drug — not through its record, nor through a lexicon entry that files it as a herb (救火 under 景天) — but as a
        head it still reaches its own names.  Such a name is ``shared`` when it may also mean another drug within the
        query's window; that drug's window and names are then among its ``rivals``.  A name reached for two asked
        names is one expansion, for the first, the others in ``also``.

        A ``part_name`` pair joins two parts of one plant that are drugs of their own (青木香, the root, and 马兜铃,
        the fruit; 鸡舌香 and 丁香) unless the part name is a member of its drug (天麻 of 赤箭, ``ho``): it is shown,
        never searched, with why ``part``.

        Ordered by direction (alias→drug first), status (open first), passages (most first) and surface; the first
        ``cap`` attested ones are searched, cap = min(expansions, mask_bits − surfaces − component groups).  Names whose
        window misses the query's come next, with why ``period``; other parts last, with why ``part``."""
        p = _params(cfg)
        ablate = _ablate(p)
        after, before = q.after, q.before
        asked = dict(getattr(q, "asked", None) or {})
        searched = list(q.all_surfaces())
        taken = set(searched) | set(asked)
        found: list[tuple[tuple, Expansion]] = []
        excluded: list[tuple[tuple, Expansion]] = []
        parts: list[tuple[tuple, Expansion]] = []

        def add(e: Expansion, order: int, part: bool = False) -> None:
            key = (DIRECTIONS.index(e.direction), STATUSES.index(e.status), -e.n, e.surface, order, e.group, e.head)
            (parts if part else found if meets(e.valid, after, before) else excluded).append((key, e))

        def other_part(name: str, ref: Referent) -> bool:  # a part name that is not a member of its drug
            named = self.records.get(name)
            return ref.k == "part_name" and "gates" not in ablate and (named is None or named.ho != ref.g)

        for order, (s, term) in enumerate(asked.items()):
            rec = self.record(s)
            refs = rec.r if rec is not None and not rec.stop else []
            # alias → drug: the referent's head and its group's spellings (the head alone when the period is missed)
            for ref in refs:
                if ref.st == "candidate" and "gates" not in ablate:
                    continue
                valid = None if "period" in ablate else ref.v
                pairs = [(ref.h, ref)]
                part = other_part(s, ref)
                if meets(valid, after, before) and not part:
                    pairs += [(a, other) for a, other in self._groups.get(ref.g, ())
                              if other.k == "spelling" and other.st != "candidate"]
                for h, pair in pairs:
                    hrec = self.record(h)
                    if len(h) < 2 or h in taken or (hrec is not None and hrec.stop):
                        continue
                    add(Expansion(h, s, DIRECTIONS[0], ref.g, ref.h, kind=pair.k, status="open", valid=valid,
                                  shared=hrec is not None and len({r.g for r in hrec.r}) > 1, cues=list(ref.c),
                                  src=list(pair.src), wit=list(pair.w), n=hrec.n if hrec is not None else 0), order,
                        part)
            # drug → alias: the other names of the groups the asked name heads
            groups = set(self.groups_for(None, [s]))
            entry = lex.resolve(term) if lex is not None and term and not (rec is not None and rec.stop) else None
            if entry is not None and entry.category == "herb":
                groups |= set(self.groups_for(entry.term_id, entry.surfaces())) - {
                    ref.g for ref in refs if ref.k != "spelling"}
            for g in sorted(groups):
                own_names = self.names(g)
                for a, ref in self._groups.get(g, ()):
                    arec = self.records[a]
                    if arec.stop or len(a) < 2 or a in taken or (ref.st == "candidate" and "gates" not in ablate):
                        continue
                    # the drugs the name may also mean here (a referent whose window misses the query's is none)
                    own = [n for n in own_names if n != a]
                    rivals = [(None if "period" in ablate else r.v, sorted(set(self.names(r.g)) - set(own) - {a}))
                              for r in sorted(arec.r, key=lambda r: r.g)
                              if r.g != g and ("period" in ablate or meets(r.v, after, before))]
                    add(Expansion(a, s, DIRECTIONS[1], g, ref.h, kind=ref.k,
                                  status="open" if "gates" in ablate else ref.st,
                                  valid=None if "period" in ablate else ref.v, shared=bool(rivals), cues=list(ref.c),
                                  own=own, rivals=rivals, src=list(ref.src), wit=list(ref.w), n=arec.n), order,
                        other_part(a, ref))
        out: list[Expansion] = []
        seen: dict[str, Expansion] = {}
        for _, e in sorted(found, key=lambda t: t[0]):
            kept = seen.setdefault(e.surface, e)
            if kept is e:
                out.append(e)
            elif e.for_ != kept.for_ and e.for_ not in kept.also:
                kept.also.append(e.for_)
        groups_n = sum(len(gs) for gs in (getattr(q, "groups", None) or {}).values())
        cap = max(0, min(int(p["expansions"]), int(p["mask_bits"]) - len(searched) - groups_n))
        used = 0
        for e in out:
            if e.n <= 0:
                e.why = "unattested"
            elif used < cap:
                e.searched = True
                used += 1
            else:
                e.why = "cap"
        for why, rest in (("period", excluded), ("part", parts)):
            for _, e in sorted(rest, key=lambda t: t[0]):
                if seen.setdefault(e.surface, e) is e:
                    e.why = why
                    out.append(e)
        place = {s: i for i, s in enumerate(asked)}
        for e in out:
            e.also.sort(key=place.__getitem__)
        return out

    def view(self, q: Any, cfg: Mapping[str, Any], lex: Any = None,
             expansions: list[Expansion] | None = None) -> dict[str, Any]:
        """The ``query.aliases`` block: asked names with their referents, expansions, and what was left out; empty
        when there is nothing to show.  ``expansions`` are those :meth:`expansions` gave (computed when None).  An asked
        name is listed when it is an alias or names several drugs, the lexicon's included.  A stop name the question
        asks on its own (``q.stops``: {surface: term id or None}) is listed after them with every drug its record or the
        lexicon gives it, each of status ``stop``, and a ``note`` that the name is mostly an ordinary word: the layer
        searches nothing for it (:data:`STOP_NOTE`) — when the lexicon files it as a herb (救火 under 景天), today's search
        of that entry's names alone (:data:`STOP_NOTE_LEXICON`)."""
        p = _params(cfg)
        web = p["witness_scope"] == "web"
        exps = self.expansions(q, lex, p) if expansions is None else expansions
        asked = []
        for s, term in (getattr(q, "asked", None) or {}).items():
            rec = self.record(s)
            refs = self.referents(s, term, lex)
            groups = {ref.g for ref in refs}
            if not refs or ((rec is None or not rec.r) and len(groups) < 2):
                continue
            asked.append({"surface": s, "term": term, "ambiguous": len(groups) > 1,
                          "referents": [self._referent_view(ref, web) for ref in refs]})
        for s, term in (getattr(q, "stops", None) or {}).items():
            rec = self.record(s)
            refs = self.referents(s, term, lex, stop=True) if rec is not None and rec.stop else []
            entry = lex.entry(term) if lex is not None and term else None
            if refs:
                asked.append({"surface": s, "term": term, "ambiguous": len({ref.g for ref in refs}) > 1,
                              "referents": [{**self._referent_view(ref, web), "status": "stop"} for ref in refs],
                              "note": STOP_NOTE_LEXICON if entry is not None and entry.category == "herb" else STOP_NOTE})
        shown = [{"surface": e.surface, "for": e.for_, "direction": e.direction, "referent": e.head,
                  "kind": KINDS.get(e.kind, e.kind), "status": e.status, "searched": e.searched, "why": e.why}
                 for e in exps if e.why != "period"]
        excluded = [{"surface": e.surface, "for": e.for_, "why": e.why} for e in exps if e.why == "period"]
        if not (asked or shown or excluded):
            return {}
        return {"asked": asked, "expansions": shown, "excluded": excluded}

    def _referent_view(self, ref: Referent, web: bool) -> dict[str, Any]:
        wit = next((w for w in ref.w if w.web or not web), None)
        head = self.record(ref.h)
        return {"head": ref.h, "kind": KINDS.get(ref.k, ref.k), "status": ref.st,
                "valid": list(ref.v) if ref.v is not None else None, "floor": head.fl if head is not None else None,
                "source": self.source_labels(ref.src), "witness": wit.pid if wit is not None else None,
                "witness_year": _year(wit) if wit is not None else None,
                "credited": list(ref.cr) if ref.cr is not None else None}
