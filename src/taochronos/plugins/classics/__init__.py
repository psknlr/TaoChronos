"""Classics plugin bundle: domain pack, corpus, philology, citations and text reuse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .citations import CitationExtractor, CitationMention
from .corpus import Corpus, ExternalWork
from .domain import DomainPack, Lexicon, LexEntry, Mention, Periods, Terminology, VariantTable
from .philology import PhilologyService
from .reuse import ReuseMatch, TextReuseDetector, strip_punct
from .segment import Segmenter, SegmentedView, is_unpunctuated
from .store import CorpusStore, StoreCorpus
from .study import StudyService


def _store_path(value: str, context: Any) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    data = Path(getattr(context, "data_dir", ".taochronos"))
    return data / path


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    home = Path(getattr(context, "home", "."))
    pack = DomainPack(home / config.get("domain", "domains/classics"), extra_lexicons=config.get("lexicon_extra", ()))
    if config.get("corpus_object") is not None:
        corpus = config["corpus_object"]
    elif config.get("store"):
        path = _store_path(config["store"], context)
        corpus = StoreCorpus(CorpusStore(path), pack.variants.normalize_text, fingerprint=pack.variants.fingerprint,
                             root=path.parent, exclude_books=config.get("exclude_books", ()))
    else:
        corpus = Corpus.load(home / config.get("corpus", "corpus/demo"))
    if not getattr(corpus, "large", False) and getattr(corpus, "normalize", None) is None:
        corpus.normalize = pack.variants.normalize_text
    registry.register("domain", "classics", pack, default=True)
    registry.register("corpus", config.get("name", "store" if getattr(corpus, "large", False) else "demo"), corpus, default=True)
    registry.register("philology", "classics", PhilologyService(pack, corpus), default=True)
    registry.register("citations", "classics", CitationExtractor(pack, corpus), default=True)
    detector = TextReuseDetector(pack)
    if getattr(corpus, "large", False):
        detector.use_corpus_statistics(corpus)  # bigram document frequencies from the full-text index, on demand
    else:
        detector.fit(corpus.passages())
    registry.register("reuse", "classics", detector, default=True)
    registry.register("study", "classics", StudyService(pack, corpus), default=True)


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
    "CorpusStore",
    "ReuseMatch",
    "Segmenter",
    "SegmentedView",
    "StoreCorpus",
    "StudyService",
    "is_unpunctuated",
    "Terminology",
    "TextReuseDetector",
    "VariantTable",
    "register",
    "strip_punct",
]
