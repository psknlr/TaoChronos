"""D3 · Formula Evolution: families, trees, stable cores and indication drift."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..protocol.research import LineageEdge


def formula_families(profiles: Iterable, edges: Iterable[LineageEdge], indications: dict[str, list[tuple[float | None, list[str]]]] | None = None) -> list[dict]:
    """Group formulas connected by ``formula_derived_from`` edges and describe each family.

    ``profiles`` are objects with ``formula_id``, ``herbs``, ``year``, ``source`` and ``surfaces``.
    """
    prof = {}
    for p in profiles:
        if p.formula_id not in prof or (p.year or 0) < (prof[p.formula_id].year or 0):
            prof[p.formula_id] = p
    adj: dict[str, set[str]] = defaultdict(set)
    parent_of: dict[str, tuple[str, LineageEdge]] = {}
    for e in edges:
        if e.relation != "formula_derived_from":
            continue
        adj[e.source_id].add(e.target_id)
        adj[e.target_id].add(e.source_id)
        if e.source_id not in parent_of or e.confidence > parent_of[e.source_id][1].confidence:
            parent_of[e.source_id] = (e.target_id, e)
    seen: set[str] = set()
    families = []
    for start in sorted(adj):
        if start in seen:
            continue
        stack, members = [start], set()
        while stack:
            node = stack.pop()
            if node in members:
                continue
            members.add(node)
            stack.extend(adj[node] - members)
        seen |= members
        ordered = sorted(members, key=lambda f: ((prof[f].year if f in prof and prof[f].year is not None else 9999), f))
        with_composition = [f for f in ordered if f in prof and getattr(prof[f], "source", "composition") == "composition"]
        core = set.intersection(*(set(prof[f].herbs) for f in with_composition)) if len(with_composition) >= 2 else set()
        steps = []
        for f in ordered:
            if f in parent_of:
                parent, edge = parent_of[f]
                ev = edge.evidence
                steps.append({
                    "child": f,
                    "parent": parent,
                    "added": ev.get("added", []),
                    "removed": ev.get("removed", []),
                    "substituted": ev.get("substituted", []),
                    "renames": ev.get("renames", []),
                    "surface_changes": ev.get("surface_changes", []),
                    "overlap": ev.get("overlap"),
                    "confidence": edge.confidence,
                    "stated_by_name": ev.get("pattern") == "X加Y",
                })
        herb_counts: dict[str, int] = defaultdict(int)
        for f in with_composition:
            for h in set(prof[f].herbs):
                herb_counts[h] += 1
        drift = []
        if indications:
            prev: set[str] = set()
            for f in ordered:
                terms = set()
                for _, t in indications.get(f, []):
                    terms |= set(t)
                if prev and terms:
                    drift.append({"formula": f, "new": sorted(terms - prev), "dropped": sorted(prev - terms)})
                prev = terms or prev
        roots = [f for f in ordered if f not in parent_of]
        families.append({
            "members": ordered,
            "roots": roots,
            "years": {f: (prof[f].year if f in prof else None) for f in ordered},
            "stable_core": sorted(core),
            "herb_retention": {h: round(n / max(1, len(with_composition)), 3) for h, n in sorted(herb_counts.items(), key=lambda t: (-t[1], t[0]))},
            "steps": steps,
            "indication_drift": drift,
            "size": len(ordered),
        })
    families.sort(key=lambda f: (-f["size"], f["members"][0]))
    return families
