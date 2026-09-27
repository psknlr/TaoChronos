"""传播链 — how one passage travelled: which earlier witness each later copy or quotation most likely came through.

``study concordance`` finds where a passage recurs — other copies of its work, quotations, restatements — with their
dates and wording.  ``study chain`` orders them into a tree by the principle of textual criticism that only shared
changes show descent (Lachmann's shared innovations): a witness's readings that differ from the earliest witness's
are its innovations; a later witness most likely came through the earlier witness whose innovations it shares most,
less those innovations of that witness it lacks (a copy keeps its model's changes, mostly).  With no shared
innovation, it hangs from the earliest witness — directly, or through a lost intermediary: the texts cannot tell.

Each edge carries the shared readings (the evidence), the score and the margin over the next candidate; a margin
under one reading is marked uncertain.  Dates order the witnesses (an edge never runs from a later witness to an
earlier one); a witness whose date overlaps its parent's is marked.  A tree of one passage is evidence for the route
of that passage, not for whole works; ``study stemma`` collates whole works.
"""

from __future__ import annotations

import difflib
from typing import Any

from ..collation.variant_graph import FUNCTION_WORDS, load_equivalents
from .base import StudyBase, dated


class ChainStudy:
    def __init__(self, base: StudyBase, concordance: Any) -> None:
        self.b = base
        self.concordance = concordance
        self.eq = load_equivalents(base.data("collation.yaml").get("equivalents") or [], base.normalize)

    def readings(self, root: str, text: str) -> set[tuple[int, int, str]]:
        """A witness's differences from the root: (root start, root end, its reading) — not at the edges (an alignment
        may stop a character early), not in spelling only (藏/脏, collation.yaml: a transcription's habit, which
        copyists change independently)."""
        def canon(s: str) -> str:
            return "".join(self.eq.get(ch, ch) for ch in s)

        sm = difflib.SequenceMatcher(None, root, text, autojunk=False)
        ops = sm.get_opcodes()
        out = set()
        for k, (tag, i1, i2, j1, j2) in enumerate(ops):
            if tag == "equal" or k == 0 or k == len(ops) - 1 or canon(root[i1:i2]) == canon(text[j1:j2]):
                continue
            out.add((i1, i2, text[j1:j2]))
        return out

    @staticmethod
    def weight(root: str, r: tuple[int, int, str]) -> float:
        """A change of function words only (之, 而, 也 …) is weaker evidence of descent than one of content."""
        diff = set(root[r[0]:r[1]]) ^ set(r[2])
        return 0.5 if diff and diff <= FUNCTION_WORDS else 1.0

    @classmethod
    def choose(cls, child: set[tuple[int, int, str]], parents: list[tuple[str, set[tuple[int, int, str]], float]],
               root: str = "") -> dict[str, Any]:
        """The parent among (id, innovations, similarity) candidates: most shared innovations (weighed) less half the
        candidate's own innovations the child lacks; ties by similarity."""
        scored = []
        for pid, inn, sim in parents:
            shared = child & inn
            score = sum(cls.weight(root, r) for r in shared) - 0.5 * sum(cls.weight(root, r) for r in inn - child)
            scored.append((score, sim, pid, shared))
        scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
        best = scored[0]
        second = scored[1][0] if len(scored) > 1 else None
        return {"parent": best[2], "score": best[0], "shared": sorted(best[3]), "similarity": round(best[1], 3),
                "margin": None if second is None else round(best[0] - second, 2)}

    def run(self, text: str | None = None, passage_id: str | None = None, *, min_coverage: float = 0.8,
            max_witnesses: int = 60, limit: int = 300) -> dict[str, Any]:
        con = self.concordance.run(text, passage_id, min_coverage=min_coverage, limit=limit)
        hits = [h for h in con["hits"] if h.get("years") and h["coverage"] >= min_coverage]
        undated = [h for h in con["hits"] if not h.get("years")]
        hits.sort(key=lambda h: (dated(h["years"]), -h["coverage"], h["passage_id"]))
        seen: set[tuple[str, str]] = set()
        nodes = []
        for h in hits:  # one witness per book and wording
            key = (h["book_id"], h["aligned"])
            if key not in seen:
                seen.add(key)
                nodes.append(h)
        nodes = nodes[:max_witnesses]
        if not nodes:
            return {"query": con["query"], "nodes": [], "edges": [], "root": None, "undated": len(undated),
                    "note": "no dated witness carries the passage"}
        root = nodes[0]
        base = root["aligned"]
        # the witnesses of the earliest date are all the source: a reading any of them has is not an innovation (宋本
        # writes this clause twice, 属桂枝汤 and 宜桂枝汤)
        first = [n for n in nodes if n["years"][0] <= root["years"][1] and n["years"][1] >= root["years"][0]]
        original = set().union(*(self.readings(base, n["aligned"]) for n in first))
        inn = {h["passage_id"]: self.readings(base, h["aligned"]) - original for h in nodes}
        edges = []
        for k, h in enumerate(nodes[1:], start=1):
            earlier = [n for n in nodes[:k] if dated(n["years"]) < dated(h["years"]) or n is root]
            cands = [(n["passage_id"], inn[n["passage_id"]],
                      difflib.SequenceMatcher(None, n["aligned"], h["aligned"], autojunk=False).ratio()) for n in earlier]
            pick = self.choose(inn[h["passage_id"]], cands, base)
            parent = next(n for n in earlier if n["passage_id"] == pick["parent"])
            via = pick["score"] > 0 and parent is not root
            if not via:
                pick.update(parent=root["passage_id"], shared=[], score=0.0)
                parent = root
            overlap = parent is not root and parent["years"][1] >= h["years"][0]
            edges.append({"from": parent["passage_id"], "to": h["passage_id"], "from_title": parent["title"], "to_title": h["title"],
                          "from_years": parent["years"], "to_years": h["years"], "relation": h["relation"],
                          "basis": "shared readings" if via else "none shared: from the earliest witness",
                          "shared": [{"root": base[i1:i2], "reading": r} for i1, i2, r in pick["shared"]][:8],
                          "score": pick["score"], "margin": pick["margin"], "similarity": pick["similarity"],
                          "uncertain": bool(via and (pick["margin"] is not None and pick["margin"] < 1)), "dates_overlap": overlap})
        depth: dict[str, int] = {root["passage_id"]: 0}
        for e in edges:
            depth[e["to"]] = depth.get(e["from"], 0) + 1
        return {
            "query": con["query"], "root": {k: root[k] for k in ("passage_id", "book_id", "title", "years", "locator", "quote")},
            "nodes": [{"passage_id": n["passage_id"], "book_id": n["book_id"], "title": n["title"], "years": n["years"],
                       "period": n["period"], "relation": n["relation"], "coverage": n["coverage"],
                       "innovations": len(inn[n["passage_id"]]), "depth": depth.get(n["passage_id"], 0),
                       "locator": n["locator"], "quote": n["quote"][:120]} for n in nodes],
            "edges": edges, "undated": len(undated), "source_witnesses": len(first),
            "summary": {"witnesses": len(nodes), "through_intermediaries": sum(1 for e in edges if e["basis"] == "shared readings"),
                        "uncertain": sum(1 for e in edges if e["uncertain"]), "depth": max(depth.values())},
            "note": "shared innovations (Lachmann): a reading none of the earliest-dated witnesses has is an innovation; a "
                    "witness hangs from the earlier one whose innovations it shares most, less that one's it lacks; with none "
                    "shared, from the earliest (directly or through a lost intermediary); one passage's route, not whole works'",
        }


__all__ = ["ChainStudy"]
