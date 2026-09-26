"""Variant units: the witnesses' alignments to a base, flattened onto the base's coordinates.

Every witness is aligned to the base separately; the edits of all witnesses are then merged into *units* — the
smallest stretches of the base that contain every overlapping or touching edit — and each witness's reading of a
unit is simply the stretch of the witness aligned to it.  Readings are grouped by their normalised text, so a unit
records which witnesses agree on what (TEI's ``<app>``).  Long omissions are *lacunae* (missing text: the witness is
silent there, not in disagreement); long additions and long replaced blocks are *structural* (commentary, added or
different passages) — listed, but not used to group the witnesses.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from ....protocol.base import stable_id
from ....protocol.textual_criticism import Reading, VariantUnit
from .align import Op, WitnessText

FUNCTION_WORDS = set("之乎者也矣焉哉而其以于於所则乃且亦又即若如故夫盖此是斯兮耳尔曰云")
LACUNA = 40  # an omission this long is missing text, not a variant
MAX_UNIT = 24  # a longer lemma or reading is structural


@dataclass
class Projection:
    """One witness projected onto the base: where each base boundary falls in the witness."""

    witness: WitnessText
    ops: list[Op]
    left: list[int]  # base boundary → witness offset before any text the witness inserts there
    right: list[int]  # … after it
    lacunae: list[tuple[int, int]] = field(default_factory=list)  # base ranges the witness does not carry
    present: bytearray = field(default_factory=bytearray)  # base positions the witness carries
    structural: int = 0  # characters of long additions
    out_of_scope: int = 0  # witness characters before or after the aligned range

    @property
    def carried(self) -> int:
        return sum(self.present)


def project(base_len: int, ops: list[Op], witness: WitnessText, *, trim: bool = True) -> Projection:
    """Map base boundaries into the witness; with ``trim``, witness text before the first and after the last
    aligned character is out of scope (the base is a slice of a longer text), not an addition."""
    ops = list(ops)
    out_of_scope = 0
    if trim:
        while ops and ops[0][0] == "insert" and ops[0][1] == 0:
            out_of_scope += ops[0][4] - ops[0][3]
            ops.pop(0)
        while ops and ops[-1][0] == "insert" and ops[-1][1] == base_len:
            out_of_scope += ops[-1][4] - ops[-1][3]
            ops.pop()
    left: list[int | None] = [None] * (base_len + 1)
    right: list[int | None] = [None] * (base_len + 1)
    present = bytearray(base_len)
    lacunae: list[tuple[int, int]] = []
    structural = 0
    # base text before the witness begins or after it ends is missing, however short (a quotation starts late)
    edge = {i for i in (0, len(ops) - 1) if ops and ops[i][0] == "delete" and (ops[i][1] == 0 or ops[i][2] == base_len)}
    for k, (tag, b0, b1, w0, w1) in enumerate(ops):
        if left[b0] is None:
            left[b0] = w0
        if tag == "insert":
            right[b0] = w1
            if w1 - w0 >= LACUNA:
                structural += w1 - w0
            continue
        right[b0] = w0
        if tag == "equal":
            for t in range(1, b1 - b0):
                left[b0 + t] = right[b0 + t] = w0 + t
            present[b0:b1] = b"\x01" * (b1 - b0)
        elif tag == "delete":
            for t in range(1, b1 - b0):
                left[b0 + t] = right[b0 + t] = w0
            if b1 - b0 >= LACUNA or k in edge:
                lacunae.append((b0, b1))
            else:
                present[b0:b1] = b"\x01" * (b1 - b0)
        else:  # replace
            for t in range(1, b1 - b0):
                left[b0 + t] = right[b0 + t] = w0
            if b1 - b0 >= LACUNA and w1 - w0 >= LACUNA:
                lacunae.append((b0, b1))  # a different text here: nothing to collate
                structural += w1 - w0
            else:
                present[b0:b1] = b"\x01" * (b1 - b0)
        left[b1] = right[b1] = w1
    # boundaries no op reached (an empty alignment) fall back to their neighbours
    last = 0
    for p in range(base_len + 1):
        if left[p] is None:
            left[p] = last
        if right[p] is None:
            right[p] = left[p]
        last = right[p]
    return Projection(witness, ops, left, right, lacunae, present, structural, out_of_scope)  # type: ignore[arg-type]


def load_equivalents(classes: list[list[str]], normalize=lambda t: t) -> dict[str, str]:
    """Equivalence classes (each a list of characters) → character → the class's first member (normalised)."""
    out: dict[str, str] = {}
    for cls in classes:
        chars = [normalize(c) for c in cls if c]
        for ch in chars + list(cls):
            out.setdefault(ch, chars[0])
    return out


def counts(u: VariantUnit) -> bool:
    """Does the unit count for distances, groups and the stemma (not structural, not orthographic)?"""
    return not u.structural and u.kind != "orthographic"


def _edits(p: Projection, base: str) -> list[tuple[int, int]]:
    out = []
    lacunae = set(p.lacunae)
    ops = p.ops
    k = 0
    while k < len(ops):
        tag, b0, b1, w0, w1 = ops[k]
        if tag == "equal":
            k += 1
            continue
        if tag == "delete" and (b1 - b0 >= LACUNA or (b0, b1) in lacunae):
            k += 1
            continue
        if tag == "replace" and b1 - b0 >= LACUNA and w1 - w0 >= LACUNA:
            k += 1
            continue
        # 倒文: characters dropped here and written a few characters further on (呕逆 → 逆呕) are one transposition
        if k + 2 < len(ops) and ops[k + 1][0] == "equal" and ops[k + 1][2] - ops[k + 1][1] <= 3:
            nxt = ops[k + 2]
            moved = base[b0:b1] if tag == "delete" else p.witness.text[w0:w1]
            again = p.witness.text[nxt[3]:nxt[4]] if nxt[0] == "insert" else base[nxt[1]:nxt[2]]
            if {tag, nxt[0]} == {"delete", "insert"} and moved and moved == again and len(moved) <= 6:
                out.append((b0, nxt[2]))
                k += 3
                continue
        out.append((b0, b1))
        k += 1
    return out


def _lacunose(p: Projection, u0: int, u1: int) -> bool:
    for l0, l1 in p.lacunae:
        if l0 < max(u1, u0 + 1) and u0 < l1:
            return True
    return False


def _kind(lemma: str, reading: str) -> str:
    if not reading:
        return "omission"
    if not lemma:
        return "addition"
    if len(lemma) >= 2 and sorted(lemma) == sorted(reading):
        return "transposition"
    return "substitution"


def _cuts(centre: str, t: str) -> tuple[list[int], list[int], set[int]]:
    """``t`` aligned to ``centre``: for each centre boundary, the offset in ``t`` before (left) and after (right) any
    text ``t`` inserts there, and the boundaries where ``t`` can be cut (not inside a replacement of another length)."""
    m = len(centre)
    left: list[int | None] = [None] * (m + 1)
    right: list[int | None] = [None] * (m + 1)
    clean: set[int] = set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, centre, t, autojunk=False).get_opcodes():
        if left[i1] is None:
            left[i1] = j1
        clean.add(i1)
        if tag == "insert":
            right[i1] = j2
            continue
        right[i1] = j1
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(1, i2 - i1):
                left[i1 + k] = right[i1 + k] = j1 + k
                clean.add(i1 + k)
        elif tag == "delete":
            for k in range(1, i2 - i1):
                left[i1 + k] = right[i1 + k] = j1
                clean.add(i1 + k)
        left[i2] = right[i2] = j2
        clean.add(i2)
    for k in range(m + 1):  # an empty t: every boundary maps to 0
        if left[k] is None:
            left[k] = right[k] = 0
            clean.add(k)
    return left, right, clean  # type: ignore[return-value]


def _atomize(own: dict[str, tuple[str, str]], lemma_sig: str) -> list[tuple[int, int, dict[str, tuple[str, str]]]] | None:
    """Split a unit where the changes of several witnesses meet (C 人 · EFG 若之 · DH 人之: a substitution and an
    addition) into columns: every reading is aligned to the centre — the reading closest to all the others — and cut
    where all alignments can be cut.  Returns (lemma offset from, to, {witness: (text, raw)}) per varying column."""
    texts = list(dict.fromkeys(t for t, _ in own.values()))
    lemma = own[lemma_sig][0]
    if any(len(t) >= 2 and t != lemma and sorted(t) == sorted(lemma) for t in texts):
        return None  # a transposition is one unit

    def dist(a: str, b: str) -> int:
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        return len(a) + len(b) - 2 * sum(bl.size for bl in sm.get_matching_blocks())

    centre = min(texts, key=lambda t: (sum(dist(t, o) for o in texts), texts.index(t)))
    if not centre:
        return None
    maps = {t: _cuts(centre, t) for t in texts}
    cuts = sorted(set.intersection(*(c for _, _, c in maps.values())))
    columns: list[tuple[str, int, int]] = []
    for i, p in enumerate(cuts):
        columns.append(("insert", p, p))
        if i + 1 < len(cuts):
            columns.append(("span", p, cuts[i + 1]))
    out = []
    for kind, p, q in columns:
        col: dict[str, tuple[str, str]] = {}
        for sig, (t, raw) in own.items():
            left, right, _ = maps[t]
            a, b = (left[p], right[p]) if kind == "insert" else (right[p], left[q])
            col[sig] = (t[a:b], raw[a:b])
        if len({x for x, _ in col.values()}) < 2:
            continue
        left, right, _ = maps[lemma]
        c0, c1 = (left[p], right[p]) if kind == "insert" else (right[p], left[q])
        out.append((c0, c1, col))
    return out if len(out) > 1 else None


def build_units(base: WitnessText, projections: dict[str, Projection], *, prefix: str = "vu",
                equivalents: dict[str, str] | None = None) -> list[VariantUnit]:
    """Variant units over the base, readings grouped, the base's reading (the lemma) first.  Where the changes of
    several witnesses meet, the unit is split into columns (``_atomize``), so that each change groups the witnesses
    that made it.  With ``equivalents`` (character → class representative), a unit whose readings differ only by
    equivalent characters is *orthographic* (a spelling convention, weight 0.1, not used for the stemma)."""
    eq = equivalents or {}

    def canon(t: str) -> str:
        return "".join(eq.get(ch, ch) for ch in t)

    spans = sorted(e for p in projections.values() for e in _edits(p, base.text))
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    def unit(u0: int, u1: int, own: dict[str, tuple[str, str]], lacunose: list[str], part: int | None) -> VariantUnit:
        lemma, lemma_raw = own[base.siglum]
        groups: dict[str, list[tuple[str, str]]] = {}
        for sig, (t, raw) in own.items():
            groups.setdefault(t, []).append((sig, raw))
        readings = [Reading(text=t, witnesses=[s for s, _ in ws], forms={s: r for s, r in ws})
                    for t, ws in sorted(groups.items(), key=lambda kv: (kv[0] != lemma, -len(kv[1]), kv[0]))]
        kinds = {_kind(lemma, r.text) for r in readings[1:]}
        diff = set().union(*(set(r.text) ^ set(lemma) for r in readings[1:]))
        structural = len(lemma) > MAX_UNIT or any(len(r.text) > MAX_UNIT for r in readings)
        orthographic = bool(eq) and len({canon(r.text) for r in readings}) == 1
        pid, label, _ = base.locate(u0)
        key = (u0, u1) if part is None else (u0, u1, part)
        return VariantUnit(
            id=stable_id(prefix, base.book_id or base.siglum, *key), start=u0, end=u1, lemma=lemma,
            kind="orthographic" if orthographic else (kinds.pop() if len(kinds) == 1 else "mixed"), readings=readings,
            lacunose=lacunose, weight=0.1 if orthographic else (0.5 if diff and diff <= FUNCTION_WORDS else 1.0),
            structural=structural, passage_id=pid, locator=label,
            context=base.raw[max(0, u0 - 8):u0] + "〔" + lemma_raw + "〕" + base.raw[u1:u1 + 8])

    units: list[VariantUnit] = []
    for u0, u1 in merged:
        own: dict[str, tuple[str, str]] = {base.siglum: (base.text[u0:u1], base.raw[u0:u1])}
        lacunose: list[str] = []
        for sig, p in projections.items():
            if _lacunose(p, u0, u1):
                lacunose.append(sig)
                continue
            ws, we = p.left[u0], p.right[u1]
            own[sig] = (p.witness.text[ws:we], p.witness.raw[ws:we])
        distinct = {t for t, _ in own.values()}
        if len(distinct) < 2:
            continue
        short = all(len(t) <= MAX_UNIT for t in distinct)
        columns = _atomize(own, base.siglum) if len(distinct) >= 3 and short else None
        if columns is None:
            units.append(unit(u0, u1, own, lacunose, None))
        else:
            units += [unit(u0 + c0, u0 + c1, col, lacunose, k) for k, (c0, c1, col) in enumerate(columns)]
    return units


__all__ = ["FUNCTION_WORDS", "LACUNA", "MAX_UNIT", "Projection", "build_units", "counts", "load_equivalents", "project"]
