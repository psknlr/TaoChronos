"""Sense evolution: what a term meant, period by period, where its meaning shifted, and what the curation misses.

Each occurrence of a term is read in its context window (the concepts and content bigrams around it).  Curated
senses — cue words that speak for a sense, anti-cues that speak against it — label the contexts they fit; the
contexts no sense fits are clustered, and a cluster with vocabulary of its own is a candidate sense the curation
lacks (to be read and named by a person).  The shares of the senses over time form a series; a change point is the
date that splits the dated occurrences into two sense distributions most unlike each other, tested by permuting the
dates.  The term's neighbourhood — the context words most characteristic of it in each period — is compared from
one period to the next.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Any

from .stats import jensen_shannon


def assign(contexts: list[dict[str, Any]], senses: list[dict[str, Any]]) -> list[str | None]:
    """The sense of each context: cue hits minus twice the anti-cue hits; the best sense when it scores above zero and
    alone (a tie leaves the context unassigned)."""
    out: list[str | None] = []
    for c in contexts:
        text = c["text"]
        scores = [(sum(1 for q in s.get("cues", []) if q and q in text) - 2 * sum(1 for q in s.get("anti_cues", []) if q and q in text),
                   s["id"]) for s in senses]
        scores.sort(reverse=True)
        if scores and scores[0][0] > 0 and (len(scores) == 1 or scores[0][0] > scores[1][0]):
            out.append(scores[0][1])
        else:
            out.append(None)
    return out


def _vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(tokens)
    v = {t: (1 + math.log(n)) * idf.get(t, 1.0) for t, n in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / norm for t, x in v.items()}


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def distinctive(members: list[list[str]], everyone: list[list[str]], top: int = 10) -> list[dict[str, Any]]:
    """Tokens more frequent in ``members`` than in all contexts (smoothed log-ratio of document frequencies)."""
    df_in = Counter(t for toks in members for t in set(toks))
    df_all = Counter(t for toks in everyone for t in set(toks))
    n_in, n_all = max(1, len(members)), max(1, len(everyone))
    rows = [(math.log((df_in[t] + 0.5) / (n_in + 1)) - math.log((df_all[t] + 0.5) / (n_all + 1)), t)
            for t in df_in if df_in[t] >= 2]
    rows.sort(key=lambda x: (-x[0], x[1]))
    return [{"token": t, "log_ratio": round(r, 3), "contexts": df_in[t]} for r, t in rows[:top]]


def discover(contexts: list[dict[str, Any]], labels: list[str | None], *, k: int = 3, min_size: int = 5, seed: int = 0,
             iters: int = 30) -> list[dict[str, Any]]:
    """Candidate senses among the unassigned contexts: spherical k-means over their token vectors (idf over all
    contexts), clusters of at least ``min_size`` with their distinctive tokens and member indices."""
    idx = [i for i, lab in enumerate(labels) if lab is None and contexts[i]["tokens"]]
    if len(idx) < max(2 * min_size, k):
        return []
    n = len(contexts)
    df = Counter(t for c in contexts for t in set(c["tokens"]))
    idf = {t: math.log((n + 1) / (d + 0.5)) for t, d in df.items()}
    vecs = [_vector(contexts[i]["tokens"], idf) for i in idx]
    rng = random.Random(seed)
    best: tuple[float, list[int]] | None = None
    for _ in range(5):
        cents = [dict(vecs[j]) for j in rng.sample(range(len(vecs)), min(k, len(vecs)))]
        lab = [0] * len(vecs)
        for _ in range(iters):
            new = [max(range(len(cents)), key=lambda c: (_cos(v, cents[c]), -c)) for v in vecs]
            for c in range(len(cents)):
                acc: dict[str, float] = defaultdict(float)
                for v, lb in zip(vecs, new):
                    if lb == c:
                        for t, x in v.items():
                            acc[t] += x
                norm = math.sqrt(sum(x * x for x in acc.values())) or 1.0
                cents[c] = {t: x / norm for t, x in acc.items()}
            if new == lab:
                break
            lab = new
        score = sum(_cos(v, cents[lb]) for v, lb in zip(vecs, lab))
        if best is None or score > best[0]:
            best = (score, lab)
    assert best is not None
    everyone = [c["tokens"] for c in contexts]
    out = []
    for c in sorted(set(best[1])):
        members = [idx[j] for j, lb in enumerate(best[1]) if lb == c]
        if len(members) < min_size:
            continue
        cohesion = sum(_cos(vecs[j], _vector([t for m in members for t in contexts[m]["tokens"]], idf))
                       for j, lb in enumerate(best[1]) if lb == c) / len(members)
        out.append({"size": len(members), "cohesion": round(cohesion, 3), "members": members,
                    "distinctive": distinctive([contexts[m]["tokens"] for m in members], everyone)})
    out.sort(key=lambda x: (-x["size"], -x["cohesion"]))
    return out


def series(labels: list[str | None], periods: list[str | None]) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for lab, per in zip(labels, periods):
        out[per or "未定"][lab or "unassigned"] += 1
    return dict(out)


def _split(pairs: list[tuple[float, str]], min_side: int) -> tuple[float, int]:
    n = len(pairs)
    best = (0.0, 0)
    left: Counter = Counter()
    right = Counter(lab for _, lab in pairs)
    for t in range(1, n):
        lab = pairs[t - 1][1]
        left[lab] += 1
        right[lab] -= 1
        if t < min_side or n - t < min_side or pairs[t][0] == pairs[t - 1][0]:
            continue  # a split falls between two dates
        stat = t * (n - t) / n * jensen_shannon(dict(left), dict(+right))
        if stat > best[0]:
            best = (stat, t)
    return best


def change_point(years: list[float], labels: list[str], *, min_side: int = 10, permutations: int = 199,
                 seed: int = 0) -> dict[str, Any] | None:
    """The date splitting the dated, labelled occurrences into the two most different sense distributions
    (n₁n₂/n × Jensen–Shannon), with a permutation p-value (labels shuffled across the dates)."""
    pairs = sorted(zip(years, labels))
    if len(pairs) < 2 * min_side:
        return None
    stat, t = _split(pairs, min_side)
    if t == 0:
        return None
    rng = random.Random(seed)
    labs = [lab for _, lab in pairs]
    exceed = 0
    for _ in range(permutations):
        rng.shuffle(labs)
        if _split([(y, lab) for (y, _), lab in zip(pairs, labs)], min_side)[0] >= stat:
            exceed += 1
    before = Counter(lab for _, lab in pairs[:t])
    after = Counter(lab for _, lab in pairs[t:])
    return {"year": round((pairs[t - 1][0] + pairs[t][0]) / 2, 1), "statistic": round(stat, 4),
            "p": round((exceed + 1) / (permutations + 1), 4), "before": dict(before.most_common()),
            "after": dict(after.most_common()), "n_before": t, "n_after": len(pairs) - t}


def change_points(years: list[float], labels: list[str], *, max_points: int = 3, alpha: float = 0.05, min_side: int = 10,
                  permutations: int = 199, seed: int = 0) -> list[dict[str, Any]]:
    """Binary segmentation: the strongest change point, then the strongest in the spans before and after it, while
    each is significant (permutation p < ``alpha``) — a term's meaning may shift more than once."""
    pairs = sorted(zip(years, labels))
    out: list[dict[str, Any]] = []

    def recurse(span: list[tuple[float, str]]) -> None:
        if len(out) >= max_points or len(span) < 2 * min_side:
            return
        cp = change_point([y for y, _ in span], [lab for _, lab in span], min_side=min_side, permutations=permutations, seed=seed)
        if cp is None or cp["p"] >= alpha:
            return
        out.append(cp)
        recurse([x for x in span if x[0] < cp["year"]])
        recurse([x for x in span if x[0] >= cp["year"]])

    recurse(pairs)
    return sorted(out, key=lambda c: c["year"])


def neighbourhood(tokens_by_period: dict[str, list[list[str]]], order: list[str], top: int = 12) -> list[dict[str, Any]]:
    """The context words most characteristic of the term in each period (document frequency against all periods),
    and their overlap with the previous period's (Jaccard): a falling overlap is a shifting neighbourhood."""
    everyone = [toks for per in order for toks in tokens_by_period.get(per, [])]
    out: list[dict[str, Any]] = []
    prev: set[str] | None = None
    for per in order:
        members = tokens_by_period.get(per, [])
        if not members:
            continue
        words = [d["token"] for d in distinctive(members, everyone, top=top)]
        common = [t for t, _ in Counter(t for toks in members for t in set(toks)).most_common(top)]
        now = set(common)
        out.append({"period": per, "contexts": len(members), "frequent": common, "distinctive": words,
                    "overlap_with_previous": round(len(now & prev) / len(now | prev), 3) if prev else None})
        prev = now
    return out


__all__ = ["assign", "change_point", "change_points", "discover", "distinctive", "neighbourhood", "series"]
