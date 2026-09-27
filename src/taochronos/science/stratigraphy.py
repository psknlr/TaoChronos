"""Textual stratigraphy: the layers of a text written, added to and annotated over centuries.

A classic is seldom one author's text of one date.  素问's 运气七篇 are held to be 王冰's addition (762), 伤寒论's 伤寒例
and 辨脉法 to come from 王叔和's edition, 本草 texts grow by accretion (本经 → 别录 → 唐本 …).  Three kinds of evidence
bear on it, none decisive alone:

* **style** — relative frequencies of the most frequent characters (Burrows' most-frequent-words, for characters), or of
  the function characters alone (之 其 者 也 而 以 于 …: less sensitive to topic, weaker).  Segments are split into
  layers with membership probabilities, the split tested against profiles with their features shuffled across
  segments; change points are sought in reading order with a local scan statistic, tested by permutation and
  corrected for the number of places tried; each segment's distance from the rest of the work is measured with
  Burrows' Delta;
* **dating** — the latest work a segment cites (a terminus post quem), vocabulary the rest of the corpus attests only
  long after the work's date, the taboo characters of the witness (which date its edition, not its composition);
* **authorship** — Burrows' Delta between a text and the works of candidate authors.

Everything here is deterministic (fixed seeds) and returns the numbers it used.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterable

FUNCTION_CHARS = list("之其者也而以于所则乃且亦又即若如故夫盖此是斯兮焉哉矣乎耳尔曰云为与皆必不无非未凡然")


# ---------------------------------------------------------------- profiles
def profile(text: str, features: list[str], *, root: bool = False) -> list[float]:
    """Frequency of each feature character per 1 000 characters of ``text`` (its square root with ``root``, which
    steadies the variance of rare features)."""
    n = len(text) or 1
    counts = dict.fromkeys(features, 0)
    for ch in text:
        if ch in counts:
            counts[ch] += 1
    freq = [1000.0 * counts[f] / n for f in features]
    return [math.sqrt(x) for x in freq] if root else freq


def most_frequent(texts: Iterable[str], n: int = 100) -> list[str]:
    counts: dict[str, int] = {}
    for t in texts:
        for ch in t:
            counts[ch] = counts.get(ch, 0) + 1
    return [ch for ch, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def zscores(rows: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    """Standardise each feature over the rows (features that never vary are dropped to zero)."""
    if not rows:
        return [], [], []
    d = len(rows[0])
    mean = [sum(r[j] for r in rows) / len(rows) for j in range(d)]
    sd = [math.sqrt(sum((r[j] - mean[j]) ** 2 for r in rows) / max(1, len(rows) - 1)) for j in range(d)]
    return [[(r[j] - mean[j]) / sd[j] if sd[j] > 0 else 0.0 for j in range(d)] for r in rows], mean, sd


def standardise(row: list[float], mean: list[float], sd: list[float]) -> list[float]:
    return [(x - m) / s if s > 0 else 0.0 for x, m, s in zip(row, mean, sd)]


def delta(a: list[float], b: list[float]) -> float:
    """Burrows' Delta: the mean absolute difference of two z-scored profiles."""
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def _d2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _mean(points: list[list[float]], weights: list[float] | None = None) -> list[float]:
    w = weights or [1.0] * len(points)
    total = sum(w) or 1.0
    return [sum(p[j] * wi for p, wi in zip(points, w)) / total for j in range(len(points[0]))]


# ---------------------------------------------------------------- layers
def _lloyd(points: list[list[float]], cents: list[list[float]], iters: int) -> tuple[list[int], list[list[float]]]:
    k = len(cents)
    labels = [-1] * len(points)
    for _ in range(iters):
        new = [min(range(k), key=lambda c: (_d2(p, cents[c]), c)) for p in points]
        for c in range(k):
            members = [p for p, lab in zip(points, new) if lab == c]
            if members:
                cents[c] = _mean(members)
        if new == labels:
            break
        labels = new
    return labels, cents


def kmeans(points: list[list[float]], k: int, *, restarts: int = 10, seed: int = 0, iters: int = 100
           ) -> tuple[list[int], list[list[float]], float]:
    """k-means with k-means++ starts from a seeded generator; the best of ``restarts`` runs (least inertia)."""
    rng = random.Random(seed)
    best: tuple[list[int], list[list[float]], float] | None = None
    for _ in range(restarts):
        cents = [list(points[rng.randrange(len(points))])]
        while len(cents) < k:
            d2 = [min(_d2(p, c) for c in cents) for p in points]
            total = sum(d2)
            if total <= 0:
                cents.append(list(points[rng.randrange(len(points))]))
                continue
            r, acc = rng.random() * total, 0.0
            for i, v in enumerate(d2):
                acc += v
                if acc >= r:
                    cents.append(list(points[i]))
                    break
        labels, cents = _lloyd(points, cents, iters)
        inertia = sum(_d2(p, cents[lab]) for p, lab in zip(points, labels))
        if best is None or inertia < best[2] - 1e-9:
            best = (labels, cents, inertia)
    assert best is not None
    return best


def silhouette(points: list[list[float]], labels: list[int]) -> float:
    ks = set(labels)
    if len(ks) < 2:
        return 0.0
    total = 0.0
    for i, p in enumerate(points):
        own = [math.sqrt(_d2(p, q)) for j, q in enumerate(points) if labels[j] == labels[i] and j != i]
        if not own:
            continue
        a = sum(own) / len(own)
        b = min(sum(math.sqrt(_d2(p, q)) for j, q in enumerate(points) if labels[j] == k) /
                max(1, sum(1 for lab in labels if lab == k)) for k in ks if k != labels[i])
        total += (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return total / len(points)


def memberships(points: list[list[float]], cents: list[list[float]], labels: list[int]) -> list[list[float]]:
    """Soft membership: p(layer) ∝ exp(−d² / s²), s² the mean squared distance of the points to their own layer."""
    s2 = sum(_d2(p, cents[lab]) for p, lab in zip(points, labels)) / max(1, len(points)) or 1.0
    out = []
    for p in points:
        e = [-_d2(p, c) / s2 for c in cents]
        m = max(e)
        w = [math.exp(x - m) for x in e]
        z = sum(w)
        out.append([x / z for x in w])
    return out


def layers(points: list[list[float]], weights: list[float], *, k: int = 2, permutations: int = 39, alpha: float = 0.05,
           seed: int = 0) -> dict[str, Any]:
    """Split the segments into ``k`` layers and test the split: the share of the variance it explains (R²) against
    the same clustering of profiles whose features were shuffled independently across segments (the marginals kept,
    any joint structure destroyed).  Layer 0 is the main layer (the most characters)."""
    n = len(points)
    if n < 2 * k:
        return {"k": 1, "supported": False, "p": None, "labels": [0] * n, "memberships": [[1.0]] * n, "r2": None}
    centre = _mean(points)
    total = sum(_d2(p, centre) for p in points) or 1.0
    labels, cents, inertia = kmeans(points, k, seed=seed)
    r2 = 1 - inertia / total
    rng = random.Random(seed + 1)
    d = len(points[0])
    null = []
    for _ in range(permutations):
        cols = [[p[j] for p in points] for j in range(d)]
        for col in cols:
            rng.shuffle(col)
        shuffled = [[cols[j][i] for j in range(d)] for i in range(n)]
        _, _, inn = kmeans(shuffled, k, restarts=2, seed=rng.randrange(1 << 30))
        null.append(1 - inn / total)
    p = (sum(1 for x in null if x >= r2) + 1) / (permutations + 1)
    mass = {c: sum(w for w, lab in zip(weights, labels) if lab == c) for c in range(k)}
    order = sorted(range(k), key=lambda c: (-mass[c], c))
    remap = {old: new for new, old in enumerate(order)}
    labels = [remap[lab] for lab in labels]
    cents = [cents[old] for old in order]
    return {"k": k, "supported": p < alpha, "p": round(p, 4), "r2": round(r2, 4), "null_r2": round(sum(null) / len(null), 4),
            "labels": labels, "centroids": cents, "memberships": memberships(points, cents, labels),
            "silhouette": round(silhouette(points, labels), 4)}


def distinctive_features(points: list[list[float]], labels: list[int], names: list[str], layer: int, top: int = 6
                         ) -> list[dict[str, Any]]:
    """The features that most set a layer apart from the rest (difference of mean z-scores)."""
    inside = [p for p, lab in zip(points, labels) if lab == layer]
    outside = [p for p, lab in zip(points, labels) if lab != layer]
    if not inside or not outside:
        return []
    a, b = _mean(inside), _mean(outside)
    diffs = sorted(((a[j] - b[j], names[j]) for j in range(len(names))), key=lambda x: (-abs(x[0]), x[1]))
    return [{"feature": name, "difference": round(d, 3), "direction": "more" if d > 0 else "less"} for d, name in diffs[:top]]


# ---------------------------------------------------------------- change points in reading order
def _split_stat(points: list[list[float]]) -> tuple[float, int]:
    """The best split of a sequence into a prefix and a suffix: between-part sum of squares and where."""
    n = len(points)
    d = len(points[0])
    prefix = [[0.0] * d]
    for p in points:
        prefix.append([x + y for x, y in zip(prefix[-1], p)])
    total = prefix[-1]
    best = (0.0, 0)
    for t in range(1, n):
        left = [x / t for x in prefix[t]]
        right = [(tt - x) / (n - t) for x, tt in zip(prefix[t], total)]
        stat = t * (n - t) / n * _d2(left, right)
        if stat > best[0]:
            best = (stat, t)
    return best


def change_points(points: list[list[float]], *, window: int = 4, alpha: float = 0.05, permutations: int = 999,
                  seed: int = 0, method: str = "both", min_size: int = 3) -> list[dict[str, Any]]:
    """Where the style changes in reading order.

    ``binary``: binary segmentation, each split tested by permuting its segment — long blocks and major breaks.
    ``scan``: at every position, the difference between the means of the ``window`` segments before and after it; at
    each local maximum a permutation p-value (the 2·window segments shuffled), kept when significant after
    Benjamini–Hochberg over the local maxima — blocks that alternate, which a single global split misses.
    ``both`` (default): the two together, the more significant of two points less than two segments apart kept."""
    if method == "binary":
        return _binary(points, min_size=min_size, alpha=alpha, permutations=min(permutations, 199), seed=seed)
    scan = [c | {"method": "scan"} for c in _scan(points, window=window, alpha=alpha, permutations=permutations, seed=seed)]
    if method == "scan":
        return scan
    binary = [c | {"method": "binary"} for c in
              _binary(points, min_size=min_size, alpha=alpha, permutations=min(permutations, 199), seed=seed)]
    kept: list[dict[str, Any]] = []
    for c in sorted(scan + binary, key=lambda c: (c["p"], c["at"])):
        if all(abs(c["at"] - k["at"]) > 1 for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda c: c["at"])


def boundaries(labels: list[int], *, min_run: int = 2) -> list[int]:
    """Where the layer changes in reading order, runs shorter than ``min_run`` segments merged into their longer
    neighbour first (one odd segment is not a layer)."""
    runs: list[list[int]] = []  # [label, length]
    for lab in labels:
        if runs and runs[-1][0] == lab:
            runs[-1][1] += 1
        else:
            runs.append([lab, 1])
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (lab, length) in enumerate(runs):
            if length < min_run:
                left = runs[i - 1] if i > 0 else None
                right = runs[i + 1] if i + 1 < len(runs) else None
                target = max((r for r in (left, right) if r is not None), key=lambda r: r[1])
                target[1] += length
                del runs[i]
                merged: list[list[int]] = []
                for r in runs:
                    if merged and merged[-1][0] == r[0]:
                        merged[-1][1] += r[1]
                    else:
                        merged.append(r)
                runs = merged
                changed = True
                break
    out, at = [], 0
    for lab, length in runs[:-1]:
        at += length
        out.append(at)
    return out


def _scan(points: list[list[float]], *, window: int, alpha: float, permutations: int, seed: int) -> list[dict[str, Any]]:
    n = len(points)
    if n < 2 * window:
        return []
    rng = random.Random(seed)

    def stat(seq: list[list[float]]) -> float:
        half = len(seq) // 2
        return half / 2 * _d2(_mean(seq[:half]), _mean(seq[half:]))

    stats = {t: stat(points[t - window: t + window]) for t in range(window, n - window + 1)}
    peaks = [t for t in stats if all(stats[t] >= stats[u] for u in range(t - window + 1, t + window) if u in stats and u != t)]
    tested = []
    for t in peaks:
        seg = points[t - window: t + window]
        exceed = 0
        for _ in range(permutations):
            shuffled = seg[:]
            rng.shuffle(shuffled)
            if stat(shuffled) >= stats[t]:
                exceed += 1
        tested.append((t, stats[t], (exceed + 1) / (permutations + 1)))
    ranked = sorted(tested, key=lambda x: x[2])
    m = len(ranked)
    cut = 0
    for i, (_, _, p) in enumerate(ranked, 1):
        if p <= alpha * i / m:
            cut = i
    keep = ranked[:cut]
    return sorted(({"at": t, "statistic": round(st, 3), "p": round(p, 4)} for t, st, p in keep), key=lambda c: c["at"])


def _binary(points: list[list[float]], *, min_size: int, alpha: float, permutations: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []

    def recurse(lo: int, hi: int) -> None:
        seg = points[lo:hi]
        if len(seg) < 2 * min_size:
            return
        stat, t = _split_stat(seg)
        if t < min_size or len(seg) - t < min_size:
            return
        exceed = 0
        for _ in range(permutations):
            shuffled = seg[:]
            rng.shuffle(shuffled)
            if _split_stat(shuffled)[0] >= stat:
                exceed += 1
        p = (exceed + 1) / (permutations + 1)
        if p >= alpha:
            return
        out.append({"at": lo + t, "statistic": round(stat, 3), "p": round(p, 4)})
        recurse(lo, lo + t)
        recurse(lo + t, hi)

    recurse(0, len(points))
    return sorted(out, key=lambda c: c["at"])


def outliers(points: list[list[float]], weights: list[float]) -> list[dict[str, Any]]:
    """Each segment's Delta from the rest of the work (the others' weighted mean), and its rank as a z-score among
    all segments' distances."""
    n = len(points)
    if n < 3:
        return [{"delta": 0.0, "z": 0.0} for _ in points]
    total_w = sum(weights)
    sums = [sum(p[j] * w for p, w in zip(points, weights)) for j in range(len(points[0]))]
    ds = []
    for p, w in zip(points, weights):
        rest = [(s - x * w) / (total_w - w) for s, x in zip(sums, p)] if total_w > w else p
        ds.append(delta(p, rest))
    m = sum(ds) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in ds) / max(1, n - 1)) or 1.0
    return [{"delta": round(x, 4), "z": round((x - m) / sd, 3)} for x in ds]


# ---------------------------------------------------------------- authorship
def attribute(text: list[float], candidates: dict[str, list[float]]) -> list[dict[str, Any]]:
    """Burrows' Delta between a text's profile and each candidate's (raw per-1000 profiles; standardised over the
    candidates and the text together).  Smaller is closer; ``margin`` is the gap to the next candidate."""
    names = sorted(candidates)
    z, _, _ = zscores([candidates[n] for n in names] + [text])
    tz = z[-1]
    ranked = sorted(((delta(tz, z[i]), names[i]) for i in range(len(names))), key=lambda x: (x[0], x[1]))
    out = []
    for i, (d, name) in enumerate(ranked):
        nxt = ranked[i + 1][0] if i + 1 < len(ranked) else None
        out.append({"candidate": name, "delta": round(d, 4), "margin": round(nxt - d, 4) if nxt is not None else None})
    return out


# ---------------------------------------------------------------- dating
def interval(evidence: list[dict[str, Any]], nominal: tuple[float, float] | None = None) -> dict[str, Any]:
    """Combine dated evidence: ``{"kind", "after": year}`` (terminus post quem) or ``{"kind", "before": year}``.
    Hard evidence (citations, taboo) bounds the interval; soft evidence (vocabulary) is reported beside it."""
    hard_after = [e["after"] for e in evidence if e.get("after") is not None and e.get("strength") != "soft"]
    soft_after = [e["after"] for e in evidence if e.get("after") is not None and e.get("strength") == "soft"]
    before = [e["before"] for e in evidence if e.get("before") is not None]
    lo = max(hard_after) if hard_after else None
    hi = min(before) if before else None
    out = {"after": lo, "before": hi, "vocabulary_after": max(soft_after) if soft_after else None,
           "consistent": lo is None or hi is None or lo <= hi}
    if nominal is not None:
        late = max([x for x in (lo, out["vocabulary_after"]) if x is not None], default=None)
        out["later_than_nominal"] = late is not None and late > nominal[1]
    return out


__all__ = ["FUNCTION_CHARS", "attribute", "boundaries", "change_points", "delta", "distinctive_features", "interval", "kmeans", "layers",
           "memberships", "most_frequent", "outliers", "profile", "silhouette", "standardise", "zscores"]
