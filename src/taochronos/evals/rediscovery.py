"""RediscoveryEval: the Historical Time Machine and source rediscovery.

Time Machine — the research runs on a corpus truncated at a cutoff year (a separate harness, so no index,
cache or graph ever sees a later text).  Every hypothesis carries structured predictions; they are then
checked against the claims of the texts written *after* the cutoff.  A text is on one side of the cutoff only when its
whole date range is: one whose range straddles it (素问·至真要大论, 100–762, at 618) is in neither the past corpus nor
the future that checks predictions — a midpoint would put a possibly later text into the past.

Source rediscovery — a cited book is removed from the corpus; the lineage engine should re-infer it as a
cited-but-absent source, dated before its earliest citer.
"""

from __future__ import annotations

from typing import Any

from ..protocol.claims import ClaimRelation
from ..science import CooccurrenceGraph, infer_missing_sources, link_prediction
from ..tools.adapters import SenseOracle
from .base import EvalContext, SuiteResult

POSITIVE = (ClaimRelation.INDICATED_FOR, ClaimRelation.HERB_INDICATION, ClaimRelation.COMPOSED_OF)


def side(corpus: Any, passage: Any, cutoff: float) -> str:
    """``before`` / ``after`` / ``straddling`` the cutoff, by the passage's whole date range (undated: ``before``)."""
    rng = corpus.year_range(passage)
    return "before" if rng is None else rng.side_of(cutoff)


def _members(claim: Any) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated and not a.qualifiers.get("outcome")}


def _surfaces(claim: Any) -> set[str]:
    return {a.surface for a in claim.arguments}


def check_prediction(pred: Any, hypothesis: Any, future: list[Any], full: Any, derived: list[Any]) -> bool | None:
    """True / False when the texts after the cutoff decide the prediction; None when they cannot."""
    kind, subject, obj = pred.kind, pred.subject, pred.object
    if kind == "absent_after":
        return not any({subject, obj} <= _members(c) for c in future)
    if kind == "link_appears":
        if not any(subject in _members(c) for c in future):
            return None  # the later corpus never discusses the subject: undecidable
        return any({subject, obj} <= _members(c) for c in future)
    if kind == "cooccurrence_after":
        lhs = set(subject.split(","))
        relevant = [c for c in future if c.relation == ClaimRelation.INDICATED_FOR and lhs <= _members(c)]
        if not relevant:
            return None
        return sum(obj in _members(c) for c in relevant) * 2 >= len(relevant)
    if kind == "herb_retained":
        family = {t for t in hypothesis.terms if t.startswith("formula:")}
        core = {t for t in subject.split(",") if t.startswith("herb:")}
        children = [e.source_id for e in derived if e.target_id in family and e.source_id not in family]
        if not children or not core:
            return None
        compositions = {f: _members(c) for c in future if c.relation == ClaimRelation.COMPOSED_OF
                        for f in _members(c) if f in children}
        judged = [core <= herbs for herbs in compositions.values()]
        return all(judged) if judged else None
    if kind == "sense_shift" and obj:
        oracle = SenseOracle(full.pack, full.corpus)
        senses = [s for s in (oracle(c, subject) for c in future if subject in _members(c)) if s]
        if not senses:
            return None
        return max(set(senses), key=senses.count) == obj
    if kind == "renaming":
        uses = [c for c in future if subject in _members(c)]
        if not uses:
            return None
        return not any(a.surface == obj for c in uses for a in c.arguments if a.term_id == subject)  # the avoided name stays gone
    return None


def time_machine(ctx: EvalContext) -> SuiteResult:
    gold = ctx.gold("rediscovery").get("time_machine", {})
    full = ctx.default
    corpus = full.corpus
    kb_full = full.capabilities.get("knowledge")
    details, notes = [], []
    metrics: dict[str, Any] = {}
    for cutoff in gold.get("cutoffs", [1368]):
        sides = {p.id: side(corpus, p, cutoff) for p in corpus.passages()}
        pre = corpus.subset(pid for pid, where in sides.items() if where == "before")
        harness = ctx.harness(corpus=pre)
        session = ctx.run(harness, gold.get("question", "消渴的概念如何演变？"), session_id=f"tm{cutoff}",
                          focus_terms=gold.get("focus_terms", ["消渴"]))
        state = session.state
        leaked = [e.id for e in state.evidence.values() if sides.get(e.passage_id, "before") != "before"]
        future = [c for c in kb_full.claims() if sides.get(c.passage_id) == "after"]
        derived = [e for e in kb_full.lineage() if e.relation == "formula_derived_from" and e.source_passage
                   and sides.get(e.source_passage) == "after"]
        outcomes: dict[str, list[bool]] = {"survived": [], "other": []}
        for h in state.hypotheses.values():
            if h.status == "superseded":
                continue
            bucket = "survived" if h.status in ("survived", "expert_approved") else "other"
            for pred in h.predictions:
                verdict = check_prediction(pred, h, future, full, derived)
                details.append({"cutoff": cutoff, "hypothesis": h.id, "kind": h.kind, "status": h.status,
                                "prediction": pred.kind, "subject": pred.subject, "object": pred.object, "held": verdict})
                if verdict is not None:
                    outcomes[bucket].append(verdict)
        checkable = outcomes["survived"] + outcomes["other"]
        metrics[str(cutoff)] = {
            "pre_cutoff_passages": len(pre.passage_ids()),
            "straddling_passages": sum(1 for where in sides.values() if where == "straddling"),
            "post_cutoff_claims": len(future),
            "hypotheses": sum(1 for h in state.hypotheses.values() if h.status != "superseded"),
            "checkable_predictions": len(checkable),
            "prediction_accuracy": round(sum(checkable) / len(checkable), 4) if checkable else None,
            "survived_accuracy": round(sum(outcomes["survived"]) / len(outcomes["survived"]), 4) if outcomes["survived"] else None,
            "other_accuracy": round(sum(outcomes["other"]) / len(outcomes["other"]), 4) if outcomes["other"] else None,
            "evidence_leakage": len(leaked),
            "link_prediction": link_baselines(kb_full.claims(), corpus, cutoff),
        }
    notes.append("Link-level hold-out needs a large corpus: the demo corpus has very few links that first appear after "
                 "the cutoff, so the baseline table documents the protocol, not a result.")
    return SuiteResult("time_machine", metrics, details, notes)


def link_baselines(claims: list[Any], corpus: Any, cutoff: float, k: int = 20) -> dict[str, Any]:
    left = lambda t: t.split(":")[0] in ("symptom", "sign", "disease", "pattern", "pulse")  # noqa: E731
    right = lambda t: t.split(":")[0] in ("formula", "herb")  # noqa: E731
    where = lambda c: side(corpus, corpus.passage(c.passage_id), cutoff)  # noqa: E731
    pre = [c for c in claims if c.relation in POSITIVE and where(c) == "before"]
    post = [c for c in claims if c.relation in POSITIVE and where(c) == "after"]
    graph = CooccurrenceGraph([sorted(_members(c)) for c in pre])
    nodes = set(graph.nodes())
    truth = {(a, b) for c in post for a in _members(c) for b in _members(c)
             if left(a) and right(b) and a in nodes and b in nodes and not graph.linked(a, b)}
    table = {}
    for method in ("adamic_adar", "resource_allocation", "common_neighbors", "popularity", "random"):
        preds = link_prediction(graph, left=left, right=right, method=method, k=k, seed=1)
        table[method] = {"hits@k": sum((p["left"], p["right"]) in truth for p in preds), "k": k}
    return {"future_links": len(truth), "methods": table}


def source_rediscovery(ctx: EvalContext) -> SuiteResult:
    gold = ctx.gold("rediscovery").get("source_rediscovery", [])
    full = ctx.default
    corpus = full.corpus
    details = []
    for g in gold:
        book = g["book"]
        reduced = corpus.without_books([book])
        harness = ctx.harness(corpus=reduced)
        edges = harness.capabilities.get("knowledge").lineage()
        present = set(reduced.books)
        candidates = infer_missing_sources(edges, present, year_of_passage=lambda pid: reduced.year(reduced.passage(pid))
                                           if reduced.has_passage(pid) else None)
        ranked = [c["source"] for c in candidates]
        rank = ranked.index(book) + 1 if book in ranked else None
        true_date = corpus.books[book].composition.midpoint if corpus.books[book].composition else None
        cand = candidates[rank - 1] if rank else None
        consistent = bool(cand and cand["must_predate"] is not None and true_date is not None and true_date < cand["must_predate"])
        details.append({"held_out": book, "rank": rank, "candidates": ranked[:5], "must_predate": cand["must_predate"] if cand else None,
                        "true_date": true_date, "date_consistent": consistent, "evidence": cand["relations"] if cand else []})
    found = [d for d in details if d["rank"] is not None and d["rank"] <= 3]
    metrics = {"held_out": len(details), "recall@3": round(len(found) / len(details), 4) if details else None,
               "date_bound_consistent": round(sum(d["date_consistent"] for d in found) / len(found), 4) if found else None}
    return SuiteResult("source_rediscovery", metrics, details)
