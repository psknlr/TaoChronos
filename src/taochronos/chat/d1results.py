"""The precomputed results of the D1 backup (docs/adr/0017-d1-backup.md): the tools a Worker cannot compute in 10 ms,
run here by the Python runtime on the full corpus, for the keys a conversation asks most, and imported with the corpus
(``results`` in database 0: ``"<tool>\\t<key>"`` → the tool's result, gzip-compressed and base64-encoded).

The keys are enumerable and deterministic — the formulas and drugs the corpus writes most (by the full-text index),
the lexicon's curated terms, the historical terms, every book, the 要籍, the schools, the clauses of the classics the
commentators comment on — and a key is what the result depends on, as the Worker derives it from a call's arguments
(``cloud/site/src/backup/precomputed.js``, ``KEYS``: the canonical term the study layer resolves a name to, the
clause's normalised characters …).  Each result is the tool's own, through ``ChatRuntime.call`` with the tool's
default arguments (a clause: as its witness punctuates it); a call that fails is left out (the Worker then says it was
not precomputed).  Some tools order ties by string hashing, so the daily job runs with a fixed ``PYTHONHASHSEED``: a
result computed again is the same.

Computing is slow (a formula's history takes seconds): the import computes a key only when its batch is due, in key
order, and a run stops at its time budget; the next run resumes after the last key imported.  The daily job computes
them in worker processes side by side (``workers``), each with its own runtime over the same store, and imports them
in the same key order; should the workers stop (a process killed for its memory), the rest are computed here.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterator

# how many of each, by attestation in the corpus (the full-text index's document count of the name)
FORMULAS = 1200
HERBS = 600
NETWORK_FORMULAS = 600
PAIRS_HERBS = 300
CLAUSE_WORKS = ("shanghanlun", "jinkui")  # the classics whose clauses the commentators comment on most
CLAUSE_CHARS = (8, 240)  # a clause: at least 8 characters of text, at most 240
FINDINGS = ("symptom", "sign", "pulse", "tongue", "disease", "pattern")
TERM_CATEGORIES = ("disease", "pattern", "symptom", "sign", "pulse", "tongue", "pathogenesis", "etiology", "treatment_method",
                   "treatment_principle", "organ", "condition", "concept")
HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff〓□]")  # study/base.py, HAN
# what a worker needs at most: the full corpus's server runtime and its caches run in a 4 GiB container
# (cloud/corpus/wrangler.toml), the store's page cache included
WORKER_BYTES = 2 << 30


def pack(value: Any) -> str:
    """A result as ``results`` holds it: its JSON, gzip-compressed (the same bytes every time), in base64."""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")


def unpack(text: str) -> Any:
    return json.loads(gzip.decompress(base64.b64decode(text)).decode("utf-8"))


def clause_key(text: str, normalize: Callable[[str], str]) -> str:
    """A clause as the concordance reads it (concordance.run: han_only of the normalised text, at most 400)."""
    return "".join(ch for ch in normalize(text) if HAN.match(ch))[:400]


class Precompute:
    """The keys to precompute and their results, over a ChatRuntime on the full corpus (its store indexed)."""

    def __init__(self, runtime: Any, *, log: Callable[[str], None] = print,
                 only: list[tuple[str, str, dict[str, Any]]] | None = None, workers: int | None = None,
                 store: str | Path | None = None, home: str | Path | None = None) -> None:
        # ``runtime``: a ChatRuntime, or a function making one (called when the first key is needed: the daily run
        # indexes the store only once the import has come to the results)
        self._runtime = runtime
        self.log = log
        # ``workers``: the results computed by this many processes, each with its runtime over ``store`` (0: as many
        # as the processors and the memory allow); None: here, one at a time
        self.workers, self.store, self.home = workers, store, home
        # ``only``: these keys and no others (the test fixture)
        self._keys = sorted(only, key=lambda t: f"{t[0]}\t{t[1]}") if only is not None else None

    @property
    def rt(self) -> Any:
        if callable(self._runtime) and not hasattr(self._runtime, "call"):
            self._runtime = self._runtime()
        return self._runtime

    @property
    def h(self) -> Any:
        return self.rt.h

    # -------------------------------------------------------------- which keys
    def _counts(self, entries: list[Any]) -> dict[str, int]:
        corpus = self.h.corpus
        return {e.term_id: corpus.count(e.term) for e in entries}

    def _ranked(self, category: str, top: int) -> list[Any]:
        lex = self.h.pack.lexicon
        entries = [e for e in lex.entries.values() if e.category == category and len(e.term) >= 2]
        counts = self._counts(entries)
        entries.sort(key=lambda e: (-counts[e.term_id], e.term))
        return [e for e in entries[:top] if counts[e.term_id] > 0]

    def keys(self) -> list[tuple[str, str, dict[str, Any]]]:
        """(tool, key, arguments), sorted by "<tool>\\t<key>" — the order ``results`` is filled in."""
        if self._keys is not None:
            return self._keys
        h = self.h
        lex = h.pack.lexicon
        norm = h.pack.variants.normalize_text
        out: dict[tuple[str, str], dict[str, Any]] = {}

        def add(tool: str, key: str, args: dict[str, Any]) -> None:
            out.setdefault((tool, key), args)

        formulas = self._ranked("formula", FORMULAS)
        herbs = self._ranked("herb", HERBS)
        for e in formulas:
            add("study.formula", e.term, {"name": e.term})
        for e in formulas[:NETWORK_FORMULAS]:
            add("study.network", e.term, {"target": e.term})
        for e in herbs:
            add("study.herb", e.term, {"name": e.term})
        for e in herbs[:PAIRS_HERBS]:
            add("study.pairs", e.term, {"herb": e.term})
        add("study.pairs", "", {})
        add("study.network", "", {})
        curated = [e for e in lex.entries.values() if e.kind != "harvested"]
        terms = [e for e in curated if e.category in TERM_CATEGORIES and len(e.term) >= 2]
        for e in terms:
            add("study.term", e.term, {"term": e.term})
            add("study.reading", e.term, {"topic": e.term})
            add("kg.claims", e.term_id, {"terms": [e.term_id]})
            add("kg.neighbors", e.term_id, {"term": e.term_id})
            if e.category in FINDINGS:
                add("study.network", e.term, {"target": e.term})
        for t in h.pack.terminology.terms:
            add("study.term", t, {"term": t})
            add("study.senses", t, {"term": t})
        for e in curated:
            if (e.aliases or e.synonyms) and len(e.term) >= 2:
                add("study.names", e.term, {"term": e.term})
        corpus = h.corpus
        for bid in sorted(corpus.books):
            add("study.taboo", bid, {"book_id": bid})
        add("study.taboo", "", {})
        canon = h.capabilities.get("study")._canon.catalog()
        for w in canon:
            add("study.witnesses", w["work"], {"work": w["work"]})
            if w.get("title"):
                add("study.citations", w["title"], {"target": w["title"]})
        add("study.citations", "", {})
        schools = (h.capabilities.get("study").data("schools.yaml") or {}).get("schools") or {}
        for s in schools:
            add("study.schools", s, {"school": s})
        add("study.schools", "", {})
        for clause, text in self._clauses(canon, norm).items():
            add("study.commentaries", clause, {"text": text})
            add("study.concordance", clause, {"text": text})
        self._keys = [(tool, key, args) for (tool, key), args in sorted(out.items(), key=lambda kv: f"{kv[0][0]}\t{kv[0][1]}")]
        return self._keys

    def _clauses(self, canon: list[dict[str, Any]], norm: Callable[[str], str]) -> dict[str, str]:
        """The clauses of the classics' open witnesses (the canon's ``open_witness``): the concordance's key of each →
        the clause as the witness punctuates it, normalised.  The key is what the Worker finds a call's clause by,
        however it is punctuated; the result is computed for the punctuated clause, as a reader quotes it (the
        concordance's probes follow a query's punctuation: 太阳之为病，脉浮，… and its bare characters find different
        witnesses).  A key two passages share keeps the first, in the canon's order."""
        corpus = self.h.corpus
        keys: dict[str, str] = {}
        for w in canon:
            if w.get("work") not in CLAUSE_WORKS or not w.get("open_witness") or w["open_witness"] not in corpus.books:
                continue
            for p in corpus.passages(book_ids=[w["open_witness"]], kinds=["text"]):
                key = clause_key(p.text, norm)
                if CLAUSE_CHARS[0] <= len(key) <= CLAUSE_CHARS[1]:
                    keys.setdefault(key, norm(p.text))
        return dict(sorted(keys.items()))

    # -------------------------------------------------------------- results
    def value(self, tool: str, args: dict[str, Any]) -> Any | None:
        """The tool's result as the server returns it (the ``result`` of ``ChatRuntime.call``), or None if it failed."""
        return _value(self.rt, tool, args)

    def rows(self, after: str | None = None, *, deadline: Callable[[], bool] = lambda: False) -> Iterator[tuple[str, str, Any]]:
        """(tool, key, result) after ``after`` ("<tool>\\t<key>" of the last row imported), in key order (the importer
        packs them); stops when ``deadline()`` says so."""
        import time

        keys = self.keys()
        todo = [(n, tool, key, args) for n, (tool, key, args) in enumerate(keys) if after is None or f"{tool}\t{key}" > after]
        workers = workers_for(self.workers) if self.workers is not None and self.store is not None and len(todo) > 1 else 0
        if self.workers == 0 and workers == 1:  # one process beside this one is no faster than this one
            workers = 0
        if workers:
            self.log(f"  results: {len(todo):,} keys, computed by {workers} process{'es' if workers > 1 else ''} side by side")
        started, done = time.perf_counter(), 0
        for n, tool, key, value in (self._side_by_side(todo, workers, deadline) if workers else self._here(todo, deadline)):
            done += 1
            if done % 250 == 0:
                self.log(f"  results: {n + 1:,} of {len(keys):,} keys ({tool}), {time.perf_counter() - started:.0f} s this run")
            if value is None:
                self.log(f"  results: {tool} {key!r} failed; left out")
                continue
            yield tool, key, value

    def _here(self, todo: list[tuple[int, str, str, dict[str, Any]]], deadline: Callable[[], bool]) -> Iterator[tuple[int, str, str, Any]]:
        for n, tool, key, args in todo:
            if deadline():
                k = f"{tool}\t{key}"
                self.log(f"  results: the run's time is up before {k!r}")
                return
            yield n, tool, key, self.value(tool, args)

    def _side_by_side(self, todo: list[tuple[int, str, str, dict[str, Any]]], workers: int,
                      deadline: Callable[[], bool]) -> Iterator[tuple[int, str, str, Any]]:
        """The keys computed by ``workers`` processes and taken in order, a few keys ahead of the one awaited (a run its
        deadline stops wastes little).  Each process starts afresh (``spawn``: none of this one's SQLite connections
        carried over) once this one has made its runtime, which indexes the store: the workers only read it."""
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool

        self.rt  # noqa: B018 — made already unless the keys were given (``only``)
        pool = ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"), initializer=_start,
                                   initargs=(str(self.store), str(self.home) if self.home else None))
        waiting: deque = deque()  # the futures of todo[i], todo[i + 1] …
        i = 0
        try:
            while i < len(todo):
                while len(waiting) < 4 * workers and i + len(waiting) < len(todo):
                    _, tool, _, args = todo[i + len(waiting)]
                    waiting.append(pool.submit(_compute, tool, args))
                n, tool, key, _ = todo[i]
                if deadline():
                    k = f"{tool}\t{key}"
                    self.log(f"  results: the run's time is up before {k!r}")
                    return
                value = waiting.popleft().result()
                yield n, tool, key, value
                i += 1
        except BrokenProcessPool as exc:
            self.log(f"  results: the workers have stopped ({exc}): the rest are computed here")
            yield from self._here(todo[i:], deadline)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def digest(self) -> str:
        """The key list's identity: when it changes, the results are imported afresh."""
        import hashlib

        h = hashlib.sha256()
        for tool, key, args in self.keys():
            h.update(f"{tool}\t{key}\t{json.dumps(args, ensure_ascii=False, sort_keys=True)}\n".encode("utf-8"))
        return h.hexdigest()[:16]


def _value(rt: Any, tool: str, args: dict[str, Any]) -> Any | None:
    out = rt.call(tool, args, max_chars=400)
    return out.get("result") if out.get("ok") else None


_worker: Any = None  # a worker process's runtime


def _start(store: str, home: str | None) -> None:
    global _worker
    _worker = runtime_for(store, home, log=lambda m: None)


def _compute(tool: str, args: dict[str, Any]) -> Any | None:
    return _value(_worker, tool, args)


def workers_for(wanted: int) -> int:
    """``wanted`` processes, or (0) as many as this machine's processors and its free memory allow."""
    if wanted > 0:
        return wanted
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            free = next(int(line.split()[1]) * 1024 for line in f if line.startswith("MemAvailable:"))
    except (OSError, StopIteration, ValueError):
        return cpus
    return max(1, min(cpus, free // WORKER_BYTES))


def runtime_for(store: str | Path, home: str | Path | None = None, *, log: Callable[[str], None] = print) -> Any:
    """The Python runtime over the full corpus whose store is ``store`` (<data>/corpus/tcm.sqlite): its full-text
    index built first if the store travelled without it (``taochronos web store``), with this checkout's normaliser."""
    import time

    from ..config import find_home
    from ..plugins.classics.domain import DomainPack
    from ..plugins.classics.webcorpus import index_state, index_store
    from . import ChatRuntime

    path = Path(store).resolve()
    if index_state(path)["state"] != "built":
        started = time.perf_counter()
        normalize = DomainPack(find_home(str(home) if home else None) / "domains" / "classics").variants.normalize_text
        index_store(path, normalize, chunk=20000)
        log(f"  results: the store indexed for the Python runtime ({time.perf_counter() - started:.0f} s)")
    return ChatRuntime.create("full-corpus", home=home, data_dir=path.parent.parent, kind="server", ephemeral=True)


__all__ = ["Precompute", "clause_key", "pack", "runtime_for", "unpack", "workers_for"]
