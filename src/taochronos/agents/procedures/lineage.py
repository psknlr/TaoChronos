"""Lineage Analyst: who cites, transcribes, rephrases, modifies or opposes whom.

Lineage separates independent witnesses from copies (a claim repeated by ten
books that transcribe one source is one piece of evidence) and underlies
formula evolution (D3) and source rediscovery.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...protocol.events import EventType
from ...protocol.research import LineageEdge
from .common import scope_passages

OUTPUT = "LineageReport"


def instructions(ctx: Any) -> str:
    return "Detect knowledge-lineage edges (cites / transcribes / rephrases / formula_derived_from / opposes) among passages in scope."


def draft(ctx: Any) -> dict[str, Any]:
    builder = ctx.cap("lineage")
    claims = sorted(ctx.state.claims.values(), key=lambda c: c.id)
    edges = builder.build(scope_passages(ctx), claims)
    return {"edges": [e.to_dict() for e in edges]}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    in_scope = {p.id for p in scope_passages(ctx)}
    edges = []
    for raw in output.get("edges", []):
        edge = LineageEdge.from_dict(raw)
        passages = [p for p in (edge.source_passage, edge.target_passage) if p]
        if any(p not in in_scope or not corpus.has_passage(p) for p in passages):
            continue
        edges.append(edge.to_dict())
    if edges:
        ctx.emit(EventType.LINEAGE_DETECTED, {"edges": edges}, generated=[e["id"] for e in edges])
    kinds = Counter(e["relation"] for e in edges)
    return f"{len(edges)} lineage edges: " + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items()))
