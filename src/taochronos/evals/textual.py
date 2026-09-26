"""TaoChronos-Eval for computational philology: collation and stemma on artificial traditions.

A real text (the demo corpus, normalised) is copied down a known stemma — two branches, three generations, one
witness contaminated from the other branch — with every copy adding known changes (substitutions, omissions,
additions of function words, transpositions).  The collation must find the changes, the tree must recover the
branches, the groups of shared readings must match the changes each branch introduced, and only the contaminated
witness may be flagged.  Artificial traditions are the standard test bed of computational stemmatology: the true
history is known exactly, which no real tradition offers.
"""

from __future__ import annotations

import bisect
import random
from typing import Any

from ..plugins.classics.collation import (
    WitnessText,
    align,
    build_units,
    clades,
    contamination,
    distances,
    groups,
    han_only,
    neighbour_joining,
    project,
    root,
    robinson_foulds,
    splits,
)
from .base import EvalContext, SuiteResult

POOL = "之而也其于以者所则乃又亦若故夫盖此是"
SWAP = "寒热虚实表里上下左右大小多少先后"

Token = tuple[str, float]  # (character, position in the archetype; insertions sit between)


def _copy(tokens: list[Token], rng: random.Random, n: int, events: list[float]) -> list[Token]:
    out = list(tokens)
    for _ in range(n):
        i = rng.randrange(1, len(out) - 2)
        op = rng.random()
        pos = out[i][1]
        if op < 0.45:  # substitution
            out[i] = (rng.choice(SWAP + POOL), pos)
        elif op < 0.7:  # omission of one or two characters
            del out[i: i + rng.choice((1, 1, 2))]
        elif op < 0.9:  # addition of a function word
            out.insert(i, (rng.choice(POOL), pos - 0.5))
        else:  # transposition of two characters
            out[i], out[i + 1] = out[i + 1], out[i]
        events.append(pos)
    return out


def _witness(siglum: str, tokens: list[Token]) -> WitnessText:
    text = "".join(ch for ch, _ in tokens)
    return WitnessText(siglum, siglum, text, text, [(0, i) for i in range(len(text))], [(siglum, siglum, "正文")])


def _tradition(text: str, seed: int, rate: int = 90) -> dict[str, Any]:
    rng = random.Random(seed)
    n = max(4, len(text) // rate)
    arche: list[Token] = [(ch, float(i)) for i, ch in enumerate(text)]
    events: dict[str, list[float]] = {}
    tokens: dict[str, list[Token]] = {}
    for node, parent in (("A", None), ("B", None), ("C", "A"), ("D", "A"), ("H", "A"), ("E", "B"), ("F", "B")):
        events[node] = list(events.get(parent, [])) if parent else []
        tokens[node] = _copy(tokens[parent] if parent else arche, rng, n, events[node])
    half = len(tokens["D"]) // 2  # G: copied from D, then from F from the middle on (contamination), with its own changes
    cut = next(i for i, (_, p) in enumerate(tokens["F"]) if p >= tokens["D"][half][1])
    events["G"] = [p for p in events["D"] if p < tokens["D"][half][1]] + [p for p in events["F"] if p >= tokens["D"][half][1]]
    tokens["G"] = _copy(tokens["D"][:half] + tokens["F"][cut:], rng, n // 2, events["G"])
    return {"tokens": tokens, "events": events, "archetype": arche}


def collation(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    normalize = h.pack.variants.normalize_text
    text = han_only(normalize("".join(p.text for p in h.corpus.passages())))[0][:4000]
    observed = ["C", "D", "E", "F", "G", "H"]
    clean = [s for s in observed if s != "G"]  # G is contaminated: it has no single place in a tree
    true_splits = {frozenset({"C", "D", "H"}), frozenset({"E", "F"})}
    details = []
    agg: dict[str, list[float]] = {k: [] for k in ("unit_recall", "unit_precision", "split_recall", "rf", "group_precision_top3", "group_precision",
                                                   "contamination_precision", "contamination_recall")}
    seeds = (1, 2, 3) if ctx.quick else (1, 2, 3, 4, 5)
    for seed in seeds:
        t = _tradition(text, seed)
        base = _witness("C", t["tokens"]["C"])
        origins = [p for _, p in t["tokens"]["C"]]
        projections = {s: project(len(base.text), align(base.text, _witness(s, t["tokens"][s]).text), _witness(s, t["tokens"][s]))
                       for s in observed if s != "C"}
        units = build_units(base, projections)
        # every change of any witness, placed in the base's coordinates
        true_pos = sorted({bisect.bisect_left(origins, p) for s in observed for p in t["events"][s]})
        found = 0
        for q in true_pos:
            if any(u.start - 1 <= q <= u.end + 1 for u in units):
                found += 1
        matched_units = sum(1 for u in units if any(u.start - 1 <= q <= u.end + 1 for q in true_pos[bisect.bisect_left(true_pos, u.start - 1):
                                                                                                    bisect.bisect_left(true_pos, u.end + 2)]))
        present = {"C": bytearray(b"\x01" * len(base.text))} | {s: p.present for s, p in projections.items()}
        # the groups the changes really define: for each change, the witnesses that carry it
        carriers: dict[float, set[str]] = {}
        for s_ in observed:
            for p_ in set(t["events"][s_]):
                carriers.setdefault(p_, set()).add(s_)
        true_groups = {frozenset(c) for c in carriers.values() if 2 <= len(c) < len(observed)}
        d = distances(units, observed, present)
        nj_clean = neighbour_joining(clean, d)
        inferred = splits(nj_clean, clean)
        canon = {x if sorted(clean)[0] not in x else frozenset(set(clean) - x) for x in true_splits}
        nj = neighbour_joining(observed, d)
        edges, _ = root(nj, observed)
        grouped = groups(units, observed)
        top = [frozenset(g["witnesses"]) for g in grouped[:3]]
        contaminated, _ = contamination(units, grouped, edges, observed)
        flagged = {c.witness for c in contaminated}
        agg["unit_recall"].append(found / len(true_pos) if true_pos else 1.0)
        agg["unit_precision"].append(matched_units / len(units) if units else 0.0)
        agg["split_recall"].append(len(inferred & canon) / len(canon))
        agg["rf"].append(robinson_foulds(inferred, canon) or 0.0)
        agg["group_precision_top3"].append(sum(1 for g in top if g in true_groups) / len(top) if top else 0.0)
        agg["group_precision"].append(sum(1 for g in grouped if frozenset(g["witnesses"]) in true_groups) / len(grouped) if grouped else 0.0)
        agg["contamination_precision"].append((len(flagged & {"G"}) / len(flagged)) if flagged else 1.0)
        agg["contamination_recall"].append(1.0 if "G" in flagged else 0.0)
        details.append({"seed": seed, "changes": len(true_pos), "units": len(units), "found": found,
                        "splits": sorted(sorted(x) for x in inferred), "flagged": sorted(flagged),
                        "top_groups": [g["witnesses"] for g in grouped[:3]], "clades": sorted(sorted(v) for v in clades(edges, observed).values() if 1 < len(v) < len(observed))})
    metrics = {k: round(sum(v) / len(v), 4) for k, v in agg.items()}
    metrics["traditions"] = len(seeds)
    return SuiteResult("collation", metrics, details, notes=[
        "artificial traditions copied from the demo corpus down a known stemma (two branches, a contaminated witness); "
        "base = witness C, as in real use; a change counts as found when a variant unit covers it; the tree is scored "
        "on the uncontaminated witnesses (a contaminated one has no single place in a tree)"])


__all__ = ["collation"]
