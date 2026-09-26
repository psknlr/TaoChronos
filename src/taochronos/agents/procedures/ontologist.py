"""Ontologist / Terminology Curator: typed historical → modern mappings, proposed only.

Mappings are never ``=``: each gets a MappingRelation (related,
partially_overlapping, uncertain, not_equivalent) with a rationale.  An agent
may not assert equivalence — the anachronism guard blocks it and the
proposal is downgraded to ``related`` and flagged for a human expert.  Every
mapping is a ProposedChange that a validator or human must decide.
"""

from __future__ import annotations

from typing import Any

from ...kernel.hooks import HookPoint
from ...protocol.base import stable_id
from ...protocol.concepts import MappingRelation
from ...protocol.events import EventType
from ...protocol.research import ProposedChange
from .common import focus_term_ids, surface

OUTPUT = "MappingProposals"


def instructions(ctx: Any) -> str:
    rels = ", ".join(r.value for r in MappingRelation if r != MappingRelation.EQUIVALENT)
    return ("Propose typed mappings between the period-bound senses of the focus terms and modern concepts. Use one of: "
            f"{rels}. Never use 'equivalent' — only a human expert may assert equivalence. Explain each relation "
            "(scope of the historical category, theory-bound concepts, sparse attestation).")


def _terms(ctx: Any) -> list[str]:
    terms = [surface(t) for t in ctx.inputs.get("terms") or focus_term_ids(ctx)]
    for r in ctx.state.term_resolutions.values():
        if r.homonym_risk:
            terms.append(surface(r.term_id))
    return sorted(set(terms))


def draft(ctx: Any) -> dict[str, Any]:
    terminology = ctx.cap("domain").terminology
    mappings = []
    for term in _terms(ctx):
        ht = terminology.term(term)
        if ht is None:
            continue
        for sense in ht.senses:
            for concept_id in terminology.sense_meta.get(sense.id, {}).get("candidates", []):
                if concept_id not in terminology.concepts:
                    continue
                m = terminology.propose_mapping(sense.id, concept_id, proposer=ctx.actor.id)
                mappings.append({"sense_id": m.sense_id, "concept_id": m.concept_id, "relation": m.relation.value,
                                 "rationale": m.rationale})
    return {"mappings": mappings}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    terminology = ctx.cap("domain").terminology
    proposed, flagged, rejected = 0, 0, 0
    for m in output.get("mappings", []):
        sense = terminology.sense(m.get("sense_id", ""))
        concept = terminology.concepts.get(m.get("concept_id", ""))
        try:
            relation = MappingRelation(m.get("relation"))
        except ValueError:
            relation = None
        if sense is None or concept is None or relation is None:
            rejected += 1
            continue
        payload = {"kind": "concept_mapping", "sense_id": sense.id, "concept_id": concept.id, "relation": relation.value,
                   "rationale": m.get("rationale", ""), "historical_label": sense.label, "modern_label": concept.label}
        verdict = ctx.hook(HookPoint.BEFORE_GRAPH_WRITE, payload, subject_id=f"{sense.id}->{concept.id}")
        if not verdict.allow:
            payload["relation"] = MappingRelation.RELATED.value
            payload["equivalence_candidate"] = True
            payload["rationale"] = (payload["rationale"] + "；" if payload["rationale"] else "") + f"降级：{verdict.reason}"
            flagged += 1
        change = ProposedChange(
            id=stable_id("chg", "terminology", sense.id, concept.id),
            target="terminology",
            op="add",
            payload=payload,
            rationale=payload["rationale"],
            proposer=ctx.actor.id,
        )
        ctx.emit(EventType.CHANGE_PROPOSED, {"change": change.to_dict()}, generated=[change.id])
        proposed += 1
    return f"{proposed} typed mapping(s) proposed for expert/validator decision; {flagged} equivalence claim(s) downgraded; {rejected} invalid"
