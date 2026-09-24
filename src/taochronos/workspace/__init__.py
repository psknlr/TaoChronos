"""The Discovery Workspace: one self-contained HTML page per research session (works offline, no server).

Left: question, hypotheses, tasks · Centre: knowledge graph, timeline, evolution, report ·
Right: original text, variants, provenance chain · Bottom: support, counter-evidence, confidence, agent trace.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..engine.report import build as build_report
from ..engine.report import ranked
from ..kernel.observability import agent_tree, research_metrics
from ..protocol.base import to_jsonable
from ..protocol.evidence import Stance
from ..verification.provenance import provenance_chain
from .markdown import render
from .page import PAGE

MAX_GRAPH_NODES = 90


def _passage(harness: Any, state: Any, pid: str) -> dict[str, Any] | None:
    corpus = harness.corpus
    if not corpus.has_passage(pid):
        return None
    p = corpus.passage(pid)
    book = corpus.books.get(p.book_id)
    a = state.philology.get(pid)
    return {
        "id": pid,
        "book": book.title if book else p.book_id,
        "dynasty": book.dynasty if book else "",
        "year": corpus.year(p),
        "locator": p.locator.label(),
        "text": p.text,
        "variants": [to_jsonable(v) for v in p.variants],
        "contested": [to_jsonable(c) for c in (a.contested if a else [])],
        "collation": a.collation_status if a else p.collation_status.value,
        "philological_confidence": a.philological_confidence if a else None,
        "chain": provenance_chain(pid, state, corpus),
    }


def _graph(state: Any, hypotheses: list[Any]) -> dict[str, Any]:
    focus: Counter = Counter()
    edges: Counter = Counter()
    claim_ids = {state.evidence[e].claim_id for h in hypotheses for e in h.supporting_evidence
                 if e in state.evidence and state.evidence[e].claim_id}
    for cid in sorted(c for c in claim_ids if c):
        claim = state.claims.get(cid)
        if claim is None:
            continue
        members = sorted({a.term_id for a in claim.arguments if a.term_id and not a.negated})
        focus.update(members)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                edges[(a, b)] += 1
    for h in hypotheses:
        focus.update({t: 3 for t in h.terms})
    keep = {t for t, _ in focus.most_common(MAX_GRAPH_NODES)}
    for e in state.lineage.values():
        if e.relation == "formula_derived_from" and e.source_id in keep and e.target_id in keep:
            edges[(e.source_id, e.target_id)] += 2
    nodes = [{"id": t, "label": t.split(":", 1)[-1], "group": t.split(":", 1)[0], "weight": focus[t]} for t in sorted(keep)]
    links = [{"source": a, "target": b, "weight": w} for (a, b), w in sorted(edges.items()) if a in keep and b in keep]
    return {"nodes": nodes, "links": links}


def workspace_data(harness: Any, session: Any) -> dict[str, Any]:
    state = session.state
    top = ranked(state)
    failed = [h for h in state.hypotheses.values() if h.status in ("rejected", "expert_rejected")]
    shown = top + failed
    evidence_ids = {e for h in shown for e in h.supporting_evidence + h.contradictory_evidence}
    evidence_ids |= {e.id for e in state.evidence.values() if e.hypothesis_id is None}
    evidence = {}
    for eid in sorted(evidence_ids):
        e = state.evidence.get(eid)
        if e is None:
            continue
        evidence[eid] = {"id": eid, "passage_id": e.passage_id, "quote": e.quote, "start": e.start, "end": e.end,
                         "stance": e.stance.value, "hypothesis_id": e.hypothesis_id, "method": e.retrieval_method,
                         "domain": e.evidence_domain.value, "note": e.note}
    passages = {}
    for e in evidence.values():
        if e["passage_id"] not in passages:
            p = _passage(harness, state, e["passage_id"])
            if p:
                passages[e["passage_id"]] = p
    hyps = []
    for h in shown:
        reviews = state.reviews_for(h.id)
        latest = max(reviews, key=lambda r: (r.round, r.id)) if reviews else None
        hyps.append({
            "id": h.id, "statement": h.statement, "kind": h.kind, "status": h.status, "generation": h.generation,
            "parent": h.parent_id, "elo": h.elo, "d": h.discovery_score, "components": h.discovery_components,
            "gates": {g: r.status for g, r in state.gates.get(h.id, {}).items()},
            "support": [e for e in h.supporting_evidence if e in evidence],
            "counter": [e for e in h.contradictory_evidence if e in evidence],
            "objections": [to_jsonable(o) for o in (latest.objections if latest else [])],
            "verdict": latest.verdict if latest else None,
            "alternatives": h.alternative_explanations, "prediction": h.testable_prediction,
            "qualifiers": h.qualifiers, "revision_note": h.revision_note,
            "confidence": h.confidence.scholar_view(), "vector": to_jsonable(h.confidence),
            "philological_risk": h.philological_risk, "anachronism_risk": h.anachronism_risk,
            "terms": h.terms, "space": h.space.value,
        })
    tasks = [{"id": t.id, "kind": t.kind, "role": t.role, "round": t.round, "status": t.status, "summary": t.summary}
             for t in sorted(state.task_graph.values(), key=lambda t: (t.round, t.id))]
    evolution = [a.get("result", {}) | {"target": a.get("target_id")} for a in state.analyses.values() if a.get("kind") == "evolution"]
    _, md, _ = build_report(harness, state, session.id)
    goal = state.goal
    return {
        "session": session.id,
        "profile": state.profile,
        "status": (state.stop or {}).get("status", state.status),
        "stop_reasons": (state.stop or {}).get("reasons", []),
        "question": goal.question if goal else "",
        "focus": goal.focus_terms if goal else [],
        "tracks": goal.tracks if goal else [],
        "metrics": {k: v for k, v in research_metrics(state).items() if not isinstance(v, dict)},
        "hypotheses": hyps,
        "evidence": evidence,
        "passages": passages,
        "tasks": tasks,
        "graph": _graph(state, top[:12]),
        "evolution": sorted(evolution, key=lambda r: r.get("kind", "")),
        "agent_tree": agent_tree(session.events()),
        "report_html": render(md),
        "changes": [{"id": c.id, "status": c.status, "payload": c.payload} for c in sorted(state.changes.values(), key=lambda c: c.id)],
    }


def build_workspace(harness: Any, session: Any) -> str:
    data = json.dumps(workspace_data(harness, session), ensure_ascii=False, default=str).replace("</", "<\\/")
    return PAGE.replace("__TAOCHRONOS_DATA__", data)


def publish_workspace(harness: Any, session: Any) -> Any:
    state = session.state
    top = ranked(state)
    return harness.artifacts.publish(
        session, kind="workspace", title="Discovery Workspace", content=build_workspace(harness, session),
        filename="workspace.html", media_type="text/html", generator="kernel:workspace",
        evidence_refs=sorted({e for h in top for e in h.supporting_evidence}), hypothesis_refs=[h.id for h in top],
    )


__all__ = ["build_workspace", "publish_workspace", "workspace_data"]
