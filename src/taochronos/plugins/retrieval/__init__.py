"""Retrieval plugin bundle: BM25, dense, graph, temporal, citation, variant and sense routes fused
into the Philology-Aware Temporal GraphRAG retriever."""

from __future__ import annotations

from typing import Any

from .hybrid import DEFAULT_WEIGHTS, ROUTES, Hit, HybridRetriever, ParsedQuery, QueryAnalyzer
from .index import BM25Index, DenseIndex, HashingEmbedder, cosine, query_tokens, tokens


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    embedder = registry.get("embedding") if registry.has("embedding") else HashingEmbedder()
    if not registry.has("embedding"):
        registry.register("embedding", "hashing", embedder, default=True)
    retriever = HybridRetriever(
        registry.get("domain"),
        registry.get("corpus"),
        knowledge=registry.get("knowledge") if registry.has("knowledge") else None,
        embedder=embedder,
        weights=config.get("route_weights"),
    )
    registry.register("retriever", "hybrid", retriever, default=True)


__all__ = [
    "BM25Index",
    "DEFAULT_WEIGHTS",
    "DenseIndex",
    "HashingEmbedder",
    "Hit",
    "HybridRetriever",
    "ParsedQuery",
    "QueryAnalyzer",
    "ROUTES",
    "cosine",
    "query_tokens",
    "register",
    "tokens",
]
