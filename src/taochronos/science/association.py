"""D4 · Syndrome–Formula Hidden Association: association rules, link prediction, communities."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations
from typing import Callable, Iterable

from .stats import fisher_exact_greater, rng


def association_rules(
    transactions: list[tuple[str, list[str]]],
    *,
    lhs: Callable[[str], bool],
    rhs: Callable[[str], bool],
    min_support: int = 2,
    min_confidence: float = 0.5,
    max_lhs: int = 2,
) -> list[dict]:
    n = len(transactions)
    if n == 0:
        return []
    item_count: Counter = Counter()
    set_count: Counter = Counter()
    joint: Counter = Counter()
    for _, items in transactions:
        left = sorted({i for i in items if lhs(i)})
        right = sorted({i for i in items if rhs(i)})
        item_count.update(right)
        for size in range(1, max_lhs + 1):
            for x in combinations(left, size):
                set_count[x] += 1
                for y in right:
                    if y not in x:
                        joint[(x, y)] += 1
    rules = []
    for (x, y), sxy in joint.items():
        if sxy < min_support:
            continue
        sx, sy = set_count[x], item_count[y]
        conf = sxy / sx
        if conf < min_confidence:
            continue
        lift = conf / (sy / n)
        p = fisher_exact_greater(sxy, sx - sxy, sy - sxy, n - sx - sy + sxy)
        rules.append({"lhs": list(x), "rhs": y, "support": sxy, "confidence": round(conf, 4), "lift": round(lift, 4), "p_value": round(p, 5)})
    rules.sort(key=lambda r: (-r["lift"], -r["support"], r["lhs"], r["rhs"]))
    return rules


class CooccurrenceGraph:
    """Weighted clique expansion of the claim hypergraph."""

    def __init__(self, hyperedges: Iterable[list[str]]) -> None:
        self.adj: dict[str, Counter] = defaultdict(Counter)
        for members in hyperedges:
            uniq = sorted(set(members))
            for a, b in combinations(uniq, 2):
                self.adj[a][b] += 1
                self.adj[b][a] += 1

    def nodes(self) -> list[str]:
        return sorted(self.adj)

    def degree(self, node: str) -> int:
        return len(self.adj.get(node, {}))

    def linked(self, a: str, b: str) -> bool:
        return b in self.adj.get(a, {})

    def common(self, a: str, b: str) -> set[str]:
        return set(self.adj.get(a, {})) & set(self.adj.get(b, {}))


def link_prediction(
    graph: CooccurrenceGraph,
    *,
    left: Callable[[str], bool],
    right: Callable[[str], bool],
    method: str = "adamic_adar",
    k: int = 20,
    seed: int = 0,
    exclude_linked: bool = True,
) -> list[dict]:
    """Rank unlinked (left, right) pairs; each prediction carries its explanatory paths."""
    lefts = [n for n in graph.nodes() if left(n)]
    rights = [n for n in graph.nodes() if right(n)]
    r = rng(seed)
    scored = []
    for a in lefts:
        for b in rights:
            if a == b or (exclude_linked and graph.linked(a, b)):
                continue
            common = graph.common(a, b)
            if method == "popularity":
                score = float(graph.degree(a) * graph.degree(b))
            elif method == "random":
                score = r.random()
            elif not common:
                continue
            elif method == "common_neighbors":
                score = float(len(common))
            elif method == "resource_allocation":
                score = sum(1.0 / graph.degree(z) for z in common)
            else:  # adamic_adar
                score = sum(1.0 / math.log(graph.degree(z) + 1.0) for z in common)
            paths = sorted(common, key=lambda z: (graph.degree(z), z))[:3]
            scored.append({"left": a, "right": b, "score": round(score, 6), "via": paths})
    scored.sort(key=lambda s: (-s["score"], s["left"], s["right"]))
    return scored[:k]


def communities(graph: CooccurrenceGraph, *, min_weight: int = 1, max_iter: int = 25) -> list[list[str]]:
    """Deterministic weighted label propagation."""
    labels = {n: n for n in graph.nodes()}
    for _ in range(max_iter):
        changed = False
        for node in graph.nodes():
            weights: Counter = Counter()
            for nb, w in graph.adj[node].items():
                if w >= min_weight:
                    weights[labels[nb]] += w
            if not weights:
                continue
            best = sorted(weights.items(), key=lambda t: (-t[1], t[0]))[0][0]
            if best != labels[node]:
                labels[node] = best
                changed = True
        if not changed:
            break
    groups: dict[str, list[str]] = defaultdict(list)
    for node, label in labels.items():
        groups[label].append(node)
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=lambda g: (-len(g), g))
