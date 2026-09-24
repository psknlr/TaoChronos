"""Source rediscovery: infer missing or lost intermediate sources from citation traces."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from ..protocol.research import LineageEdge


def infer_missing_sources(
    edges: Iterable[LineageEdge],
    present_books: set[str],
    *,
    year_of_passage: Callable[[str], float | None],
    aliases: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Rank cited targets that are absent from the corpus (lost works or held-out books).

    Each candidate gets an upper date bound (it must predate its earliest citer)
    and a support score from the number and confidence of citing passages.
    """
    buckets: dict[str, dict] = defaultdict(lambda: {"citers": [], "confidence": 0.0, "quotes": [], "relations": set()})
    for e in edges:
        # an explicit citation — or an explicit argument against a named work — attests that the work existed
        if e.relation not in ("cites", "opposes") or e.target_id in present_books:
            continue
        if e.relation == "opposes" and e.target_kind not in ("book", "external"):
            continue
        rec = buckets[e.target_id]
        rec["citers"].append(e.source_passage or e.source_id)
        rec["confidence"] += e.confidence
        rec["relations"].add(e.relation)
        quote = e.evidence.get("quote")
        if quote:
            rec["quotes"].append(quote)
    out = []
    for target, rec in buckets.items():
        years = [y for y in (year_of_passage(p) for p in rec["citers"]) if y is not None]
        out.append({
            "source": target,
            "aliases": (aliases or {}).get(target, []),
            "cited_by": sorted(set(rec["citers"])),
            "support": round(rec["confidence"], 4),
            "must_predate": min(years) if years else None,
            "quotes": rec["quotes"][:3],
            "relations": sorted(rec["relations"]),
        })
    out.sort(key=lambda r: (-r["support"], r["source"]))
    return out
