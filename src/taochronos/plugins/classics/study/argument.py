"""医理论证 — the reasoning of a passage as a graph, and the way of reasoning of a work, compared with another's.

A passage's clauses become nodes with the concepts the lexicon finds in them; the discourse markers of
``argument.yaml`` give typed edges (``science.argumentation``).  ``profile`` reads the main text of a work's base
witness (or a sample of its passages) and counts relations per 1 000 clauses, the kinds of concept each relation
links, and the chains of steps; ``compare`` sets two works side by side — 伤寒论's 若…者…主之 against 温热论's
chains of cause and inference, say.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ....science.argumentation import build_graph, chains, compare, triples
from .base import StudyBase
from .stemma import mask_notes

_CLAUSE = re.compile(r"(?<=[，；：。！？])")
_SENTENCE_END = set("。！？")
_WEAK = {"herb", "formula"}


class ArgumentStudy:
    def __init__(self, base: StudyBase, stemma: Any) -> None:
        self.b = base
        self.stemma = stemma
        d = base.data("argument.yaml")
        n = base.normalize
        self.table = {rel: {"lead": [n(m) for m in spec.get("lead", [])], "tail": [n(m) for m in spec.get("tail", [])],
                            "direction": spec.get("direction", "from_previous")}
                      for rel, spec in (d.get("relations") or {}).items()}
        inner = "|".join(map(re.escape, (n(m) for m in d.get("inner_markers", []))))
        keep = [n(x) for x in d.get("inner_exceptions", [])]
        self._inner = re.compile(rf"(?<=[㐀-鿿])(?=(?:{inner})[㐀-鿿])") if inner else None
        self._keep = keep

    # ------------------------------------------------------------ one passage
    def clauses(self, text: str) -> list[dict[str, Any]]:
        norm = self.b.normalize(mask_notes(text))
        out: list[dict[str, Any]] = []
        sentence = 0
        for piece in (sub for part in _CLAUSE.split(norm) for sub in self._split_inner(part)):
            clause = piece.strip("　 \n")
            if not clause or not re.search(r"[㐀-鿿]", clause):
                continue
            concepts = [(m.entry.term, m.category) for m in self.b.pack.lexicon.match(clause, include_weak=False)
                        if not (len(m.surface) == 1 and m.category in _WEAK)]
            out.append({"text": clause, "sentence": sentence, "concepts": list(dict.fromkeys(concepts))})
            if clause[-1] in _SENTENCE_END:
                sentence += 1
        return out

    def _split_inner(self, clause: str) -> list[str]:
        """阳胜则热 → 阳胜 · 则热: a clause cut before an inner 则 / 故 (not inside 法则, 否则 …)."""
        if self._inner is None:
            return [clause]
        cuts = [m.start() for m in self._inner.finditer(clause)
                if not any(clause[max(0, m.start() - len(k) + 1): m.start() + len(k)].find(k) >= 0 for k in self._keep)]
        if not cuts:
            return [clause]
        out, last = [], 0
        for c in cuts:
            out.append(clause[last:c])
            last = c
        return out + [clause[last:]]

    def graph(self, text: str | None = None, passage_id: str | None = None) -> dict[str, Any]:
        p = self.b.corpus.passage(passage_id) if passage_id else None
        raw = text if text else (p.text if p else "")
        cl = self.clauses(raw)
        edges = build_graph(cl, self.table)
        return {"passage": self.b.witness(p) if p else None, "text": raw[:400], "clauses": cl, "edges": edges,
                "triples": [{"from": a, "relation": r, "to": b, "count": n} for (a, r, b), n in triples(cl, edges).most_common()],
                "chains": [{"chain": list(k), "count": n} for k, n in chains(len(cl), edges).most_common(10)]}

    # ------------------------------------------------------------ a work
    def _texts(self, work: str | None, books: list[str] | None, passages: int) -> tuple[list[str], list[tuple[str, str]]]:
        ids = self.stemma.base_witness(work, books)
        rows = [(pid, text) for bid in ids for pid, _, _, text in self.stemma._rows(bid)]
        if len(rows) > passages:
            step = len(rows) / passages
            rows = [rows[int(i * step)] for i in range(passages)]
        return ids, rows

    def profile(self, work: str | None = None, *, books: list[str] | None = None, passages: int = 600) -> dict[str, Any]:
        ids, rows = self._texts(work, books, passages)
        rel: Counter = Counter()
        tri: Counter = Counter()
        ch: Counter = Counter()
        examples: dict[str, list[dict[str, Any]]] = {}
        n_clauses = 0
        for pid, text in rows:
            cl = self.clauses(text)
            n_clauses += len(cl)
            edges = build_graph(cl, self.table)
            for e in edges:
                rel[e["relation"]] += 1
                if len(examples.setdefault(e["relation"], [])) < 3:
                    examples[e["relation"]].append({"passage_id": pid, "from": cl[e["source"]]["text"][:40],
                                                    "to": cl[e["target"]]["text"][:40], "marker": e["marker"]})
            tri.update(triples(cl, edges))
            ch.update(chains(len(cl), edges))
        book = self.b.corpus.books.get(ids[0])
        per = {k: round(1000 * v / n_clauses, 2) for k, v in rel.most_common()} if n_clauses else {}
        return {
            "work": book.title if book else work, "witness": ids, "passages": len(rows), "clauses": n_clauses,
            "edges": sum(rel.values()), "relations": dict(rel.most_common()), "per_1000_clauses": per,
            "triples": [{"from": a, "relation": r, "to": b, "count": n} for (a, r, b), n in tri.most_common(25)],
            "chains": [{"chain": list(k), "count": n} for k, n in ch.most_common(12)],
            "examples": examples, "_counts": {"relations": rel, "triples": tri},
            "note": "edges only where a discourse marker states the step (argument.yaml); per 1 000 clauses; triples: the "
                    "categories of concept a relation links (— = no concept the lexicon knows)",
        }

    def compare(self, a: str, b: str, *, passages: int = 600) -> dict[str, Any]:
        pa, pb = self.profile(a, passages=passages), self.profile(b, passages=passages)
        diff = compare(pa.pop("_counts"), pb.pop("_counts"))
        return {"a": pa, "b": pb, "comparison": diff,
                "note": "Jensen–Shannon divergence of the relation and triple distributions (0 = the same way of reasoning); "
                        "log-odds z-scores with an informative prior: positive = more typical of the first work"}


__all__ = ["ArgumentStudy"]
