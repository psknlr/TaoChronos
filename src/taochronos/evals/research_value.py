"""Research value — evaluation layer 3: does what the system proposes from the past anticipate what later physicians
wrote?

The invariants (layer 1) ask whether the harness keeps its boundaries, the interpretive cases (layer 2) whether it reads
hard sentences safely.  This layer asks whether its discoveries are worth anything — on the full corpus, blind to time.
At a cutoff year the store splits into the past, the passages whose whole date range lies before it, and the future,
the passages wholly after it (``StoreCorpus.on_side``); a passage that may have been written on either side is in
neither.  Two measurements, each against baselines on the same material:

**Link anticipation.**  For every disease and symptom of the lexicon with enough past and future passages (the rule is
fixed in ``evals/gold/research_value.yaml``; the topics follow from it), the positive claims of all the past passages
that name the topic form the co-occurrence graph the D4 track reads.  Every formula or drug of that graph not linked to
the topic is a candidate; it *comes true* when future claims of at least two books link it to the topic.  Adamic–Adar
(what D4 ranks by), resource allocation and common neighbours are compared with popularity — the best-connected
remedies first, the baseline that is hardest to beat — and with chance: hits in the top k, average precision, and the
paired comparison over topics (an exact sign test).

**End to end.**  The research pipeline runs on the past alone — a full-corpus harness whose corpus is the past view, so
its retrieval, knowledge and study layers see nothing later — and each structured prediction of its hypotheses is
judged by the future: strictly (a future claim of the association's own relation whose quote supports it) and, as the
first runs did, loosely (any claim naming both terms).  A hidden association is also checked against the whole past (a
session reads a sample: a link it calls hidden may be written in a past book it did not read), and set beside what
popularity and chance achieve for the same condition on the session's own graph.  The topics are split: dev (runs
inspected while the pipeline was changed) and held-out.  A passage of the session that is not in the past is counted
as leakage.

What it does not show: that a later text learned the link from an earlier one — a link comes true when later physicians
wrote it, whoever found it first, so the benchmark measures anticipation, not influence.  It measures the rules'
extraction on both sides: a link the extractor misses in the future is a miss for every ranker alike.  And the shared
full-text index still ranks with statistics of the whole store (``StoreCorpus.on_side``).  Skipped when the
full-corpus store is absent, and in ``--quick`` runs.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import Counter, defaultdict
from typing import Any, Iterable

from ..protocol.claims import ClaimRelation
from ..science import CooccurrenceGraph, link_prediction
from ..science.stats import bootstrap_ci, wilson_interval
from ..verification.support import assess_support
from .base import EvalContext, SuiteResult
from .rediscovery import check_prediction

POSITIVE = frozenset({ClaimRelation.INDICATED_FOR.value, ClaimRelation.HERB_INDICATION.value, ClaimRelation.COMPOSED_OF.value})
CAUSAL = frozenset({ClaimRelation.CAUSES.value, ClaimRelation.PATHOGENESIS.value})
INDICATION = frozenset({ClaimRelation.INDICATED_FOR.value, ClaimRelation.HERB_INDICATION.value})
RANKERS = ("adamic_adar", "resource_allocation", "common_neighbors", "popularity", "random")
REMEDY = ("formula", "herb")
CONDITION = ("disease", "symptom", "pattern", "sign")
Link = tuple[str, str, frozenset]  # (relation, book, argument terms) of one claim


def _members(claim: Any) -> frozenset:
    return frozenset(a.term_id for a in claim.arguments if a.term_id and not a.negated and not a.qualifiers.get("outcome"))


def _kind(term_id: str) -> str:
    return term_id.split(":", 1)[0]


def _sample(ids: Iterable[str], cap: int | None) -> list[str]:
    """A fixed sample: the ``cap`` ids of smallest hash, the same passages on every run."""
    ids = sorted(set(ids))
    if cap is None or len(ids) <= cap:
        return ids
    return sorted(sorted(ids, key=lambda pid: hashlib.sha1(pid.encode("utf-8")).hexdigest())[:cap])


class Reader:
    """The passages of a view that name some words, and their claims — extracted in process and kept per passage in a
    compact form (a benchmark does not fill the store's claim cache)."""

    def __init__(self, harness: Any) -> None:
        self.pack = harness.pack
        self.extractor = harness.capabilities.get("extractor")
        self.philology = harness.capabilities.get("philology")
        self._links: dict[str, list[Link]] = {}
        self._ids: dict[tuple[Any, str], set[str]] = {}
        self.extracted = 0

    def is_remedy(self, term_id: str) -> bool:
        """A formula or drug of the lexicon, its weak entries excepted: the harvested one-character entries (药, 补,
        白 …) are as often words as drugs."""
        entry = self.pack.lexicon.entry(term_id)
        return _kind(term_id) in REMEDY and entry is not None and not entry.weak

    def words(self, term_id: str) -> list[str]:
        """The words that name a term: its name and its surfaces of two characters or more (a one-character synonym,
        such as 利 for 下利, names far more than the term)."""
        entry = self.pack.lexicon.entry(term_id)
        if entry is None:
            return [term_id.split(":", 1)[-1]]
        return list(dict.fromkeys([entry.term, *(s for s in entry.surfaces()[1:] if len(s) >= 2)]))

    def ids(self, view: Any, term_id: str) -> set[str]:
        key = ((tuple(getattr(view, "bounds", ())), tuple(sorted(getattr(view, "exclude_books", ())))), term_id)
        if key not in self._ids:
            found: set[str] = set()
            for w in self.words(term_id):
                found.update(view.contains(w, verify=False))
            self._ids[key] = found
        return self._ids[key]

    def links(self, view: Any, ids: Iterable[str]) -> list[Link]:
        ids = list(ids)
        todo = [pid for pid in ids if pid not in self._links]
        for p in view.passages_by_id(todo):
            self._links[p.id] = [(c.relation.value, c.book_id, _members(c)) for c in self.extractor.extract(p, self.philology.assess(p))]
            self.extracted += 1
        return [x for pid in ids for x in self._links.get(pid, ())]

    def claims(self, view: Any, ids: Iterable[str]) -> list[Any]:
        """Full claims (for the checks that read arguments), not kept."""
        return [c for p in view.passages_by_id(list(ids)) for c in self.extractor.extract(p, self.philology.assess(p))]


# ------------------------------------------------------------------ ranking
def ranking(graph: CooccurrenceGraph, topic: str, candidates: set[str], method: str, seed: int = 0) -> list[str]:
    """Every candidate, best first: the ones the method scores (``science.link_prediction``, as D4 calls it), then
    the unscored ones — no shared neighbour — in a fixed random order."""
    scored = link_prediction(graph, left=lambda n: n == topic, right=lambda n: n in candidates, method=method,
                             k=len(candidates), seed=seed)
    ranked = [p["right"] for p in scored]
    seen = set(ranked)
    rest = sorted((x for x in candidates if x not in seen), key=lambda x: hashlib.sha1(f"{seed}:{x}".encode("utf-8")).hexdigest())
    return ranked + rest


def average_precision(ranked: list[str], truth: set[str]) -> float:
    hits, total = 0, 0.0
    for i, x in enumerate(ranked, 1):
        if x in truth:
            hits += 1
            total += hits / i
    return total / len(truth) if truth else 0.0


def _score(ranked: list[str], truth: set[str], ks: list[int]) -> dict[str, Any]:
    out: dict[str, Any] = {f"hits@{k}": sum(1 for x in ranked[:k] if x in truth) for k in ks}
    out["ap"] = round(average_precision(ranked, truth), 4)
    out["first_hit"] = next((i for i, x in enumerate(ranked, 1) if x in truth), None)
    return out


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact sign test (ties left out)."""
    n = wins + losses
    if n == 0:
        return 1.0
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n)
    return round(p, 4) if p >= 1e-4 else float(f"{p:.1e}")


# ------------------------------------------------------------------ 1. link anticipation
def topic_row(reader: Reader, past: Any, future: Any, topic: str, rules: dict[str, Any]) -> dict[str, Any]:
    """One topic at one cutoff: its candidates, which came true, and how each ranker orders them."""
    rule = rules["topics"]
    min_books, ks = rules["truth"]["min_books"], rules["ks"]
    past_ids, future_ids = reader.ids(past, topic), reader.ids(future, topic)
    row: dict[str, Any] = {"topic": topic, "past_passages": len(past_ids), "future_passages": len(future_ids)}
    if len(past_ids) < rule["min_past"]:
        return {**row, "skipped": "past_too_few"}
    if len(past_ids) > rule["max_past"]:
        return {**row, "skipped": "past_too_many"}
    if len(future_ids) < rule["min_future"]:
        return {**row, "skipped": "future_too_few"}
    graph = CooccurrenceGraph([sorted(m) for rel, _, m in reader.links(past, past_ids) if rel in POSITIVE])
    if topic not in graph.adj:
        return {**row, "skipped": "no_positive_past_claim"}
    candidates = {n for n in graph.nodes() if reader.is_remedy(n) and not graph.linked(topic, n)}
    sample = _sample(future_ids, rule["future_cap"])
    books: dict[str, set[str]] = defaultdict(set)
    for rel, book, m in reader.links(future, sample):
        if rel in POSITIVE and topic in m:
            for x in m:
                books[x].add(book)
    truth = {x for x in candidates if len(books.get(x, ())) >= min_books}
    row.update(future_read=len(sample), linked_before=sum(1 for n in graph.adj[topic] if reader.is_remedy(n)),
               candidates=len(candidates), came_true=len(truth), came_true_one_book=sum(1 for x in candidates if books.get(x)),
               base_rate=round(len(truth) / len(candidates), 4) if candidates else None)
    if not truth:
        return row
    for method in RANKERS[:-1]:
        ranked = ranking(graph, topic, candidates, method)
        row[method] = _score(ranked, truth, ks)
        if method == "adamic_adar":
            row["examples"] = [{"remedy": x, "rank": i, "future_books": len(books[x])}
                               for i, x in enumerate(ranked[:20], 1) if x in truth][:3]
    draws = [_score(ranking(graph, topic, candidates, "random", seed=s), truth, ks) for s in range(1, rules["random_seeds"] + 1)]
    row["random"] = {key: round(sum(d[key] for d in draws) / len(draws), 4) for key in [f"hits@{k}" for k in ks] + ["ap"]}
    return row


def summarise(rows: list[dict[str, Any]], ks: list[int]) -> dict[str, Any]:
    judged = [r for r in rows if r.get("came_true")]
    out: dict[str, Any] = {
        "topics_read": sum(1 for r in rows if "skipped" not in r), "topics_with_links_come_true": len(judged),
        "skipped": dict(Counter(r["skipped"] for r in rows if "skipped" in r)),
        "candidates": sum(r.get("candidates", 0) for r in judged), "came_true": sum(r["came_true"] for r in judged),
    }
    if not judged:
        return out
    out["base_rate"] = round(out["came_true"] / out["candidates"], 4)
    for m in RANKERS:
        aps = [r[m]["ap"] for r in judged]
        lo, hi = bootstrap_ci(aps, seed=1)
        entry: dict[str, Any] = {"mean_ap": round(sum(aps) / len(aps), 4), "mean_ap_ci": [round(lo, 4), round(hi, 4)]}
        for k in ks:
            hits = sum(r[m][f"hits@{k}"] for r in judged)
            n = sum(min(k, r["candidates"]) for r in judged)
            entry[f"precision@{k}"] = round(hits / n, 4) if n else None
            if m != "random":  # the random rows are expectations over draws, not counts
                lo, hi = wilson_interval(int(hits), n)
                entry[f"precision@{k}_ci"] = [round(lo, 4), round(hi, 4)]
        out[m] = entry

    def paired(a: str, b: str) -> dict[str, Any]:
        wins = sum(1 for r in judged if r[a]["ap"] > r[b]["ap"])
        losses = sum(1 for r in judged if r[a]["ap"] < r[b]["ap"])
        return {"wins": wins, "losses": losses, "ties": len(judged) - wins - losses, "sign_test_p": sign_test(wins, losses)}

    out["adamic_adar_vs_popularity"] = paired("adamic_adar", "popularity")
    out["adamic_adar_vs_random"] = paired("adamic_adar", "random")
    out["popularity_vs_random"] = paired("popularity", "random")
    return out


def link_anticipation(big: Any, reader: Reader, rules: dict[str, Any], details: list[dict[str, Any]]) -> dict[str, Any]:
    lexicon = big.pack.lexicon
    topics = sorted(e.term_id for e in lexicon.by_category(*rules["topics"]["categories"]) if not e.weak)
    per_cutoff: dict[str, Any] = {}
    every: list[dict[str, Any]] = []
    for cutoff in rules["cutoffs"]:
        past, future = big.corpus.on_side(cutoff, "before"), big.corpus.on_side(cutoff, "after")
        rows = [{"cutoff": cutoff, **topic_row(reader, past, future, t, rules)} for t in topics]
        details.extend({"part": "link_anticipation", **r} for r in rows)
        per_cutoff[str(cutoff)] = summarise(rows, rules["ks"])
        every.extend(rows)
    return {"by_cutoff": per_cutoff, "pooled": summarise(every, rules["ks"]), "topics_considered": len(topics)}


# ------------------------------------------------------------------ 2. end to end
def end_to_end(ctx: EvalContext, big: Any, reader: Reader, rules: dict[str, Any], details: list[dict[str, Any]], *,
               splits: Iterable[str] = ("dev", "heldout")) -> dict[str, Any]:
    cfg = rules.get("end_to_end") or {}
    topics = [t for t in cfg.get("topics") or [] if t.get("split", "heldout") in set(splits)]
    if not topics:
        return {}
    cutoff = cfg["cutoff"]
    min_books, cap = rules["truth"]["min_books"], rules["topics"]["future_cap"]
    past, future = big.corpus.on_side(cutoff, "before"), big.corpus.on_side(cutoff, "after")
    harness = ctx.corpus_view_harness(past)
    lexicon = big.pack.lexicon

    normalize, cruxes = big.pack.variants.normalize_text, getattr(big.pack, "cruxes", None)

    def pair_books(view: Any, a: str, b: str, *, positive: bool) -> set[str]:
        """The loose reading (the first runs'): books with a claim of any (or any positive) relation naming both."""
        both = reader.ids(view, a) & reader.ids(view, b)
        return {book for rel, book, m in reader.links(view, both) if {a, b} <= m and (rel in POSITIVE or not positive)}

    def stated_books(view: Any, a: str, b: str, relations: frozenset) -> set[str]:
        """The strict reading: books with a claim of the association's own relation naming both, whose quote supports it."""
        out: set[str] = set()
        for p in view.passages_by_id(_sample(reader.ids(view, a) & reader.ids(view, b), cap)):
            for c in reader.extractor.extract(p, reader.philology.assess(p)):
                if c.relation.value in relations and {a, b} <= _members(c) and c.book_id not in out \
                        and assess_support(c, p.text, normalize, cruxes).verdict == "supports":
                    out.add(c.book_id)
        return out

    def judge(pred: Any, hyp: Any) -> dict[str, Any]:
        kind, subject, obj = pred.kind, pred.subject or "", pred.object or ""
        termlike = ":" in subject and _kind(subject) not in ("work",)
        if kind == "absent_after" and termlike and obj:
            unit = CAUSAL if {_kind(subject), _kind(obj)} & {"etiology", "pathogenesis"} else INDICATION
            loose, strict = pair_books(future, subject, obj, positive=False), stated_books(future, subject, obj, unit)
            return {"held": not strict, "held_loose": not loose, "future_books": len(strict), "future_books_loose": len(loose)}
        if kind == "link_appears" and termlike and obj:
            loose, strict = pair_books(future, subject, obj, positive=True), stated_books(future, subject, obj, POSITIVE)
            if not loose and not any(subject in m for _, _, m in reader.links(future, _sample(reader.ids(future, subject), 1500))):
                return {"held": None, "why": "the future makes no claim about the subject"}
            return {"held": len(strict) >= min_books, "held_loose": len(loose) >= min_books, "future_books": len(strict),
                    "future_books_loose": len(loose), "written_before": bool(stated_books(past, subject, obj, POSITIVE))}
        if kind == "cooccurrence_after" and subject and obj:
            lhs = subject.split(",")
            ids = set.intersection(*(reader.ids(future, t) for t in lhs)) if lhs else set()
            verdict = check_prediction(pred, hyp, reader.claims(future, _sample(ids, cap)), big, [])
            return {"held": verdict, "held_loose": verdict}
        if kind in ("sense_shift", "renaming") and ":" in subject:
            verdict = check_prediction(pred, hyp, reader.claims(future, _sample(reader.ids(future, subject), 1500)), big, [])
            return {"held": verdict, "held_loose": verdict}
        return {"held": None, "why": "not judged by this benchmark"}

    out: dict[str, Any] = {"cutoff": cutoff, "topics": {}}
    tally: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    loose: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    reviewed: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    novel: dict[str, list[bool]] = defaultdict(list)  # hidden associations: came true *and* written nowhere before
    # what a review lets through, counted as discoveries: a hidden association that came true but was already written
    # before the cutoff is no discovery
    found: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for t in topics:
        split = t.get("split", "heldout")
        entry = lexicon.resolve(t["term"])
        term_id = entry.term_id if entry else t["term"]
        started = time.perf_counter()
        session = ctx.run(harness, t["question"], session_id=f"rv{cutoff}-{t['term']}", focus_terms=[t["term"]],
                          forbidden_assumptions=list(t.get("forbidden_assumptions", [])))
        state = session.state
        refs = ({e.passage_id for e in state.evidence.values()} | {c.passage_id for c in state.claims.values()}
                | {pid for o in state.observations.values() for pid in o.passage_ids})
        leaked = sorted(pid for pid in refs if not past.has_passage(pid))
        graph = CooccurrenceGraph([sorted(_members(c)) for c in state.claims.values() if c.relation.value in POSITIVE])
        rows = []
        for hyp in state.hypotheses.values():
            if hyp.status == "superseded":
                continue
            for pred in hyp.predictions:
                verdict = judge(pred, hyp)
                row = {"part": "end_to_end", "split": split, "topic": term_id, "hypothesis": hyp.id, "kind": hyp.kind,
                       "status": hyp.status, "prediction": pred.kind, "subject": pred.subject, "object": pred.object, **verdict}
                if hyp.kind == "hidden_association" and pred.kind == "link_appears" and verdict.get("held") is not None:
                    row["same_condition"] = _matched(reader, future, graph, pred.subject, pred.object, min_books, cap)
                rows.append(row)
                if verdict.get("held") is not None:
                    tally[split][pred.kind].append(bool(verdict["held"]))
                    loose[split][pred.kind].append(bool(verdict.get("held_loose", verdict["held"])))
                    reviewed[split]["survived" if hyp.status in ("survived", "expert_approved") else "other"].append(bool(verdict["held"]))
                    known = hyp.kind == "hidden_association" and bool(verdict.get("written_before"))
                    found[split]["survived" if hyp.status in ("survived", "expert_approved") else "other"].append(
                        bool(verdict["held"]) and not known)
                    if hyp.kind == "hidden_association" and pred.kind == "link_appears":
                        novel[split].append(bool(verdict["held"]) and not known)
        details.extend(rows)
        out["topics"][term_id] = {
            "split": split, "seconds": round(time.perf_counter() - started, 1), "status": state.status,
            "acceptance": (state.acceptance or {}).get("status"), "claims": len(state.claims),
            "hypotheses": sum(1 for h in state.hypotheses.values() if h.status != "superseded"),
            "predictions": len(rows), "judged": sum(1 for r in rows if r.get("held") is not None),
            "passages_referenced": len(refs), "leakage": len(leaked), "leaked": leaked[:10],
        }

    def rate(values: list[bool]) -> dict[str, Any]:
        lo, hi = wilson_interval(sum(values), len(values))
        return {"n": len(values), "held": sum(values), "rate": round(sum(values) / len(values), 4) if values else None,
                "ci": [round(lo, 4), round(hi, 4)]}

    for split in sorted(set(tally) | set(reviewed)):
        judged = [v for values in tally[split].values() for v in values]
        out[split] = {"judged": rate(judged), "by_prediction": {k: rate(v) for k, v in sorted(tally[split].items())},
                      "by_review": {k: rate(v) for k, v in sorted(reviewed[split].items())},
                      "judged_loose": rate([v for values in loose[split].values() for v in values]),
                      "by_prediction_loose": {k: rate(v) for k, v in sorted(loose[split].items())},
                      "hidden_associations_new_and_true": rate(novel[split]) if novel[split] else None,
                      "discoveries_by_review": {k: rate(v) for k, v in sorted(found[split].items())}}
    out["leakage"] = sum(t["leakage"] for t in out["topics"].values())
    return out


def _matched(reader: Reader, future: Any, graph: CooccurrenceGraph, condition: str, remedy: str, min_books: int,
             cap: int) -> dict[str, Any]:
    """For the condition of a hidden association, on the session's own graph: how often a remedy not linked to it
    comes true (chance), and whether the best-connected such remedy did (popularity)."""
    if condition not in graph.adj:
        return {}
    candidates = {n for n in graph.nodes() if reader.is_remedy(n) and not graph.linked(condition, n)}
    books: dict[str, set[str]] = defaultdict(set)
    for rel, book, m in reader.links(future, _sample(reader.ids(future, condition), cap)):
        if rel in POSITIVE and condition in m:
            for x in m:
                books[x].add(book)
    truth = {x for x in candidates if len(books.get(x, ())) >= min_books}
    popular = ranking(graph, condition, candidates, "popularity")[:1]
    aa = ranking(graph, condition, candidates, "adamic_adar")
    return {"candidates": len(candidates), "chance": round(len(truth) / len(candidates), 4) if candidates else None,
            "popularity_pick": popular[0] if popular else None, "popularity_pick_held": bool(popular and popular[0] in truth),
            "adamic_adar_rank": aa.index(remedy) + 1 if remedy in aa else None,
            "adamic_adar_precision@5": round(sum(1 for x in aa[:5] if x in truth) / min(5, len(aa)), 4) if aa else None}


# ------------------------------------------------------------------ the suite
def headline(links: dict[str, Any], e2e: dict[str, Any]) -> dict[str, Any]:
    """The few numbers a summary line shows (flat)."""
    pooled = links.get("pooled", {})
    out: dict[str, Any] = {}
    for key, ranker in (("adamic_adar", "adamic_adar"), ("popularity", "popularity"), ("chance", "random")):
        if ranker in pooled:
            out[f"{key}_p@10"] = pooled[ranker].get("precision@10")
    duel = pooled.get("adamic_adar_vs_popularity")
    if duel:
        out["adamic_adar_vs_popularity"] = f"{duel['wins']}/{duel['losses']} (p={duel['sign_test_p']})"
    held = (e2e.get("heldout") or {})
    if held:
        out["heldout_held"] = f"{held['judged']['held']}/{held['judged']['n']}"
        found = (held.get("discoveries_by_review") or {}).get("survived")
        if found:
            out["heldout_surviving_discoveries"] = f"{found['held']}/{found['n']}"
    if e2e:
        out["leakage"] = e2e.get("leakage")
    return out


def research_value(ctx: EvalContext) -> SuiteResult:
    if ctx.quick:
        return SuiteResult("research_value", {"skipped": "quick run"}, notes=["A full-corpus benchmark: run it without --quick."])
    big = ctx.corpus_harness()
    if big is None:
        return SuiteResult("research_value", {"skipped": "no full-corpus store"},
                           notes=["Needs the full-corpus store (taochronos corpus …): the benchmark is only meaningful on it."])
    rules = ctx.gold("research_value")
    reader = Reader(big)
    details: list[dict[str, Any]] = []
    started = time.perf_counter()
    links = link_anticipation(big, reader, rules, details)
    e2e = end_to_end(ctx, big, reader, rules, details)
    metrics: dict[str, Any] = {"headline": headline(links, e2e), "link_anticipation": links, "end_to_end": e2e,
                               "passages_read": reader.extracted, "seconds": round(time.perf_counter() - started, 1)}
    notes = [
        "Past and future are the passages wholly before and wholly after the cutoff (a passage straddling it is in neither); "
        "a candidate comes true when future claims of at least two books link it to the topic.",
        "Anticipation, not influence: a link that comes true was written later, whoever found it first.",
        "Both sides are read by the rule extractor: a link it misses is a miss for every ranker alike.",
        "The full-text index of the store ranks with whole-store statistics; no passage of the other side is read.",
    ]
    return SuiteResult("research_value", metrics, details, notes)


__all__ = ["Reader", "average_precision", "headline", "ranking", "research_value", "sign_test", "summarise", "topic_row"]
