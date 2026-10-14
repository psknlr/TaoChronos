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
    "dose": r"^\|?[^|]{0,6}?[一二三四五六七八九十百千半两0-9]+[两钱分斤枚个升合片铢粒]",  # 将军二两 · 将军（炙）三两
    "each": r"^[^|]{0,8}?各[一二三四五六七八九十百半等]",  # 将军芒硝各三两
    "prep": r"^\|[^|]{0,8}?(?:炒|炙|去|研|制|焙|煨|洗|切|熬|烧|酒|醋|锉|碎|捣|浸|蒸)",  # 将军（酒洗）
    "nameof": r"(?:一名|又名|亦名|俗名|俗呼|名曰)$",  # 大黄一名将军
}
# source id → how an answer credits it; the CC0 别名录 always with 中醫笈成
SOURCE_LABELS: dict[str, str] = {
    "bielu-jc": "别名录（中醫笈成）", "curated": "编者审定", "store": "古籍互证", "shiming": "纲目释名", "taboo": "避讳",
    "lexicon": "词表", "bielu-gb": "别名录（GB本）", "hurb": "hurbTable", "ntu40k": "NTU 40K",
}

Window = tuple[int | None, int | None]  # [from, to) in years; None leaves that side open
Blocker = str | tuple[str, int | None, int | None]  # a string containing a name that is not it, with a year window


def _window(value: Any) -> Window | None:
    """A window as stored: None when it bounds nothing."""
    if value is None:
        return None
    lo, hi = value
    return None if lo is None and hi is None else (lo, hi)


def _blocker(value: Any) -> Blocker:
    """A blocker read from or written to the file: the bare string when its window bounds nothing."""
    if isinstance(value, str):
        return value
    text, lo, hi = value
    return text if lo is None and hi is None else (text, lo, hi)


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
        return [self.pid, self.y0, self.y1, self.kind, 1 if self.web else 0]

    @classmethod
    def from_json(cls, row: Iterable[Any]) -> Witness:
        pid, y0, y1, kind, web = row
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
        out: dict[str, Any] = {"h": self.h, "src": list(self.src)}
        if self.g != self.h:
            out["g"] = self.g
        if self.t is not None:
            out["t"] = self.t
        if self.k != "alias":
            out["k"] = self.k
        if self.st != "open":
            out["st"] = self.st
        if _window(self.v) is not None:
            out["v"] = list(self.v)
        if self.c != [self.h]:
            out["c"] = list(self.c)
        if self.a:
            out["a"] = list(self.a)
        if self.w:
            out["w"] = [w.to_json() for w in self.w]
        if self.cr is not None:
            out["cr"] = list(self.cr)
        if self.nt:
            out["nt"] = self.nt
        return out

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Referent:
        return cls(
            h=d.get("h") or "",
            g=d.get("g") or "",
            t=d.get("t"),
            k=d.get("k", "alias"),
            st=d.get("st", "open"),
            v=_window(d.get("v")),
            c=list(d["c"]) if "c" in d else None,
            a=list(d.get("a") or ()),
            src=list(d.get("src") or ()),
            w=[Witness.from_json(w) for w in d.get("w") or ()],
            cr=tuple(d["cr"]) if d.get("cr") is not None else None,
            nt=d.get("nt") or "",
        )


@dataclass
class AliasRecord:
    """A normalised surface and every drug it names."""

    s: str  # the surface, normalised, ≥ 2 Han characters
    raw: list[str] | None = None  # raw spellings seen, ≤ 4 (default [s])
    stop: bool = False  # a false friend (小便, 月经): never expanded, never listed
    n: int = 0  # passages with a free occurrence in the build store (jc_c030 left out)
    sh: float = 0.0  # the share of those passages in drug context (2 decimals)
    b: list[Blocker] = field(default_factory=list)  # ordered by store frequency, ≤ 24
    fl: int | None = None  # soft first-use floor: earlier passages are flagged, never filtered
    flb: str | None = None  # the floor's basis: "taboo:<rule id>" or "curated"
    ho: str | None = None  # the group id when s is a referent's head
    r: list[Referent] = field(default_factory=list)  # referents (empty when stop or a head only)

    def __post_init__(self) -> None:
        if self.raw is None:
            self.raw = [self.s]

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"s": self.s}
        if self.raw != [self.s]:
            out["raw"] = list(self.raw)
        if self.stop:
            out["stop"] = True
        if self.n:
            out["n"] = self.n
        if round(self.sh, 2):
            out["sh"] = round(self.sh, 2)
        blockers = [_blocker(b) for b in self.b]
        if blockers:
            out["b"] = [b if isinstance(b, str) else list(b) for b in blockers]
        if self.fl is not None:
            out["fl"] = self.fl
        if self.flb is not None:
            out["flb"] = self.flb
        if self.ho is not None:
            out["ho"] = self.ho
        if self.r:
            out["r"] = [ref.to_json() for ref in self.r]
        return out

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> AliasRecord:
        return cls(
            s=d.get("s") or "",
            raw=list(d["raw"]) if "raw" in d else None,
            stop=bool(d.get("stop", False)),
            n=int(d.get("n", 0)),
            sh=float(d.get("sh", 0)),
            b=[_blocker(b) for b in d.get("b") or ()],
            fl=d.get("fl"),
            flb=d.get("flb"),
            ho=d.get("ho"),
            r=[Referent.from_json(ref) for ref in d.get("r") or ()],
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
    shared: bool = False  # the name denotes other drugs too
    cues: list[str] = field(default_factory=list)
    own: list[str] = field(default_factory=list)  # the group's other names
    rivals: list[str] = field(default_factory=list)  # names of the other drugs the name denotes
    src: list[str] = field(default_factory=list)
    wit: list[Witness] = field(default_factory=list)
    n: int = 0
    searched: bool = False
    why: str | None = None  # why it was not searched: "cap", "unattested" or "period" (outside the query's window)


# --------------------------------------------------------------------------- the file
def _counts(records: list[AliasRecord]) -> dict[str, int]:
    refs = [ref for rec in records for ref in rec.r]
    out = {"surfaces": len(records), "pairs": len(refs), "stop": sum(rec.stop for rec in records)}
    out.update({st: sum(ref.st == st for ref in refs) for st in STATUSES})
    return out


def dumps_records(records: Iterable[AliasRecord], meta: Mapping[str, Any] | None = None) -> str:
    """The file's text: the header, then the records by surface in code-point order.  ``meta`` goes into the header
    (store, normalizer, lexicon, coverage); its format, version, sources and counts are those of the records."""
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
    """The header (empty when the text has none) and the records of an alias file.  A line that is not a record, a
    header elsewhere than first, or another format or a newer version raises ``ValueError``; what a record says is
    judged by :class:`AliasIndex`."""
    header: dict[str, Any] = {}
    records: list[AliasRecord] = []
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
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
            header = dict(obj["_header"])
            if header.get("format") != FORMAT or int(header.get("version", 0)) > VERSION:
                raise ValueError(f"{origin}: {header.get('format')} v{header.get('version')} is not {FORMAT} "
                                 f"v{VERSION} or older")
            continue
        try:
            records.append(AliasRecord.from_json(obj))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{origin}:{no}: malformed record ({exc})") from None
    return header, records


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


def _around(g: str, i: int, j: int, width: int) -> str:
    """The ``width`` characters on each side of ``g[i:j]``, joined by a break so nothing matches across the name."""
    return g[max(0, i - width):i] + "|" + g[j:j + width]


def _params(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    return {**DEFAULT_ALIAS, **(cfg or {})}


def _year(w: Witness) -> float | int | None:
    """A witness's year as answers show it: the middle of its range."""
    if w.y0 is None or w.y1 is None:
        return w.y0 if w.y1 is None else w.y1
    mid = (w.y0 + w.y1) / 2
    return int(mid) if mid == int(mid) else mid


def source_labels(ids: Iterable[str]) -> list[str]:
    """How an answer credits sources (:data:`SOURCE_LABELS`; an unknown id stands for itself)."""
    return [SOURCE_LABELS.get(i, i) for i in ids]


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
    record with it when none of its referents is left)."""

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

    def referents(self, s: str, term: str | None = None, lex: Any = None) -> list[Referent]:
        """The drugs an asked surface may name: its record's referents, then the lexicon's herb entries for it (its own
        entry first, the others by term id) whose group none of them is in, as ``lexicon`` referents (百枝 → 狗脊, 防风)."""
        rec = self.record(s)
        if rec is not None and rec.stop:
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
            refs.append(Referent(entry.term, g=g, t=entry.term_id, src=["lexicon"]))
            seen.add(g)
        return refs

    def scan(self, norm: str) -> list[tuple[int, int, str]]:
        """Alias and head surfaces in normalised text, ``(start, end, surface)``: longest first, left to right, stop
        names left out."""
        out: list[tuple[int, int, str]] = []
        i, n = 0, len(norm)
        while i < n:
            for length in range(min(self.max_len, n - i), 1, -1):
                rec = self.records.get(norm[i:i + length])
                if rec is not None and not rec.stop and (rec.r or rec.ho is not None):
                    out.append((i, i + length, rec.s))
                    i += length
                    break
            else:
                i += 1
        return out

    # ---------------------------------------------------------------- gates
    def free_offsets(self, g: str, s: str, blockers: Iterable[Blocker], yr: Window) -> list[int]:
        """Offsets of ``s`` in gate-form text ``g`` not covered by a blocker whose window overlaps ``yr``."""
        live = []
        for b in blockers:
            text, window = (b, None) if isinstance(b, str) else (b[0], (b[1], b[2]))
            if s in text and text != s and overlaps(window, yr):
                live.append(text)
        out = []
        i = g.find(s) if s else -1
        while i >= 0:
            if not any(_inside(g, i, s, b) for b in live):
                out.append(i)
            i = g.find(s, i + 1)
        return out

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
        dose, each, prep, nameof = (self._patterns[key] for key in ("dose", "each", "prep", "nameof"))
        for i in offs:
            j = i + len(s)
            after = g[j:j + 12]
            if dose.match(after) or each.match(after) or prep.match(after) or nameof.search(g[max(0, i - 4):i]):
                return True
            near = _around(g, i, j, p["cue_window"])
            if any(c in near for c in cues):
                return True
            if self._herb_count(_around(g, i, j, p["list_window"])) >= 2:
                return True
        return False

    def accept(self, g: str, exp: Expansion, yr: Window, *, cfg: Mapping[str, Any] | None = None) -> tuple[bool, str]:
        """Whether a side-queue passage is taken for an expansion: boundary, context, rival and validity gates.  The
        reason is ``ok`` or the gate that refused: ``absent``, ``candidate``, ``boundary``, ``context``, ``rival``,
        ``period``."""
        p = _params(cfg)
        ablate = set(p["ablate"])
        s = exp.surface
        if s not in g:
            return False, "absent"
        if exp.status == "candidate" and "gates" not in ablate:
            return False, "candidate"
        rec = self.record(s)
        offs = self.free_offsets(g, s, rec.b if rec is not None and "boundary" not in ablate else (), yr)
        if not offs:
            return False, "boundary"
        if exp.status == "cue" and "gates" not in ablate and not self.drug_context(g, s, offs, exp.cues, cfg=p):
            return False, "context"
        if exp.direction == DIRECTIONS[1] and exp.shared:
            rest = g.replace(s, "|")  # names are read outside the name itself (木香 in 青木香 is no rival's)
            if not any(n in rest for n in exp.own) or any(n in rest for n in exp.rivals):
                return False, "rival"
        if "period" not in ablate and not overlaps(exp.valid, yr):
            return False, "period"
        return True, "ok"

    def reading(self, g: str, s: str, yr: Window, *,
                cfg: Mapping[str, Any] | None = None) -> tuple[Referent | None, float]:
        """The referent an ambiguous name reads as in a passage, by the ``Terminology.resolve`` formula, and its p.

        Per referent: fit 1 when its window meets ``yr``, else max(0.15, 1 − gap/600); raw = fit · (1 + cues) ·
        0.35^anti-cues, counting those within ``reading_window`` of a free occurrence; p = raw / Σ raw, to 4 places.
        The best referent is the reading when its p is at least 0.5 and no other referent has it; else None."""
        rec = self.record(s)
        if rec is None or rec.stop or not rec.r:
            return None, 0.0
        width = _params(cfg)["reading_window"]
        near = [_around(g, i, i + len(s), width) for i in self.free_offsets(g, s, rec.b, yr)]
        raw = []
        for ref in rec.r:
            fit = 1.0 if overlaps(ref.v, yr) else max(0.15, 1.0 - _gap(ref.v, yr) / 600.0)
            cues = sum(1 for c in ref.c if c and c != s and any(c in t for t in near))
            anti = sum(1 for c in ref.a if c and c != s and any(c in t for t in near))
            raw.append(fit * (1.0 + cues) * (0.35 ** anti))
        total = sum(raw) or 1.0
        probs = [round(x / total, 4) for x in raw]
        best = max(probs)
        if best < 0.5 or probs.count(best) > 1:
            return None, best
        return rec.r[probs.index(best)], best

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
        other names of its groups; never further (地精 → 何首乌, never on to 夜合 → 合欢).  Such a name is ``shared``
        when it may also mean another drug within the query's window, whose names are then its ``rivals``.

        Ordered by direction (alias→drug first), status (open first), passages (most first) and surface; the first
        ``cap`` attested ones are searched, cap = min(expansions, mask_bits − surfaces − component groups).  Names whose
        window misses the query's come last, with why ``period``."""
        p = _params(cfg)
        ablate = set(p["ablate"])
        after, before = q.after, q.before
        asked = dict(getattr(q, "asked", None) or {})
        searched = list(q.all_surfaces())
        taken = set(searched) | set(asked)
        found: list[tuple[tuple, Expansion]] = []
        excluded: list[tuple[tuple, Expansion]] = []

        def add(e: Expansion, order: int) -> None:
            key = (DIRECTIONS.index(e.direction), STATUSES.index(e.status), -e.n, e.surface, order, e.group, e.head)
            (found if meets(e.valid, after, before) else excluded).append((key, e))

        for order, (s, term) in enumerate(asked.items()):
            rec = self.record(s)
            if rec is not None and rec.stop:
                continue
            refs = rec.r if rec is not None else []
            # alias → drug: the referent's head and its group's spellings (the head alone when the period is missed)
            for ref in refs:
                if ref.st == "candidate" and "gates" not in ablate:
                    continue
                valid = None if "period" in ablate else ref.v
                pairs = [(ref.h, ref)]
                if meets(valid, after, before):
                    pairs += [(a, other) for a, other in self._groups.get(ref.g, ())
                              if other.k == "spelling" and other.st != "candidate"]
                for h, pair in pairs:
                    hrec = self.record(h)
                    if len(h) < 2 or h in taken or (hrec is not None and hrec.stop):
                        continue
                    add(Expansion(h, s, DIRECTIONS[0], ref.g, ref.h, kind=pair.k, status="open", valid=valid,
                                  shared=hrec is not None and len({r.g for r in hrec.r}) > 1, cues=list(ref.c),
                                  src=list(pair.src), wit=list(pair.w), n=hrec.n if hrec is not None else 0), order)
            # drug → alias: the other names of the groups the asked name heads
            groups = set(self.groups_for(None, [s]))
            entry = lex.resolve(term) if lex is not None and term else None
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
                    others = sorted({r.g for r in arec.r
                                     if r.g != g and ("period" in ablate or meets(r.v, after, before))})
                    own = [n for n in own_names if n != a]
                    rivals = sorted({n for o in others for n in self.names(o)} - set(own) - {a})
                    add(Expansion(a, s, DIRECTIONS[1], g, ref.h, kind=ref.k,
                                  status="open" if "gates" in ablate else ref.st,
                                  valid=None if "period" in ablate else ref.v, shared=bool(others), cues=list(ref.c),
                                  own=own, rivals=rivals, src=list(ref.src), wit=list(ref.w), n=arec.n), order)
        out: list[Expansion] = []
        seen: set[str] = set()
        for _, e in sorted(found, key=lambda t: t[0]):
            if e.surface not in seen:
                seen.add(e.surface)
                out.append(e)
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
        for _, e in sorted(excluded, key=lambda t: t[0]):
            if e.surface not in seen:
                seen.add(e.surface)
                e.why = "period"
                out.append(e)
        return out

    def view(self, q: Any, cfg: Mapping[str, Any], lex: Any = None,
             expansions: list[Expansion] | None = None) -> dict[str, Any]:
        """The ``query.aliases`` block: asked names with their referents, expansions, and what was left out; empty
        when there is nothing to show.  ``expansions`` are those :meth:`expansions` gave (computed when None).  An asked
        name is listed when it is an alias or names several drugs, the lexicon's included."""
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
                "source": source_labels(ref.src), "witness": wit.pid if wit is not None else None,
                "witness_year": _year(wit) if wit is not None else None,
                "credited": list(ref.cr) if ref.cr is not None else None}
