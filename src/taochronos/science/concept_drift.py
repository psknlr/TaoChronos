"""D2 · Concept Evolution Discovery (semantic drift of a historical term).

For a focus term the context profile (co-members of the claim hyperedges it
appears in) is computed per period.  Drift between periods is the
Jensen–Shannon divergence of the profiles; its significance is assessed with a
label-permutation test.  Resolved senses per period make the drift readable
(“symptom sense → disease sense → 三消 system”).
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from ..protocol.claims import Claim, Role
from .stats import context_jsd, jensen_shannon, normalize, permutation_test
from .temporal import PeriodBinner

CONTEXT_ROLES = (
    Role.SYMPTOM, Role.SIGN, Role.PULSE, Role.TONGUE, Role.DISEASE, Role.PATTERN, Role.PATHOGENESIS,
    Role.ETIOLOGY, Role.TREATMENT_PRINCIPLE, Role.TREATMENT_METHOD, Role.FORMULA, Role.HERB, Role.ORGAN, Role.CONDITION,
    Role.CONCEPT,
)


def _members(claim: Claim) -> list[str]:
    out = []
    for a in claim.arguments:
        if a.term_id and a.role in CONTEXT_ROLES and not a.negated and not a.qualifiers.get("outcome") and a.term_id not in out:
            out.append(a.term_id)
    return out


def concept_drift(
    term_id: str | set[str],
    claims: list[Claim],
    year_fn: Callable[[Claim], float | None],
    binner: PeriodBinner,
    *,
    sense_fn: Callable[[Claim, str], str | None] | None = None,
    n_permutations: int = 499,
    seed: int = 0,
    top: int = 6,
) -> dict | None:
    family = {term_id} if isinstance(term_id, str) else set(term_id)
    focus = term_id if isinstance(term_id, str) else sorted(family)[0]
    occurrences: list[tuple[str, list[str], str | None, Claim]] = []
    for c in claims:
        members = _members(c)
        hits = [m for m in members if m in family]
        if not hits:
            continue
        period = binner.of(year_fn(c))
        if period is None:
            continue
        sense = sense_fn(c, hits[0]) if sense_fn else None
        occurrences.append((period, [m for m in members if m not in family], sense, c))
    periods = [p for p in binner.ids() if any(o[0] == p for o in occurrences)]
    if len(periods) < 2:
        return None
    profiles = {p: Counter() for p in periods}
    samples: dict[str, list[list[str]]] = {p: [] for p in periods}
    senses = {p: Counter() for p in periods}
    books = {p: set() for p in periods}
    for period, ctx, sense, claim in occurrences:
        profiles[period].update(ctx)
        samples[period].append(ctx)
        books[period].add(claim.book_id)
        if sense:
            senses[period][sense] += 1
    series = []
    for a, b in zip(periods, periods[1:]):
        series.append({"from": a, "to": b, "jsd": round(jensen_shannon(profiles[a], profiles[b]), 4)})
    shift = max(series, key=lambda s: (s["jsd"], s["to"]))
    observed, p_value = permutation_test(samples[shift["from"]], samples[shift["to"]], context_jsd, n=n_permutations, seed=seed)
    first, last = periods[0], periods[-1]
    fl_obs, fl_p = permutation_test(samples[first], samples[last], context_jsd, n=n_permutations, seed=seed + 1)
    pf, pl = normalize(profiles[first]), normalize(profiles[last])
    gained = sorted(((t, pl[t] - pf.get(t, 0.0)) for t in pl if pl[t] > pf.get(t, 0.0)), key=lambda t: (-t[1], t[0]))[:top]
    lost = sorted(((t, pf[t] - pl.get(t, 0.0)) for t in pf if pf[t] > pl.get(t, 0.0)), key=lambda t: (-t[1], t[0]))[:top]
    dominant_senses = {p: senses[p].most_common(1)[0][0] for p in periods if senses[p]}
    sense_changes = []
    ordered = [dominant_senses.get(p) for p in periods]
    for (pa, sa), (pb, sb) in zip(zip(periods, ordered), list(zip(periods, ordered))[1:]):
        if sa and sb and sa != sb:
            sense_changes.append({"from_period": pa, "to_period": pb, "from": sa, "to": sb})
    return {
        "term": focus,
        "family": sorted(family),
        "periods": periods,
        "occurrences": {p: len(samples[p]) for p in periods},
        "books": {p: sorted(books[p]) for p in periods},
        "profiles": {p: profiles[p].most_common(top) for p in periods},
        "jsd_series": series,
        "max_shift": {**shift, "observed": round(observed, 4), "p_value": round(p_value, 4)},
        "first_last": {"from": first, "to": last, "jsd": round(fl_obs, 4), "p_value": round(fl_p, 4)},
        "gained": [(t, round(v, 4)) for t, v in gained],
        "lost": [(t, round(v, 4)) for t, v in lost],
        "senses": {p: dict(senses[p]) for p in periods},
        "dominant_sense": dominant_senses,
        "sense_changes": sense_changes,
        "claim_ids": [o[3].id for o in occurrences],
        "passage_ids": sorted({o[3].passage_id for o in occurrences}),
    }
