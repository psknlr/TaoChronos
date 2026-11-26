"""The retrieval indexes (``plugins/retrieval/index.py``) give what their plain definitions give, bit for bit.

A search over a large corpus builds both indexes anew over its candidates, so the module is arranged for speed; this
compares it with the definitions written the plain way — the tokens, each passage's vector, every score and the order
of the results — on passages of the demonstration corpus and on texts made to try the edges.  A ranking that moved by
one place would show here before it showed in an answer.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter

from taochronos.plugins.retrieval import index
from taochronos.plugins.retrieval.index import BM25Index, DenseIndex, HashingEmbedder, cosine, query_tokens, tokens

KEEP = re.compile(r"[\u3400-\ud7ff\ue000-\ufaff]")  # by number: see index._KEEP


# ---------------------------------------------------------------- the plain definitions
def plain_tokens(text: str) -> list[str]:
    chars = [c for c in text if KEEP.match(c)]
    out = list(chars)
    out.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    return out


def plain_embed(text: str, dim: int = 512, ngram: tuple[int, ...] = (1, 2, 3)) -> list[float]:
    chars = [c for c in text if KEEP.match(c)]
    vec = [0.0] * dim
    for n in ngram:
        for i in range(len(chars) - n + 1):
            gram = "".join(chars[i: i + n])
            h = int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")
            vec[h % dim] += (1.0 if (h >> 63) & 1 else -1.0) * (1.0 + 0.5 * (n - 1))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def plain_cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class PlainBM25:
    def __init__(self, k1: float = 1.4, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs: dict[str, Counter] = {}
        self.lengths: dict[str, int] = {}
        self.df: Counter = Counter()

    def add(self, doc_id: str, text: str) -> None:
        toks = Counter(plain_tokens(text))
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


def plain_dense_search(vectors: dict[str, list[float]], text: str, k: int, candidates: set[str] | None = None) -> list[tuple[str, float]]:
    q = plain_embed(text)
    ids = candidates if candidates is not None else vectors.keys()
    scored = [(d, plain_cosine(q, vectors[d])) for d in ids]
    scored = [t for t in scored if t[1] > 0.05]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored[:k]


# ---------------------------------------------------------------- texts
EDGES = [
    "", "。", "abc 123", "桂", "桂枝", "桂枝汤", "太阳病，头痛，发热，汗出，恶风，桂枝汤主之。",
    "太陽病，頭痛，發熱（繁體）", "〇○々 桂 枝",
    "\uf900\uf901\uf902\uf903\uf904\uf905\uf906\uf907 — the compatibility ideographs (by number)",
    "𠀀𠀁 beyond the plane 桂枝 𪚥",
    "消渴消渴消渴消渴", "阳浮而阴弱，阳浮者，热自发；阴弱者，汗自出。", "ａｂ　全角　与　半角 mixed 桂 枝\n汤\t主之",
]


def texts() -> list[str]:
    from taochronos.bootstrap import Harness

    h = Harness.from_profile("full-discovery", ephemeral=True)
    normalize = h.pack.variants.normalize_text
    out = [normalize(p.text) for p in h.corpus.passages()]
    rng = random.Random(20261110)
    pool = "".join(out)
    for _ in range(120):  # texts cut and joined at random: lengths from none to long, every mix of marks and characters
        n = rng.choice([0, 1, 2, 3, 7, 30, 120, 400])
        start = rng.randrange(max(1, len(pool) - n))
        out.append(pool[start: start + n] + rng.choice(["", "，", " x ", "。\n"]) + pool[start: start + rng.randrange(4)])
    return EDGES + out


def test_the_tokens_and_the_vectors_are_the_plain_ones():
    embedder = HashingEmbedder()
    all_texts = texts()
    assert len(all_texts) > 150
    for text in all_texts:
        assert tokens(text) == plain_tokens(text)
        assert embedder.embed(text) == plain_embed(text)  # every one of the 512 numbers, exactly
    assert query_tokens("桂") == ["桂"] and query_tokens("桂枝汤") == ["桂枝", "枝汤"] and query_tokens("abc") == []
    # another size and other n-grams; and the same vectors again once the hashes are kept, and once they are dropped
    small = HashingEmbedder(dim=64, ngram=(2, 4))
    for text in all_texts[:60]:
        assert small.embed(text) == plain_embed(text, 64, (2, 4))
    again = [embedder.embed(t) for t in all_texts]
    assert again == [plain_embed(t) for t in all_texts]
    assert embedder.embed_many(all_texts[:5]) == again[:5]


def test_an_embedder_keeps_only_so_many_hashes_and_gives_the_same_vectors(monkeypatch):
    monkeypatch.setattr(index, "GRAMS_KEPT", 50)  # small enough to be reached, and passed, many times
    embedder = HashingEmbedder()
    for text in texts():
        assert embedder.embed(text) == plain_embed(text)
        assert len(embedder._slots) <= 25 and len(embedder._old) <= 25  # two halves: GRAMS_KEPT in all


def test_the_characters_read_are_named_by_number():
    """The class was once written with the characters themselves, and an editor's normalisation had turned the first of
    the compatibility ideographs (U+F900) into its unified form (U+8C48): one range, U+3400–U+FAFF, which the indexes
    read to this day.  Written by number now, and pinned here by number."""
    for cp in (0x3400, 0x4E00, 0x8C48, 0x9FFF, 0xA000, 0xAC00, 0xD7A3, 0xD7FF, 0xE000, 0xE3E7, 0xF8FF, 0xF900, 0xFA0E, 0xFAFF):
        assert index.kept(chr(cp)) == chr(cp) and index.han(chr(cp)) == [chr(cp)], hex(cp)
    for cp in (0x41, 0x3000, 0x3007, 0x33FF, 0xD800, 0xDBFF, 0xDC00, 0xDFFF, 0xFB00, 0xFF0C, 0x20000, 0x2A6A5):
        assert index.kept(chr(cp)) == "" and index.han(chr(cp)) == [], hex(cp)
    for text in texts():
        assert index.kept(text) == "".join(index.han(text))
    # a lone surrogate (an unpaired escape in JSON, bytes read with surrogateescape) is not read: no token, no n-gram
    assert tokens("桂\ud800枝") == tokens("桂枝") and HashingEmbedder().embed("桂\udfff枝") == plain_embed("桂枝")


def test_bm25_scores_and_ranks_as_the_plain_index_does():
    all_texts = texts()
    fast, plain = BM25Index(), PlainBM25()
    for i, text in enumerate(all_texts):
        fast.add(f"p{i:04d}", text)
        plain.add(f"p{i:04d}", text)
    assert fast.docs == plain.docs and fast.lengths == plain.lengths and fast.df == plain.df
    assert fast.avgdl == plain.avgdl
    rng = random.Random(7)
    queries = [query_tokens(q) for q in ("桂枝汤", "消渴", "太阳病头痛发热", "汗", "阴阳", "麻黄汤主之", "不存在的词语", "")]
    queries.append(query_tokens("桂枝") * 3)  # a token asked more than once counts each time
    ids = sorted(fast.docs)
    for query in queries:
        for doc in rng.sample(ids, 40):
            assert fast.score(doc, query) == plain.score(doc, query)
        for k in (1, 5, 20, 1000):
            assert fast.search(query, k) == plain.search(query, k)
        some = set(rng.sample(ids, 60))
        assert fast.search(query, 20, some) == plain.search(query, 20, some)
        assert fast.search(query, 20, set()) == []
    # passages of which nothing is read (no character the index keeps): scored 0, never a division by no length
    empty = BM25Index()
    empty.add("a", "abc")
    empty.add("b", "。。")
    assert empty.avgdl == 0 and empty.score("a", ["桂枝"]) == 0.0 and empty.search(["桂枝"]) == []
    assert BM25Index().search(["桂枝"]) == []


def test_the_dense_index_ranks_as_the_plain_one_does():
    all_texts = texts()
    dense = DenseIndex(HashingEmbedder())
    for i, text in enumerate(all_texts):
        dense.add(f"p{i:04d}", text)
    vectors = {f"p{i:04d}": plain_embed(text) for i, text in enumerate(all_texts)}
    assert dense.vectors == vectors
    rng = random.Random(11)
    ids = sorted(vectors)
    for a, b in zip(rng.sample(ids, 80), rng.sample(ids, 80)):
        assert cosine(vectors[a], vectors[b]) == plain_cosine(vectors[a], vectors[b])
    for query in ("桂枝汤的主治", "消渴 三消", "太阳之为病，脉浮，头项强痛而恶寒", "汗出恶风", "", "abc"):
        for k in (1, 10, 500):
            assert dense.search(query, k) == plain_dense_search(vectors, query, k)
        some = set(rng.sample(ids, 50))
        assert dense.search(query, 20, some) == plain_dense_search(vectors, query, 20, some)


# ---------------------------------------------------------------- searches asked at the same time
def test_searches_asked_at_once_do_not_read_each_others_candidates(tmp_path):
    """A server runs its callers' searches on threads — a page sends a round's calls four at a time — and a search keeps
    what it reads of its candidates while it runs (their ranks in the index, the indexes built over them).  Each
    thread's are its own: a search asked while another is part-way neither waits for it nor touches what it keeps, and
    both give what they give asked alone."""
    import copy
    import threading
    from pathlib import Path

    from taochronos.plugins.classics.domain import DomainPack
    from taochronos.plugins.classics.ingest import ingest_kanripo, load_catalog
    from taochronos.plugins.classics.store import CorpusStore, StoreCorpus
    from taochronos.plugins.retrieval import HybridRetriever

    home = Path(__file__).resolve().parents[1]
    fixtures = home / "tests" / "fixtures" / "kanripo"
    pack = DomainPack(home / "domains" / "classics")
    store = CorpusStore(tmp_path / "corpus" / "tcm.sqlite", create=True)
    ingest_kanripo(store, load_catalog(fixtures / "catalog.yaml"), fixtures, pack.variants.normalize_text, pack.variants.fingerprint,
                   log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    store.optimize()
    retriever = HybridRetriever(pack, StoreCorpus(store, pack.variants.normalize_text, fingerprint=pack.variants.fingerprint))
    assert retriever.large  # the indexes are built per search, over its candidates

    def found(text: str) -> list[tuple[str, float, list[str]]]:
        return [(h.passage_id, h.score, sorted(h.routes)) for h in retriever.search(text, k=8)[1]]

    assert retriever._rank == {}  # a thread that has run no search reads no ranks
    queries = ["五苓散", "消渴", "小便不利", "脉浮"]
    alone = {q: found(q) for q in queries}
    assert alone["五苓散"] and alone["五苓散"] != alone["消渴"]

    # the first search stops part-way — its candidates read, its indexes about to be built — while the second is asked
    # and runs to its end; the first then goes on with what it had
    inside, go = threading.Event(), threading.Event()
    build = retriever._local_indexes
    held: dict[str, object] = {}

    def paused(cand):
        if threading.current_thread() is first:
            held["before"] = dict(retriever._rank)
            inside.set()
            assert go.wait(20)
            held["after"] = dict(retriever._rank)
        return build(cand)

    retriever._local_indexes = paused
    got: dict[str, list] = {}
    first = threading.Thread(target=lambda: got.__setitem__("first", found("五苓散")))
    second = threading.Thread(target=lambda: got.__setitem__("second", found("消渴")))
    first.start()
    assert inside.wait(20)
    second.start()
    second.join(20)
    assert got == {"second": alone["消渴"]}                 # it did not wait for the first, and gave what it gives alone
    go.set()
    first.join(20)
    assert held["before"] and held["after"] == held["before"]  # the first's candidates were still its own
    assert got == {"first": alone["五苓散"], "second": alone["消渴"]}
    # and many at once, over and over: each as alone
    retriever._local_indexes = build
    for _ in range(5):
        out: dict[str, list] = {}
        threads = [threading.Thread(target=lambda q=q: out.__setitem__(q, found(q))) for q in queries]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert out == alone
    # a copy of the retriever (the evaluations make one) searches as the retriever does
    twin = copy.copy(retriever)
    assert [(h.passage_id, h.score, sorted(h.routes)) for h in twin.search("五苓散", k=8)[1]] == alone["五苓散"]
    assert found("消渴") == alone["消渴"]
    store.close()
