"""Confirmation: re-test what exploration found on material it never saw.

When the contract keeps back a confirmation set (whole source families of the same era, withheld from every agent), a
validator reads it once exploration is over: it extracts the claims of those passages with the rules and checks each
hypothesis's structured predictions against them.  A prediction holds, fails, or cannot be decided by the material;
a hypothesis is *confirmed* when at least one prediction is decided and every decided one holds, *refuted* when one
fails, *untestable* otherwise.  The same checks serve the Historical Time Machine evaluation (texts after a cutoff).
"""

from __future__ import annotations

from typing import Any

from ..protocol.claims import ClaimRelation
from ..protocol.events import EventType
from ..tools.adapters import SenseOracle


def _members(claim: Any) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated and not a.qualifiers.get("outcome")}


def check_prediction(pred: Any, hypothesis: Any, claims: list[Any], harness: Any, derived: list[Any]) -> bool | None:
    """True / False when ``claims`` decide the prediction; None when they cannot."""
    kind, subject, obj = pred.kind, pred.subject, pred.object
    if kind == "absent_after":
        start = pred.period.start if getattr(pred, "period", None) is not None else None
        year = lambda c: c.temporal.year("composition") if c.temporal else None  # noqa: E731
        relevant = [c for c in claims if start is None or (year(c) or 0) >= start]
        if not any(subject in _members(c) for c in relevant):
            return None  # the material never discusses the subject: its silence decides nothing
        return not any({subject, obj} <= _members(c) for c in relevant)
    if kind == "link_appears":
        if not any(subject in _members(c) for c in claims):
            return None
        return any({subject, obj} <= _members(c) for c in claims)
    if kind == "cooccurrence_after":
        lhs = set(subject.split(","))
        relevant = [c for c in claims if c.relation == ClaimRelation.INDICATED_FOR and lhs <= _members(c)]
        if not relevant:
            return None
        return sum(obj in _members(c) for c in relevant) * 2 >= len(relevant)
    if kind == "herb_retained":
        family = {t for t in hypothesis.terms if t.startswith("formula:")}
        core = {t for t in subject.split(",") if t.startswith("herb:")}
        children = [e.source_id for e in derived if e.target_id in family and e.source_id not in family]
        if not children or not core:
            return None
        compositions = {f: _members(c) for c in claims if c.relation == ClaimRelation.COMPOSED_OF
                        for f in _members(c) if f in children}
        judged = [core <= herbs for herbs in compositions.values()]
        return all(judged) if judged else None
    if kind == "sense_shift" and obj:
        oracle = SenseOracle(harness.pack, harness.corpus)
        senses = [s for s in (oracle(c, subject) for c in claims if subject in _members(c)) if s]
        if not senses:
            return None
        return max(set(senses), key=senses.count) == obj
    if kind == "renaming":
        uses = [c for c in claims if subject in _members(c)]
        if not uses:
            return None
        return not any(a.surface == obj for c in uses for a in c.arguments if a.term_id == subject)  # the avoided name stays gone
    return None


def confirm_hypotheses(harness: Any, state: Any, tx: Any) -> str:
    manifest = state.corpus
    ids = list(getattr(manifest, "confirmation_passage_ids", []) or []) if manifest is not None else []
    if not ids:
        return "no confirmation set in the contract: nothing to confirm"
    corpus = harness.corpus
    extractor = harness.capabilities.get("extractor")
    passages = corpus.passages_by_id(ids)
    claims = [c for p in passages for c in extractor.extract(p, harness.philology.assess(p))]
    try:
        derived = [e for e in harness.capabilities.get("lineage").build(passages, claims) if e.relation == "formula_derived_from"]
    except Exception:  # lineage is an aid for one prediction kind, not a requirement
        derived = []
    counts = {"confirmed": 0, "refuted": 0, "untestable": 0}
    for h in sorted(state.hypotheses.values(), key=lambda x: x.id):
        if h.status in ("superseded", "rejected", "expert_rejected") or not h.predictions:
            continue
        tests = []
        for pred in h.predictions:
            held = check_prediction(pred, h, claims, harness, derived)
            tests.append({"kind": pred.kind, "subject": pred.subject, "object": pred.object, "held": held})
        decided = [t["held"] for t in tests if t["held"] is not None]
        status = "untestable" if not decided else ("confirmed" if all(decided) else "refuted")
        counts[status] += 1
        tx.emit(EventType.HYPOTHESIS_CONFIRMED, {"hypothesis_id": h.id, "confirmation": {
            "status": status, "tests": tests, "passages": len(passages), "claims": len(claims), "version": h.version(),
            "material": "confirmation set: whole source families withheld from exploration"}})
    return f"confirmation on {len(passages)} withheld passages ({len(claims)} claims): " + ", ".join(f"{k} {v}" for k, v in counts.items())
