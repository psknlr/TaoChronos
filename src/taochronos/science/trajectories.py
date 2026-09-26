"""Treatment trajectories: what physicians did visit after visit, across many case records.

A case is a sequence of visits, each a set of items (``principle:清热``, ``formula:银翘散``, ``added:麦冬``, ``finding:
脉数`` …).  Three views of many cases:

* **sequential patterns** — items that follow one another across visits in many cases (PrefixSpan: patterns grow by
  one item that occurs in a later visit of the same case; support = cases);
* **transitions** — what the next visit holds given what this one held, with the lift over the next visit's baseline;
* **outcome associations** — items used in cases that ended in recovery more (or less) often than the rest, with
  one-sided Fisher tests and Benjamini–Hochberg control.  Case records are written by their physicians and
  selected for publication: these are associations in a biased record, never evidence of efficacy.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Hashable

from .stats import benjamini_hochberg, fisher_exact_greater

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


__all__ = ["outcome_associations", "prefixspan", "transitions"]
