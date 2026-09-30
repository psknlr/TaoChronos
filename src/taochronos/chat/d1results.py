"""The precomputed results of the D1 backup (docs/adr/0017-d1-backup.md): the tools a Worker cannot compute in 10 ms,
run here by the Python runtime on the full corpus, for the keys a conversation asks most, and imported with the corpus
(``results`` in database 0: ``"<tool>\\t<key>"`` → the tool's result, gzip-compressed and base64-encoded).

The keys are enumerable and deterministic — the formulas and drugs the corpus writes most (by the full-text index),
the lexicon's curated terms, the historical terms, every book, the 要籍, the schools, the clauses of the classics the
commentators comment on — and a key is what the result depends on, as the Worker derives it from a call's arguments
(``cloud/site/src/backup/precomputed.js``, ``KEYS``: the canonical term the study layer resolves a name to, the
clause's normalised characters …).  Each result is the tool's own, through ``ChatRuntime.call`` with the tool's
default arguments; a call that fails is left out (the Worker then says it was not precomputed).

Computing is slow (a formula's history takes seconds): the import computes a key only when its batch is due, in key
order, and a run stops at its time budget; the next run resumes after the last key imported.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
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
                 only: list[tuple[str, str, dict[str, Any]]] | None = None) -> None:
        self.rt = runtime
        self.h = runtime.h
        self.log = log
        # ``only``: these keys and no others (the test fixture)
        self._keys = sorted(only, key=lambda t: f"{t[0]}\t{t[1]}") if only is not None else None

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
        for clause in self._clauses(canon, norm):
            add("study.commentaries", clause, {"text": clause})
            add("study.concordance", clause, {"text": clause})
        self._keys = [(tool, key, args) for (tool, key), args in sorted(out.items(), key=lambda kv: f"{kv[0][0]}\t{kv[0][1]}")]
        return self._keys

    def _clauses(self, canon: list[dict[str, Any]], norm: Callable[[str], str]) -> list[str]:
        """The clauses of the classics' open witnesses (the canon's ``open_witness``), as the concordance keys them."""
        corpus = self.h.corpus
        keys: list[str] = []
        for w in canon:
            if w.get("work") not in CLAUSE_WORKS or not w.get("open_witness") or w["open_witness"] not in corpus.books:
                continue
            for p in corpus.passages(book_ids=[w["open_witness"]], kinds=["text"]):
                key = clause_key(p.text, norm)
                if CLAUSE_CHARS[0] <= len(key) <= CLAUSE_CHARS[1]:
                    keys.append(key)
        return sorted(set(keys))

    # -------------------------------------------------------------- results
    def value(self, tool: str, args: dict[str, Any]) -> Any | None:
        """The tool's result as the server returns it (the ``result`` of ``ChatRuntime.call``), or None if it failed."""
        out = self.rt.call(tool, args, max_chars=400)
        return out.get("result") if out.get("ok") else None

    def rows(self, after: str | None = None, *, deadline: Callable[[], bool] = lambda: False) -> Iterator[tuple[str, str, Any]]:
        """(tool, key, packed result) after ``after`` ("<tool>\\t<key>" of the last row imported), computed one at a time;
        stops when ``deadline()`` says so."""
        for tool, key, args in self.keys():
            k = f"{tool}\t{key}"
            if after is not None and k <= after:
                continue
            if deadline():
                self.log(f"  results: the run's time is up before {k!r}")
                return
            value = self.value(tool, args)
            if value is None:
                self.log(f"  results: {tool} {key!r} failed; left out")
                continue
            yield tool, key, value

    def digest(self) -> str:
        """The key list's identity: when it changes, the results are imported afresh."""
        import hashlib

        h = hashlib.sha256()
        for tool, key, args in self.keys():
            h.update(f"{tool}\t{key}\t{json.dumps(args, ensure_ascii=False, sort_keys=True)}\n".encode("utf-8"))
        return h.hexdigest()[:16]


def runtime_for(store: str | Path, home: str | Path | None = None) -> Any:
    """The Python runtime over the full corpus whose (indexed) store is ``store`` (<data>/corpus/tcm.sqlite)."""
    from . import ChatRuntime

    data = Path(store).resolve().parent.parent
    return ChatRuntime.create("full-corpus", home=home, data_dir=data, kind="server", ephemeral=True)


__all__ = ["Precompute", "clause_key", "pack", "runtime_for", "unpack"]
