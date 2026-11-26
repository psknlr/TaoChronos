"""TaoCore: a search's own rankings over its candidates — BM25 of its query's tokens and the dense route's cosines —
by a compiled kernel where one is present, by the Python definitions otherwise, the same numbers either way.

On a large corpus each search ranks its few thousand candidates anew (``hybrid._local_indexes``), and those two
rankings were most of a search's time: 70% of a warm one in CPython and in the browser's Pyodide alike, nearly all of
it in loops Python runs a character at a time (docs/adr/0036-taocore.md has the measurements).  The kernel
(``rust/``) runs those loops, in two builds behind one interface: ``_taocore``, a CPython extension
(``rust/crates/taocore-py``), and ``_taocore_wasm``, the browser's WebAssembly module, which the runtime worker
registers before Python starts (``web/js/taocore.js``).  Neither is needed.  Without one — or when one fails, or gives
other rankings than the definitions on the self-test it runs before it is first used — a search runs the definitions
here and in ``index.py``, which are the reference.

What depends on the platform stays in Python: a token's weight (idf) is ``math.log`` of the C library Python runs on
(glibc, musl and a wasm32 build disagree in the last bit of some), the average length is Python's int / int, and the
kernel sums as this Python's ``sum()`` does (``COMPENSATED``: from CPython 3.12 a float sum is compensated).  So each
result is the one the definitions give on the same interpreter: the extension's beside CPython, the module's beside
Pyodide.

``TAOCHRONOS_TAOCORE`` says how: ``auto`` (the default) uses a kernel that passed its self-test; ``off`` never does;
``require`` fails a search rather than run it without one (how CI shows the kernel really ran); ``shadow`` computes
both and answers with the definitions', counting any difference (``status()``).
"""

from __future__ import annotations

import math
import os
import re
import threading
from array import array
from typing import Any, Callable

from .index import B, DENSE_FLOOR, K1, HashingEmbedder, cosine, kept

ABI = 1  # what the kernel's bindings must speak (rust/crates/taocore/src/lib.rs: ABI)
SEPARATOR = "\x1f"  # between a batch's texts: no character the indexes read
MODES = ("auto", "off", "require", "shadow")
MAX_NGRAM = 42  # the longest n-gram the kernel hashes (one BLAKE2b block)
# which summation this Python's sum() does over floats: compensated (CPython 3.12 and later) or plain (3.11)
COMPENSATED = sum([1e100, 1.0, -1e100]) == 1.0

Ranked = list[tuple[str, float]]


class Unsuitable(Exception):
    """What this search asks is not the kernel's to compute (another embedder, a text holding the separator, a token
    that is not one or two characters the indexes read): it runs the definitions, and the kernel stays in use."""


def mode() -> str:
    """``TAOCHRONOS_TAOCORE``, read each time (``auto`` when unset or not one of MODES)."""
    chosen = os.environ.get("TAOCHRONOS_TAOCORE", "").strip().lower()
    return chosen if chosen in MODES else "auto"


# ---------------------------------------------------------------- the kernels
class _Native:
    """``_taocore``, the CPython extension."""

    name = "native"

    def __init__(self, module: Any) -> None:
        self._batch = module.Batch

    def batch(self, data: bytes, count: int) -> Any:
        return _NativeBatch(self._batch(data, count))


class _NativeBatch:
    def __init__(self, batch: Any) -> None:
        self._b = batch

    def count(self, tokens: list[str]) -> tuple[list[int], int]:
        return self._b.count(tokens)

    def bm25(self, idf: list[float], avgdl: float, k: int) -> tuple[list[int], list[float]]:
        return self._b.bm25(idf, avgdl, K1, B, k)

    def dense(self, places: list[int], query: bytes, dim: int, ngram: list[int], k: int) -> tuple[list[int], list[float]]:
        return self._b.dense(places, query, dim, ngram, COMPENSATED, DENSE_FLOOR, k)


class _Wasm:
    """``_taocore_wasm``, the browser's module as its loader presents it (web/js/taocore.js): arrays go in as Python
    bytes (copied once into the module's memory), and come back as JavaScript arrays."""

    name = "wasm"

    def __init__(self, module: Any) -> None:
        self._batch = module.batch  # bound once: a lookup on the module crosses into JavaScript each time

    def batch(self, data: bytes, count: int) -> Any:
        return _WasmBatch(self._batch(data, count))


class _WasmBatch:
    def __init__(self, batch: Any) -> None:
        self._b = batch

    def count(self, tokens: list[str]) -> tuple[list[int], int]:
        got = self._b.count("\n".join(tokens).encode("utf-8"))
        return [int(x) for x in got.df], int(got.total)

    def bm25(self, idf: list[float], avgdl: float, k: int) -> tuple[list[int], list[float]]:
        got = self._b.bm25(array("d", idf).tobytes(), avgdl, K1, B, k)
        return [int(x) for x in got.places], [float(x) for x in got.scores]

    def dense(self, places: list[int], query: bytes, dim: int, ngram: list[int], k: int) -> tuple[list[int], list[float]]:
        got = self._b.dense(array("I", places).tobytes(), query, dim, array("I", ngram).tobytes(), int(COMPENSATED),
                            DENSE_FLOOR, k)
        return [int(x) for x in got.places], [float(x) for x in got.scores]


def _find() -> tuple[Any, str]:
    """The kernel this Python can reach, or None and why not."""
    try:
        import _taocore  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        if getattr(_taocore, "ABI", None) == ABI:
            return _Native(_taocore), ""
        return None, f"_taocore speaks ABI {getattr(_taocore, 'ABI', None)}, not {ABI}"
    try:
        import _taocore_wasm  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        if getattr(_taocore_wasm, "abi", None) == ABI:
            return _Wasm(_taocore_wasm), ""
        return None, f"_taocore_wasm speaks ABI {getattr(_taocore_wasm, 'abi', None)}, not {ABI}"
    return None, "no kernel: neither _taocore (rust/crates/taocore-py) nor the browser's _taocore_wasm is present"


_lock = threading.Lock()
_state: dict[str, Any] = {"checked": False, "kernel": None, "reason": ""}
_counts = {"bm25": 0, "dense": 0, "python": 0, "failed": 0, "differed": 0}


def kernel() -> Any:
    """The kernel in use: found, and checked against the definitions, at the first call (None when there is none)."""
    if _state["checked"]:
        return _state["kernel"]
    with _lock:
        if not _state["checked"]:
            found, why = _find()
            if found is not None:
                try:
                    why = _selftest(found)
                except Exception as err:  # noqa: BLE001 — a kernel that fails its self-test is not used, whatever the failure
                    why = f"the self-test failed: {type(err).__name__}: {err}"
                if why:
                    why, found = f"{found.name}: {why}", None
            _state.update(checked=True, kernel=found, reason=why)
    return _state["kernel"]


def _put_aside(kern: Any, err: BaseException) -> None:
    """A kernel that failed during a search is not used again in this process: the definitions answer from here."""
    with _lock:
        if _state["kernel"] is kern:
            _state.update(kernel=None, reason=f"{kern.name}: put aside after {type(err).__name__}: {err}")
    _counts["failed"] += 1


def status() -> dict[str, Any]:
    """Which kernel searches use and why (for the runtime's information), and how often each way ran."""
    chosen = mode()
    kern = kernel() if chosen != "off" else None
    return {"mode": chosen, "kernel": kern.name if kern else None,
            "reason": "TAOCHRONOS_TAOCORE=off" if chosen == "off" else _state["reason"], **_counts}


def reset() -> None:
    """Forget the kernel found (tests: after a change of what is importable)."""
    with _lock:
        _state.update(checked=False, kernel=None, reason="")
        for key in _counts:
            _counts[key] = 0


def _bits(ranked: Ranked) -> list[tuple[str, str]]:
    return [(pid, float(score).hex()) for pid, score in ranked]


# ---------------------------------------------------------------- a search's indexes
class LocalIndexes:
    """A search's candidates, as its BM25 and dense routes read them (large corpora: ``hybrid._local_indexes``).

    ``ids`` are in order, so that a tie broken by a candidate's place is broken by its id; ``texts`` are theirs,
    normalised; ``dense`` names the places of the dense route's candidates, the index's best first.  Nothing is
    computed until a route asks: the kernel's copy of the texts at the first route that uses it, and for the
    definitions, each text's characters read once for both."""

    def __init__(self, ids: list[str], texts: list[str], dense: list[int], embedder: Any) -> None:
        self.ids = ids
        self.texts = texts
        self.dense_places = dense
        self.embedder = embedder
        self._batch: Any = None
        self._batch_of: Any = None
        self._kept: list[str] | None = None

    # ---- the routes
    def bm25(self, query: list[str], k: int) -> Ranked:
        """BM25Index.search(query, k) over the candidates: the same scores, the same order."""
        if not query or not self.ids:
            return []
        return self._run("bm25", lambda kern: self._bm25_kernel(kern, query, k), lambda: self._bm25_python(query, k))

    def dense(self, text: str, k: int) -> Ranked:
        """DenseIndex.search(text, k) over the dense route's candidates: the same cosines, the same order."""
        if not self.dense_places:
            return []
        return self._run("dense", lambda kern: self._dense_kernel(kern, text, k), lambda: self._dense_python(text, k))

    def _run(self, route: str, fast: Callable[[Any], Ranked], slow: Callable[[], Ranked]) -> Ranked:
        chosen = mode()
        kern = kernel() if chosen != "off" else None
        if kern is None:
            if chosen == "require":
                raise RuntimeError(f"TAOCHRONOS_TAOCORE=require, and no kernel is in use: {_state['reason']}")
            _counts["python"] += 1
            return slow()
        try:
            got = fast(kern)
        except Unsuitable:
            _counts["python"] += 1
            return slow()
        except Exception as err:  # noqa: BLE001 — whatever went wrong in the kernel, the definitions answer
            if chosen == "require":
                raise
            _put_aside(kern, err)
            _counts["python"] += 1
            return slow()
        if chosen == "shadow":
            want = slow()
            if _bits(got) != _bits(want):
                _counts["differed"] += 1
                with _lock:
                    _state["reason"] = f"shadow: {route} differed from the definitions"
            return want
        _counts[route] += 1
        return got

    # ---- by the kernel
    def _batch_for(self, kern: Any) -> Any:
        if self._batch is None or self._batch_of is not kern:
            joined = SEPARATOR.join(self.texts)
            if joined.count(SEPARATOR) != len(self.texts) - 1:
                raise Unsuitable("a text holds the separator")
            # a lone surrogate cannot be encoded: '?' stands for it, which the indexes do not read either
            self._batch = kern.batch(joined.encode("utf-8", "replace"), len(self.texts))
            self._batch_of = kern
        return self._batch

    def _bm25_kernel(self, kern: Any, query: list[str], k: int) -> Ranked:
        if not all(len(t) in (1, 2) and kept(t) == t for t in query):
            raise Unsuitable("a token that is not one or two of the characters read")
        batch = self._batch_for(kern)
        df, total = batch.count(query)
        n = len(self.ids)
        idf = [math.log(1 + (n - x + 0.5) / (x + 0.5)) for x in df]  # BM25Index.idf, with this Python's log
        places, scores = batch.bm25(idf, total / max(1, n), k)  # BM25Index.avgdl: int / int
        return [(self.ids[p], s) for p, s in zip(places, scores)]

    def _dense_kernel(self, kern: Any, text: str, k: int) -> Ranked:
        e = self.embedder
        if type(e) is not HashingEmbedder or e.dim < 1 or not all(1 <= n <= MAX_NGRAM for n in e.ngram):
            raise Unsuitable("an embedder the kernel does not compute")
        batch = self._batch_for(kern)
        places, scores = batch.dense(self.dense_places, text.encode("utf-8", "replace"), e.dim, list(e.ngram), k)
        return [(self.ids[p], s) for p, s in zip(places, scores)]

    # ---- by the definitions
    def _kept_texts(self) -> list[str]:
        if self._kept is None:
            self._kept = [kept(t) for t in self.texts]
        return self._kept

    def _bm25_python(self, query: list[str], k: int) -> Ranked:
        """What BM25Index.search computes, from what it reads: each candidate's length and the query tokens' counts in
        it (an index of every token of every candidate is built for nothing but these)."""
        texts = self._kept_texts()
        n = len(texts)
        lengths = [2 * len(t) - 1 if t else 0 for t in texts]  # the characters and the bigrams
        avgdl = sum(lengths) / max(1, n)
        tf: dict[str, dict[int, int]] = {}
        for tok in dict.fromkeys(query):
            found: dict[int, int] = {}
            if len(tok) == 2 and tok[0] == tok[1]:  # a doubled character's bigrams overlap: 汤汤汤 holds two
                doubled = re.compile(re.escape(tok[0]) + "{2,}")
                for d, t in enumerate(texts):
                    c = sum(len(run) - 1 for run in doubled.findall(t))
                    if c:
                        found[d] = c
            elif len(tok) in (1, 2):  # the tokens of a text are its characters and its bigrams, no other
                for d, t in enumerate(texts):
                    c = t.count(tok)
                    if c:
                        found[d] = c
            tf[tok] = found
        idf = {tok: math.log(1 + (n - len(found) + 0.5) / (len(found) + 0.5)) for tok, found in tf.items()}
        k1, b = K1, B
        scored = []
        for d in set().union(*tf.values()):
            norm = k1 * (1 - b + b * lengths[d] / avgdl)
            s = 0.0
            for q in query:
                c = tf[q].get(d, 0)
                if c:
                    s += idf[q] * c * (k1 + 1) / (c + norm)
            if s > 0:
                scored.append((d, s))
        scored.sort(key=lambda t: (-t[1], t[0]))
        return [(self.ids[d], s) for d, s in scored[:k]]

    def _dense_python(self, text: str, k: int) -> Ranked:
        e = self.embedder
        q = e.embed(text)
        scored = []
        for d in self.dense_places:
            s = cosine(q, e.embed(self.texts[d]))
            if s > DENSE_FLOOR:
                scored.append((d, s))
        scored.sort(key=lambda t: (-t[1], t[0]))
        return [(self.ids[d], s) for d, s in scored[:k]]


# ---------------------------------------------------------------- the self-test
# Texts made to try the edges — none of the characters read, one, a doubled one, the private use area, Hangul, the
# compatibility ideographs and the range's ends, characters beyond the plane, a lone surrogate, marks between
# characters, a long passage — and the queries asked of them.
_SELFTEST_TEXTS = [
    "", "。", "abc 123", "桂", "桂枝", "桂枝汤", "汤汤汤", "汤汤", "消渴消渴消渴消渴", "桂 枝,汤", " 缺字",
    "한글 桂枝", "豈更車賈滑串句龜", "㐀퟿﫿", "𠀀𠀁 桂枝 𪚥", "桂\ud800枝汤", "太阳病，头痛，发热，汗出，恶风，桂枝汤主之。",
    "阳浮而阴弱，阳浮者，热自发；阴弱者，汗自出。", "太陽病，頭痛，發熱", "麻黄汤主之，桂枝汤亦主之。" * 12,
    "渴而饮水，消渴，小便不利。", "伤寒，脉浮缓，身不疼，但重，乍有轻时。", "\x1e", "桂枝汤桂枝汤",
]
_SELFTEST_QUERIES = [
    (["桂枝", "枝汤"], "桂枝汤的主治"), (["汤汤"], "汤汤汤"), (["桂"], "桂"), (["消渴"] * 3, "消渴 三消"),
    ([""], ""), (["桂枝", "桂枝", "不存"], ""), (["豈更", "﫿"], "abc"),
    (["太阳", "阳病", "麻黄", "黄汤"], "太阳之为病，脉浮，头项强痛而恶寒"),
]


def _selftest(kern: Any) -> str:
    """'' when the kernel ranks the edge texts as the definitions do, every score bit for bit; else what differed."""
    ids = [f"t{i:02d}" for i in range(len(_SELFTEST_TEXTS))]
    places = list(range(len(ids)))[::-1]
    for embedder in (HashingEmbedder(), HashingEmbedder(dim=60, ngram=(2, 1, 4))):
        local = LocalIndexes(ids, list(_SELFTEST_TEXTS), places, embedder)
        for query, text in _SELFTEST_QUERIES:
            if _bits(local._bm25_kernel(kern, query, 100)) != _bits(local._bm25_python(query, 100)):
                return f"BM25 differed for {query}"
            if _bits(local._dense_kernel(kern, text, 100)) != _bits(local._dense_python(text, 100)):
                return f"the dense route differed for {text!r} (dim {embedder.dim})"
            if _bits(local._bm25_kernel(kern, query, 2)) != _bits(local._bm25_python(query, 2)):
                return f"BM25's first 2 differed for {query}"
    return ""
