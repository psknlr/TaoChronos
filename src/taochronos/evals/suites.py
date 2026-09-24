"""TaoChronos-Eval suites: philology, claims, provenance, hallucination, contradiction, lineage,
temporal reasoning, anachronism and crash recovery."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from ..kernel.hooks import HookContext, HookPoint
from ..kernel.policy import Actor
from ..kernel.store import FaultInjectingStore, MemoryEventStore, SimulatedCrash
from ..protocol.concepts import KnowledgeSpace
from ..protocol.evidence import EvidenceRecord
from ..protocol.hypothesis import Hypothesis
from ..science.contradiction import classify_passages
from ..tools.adapters import contradiction_context
from ..verification.hooks import anachronism_guard
from ..verification.provenance import find_quote, provenance_chain, verify_claim, verify_evidence
from .base import EvalContext, SuiteResult, accuracy, confusion, macro_f1, prf


# ================================================================ PhilologyEval
def philology(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    gold = ctx.gold("philology")
    ph, corpus, pack = h.philology, h.corpus, h.pack
    details = []
    for g in gold.get("contested", []):
        a = ph.assess(corpus.passage(g["passage"]))
        spans = [c for c in a.contested if g["span_text"] in c.base or c.base in g["span_text"]]
        readings = {o.reading for c in spans for o in c.options}
        base_p = min((c.base_probability() for c in spans), default=None)
        checks = {
            "span_found": bool(spans),
            "readings_kept": all(any(r in x or x in r for x in readings) for r in g.get("expect_readings", [])),
            "base_not_forced": base_p is not None and base_p <= g["max_base_probability"],
            "uncertain_mass": all(c.uncertain >= g["min_uncertain"] for c in spans) if spans else False,
        }
        details.append({"case": f"contested:{g['passage']}", "base_probability": base_p, **checks, "pass": all(checks.values())})
    for pid in gold.get("no_contest", []):
        ok = not ph.assess(corpus.passage(pid)).contested
        details.append({"case": f"no_contest:{pid}", "pass": ok})
    for n in gold.get("normalization", []):
        ok = n["contains"] in pack.variants.normalize_text(n["text"])
        details.append({"case": f"normalize:{n['text']}", "pass": ok})
    passed = sum(1 for d in details if d["pass"])
    return SuiteResult("philology", {"cases": len(details), "pass_rate": round(passed / len(details), 4) if details else None}, details)


# ================================================================ ClaimEval
def _members(claim: Any, negated: bool) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and a.negated == negated and not a.qualifiers.get("outcome")}


def claims(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    gold = ctx.gold("claims")
    extractor = h.capabilities.get("extractor")
    tp = fp = fn = 0
    details = []
    relation_hits: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    provenance_ok = provenance_all = 0
    for entry in gold.get("passages", []):
        passage = h.corpus.passage(entry["passage"])
        extracted = extractor.extract(passage, h.philology.assess(passage))
        for c in extracted:
            provenance_all += 1
            provenance_ok += not verify_claim(c, h.corpus, h.pack.variants.normalize_text)
        used: set[str] = set()
        missed = []
        for g in entry["claims"]:
            relation_hits[g["relation"]][1] += 1
            match = next((c for c in extracted if c.id not in used and c.relation.value == g["relation"]
                          and set(g.get("terms", [])) <= _members(c, False) and set(g.get("negated", [])) <= _members(c, True)), None)
            if match is None:
                fn += 1
                missed.append(g)
            else:
                tp += 1
                used.add(match.id)
                relation_hits[g["relation"]][0] += 1
        spurious = [c for c in extracted if c.id not in used]
        fp += len(spurious)
        details.append({"passage": entry["passage"], "gold": len(entry["claims"]), "extracted": len(extracted),
                        "missed": [f"{m['relation']}{m.get('terms', [])}" for m in missed],
                        "spurious": [f"{c.relation.value}:{c.quote[:24]}" for c in spurious]})
    metrics = prf(tp, fp, fn)
    metrics["recall_by_relation"] = {r: round(v[0] / v[1], 3) for r, v in sorted(relation_hits.items())}
    metrics["provenance_pass_rate"] = round(provenance_ok / provenance_all, 4) if provenance_all else None
    return SuiteResult("claims", metrics, details)


# ================================================================ ProvenanceEval
def provenance(ctx: EvalContext) -> SuiteResult:
    h, session = ctx.pipeline()
    state = session.state
    normalize = h.pack.variants.normalize_text
    claim_ok = sum(1 for c in state.claims.values() if not verify_claim(c, h.corpus, normalize))
    textual = [e for e in state.evidence.values() if e.book_id != "modern-literature"]
    evidence_ok = sum(1 for e in textual if not verify_evidence(e, h.corpus))
    hyps = [x for x in state.hypotheses.values() if x.status != "superseded"]
    with_support = sum(1 for x in hyps if x.supporting_evidence)
    depth, available = [], defaultdict(int)
    for x in hyps:
        chain = provenance_chain(x.id, state, h.corpus)
        depth.append(sum(1 for c in chain if c["available"]))
        for c in chain:
            available[c["level"]] += int(c["available"])
    metrics = {
        "claims_verbatim": round(claim_ok / len(state.claims), 4) if state.claims else None,
        "evidence_verbatim": round(evidence_ok / len(textual), 4) if textual else None,
        "hypotheses_with_evidence": round(with_support / len(hyps), 4) if hyps else None,
        "mean_chain_depth": round(sum(depth) / len(depth), 2) if depth else None,
        "chain_level_availability": {k: round(v / len(hyps), 3) for k, v in available.items()} if hyps else {},
    }
    notes = ["Page / line / region / image levels are unavailable because the demo corpus has no page images; "
             "the chain reports them as unavailable rather than inventing them."]
    return SuiteResult("provenance", metrics, notes=notes)


# ================================================================ HallucinationEval
def hallucination(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    corpus, normalize = h.corpus, h.pack.variants.normalize_text
    rng = random.Random(7)
    passages = [p for p in corpus.passages() if len(p.text) >= 24]
    rng.shuffle(passages)
    alphabet = sorted({ch for p in corpus.passages() for ch in p.text if "一" <= ch <= "鿿"})
    sample = passages[: 20 if ctx.quick else 60]
    stats = {"verbatim_found": 0, "verbatim": 0, "perturbed_flagged": 0, "perturbed": 0, "fabricated_flagged": 0,
             "fabricated": 0, "span_flagged": 0, "span": 0}
    for p in sample:
        n = rng.randint(8, min(20, len(p.text) - 1))
        start = rng.randint(0, len(p.text) - n)
        quote = p.text[start: start + n]
        stats["verbatim"] += 1
        stats["verbatim_found"] += bool(find_quote(corpus, quote, normalize))
        i = rng.randrange(len(quote))
        replacement = next(ch for ch in rng.sample(alphabet, 40) if ch not in p.text and normalize(ch) != normalize(quote[i]))
        perturbed = quote[:i] + replacement + quote[i + 1:]
        stats["perturbed"] += 1
        stats["perturbed_flagged"] += not find_quote(corpus, perturbed, normalize)
        fabricated = "".join(rng.sample(alphabet, n))
        stats["fabricated"] += 1
        stats["fabricated_flagged"] += not find_quote(corpus, fabricated, normalize)
        shift = min(len(p.text) - n, start + 3) if start + 3 <= len(p.text) - n else max(0, start - 3)
        if shift != start:
            rec = EvidenceRecord(id="evd_test", passage_id=p.id, book_id=p.book_id, locator=p.locator, quote=quote, start=shift,
                                 end=shift + n, agent="eval", retrieval_method="test")
            stats["span"] += 1
            stats["span_flagged"] += bool(verify_evidence(rec, corpus))
    variant_ok = bool(find_quote(corpus, "横连膜原", normalize))  # a legitimate variant spelling is not a fabrication
    metrics = {
        "verbatim_recall": round(stats["verbatim_found"] / stats["verbatim"], 4),
        "perturbed_detection": round(stats["perturbed_flagged"] / stats["perturbed"], 4),
        "fabricated_detection": round(stats["fabricated_flagged"] / stats["fabricated"], 4),
        "wrong_span_detection": round(stats["span_flagged"] / stats["span"], 4) if stats["span"] else None,
        "variant_spelling_accepted": variant_ok,
        "samples": stats["verbatim"],
    }
    return SuiteResult("hallucination", metrics, notes=[
        "perturbed = one character replaced; fabricated = random characters; wrong span = verbatim quote at shifted offsets"])


# ================================================================ ContradictionEval
def contradiction(ctx: EvalContext, *, sense: bool = True, philology_aware: bool = True) -> SuiteResult:
    h = ctx.default
    gold = ctx.gold("contradictions")
    kb = h.capabilities.get("knowledge")
    by_passage: dict[str, list] = defaultdict(list)
    for c in kb.claims():
        by_passage[c.passage_id].append(c)
    cctx = contradiction_context(h.pack, h.corpus, h.philology, lineage=kb.lineage())
    if not sense:
        cctx.sense_fn = lambda c, t: None
    if not philology_aware:
        cctx.contested_fn = lambda *a: False
    pairs, details = [], []
    for g in gold.get("pairs", []):
        a, b = by_passage.get(g["a"], []), by_passage.get(g["b"], [])
        verdict = classify_passages(a, b if g["a"] != g["b"] else a, cctx, g["a"], g["b"])
        pairs.append((g["label"], verdict["label"]))
        details.append({"a": g["a"], "b": g["b"], "gold": g["label"], "predicted": verdict["label"], "type": verdict.get("type"),
                        "correct": g["label"] == verdict["label"]})
    metrics = {"pairs": len(pairs), "accuracy": accuracy(pairs), "macro_f1": macro_f1(pairs), "confusion": confusion(pairs)}
    return SuiteResult("contradiction", metrics, details)


# ================================================================ LineageEval
def lineage(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    gold = ctx.gold("lineage")
    predicted = {(e.relation, e.source_id, e.target_id) for e in h.capabilities.get("knowledge").lineage()}
    pos = {(g["relation"], g["source"], g["target"]) for g in gold.get("positive", [])}
    neg = {(g["relation"], g["source"], g["target"]) for g in gold.get("negative", [])}
    tp = len(predicted & pos)
    fp = len(predicted & neg)
    fn = len(pos - predicted)
    metrics = prf(tp, fp, fn)
    metrics["unjudged_predictions"] = len(predicted - pos - neg)
    details = [{"edge": list(e), "found": e in predicted, "gold": "positive"} for e in sorted(pos)]
    details += [{"edge": list(e), "found": e in predicted, "gold": "negative"} for e in sorted(neg)]
    return SuiteResult("lineage", metrics, details)


# ================================================================ TemporalEval
def temporal(ctx: EvalContext, *, routes: list[str] | None = None, name: str = "temporal") -> SuiteResult:
    h = ctx.default
    gold = ctx.gold("temporal")
    periods = h.pack.periods
    retriever = h.capabilities.get("retriever")
    details = []
    parsed_ok = 0
    for g in gold.get("constraints", []):
        got = periods.parse_constraint(h.pack.variants.normalize_text(g["query"]))
        ok = tuple(got) == (g["after"], g["before"])
        parsed_ok += ok
        details.append({"case": f"parse:{g['query']}", "expected": [g["after"], g["before"]], "got": list(got), "pass": ok})
    earliest_ok = 0
    for g in gold.get("earliest", []):
        _, hits = retriever.search(g["query"], k=5, routes=routes)
        top = hits[0] if hits else None
        if top is None:
            ok = False
        elif "passage" in g:
            ok = top.passage_id == g["passage"]
        else:
            ok = h.corpus.passage(top.passage_id).book_id == g["book"]
        earliest_ok += ok
        details.append({"case": f"earliest:{g['query']}", "expected": g.get("passage") or g.get("book"),
                        "got": top.passage_id if top else None, "pass": ok})
    violations = 0
    for g in gold.get("leakage", []):
        q, hits = retriever.search(g["query"], k=20, routes=routes)
        for hit in hits:
            y = hit.year
            if (q.after is not None and (y is None or y < q.after)) or (q.before is not None and (y is None or y >= q.before)):
                violations += 1
    n_c, n_e = len(gold.get("constraints", [])), len(gold.get("earliest", []))
    metrics = {"constraint_accuracy": round(parsed_ok / n_c, 4) if n_c else None,
               "earliest_accuracy": round(earliest_ok / n_e, 4) if n_e else None, "period_leakage": violations}
    return SuiteResult(name, metrics, details)


# ================================================================ AnachronismEval
def anachronism(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    gold = ctx.gold("anachronism")
    terminology = h.pack.terminology
    labels = [c.label for c in terminology.concepts.values()]
    guard = anachronism_guard(labels, gold.get("forbidden_assumptions", []))
    pairs, details = [], []
    for g in gold.get("statements", []):
        subject = Hypothesis(id="hyp_eval", statement=g["text"], kind="eval", space=KnowledgeSpace.COMPUTATIONAL_HYPOTHESIS)
        result = guard(HookContext(HookPoint.AFTER_HYPOTHESIS, subject=subject, actor=Actor(id="agent:eval", role="eval")))
        blocked = bool(result and not result.allow)
        pairs.append((g["blocked"], blocked))
        details.append({"text": g["text"], "expected_blocked": g["blocked"], "blocked": blocked,
                        "reason": result.reason if result else ""})
    mapping_pairs = []
    for m in gold.get("mappings", []):
        got = terminology.propose_mapping(m["sense"], m["concept"]).relation.value
        mapping_pairs.append((m["relation"], got))
        details.append({"mapping": f"{m['sense']} → {m['concept']}", "expected": m["relation"], "got": got})
    guard_ok = True
    for m in gold.get("agent_equivalence", []):
        payload = {"relation": "equivalent", "sense_id": m["sense"], "concept_id": m["concept"]}
        by_agent = guard(HookContext(HookPoint.BEFORE_GRAPH_WRITE, subject=payload, actor=Actor(id="agent:ontologist", role="ontologist")))
        by_human = guard(HookContext(HookPoint.BEFORE_GRAPH_WRITE, subject=payload, actor=Actor.human("expert")))
        guard_ok &= bool(by_agent and not by_agent.allow) and (by_human is None or by_human.allow)
    tp = sum(1 for g, p in pairs if g and p)
    fp = sum(1 for g, p in pairs if not g and p)
    fn = sum(1 for g, p in pairs if g and not p)
    metrics = {"statement_accuracy": accuracy(pairs), "block": prf(tp, fp, fn),
               "mapping_accuracy": accuracy(mapping_pairs), "agent_equivalence_blocked": guard_ok}
    return SuiteResult("anachronism", metrics, details)


# ================================================================ RecoveryEval
def recovery(ctx: EvalContext) -> SuiteResult:
    reference = ctx.run(ctx.harness(), session_id="rec")
    ref_hash = reference.state.state_hash()
    verify = reference.verify()
    points = [5, 15] if ctx.quick else [3, 9, 17, 25]
    details = []
    for n in points:
        inner = MemoryEventStore()
        try:
            ctx.run(ctx.harness(store=FaultInjectingStore(inner, crash_on_batch=n)), session_id="rec")
            details.append({"crash_batch": n, "crashed": False})
            continue
        except SimulatedCrash:
            pass
        h = ctx.harness(store=inner)
        engine = h.engine()
        session = engine.open("rec")
        dropped = session.recovery.discarded_events if session.recovery else 0
        engine.run(session)
        details.append({"crash_batch": n, "crashed": True, "discarded_events": dropped,
                        "same_scientific_state": session.state.state_hash() == ref_hash, "status": session.state.status})
    crashed = [d for d in details if d.get("crashed")]
    metrics = {
        "crash_points": len(crashed),
        "recovery_success_rate": round(sum(d["same_scientific_state"] for d in crashed) / len(crashed), 4) if crashed else None,
        "replay_consistent": verify["consistent"],
        "checkpoint_mismatches": len(verify["checkpoint_mismatches"]),
    }
    if not ctx.quick:
        rerun = ctx.run(ctx.harness(), session_id="rec")
        parallel = ctx.run(ctx.harness(overrides={"context": {"max_parallel_agents": 4}}), session_id="rec")
        metrics["deterministic_rerun"] = rerun.state.state_hash() == ref_hash
        metrics["parallel_equivalent"] = parallel.state.state_hash() == ref_hash
    return SuiteResult("recovery", metrics, details)
