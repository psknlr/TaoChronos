"""TCM Discovery Score, hypothesis score cards, novelty and Elo tournaments.

D = w1·E + w2·N + w3·R + w4·T + w5·F − w6·A  — always reported *with* its components,
so the scalar never hides which dimension carries a result.
"""

from __future__ import annotations

from itertools import combinations

from .stats import jaccard, rng

DEFAULT_DISCOVERY_WEIGHTS = {"E": 0.25, "N": 0.2, "R": 0.2, "T": 0.15, "F": 0.1, "A": 0.1}


def discovery_score(components: dict[str, float], weights: dict[str, float] | None = None) -> float:
    w = {**DEFAULT_DISCOVERY_WEIGHTS, **(weights or {})}
    value = (
        w["E"] * components.get("E", 0.0)
        + w["N"] * components.get("N", 0.0)
        + w["R"] * components.get("R", 0.0)
        + w["T"] * components.get("T", 0.0)
        + w["F"] * components.get("F", 0.0)
        - w["A"] * components.get("A", 0.0)
    )
    return round(value, 4)


def novelty(terms: list[str], known: list[dict]) -> tuple[float, str]:
    """1 − max overlap with the curated 'existing understanding'; returns (novelty, rationale).

    This is novelty *within that list only* — "not found within the specified scope", never "first discovery"."""
    labels = {t.split(":", 1)[-1] for t in terms}
    best, best_id = 0.0, None
    for finding in known:
        overlap = jaccard(labels, set(finding.get("terms", [])))
        if overlap > best:
            best, best_id = overlap, finding.get("id")
    if best_id is None:
        return 1.0, "not found within the curated list of existing understanding (scope: that list only)"
    rationale = f"overlaps {best_id} (Jaccard {best:.2f})"
    if best >= 0.5:
        rationale += " — likely a rediscovery of known knowledge"
    return round(1.0 - best, 4), rationale


def novelty_profile(terms: list[str], known: list[dict], *, stated_in_corpus: bool | None, literature: dict | None = None) -> dict:
    """Novelty split by scope: the curated known findings, the corpus under study, and the literature (assessed only
    when a search within a stated scope was run).  The verdict is always relative: 未在指定范围内发现."""
    score, rationale = novelty(terms, known)
    corpus = ("stated directly in the corpus under study" if stated_in_corpus else
              "not stated directly within the research scope" if stated_in_corpus is not None else "not assessed")
    lit = literature or {"status": "not assessed", "scope": None}
    found = score < 0.5 or bool(stated_in_corpus)
    return {"known_findings": {"novelty": score, "rationale": rationale, "scope": "the curated list of existing understanding"},
            "corpus": corpus, "literature": lit, "research_value": "the heuristic discovery score D (a priority, not a truth value)",
            "statement": "与既有认识或语料中的直接记载重叠" if found else "未在指定范围内发现（策展的既有认识清单与本次研究语料）",
            "never_claimed": "first discovery"}


def explanatory_comparison(a: dict, b: dict) -> float:
    """Which of two hypotheses explains its evidence better, by what a reader can check: fewer live defeaters (open
    critical/major objections); confirmed rather than refuted on withheld material; more independent source families
    explained; more rival explanations excluded than left open; fewer extra assumptions.  1 = a, 0 = b, 0.5 = tie."""
    keys = ("defeaters", "confirmation", "families", "rivals", "assumptions")
    sign = {"defeaters": -1, "confirmation": 1, "families": 1, "rivals": 1, "assumptions": -1}
    for k in keys:
        da, db = sign[k] * a.get(k, 0), sign[k] * b.get(k, 0)
        if da != db:
            return 1.0 if da > db else 0.0
    return 0.5


def pairwise_tournament(players: dict[str, dict], compare=explanatory_comparison, *, k_factor: float = 32.0, rounds: int = 3,
                        seed: int = 0, start: dict[str, float] | None = None) -> tuple[dict[str, float], list[dict]]:
    """Elo over pairwise comparisons of explanations — an **exploration priority** (what to examine first), not a
    credibility: it orders hypotheses by checkable features, and says nothing about whether any of them is true."""
    elo = {p: (start or {}).get(p, 1200.0) for p in players}
    matches = []
    order = sorted(players)
    r = rng(seed)
    for rnd in range(rounds):
        pairs = list(combinations(order, 2))
        r.shuffle(pairs)
        for a, b in pairs:
            result = compare(players[a], players[b])
            expected = 1.0 / (1.0 + 10 ** ((elo[b] - elo[a]) / 400.0))
            elo[a] += k_factor * (result - expected)
            elo[b] -= k_factor * (result - expected)
            matches.append({"round": rnd, "a": a, "b": b, "result": result})
    return {p: round(v, 2) for p, v in elo.items()}, matches


def elo_tournament(
    players: dict[str, float],
    *,
    k_factor: float = 32.0,
    rounds: int = 3,
    seed: int = 0,
    tie_margin: float = 0.01,
    start: dict[str, float] | None = None,
) -> tuple[dict[str, float], list[dict]]:
    """Round-robin Elo on a strength value per player (e.g. a weighted score card)."""
    elo = {p: (start or {}).get(p, 1200.0) for p in players}
    matches = []
    order = sorted(players)
    r = rng(seed)
    for rnd in range(rounds):
        pairs = list(combinations(order, 2))
        r.shuffle(pairs)
        for a, b in pairs:
            diff = players[a] - players[b]
            result = 0.5 if abs(diff) <= tie_margin else (1.0 if diff > 0 else 0.0)
            expected = 1.0 / (1.0 + 10 ** ((elo[b] - elo[a]) / 400.0))
            elo[a] += k_factor * (result - expected)
            elo[b] -= k_factor * (result - expected)
            matches.append({"round": rnd, "a": a, "b": b, "result": result})
    return {p: round(v, 2) for p, v in elo.items()}, matches
