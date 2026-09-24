"""Classics plugin bundle: domain pack, corpus, philology, citations and text reuse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .citations import CitationExtractor, CitationMention
from .corpus import Corpus, ExternalWork
from .domain import DomainPack, Lexicon, LexEntry, Mention, Periods, Terminology, VariantTable
from .philology import PhilologyService
from .reuse import ReuseMatch, TextReuseDetector, strip_punct


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    home = Path(getattr(context, "home", "."))
    pack = DomainPack(home / config.get("domain", "domains/classics"))
    corpus = config.get("corpus_object") or Corpus.load(home / config.get("corpus", "corpus/demo"))
    registry.register("domain", "classics", pack, default=True)
    registry.register("corpus", config.get("name", "demo"), corpus, default=True)
    registry.register("philology", "classics", PhilologyService(pack, corpus), default=True)
    registry.register("citations", "classics", CitationExtractor(pack, corpus), default=True)
    detector = TextReuseDetector(pack)
    detector.fit(corpus.passages())
    registry.register("reuse", "classics", detector, default=True)


__all__ = [
    "CitationExtractor",
    "CitationMention",
    "Corpus",
    "DomainPack",
    "ExternalWork",
    "LexEntry",
    "Lexicon",
    "Mention",
    "Periods",
    "PhilologyService",
    "ReuseMatch",
    "Terminology",
    "TextReuseDetector",
    "VariantTable",
    "register",
    "strip_punct",
]
