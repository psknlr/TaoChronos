"""Evaluate the research contract: execution is not acceptance.

A validator reads the research object and judges every non-superseded hypothesis against the contract's acceptance
criteria, on the hypothesis *as it now stands* (a gate computed on an earlier version does not count).  Each criterion
records who judged it, what it observed, what was required and what the hypothesis becomes if it fails.  The research
as a whole is then ``research_accepted``, ``needs_expert``, ``inconclusive`` or ``budget_exhausted`` — never
"completed" merely because no task was left.
"""

from __future__ import annotations

from typing import Any

from ..protocol.contract import ContractEvaluation, CriterionResult, HypothesisAcceptance

JUDGE = "validator:contract"
HUMAN = "human"


def _latest_review(state: Any, hid: str) -> Any:
    reviews = state.reviews_for(hid)
    return max(reviews, key=lambda r: (r.round, r.id)) if reviews else None


def _support(state: Any, h: Any) -> list[Any]:
    return [state.evidence[e] for e in h.supporting_evidence if e in state.evidence and e not in state.retractions]


def judge_hypothesis(state: Any, h: Any) -> HypothesisAcceptance:
    goal = state.goal
    acc = goal.acceptance
    version = h.version()
    crit: list[CriterionResult] = []

    def add(cid: str, ok: bool | None, observed: str, required: str, *, judge: str = JUDGE, failure: str = "inconclusive") -> None:
        status = "pending" if ok is None else ("pass" if ok else "fail")
        crit.append(CriterionResult(id=cid, status=status, judge=judge, observed=observed, required=required, failure_state=failure))

    if h.status in ("rejected", "expert_rejected"):
        add("falsification", False, f"status {h.status}", "not rejected", failure="rejected")
        return HypothesisAcceptance(hypothesis_id=h.id, version=version, status="rejected", criteria=crit)

    support = _support(state, h)
    need = goal.required_evidence.min_supporting_evidence
    add("min_supporting_evidence", len(support) >= need, f"{len(support)} verified supporting record(s)", f"≥ {need}")

    if acc.semantic_support_checked:
        bad, weak = [], []
        for r in support:
            claim = state.claims.get(r.claim_id or "")
            if claim is None:
                continue
            verdict = (claim.support or {}).get("verdict")
            if verdict == "contradicts" or claim.stance == "rejected":
                bad.append(claim.id)
            elif verdict in ("insufficient", "ambiguous"):
                weak.append(claim.id)
        if bad:
            add("semantic_support", False, f"{len(bad)} supporting claim(s) contradicted by their quote or rejected by their author",
                "every supporting claim borne by its quote")
        elif weak:
            add("semantic_support", False, f"{len(weak)} supporting claim(s) not clearly stated by their quote",
                "every supporting claim borne by its quote", failure="needs_expert")
        else:
            add("semantic_support", True, "every supporting claim is stated by its quote", "every supporting claim borne by its quote")

    gates = state.gates.get(h.id, {})
    if acc.source_dependence_checked:
        g5 = gates.get("G5")
        current = g5 is not None and (not g5.subject_version or g5.subject_version == version)
        add("source_dependence", bool(current and g5.status == "pass"),
            f"G5 {g5.status if g5 else 'missing'}{'' if current else ' (not on the current version)'}: {g5.details if g5 else ''}",
            f"≥ {goal.required_evidence.min_independent_sources} independent source families, on the current version")

    latest = _latest_review(state, h.id)
    hard = [o for o in (latest.objections if latest else []) if o.is_open and o.hard]
    critical = [o for o in (latest.objections if latest else []) if o.is_open and o.severity == "critical"]
    add("falsification_review", latest is not None, "reviewed" if latest else "no review", "a skeptic review")
    add("unresolved_hard_objections", len(hard) <= acc.max_unresolved_hard_objections,
        f"{len(hard)} open hard objection(s)" + (f": {', '.join(o.check for o in hard[:3])}" if hard else ""),
        f"≤ {acc.max_unresolved_hard_objections}")
    add("unresolved_critical", len(critical) <= acc.max_unresolved_critical, f"{len(critical)} open critical objection(s)",
        f"≤ {acc.max_unresolved_critical}")

    warrant = state.warrants.get(h.warrant_id or "") if h.warrant_id else None
    if acc.alternatives_required:
        if warrant is None or warrant.get("hypothesis_version") != version:
            add("alternatives_addressed", False, "no warrant for the current version", "the discovery type's rival explanations addressed")
        else:
            unaddressed = [c["id"] for c in warrant.get("competing", []) if c.get("status") == "unaddressed"]
            open_ = [c["id"] for c in warrant.get("competing", []) if c.get("status") == "open"]  # considered, reported, not excluded
            add("alternatives_addressed", not unaddressed,
                (f"unaddressed: {', '.join(unaddressed)}" if unaddressed else "all addressed") + (f"; open: {', '.join(open_)}" if open_ else ""),
                "every rival explanation of the discovery type excluded or stated as open")

    if acc.current_version_gates:
        strict = set(goal.stop.strict_gates)
        missing, stale, failing = [], [], []
        for gate in goal.required_validation:
            if gate in ("G7",):
                continue
            r = gates.get(gate)
            if r is None:
                missing.append(gate)
            elif r.subject_version and r.subject_version != version:
                stale.append(gate)
            elif r.status not in (("pass", "not_applicable") if gate in strict else ("pass", "warn", "not_applicable")):
                failing.append(f"{gate}={r.status}")
        add("current_version_gates", not (missing or stale or failing),
            "; ".join(x for x in (f"missing {missing}" if missing else "", f"stale {stale}" if stale else "",
                                  f"failing {failing}" if failing else "") if x) or "all required gates pass on this version",
            f"{', '.join(g for g in goal.required_validation if g != 'G7')} on the current version (strict: {', '.join(sorted(strict))})")

    confirmation_set = bool(state.corpus is not None and state.corpus.confirmation_passage_ids)
    if acc.confirmation_required or confirmation_set:
        conf = (h.confirmation or {}).get("status")
        required = "predictions hold on material withheld from exploration"
        if conf == "confirmed":
            add("confirmation", True, "every decided prediction holds on the withheld material", required)
        elif conf == "refuted":
            add("confirmation", False, "a prediction fails on the withheld material", required)
        elif acc.confirmation_required:
            add("confirmation", False, f"confirmation {conf or 'not run'}", required)
        else:  # the withheld material cannot decide it, and the contract does not demand it: reported, not blocking
            crit.append(CriterionResult(id="confirmation", status="not_applicable", judge=JUDGE,
                                        observed=f"confirmation {conf or 'not run'}", required=required))

    if acc.expert_review_required_for_publication:
        g7 = state.gates.get(h.id, {}).get("G7")
        add("expert_review", None if g7 is None else g7.status == "pass", f"G7 {g7.status if g7 else 'pending'}", "an expert's approval",
            judge=HUMAN, failure="needs_expert")

    machine = [c for c in crit if c.judge == JUDGE]
    if any(c.status == "fail" and c.failure_state == "rejected" for c in crit):
        status = "rejected"
    elif any(c.status == "fail" and c.failure_state == "inconclusive" for c in machine):
        status = "inconclusive"
    elif any(c.status in ("fail", "pending") for c in crit):
        status = "needs_expert"
    else:
        status = "accepted"
    return HypothesisAcceptance(hypothesis_id=h.id, version=version, status=status, criteria=crit)


def _outputs(state: Any, judged: list[HypothesisAcceptance]) -> dict[str, bool]:
    live = [state.hypotheses[j.hypothesis_id] for j in judged if j.status != "rejected"]
    return {
        "candidate_hypotheses": bool(state.hypotheses),
        "supporting_and_counter_evidence": bool(live) and all(state.reviews_for(h.id) and _support(state, h) for h in live),
        "alternative_explanations": bool(live) and all(h.warrant_id in state.warrants for h in live),
        "reproducibility_bundle": state.run_manifest is not None,
    }


def evaluate_contract(state: Any, *, execution: str, at_seq: int = 0) -> ContractEvaluation:
    goal = state.goal
    judged = [judge_hypothesis(state, h) for h in sorted(state.hypotheses.values(), key=lambda x: x.id) if h.status != "superseded"]
    outputs = {k: v for k, v in _outputs(state, judged).items() if k in goal.required_outputs}
    missing = [k for k, v in outputs.items() if not v]
    reasons: list[str] = []
    accepted = [j for j in judged if j.status == "accepted"]
    waiting = [j for j in judged if j.status == "needs_expert"]
    human = list(goal.acceptance_criteria)
    if missing:
        reasons.append(f"required outputs missing: {', '.join(missing)}")
    if accepted and not missing and not human:
        status = "research_accepted"
        reasons.append(f"{len(accepted)} hypothesis(es) meet every criterion, the expert's included")
    elif (accepted or waiting) and not missing:
        status = "needs_expert"
        if waiting:
            reasons.append(f"{len(waiting)} hypothesis(es) meet the machine criteria and wait for an expert")
        if human:
            reasons.append(f"{len(human)} criterion(s) of the contract can only be judged by a person")
    elif execution == "budget_exhausted":
        status = "budget_exhausted"
        reasons.append("the budget ran out before any hypothesis met the contract")
    else:
        status = "inconclusive"
        reasons.append("no hypothesis meets the contract" if judged else "no hypothesis was produced")
    return ContractEvaluation(status=status, execution=execution, hypotheses=judged, outputs=outputs, human_criteria=human,
                              reasons=reasons, at_seq=at_seq, versions={j.hypothesis_id: j.version for j in judged})
