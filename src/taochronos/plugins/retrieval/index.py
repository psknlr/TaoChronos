"""Lexical (BM25) and dense (hashed character n-gram) indexes over classical Chinese.

Classical Chinese needs no word segmentation for retrieval: character unigrams
and bigrams on variant-normalised text work well as lexical units.  The dense
index is a deterministic hashing embedder — a baseline stand-in for a trained
classical-Chinese encoder (GujiRoBERTa, GuwenBERT) or an API embedding model,
both of which plug in through the ``embedding`` capability.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

_KEEP = re.compile(r"[㐀-鿿豈-﫿]")


def tokens(text: str) -> list[str]:
    chars = [c for c in text if _KEEP.match(c)]
    out = list(chars)
    out.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    return out


def query_tokens(surface: str) -> list[str]:
    chars = [c for c in surface if _KEEP.match(c)]
    if len(chars) == 1:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


@dataclass
class BM25Index:
    k1: float = 1.4
    b: float = 0.75
    docs: dict[str, Counter] = field(default_factory=dict)
    lengths: dict[str, int] = field(default_factory=dict)
    df: Counter = field(default_factory=Counter)

    def add(self, doc_id: str, text: str) -> None:
        toks = Counter(tokens(text))
        self.docs[doc_id] = toks
        self.lengths[doc_id] = sum(toks.values())
        self.df.update(toks.keys())

    @property
    def avgdl(self) -> float:
        return sum(self.lengths.values()) / max(1, len(self.lengths))

    def idf(self, token: str) -> float:
        n = len(self.docs)
        df = self.df.get(token, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, doc_id: str, query: list[str]) -> float:
        toks = self.docs[doc_id]
        dl = self.lengths[doc_id]
        s = 0.0
        for q in query:
            tf = toks.get(q, 0)
            if tf:
                s += self.idf(q) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: list[str], k: int = 20, candidates: set[str] | None = None) -> list[tuple[str, float]]:
        ids = candidates if candidates is not None else self.docs.keys()
        scored = [(d, self.score(d, query)) for d in ids]
        scored = [t for t in scored if t[1] > 0]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]


class HashingEmbedder:
    """Deterministic character n-gram hashing embedder (signed feature hashing, L2-normalised)."""

    name = "hashing-char-ngram"

    def __init__(self, dim: int = 512, ngram: tuple[int, ...] = (1, 2, 3)) -> None:
        self.dim = dim
        self.ngram = ngram

    def embed(self, text: str) -> list[float]:
        chars = [c for c in text if _KEEP.match(c)]
        vec = [0.0] * self.dim
        for n in self.ngram:
            for i in range(len(chars) - n + 1):
                gram = "".join(chars[i: i + n])
                h = int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")
                vec[h % self.dim] += (1.0 if (h >> 63) & 1 else -1.0) * (1.0 + 0.5 * (n - 1))
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class DenseIndex:
    def __init__(self, embedder: HashingEmbedder) -> None:
        self.embedder = embedder
        self.vectors: dict[str, list[float]] = {}

    def add(self, doc_id: str, text: str) -> None:
        self.vectors[doc_id] = self.embedder.embed(text)

    def search(self, text: str, k: int = 20, candidates: set[str] | None = None) -> list[tuple[str, float]]:
        q = self.embedder.embed(text)
        ids = candidates if candidates is not None else self.vectors.keys()
        scored = [(d, cosine(q, self.vectors[d])) for d in ids]
        scored = [t for t in scored if t[1] > 0.05]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]
