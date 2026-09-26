"""Modern Evidence Analyst: the only door between the historical and biomedical spaces.

Modern literature never upgrades a historical hypothesis.  When a focus term or
hypothesis touches a concept with modern evidence, this agent (1) links the
modern records to the hypothesis as *context* (Biomedical space, stance
``context``), and (2) may open a separate cross-space *bridge* hypothesis in
the Modern-TCM space whose mapping relation is typed (never ``=``) and which
must pass Gate G8.  Historical support for a bridge is still verbatim text.
"""

from __future__ import annotations

from typing import Any

from ...kernel.hooks import HookPoint
from ...protocol.base import stable_id
from ...protocol.claims import ClaimRelation
from ...protocol.concepts import EvidenceDomain, KnowledgeSpace
from ...protocol.confidence import ConfidenceVector
from ...protocol.documents import Locator
from ...protocol.events import EventType
from ...protocol.evidence import EvidenceRecord, Stance
from ...protocol.hypothesis import Hypothesis, Prediction
from .common import evidence_from_claim, focus_term_ids, surface, surfaces_of

OUTPUT = "ModernEvidenceSet"


def instructions(ctx: Any) -> str:
    return ("Link modern evidence records (Biomedical space) to hypotheses as context only, and propose cross-space "
            "bridges where a historical term's sense has a candidate modern concept. State the mapping relation "
            "(related / partially_overlapping / uncertain / not_equivalent) — never equivalence — and remember that a "
            "modern finding does not validate an ancient text, nor the reverse.")


def _concepts_for(ctx: Any, term_surface: str) -> list[tuple[str, str]]:
    terminology = ctx.cap("domain").terminology
    term = terminology.term(term_surface)
    out = []
    if term:
        for s in term.senses:
            for c in terminology.sense_meta.get(s.id, {}).get("candidates", []):
                out.append((s.id, c))
    return out


def draft(ctx: Any) -> dict[str, Any]:
    records = ctx.services.get("modern_evidence", [])
    focus = [surface(t) for t in focus_term_ids(ctx)]
    links, bridges = [], []
    terms_by_h = {h.id: {surface(t) for t in h.terms} for h in ctx.state.active_hypotheses()}
    for rec in records:
        related = set(rec.get("related_terms", []))
        for hid, terms in sorted(terms_by_h.items()):
            if terms & related:
                links.append({"hypothesis_id": hid, "record_id": rec["id"], "concept_id": rec.get("concept_id", ""),
                              "relation": "context", "note": "modern evidence attached as context; it does not validate the historical claim"})
        in_play = set(focus).union(*terms_by_h.values()) if terms_by_h else set(focus)
        for term in sorted(related & in_play):
            for sense_id, concept_id in _concepts_for(ctx, term):
                mapping = ctx.cap("domain").terminology.propose_mapping(sense_id, concept_id, proposer=ctx.actor.id)
                bridges.append({"term": term, "sense_id": sense_id, "concept_id": concept_id, "relation": mapping.relation.value,
                                "rationale": mapping.rationale, "record_ids": [rec["id"]]})
    merged: dict[tuple, dict] = {}
    for b in bridges:
        key = (b["sense_id"], b["concept_id"])
        if key in merged:
            merged[key]["record_ids"] = sorted(set(merged[key]["record_ids"]) | set(b["record_ids"]))
        else:
            merged[key] = b
    return {"links": links, "bridges": list(merged.values())}


def _modern_record(ctx: Any, rec: dict[str, Any], hypothesis_id: str) -> EvidenceRecord:
    statement = " ".join(str(rec.get("statement", "")).split())
    domain = EvidenceDomain(rec.get("evidence_domain", "modern_clinical"))
    return EvidenceRecord(
        id=stable_id("evd", "modern", rec["id"], hypothesis_id),
        passage_id=rec["id"], book_id="modern-literature",
        locator=Locator(book_id="modern-literature", section=rec.get("source", ""), precision="unknown"),
        quote=statement, start=0, end=len(statement), agent=ctx.actor.id, retrieval_method="literature:curated",
        hypothesis_id=hypothesis_id, stance=Stance.CONTEXT, evidence_domain=domain,
        confidence=ConfidenceVector(modern_mapping=None), note=f"{rec.get('source', '')} — {rec.get('note', '')}".strip(" —"),
    )


def commit(ctx: Any, output: dict[str, Any]) -> str:
    state = ctx.state
    records = {r["id"]: r for r in ctx.services.get("modern_evidence", [])}
    terminology = ctx.cap("domain").terminology
    linked = 0
    evidence: dict[str, dict] = {}
    for link in output.get("links", []):
        hid, rid = link.get("hypothesis_id"), link.get("record_id")
        if hid not in state.hypotheses or rid not in records:
            continue
        rec = _modern_record(ctx, records[rid], hid)
        evidence[rec.id] = rec.to_dict()
        linked += 1
    bridges = []
    for b in output.get("bridges", []):
        sense = terminology.sense(b.get("sense_id", ""))
        concept = terminology.concepts.get(b.get("concept_id", ""))
        rids = [r for r in b.get("record_ids", []) if r in records]
        if sense is None or concept is None or not rids or b.get("relation") == "equivalent":
            continue
        term_surface = b.get("term") or sense.term_id
        entry_ids = {e.term_id for e in ctx.cap("domain").lexicon.entries.values() if term_surface in e.surfaces()}
        claims = sorted((c for c in state.claims.values() if entry_ids & {a.term_id for a in c.arguments}
                         and c.relation in (ClaimRelation.HERB_INDICATION, ClaimRelation.INDICATED_FOR, ClaimRelation.COMPOSED_OF)),
                        key=lambda c: c.id)[:4]
        if not claims:
            continue
        hid = stable_id("hyp", "bridge", sense.id, concept.id)
        if hid in state.hypotheses:
            continue
        support = [evidence_from_claim(ctx, c, hypothesis_id=hid) for c in claims]
        context = [_modern_record(ctx, records[r], hid) for r in rids]
        statement = (f"古籍中「{term_surface}」（{sense.label}）的记载与现代「{concept.label}」研究之间存在历史关联线索；"
                     f"二者的对应关系为「{b['relation']}」（{b.get('rationale', '')}），"
                     f"现代证据不构成对古籍记载的验证，古籍记载也不构成现代疗效的证据。")
        h = Hypothesis(
            id=hid, statement=statement, kind="cross_space_bridge", terms=sorted(entry_ids) + [concept.id],
            supporting_evidence=[r.id for r in support], replication_sources=sorted({r.book_id for r in support}),
            alternative_explanations=["同名异物：历史药名与现代物种的对应需本草考证", "现代发现的研究路径可能只是受到古籍启发，而非验证古籍用法"],
            anachronism_risk="medium", anachronism_risk_note="跨越历史文本与生物医学两个知识空间",
            testable_prediction=f"本草考证应能确定「{term_surface}」与 {concept.label} 的物种/概念对应程度",
            predictions=[Prediction(kind="mapping", subject=sense.id, object=concept.id, description=f"typed mapping: {b['relation']}")],
            space=KnowledgeSpace.MODERN_TCM, generated_by=ctx.actor.id, round=ctx.task.round,
            confidence=ConfidenceVector.mean([r.confidence for r in support]).replace(modern_mapping=None),
        )
        if not ctx.hook(HookPoint.AFTER_HYPOTHESIS, h, subject_id=h.id).allow:
            continue
        for r in support + context:
            evidence[r.id] = r.to_dict()
        bridges.append(h)
    if evidence:
        ctx.emit(EventType.EVIDENCE_RETRIEVED, {"records": [evidence[k] for k in sorted(evidence)]}, generated=sorted(evidence))
    if bridges:
        ctx.emit(EventType.HYPOTHESIS_GENERATED, {"hypotheses": [h.to_dict() for h in bridges]}, generated=[h.id for h in bridges])
    return f"{linked} context link(s); {len(bridges)} cross-space bridge hypothesis(es) opened for Gate G8"
