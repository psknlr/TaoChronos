"""Lexical (BM25) and dense (hashed character n-gram) indexes over classical Chinese.

Classical Chinese needs no word segmentation for retrieval: character unigrams
and bigrams on variant-normalised text work well as lexical units.  The dense
index is a deterministic hashing embedder — a baseline stand-in for a trained
classical-Chinese encoder (GujiRoBERTa, GuwenBERT) or an API embedding model,
both of which plug in through the ``embedding`` capability.

On a large corpus both indexes are built anew for each search, over its candidates (``hybrid._local_indexes``:
thousands of passages tokenised, up to 1,500 embedded), so this module is where a search's time goes.  What it
computes is fixed — the same tokens, the same vectors, the same scores, bit for bit (``tests/test_retrieval_index.py``
compares them with the plain definitions) — and only how it gets there is arranged for speed: the characters read by
one regular-expression pass, an n-gram's hash kept once it is known, and what a search needs of the whole index
(its average length, a query token's weight) reckoned once per search and not once per passage.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from operator import mul

_KEEP = re.compile(r"[㐀-鿿豈-﫿]")


def han(text: str) -> list[str]:
    """The characters of a text the indexes read, in order: one pass (each match is one character)."""
    return _KEEP.findall(text)


def tokens(text: str) -> list[str]:
    chars = han(text)
    return chars + [a + b for a, b in zip(chars, chars[1:])]


def query_tokens(surface: str) -> list[str]:
    chars = han(surface)
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
        toks = tokens(text)
        counted = Counter(toks)
        self.docs[doc_id] = counted
        self.lengths[doc_id] = len(toks)
        self.df.update(counted.keys())

    @property
    def avgdl(self) -> float:
        return sum(self.lengths.values()) / max(1, len(self.lengths))

    def idf(self, token: str) -> float:
        n = len(self.docs)
        df = self.df.get(token, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def _score(self, doc_id: str, query: list[str], idf: dict[str, float], avgdl: float) -> float:
        """One passage's score, given what the query needs of the whole index: each of its tokens' weight (``idf``) and
        the average length — the same for every passage of a search, reckoned once by the caller."""
        toks = self.docs[doc_id]
        s = 0.0
        if not toks:  # nothing of it is read (and an index of such passages only has no average length to divide by)
            return s
        k1 = self.k1
        norm = k1 * (1 - self.b + self.b * self.lengths[doc_id] / avgdl)
        for q in query:
            tf = toks.get(q, 0)
            if tf:
                s += idf[q] * tf * (k1 + 1) / (tf + norm)
        return s

    def score(self, doc_id: str, query: list[str]) -> float:
        return self._score(doc_id, query, {q: self.idf(q) for q in set(query)}, self.avgdl)

    def search(self, query: list[str], k: int = 20, candidates: set[str] | None = None) -> list[tuple[str, float]]:
        ids = candidates if candidates is not None else self.docs.keys()
        idf = {q: self.idf(q) for q in set(query)}
        avgdl = self.avgdl
        scored = [(d, self._score(d, query, idf, avgdl)) for d in ids]
        scored = [t for t in scored if t[1] > 0]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]


# n-grams whose hash an embedder keeps at most (a search embeds up to 1,500 passages, and the same characters and
# words come back in every one): beyond, it starts again.  About 20 MB at the most — the browser's runtime keeps it too
GRAMS_KEPT = 100_000


class HashingEmbedder:
    """Deterministic character n-gram hashing embedder (signed feature hashing, L2-normalised)."""

    name = "hashing-char-ngram"

    def __init__(self, dim: int = 512, ngram: tuple[int, ...] = (1, 2, 3)) -> None:
        self.dim = dim
        self.ngram = ngram
        self._slots: dict[str, int] = {}  # an n-gram's place in the vector and its sign, once hashed (_slot)

    def _slot(self, gram: str) -> int:
        """Where an n-gram goes in the vector, and with which sign: 2 × its index, + 1 when it adds (kept as one small
        number, GRAMS_KEPT of them at most)."""
        h = int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")
        slot = (h % self.dim) * 2 + ((h >> 63) & 1)
        if len(self._slots) >= GRAMS_KEPT:
            self._slots.clear()
        self._slots[gram] = slot
        return slot

    def embed(self, text: str) -> list[float]:
        chars = "".join(han(text))  # each is one character of the Basic Multilingual Plane: a slice is an n-gram
        vec = [0.0] * self.dim
        slots = self._slots
        for n in self.ngram:
            weight = 1.0 + 0.5 * (n - 1)
            signed = (-weight, weight)
            for i in range(len(chars) - n + 1):
                gram = chars[i: i + n]
                slot = slots.get(gram)
                if slot is None:
                    slot = self._slot(gram)
                vec[slot >> 1] += signed[slot & 1]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(map(mul, a, b))


class DenseIndex:
    def __init__(self, embedder: HashingEmbedder) -> None:
        self.embedder = embedder
        self.vectors: dict[str, list[float]] = {}

    def add(self, doc_id: str, text: str) -> None:
        self.vectors[doc_id] = self.embedder.embed(text)

    def search(self, text: str, k: int = 20, candidates: set[str] | None = None) -> list[tuple[str, float]]:
        q = self.embedder.embed(text)
        ids = candidates if candidates is not None else self.vectors.keys()
        vectors = self.vectors
        scored = [(d, cosine(q, vectors[d])) for d in ids]
        scored = [t for t in scored if t[1] > 0.05]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]
