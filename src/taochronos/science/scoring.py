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
    """1 − max overlap with the curated 'existing understanding'; returns (novelty, rationale)."""
    labels = {t.split(":", 1)[-1] for t in terms}
    best, best_id = 0.0, None
    for finding in known:
        overlap = jaccard(labels, set(finding.get("terms", [])))
        if overlap > best:
            best, best_id = overlap, finding.get("id")
    if best_id is None:
        return 1.0, "no overlap with curated existing understanding"
    rationale = f"overlaps {best_id} (Jaccard {best:.2f})"
    if best >= 0.5:
        rationale += " — likely a rediscovery of known knowledge"
    return round(1.0 - best, 4), rationale


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
