"""Treatment trajectories: what physicians did visit after visit, across many case records.

A case is a sequence of visits, each a set of items (``principle:清热``, ``formula:银翘散``, ``added:麦冬``, ``finding:
脉数`` …).  Three views of many cases:

* **sequential patterns** — items that follow one another across visits in many cases (PrefixSpan: patterns grow by
  one item that occurs in a later visit of the same case; support = cases);
* **transitions** — what the next visit holds given what this one held, with the lift over the next visit's baseline;
* **outcome associations** — items used in cases that ended in recovery more (or less) often than the rest, with
  one-sided Fisher tests and Benjamini–Hochberg control.  Case records are written by their physicians and
  selected for publication: these are associations in a biased record, never evidence of efficacy.

And three for exploring many cases at once:

* **weighted similarity** — two cases' presentations (sets of findings) compared by the cosine of their binary vectors
  weighted by inverse document frequency, so that a shared rare finding (脉代) counts for more than a shared common one
  (发热): the 类案 a reader looks for;
* **cross associations** — a left item and a right item in the same unit (a finding at a visit, a drug added at it)
  more often than chance: count, P(right | left), lift, one-sided Fisher, Benjamini–Hochberg;
* **group contrasts** — the items over-represented in one group of cases against the rest (a physician's cases, a
  period's, those treated with one formula): shares in and out, odds ratio, one-sided Fisher, Benjamini–Hochberg.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Hashable

from .stats import benjamini_hochberg, fisher_exact_greater, odds_ratio

Sequence_ = list[set[str]]


def prefixspan(sequences: list[Sequence_], *, min_support: int = 3, max_len: int = 4, top: int = 50) -> list[dict[str, Any]]:
    """Frequent sequential patterns ``a → b → c`` (each item in a later visit than the one before), by case support."""
    out: list[tuple[int, tuple[str, ...]]] = []

    def grow(prefix: tuple[str, ...], projected: list[tuple[int, int]]) -> None:
        # projected: (case, index of the visit where the prefix's last item was matched); extensions come after it
        support: dict[str, set[int]] = defaultdict(set)
        first: dict[tuple[str, int], int] = {}
        for case, at in projected:
            seen: set[str] = set()
            for v in range(at + 1, len(sequences[case])):
                for item in sequences[case][v]:
                    if item not in seen:
                        seen.add(item)
                        support[item].add(case)
                        first[(item, case)] = v
        for item, cases in sorted(support.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if len(cases) < min_support:
                continue
            pattern = prefix + (item,)
            out.append((len(cases), pattern))
            if len(pattern) < max_len:
                grow(pattern, [(c, first[(item, c)]) for c in sorted(cases)])

    grow((), [(i, -1) for i in range(len(sequences))])
    multi = [(n, p) for n, p in out if len(set(p)) >= 2]  # a repeated item (辛凉 → 辛凉) is continuation, not a pattern
    multi.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))
    return [{"pattern": list(p), "cases": n} for n, p in multi[:top]]


def transitions(sequences: list[Sequence_], *, min_count: int = 3, top: int = 50) -> list[dict[str, Any]]:
    """Item a in one visit, item b in the next: count, P(b | a) and lift = P(b | a) / P(b in a next visit).  Changes
    (a ≠ b) come first, by lift weighted towards frequent ones; continuations (the same item kept, ``same``) after."""
    pair: Counter = Counter()
    before: Counter = Counter()
    after: Counter = Counter()
    steps = 0
    for seq in sequences:
        for v in range(len(seq) - 1):
            steps += 1
            for a in seq[v]:
                before[a] += 1
            for b in seq[v + 1]:
                after[b] += 1
            for a in seq[v]:
                for b in seq[v + 1]:
                    pair[(a, b)] += 1
    rows = []
    for (a, b), n in pair.items():
        if n < min_count:
            continue
        p = n / before[a]
        base = after[b] / steps if steps else 0.0
        rows.append({"from": a, "to": b, "count": n, "p": round(p, 3), "lift": round(p / base, 3) if base else None,
                     "same": a == b})
    rows.sort(key=lambda r: (-(r["lift"] or 0) * min(1.0, r["count"] / 10), -r["count"], r["from"], r["to"]))
    changes = [r for r in rows if not r["same"]][:top]
    kept = sorted((r for r in rows if r["same"]), key=lambda r: (-r["count"], r["from"]))[: max(10, top // 5)]
    return changes + kept


def outcome_associations(cases: list[tuple[set[str], str]], *, positive: str = "improved", min_cases: int = 5,
                         q: float = 0.1, top: int = 40) -> list[dict[str, Any]]:
    """For each item: in how many cases with it the outcome was ``positive``, against the cases without it; one-sided
    Fisher tests both ways, significance after Benjamini–Hochberg (q)."""
    items: Counter = Counter()
    for used, _ in cases:
        items.update(used)
    total_pos = sum(1 for _, o in cases if o == positive)
    total = len(cases)
    rows: dict[Hashable, dict[str, Any]] = {}
    pvals: dict[Hashable, float] = {}
    for item, n in items.items():
        if n < min_cases or n == total:
            continue
        a = sum(1 for used, o in cases if item in used and o == positive)
        b = n - a
        c = total_pos - a
        d = total - n - c
        more = fisher_exact_greater(a, b, c, d)
        less = fisher_exact_greater(b, a, d, c)
        rows[item] = {"item": item, "cases": n, "positive": a, "rate": round(a / n, 3),
                      "rate_without": round(c / (total - n), 3) if total > n else None,
                      "direction": "more" if more < less else "less", "p": round(min(more, less), 6)}
        pvals[item] = min(1.0, 2 * min(more, less))
    keep = benjamini_hochberg(pvals, q) if pvals else {}
    out = [r | {"significant": keep.get(k, False)} for k, r in rows.items()]
    out.sort(key=lambda r: (not r["significant"], r["p"], -r["cases"], r["item"]))
    return out[:top]


def idf_weights(sets: list[set[str]]) -> dict[str, float]:
    """Each item's inverse document frequency over the sets, ln((N + 1) / (df + 1)) + 1: rare items weigh more."""
    df: Counter = Counter()
    for s in sets:
        df.update(s)
    n = len(sets)
    return {k: math.log((n + 1) / (v + 1)) + 1 for k, v in df.items()}


def weighted_cosine(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """The cosine of two sets as binary vectors weighted by ``idf`` (an item it lacks weighs as the rarest)."""
    if not a or not b:
        return 0.0
    top = max(idf.values(), default=1.0)
    w = lambda k: idf.get(k, top)  # noqa: E731
    shared = sum(w(k) ** 2 for k in a & b)
    if not shared:
        return 0.0
    return shared / math.sqrt(sum(w(k) ** 2 for k in a) * sum(w(k) ** 2 for k in b))


def cross_associations(units: list[tuple[set[str], set[str]]], *, min_count: int = 3, q: float = 0.1,
                       top: int = 40) -> list[dict[str, Any]]:
    """Left item a and right item b in the same unit: the count, P(b | a), the lift P(b | a) / P(b) and a one-sided
    Fisher test of b's over-representation among the units with a; significance after Benjamini–Hochberg (q)."""
    n = len(units)
    left: Counter = Counter()
    right: Counter = Counter()
    pair: Counter = Counter()
    for ls, rs in units:
        left.update(ls)
        right.update(rs)
        for a in ls:
            for b in rs:
                pair[(a, b)] += 1
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    pvals: dict[tuple[str, str], float] = {}
    for (a, b), k in pair.items():
        if k < min_count or a == b:
            continue
        na, nb = left[a], right[b]
        p = fisher_exact_greater(k, na - k, nb - k, n - na - nb + k)
        rows[(a, b)] = {"left": a, "right": b, "count": k, "left_units": na, "right_units": nb,
                        "p_right_given_left": round(k / na, 3), "lift": round(k * n / (na * nb), 3), "p": round(p, 6)}
        pvals[(a, b)] = p
    keep = benjamini_hochberg(pvals, q) if pvals else {}
    out = [r | {"significant": keep.get(key, False)} for key, r in rows.items()]
    out.sort(key=lambda r: (not r["significant"], -r["lift"] * min(1.0, r["count"] / 10), r["p"], r["left"], r["right"]))
    return out[:top]


def group_contrasts(groups: dict[str, list[set[str]]], *, min_cases: int = 3, q: float = 0.1,
                    top: int = 8) -> dict[str, list[dict[str, Any]]]:
    """For each group, the items its cases hold more often than the other groups' cases: cases with the item in and
    out of the group, the shares, the odds ratio (Woolf interval) and a one-sided Fisher test; significance after
    Benjamini–Hochberg over every group and item together (q)."""
    total: Counter = Counter()
    sizes = {g: len(cases) for g, cases in groups.items()}
    per: dict[str, Counter] = {}
    for g, cases in groups.items():
        c: Counter = Counter()
        for s in cases:
            c.update(s)
        per[g] = c
        total.update(c)
    n = sum(sizes.values())
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    pvals: dict[tuple[str, str], float] = {}
    for g, c in per.items():
        size = sizes[g]
        if not size or size == n:
            continue
        for item, k in c.items():
            out_k = total[item] - k
            if k < min_cases:
                continue
            if k * (n - size) <= out_k * size:  # held no more often than elsewhere: one-sided p ≥ ½, never significant —
                pvals[(g, item)] = 1.0         # counted for Benjamini–Hochberg as before, its exact test spared
                continue
            p = fisher_exact_greater(k, size - k, out_k, n - size - out_k)
            ratio = odds_ratio(k, size - k, out_k, n - size - out_k)
            rows[(g, item)] = {"item": item, "cases": k, "share": round(k / size, 3),
                               "share_elsewhere": round(out_k / (n - size), 3), "or": round(ratio["or"], 3),
                               "or_ci": [round(ratio["lo"], 3), round(ratio["hi"], 3)], "p": round(p, 6)}
            pvals[(g, item)] = p
    keep = benjamini_hochberg(pvals, q) if pvals else {}
    out: dict[str, list[dict[str, Any]]] = {g: [] for g in groups}
    for (g, item), r in rows.items():
        out[g].append(r | {"significant": keep.get((g, item), False)})
    for g in out:
        out[g] = sorted((r for r in out[g] if r["share"] > r["share_elsewhere"]),
                        key=lambda r: (not r["significant"], r["p"], -r["cases"], r["item"]))[:top]
    return out


__all__ = ["cross_associations", "group_contrasts", "idf_weights", "outcome_associations", "prefixspan", "transitions",
           "weighted_cosine"]
