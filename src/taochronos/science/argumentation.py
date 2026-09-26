"""Medical argument graphs: how a passage reasons — from what, to what, by which step.

The classics argue as well as prescribe: 若…则… (condition and consequence), 故 / 是以 (inference), 因 / 由 (cause),
…所致 (an effect traced to its cause), 然 / 虽 (contrast), 犹 / 譬 (analogy), 非…也 / 殊不知 (rebuttal), 盖 (a reason
given), …者…也 and 名曰 (definition), …主之 / 宜 (treatment).  A passage is cut into clauses; each clause is a node
with the concepts it names (by category: etiology, symptom, pulse, pattern, formula …); each discourse marker gives
an edge, typed and directed by the marker table (``argument.yaml``).  Only explicit markers are used: an unmarked
step of reasoning is not guessed.

Aggregated over a work, the graphs show a way of reasoning: which relations it uses (per 1 000 clauses), which kinds
of concept it links by them (symptom —treatment→ formula; etiology —cause→ symptom; symptom —inference→ pattern),
and its chains of steps.  Two works (or authors) are compared by those distributions (Jensen–Shannon divergence,
log-odds with an informative prior for what sets each apart).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .stats import jensen_shannon

SPECIFIC = ["treatment", "define", "effect", "rebut", "analogy", "inference", "cause", "support", "consequence", "contrast",
            "condition"]  # when two markers link the same clauses, the more specific relation wins


def detect(text: str, table: dict[str, dict[str, Any]]) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """(lead relation, marker), (tail relation, marker) of a clause — the longest marker wins."""
    head = text.lstrip("　 ")
    tail = text.rstrip("　 。，；：！？、")
    lead = max(((len(m), rel, m) for rel, spec in table.items() for m in spec.get("lead", []) if head.startswith(m)), default=None)
    end = max(((len(m), rel, m) for rel, spec in table.items() for m in spec.get("tail", []) if tail.endswith(m)), default=None)
    return (lead[1], lead[2]) if lead else None, (end[1], end[2]) if end else None


def build_graph(clauses: list[dict[str, Any]], table: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Edges between clauses (``{"text", "sentence", "concepts": [(term, category)]}``) from their markers.

    ``from_previous``: the previous clause → this one; ``to_previous``: this clause → the previous one; ``to_next``:
    this clause → the clause of its sentence that draws the consequence (a consequence, treatment or inference
    marker), else the next clause.  Edges do not cross sentences, except inference and support (故 / 盖 opening a
    sentence reach back to the last one).  A clause ending in 者 is a condition when its sentence draws a consequence
    or prescribes after it; otherwise it is a topic, and the next clause explains it (a definition: A 者，B 也)."""
    n = len(clauses)
    marks = [detect(c["text"], table) for c in clauses]
    raw: list[tuple[int, int, str, str]] = []

    def same_sentence(i: int, j: int) -> bool:
        return 0 <= j < n and clauses[i]["sentence"] == clauses[j]["sentence"]

    drawing = ("consequence", "treatment", "inference")

    def consequence_of(i: int) -> int | None:
        """The clause of i's sentence that draws the consequence — before any clause that opens another kind of step
        (an analogy, a contrast …), which begins a reasoning of its own."""
        for j in range(i + 1, n):
            if not same_sentence(i, j):
                break
            lead, tail = marks[j]
            if (lead and lead[0] in drawing) or (tail and tail[0] == "treatment"):
                return j
            if lead:
                break
        return None

    def _draws(i: int) -> bool:
        return consequence_of(i) is not None

    for i, (lead, tail) in enumerate(marks):
        if lead and tail and tail[1] == "者" and lead[0] != "condition":
            tail = None  # 所以然者: the 者 closes the announcement, it opens no condition
        for found in (lead, tail):
            if not found:
                continue
            rel, marker = found
            direction = table[rel].get("direction", "from_previous")
            crosses = rel in ("inference", "support")
            if direction == "from_previous" and i > 0 and (same_sentence(i, i - 1) or crosses):
                raw.append((i - 1, i, rel, marker))
            elif direction == "to_previous" and i > 0 and (same_sentence(i, i - 1) or crosses):
                raw.append((i, i - 1, rel, marker))
            elif direction == "to_next":
                j = consequence_of(i)
                if marker == "者" and j is None:  # a topic the next clause explains, not a condition
                    if same_sentence(i, i + 1) and not marks[i + 1][0]:
                        raw.append((i + 1, i, "define", "者"))
                elif j is not None:
                    raw.append((i, j, rel, marker))
                elif same_sentence(i, i + 1):
                    raw.append((i, i + 1, rel, marker))
        # A 者，B 也: B defines A (not after a lead of another kind: 所以然者 announces a reason)
        if tail and tail[1] == "者" and (not lead or lead[0] == "condition") and same_sentence(i, i + 1) and not marks[i + 1][0] \
                and clauses[i + 1]["text"].rstrip("　 。，；").endswith("也") and not _draws(i):
            raw.append((i + 1, i, "define", "者…也"))
    best: dict[frozenset[int], tuple[int, int, str, str]] = {}  # one edge per pair of clauses: the most specific
    for s, t, rel, marker in raw:
        key = frozenset((s, t))
        if key not in best or SPECIFIC.index(rel) < SPECIFIC.index(best[key][2]):
            best[key] = (s, t, rel, marker)
    return [{"source": s, "target": t, "relation": rel, "marker": marker} for s, t, rel, marker in sorted(best.values())]


def triples(clauses: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Counter:
    """(category of the source, relation, category of the target) for every edge and every pair of concepts it joins."""
    out: Counter = Counter()
    for e in edges:
        src = {cat for _, cat in clauses[e["source"]]["concepts"]} or {"—"}
        tgt = {cat for _, cat in clauses[e["target"]]["concepts"]} or {"—"}
        for a in src:
            for b in tgt:
                out[(a, e["relation"], b)] += 1
    return out


def chains(n: int, edges: list[dict[str, Any]], max_len: int = 4) -> Counter:
    """Sequences of relations along directed paths of two or more steps (condition → consequence → treatment …)."""
    succ: dict[int, list[tuple[int, str]]] = {}
    for e in edges:
        succ.setdefault(e["source"], []).append((e["target"], e["relation"]))
    out: Counter = Counter()

    def walk(node: int, path: tuple[str, ...], seen: set[int]) -> None:
        if len(path) >= 2:
            out[path] += 1
        if len(path) >= max_len:
            return
        for nxt, rel in succ.get(node, []):
            if nxt not in seen:
                walk(nxt, path + (rel,), seen | {nxt})

    targets = {e["target"] for e in edges}
    for start in sorted(set(succ) - targets) or sorted(succ):
        walk(start, (), {start})
    return out


def log_odds(a: Counter, b: Counter, top: int = 12) -> list[dict[str, Any]]:
    """What sets ``a`` apart from ``b``: log-odds ratios with an informative Dirichlet prior (both together), as
    z-scores (Monroe, Colaresi & Quinn 2008).  Positive: more typical of ``a``."""
    prior = a + b
    na, nb, n0 = sum(a.values()), sum(b.values()), sum(prior.values())
    if not na or not nb:
        return []
    out = []
    for k in prior:
        ya, yb, a0 = a.get(k, 0), b.get(k, 0), prior[k] * 10 / n0  # a weak prior: ten pseudo-counts in all
        la = math.log((ya + a0) / (na + 10 - ya - a0))
        lb = math.log((yb + a0) / (nb + 10 - yb - a0))
        var = 1 / (ya + a0) + 1 / (yb + a0)
        out.append({"item": k, "z": round((la - lb) / math.sqrt(var), 3), "a": ya, "b": yb})
    out.sort(key=lambda r: (-abs(r["z"]), str(r["item"])))
    return out[:top]


def compare(a: dict[str, Counter], b: dict[str, Counter]) -> dict[str, Any]:
    """Two aggregates ({"relations", "triples"}): divergence of the distributions and what sets each apart."""
    return {
        "relations_jsd": round(jensen_shannon(dict(a["relations"]), dict(b["relations"])), 4),
        "triples_jsd": round(jensen_shannon({str(k): v for k, v in a["triples"].items()},
                                            {str(k): v for k, v in b["triples"].items()}), 4),
        "relations": log_odds(a["relations"], b["relations"]),
        "triples": [r | {"item": list(r["item"])} for r in log_odds(a["triples"], b["triples"])],
    }


__all__ = ["SPECIFIC", "build_graph", "chains", "compare", "detect", "log_odds", "triples"]
