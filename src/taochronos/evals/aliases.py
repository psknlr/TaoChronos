"""AliasEval (别名, spec §3.10, ADR 0023): is a drug found under its other names without losing the name asked, without
merging two drugs that share a name and without reaching outside the period a name was in use?

* **synthetic** — always runs (well under 2 s): a corpus and an alias layer written for the eval, planted with the hard
  cases — 将军 beside 大将军 and 将军之官, 通草 before and after 960, a name two drugs share (鬼督邮), 蜜甘 inside 石蜜甘,
  黄连 inside 胡黄连, the weak 葛 inside 干葛, 山药 before its first use in 1063, and passages on 虚劳 that outrank the
  asked name in a question about both — checks the reserved places and the asked name's retention, that nothing is
  merged, the gates, the readings, the flags, that nothing leaks out of the question's window and that ``off`` is
  today's search; and scores its nine items like the gold below.
* **store** (skipped with ``--quick`` and without a corpus store) — each profile of ``$TAOCHRONOS_ALIAS_EVAL``
  (default ``web-canon,full-corpus``) on the store under ``--data``, the 别名录 (jc_c030) left out of the corpus, and again
  without bencao_gangmu_*: the items of ``evals/gold/aliases.yaml`` searched by each system — ``off`` (B0, today's
  search), ``naive`` (B1, :class:`Naive`), ``on`` (B2), ``analysis`` (the layer's reading of the question alone) and
  the ablations (gates, boundary, slots, period, asked_first all and off) — at k = 10 and k = 50, per split (dev,
  heldout, all) and item type; and the resolution rows.  The gold is checked on the store first: its witnesses, and on
  the web store it was drawn from, its pools.  Each profile extracts its claims into a cache of its own
  (:meth:`EvalContext.profile_harness`), so that no run reads another profile's claims or writes into the store.

Labels come only from each item's own patterns (:class:`Labeller`): this module never imports or calls the layer's
gates, which a test checks.  Held-out items are reported in aggregate only — ``details`` lists dev items, and a note
on the gold's problems gives an example only on a dev item — and not at all while the gold fails its checks, on file
(its split pin among them) or on the store.  Restrict a run with ``TAOCHRONOS_ALIAS_EVAL_SPLITS``
(dev, heldout), ``TAOCHRONOS_ALIAS_EVAL_SYSTEMS`` and ``TAOCHRONOS_ALIAS_EVAL_VIEWS`` (main, no-gangmu), each a
comma-separated list.

Uncertainty (:func:`intervals`): a paired bootstrap over items — seeded (:data:`SEED`), so that a run is reproduced
exactly; ``$TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP`` resamples (default :data:`RESAMPLES`, 0 for none) — gives 95 % intervals
for on − off, on − naive and each layer comparison below, for P@10, nDCG@10, Wrong@10 and the mean AskedRet@10, per
split of the main view (and on the synthetic items), in the metrics and as aggregates only.
``TAOCHRONOS_ALIAS_EVAL_BASELINE`` (a directory holding an alias layer's ``aliases.jsonl`` and ``context.json``, or the
``aliases.jsonl`` itself) searches the same items with that layer too, the profile's pack otherwise unchanged
(:func:`layer_pack`): as ``on@baseline`` (``$TAOCHRONOS_ALIAS_EVAL_BASELINE_SYSTEMS``, default ``on``, picks which
systems), so that a change of the layer reads as on(new) − on(old), with its interval.
"""

from __future__ import annotations

import copy
import json
import math
import operator
import os
import random
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .base import EvalContext, SuiteResult, _r

PROFILES = ("web-canon", "full-corpus")
SPLITS = ("dev", "heldout")
VIEWS = ("main", "no-gangmu")  # jc_c030 left out; bencao_gangmu_* left out too
GANGMU = "bencao_gangmu_"
# how each system searches: today's search, the naive baseline, the layer, and the layer with one part taken away
SYSTEMS: dict[str, dict[str, Any] | None] = {
    "off": {"aliases": "off"},
    "naive": None,
    "on": {"aliases": "on"},
    # the layer's reading of the question (names asked as written, gated-out hits last), no expansion or side queue
    "analysis": {"aliases": "on", "alias_params": {"expansions": 0, "asked_first": "off"}},
    "gates": {"aliases": "on", "alias_params": {"ablate": ["gates"]}},
    "boundary": {"aliases": "on", "alias_params": {"ablate": ["boundary"]}},
    "slots": {"aliases": "on", "alias_params": {"ablate": ["slots"]}},
    "period": {"aliases": "on", "alias_params": {"ablate": ["period"]}},
    "asked_first:all": {"aliases": "on", "alias_params": {"asked_first": "all"}},
    "asked_first:off": {"aliases": "on", "alias_params": {"asked_first": "off"}},
}
CAP = 50  # store counts are read up to here: the metrics need min(10, ·) and min(50, ·)
TYPES = ("alias", "head", "ambiguous", "period", "trap", "substring")
MASK = "|"
BASELINE = "@baseline"  # a system searched with the baseline layer (``on@baseline``)
RESAMPLES = 2000  # bootstrap resamples over items (``$TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP``)
SEED = 20261018  # the bootstrap's seed: every run draws the same resamples
LEVEL = 0.95
# the metrics given intervals, each computed on a resample as :func:`aggregate` does: a mean over the items that have
# it, or the total
BOOT_METRICS = (("P@10", "mean"), ("nDCG@10", "mean"), ("Wrong@10", "sum"), ("AskedRet@10", "mean"))


# ------------------------------------------------------------------ labels
def _mask(text: str, strings: Iterable[str]) -> str:
    for s in strings:
        text = text.replace(s, MASK * len(s))
    return text


def _inside(valid: Any, yr: tuple[int, int] | None) -> bool:
    """Whether a passage's range lies inside a referent's ``valid`` [from, to); an undated one only when it has none."""
    if valid is None:
        return True
    if yr is None:
        return False
    lo, hi = valid
    return (lo is None or yr[0] >= lo) and (hi is None or yr[1] < hi)


def _meets(valid: Any, after: float | None, before: float | None) -> bool:
    """Whether a window [from, to) meets the question's [after, before)."""
    if valid is None:
        return True
    lo, hi = valid
    return (after is None or hi is None or after < hi) and (before is None or lo is None or lo < before)


class Labeller:
    """The labels of one item (§3.10), from its own patterns, on a passage's normalised text with every false friend
    masked: ``asked`` — the asked form occurs (and one of ``asked_cues`` anywhere in the passage, when the item has
    cues); ``other`` — a referent name other than the asked form occurs, the passage's range inside that referent's
    ``valid``; ``wrong`` — neither, and a ``wrong`` name occurs, or the asked form only inside a masked string, or in a
    passage without a cue.  A name that is part of the asked form is read outside the asked form's occurrences (木香 in
    青木香 is no 木香)."""

    def __init__(self, item: dict[str, Any]) -> None:
        self.asked = item["asked"]
        self.cues = list(item.get("asked_cues") or [])
        self.masks = sorted(set(item.get("false_friends") or []), key=len, reverse=True)
        self.names = [(n, ref.get("valid")) for ref in item["referents"] for n in ref.get("names") or []
                      if n != self.asked]
        self.wrong = list(item.get("wrong") or [])

    def _apart(self, text: str, name: str) -> str:
        return _mask(text, [self.asked]) if name in self.asked else text

    def __call__(self, text: str, yr: tuple[int, int] | None) -> tuple[bool, bool, bool]:
        masked = _mask(text, self.masks)
        present = self.asked in masked
        asked = present and (not self.cues or any(c in masked for c in self.cues))
        other = any(n in self._apart(masked, n) and _inside(valid, yr) for n, valid in self.names)
        if asked or other:
            return asked, other, False
        wrong = (present  # the asked form without a cue
                 or (self.asked in text and not present)  # only inside a masked string
                 or any(w in self._apart(masked, w) for w in self.wrong))
        return False, False, wrong


class _Texts:
    """Normalised texts and date ranges of a corpus's passages, cached for the labels."""

    def __init__(self, corpus: Any) -> None:
        self.corpus = corpus
        self.normalize: Callable[[str], str] = corpus.normalize
        self._text: dict[str, tuple[str, tuple[int, int] | None]] = {}

    def __call__(self, pid: str, passage: Any = None) -> tuple[str, tuple[int, int] | None]:
        got = self._text.get(pid)
        if got is None:
            p = passage if passage is not None else self.corpus.passage(pid)
            rng = self.corpus.year_range(p)
            got = (self.normalize(p.text), None if rng is None else (rng.start, rng.end))
            if len(self._text) > 60_000:
                self._text.clear()
            self._text[pid] = got
        return got


def store_counts(item: dict[str, Any], label: Labeller, texts: _Texts, after: float | None,
                 before: float | None) -> dict[str, int]:
    """Passages of the corpus inside the question's window that are relevant (``rel``), write the asked form
    (``asked``) and write another name of a referent only (``other``), each counted up to :data:`CAP`.  A relevant
    passage writes the asked form or a name, so the candidates are those holding one of them."""
    corpus = texts.corpus
    n = {"rel": 0, "asked": 0, "other": 0}
    seen: set[str] = set()
    names = [nm for ref in item["referents"] for nm in ref.get("names") or [] if nm != item["asked"]]
    for surfaces, enough in (([item["asked"]], "asked"), (names, "other")):
        ids: list[str] = []
        for s in dict.fromkeys(surfaces):
            ids += corpus.contains(s, after=after, before=before, verify=False)
        ids = [pid for pid in dict.fromkeys(ids) if pid not in seen]
        for i in range(0, len(ids), 200):
            if n[enough] >= CAP:
                break
            for p in corpus.passages_by_id(ids[i: i + 200]):
                seen.add(p.id)
                a, o, _ = label(*texts(p.id, p))
                n["asked"] += a
                n["other"] += o and not a
                n["rel"] += a or o
    return {key: min(v, CAP) for key, v in n.items()}


# ------------------------------------------------------------------ the naive baseline
class Naive:
    """B1, the naive baseline: today's search (``aliases="off"``) with the layer's own one-hop pairs added to the
    question as lexicon surfaces — the layer's names the question writes, as written; the heads of the drugs each is an
    open or cue name of, with their spellings (alias→drug); the open and cue names of the drugs each, or a lexicon herb
    of the question, heads (drug→alias; an alias's own drugs left out, as the layer leaves them) — ``expansions`` of
    them at most (alias→drug first, then most passages first), with no gates, no windows and no reserved places: what
    putting the layer's pairs into the lexicon as synonyms would do.  It reads the layer's records only, never its
    gates."""

    def __init__(self, retriever: Any) -> None:
        self.base = retriever.analyzer
        self.retriever = copy.copy(retriever)
        self.retriever.analyzer = self
        pack = retriever.pack
        self.normalize = pack.variants.normalize_text
        self.lex = pack.lexicon
        self.records = dict(getattr(pack.aliases, "records", {}) or {})
        self.max_len = max(map(len, self.records), default=0)
        self.cap = int(retriever.alias.get("expansions", 8))
        self.heads: dict[str, set[str]] = defaultdict(set)  # name → the drugs (groups) it heads
        self.terms: dict[str, set[str]] = defaultdict(set)  # lexicon term id → its drugs
        self.own: dict[str, set[str]] = defaultdict(set)  # name → the drugs it is another name of (spellings aside)
        # name → the heads of the drugs it is an open or cue name of → their group
        self.drugs: dict[str, dict[str, str]] = defaultdict(dict)
        self.names: dict[str, dict[str, int]] = defaultdict(dict)  # drug → its open and cue names → passages
        self.spellings: dict[str, set[str]] = defaultdict(set)  # drug → its open and cue spellings
        for s, rec in self.records.items():
            if rec.ho is not None:
                self.heads[s].add(rec.ho)
            for ref in rec.r:
                self.heads[ref.h].add(ref.g)
                if ref.t:
                    self.terms[ref.t].add(ref.g)
                if rec.stop:
                    continue
                if ref.k != "spelling":
                    self.own[s].add(ref.g)
                if ref.st in ("open", "cue"):
                    self.drugs[s][ref.h] = ref.g
                    self.names[ref.g][s] = rec.n
                    if ref.k == "spelling":
                        self.spellings[ref.g].add(s)

    def __getattr__(self, name: str) -> Any:  # the rest of the analyzer's interface is today's
        if name == "base":
            raise AttributeError(name)
        return getattr(self.base, name)

    def written(self, norm: str) -> list[str]:
        """The layer's names the question writes, longest first, left to right (stop names left out)."""
        out: list[str] = []
        i = 0
        while i < len(norm):
            for size in range(min(self.max_len, len(norm) - i), 1, -1):
                rec = self.records.get(norm[i:i + size])
                if rec is not None and not rec.stop and (rec.r or rec.ho is not None or rec.fl is not None):
                    out.append(rec.s)
                    i += size
                    break
            else:
                i += 1
        return list(dict.fromkeys(out))

    def pairs(self, norm: str, terms: Iterable[str]) -> dict[str, tuple[int, int]]:
        """The names one hop from what the question asks → (direction, −passages): 0 alias→drug, 1 drug→alias."""
        found: dict[str, tuple[int, int]] = {}

        def add(name: str, direction: int) -> None:
            rec = self.records.get(name)
            if len(name) >= 2 and (rec is None or not rec.stop):
                key = (direction, -(rec.n if rec is not None else 0))
                found[name] = min(found.get(name, key), key)

        groups: set[str] = set()
        for s in self.written(norm):
            for head, g in self.drugs.get(s, {}).items():
                for name in [head, *sorted(self.spellings.get(g, ()))]:
                    add(name, 0)
            groups |= self.heads.get(s, set())
        terms = set(terms)
        for m in self.lex.match(norm):
            entry = self.lex.entry(m.term_id) if m.term_id in terms else None
            if entry is not None and entry.category == "herb":
                drugs = set(self.terms.get(entry.term_id, ()))
                for f in entry.surfaces():
                    drugs |= self.heads.get(self.normalize(f), set())
                groups |= drugs - self.own.get(m.surface, set())
        for g in sorted(groups):
            for name in self.names.get(g, {}):
                add(name, 1)
        return found

    def analyze(self, text: str, *, after: int | None = None, before: int | None = None, aliases: bool = False,
                cfg: dict[str, Any] | None = None) -> Any:
        q = self.base.analyze(text, after=after, before=before)
        norm = self.normalize(text)
        written = self.written(norm)
        have = set(q.all_surfaces())
        found = {s: key for s, key in self.pairs(norm, q.terms).items() if s not in have and s not in written}
        extra = [s for s in written if s not in have] + sorted(found, key=lambda s: (found[s], s))[:self.cap]
        if extra:
            q.surfaces["naive:aliases"] = extra
            for s in extra:
                spellings = self.base.variant_spellings(s)
                if spellings:
                    q.variants[s] = spellings
        return q

    def search(self, text: str, *, k: int) -> tuple[Any, list[Any]]:
        return self.retriever.search(text, k=k, aliases="off")


def _base(system: str) -> str:
    """The system a name stands for: ``on@baseline`` searches as ``on`` does, with the baseline layer."""
    return system.split("@", 1)[0]


def searcher(system: str, retriever: Any, naive: Naive | None = None) -> Callable[[str, int], tuple[Any, list[Any]]]:
    spec = SYSTEMS[_base(system)]
    if spec is None:
        base = naive or Naive(retriever)
        return lambda text, k: base.search(text, k=k)
    return lambda text, k: retriever.search(text, k=k, aliases=spec["aliases"], alias_params=spec.get("alias_params"))


# ------------------------------------------------------------------ scoring
def same_drug(items: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    """The gold's same-drug names: each referent head → the names its items give it; a name two heads are given is
    left out, since it tells neither apart (鬼督邮)."""
    same: dict[str, set[str]] = defaultdict(set)
    for item in items:
        for ref in item["referents"]:
            same[ref["head"]] |= set(ref.get("names") or []) - {ref["head"]}
    owners: dict[str, set[str]] = defaultdict(set)
    for head, names in same.items():
        for name in names:
            owners[name].add(head)
    return {head: {n for n in names if len(owners[n]) == 1} for head, names in same.items()}


def _alike(a: str, b: str, same: dict[str, set[str]]) -> bool:
    """Whether two heads name one drug by the gold: equal, or one among the other's same-drug names."""
    return a == b or a in same.get(b, ()) or b in same.get(a, ())


def _drug(item: dict[str, Any], head: str, names: Iterable[str] = (), same: dict[str, set[str]] | None = None) -> str:
    """The item's referent a listed drug stands for — its head is the referent's head or one of the item's names for
    it (every referent tried so first, so that a drug the gold names is never taken for another through shared
    forms: 玄石 stays 玄石 under 处石 whose forms hold 磁石), else the referent's head or one of those names is among the
    drug's own names (an expansion's surfaces, the asked drug's forms); else the one referent the gold's same-drug
    names make it (never for the asked form, which may name several) — else the drug's head."""
    names = set(names)
    for ref in item["referents"]:
        if head == ref["head"] or head in (ref.get("names") or ()):
            return ref["head"]
    for ref in item["referents"]:
        if ref["head"] in names or set(ref.get("names") or ()) & names:
            return ref["head"]
    if same and head != item["asked"]:
        alike = {ref["head"] for ref in item["referents"] if _alike(head, ref["head"], same)}
        if len(alike) == 1:
            return alike.pop()
    return head


def _for(rows: list[dict[str, Any]], key: str, asked: str) -> list[dict[str, Any]]:
    """The rows of a ``query.aliases`` list for the asked form: written as asked, else read inside it or around it
    (慎火 for 慎火草)."""
    return [a for a in rows if a.get(key) == asked] or [a for a in rows if a.get(key) and (
        a[key] in asked or asked in a[key])]


def asked_forms(pack: Any, q: Any, asked: str) -> set[str]:
    """The asked form and the forms of the lexicon herb entry the question reads it as (紫葳 → 紫葳, 凌霄花, 陵苕 …),
    normalised: the names today's search already treats as the asked drug's own.  The entry is the asked form's, else
    that of a name the question reads inside it or around it (慎火 for 慎火草)."""
    terms = getattr(q, "asked", None) or {}
    names = [s for s in terms if s == asked and terms[s]] or [s for s in terms if terms[s] and (
        s in asked or asked in s)]
    normalize = pack.variants.normalize_text
    out = {asked}
    for s in names:
        entry = pack.lexicon.entry(terms[s])
        if entry is not None and entry.category == "herb":
            out |= {normalize(f) for f in entry.surfaces()}
    return out


def _stop(entry: dict[str, Any]) -> bool:
    """Whether a ``query.aliases`` entry lists a stop name asked on its own: its drugs, each of status ``stop``, are
    candidates shown beside a note that the name is mostly an ordinary word — never a reading of the name."""
    refs = entry.get("referents") or []
    return bool(refs) and all(r.get("status") == "stop" for r in refs)


def listed(item: dict[str, Any], q: Any, same: dict[str, set[str]] | None = None,
           forms: Iterable[str] = ()) -> list[str]:
    """The drugs ``query.aliases`` names for the asked form, as the item's referents (:func:`_drug`): the referents it
    lists whose window meets the question's — a stop name's drugs (status ``stop``) among them, which it lists as
    candidates when the name is asked on its own (解离 → 防己), except for an item that expects none: the gold reads
    that name as no drug, and a stop's listing, beside its note, agrees — and the drugs its drug→alias expansions show
    by their names (丹砂, whose names include 朱砂).  A listed drug that is the asked drug itself — the asked form or one
    of ``forms``, the forms of the lexicon entry the question reads it as (:func:`asked_forms`) — and is none of the
    item's drugs by its head is mapped with those names too (紫葳, whose entry holds 凌霄花, names 凌霄花); forms the
    item calls wrong are none of them, and forms that meet two referents tell neither apart (as a same-drug name two
    heads share).  The asked form itself counts only where the item expects it as a drug of its own (苦菜 beside 贝母):
    elsewhere it is the lexicon's entry for the name asked (胡王使者) or the drug a head names (铜绿 → 铜青), no
    candidate."""
    view = getattr(q, "alias_view", None) or {}
    asked = item["asked"]
    wanted = item.get("expect_candidates") or []
    own = (set(forms) - set(item.get("wrong") or ())) | {asked}
    if sum(1 for ref in item["referents"] if ({ref["head"]} | set(ref.get("names") or ())) & own) > 1:
        own = {asked}

    def drug(head: str, names: Iterable[str] = ()) -> str:
        return _drug(item, head, set(names) | (own if head in own else set()), same)

    out = [drug(r["head"]) for a in _for(view.get("asked") or [], "surface", asked)
           for r in a.get("referents") or [] if _meets(r.get("valid"), q.after, q.before)
           and (wanted or r.get("status") != "stop")]
    members: dict[str, set[str]] = defaultdict(set)
    for e in _for(view.get("expansions") or [], "for", asked):
        if e.get("direction") == "drug→alias":
            members[e["referent"]].add(e["surface"])
    out += [drug(head, names) for head, names in members.items()]
    return [d for d in dict.fromkeys(out) if d != asked or asked in wanted]


def _leaks(hits: list[Any], after: float | None, before: float | None) -> int:
    """Passages among the hits whose midpoint year lies outside the question's window (an undated one too)."""
    if after is None and before is None:
        return 0
    return len({h.passage_id for h in hits if h.year is None or (after is not None and h.year < after)
                or (before is not None and h.year >= before)})


def score(item: dict[str, Any], label: Labeller, texts: _Texts, counts: dict[str, int], q: Any,
          hits10: list[Any], hits50: list[Any], ms: float, *, layered: bool = True,
          same: dict[str, set[str]] | None = None, forms: Iterable[str] = ()) -> dict[str, Any]:
    """One item under one system: the §3.10 metrics of its k = 10 and k = 50 answers.  AskedRet@10 and XR@50 are not
    capped at 1, so that a count of the store that falls short shows.  Candidates and merging are None for a system
    without the layer (``layered``), which lists nothing; an ambiguous item is merged when fewer than two of its
    expected drugs (all, when it expects one) are listed (``forms``: the asked drug's own, :func:`listed`)."""
    labs10 = [label(*texts(h.passage_id)) for h in hits10]
    labs50 = [label(*texts(h.passage_id)) for h in hits50]
    rel = [a or o for a, o, _ in labs10]
    n_rel, n_asked, n_other = counts["rel"], counts["asked"], counts["other"]
    idcg = sum(1 / math.log2(i + 2) for i in range(min(10, n_rel)))
    on50 = sum(1 for a, o, _ in labs50 if o and not a)
    row: dict[str, Any] = {
        "P@10": sum(rel) / len(rel) if rel else (0.0 if n_rel else None),
        "nDCG@10": sum(g / math.log2(i + 2) for i, g in enumerate(rel)) / idcg if idcg else None,
        "AskedRet@10": sum(a for a, _, _ in labs10) / min(10, n_asked) if n_asked else None,
        "ON@10": sum(1 for a, o, _ in labs10 if o and not a),
        "ON@50": on50,
        "XR@50": on50 / min(50, n_other) if n_other else None,
        "Wrong@10": sum(w for _, _, w in labs10),
        "leak": _leaks(hits10 + hits50, q.after, q.before),
        "ms": ms, "type": item["type"], "n_asked": n_asked,
        "labels": "".join("a" if a else "o" if o else "w" if w else "." for a, o, w in labs10),
    }
    have = set(listed(item, q, same, forms)) if layered else set()
    expected = set(item.get("expect_candidates") or [])
    row["listed"] = sorted(have)
    row["cand"] = (len(have & expected), len(have), len(expected)) if layered else None
    row["merge"] = (len(have & expected) < min(2, len(expected))
                    if layered and item["type"] == "ambiguous" else None)
    floor = item.get("floor")
    row["flag"] = None
    if floor:
        tp = fp = fn = 0
        for h in hits10:
            text, yr = texts(h.passage_id)
            want = floor["surface"] in text and yr is not None and yr[1] < floor["year"]
            got = any(f.startswith(f"anachronism:{floor['surface']}<") for f in h.flags)
            tp, fp, fn = tp + (want and got), fp + (got and not want), fn + (want and not got)
        row["flag"] = (tp, fp, fn)
    return row


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[max(0, math.ceil(q * len(s)) - 1)], 1)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Item rows → the metrics of §3.10: means of P@10, nDCG@10, AskedRet@10 and XR@50 over the items that have them;
    the least AskedRet@10 of the items with N_asked ≥ 7, traps left out; totals of ON@10, ON@50, Wrong@10 and leaks;
    candidates and flags pooled over the items (None where no row has them: a system without the layer lists no
    candidates); latency of the k = 10 calls."""

    def mean(key: str) -> float | None:
        vals = [r[key] for r in rows if r[key] is not None]
        return _r(sum(vals) / len(vals)) if vals else None

    kept = [r["AskedRet@10"] for r in rows
            if r["type"] != "trap" and r["n_asked"] >= 7 and r["AskedRet@10"] is not None]
    cands = [r["cand"] for r in rows if r["cand"] is not None]
    tp, have, want = (sum(c[i] for c in cands) for i in range(3))
    merges = [r["merge"] for r in rows if r["merge"] is not None]
    flags = [r["flag"] for r in rows if r["flag"] is not None]
    ftp, ffp, ffn = (sum(f[i] for f in flags) for i in range(3))
    ms = [r["ms"] for r in rows]
    return {
        "items": len(rows), "P@10": mean("P@10"), "nDCG@10": mean("nDCG@10"), "AskedRet@10": mean("AskedRet@10"),
        "AskedRet@10_min": _r(min(kept)) if kept else None,
        "ON@10": sum(r["ON@10"] for r in rows), "ON@50": sum(r["ON@50"] for r in rows), "XR@50": mean("XR@50"),
        "Wrong@10": sum(r["Wrong@10"] for r in rows),
        "CandRecall": _r(tp / want) if want else None, "CandPrecision": _r(tp / have) if have else None,
        "SilentMerge": sum(merges) if merges else None,
        "FlagP": _r(ftp / (ftp + ffp)) if ftp + ffp else None, "FlagR": _r(ftp / (ftp + ffn)) if ftp + ffn else None,
        "Leakage": sum(r["leak"] for r in rows), "p50_ms": _pct(ms, 0.5), "p95_ms": _pct(ms, 0.95),
    }


def table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The metrics of the rows, and of each item type among them."""
    by = {t: [r for r in rows if r["type"] == t] for t in TYPES}
    return {"all": aggregate(rows), "by_type": {t: aggregate(rs) for t, rs in by.items() if rs}}


def layered(system: str) -> bool:
    """Whether a system searches with the alias layer (and so lists candidates)."""
    spec = SYSTEMS[_base(system)]
    return spec is not None and spec["aliases"] == "on"


def run_items(items: list[dict[str, Any]], retriever: Any, corpus: Any, systems: list[str],
              texts: _Texts | None = None, same: dict[str, set[str]] | None = None,
              others: dict[str, Any] | None = None) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Every item searched by every system (k = 10, then 50).  Latency is the k = 10 call, timed only after every
    system has searched the item once untimed: a first call fills caches the others then read (the claims of the
    item's passages, extracted into the harness's own cache), so that timing first calls would charge that cost to
    whichever system ran first on the item.  The systems' order still turns with the item.  ``same``: the gold's
    same-drug names (:func:`same_drug`, by default the items' own).  ``others``: a retriever for a system to search
    with in place of ``retriever`` (``on@baseline`` with the baseline layer, :func:`layer_retriever`), in the same
    rotation, on the same counts.  Returns the rows per system and, per item, its counts."""
    texts = texts or _Texts(corpus)
    same = same_drug(items) if same is None else same
    others = others or {}
    naive = Naive(retriever) if "naive" in systems else None
    run = {s: searcher(s, others[s]) if s in others else searcher(s, retriever, naive) for s in systems}
    rows: dict[str, list[dict[str, Any]]] = {s: [] for s in systems}
    info = []
    for idx, item in enumerate(items):
        label = Labeller(item)
        q0 = retriever.analyzer.analyze(item["query"])
        counts = store_counts(item, label, texts, q0.after, q0.before)
        info.append({"id": item["id"], "window": [q0.after, q0.before], "n": counts})
        turn = idx % len(systems)
        order = systems[turn:] + systems[:turn]
        for system in order:  # untimed: warms what any system's first call on the item fills
            run[system](item["query"], 10)
        for system in order:
            started = time.perf_counter()
            q, hits10 = run[system](item["query"], 10)
            ms = (time.perf_counter() - started) * 1000
            _, hits50 = run[system](item["query"], 50)
            forms = asked_forms(others.get(system, retriever).pack, q, item["asked"]) if layered(system) else set()
            rows[system].append(score(item, label, texts, counts, q, hits10, hits50, ms, layered=layered(system),
                                      same=same, forms=forms))
    for system in systems:
        for row, item in zip(rows[system], items):
            row["id"], row["split"] = item["id"], item.get("split")
    return rows, info


# ------------------------------------------------------------------ resolution rows
def resolve(row: dict[str, Any], q: Any, same: dict[str, set[str]], pack: Any) -> tuple[str, list[str], bool]:
    """What the system does with a surface asked alone, from what it answers (``query.aliases``, the expansions and
    the lexicon's reading of the names asked): ``candidate`` — it lists several drugs (ambiguous), or only doubtful
    ones; ``expand`` — it reads the name as another drug (an alias→drug expansion, a referent listed, or a lexicon herb
    headed by another name); ``none`` — neither (a head reaching only its own other names); the heads it gives; and
    whether that is the row's expectation, heads matched through the gold's same-drug names.  An ``expand`` row is also
    met when the expected head is among the names the system searches as the asked drug's own (铜青, whose group holds
    铜绿; 薯蓣, which the lexicon files under 山药).  A stop name's listing (:func:`_stop`) is no reading of the name:
    the candidates it shows beside its note leave the action as the rest of the answer makes it."""
    view = getattr(q, "alias_view", None) or {}
    entries = [a for a in view.get("asked") or [] if not _stop(a)]
    refs = [r for a in entries for r in a.get("referents") or []]
    exps = [e for e in q.expansions if e.why != "period"]
    reach = [e.head for e in exps if e.direction == "alias→drug"]
    normalize = pack.variants.normalize_text
    forms: set[str] = set()
    lexical: set[str] = set()
    for name, term in q.asked.items():
        entry = pack.lexicon.entry(term) if term else None
        if entry is not None and entry.category == "herb":
            forms |= {normalize(f) for f in entry.surfaces()}
            if normalize(entry.term) != name:
                lexical.add(normalize(entry.term))
    if any(a.get("ambiguous") for a in entries) or (refs and all(r.get("status") == "candidate" for r in refs)):
        action, heads = "candidate", sorted({r["head"] for r in refs})
    elif reach or refs or lexical:
        action, heads = "expand", sorted(set(reach) | {r["head"] for r in refs} | lexical)
    else:
        action, heads = "none", []
    want = list(row["expect_heads"])

    def found(e: str, pool: set[str]) -> bool:
        return any(_alike(e, h, same) for h in pool)

    names = {e.surface for e in exps} | {e.head for e in exps} | forms | set(heads)
    if row["expect_action"] == "expand" and action == "none" and want and all(found(e, names) for e in want):
        action, heads = "expand", want
    if action != row["expect_action"]:
        return action, heads, False
    if action == "expand":
        return action, heads, all(found(e, names) for e in want)
    return action, heads, all(found(e, set(heads)) for e in want)


def resolution(gold: dict[str, Any], retriever: Any, systems: list[str], splits: list[str]) -> dict[str, Any]:
    """Resolution accuracy of the layered systems on the gold's resolution rows, per split, with the confusion of
    expected and given actions."""
    same = same_drug(gold.get("items") or [])
    rows = [r for r in gold.get("resolution") or [] if r.get("split") in splits]
    out: dict[str, Any] = {}
    for system in filter(layered, systems):
        cfg = {**retriever.alias, **(SYSTEMS[_base(system)] or {}).get("alias_params", {})}
        done = []
        for row in rows:
            q = retriever.analyzer.analyze(row["surface"], aliases=True, cfg=cfg)
            action, _, ok = resolve(row, q, same, retriever.pack)
            done.append((row["split"], row["expect_action"], action, ok))
        res = {}
        for split in splits + (["all"] if len(splits) > 1 else []):
            part = [d for d in done if split == "all" or d[0] == split]
            confusion: dict[str, dict[str, int]] = {}
            for _, want, got, _ in part:
                confusion.setdefault(want, {}).setdefault(got, 0)
                confusion[want][got] += 1
            res[split] = {"rows": len(part), "accuracy": _r(sum(d[3] for d in part) / len(part)) if part else None,
                          "confusion": confusion}
        out[system] = res
    return out


# ------------------------------------------------------------------ uncertainty
def _draws(n: int, resamples: int, seed: int) -> list[list[int]]:
    """``resamples`` bootstrap resamples of ``n`` items, each as how often it draws every item (drawn with
    replacement, ``n`` draws): seeded, so that every run draws the same ones."""
    rng = random.Random(seed)
    out = []
    for _ in range(resamples):
        counts = [0] * n
        for i in rng.choices(range(n), k=n):
            counts[i] += 1
        out.append(counts)
    return out


def _stat(counts: list[int], vals: list[float], have: list[int], how: str) -> float | None:
    """A metric on a resample, as :func:`aggregate` computes it: the total, or the mean over the items that have it."""
    total = sum(map(operator.mul, counts, vals))
    if how == "sum":
        return total
    n = sum(map(operator.mul, counts, have))
    return total / n if n else None


def _quantile(values: list[float], q: float) -> float:
    """The ``q`` quantile of sorted values: the least value with at least a share ``q`` of them at or below it."""
    return values[max(0, math.ceil(round(q * len(values), 9)) - 1)]


def contrasts(systems: Iterable[str]) -> list[tuple[str, str]]:
    """The differences given intervals: on − off, on − naive, and each system searched with the baseline layer against
    itself with the profile's (on − on@baseline: the layer's change)."""
    systems = list(systems)
    pairs = [("on", "off"), ("on", "naive")] + [(_base(s), s) for s in systems if s.endswith(BASELINE)]
    return [(a, b) for a, b in pairs if a in systems and b in systems]


def bootstrap(rows: dict[str, list[dict[str, Any]]], pairs: Iterable[tuple[str, str]], *,
              resamples: int = RESAMPLES, seed: int = SEED) -> dict[str, Any]:
    """A paired bootstrap of the differences ``a − b`` of :data:`BOOT_METRICS`: the items both systems scored, paired
    by id, are resampled with replacement ``resamples`` times — the same resamples for every pair and metric — and on
    each the metric of either system is computed as :func:`aggregate` does (the mean over the items that have it,
    Wrong@10 the total), and the difference.  Each pair ``"a-b"`` → metric → ``diff`` (on all the items) and ``ci95``
    (the 2.5 and 97.5 percentiles of the resampled differences; resamples on which a system has no value left out).
    Aggregates only: nothing of a single item."""
    pairs = [(a, b) for a, b in pairs if a in rows and b in rows]
    if not pairs or resamples <= 0:
        return {}
    systems = list(dict.fromkeys(s for pair in pairs for s in pair))
    by = {s: {r["id"]: r for r in rows[s]} for s in systems}
    ids = [r["id"] for r in rows[systems[0]] if all(r["id"] in by[s] for s in systems)]
    if not ids:
        return {}
    draws = [[1] * len(ids)] + _draws(len(ids), resamples, seed)  # the first: every item once
    stats: dict[tuple[str, str], list[float | None]] = {}
    for s in systems:
        for key, how in BOOT_METRICS:
            got = [by[s][i][key] for i in ids]
            vals = [0 if v is None else v for v in got]
            have = [0 if v is None else 1 for v in got]
            stats[s, key] = [_stat(c, vals, have, how) for c in draws]
    out: dict[str, Any] = {"items": len(ids)}
    for a, b in pairs:
        res: dict[str, Any] = {}
        for key, how in BOOT_METRICS:
            x, y = stats[a, key], stats[b, key]
            point = None if x[0] is None or y[0] is None else x[0] - y[0]
            diffs = sorted(p - q for p, q in zip(x[1:], y[1:]) if p is not None and q is not None)
            ci = [_quantile(diffs, (1 - LEVEL) / 2), _quantile(diffs, 1 - (1 - LEVEL) / 2)] if diffs else None
            if how == "sum":
                res[key] = {"diff": point, "ci95": ci}
            else:
                res[key] = {"diff": _r(point), "ci95": [_r(v) for v in ci] if ci else None}
        out[f"{a}-{b}"] = res
    return out


def _resamples() -> int:
    raw = os.environ.get("TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP", "").strip()
    try:
        n = int(raw) if raw else RESAMPLES
    except ValueError:
        raise ValueError(f"TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP: {raw!r} is no number of resamples") from None
    if n < 0:
        raise ValueError(f"TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP: {n} < 0")
    return n


def intervals(rows: dict[str, list[dict[str, Any]]], splits: list[str], *, resamples: int = RESAMPLES,
              seed: int = SEED) -> dict[str, Any]:
    """:func:`bootstrap` of :func:`contrasts` per split (and over all of them when there are several); empty with no
    resamples or no pair to compare."""
    pairs = contrasts(rows)
    if resamples <= 0 or not pairs:
        return {}
    out: dict[str, Any] = {"resamples": resamples, "seed": seed, "level": LEVEL,
                           "metrics": [key for key, _ in BOOT_METRICS], "pairs": [f"{a}-{b}" for a, b in pairs]}
    for split in splits + (["all"] if len(splits) > 1 else []):
        part = {s: [r for r in rs if split == "all" or r["split"] == split] for s, rs in rows.items()}
        out[split] = bootstrap(part, pairs, resamples=resamples, seed=seed)
    return out


def interval_text(got: dict[str, Any] | None, key: str) -> str | None:
    """A difference and its interval as one line: +0.049 [+0.012, +0.090]; Wrong@10 in whole passages."""
    if not got or got.get("diff") is None or not got.get("ci95"):
        return None
    fmt = "{:+g}" if dict(BOOT_METRICS)[key] == "sum" else "{:+.3f}"
    lo, hi = got["ci95"]
    return f"{fmt.format(got['diff'])} [{fmt.format(lo)}, {fmt.format(hi)}]"


def layer_file(layer: str | Path) -> Path:
    """The ``aliases.jsonl`` of an alias layer given as its directory or as the file itself."""
    path = Path(layer).expanduser()
    file = path / "aliases.jsonl" if path.is_dir() else path
    if not file.is_file():
        raise FileNotFoundError(f"TAOCHRONOS_ALIAS_EVAL_BASELINE: no alias layer at {file}")
    return file


def layer_pack(pack: Any, layer: str | Path) -> Any:
    """``pack`` with another alias layer in place of its own — the same domain and lexicons, the layer's
    ``aliases.jsonl`` and the ``context.json`` beside it — loaded as the classics plugin loads a local layer
    (``aliases_local``)."""
    from ..plugins.classics import DomainPack

    return DomainPack(pack.root, extra_lexicons=pack.extra_lexicons, aliases_file=layer_file(layer))


def layer_retriever(retriever: Any, pack: Any) -> Any:
    """A retriever like ``retriever`` — the same corpus, knowledge, embedder, route weights and alias parameters — on
    ``pack`` (:func:`layer_pack`)."""
    from ..plugins.retrieval import HybridRetriever

    return HybridRetriever(pack, retriever.corpus, knowledge=retriever.knowledge, embedder=retriever.embedder,
                           weights=retriever.weights, alias=retriever.alias)


def layer_label(pack: Any, file: Path | None = None) -> dict[str, Any]:
    """What identifies an alias layer: its fingerprint (of its bytes and its context's), records, and the store it was
    built on."""
    index = pack.aliases
    headers = getattr(index, "headers", None) or [{}]
    out = {"fingerprint": getattr(index, "fingerprint", None), "records": len(index),
           "layer_store": (headers[0].get("store") or {}).get("sha")}
    return {"file": str(file), **out} if file is not None else out


# ------------------------------------------------------------------ the synthetic part
_CN = "一二三四五六七八九十"
SYN_HERBS = ("甘草", "大黄", "芒硝", "大枣", "生姜", "人参", "桂枝", "黄连", "黄芩", "胡黄连", "木通", "通草", "徐长卿", "赤箭",
             "山药", "茯苓", "干地黄", "升麻", "麻黄", "葛根", "车前子")
# (id, title, author, year, category, passages): a synthetic corpus (CC0), written for the eval
SYN_BOOKS = (
    [(f"g{i:02d}", f"甘草方{i}", "甲", 200 + 60 * i, "方书", [f"治某病方{i}：甘草{_CN[i % 10]}两，大枣十二枚，水煮服。"])
     for i in range(20)]
    + [(f"l{i:02d}", f"国老方{i}", "乙", 600 + 150 * i, "方书", [f"又方{i}：国老{_CN[i]}两，生姜三两，大枣十二枚，煮取。"])
       for i in range(6)]
    + [(f"c{i:02d}", f"黄连方{i}", "丙", 300 + 100 * i, "方书", [f"黄连{_CN[i]}两，黄芩一两，水煎服。"]) for i in range(8)]
    + [(f"h{i:02d}", f"胡黄连方{i}", "丙", 1100 + 50 * i, "方书", [f"胡黄连{_CN[i]}钱，治小儿疳热。"]) for i in range(3)]
    + [("w01", "王连方", "丙", 500, "方书", ["王连二两，治下利。"]),
       ("w02", "王连论", "丙", 600, "本草", ["王连，味苦寒，主热气。"]),
       ("m01", "蜜方", "丁", 900, "方书", ["蜜甘一两，人参二两，为末。"]),
       ("m02", "石蜜", "丁", 500, "本草", ["石蜜甘平，主心腹邪气。"]),
       ("j01", "兵书", "戊", 300, "杂", ["大将军出征，三军随之。"]),
       ("j02", "灵兰", "戊", 300, "医经", ["心者，君主之官；肝者，将军之官。"]),
       ("j03", "承气方", "戊", 400, "方书", ["将军二两，芒硝三合，煮取一升。"]),
       ("j04", "武官", "戊", 400, "杂", ["将军者，武官也，非药。"]),
       ("j05", "大黄方", "戊", 450, "方书", ["大黄四两，芒硝三合，荡涤肠胃。"]),
       ("t01", "古通方", "己", 550, "方书", ["通草三两，治小便不利。"]),
       ("t02", "古通方二", "己", 600, "方书", ["通草、桂枝各二两。"]),
       ("t03", "清本草", "己", 1700, "本草", ["通草，即通脱木之茎髓，色白。"]),
       ("t04", "清方", "己", 1750, "方书", ["通草一钱，灯心一束。"]),
       ("t05", "清本草二", "己", 1800, "本草", ["通脱木，生山侧，茎中有瓤。"]),
       ("t06", "清方二", "己", 1820, "方书", ["木通二钱，车前子三钱。"]),
       ("k01", "木通古", "己", 500, "本草", ["木通，主除脾胃寒热。"]),
       ("k02", "木通明", "己", 1600, "方书", ["木通三两。"]),
       ("d01", "督邮一", "庚", 500, "本草", ["徐长卿，一名鬼督邮，味辛温。"]),
       ("d02", "督邮二", "庚", 600, "本草", ["赤箭，一名鬼督邮，杀鬼精物。"]),
       ("d03", "督邮三", "庚", 700, "方书", ["鬼督邮二两，治鬼疰。"]),
       ("e01", "长卿一", "庚", 500, "本草", ["徐长卿，味辛温，主蛊毒。"]),
       ("e02", "长卿二", "庚", 550, "方书", ["徐长卿三两，治疫疠。"]),
       ("f01", "赤箭一", "庚", 520, "本草", ["赤箭，味辛温，主杀鬼。"]),
       ("f02", "赤箭二", "庚", 560, "本草", ["天麻者，赤箭之根也。"]),
       ("s01", "唐方", "辛", 700, "方书", ["山药三两，干地黄八两。"]),
       ("s02", "宋方", "辛", 1200, "方书", ["山药一两，茯苓一两。"]),
       ("s03", "薯蓣方", "辛", 650, "方书", ["薯蓣丸，治虚劳。"]),
       ("x01", "干葛方", "壬", 900, "方书", ["干葛二两，升麻一两。"]),
       ("x02", "葛根方", "壬", 1000, "方书", ["葛根四两，麻黄三两。"]),
       ("z01", "汗论", "癸", 700, "医经", ["太阳病，汗出恶风。"])]
    # a question's other term that outranks the asked name: 国老治虚劳 keeps 国老 only by the asked-first rule
    + [(f"v{i:02d}", f"劳论{i}", "子", 400 + 50 * i, "医经", ["虚劳者，五劳七伤，虚劳里急，虚劳不足。"]) for i in range(12)]
)


def _syn_records() -> list[Any]:
    """The synthetic layer: invented counts and witnesses, the spec's planted pairs."""
    from ..plugins.classics.aliases import AliasRecord, Referent, Witness

    R = Referent
    return [
        AliasRecord("甘草", ho="甘草", n=900, sh=0.9),
        AliasRecord("国老", n=12, sh=0.6, r=[R("甘草", src=["bielu-jc"], w=[Witness("l00.000", 600, 600, "e", True)])]),
        AliasRecord("蜜甘", n=8, sh=0.6, b=["石蜜甘"], r=[R("甘草", src=["bielu-jc"])]),
        AliasRecord("大黄", ho="大黄", n=900, sh=0.9),
        AliasRecord("将军", n=116, sh=0.3, b=["大将军", "将军之官"],
                    r=[R("大黄", st="cue", c=["大黄", "锦纹", "川军"], src=["curated"])]),
        AliasRecord("木通", ho="木通", n=500, sh=0.9),
        AliasRecord("通草", n=300, sh=0.85, r=[R("木通", k="old_name", v=(None, 960), src=["curated"]),
                                             R("通脱木", v=(960, None), src=["curated"])]),
        AliasRecord("通脱木", ho="通脱木", n=40, sh=0.8),
        AliasRecord("鬼督邮", n=50, sh=0.9, r=[R("徐长卿", st="cue", c=["徐长卿"], src=["bielu-jc"]),
                                              R("赤箭", st="cue", c=["赤箭", "天麻"], src=["shiming"])]),
        AliasRecord("徐长卿", ho="徐长卿", n=100, sh=0.9),
        AliasRecord("赤箭", ho="赤箭", n=100, sh=0.9),
        AliasRecord("黄连", ho="黄连", n=900, sh=0.9, b=["胡黄连"]),
        AliasRecord("王连", n=10, sh=0.8, r=[R("黄连", src=["bielu-jc"])]),
        AliasRecord("胡黄连", ho="胡黄连", n=60, sh=0.9),
        AliasRecord("山药", ho="山药", n=800, sh=0.8, fl=1063, flb="taboo:yingzong"),
        AliasRecord("薯蓣", n=600, sh=0.8, r=[R("山药", k="taboo_rename", src=["taboo"])]),
    ]


def _item(iid: str, kind: str, query: str, asked: str, refs: list[tuple[str, list[str], Any]], *,
          cues: Iterable[str] = (), masks: Iterable[str] = (), wrong: Iterable[str] = (), expect: Iterable[str] = (),
          floor: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": iid, "split": "synthetic", "type": kind, "query": query, "asked": asked, "asked_cues": list(cues),
            "false_friends": list(masks), "referents": [{"head": h, "names": n, "valid": v} for h, n, v in refs],
            "wrong": list(wrong), "expect_candidates": list(expect), "floor": floor}


SYN_ITEMS = [
    _item("s-alias", "alias", "国老", "国老", [("甘草", ["甘草"], None)], expect=["甘草"]),
    _item("s-head", "head", "甘草", "甘草", [("甘草", ["国老", "蜜甘"], None)], masks=["石蜜甘"]),
    _item("s-trap", "trap", "将军", "将军", [("大黄", ["大黄"], None)], cues=["芒硝", "大黄"], masks=["大将军", "将军之官"],
          expect=["大黄"]),
    _item("s-period-early", "period", "唐以前的木通", "木通", [("木通", ["通草"], [None, 960])], wrong=["通脱木"]),
    _item("s-period-late", "period", "清代的通草", "通草", [("通脱木", ["通脱木"], [960, None])], wrong=["木通"],
          expect=["通脱木"]),
    _item("s-ambiguous", "ambiguous", "鬼督邮", "鬼督邮", [("徐长卿", ["徐长卿"], None), ("赤箭", ["赤箭", "天麻"], None)],
          expect=["徐长卿", "赤箭"]),
    _item("s-substring", "substring", "黄连", "黄连", [("黄连", ["王连"], None)], masks=["胡黄连"]),
    _item("s-weak", "head", "干葛", "干葛", [("干葛", [], None)]),
    _item("s-floor", "period", "山药", "山药", [("山药", ["薯蓣"], None)], floor={"surface": "山药", "year": 1063}),
]


def _ids(hits: list[Any]) -> list[str]:
    return [h.passage_id for h in hits]


def _checks(r: Any, legacy: Any) -> dict[str, bool]:
    """The planted cases, each a property of the layered search."""

    def on(text: str, k: int = 10, **kw: Any) -> tuple[Any, list[Any]]:
        return r.search(text, k=k, aliases="on", **kw)

    out: dict[str, bool] = {}
    queries = [i["query"] for i in SYN_ITEMS] + ["太阳病", "汗出恶风"]
    out["off_is_legacy"] = all(
        [(h.passage_id, h.score) for h in r.search(t, k=10, aliases="off")[1]]
        == [(h.passage_id, h.score) for h in r.search(t, k=10)[1]]  # the profile's choice, off
        == [(h.passage_id, h.score) for h in legacy.search(t, k=10)[1]] for t in queries)
    num, den = r.alias["share"]
    places = True
    for text in ("甘草", "国老", "鬼督邮", "将军", "黄连", "国老治虚劳", "甘草治虚劳"):
        whole = on(text, 200)[1]
        main_total = sum(h.tier not in ("B", "X") for h in whole)
        asked_total = sum(h.tier == "A" for h in whole)
        for k in (5, 10, 20):
            hits = on(text, k)[1]
            side = sum(h.tier in ("B", "X") for h in hits)
            places &= side <= num * k // den or len(hits) - side == main_total
            places &= sum(h.tier == "A" for h in hits) >= min(asked_total, k - num * k // den)
            places &= len(set(_ids(hits))) == len(hits)
    out["places_and_retention"] = places
    q, hits = on("鬼督邮")
    entry = (q.alias_view.get("asked") or [{}])[0]
    by = {h.passage_id: h for h in hits}
    side_refs = {h.via[0]["referent"] for h in hits if h.tier == "B" and h.via}
    out["no_merge"] = bool(entry.get("ambiguous")) and {"徐长卿", "赤箭"} <= {
        x["head"] for x in entry.get("referents") or []} and {"徐长卿", "赤箭"} <= side_refs
    read = {pid: (by[pid].via[0]["reading"] if pid in by and by[pid].via else "?")
            for pid in ("d01.000", "d02.000", "d03.000")}
    out["readings"] = read == {"d01.000": "徐长卿", "d02.000": "赤箭", "d03.000": None} \
        and "homonym:鬼督邮" in by["d03.000"].flags
    hits = on("将军")[1]
    gates = {h.passage_id for h in hits if h.tier == "A"} == {"j03.000"} \
        and all(h.tier == "D" for h in hits if h.passage_id in ("j01.000", "j02.000", "j04.000"))
    every = _ids(on("甘草", 50)[1])
    gates &= "m01.000" in every and "m02.000" not in every  # 蜜甘 free, not inside 石蜜甘
    hits = on("黄连", 50)[1]
    gates &= all(h.tier == "D" for h in hits if h.passage_id.startswith("h"))  # 黄连 inside 胡黄连
    gates &= set(_ids(on("干葛")[1])) == {"x01.000"}  # not the weak 葛, never 葛根
    out["gates"] = gates
    q, hits = on("唐以前的木通")
    early = {h.passage_id for h in hits if h.tier == "B"} == {"t01.000", "t02.000"}
    q2, hits2 = on("清代的通草")
    late = [(e.surface, e.why) for e in q2.expansions if e.surface == "木通"] == [("木通", "period")] \
        and "t06.000" not in _ids(hits2) and "t05.000" in _ids(hits2)
    out["periods"] = early and late
    hits = on("山药")[1]
    by = {h.passage_id: h for h in hits}
    out["flags"] = {"s01.000", "s02.000"} <= set(by) and "anachronism:山药<1063:layer" in by["s01.000"].flags \
        and not by["s02.000"].flags
    leak = 0
    for text in ("唐以前的木通", "清代的通草", "宋代以前的国老", "宋代以前的鬼督邮"):
        q, hits = on(text, 20)
        leak += _leaks(hits, q.after, q.before)
    out["no_leakage"] = leak == 0
    return out


@contextmanager
def synthetic_search(home: Path) -> Iterator[tuple[Any, Any, Any]]:
    """The synthetic corpus and layer (the full-corpus lexicon, its weak 葛 included), searched: the layered retriever,
    today's (the same pack without a layer) and the corpus."""
    from ..plugins.classics import Corpus, DomainPack
    from ..plugins.classics.aliases import write_records
    from ..plugins.retrieval import HybridRetriever
    from .textual import _write_corpus

    with tempfile.TemporaryDirectory(prefix="taochronos-aliases-") as tmp:
        root = Path(tmp)
        (root / "layer").mkdir()
        (root / "layer" / "context.json").write_text(json.dumps({"version": 1, "herbs": sorted(SYN_HERBS)},
                                                                ensure_ascii=False), encoding="utf-8")
        layer = write_records(root / "layer" / "aliases.jsonl", _syn_records(),
                              {"labels": {"bielu-jc": "别名录（中醫笈成）"}})
        pack = DomainPack(home / "domains" / "classics", extra_lexicons=["lexicon-supplement", "lexicon-harvested"],
                          aliases_file=layer)
        corpus = Corpus.load(_write_corpus(root / "corpus", SYN_BOOKS, "TaoChronos eval fixture (synthetic)"))
        corpus.normalize = pack.variants.normalize_text
        plain = copy.copy(pack)
        plain.aliases = type(pack.aliases)()
        yield HybridRetriever(pack, corpus), HybridRetriever(plain, corpus), corpus


def synthetic(ctx: EvalContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The planted cases on the synthetic corpus and layer (:func:`synthetic_search`); the checks and the metrics of
    off, naive and on on the nine synthetic items, with the paired bootstrap's intervals for on − off and on − naive
    (:func:`intervals`)."""
    with synthetic_search(ctx.home) as (r, legacy, corpus):
        checks = _checks(r, legacy)
        rows, _ = run_items(SYN_ITEMS, r, corpus, ["off", "naive", "on"])
    metrics: dict[str, Any] = dict(checks)
    for system, rs in rows.items():
        agg = aggregate(rs)
        for key in ("P@10", "AskedRet@10", "ON@10", "Wrong@10", "CandRecall", "SilentMerge", "FlagR", "Leakage"):
            metrics[f"{key} {system}"] = agg[key]
    boot = intervals(rows, ["synthetic"], resamples=_resamples())
    if boot:
        metrics["bootstrap"] = boot
    details = [{"part": "synthetic", "id": rs_on["id"], "type": rs_on["type"],
                **{s: {"P@10": _r(rows[s][k]["P@10"]), "labels": rows[s][k]["labels"]} for s in rows}}
               for k, rs_on in enumerate(rows["on"])]
    return metrics, details


# ------------------------------------------------------------------ the store part
def _env(name: str, default: Iterable[str], known: Iterable[str] | None = None) -> list[str]:
    raw = os.environ.get(name, "")
    out = [x.strip() for x in raw.split(",") if x.strip()] or list(default)
    if known is not None:
        bad = sorted(set(out) - set(known))
        if bad:
            raise ValueError(f"{name}: unknown {bad} (known: {list(known)})")
    return out


def _store_label(harness: Any) -> dict[str, Any]:
    from ..plugins.classics.aliasbuild import store_label

    corpus = harness.corpus
    label = dict(store_label(corpus.store)) if hasattr(corpus, "store") else {}
    label["edition"] = getattr(corpus, "edition", None)
    headers = getattr(harness.pack.aliases, "headers", None) or [{}]
    label["layer_store"] = (headers[0].get("store") or {}).get("sha")
    label["layer"] = getattr(harness.pack.aliases, "fingerprint", None)
    return label


def answered(rows: dict[str, list[dict[str, Any]]], split: str) -> dict[str, Any]:
    """P@10 of each system on the items of a split that ``off`` answers (at least one hit): the gain that is not a
    name made searchable as written (a question today's search finds nothing for scores 0 under it)."""
    if "off" not in rows:
        return {}
    part = {s: [r for r in rs if split == "all" or r["split"] == split] for s, rs in rows.items()}
    keep = {r["id"] for r in part["off"] if r["labels"]}
    out: dict[str, Any] = {"items": len(keep), "of": len(part["off"])}
    for system, rs in part.items():
        vals = [r["P@10"] for r in rs if r["id"] in keep and r["P@10"] is not None]
        out[f"P@10 {system}"] = _r(sum(vals) / len(vals)) if vals else None
    return out


def _acceptance(tables: dict[str, Any], split: str,
                rows: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """The spec's acceptance (§3.10) read off one split of a profile's main view; with the view's item ``rows``, also
    the gain on the items ``off`` answers (:func:`answered`, reported beside the checks, not one of them)."""
    if not {"on", "off"} <= set(tables):
        return {}
    on, off = tables["on"][split], tables["off"][split]
    a, b = on["all"], off["all"]

    def gap(x: Any, y: Any) -> float | None:
        return None if x is None or y is None else _r(x - y)

    drops = {t: gap(on["by_type"][t]["P@10"], off["by_type"][t]["P@10"]) for t in on["by_type"] if t in off["by_type"]}
    worst = min((d for d in drops.values() if d is not None), default=None)
    out = {
        "split": split,
        "P@10 gain": gap(a["P@10"], b["P@10"]),
        "worst type P@10 change": worst,
        "AskedRet@10_min on": a["AskedRet@10_min"],
        "AskedRet@10 mean on/off": [a["AskedRet@10"], b["AskedRet@10"]],
        "ON@50 on/off": [a["ON@50"], b["ON@50"]],
        "Wrong@10 on/off": [a["Wrong@10"], b["Wrong@10"]],
        "p95_ms on/off": [a["p95_ms"], b["p95_ms"]],
    }
    if rows is not None:
        got = answered(rows, split)
        if got:
            out["P@10 gain where off answers"] = gap(got.get("P@10 on"), got.get("P@10 off"))
            out["items off answers"] = [got["items"], got["of"]]
    checks = {
        "P@10 +0.03": out["P@10 gain"] is not None and out["P@10 gain"] >= 0.03,
        "no type −0.05": worst is not None and worst >= -0.05,
        "AskedRet min ≥ 0.7": a["AskedRet@10_min"] is not None and a["AskedRet@10_min"] >= 0.7,
        "AskedRet mean ≥ off": None not in (a["AskedRet@10"], b["AskedRet@10"])
        and a["AskedRet@10"] >= b["AskedRet@10"],
        "ON@50 ≥ 1.5×off": a["ON@50"] >= 1.5 * b["ON@50"],
        "Wrong@10 ≤ off": a["Wrong@10"] <= b["Wrong@10"],
        "CandRecall ≥ 0.9": a["CandRecall"] is not None and a["CandRecall"] >= 0.9,
        "SilentMerge 0": a["SilentMerge"] == 0,
        "Leakage 0": a["Leakage"] == 0,
        "p95 ≤ 1.5×off": None not in (a["p95_ms"], b["p95_ms"]) and a["p95_ms"] <= 1.5 * b["p95_ms"],
    }
    out["checks"] = checks
    out["met"] = all(checks.values())
    return out


def _problems_note(where: str, problems: list[str], gold: dict[str, Any]) -> str:
    """A note on the gold's problems: their count, and an example only among those that name a dev item (a problem
    message starts with its item's id), so that no held-out item's id or names reach the report."""
    from .aliases_gold import split_of

    dev = {i["id"] for i in gold.get("items") or [] if isinstance(i, dict) and isinstance(i.get("id"), str)
           and i.get("split") == "dev" and isinstance(i.get("group"), str) and split_of(i["group"]) == "dev"}
    on_dev = [p for p in problems if p.split(": ", 1)[0] in dev]
    return f"{where}: {len(problems)} problems, {len(on_dev)} on dev items" + (f", e.g. {on_dev[0]}" if on_dev else "")


def _refuse_heldout(splits: list[str], notes: list[str], why: str) -> list[str]:
    if "heldout" not in splits:
        return splits
    notes.append(f"held-out split refused: the gold fails its checks{why} (aliases_gold.validate)")
    return [x for x in splits if x != "heldout"]


def store(ctx: EvalContext, gold: dict[str, Any], notes: list[str], details: list[dict[str, Any]],
          checks: dict[str, Any] | None = None, heldout: bool = True) -> dict[str, Any]:
    """Each profile on the store, per view, system, split and item type.  The gold is checked on the store first, on
    the first profile's harness and before any item is chosen: its witnesses, and on the web store (which the gold was
    drawn from) its pools; ``checks`` receives the result.  Without ``heldout`` (a gold that fails its checks on file),
    or when it fails them on the store, the held-out split is not run.  With ``$TAOCHRONOS_ALIAS_EVAL_BASELINE`` the
    baseline systems (``on@baseline`` …) search the same items with that layer (:func:`layer_pack`), in the same
    rotation; the paired bootstrap (:func:`intervals`) runs on the main view's rows."""
    from ..bootstrap import Harness

    profiles = _env("TAOCHRONOS_ALIAS_EVAL", PROFILES, Harness.profiles(ctx.home))
    splits = _env("TAOCHRONOS_ALIAS_EVAL_SPLITS", SPLITS, SPLITS)
    systems = _env("TAOCHRONOS_ALIAS_EVAL_SYSTEMS", SYSTEMS, SYSTEMS)
    views = _env("TAOCHRONOS_ALIAS_EVAL_VIEWS", VIEWS, VIEWS)
    resamples = _resamples()
    layer = os.environ.get("TAOCHRONOS_ALIAS_EVAL_BASELINE", "").strip()
    base_file = layer_file(layer) if layer else None  # a wrong path fails before anything runs
    baseline = [f"{s}{BASELINE}" for s in _env("TAOCHRONOS_ALIAS_EVAL_BASELINE_SYSTEMS", ["on"],
                                                [s for s in SYSTEMS if s != "off"])] if layer else []
    if not heldout:
        splits = _refuse_heldout(splits, notes, "")
        if not splits:
            return {}
    checks = {} if checks is None else checks
    same = same_drug(gold.get("items") or [])
    excluded = list(gold.get("excluded_books") or ["jc_c030"])
    out: dict[str, Any] = {}
    for profile in profiles:
        try:
            main = ctx.profile_harness(profile, exclude_books=excluded)
        except FileNotFoundError as e:  # full-corpus-local without its built layer
            notes.append(f"{profile}: skipped — {e}")
            continue
        if main is None:
            return {}
        label = _store_label(main)
        edition = label.get("edition")
        if "store_valid" not in checks:
            from .aliases_gold import pools, validate

            mined = pools(main.corpus.store, ctx.home)["pools"] if edition == "web" else None
            problems = validate(gold, corpus=main.corpus, pools=mined)
            checks.update({"store_valid": not problems, "store_checks": "witnesses and pools" if mined else "witnesses"})
            if problems:
                notes.append(_problems_note("gold on the store", problems, gold))
        if checks.get("store_valid") is False:
            splits = _refuse_heldout(splits, notes, " on the store")
            if not splits:
                return out
        items = [i for i in gold.get("items") or [] if i.get("split") in splits]
        deployed = (profile == "web-canon" and edition == "web") or (profile == "full-corpus" and edition == "full")
        result: dict[str, Any] = {"store": label, "pair": "deployed" if deployed else "proxy", "splits": splits,
                                  "views": {}}
        gangmu = sorted({b for b in main.corpus.books if b.startswith(GANGMU)}
                        | set(gold.get("report_without") or []))
        base_pack = layer_pack(main.capabilities.get("retriever").pack, base_file) if baseline else None
        main_rows: dict[str, list[dict[str, Any]]] | None = None
        boot_view, boot_rows = None, None
        for view in views:
            harness = main if view == "main" else ctx.profile_harness(profile, exclude_books=excluded + gangmu)
            retriever = harness.capabilities.get("retriever")
            others = dict.fromkeys(baseline, layer_retriever(retriever, base_pack)) if baseline else {}
            rows, info = run_items(items, retriever, harness.corpus, systems + baseline, same=same, others=others)
            if view == "main" or boot_rows is None:
                boot_view, boot_rows = view, rows
            tables: dict[str, Any] = {}
            for system, rs in rows.items():
                tables[system] = {split: table([r for r in rs if r["split"] == split]) for split in splits}
                if len(splits) > 1:
                    tables[system]["all"] = table(rs)
            result["views"][view] = tables
            if view == "main":
                main_rows = rows
                for k, (item, meta) in enumerate(zip(items, info)):
                    if item["split"] != "dev":
                        continue  # held-out items are scored in aggregate only
                    details.append({"part": "store", "profile": profile, "id": item["id"], "type": item["type"],
                                    "query": item["query"], **meta,
                                    "systems": {s: {key: (_r(v) if isinstance(v, float) else v)
                                                    for key, v in rows[s][k].items()
                                                    if key not in ("type", "split", "id", "n_asked")}
                                                for s in rows}})
        result["resolution"] = resolution(gold, main.capabilities.get("retriever"), systems, splits)
        if baseline:
            result["baseline"] = layer_label(base_pack, base_file)
            result["resolution"].update(resolution(gold, layer_retriever(main.capabilities.get("retriever"), base_pack),
                                                   baseline, splits))
        boot = intervals(boot_rows, splits, resamples=resamples) if boot_rows is not None else {}
        if boot:
            result["bootstrap"] = {"view": boot_view, **boot}
        split = "heldout" if "heldout" in splits else splits[0]
        tables = result["views"].get("main") or next(iter(result["views"].values()))
        result["acceptance"] = _acceptance(tables, split, main_rows)
        result["answered"] = answered(main_rows, split) if main_rows is not None else {}
        headline: dict[str, Any] = {"pair": result["pair"], "split": split, "store": label.get("sha")}
        for system in ("off", "naive", "analysis", "on", *baseline):
            if system in tables:
                a = tables[system][split]["all"]
                headline[f"P@10 {system}"] = a["P@10"]
                headline[f"Wrong@10 {system}"] = a["Wrong@10"]
        if "on" in tables:
            a = tables["on"][split]["all"]
            headline.update({"AskedRet@10 on": a["AskedRet@10"], "ON@50 on": a["ON@50"],
                             "CandRecall on": a["CandRecall"], "SilentMerge on": a["SilentMerge"],
                             "Leakage on": a["Leakage"]})
        for system in ("on", *baseline):
            if system in result["resolution"]:
                headline[f"resolution {system}"] = result["resolution"][system][split]["accuracy"]
        if "P@10 gain where off answers" in result["acceptance"]:
            headline["P@10 gain where off answers"] = result["acceptance"]["P@10 gain where off answers"]
        boot = result.get("bootstrap") or {}
        for pair in boot.get("pairs") or []:  # the split's differences with their 95 % intervals, as text
            for key in ("P@10", "Wrong@10"):
                text = interval_text((boot.get(split) or {}).get(pair, {}).get(key), key)
                if text:
                    headline[f"{key} {pair}"] = text
        out[profile] = {**headline, "results": result}
        notes.append(f"{profile}: store {label.get('sha')} ({label.get('books')} books, {label.get('passages')} "
                     f"passages, edition {edition}; layer {label.get('layer')} built on {label.get('layer_store')}) — "
                     f"{result['pair']}; {len(items)} items ({', '.join(splits)}), views {', '.join(views)} (no-gangmu "
                     f"also leaves out {', '.join(gangmu)})")
        if baseline:
            base = result["baseline"]
            notes.append(f"{profile}: baseline layer {base['fingerprint']} ({base['records']} records, built on "
                         f"{base['layer_store']}; {base['file']}) searched as {', '.join(baseline)}")
    return out


def aliases(ctx: EvalContext) -> SuiteResult:
    """AliasEval: the synthetic planted cases always; the gold on the store for each profile unless ``--quick``."""
    from .aliases_gold import load_gold, split_digest, validate

    started = time.perf_counter()
    syn, details = synthetic(ctx)
    syn["seconds"] = round(time.perf_counter() - started, 2)
    metrics: dict[str, Any] = {"synthetic": syn}
    notes = [
        ("synthetic: 将军/大将军/将军之官, 通草 before and after 960, 鬼督邮 (two drugs, cue names), 蜜甘 in 石蜜甘, 黄连 in "
         "胡黄连, the weak 葛 in 干葛, 山药 before 1063; checks: places (side ≤ ⌊3k/10⌋ while the main queue lasts) and "
         "retention (asked ≥ min(|A|, k − ⌊3k/10⌋)) at k = 5, 10, 20, no merging, gates, readings, flags, no leakage, "
         "off = today's search"),
        ("labels: each item's own patterns on normalised text, false friends masked — asked (with a cue when the item "
         "has cues), other (a referent's name, the passage inside its window), wrong (neither, and a wrong name, the "
         "asked form only masked, or without a cue); rel = asked or other; the layer's gates are never used"),
        ("systems: off = today's search; naive = today's search with the layer's one-hop pairs (alias→drug, and the "
         "open and cue names of the drugs asked) as lexicon surfaces, no gates, windows or places; on = the layer; "
         "analysis = the layer's reading of the question alone (no expansions, no side queue); ablations gates, "
         "boundary, slots, period, asked_first all/off"),
        ("counts N_rel, N_asked, N_other are read in the question's window up to 50 (all that min(10, ·) and "
         "min(50, ·) need); latency is the k = 10 call, timed after every system has searched the item once untimed "
         "(the systems' order turning with the item), so that what a first call fills favours none of them; each "
         "profile extracts its claims into a cache of its own (the store's claim cache is neither read nor written)"),
        (f"intervals: a paired bootstrap over items ({_resamples()} resamples, seed {SEED}; the same resamples for "
         "every system and metric): 95 % percentile intervals of on − off, on − naive and, with "
         "TAOCHRONOS_ALIAS_EVAL_BASELINE, on − on@baseline (the same items searched with that layer), for P@10, "
         "nDCG@10, Wrong@10 and the mean AskedRet@10, per split of the main view; aggregates only"),
        ("candidates: the drugs query.aliases names for the asked form (a stop name's drugs, status stop, among them "
         "where the item expects candidates; for an item expecting none a stop's listing is no candidate), mapped to "
         "the item's referents by their heads and names first, then by the asked drug's own lexicon forms (none the "
         "item calls wrong; none when they meet two referents) and the asked form, else through the gold's same-drug "
         "names (the asked form itself only where the item expects it); SilentMerge = ambiguous items with fewer than "
         "two expected drugs listed; None for systems without the layer"),
    ]
    gold = load_gold(ctx.home)
    problems = validate(gold)
    metrics["gold"] = {"items": len(gold.get("items") or []), "resolution": len(gold.get("resolution") or []),
                       "valid": not problems, "split_sha256": split_digest(gold)[:12]}
    if problems:
        notes.append(_problems_note("gold", problems, gold))
    if ctx.quick:
        notes.append("store part skipped (--quick)")
    else:
        found = store(ctx, gold, notes, details, metrics["gold"], heldout=not problems)
        if not found and ctx.store_data() is None:
            notes.append("store part skipped: no corpus store under --data")
        metrics.update(found)
        notes.append("held-out items are reported in aggregate only: details list dev items")
    return SuiteResult("aliases", metrics, details, notes=notes)


__all__ = ["Labeller", "Naive", "aggregate", "aliases", "answered", "asked_forms", "bootstrap", "contrasts",
           "intervals", "layer_pack", "layer_retriever", "listed", "resolve", "same_drug", "score", "store_counts",
           "synthetic", "synthetic_search"]
