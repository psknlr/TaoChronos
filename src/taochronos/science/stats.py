"""Small, dependency-free statistics used by the pattern miner and statistician.

Everything is deterministic given a seed, so mined observations are reproducible.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any, Callable, Hashable, Iterable, Sequence


def rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


def normalize(counts: dict[Hashable, float]) -> dict[Hashable, float]:
    total = float(sum(counts.values()))
    return {k: v / total for k, v in counts.items()} if total else {}


def entropy(counts: dict[Hashable, float], base: float = 2.0) -> float:
    p = normalize(counts)
    return -sum(v * math.log(v, base) for v in p.values() if v > 0)


def jensen_shannon(a: dict[Hashable, float], b: dict[Hashable, float]) -> float:
    """JS divergence (base 2) in [0, 1] between two count/probability maps."""
    pa, pb = normalize(a), normalize(b)
    if not pa or not pb:
        return 0.0
    keys = set(pa) | set(pb)
    m = {k: 0.5 * (pa.get(k, 0.0) + pb.get(k, 0.0)) for k in keys}

    def kl(p: dict, q: dict) -> float:
        return sum(v * math.log(v / q[k], 2) for k, v in p.items() if v > 0)

    return max(0.0, min(1.0, 0.5 * kl(pa, m) + 0.5 * kl(pb, m)))


def cosine_counts(a: dict[Hashable, float], b: dict[Hashable, float]) -> float:
    keys = set(a) & set(b)
    num = sum(a[k] * b[k] for k in keys)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def jaccard(a: Iterable[Hashable], b: Iterable[Hashable]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if (sa or sb) else 0.0


def permutation_test(
    samples_a: Sequence[Sequence[Hashable]],
    samples_b: Sequence[Sequence[Hashable]],
    statistic: Callable[[Sequence[Sequence[Hashable]], Sequence[Sequence[Hashable]]], float],
    *,
    n: int = 999,
    seed: int = 0,
) -> tuple[float, float]:
    """Two-sample permutation test on the group labels. Returns (observed, p-value)."""
    observed = statistic(samples_a, samples_b)
    pooled = list(samples_a) + list(samples_b)
    na = len(samples_a)
    if na == 0 or len(samples_b) == 0:
        return observed, 1.0
    r = rng(seed)
    extreme = 0
    for _ in range(n):
        r.shuffle(pooled)
        if statistic(pooled[:na], pooled[na:]) >= observed - 1e-12:
            extreme += 1
    return observed, (extreme + 1) / (n + 1)


def context_jsd(samples_a: Sequence[Sequence[Hashable]], samples_b: Sequence[Sequence[Hashable]]) -> float:
    ca: Counter = Counter()
    cb: Counter = Counter()
    for s in samples_a:
        ca.update(s)
    for s in samples_b:
        cb.update(s)
    return jensen_shannon(ca, cb)


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact_greater(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher exact test p-value for over-representation of cell ``a`` in [[a, b], [c, d]]."""
    row1, col1, n = a + b, a + c, a + b + c + d
    lo, hi = max(0, row1 + col1 - n), min(row1, col1)
    denom = _log_comb(n, col1)
    p = 0.0
    for x in range(a, hi + 1):
        p += math.exp(_log_comb(row1, x) + _log_comb(n - row1, col1 - x) - denom)
    return min(1.0, p)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = lambda v: sum(v) / len(v),
                 *, n: int = 999, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    r = rng(seed)
    stats = sorted(stat([r.choice(values) for _ in values]) for _ in range(n))
    lo = stats[int((alpha / 2) * n)]
    hi = stats[min(n - 1, int((1 - alpha / 2) * n))]
    return lo, hi


def benjamini_hochberg(pvalues: dict[Hashable, float], q: float = 0.1) -> dict[Hashable, bool]:
    """False-discovery-rate control across many mined patterns."""
    items = sorted(pvalues.items(), key=lambda t: t[1])
    m = len(items)
    cutoff = 0
    for i, (_, p) in enumerate(items, start=1):
        if p <= q * i / m:
            cutoff = i
    keep = {k for k, _ in items[:cutoff]}
    return {k: k in keep for k in pvalues}


def max_statistic_permutation(
    groups: Sequence[Sequence[Sequence[Hashable]]],
    statistic: Callable[[Sequence[Sequence[Hashable]], Sequence[Sequence[Hashable]]], float],
    *,
    n: int = 499,
    seed: int = 0,
) -> tuple[float, int, float, list[float]]:
    """Selection-aware test of the largest difference between *adjacent* groups (e.g. periods).

    Picking the boundary with the largest statistic and then testing only that pair overstates significance (the
    boundary was chosen *because* it was largest).  Here the null is the maximum over every adjacent boundary of the
    statistic when the group labels are permuted (group sizes kept): p = P(max_perm ≥ observed max).
    Returns (observed max, index of its boundary, p-value, the observed series)."""
    sizes = [len(g) for g in groups]
    series = [statistic(groups[i], groups[i + 1]) for i in range(len(groups) - 1)]
    if not series:
        return 0.0, -1, 1.0, []
    observed = max(series)
    where = max(range(len(series)), key=lambda i: (series[i], i))
    pooled = [s for g in groups for s in g]
    r = rng(seed)
    extreme = 0
    for _ in range(n):
        r.shuffle(pooled)
        cuts, start = [], 0
        for size in sizes:
            cuts.append(pooled[start: start + size])
            start += size
        if max(statistic(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)) >= observed - 1e-12:
            extreme += 1
    return observed, where, (extreme + 1) / (n + 1), series


def leave_one_cluster_out(items_by_cluster: dict[Hashable, Sequence], fn: Callable[[list], float]) -> dict[str, Any]:
    """Recompute a statistic with each source family (cluster) left out in turn: how much the result rests on one
    family.  Returns the full value, the per-family values and the range."""
    everything = [x for items in items_by_cluster.values() for x in items]
    full = fn(everything)
    per = {str(k): fn([x for c, items in items_by_cluster.items() if c != k for x in items]) for k in items_by_cluster}
    values = list(per.values())
    return {"full": full, "without": per, "min": min(values) if values else full, "max": max(values) if values else full,
            "clusters": len(items_by_cluster)}


def cluster_bootstrap(items_by_cluster: dict[Hashable, Sequence], fn: Callable[[list], float], *, n: int = 499, alpha: float = 0.05,
                      seed: int = 0) -> tuple[float, float]:
    """Bootstrap interval that resamples whole source families (clusters), not single passages: dependent witnesses
    of one family are drawn together, so the interval reflects how many independent families there are."""
    clusters = list(items_by_cluster)
    if not clusters:
        return 0.0, 0.0
    r = rng(seed)
    stats = []
    for _ in range(n):
        drawn = [x for _c in range(len(clusters)) for x in items_by_cluster[r.choice(clusters)]]
        stats.append(fn(drawn))
    stats.sort()
    return stats[int((alpha / 2) * n)], stats[min(n - 1, int((1 - alpha / 2) * n))]
