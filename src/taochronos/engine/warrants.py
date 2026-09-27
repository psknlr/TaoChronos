"""Build the warrant of every hypothesis: the inference, its premises and assumptions, the rival explanations of its
discovery type — each checked where a deterministic check exists — its defeaters, scope and uncertainties.

A validator runs this (it grades nothing: it records what a reader needs to judge the inference).  A rival is
**excluded** only when a check on the corpus rules it out, and the check is named; it is **open** when a check finds
it possible, or when none can be run and the hypothesis at least names it; **unaddressed** otherwise.  Some checks
are discriminating analyses in their own right — the drift re-estimated without the later texts that only quote the
earlier ones, the early support counted by independent source family.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..protocol.base import stable_id
from ..protocol.claims import ClaimRelation
from ..protocol.evidence import Stance
from ..protocol.warrant import ALTERNATIVES, ASSUMPTIONS_BY_KIND, DISCOVERY_TYPE, INFERENCE_BY_KIND, CompetingExplanation, Warrant
from ..science.concept_drift import concept_drift
from ..tools.adapters import SenseOracle, author_clusters, binner, claim_year_fn

MIN_LATE_PASSAGES = 20
QUOTING = ("transcribes", "rephrases")


class _Ctx:
    """What the checks share for one state."""

    def __init__(self, harness: Any, state: Any) -> None:
        self.h = harness
        self.state = state
        self.corpus = harness.corpus
        self.pack = harness.pack
        self.cluster = author_clusters(self.corpus, list(state.lineage.values()))
        self.year = claim_year_fn(self.corpus)
        self.need = state.goal.required_evidence.min_independent_sources if state.goal else 2
        self.quoting = [e for e in state.lineage.values() if e.relation in QUOTING and e.source_passage and e.target_passage]
        self.quoted_later = {e.source_passage for e in self.quoting}  # passages that transcribe or rephrase an earlier one

    def passage_year(self, pid: str) -> float | None:
        return self.corpus.year(self.corpus.passage(pid)) if self.corpus.has_passage(pid) else None

    def category(self, book_id: str) -> str:
        book = self.corpus.books.get(book_id)
        return getattr(book, "category", "") or "" if book else ""

    def members(self, claim: Any) -> set[str]:
        return {a.term_id for a in claim.arguments if a.term_id and not a.negated}


def _alt(spec: dict[str, str], status: str, basis: str, evidence: list[str] | None = None) -> CompetingExplanation:
    return CompetingExplanation(id=spec["id"], label=spec["label"], test=spec["test"], status=status, basis=basis,
                                evidence_ids=list(evidence or []))


# ------------------------------------------------------------------ checks by rival
def _decline(c: _Ctx, h: Any, support: list[Any], analyses: dict[str, Any]) -> dict[str, tuple[str, str]]:
    obs = [c.state.observations[o] for o in h.observation_ids if o in c.state.observations]
    data = obs[0].data if obs else {}
    out: dict[str, tuple[str, str]] = {}
    if h.kind == "historical_testimony":
        why = "a witness states the change of use; it is tested against earlier attestation (earliest_source), not inferred from silence"
        out["coverage"] = ("excluded", "the change is stated by a witness of the time, not inferred from later silence")
        for rival in ("genre", "renaming", "transcription_omission"):
            out[rival] = ("not_applicable", why)
    pivot = float(data.get("pivot_year", 0) or 0)
    left, right = data.get("left"), data.get("right")
    if pivot and left:
        manifest = c.state.corpus
        late = [pid for pid in (manifest.passage_ids if manifest else []) if (c.passage_year(pid) or 0) >= pivot]
        periods = Counter(c.pack.periods.period_of(c.passage_year(pid)) for pid in late)
        analyses["later_passages"] = len(late)
        out["coverage"] = (("excluded", f"{len(late)} passages after {int(pivot)} in {len([p for p in periods if p])} period(s) were surveyed")
                           if len(late) >= MIN_LATE_PASSAGES else
                           ("open", f"only {len(late)} passages after {int(pivot)} are in scope: absence there is weak evidence"))
        later = [cl for cl in c.state.claims.values() if (c.year(cl) or 0) >= pivot and left in c.members(cl)]
        early_genres = {c.category(r.book_id) for r in support}
        later_genres = {c.category(cl.book_id) for cl in later}
        shared = sorted(g for g in early_genres & later_genres if g)
        out["genre"] = (("excluded", f"later texts of the same genre ({'、'.join(shared)}) still discuss the first term without the second")
                        if shared else ("open", "the later mentions come from other genres than the early support"))
        if right:
            entry = c.pack.lexicon.entry(right)
            names = set(entry.surfaces()) - {entry.term} if entry is not None else set()
            renamed = [cl.passage_id for cl in later if any(a.surface in names for a in cl.arguments)]
            out["renaming"] = (("open", f"another name of the second term appears with the first after {int(pivot)}", renamed[:3])  # type: ignore[assignment]
                               if renamed else ("excluded", "no other recorded name of the second term appears with the first later on"))
        early = {r.passage_id for r in support}
        copies = [e for e in c.quoting if e.target_passage in early and (c.passage_year(e.source_passage) or 0) >= pivot]
        out["transcription_omission"] = (("open", f"{len(copies)} later text(s) copy the early passages; an omission in copying could explain the silence")
                                         if copies else ("excluded", "the later texts do not copy the early passages: their silence is independent"))
    families = sorted({c.cluster(r.book_id) for r in support})
    analyses["early_families"] = families
    out["survival_bias"] = (("excluded", f"the early support comes from {len(families)} independent source families")
                            if len(families) >= 2 else ("open", "the early support comes from one surviving source family"))
    return out


def _semantic(c: _Ctx, h: Any, support: list[Any], analyses: dict[str, Any]) -> dict[str, tuple[str, str]]:
    obs = [c.state.observations[o] for o in h.observation_ids if o in c.state.observations]
    data = obs[0].data if obs else {}
    out: dict[str, tuple[str, str]] = {}
    contested = [r.id for r in support if (a := c.state.philology.get(r.passage_id)) is not None and a.contested_at(r.start, r.end)]
    out["version"] = (("open", f"{len(contested)} supporting passage(s) read through a contested variant", contested)  # type: ignore[assignment]
                      if contested else ("excluded", "no supporting passage depends on a contested reading"))
    schools = Counter(getattr(c.corpus.books.get(r.book_id), "school", "") or "" for r in support)
    named = {s for s in schools if s}
    out["school"] = (("open", f"the evidence comes from one school ({next(iter(named))})") if len(named) == 1 and len(schools) == 1
                     else ("excluded", "the evidence spans works of more than one school or none"))
    genres = {c.category(r.book_id) for r in support} - {""}
    out["genre"] = (("excluded", f"the evidence spans genres ({'、'.join(sorted(genres))}); the change is not one genre replacing another")
                    if len(genres) >= 2 else ("open", "all evidence comes from one genre"))
    # discriminating analysis: re-estimate the drift without the later uses that only transcribe or rephrase earlier texts
    family = set(data.get("family") or ([data["term"]] if data.get("term") else []))
    if family:
        claims = [cl for cl in c.state.claims.values() if family & c.members(cl)]
        independent = [cl for cl in claims if cl.passage_id not in c.quoted_later]
        share = 1 - len(independent) / len(claims) if claims else 0.0
        again = concept_drift(family, independent, c.year, binner(c.pack), sense_fn=SenseOracle(c.pack, c.corpus, c.state.term_resolutions),
                              n_permutations=199, seed=11) if independent else None
        before = (data.get("max_shift") or {}).get("jsd")
        after = again["max_shift"]["jsd"] if again else None
        analyses["drift_without_quotations"] = {"quoted_share": round(share, 3), "jsd_before": before, "jsd_after": after}
        if after is not None and before and after >= 0.5 * before:
            out["quotation_share"] = ("excluded", f"re-estimated without quoting texts ({share:.0%} of uses) the shift remains (JSD {after} vs {before})")
        elif share == 0:
            out["quotation_share"] = ("excluded", "no later use transcribes an earlier text")
        else:
            out["quotation_share"] = ("open", f"without the quoting texts ({share:.0%} of uses) the shift is not recovered")
    return out


def _conflict(c: _Ctx, h: Any, support: list[Any], analyses: dict[str, Any]) -> dict[str, tuple[str, str]]:
    obs = [c.state.observations[o] for o in h.observation_ids if o in c.state.observations]
    claims = [c.state.claims[x] for o in obs for x in o.claim_ids if x in c.state.claims][:2]
    out: dict[str, tuple[str, str]] = {}
    if len(claims) < 2:
        return out
    a, b = claims
    reported = [x.id for x in (a, b) if x.stance in ("reported", "rejected")]
    out["speaker"] = (("open", "one of the two statements is reported or rejected by its author, not asserted", reported)  # type: ignore[assignment]
                      if reported else ("excluded", "both statements are their authors' own"))
    out["conditions"] = (("open", f"the statements carry different conditions: {a.conditions[:1]} / {b.conditions[:1]}")
                         if (a.conditions or b.conditions) and a.conditions != b.conditions else
                         ("excluded", "neither statement is conditioned differently"))
    out["stage"] = (("open", f"the statements concern different stages: {a.temporal_scope} / {b.temporal_scope}")
                    if (a.temporal_scope or b.temporal_scope) and set(a.temporal_scope) != set(b.temporal_scope) else
                    ("excluded", "no difference of stage or time is marked"))
    kinds = [getattr(c.corpus.passage(x.passage_id), "kind", "") if c.corpus.has_passage(x.passage_id) else "" for x in (a, b)]
    out["editorial_insertion"] = (("open", "one statement stands in a commentary or note layer") if any(k in ("commentary", "note", "annotation") for k in kinds)
                                  else ("excluded", "both statements stand in the main text"))
    return out


def _new_use(c: _Ctx, h: Any, support: list[Any], analyses: dict[str, Any]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    families = sorted({c.cluster(r.book_id) for r in support})
    out["single_case"] = (("excluded", f"{len(families)} independent source families") if len(families) >= 2
                          else ("open", "one source family only"))
    passages = {r.passage_id for r in support}
    dup = {e.source_passage for e in c.quoting if e.source_passage in passages and e.target_passage in passages}
    independent = passages - dup
    out["quotation_duplication"] = (("excluded", f"{len(independent)} supporting passages remain once copies of each other are collapsed")
                                    if len(independent) >= 2 else ("open", "the support reduces to one passage and its copies"))
    formulas = [t for t in h.terms if t.startswith("formula:")]
    if not formulas:
        for rival in ("same_name_other_formula", "same_formula_other_name"):
            out[rival] = ("not_applicable", "the hypothesis names no formula")
    comps: dict[str, list[set[str]]] = {}
    for cl in c.state.claims.values():
        if cl.relation == ClaimRelation.COMPOSED_OF:
            fs = [a.term_id for a in cl.arguments if (a.term_id or "").startswith("formula:")]
            herbs = {a.term_id for a in cl.arguments if (a.term_id or "").startswith("herb:")}
            for f in fs:
                comps.setdefault(f, []).append(herbs)
    if formulas:
        f = formulas[0]
        versions = comps.get(f, [])
        spread = min((len(x & y) / len(x | y) for i, x in enumerate(versions) for y in versions[i + 1:] if x | y), default=1.0)
        out["same_name_other_formula"] = (("open", f"compositions under the name differ (Jaccard {spread:.2f})") if spread < 0.5
                                          else ("excluded", f"{len(versions)} composition(s) under the name agree"))
        mine = set().union(*versions) if versions else set()
        twins = [g for g, vs in comps.items() if g != f and mine and any(len(v & mine) / len(v | mine) >= 0.8 for v in vs if v | mine)]
        out["same_formula_other_name"] = (("open", f"the same composition appears under another name ({twins[0]})") if twins
                                          else ("excluded", "no other formula has the same composition"))
    return out


def _influence(c: _Ctx, h: Any, support: list[Any], analyses: dict[str, Any]) -> dict[str, tuple[str, str]]:
    obs = [c.state.observations[o] for o in h.observation_ids if o in c.state.observations]
    data = obs[0].data if obs else {}
    out: dict[str, tuple[str, str]] = {}
    steps = data.get("steps") or ([{"child": data["child"], "parent": data["parent"]}] if data.get("child") and data.get("parent") else [])
    first: dict[str, float] = {}
    for cl in c.state.claims.values():
        y = c.year(cl)
        if y is None:
            continue
        for a in cl.arguments:
            if (a.term_id or "").startswith("formula:"):
                first[a.term_id] = min(first.get(a.term_id, y), y)
    overlapping = []
    for s in steps:
        yc, yp = first.get(s.get("child", "")), first.get(s.get("parent", ""))
        if yc is None or yp is None or yc - yp < 20:
            overlapping.append(f"{s.get('parent')}→{s.get('child')}")
    if steps:
        out["reversed_chronology"] = (("open", f"{len(overlapping)} step(s) whose order the dates do not settle (within 20 years, reversed or undated)")
                                      if overlapping else ("excluded", "every step goes from an earlier formula to one first attested 20+ years later"))
        herbs = Counter(a.term_id for cl in c.state.claims.values() if cl.relation == ClaimRelation.COMPOSED_OF
                        for a in cl.arguments if (a.term_id or "").startswith("herb:"))
        common = {t for t, _ in herbs.most_common(5)}
        core = set(data.get("stable_core") or []) - common
        out["common_vocabulary"] = (("excluded", f"the shared core keeps uncommon drugs ({'、'.join(sorted(core))[:40]})") if core
                                    else ("open", "the shared drugs are the most common ones"))
    explicit = [e for e in c.state.lineage.values() if e.relation in ("cites", "formula_derived_from") and e.evidence.get("quote")
                and ({e.source_id, e.target_id} & set(h.terms))] + [s for s in steps if s.get("stated_by_name")]
    out["common_ancestor"] = (("excluded", "a text states the derivation explicitly", [])  # type: ignore[assignment]
                              if explicit else ("open", "no text states the derivation; a shared earlier source is possible"))
    if h.kind == "formula_evolution":
        out["indirect_citation"] = (("excluded", "the derivation is stated by name (X加Y) in the later text") if explicit
                                    else ("open", "the derivation may pass through intermediate formulas absent from the corpus"))
    elif h.kind == "renaming":
        out["common_vocabulary"] = ("excluded", "a renaming is read as one drug under two names in the same composition slot, not as shared words")
        out["indirect_citation"] = ("open", "the renamed composition may reach the later text through an intermediate copy")
    elif h.kind == "lost_source":
        bound = data.get("must_predate")
        out["reversed_chronology"] = (("excluded", f"the citations date the cited work before {int(bound)}") if bound is not None
                                      else ("open", "the citing passages are undated: the order is not settled"))
        out["common_vocabulary"] = ("excluded", "the source is identified by an explicit title in the citations, not by shared words")
        out["indirect_citation"] = ("open", "the citations may pass through intermediate compilations (类书) rather than the book itself")
    return out


def _bridge(c: _Ctx, h: Any, support: list[Any], analyses: dict[str, Any]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {"same_name_other_thing": ("open", "the identity of the historical name needs 本草考证")}
    if "不构成" in h.statement or "not validate" in h.statement:
        out["inspired_not_validated"] = ("excluded", "the hypothesis itself states that modern evidence does not validate the text")
    return out


CHECKS = {"decline": _decline, "semantic_change": _semantic, "conflict": _conflict, "new_use": _new_use, "influence": _influence,
          "bridge": _bridge}


def build_warrant(harness: Any, state: Any, h: Any, c: _Ctx | None = None) -> Warrant:
    c = c or _Ctx(harness, state)
    inference = INFERENCE_BY_KIND.get(h.kind, "abduction")
    dtype = DISCOVERY_TYPE.get(h.kind, "new_use")
    support = [state.evidence[e] for e in h.supporting_evidence if e in state.evidence and e not in state.retractions]
    counter = [state.evidence[e] for e in h.contradictory_evidence if e in state.evidence and e not in state.retractions]
    analyses: dict[str, Any] = {}
    found = CHECKS.get(dtype, lambda *a: {})(c, h, support, analyses)
    named = " ".join(h.alternative_explanations)
    competing = []
    for spec in ALTERNATIVES.get(dtype, []):
        if spec["id"] in found:
            status, basis, *rest = found[spec["id"]]
            competing.append(_alt(spec, status, basis, rest[0] if rest else None))
        elif any(k and k in named for k in (spec["label"][:2], spec["label"][-2:])):
            competing.append(_alt(spec, "open", "named by the hypothesis; no mechanical check exists"))
        else:
            competing.append(_alt(spec, "unaddressed", "no check could be run and the hypothesis does not name it"))
    reviews = state.reviews_for(h.id)
    latest = max(reviews, key=lambda r: (r.round, r.id)) if reviews else None
    defeaters = [{"objection_id": o.id, "check": o.check, "severity": o.severity, "kind": o.kind or ("hard" if o.hard else "interpretive"),
                  "status": "defeated" if o.resolved else "active"}
                 for o in (latest.objections if latest else []) if o.status != "noted"]
    obs_ids = [o for o in h.observation_ids if o in state.observations]
    ana = [a for a, rec in state.analyses.items() if rec.get("target_id") in obs_ids]
    premises = ([{"id": r.id, "kind": "evidence", "role": "attestation"} for r in support]
                + [{"id": o, "kind": "observation", "role": "pattern"} for o in obs_ids]
                + [{"id": a, "kind": "analysis", "role": "statistic"} for a in ana])
    families = sorted({c.cluster(r.book_id) for r in support})
    periods = sorted({c.pack.periods.period_of(c.passage_year(r.passage_id)) or "?" for r in support})
    uncertainties = []
    if any((rec := state.claims.get(r.claim_id or "")) is not None and rec.support.get("verdict") in ("insufficient", "ambiguous") for r in support):
        uncertainties.append("some supporting claims are not clearly stated by their quotes (semantic support insufficient or ambiguous)")
    if any(r.temporal is None or r.temporal.effective() is None for r in support):
        uncertainties.append("some witnesses are undated")
    if h.anachronism_risk in ("medium", "high"):
        uncertainties.append(f"anachronism risk {h.anachronism_risk}")
    active = [d for d in defeaters if d["status"] == "active" and d["severity"] in ("critical", "major")]
    confirmed = (h.confirmation or {}).get("status") == "confirmed"
    needs_confirmation = bool(state.corpus is not None and getattr(state.corpus, "confirmation_passage_ids", None))
    if not active and len(families) >= c.need and all(x.status == "excluded" for x in competing) and (confirmed or not needs_confirmation):
        strength = "robust"
    elif not active and len(families) >= c.need:
        strength = "supported"
    else:
        strength = "consistent_with"
    version = h.version()
    return Warrant(
        id=stable_id("wrt", h.id, version), hypothesis_id=h.id, hypothesis_version=version, inference=inference, discovery_type=dtype,
        premises=premises, assumptions=list(ASSUMPTIONS_BY_KIND.get(inference, [])), competing=competing, defeaters=defeaters,
        supporting=[r.id for r in support if r.stance == Stance.SUPPORTS], opposing=[r.id for r in counter],
        scope={"corpus": "the research scope of this session (its corpus manifest)", "families": families, "periods": periods,
               "qualifiers": dict(h.qualifiers)},
        uncertainties=uncertainties, analyses=analyses, strength=strength,
    )


def build_warrants(harness: Any, state: Any) -> list[Warrant]:
    c = _Ctx(harness, state)
    return [build_warrant(harness, state, h, c) for h in sorted(state.hypotheses.values(), key=lambda x: x.id)
            if h.status not in ("superseded",)]
