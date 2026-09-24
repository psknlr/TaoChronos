"""Knowledge plugin bundle: claim extraction, claim hypergraph, lineage engine, exports."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any, Iterable

from ...protocol.claims import Claim
from .export import json_graph, to_cypher, to_graphml, to_prov
from .extraction import EXTRACTOR_VERSION, ClaimExtractor
from .hypergraph import ClaimHypergraph
from .lineage import FormulaProfile, LineageBuilder, dose_value

WORKING_SET_LIMIT = 20_000


class KnowledgeBase:
    """Claim hypergraph over the corpus (used by graph retrieval and tools).

    Session-level claims live in the ResearchObject; this index is a cache that never bypasses the gates.
    For the demo corpus it covers every passage.  For a large corpus, claims are extracted *on demand* per
    passage (memoised, and persisted in the store's claim cache), and corpus-wide views outside a research
    session cover the *working set* — the passages retrieved or read so far in this process.
    """

    def __init__(self, registry: Any) -> None:
        self.registry = registry
        self._hypergraph: ClaimHypergraph | None = None
        self._claims: list | None = None
        self._lineage: list | None = None
        self._by_passage: OrderedDict[str, list[Claim]] = OrderedDict()
        self._working: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.RLock()
        self._version: str | None = None

    @property
    def corpus(self) -> Any:
        return self.registry.get("corpus")

    @property
    def large(self) -> bool:
        return bool(getattr(self.corpus, "large", False))

    def _cache_version(self) -> str:
        if self._version is None:
            pack = self.registry.get("domain")
            self._version = f"{EXTRACTOR_VERSION}|{pack.variants.fingerprint}"
        return self._version

    def touch(self, passage_ids: Iterable[str]) -> None:
        """Add passages to the working set (large corpora)."""
        with self._lock:
            for pid in passage_ids:
                self._working[pid] = None
                self._working.move_to_end(pid)
            while len(self._working) > WORKING_SET_LIMIT:
                self._working.popitem(last=False)
            self._hypergraph = None
            self._lineage = None

    def claims_for(self, passage_ids: Iterable[str]) -> list[Claim]:
        """Claims of the given passages (extracted once, then cached)."""
        ids = list(dict.fromkeys(passage_ids))
        extractor = self.registry.get("extractor")
        philology = self.registry.get("philology")
        corpus = self.corpus
        store = getattr(corpus, "store", None)
        version = self._cache_version()
        out: list[Claim] = []
        missing = [pid for pid in ids if pid not in self._by_passage]
        cached: dict[str, list[Claim]] = {}
        if store is not None and missing:
            for i in range(0, len(missing), 500):
                chunk = missing[i: i + 500]
                marks = ",".join("?" * len(chunk))
                with store.lock:
                    rows = store.db.execute(f"SELECT passage_id, data FROM claim_cache WHERE version=? AND passage_id IN ({marks})",
                                            [version, *chunk]).fetchall()
                for pid, data in rows:
                    cached[pid] = [Claim.from_dict(c) for c in json.loads(data)]
        fresh: dict[str, list[Claim]] = {}
        to_extract = [pid for pid in missing if pid not in cached]
        for p in (corpus.passages_by_id(to_extract) if hasattr(corpus, "passages_by_id") else [corpus.passage(x) for x in to_extract]):
            fresh[p.id] = extractor.extract(p, philology.assess(p))
        if store is not None and fresh:
            with store.lock:
                store.db.executemany(
                    "INSERT OR REPLACE INTO claim_cache(passage_id, version, data) VALUES (?, ?, ?)",
                    [(pid, version, json.dumps([c.to_dict() for c in cs], ensure_ascii=False)) for pid, cs in fresh.items()])
                store.db.commit()
        with self._lock:
            for pid, cs in {**cached, **fresh}.items():
                self._by_passage[pid] = cs
            while len(self._by_passage) > 4 * WORKING_SET_LIMIT:
                self._by_passage.popitem(last=False)
            for pid in ids:
                out.extend(self._by_passage.get(pid, []))
        return out

    def claims(self) -> list:
        if self.large:
            return self.claims_for(list(self._working))
        if self._claims is None:
            extractor = self.registry.get("extractor")
            philology = self.registry.get("philology")
            self._claims = [c for p in self.corpus.passages() for c in extractor.extract(p, philology.assess(p))]
        return self._claims

    def hypergraph(self, passage_ids: Iterable[str] | None = None) -> ClaimHypergraph:
        corpus = self.corpus
        year_fn = lambda c: corpus.year(corpus.passage(c.passage_id))  # noqa: E731
        if passage_ids is not None:
            return ClaimHypergraph(self.claims_for(passage_ids), year_fn=year_fn)
        if self._hypergraph is None:
            self._hypergraph = ClaimHypergraph(self.claims(), year_fn=year_fn)
        return self._hypergraph

    def lineage(self, passage_ids: Iterable[str] | None = None) -> list:
        if passage_ids is not None:
            ids = list(passage_ids)
            ps = self.corpus.passages_by_id(ids) if hasattr(self.corpus, "passages_by_id") else [self.corpus.passage(i) for i in ids]
            return self.registry.get("lineage").build(ps, self.claims_for(ids))
        if self._lineage is None:
            if self.large:
                ids = list(self._working)
                self._lineage = self.registry.get("lineage").build(self.corpus.passages_by_id(ids), self.claims_for(ids))
            else:
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
