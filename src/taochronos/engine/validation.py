"""Kernel validator tasks: gates, score cards, Discovery Score and the Elo tournament.

These run as ``validator:gates`` — deterministic harness code, not agents —
so an agent can never grade its own work.  Every result is an event.
"""

from __future__ import annotations

from typing import Any

from ..kernel.hooks import HookContext, HookPoint
from ..kernel.policy import Actor
from ..protocol.concepts import MODERN_EVIDENCE_DOMAINS
from ..protocol.confidence import ConfidenceVector
from ..protocol.events import EventType
from ..protocol.evidence import Stance
from ..protocol.hypothesis import NARROWING_AXIS, ScoreCard
from ..science.scoring import discovery_score, elo_tournament, novelty
from ..tools.adapters import author_clusters
from ..verification.provenance import verify_evidence
from ..verification.scope import scope_for

VALIDATOR = Actor.validator("gates")
ANACHRONISM = {"low": 0.1, "medium": 0.5, "high": 0.9, "unknown": 0.5}
G6_FACTOR = {"pass": 1.0, "warn": 0.7, "pending": 0.5, "fail": 0.2}
# how directly a hypothesis kind's evidence speaks to its statement: a text that states an indication
# is direct; claims that only share graph neighbours with it are indirect (link prediction)
DIRECTNESS = {"lost_knowledge": 1.0, "association_rule": 1.0, "formula_evolution": 0.9, "renaming": 0.9, "contradiction": 1.0,
              "historical_testimony": 0.9, "concept_drift": 0.8, "lost_source": 0.7, "hidden_association": 0.4,
              "cross_space_bridge": 0.6}


def validate_claims(harness: Any, state: Any, tx: Any) -> str:
    gates = harness.gates(state)
    results = []
    for claim in sorted(state.claims.values(), key=lambda c: c.id):
        results += [r.to_dict() for r in gates.evaluate_claim(claim)]
    for rec in sorted(state.evidence.values(), key=lambda e: e.id):
        if rec.evidence_domain in MODERN_EVIDENCE_DOMAINS or rec.id in state.gates:
            continue
        results += [r.to_dict() for r in gates.evaluate_evidence(rec)]
    if results:
        tx.emit(EventType.GATE_EVALUATED, {"results": results})
    fails = sum(1 for r in results if r["status"] == "fail")
    warns = sum(1 for r in results if r["status"] == "warn")
    return f"{len(results)} gate results for {len(state.claims)} claims; fail {fails}, warn {warns}"


def validate_hypotheses(harness: Any, state: Any, tx: Any) -> str:
    gates = harness.gates(state)
    results = []
    for rec in sorted(state.evidence.values(), key=lambda e: e.id):
        if rec.evidence_domain in MODERN_EVIDENCE_DOMAINS or rec.id in state.gates or rec.id in state.retractions:
            continue
        results += [r.to_dict() for r in gates.evaluate_evidence(rec)]
    summary: dict[str, int] = {}
    for h in sorted(state.hypotheses.values(), key=lambda h: h.id):
        if h.status == "superseded":
            continue
        version = h.version()
        for r in gates.evaluate_hypothesis(h, state):
            if r.gate == "G7":  # the expert's gate is the expert's: a validator never writes it
                continue
            results.append(r.replace(subject_version=version).to_dict())
            if r.gate in ("G5", "G6"):
                key = f"{r.gate}:{r.status}"
                summary[key] = summary.get(key, 0) + 1
    if results:
        tx.emit(EventType.GATE_EVALUATED, {"results": results})
    return f"{len(results)} gate results; " + ", ".join(f"{k}×{v}" for k, v in sorted(summary.items()))


# ------------------------------------------------------------------ objections
def _support(state: Any, h: Any) -> list[Any]:
    return [state.evidence[e] for e in h.supporting_evidence if e in state.evidence and e not in state.retractions]


def rerun_check(harness: Any, state: Any, h: Any, check: str) -> dict[str, Any] | None:
    """Re-run a check mechanically on the hypothesis as it stands; None when the check has no mechanical re-run
    (then only its own conditions — or, for an interpretive objection, an expert — can close it)."""
    support = _support(state, h)
    if check == "provenance":
        problems = [f"{r.id}: {x}" for r in support for x in verify_evidence(r, harness.corpus)]
        if not support:
            problems.append("no supporting evidence left")
        return {"check": check, "status": "fail" if problems else "pass",
                "detail": "; ".join(problems[:3]) or f"{len(support)} supporting quotes verbatim at their spans"}
    if check == "anachronism":
        verdict = harness.hooks.run(HookContext(HookPoint.AFTER_HYPOTHESIS, subject=h, actor=VALIDATOR))
        return {"check": check, "status": "pass" if verdict.allow else "fail", "detail": verdict.reason or "anachronism guard passes"}
    if check == "scope":
        scope = scope_for(state, "agent")
        outside = [r.passage_id for r in support if scope is not None and not scope.permits(r.passage_id)]
        return {"check": check, "status": "fail" if outside else "pass",
                "detail": f"{len(outside)} supporting passage(s) outside the exploration scope" if outside else "all evidence in scope"}
    if check == "semantic_support":
        bad = []
        for r in support:
            claim = state.claims.get(r.claim_id or "")
            if claim is not None and (claim.support or {}).get("verdict") in ("contradicts",):
                bad.append(claim.id)
        return {"check": check, "status": "fail" if bad else "pass",
                "detail": f"claims whose quote does not bear their relation: {', '.join(bad[:3])}" if bad else "supporting claims are borne by their quotes"}
    if check in ("single_source", "transcription_dependence"):
        need = state.goal.required_evidence.min_independent_sources if state.goal else 2
        cluster = author_clusters(harness.corpus, list(state.lineage.values()))
        books = sorted({r.book_id for r in support})
        clusters = sorted({cluster(b) for b in books})
        ok = len(clusters) >= need if check == "single_source" else len(clusters) == len(books) or len(clusters) >= need
        return {"check": check, "status": "pass" if ok else "fail",
                "detail": f"{len(clusters)} independent source cluster(s) over {len(books)} book(s) (need {need})"}
    return None


def adjudicate_objections(harness: Any, state: Any, tx: Any) -> str:
    """Close what can be closed, and only that.

    * a **hard** objection closes when a re-run of its check passes (and in no other way);
    * an **interpretive** one closes when its proposal is verified: a narrowing (the revision carries the qualifier on
      the objection's axis) or new evidence (recorded, not retracted, supporting this hypothesis — and the check re-run
      with it passes); a proposal that rests on a rationale alone waits for an expert.
    Everything left open is counted in G6 and listed by the contract evaluation."""
    closed = rejected = waiting = 0
    for h in sorted(state.hypotheses.values(), key=lambda x: x.id):
        if h.status in ("superseded",):
            continue
        reviews = state.reviews_for(h.id)
        if not reviews:
            continue
        latest = max(reviews, key=lambda r: (r.round, r.id))
        for o in latest.objections:
            if not o.is_open:
                continue
            payload = {"hypothesis_id": h.id, "review_id": latest.id, "objection_id": o.id}
            if o.hard:
                rerun = rerun_check(harness, state, h, o.check)
                if rerun is not None and rerun["status"] == "pass":
                    tx.emit(EventType.OBJECTION_CLOSED, {**payload, "method": "validator_rerun", "rerun": rerun,
                                                         "resolution": f"re-run passes: {rerun['detail']}"})
                    closed += 1
                elif o.status == "resolution_proposed":
                    rejected += 1  # a proposal cannot close a hard objection whose check still fails
                continue
            if o.status != "resolution_proposed":
                continue
            basis = (o.proposal or {}).get("basis")
            if basis == "qualifier":
                axis = NARROWING_AXIS.get(o.check)
                offered = (o.proposal or {}).get("qualifier") or {}
                if axis and h.qualifiers.get(axis) is not None and (not offered or offered.get(axis) == h.qualifiers[axis]) \
                        and h.parent_id and h.revision_kind != "substantive":
                    tx.emit(EventType.OBJECTION_CLOSED, {**payload, "method": "scope_restriction",
                                                         "resolution": f"claim narrowed by revision: {axis}={h.qualifiers[axis]}"})
                    closed += 1
                else:
                    rejected += 1
            elif basis == "new_evidence":
                ids = [e for e in (o.proposal or {}).get("evidence_ids", []) if e in state.evidence and e not in state.retractions]
                good = [e for e in ids if state.evidence[e].hypothesis_id == h.id and state.evidence[e].stance == Stance.SUPPORTS
                        and not verify_evidence(state.evidence[e], harness.corpus)]
                rerun = rerun_check(harness, state, h, o.check) if good else None
                if good and rerun is not None and rerun["status"] == "pass":
                    tx.emit(EventType.OBJECTION_CLOSED, {**payload, "method": "new_evidence", "evidence_ids": good, "rerun": rerun,
                                                         "resolution": f"new evidence ({len(good)}); re-run passes: {rerun['detail']}"})
                    closed += 1
                else:
                    rejected += 1
            else:
                waiting += 1  # a rationale is for an expert to weigh
    return f"objections: {closed} closed by validator, {rejected} proposals not borne out, {waiting} awaiting an expert"


def _gate(state: Any, hid: str, gate: str) -> Any:
    return state.gates.get(hid, {}).get(gate)


def score_card(h: Any, state: Any, known: list[dict]) -> tuple[ScoreCard, dict[str, float], ConfidenceVector, float, str]:
    support = [state.evidence[e] for e in h.supporting_evidence if e in state.evidence]
    counter = [state.evidence[e] for e in h.contradictory_evidence if e in state.evidence]
    textual = [r.confidence.textual for r in support if r.confidence.textual is not None]
    philological = [r.confidence.philological for r in support if r.confidence.philological is not None]
    g5 = _gate(state, h.id, "G5")
    g6 = _gate(state, h.id, "G6")
    directness = DIRECTNESS.get(h.kind, 0.7)
    # indirect evidence replicates the *paths*, not the statement: discount replication too
    replication = (min(1.0, g5.score) if g5 is not None and g5.score is not None else 0.0) * min(1.0, directness + 0.2)
    nov, rationale = novelty(h.terms, known)
    temporal = h.confidence.temporal if h.confidence.temporal is not None else 0.5
    counter_ratio = len(counter) / (len(support) + len(counter)) if (support or counter) else 0.0
    g6_status = g6.status if g6 is not None else "pending"
    card = ScoreCard(
        textual_support=round(min(1.0, len(support) / 3) * (sum(textual) / len(textual) if textual else 0.5) * directness, 4),
        cross_source_replication=round(replication, 4),
        philological_robustness=round(sum(philological) / len(philological), 4) if philological else 0.5,
        temporal_coherence=round(temporal, 4),
        novelty=nov,
        explanatory_power=round(min(1.0, 0.3 + 0.1 * len(support) + 0.2 * len(h.observation_ids)), 4),
        counterevidence_robustness=round((1.0 - counter_ratio) * G6_FACTOR.get(g6_status, 0.5), 4),
        testability=1.0 if h.predictions else (0.5 if h.testable_prediction else 0.2),
        anachronism_risk=ANACHRONISM.get(h.anachronism_risk, 0.5),
    )
    if h.status in ("survived", "expert_approved"):
        survival = 1.0 if h.generation == 0 else 0.7
    elif h.status == "needs_revision":
        survival = 0.4
    elif h.status in ("rejected", "expert_rejected"):
        survival = 0.0
    else:
        survival = 0.3
    components = {
        "E": round(card.textual_support * card.philological_robustness, 4),
        "N": nov,
        "R": card.cross_source_replication,
        "T": card.temporal_coherence,
        "F": survival,
        "A": card.anachronism_risk,
    }
    modern = [e for e in state.evidence.values() if e.hypothesis_id == h.id and e.evidence_domain in MODERN_EVIDENCE_DOMAINS]
    confidence = h.confidence.replace(
        cross_source=card.cross_source_replication,
        contradiction_penalty=round(min(0.5, 0.1 * len(counter)), 4),
        modern_mapping=(0.5 if modern else None) if h.space.value in ("modern_tcm", "biomedical") else None,
    )
    return card, components, confidence, nov, rationale


def score_hypotheses(harness: Any, state: Any, tx: Any, round_: int) -> str:
    known = harness.pack.known_findings
    weights = (harness.profile.discovery or {}).get("weights")
    active = sorted((h for h in state.hypotheses.values() if h.status not in ("superseded",)), key=lambda h: h.id)
    strength: dict[str, float] = {}
    for h in active:
        card, components, confidence, nov, rationale = score_card(h, state, known)
        d = discovery_score(components, weights)
        tx.emit(EventType.HYPOTHESIS_SCORED, {"hypothesis_id": h.id, "scores": card.to_dict(), "discovery_score": d,
                                              "components": components, "confidence": confidence.to_dict(), "novelty": nov,
                                              "novelty_rationale": rationale})
        if h.status not in ("rejected", "expert_rejected"):
            strength[h.id] = card.weighted()
    if len(strength) >= 2:
        elo, matches = elo_tournament(strength, rounds=3, seed=round_, start={hid: state.hypotheses[hid].elo for hid in strength})
        tx.emit(EventType.HYPOTHESIS_RANKED, {"elo": elo, "matches": matches[:200], "round": round_})
    return f"{len(active)} hypotheses scored; {len(strength)} in the tournament"


def counter_evidence(state: Any, hid: str) -> list[Any]:
    return [e for e in state.evidence.values() if e.hypothesis_id == hid and e.stance == Stance.CONTRADICTS]
