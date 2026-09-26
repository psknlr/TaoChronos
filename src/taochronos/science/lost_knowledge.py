"""D1 · Lost Knowledge Rediscovery.

An association (intervention ↔ indication, cause ↔ disease) that is attested
in early periods — ideally by independent sources — and then vanishes, while
both of its concepts keep being written about, is a candidate for lost or
forgotten knowledge.  Explicit historical testimony (e.g. 李时珍: “昔人称其…为要药，
而后世不复知用”) is surfaced as its own observation type.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from ..protocol.claims import Claim, ClaimRelation, Role
from .temporal import PeriodBinner

INTERVENTIONS = (Role.FORMULA, Role.HERB)
INDICATIONS = (Role.SYMPTOM, Role.SIGN, Role.DISEASE, Role.PATTERN, Role.INDICATION)


def association_units(claim: Claim, components: dict[str, list[str]] | None = None) -> list[tuple[str, str, str]]:
    """(left, right, kind) pairs expressed by a claim (compound findings expand to their parts)."""
    units: list[tuple[str, str, str]] = []
    comps = components or {}
    if claim.relation in (ClaimRelation.INDICATED_FOR, ClaimRelation.HERB_INDICATION):
        lefts = [a for a in claim.args(*INTERVENTIONS) if a.term_id]
        for left in lefts:
            for right in claim.args(*INDICATIONS):
                key = right.term_id or f"indication:{right.surface}"
                if right.negated or right.qualifiers.get("outcome"):
                    continue
                for part in [key, *comps.get(key, [])]:
                    units.append((left.term_id, part, "indication"))  # type: ignore[arg-type]
    elif claim.relation in (ClaimRelation.CAUSES, ClaimRelation.PATHOGENESIS):
        causes = [a for a in claim.args(Role.ETIOLOGY, Role.PATHOGENESIS) if a.term_id and not a.negated]
        for c in causes:
            for d in claim.args(Role.DISEASE, Role.SYMPTOM):
                if d.term_id and not d.negated:
                    units.append((c.term_id, d.term_id, "etiology"))  # type: ignore[arg-type]
    return units


def lost_knowledge(
    claims: list[Claim],
    year_fn: Callable[[Claim], float | None],
    binner: PeriodBinner,
    *,
    pivot_year: float = 960,
    cluster_of: Callable[[str], str] = lambda book: book,
    min_support: int = 2,
    max_candidates: int = 25,
    components: dict[str, list[str]] | None = None,
) -> dict:
    early_units: dict[tuple, dict] = defaultdict(lambda: {"books": set(), "clusters": set(), "claims": [], "years": []})
    late_units: set[tuple] = set()
    late_terms: dict[str, int] = defaultdict(int)
    for c in claims:
        y = year_fn(c)
        if y is None:
            continue
        members = {a.term_id for a in c.arguments if a.term_id and not a.negated}
        for m in list(members):
            members.update((components or {}).get(m, []))
        if y >= pivot_year:
            late_terms.update({m: late_terms[m] + 1 for m in members})
        for left, right, kind in association_units(c, components):
            key = (left, right, kind)
            if y < pivot_year:
                rec = early_units[key]
                rec["books"].add(c.book_id)
                rec["clusters"].add(cluster_of(c.book_id))
                rec["claims"].append(c.id)
                rec["years"].append(y)
            else:
                late_units.add(key)
    candidates = []
    for key, rec in early_units.items():
        if key in late_units:
            continue
        left, right, kind = key
        persists_left = late_terms.get(left, 0)
        persists_right = late_terms.get(right, 0)
        if not persists_left or not persists_right:
            continue  # a vanished concept is concept loss, not association loss
        support = len(rec["clusters"])
        score = (support / (support + 1)) * min(1.0, (persists_left + persists_right) / 6)
        candidates.append({
            "left": left,
            "right": right,
            "kind": kind,
            "support_books": sorted(rec["books"]),
            "independent_support": support,
            "replicated": support >= min_support,
            "early_years": sorted(rec["years"]),
            "later_mentions": {"left": persists_left, "right": persists_right},
            "claim_ids": rec["claims"],
            "score": round(score, 4),
        })
    candidates.sort(key=lambda c: (-c["replicated"], -c["score"], c["left"], c["right"]))
    testimony = []
    for c in claims:
        markers = [t for t in c.tags if t.startswith("period:")]
        if markers and c.relation == ClaimRelation.HERB_INDICATION:
            testimony.append({
                "claim_id": c.id,
                "passage_id": c.passage_id,
                "marker": markers[0].split(":", 1)[1],
                "herb": next((a.term_id for a in c.args(Role.HERB)), None),
                "uses": [a.surface for a in c.args(*INDICATIONS)],
            })
    return {
        "pivot_year": pivot_year,
        "candidates": candidates[:max_candidates],
        "replicated": sum(1 for c in candidates if c["replicated"]),
        "single_source": sum(1 for c in candidates if not c["replicated"]),
        "testimony": testimony,
    }
