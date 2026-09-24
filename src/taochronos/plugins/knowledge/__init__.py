"""Knowledge plugin bundle: claim extraction, claim hypergraph, lineage engine, exports."""

from __future__ import annotations

from typing import Any

from .export import json_graph, to_cypher, to_graphml, to_prov
from .extraction import ClaimExtractor
from .hypergraph import ClaimHypergraph
from .lineage import FormulaProfile, LineageBuilder, dose_value


class KnowledgeBase:
    """Corpus-wide claim hypergraph built once at bootstrap (used by graph retrieval and tools).

    Session-level claims live in the ResearchObject; this global index is a
    cache over the whole corpus that never bypasses the gates.
    """

    def __init__(self, registry: Any) -> None:
        self.registry = registry
        self._hypergraph: ClaimHypergraph | None = None
        self._claims: list | None = None
        self._lineage: list | None = None

    @property
    def corpus(self) -> Any:
        return self.registry.get("corpus")

    def claims(self) -> list:
        if self._claims is None:
            extractor = self.registry.get("extractor")
            philology = self.registry.get("philology")
            self._claims = [c for p in self.corpus.passages() for c in extractor.extract(p, philology.assess(p))]
        return self._claims

    def hypergraph(self) -> ClaimHypergraph:
        if self._hypergraph is None:
            corpus = self.corpus
            self._hypergraph = ClaimHypergraph(self.claims(), year_fn=lambda c: corpus.year(corpus.passage(c.passage_id)))
        return self._hypergraph

    def lineage(self) -> list:
        if self._lineage is None:
            self._lineage = self.registry.get("lineage").build(self.corpus.passages(), self.claims())
        return self._lineage


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    pack = registry.get("domain")
    corpus = registry.get("corpus")
    registry.register("extractor", "lexicon-rules", ClaimExtractor(pack), default=True)
    registry.register(
        "lineage",
        "classics",
        LineageBuilder(pack, corpus, registry.get("citations"), registry.get("reuse"),
                       min_shared=config.get("min_shared", 3), min_overlap=config.get("min_overlap", 0.5)),
        default=True,
    )
    registry.register("knowledge", "corpus", KnowledgeBase(registry), default=True)


__all__ = [
    "ClaimExtractor",
    "ClaimHypergraph",
    "FormulaProfile",
    "KnowledgeBase",
    "LineageBuilder",
    "dose_value",
    "json_graph",
    "register",
    "to_cypher",
    "to_graphml",
    "to_prov",
]
