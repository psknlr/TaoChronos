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
    """One-sided Fisher exact test p-value for over-representation of cell ``a`` in [[a, b], [c, d]].

    Past the mode the terms only fall: once one is below 1e-17 of the sum, it and every later one leave the sum unchanged
    in double precision (each under half its last place), so the loop stops there — the same value, without the
    hundreds of vanishing terms a large table has."""
    row1, col1, n = a + b, a + c, a + b + c + d
    lo, hi = max(0, row1 + col1 - n), min(row1, col1)
    denom = _log_comb(n, col1)
    mode = (row1 + 1) * (col1 + 1) // (n + 2)
    p = 0.0
    for x in range(a, hi + 1):
        term = math.exp(_log_comb(row1, x) + _log_comb(n - row1, col1 - x) - denom)
        if x > mode and term <= p * 1e-17:
            break
        p += term
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


# ------------------------------------------------------------------ tests and measures for figures and tables
def _gamma_q(a: float, x: float) -> float:
    """The regularized upper incomplete gamma function Q(a, x): a series below a + 1, a continued fraction above."""
    if x <= 0:
        return 1.0
    log_front = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        term = total = 1.0 / a
        ap = a
        for _ in range(1000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return min(1.0, max(0.0, 1.0 - total * math.exp(log_front)))
    tiny = 1e-300
    b = x + 1 - a
    c, d = 1 / tiny, 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        step = d * c
        h *= step
        if abs(step - 1) < 1e-15:
            break
    return min(1.0, max(0.0, math.exp(log_front) * h))


def chi2_sf(x: float, df: int) -> float:
    """P(X ≥ x) for a chi-square variable with ``df`` degrees of freedom."""
    return _gamma_q(df / 2, x / 2) if df > 0 else float("nan")


def _beta_cf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (tiny if abs(d) < tiny else d)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (tiny if abs(d) < tiny else d)
        c = 1 + aa / c
        c = tiny if abs(c) < tiny else c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (tiny if abs(d) < tiny else d)
        c = 1 + aa / c
        c = tiny if abs(c) < tiny else c
        step = d * c
        h *= step
        if abs(step - 1) < 1e-15:
            break
    return h


def beta_inc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _beta_cf(a, b, x) / a
    return 1 - front * _beta_cf(b, a, 1 - x) / b


def t_two_sided(t: float, df: float) -> float:
    """Two-sided P of Student's t with ``df`` degrees of freedom."""
    if df <= 0:
        return float("nan")
    return min(1.0, beta_inc(df / 2, 0.5, df / (df + t * t)))


def ranks(values: Sequence[float]) -> tuple[list[float], float]:
    """Ranks from 1 (ties share their mean rank) and the tie term Σ(t³ − t)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    ties = 0.0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    return out, ties


def kruskal_wallis(groups: Sequence[Sequence[float]]) -> dict[str, Any] | None:
    """Kruskal–Wallis test that the groups come from one distribution: H corrected for ties, its degrees of freedom,
    P by the chi-square approximation, the number of values and ε² = H / (n − 1) (the share of rank variance between
    groups).  None with fewer than two non-empty groups or when every value is the same."""
    groups = [list(g) for g in groups if len(g)]
    if len(groups) < 2:
        return None
    pooled = [v for g in groups for v in g]
    n = len(pooled)
    r, ties = ranks(pooled)
    correction = 1 - ties / (n ** 3 - n) if n > 1 else 0.0
    if correction <= 0:
        return None
    h, at = 0.0, 0
    for g in groups:
        h += sum(r[at: at + len(g)]) ** 2 / len(g)
        at += len(g)
    h = (12 / (n * (n + 1)) * h - 3 * (n + 1)) / correction
    df = len(groups) - 1
    return {"h": round(h, 3), "df": df, "p": chi2_sf(h, df), "n": n, "epsilon2": round(h / (n - 1), 4) if n > 1 else None}


def spearman(x: Sequence[float], y: Sequence[float]) -> dict[str, Any] | None:
    """Spearman's ρ (ranks, ties averaged) with its two-sided P (t approximation, n − 2 degrees of freedom).  None
    with fewer than four pairs or when either variable does not vary."""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 4:
        return None
    rx, _ = ranks([a for a, _ in pairs])
    ry, _ = ranks([b for _, b in pairs])
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    rho = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))
    p = 0.0 if abs(rho) >= 1 else t_two_sided(rho * math.sqrt((n - 2) / (1 - rho * rho)), n - 2)
    return {"rho": round(rho, 4), "p": p, "n": n}


def odds_ratio(a: int, b: int, c: int, d: int, z: float = 1.96) -> dict[str, float]:
    """The odds ratio of [[a, b], [c, d]] with its Woolf (log) interval; 0.5 is added to every cell when one is zero
    (Haldane–Anscombe)."""
    corrected = 0 in (a, b, c, d)
    if corrected:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    ratio = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    log_or = math.log(ratio)
    return {"or": ratio, "lo": math.exp(log_or - z * se), "hi": math.exp(log_or + z * se), "corrected": corrected}


def average_linkage(distance: Sequence[Sequence[float]]) -> list[list[float]]:
    """Agglomerative clustering with average linkage (UPGMA) on a square distance matrix: the merges in scipy's linkage
    form, [cluster a, cluster b, height, size] — clusters 0 … n − 1 are the items, n + i the i-th merge; of equal
    heights the pair of smallest ids merges first."""
    n = len(distance)
    members: dict[int, list[int]] = {i: [i] for i in range(n)}
    dist: dict[tuple[int, int], float] = {(i, j): float(distance[i][j]) for i in range(n) for j in range(i + 1, n)}
    merges: list[list[float]] = []
    nxt = n
    while len(members) > 1:
        (a, b), h = min(dist.items(), key=lambda kv: (kv[1], kv[0]))
        na, nb = len(members[a]), len(members[b])
        new = members.pop(a) + members.pop(b)
        del dist[(a, b)]
        for k in members:  # the average distance of the new cluster's items to k's
            da = dist.pop((min(a, k), max(a, k)))
            db = dist.pop((min(b, k), max(b, k)))
            dist[(k, nxt)] = (na * da + nb * db) / (na + nb)
        merges.append([a, b, round(h, 6), len(new)])
        members[nxt] = new
        nxt += 1
    return merges


def leaf_order(merges: Sequence[Sequence[float]], n: int) -> list[int]:
    """The items in the order a dendrogram draws them: of each merge, the cluster holding the earlier item first (items
    given most frequent first stay near the top)."""
    if n == 0:
        return []
    if not merges:
        return list(range(n))
    first = list(range(n))  # the smallest item of each cluster
    for a, b, _h, _s in merges:
        first.append(min(first[int(a)], first[int(b)]))
    out: list[int] = []
    stack = [n + len(merges) - 1]
    while stack:
        c = stack.pop()
        if c < n:
            out.append(c)
        else:
            a, b = int(merges[c - n][0]), int(merges[c - n][1])
            stack += [b, a] if first[a] <= first[b] else [a, b]
    return out


def cut_tree(merges: Sequence[Sequence[float]], n: int, k: int) -> list[int]:
    """The cluster of each item when the tree is cut into ``k`` clusters (numbered 0 … k − 1 in leaf order)."""
    k = max(1, min(k, n))
    parent = list(range(n + len(merges)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, (a, b, _h, _s) in enumerate(merges[: n - k]):
        parent[find(int(a))] = n + i
        parent[find(int(b))] = n + i
    roots: dict[int, int] = {}
    out = [0] * n
    for item in leaf_order(merges, n):
        out[item] = roots.setdefault(find(item), len(roots))
    return out


def largest_gap(merges: Sequence[Sequence[float]], n: int, *, k_min: int = 2, k_max: int = 8) -> int:
    """How many clusters to cut a tree into: where the next merge would be the largest jump in height (between
    ``k_min`` and ``k_max`` clusters) — the usual reading of a dendrogram's long branches."""
    heights = [float(m[2]) for m in merges]
    best, best_k = -1.0, k_min
    for k in range(max(2, k_min), min(k_max, n) + 1):
        # with k clusters the last merge made is the (n − k)-th; the next one is at heights[n − k]
        if n - k < 0 or n - k >= len(heights) or n - k - 1 < 0:
            continue
        gap = heights[n - k] - heights[n - k - 1]
        if gap > best + 1e-12:
            best, best_k = gap, k
    return best_k


def loess(xs: Sequence[float], ys: Sequence[float], *, span: float = 0.6, points: int = 40) -> list[list[float]]:
    """A LOESS curve (local linear regression with tricube weights, no robustness steps) at ``points`` evenly spaced x
    over the data's range: [[x, ŷ], …].  Empty with fewer than ten points or no spread in x."""
    data = sorted((float(a), float(b)) for a, b in zip(xs, ys) if a is not None and b is not None)
    n = len(data)
    if n < 10 or data[0][0] == data[-1][0]:
        return []
    k = max(3, min(n, int(math.ceil(span * n))))
    lo, hi = data[0][0], data[-1][0]
    out = []
    for i in range(points):
        x0 = lo + (hi - lo) * i / (points - 1)
        near = sorted(data, key=lambda p: abs(p[0] - x0))[:k]
        d = max(abs(p[0] - x0) for p in near) or 1.0
        w = [(1 - (abs(p[0] - x0) / (d * 1.000001)) ** 3) ** 3 for p in near]
        sw = sum(w)
        if sw <= 0:
            continue
        mx = sum(wi * p[0] for wi, p in zip(w, near)) / sw
        my = sum(wi * p[1] for wi, p in zip(w, near)) / sw
        sxx = sum(wi * (p[0] - mx) ** 2 for wi, p in zip(w, near))
        slope = sum(wi * (p[0] - mx) * (p[1] - my) for wi, p in zip(w, near)) / sxx if sxx > 1e-12 else 0.0
        out.append([round(x0, 3), round(my + slope * (x0 - mx), 4)])
    return out


def tukey(values: Sequence[float]) -> dict[str, Any] | None:
    """A box plot's numbers (Tukey): quartiles (linear interpolation), whiskers at the furthest values within 1.5 IQR of
    the box, the values beyond them, the mean and n."""
    v = sorted(float(x) for x in values if x is not None)
    if not v:
        return None

    def q(p: float) -> float:
        k = (len(v) - 1) * p
        a, b = int(k), min(int(k) + 1, len(v) - 1)
        return v[a] + (v[b] - v[a]) * (k - a)

    q1, med, q3 = q(0.25), q(0.5), q(0.75)
    fence_lo, fence_hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    inside = [x for x in v if fence_lo <= x <= fence_hi] or v
    return {"n": len(v), "min": v[0], "q1": round(q1, 4), "median": round(med, 4), "q3": round(q3, 4), "lo": inside[0], "hi": inside[-1],
            "max": v[-1], "mean": round(sum(v) / len(v), 4), "outliers": [x for x in v if x < inside[0] or x > inside[-1]]}


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact P for [[a, b], [c, d]]: the probability, given the margins, of every table no more likely
    than the one observed."""
    row1, col1, n = a + b, a + c, a + b + c + d
    lo, hi = max(0, row1 + col1 - n), min(row1, col1)
    denom = _log_comb(n, col1)
    prob = [math.exp(_log_comb(row1, x) + _log_comb(n - row1, col1 - x) - denom) for x in range(lo, hi + 1)]
    seen = prob[a - lo]
    return min(1.0, sum(p for p in prob if p <= seen * (1 + 1e-7)))


def chi_square_independence(table: Sequence[Sequence[float]]) -> dict[str, Any] | None:
    """Pearson's χ² test that the rows and columns of a table of counts are independent: χ², its degrees of freedom, P,
    n, the smallest expected count (below 5 the approximation is poor: a 2 × 2 table then wants Fisher's exact test)
    and Cramér's V.  Rows and columns that are empty throughout are left out; None when fewer than two of either
    remain."""
    rows = [list(map(float, r)) for r in table if sum(r) > 0]
    if len(rows) < 2:
        return None
    keep = [j for j in range(len(rows[0])) if sum(r[j] for r in rows) > 0]
    rows = [[r[j] for j in keep] for r in rows]
    if len(keep) < 2:
        return None
    n = sum(map(sum, rows))
    rsum = [sum(r) for r in rows]
    csum = [sum(r[j] for r in rows) for j in range(len(keep))]
    chi2, smallest = 0.0, float("inf")
    for i, r in enumerate(rows):
        for j, o in enumerate(r):
            e = rsum[i] * csum[j] / n
            smallest = min(smallest, e)
            chi2 += (o - e) ** 2 / e
    df = (len(rows) - 1) * (len(keep) - 1)
    v = math.sqrt(chi2 / (n * (min(len(rows), len(keep)) - 1))) if n else 0.0
    return {"chi2": round(chi2, 3), "df": df, "p": chi2_sf(chi2, df), "n": int(n), "min_expected": round(smallest, 2),
            "cramers_v": round(v, 4)}


def mean_sd(values: Sequence[float]) -> tuple[float, float]:
    """The mean and the sample standard deviation (n − 1)."""
    n = len(values)
    if not n:
        return 0.0, 0.0
    m = sum(values) / n
    return m, math.sqrt(sum((x - m) ** 2 for x in values) / (n - 1)) if n > 1 else 0.0
