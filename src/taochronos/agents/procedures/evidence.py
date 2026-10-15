"""Evidence Retriever: the Evidence Ledger.

Round 0 builds a question-level ledger with the philology-aware temporal
GraphRAG search.  Later rounds are targeted: for hypotheses the meta-review
flags as under-replicated, the agent looks for *independent* witnesses (other
author clusters, not transcriptions of the same source).  Every record is a
verbatim span; the commit re-verifies it, so a fabricated quote never reaches
the ledger.
"""

from __future__ import annotations

import re
from typing import Any

from ...protocol.claims import Claim
from ...protocol.events import EventType
from ...protocol.evidence import EvidenceRecord, Stance
from ...verification.provenance import verify_evidence
from .common import block, cluster_fn, evidence_from_claim, evidence_record, focus_term_ids, locate, period_binner, surface, year_fn

OUTPUT = "EvidenceSet"
PER_QUERY = 8
PER_HYPOTHESIS = 3


def instructions(ctx: Any) -> str:
    if ctx.inputs.get("hypothesis_ids"):
        return ("Find independent textual witnesses (other books / author clusters, not transcriptions) for the listed "
                "hypotheses. Use classics.search and kg.claims; return records with verbatim quotes and a stance "
                "(supports / contradicts / context) and the hypothesis_id.")
    return ("Build the question-level evidence ledger: search the classics for the research question and focus terms "
            "(respect the period constraints) and return the most relevant verbatim passages with stance 'neutral'.")


def _members(claim: Claim) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated}


def _replicate(ctx: Any, h: Any) -> list[tuple[Claim, Stance, str]]:
    """Kind-specific replication: what would count as an *independent* witness for this hypothesis?

    Only hypotheses whose statement a further text can confirm are replicable by claims: an early
    attestation of a lost association, another indication with the rule's findings and formula, or a
    use of a drifting term in the sense its period predicts (a use in another sense is counter-evidence).
    Contradictions, testimony, lineages, renamings and lost sources are local by nature.
    """
    state = ctx.state
    obs = [state.observations[o] for o in h.observation_ids if o in state.observations]
    data = obs[0].data if obs else {}
    year = year_fn(ctx)
    out: list[tuple[Claim, Stance, str]] = []
    if h.kind == "lost_knowledge":
        terms = {data.get("left"), data.get("right")} - {None}
        pivot = data.get("pivot_year")
        for c in state.claims.values():
            y = year(c)
            if terms <= _members(c) and y is not None and pivot is not None and y < pivot:
                out.append((c, Stance.SUPPORTS, "early attestation"))
    elif h.kind == "association_rule":
        terms = set(data.get("lhs", [])) | {data.get("rhs")} - {None}
        for c in state.claims.values():
            if c.relation.value == "indicated_for" and terms <= _members(c):
                out.append((c, Stance.SUPPORTS, "same findings, same formula"))
    elif h.kind == "concept_drift":
        term = data.get("term")
        dominant = data.get("dominant_sense", {})
        binner = period_binner(ctx)
        senses = {(r.passage_id, r.term_id): r for r in state.term_resolutions.values()}
        for c in state.claims.values():
            if term not in _members(c):
                continue
            period = binner.of(year(c))
            res = senses.get((c.passage_id, term))
            if period not in dominant or res is None or res.sense_id is None:
                continue
            if res.sense_id == dominant[period]:
                out.append((c, Stance.SUPPORTS, f"sense {res.sense_id} as predicted for {period}"))
            elif res.probability >= 0.6:
                out.append((c, Stance.CONTRADICTS, f"sense {res.sense_id} ≠ {dominant[period]} predicted for {period}"))
    return sorted(out, key=lambda t: (year(t[0]) or 0, t[0].id))


def _targeted(ctx: Any, ids: list[str]) -> list[EvidenceRecord]:
    state = ctx.state
    cluster = cluster_fn(ctx)
    out: list[EvidenceRecord] = []
    for hid in ids:
        h = state.hypotheses.get(hid)
        if h is None:
            continue
        used = {state.evidence[e].claim_id for e in h.supporting_evidence + h.contradictory_evidence if e in state.evidence}
        clusters = {cluster(state.evidence[e].book_id) for e in h.supporting_evidence if e in state.evidence}
        found = 0
        for c, stance, why in _replicate(ctx, h):
            if c.id in used:
                continue
            if stance == Stance.SUPPORTS:
                if cluster(c.book_id) in clusters or found >= PER_HYPOTHESIS:
                    continue
                clusters.add(cluster(c.book_id))
                found += 1
            rec = evidence_from_claim(ctx, c, hypothesis_id=hid, stance=stance, method="replication:claims")
            rec.note = why
            out.append(rec)
            used.add(c.id)
        if not found:
            ctx.note(f"{hid}: no independent witness in scope")
    return out


# a search hit's flags (ADR 0023) in the page's words (web/js/util.js FLAG_WORDS), with the name they concern
FLAG_WORDS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"^anachronism:(.+)<(-?\d+):(?:edition|layer)$"), lambda m: f"年代存疑（{m[1]}约 {m[2]} 年后才通行）"),
    (re.compile(r"^homonym:(.+)$"), lambda m: f"同名异物（{m[1]}未能判定所指）"),
    (re.compile(r"^demoted:inside (.+)$"), lambda m: "仅见于他名之中" if m[1] == "?" else f"仅见于「{m[1]}」"),
    (re.compile(r"^demoted:no-context$"), lambda m: "无药物语境"),
    (re.compile(r"^other-referent:(.+)$"), lambda m: f"所指不同（{m[1]}在此段的年代指另一味药）"),
)
STATUS_WORDS = {"candidate": "候选", "stop": "多作普通词语"}  # open and cue (a gate the passage passed) say nothing


def _strings(value: Any) -> list[str]:
    return [x for x in (value if isinstance(value, list) else [value]) if isinstance(x, str) and x]


def _via_note(v: Any) -> str | None:
    """One ``via`` of a search hit, compact: 国老→甘草（别名录） — the other name, the drug, how they relate when it is not
    a plain 异名, what the passage writes when it is neither, the sources; a name read as one of its drugs is 读作
    鬼督邮→徐长卿（p 0.71）."""
    if not isinstance(v, dict) or not _strings(v.get("referent")) or not _strings(v.get("surface")):
        return None
    name, drug = v["surface"], v["referent"]
    if v.get("direction") == "asked":
        p = v.get("p")
        return f"读作 {name}→{drug}" + (f"（p {p}）" if isinstance(p, (int, float)) else "")
    names = [name] if v.get("direction") == "drug→alias" else [s for s in _strings(v.get("for")) if s != drug]
    kind = v.get("kind") if isinstance(v.get("kind"), str) and v.get("kind") else None
    why = ["写作" + name] if name not in names and name != drug else []
    why += ["相关" if kind is None else kind] if kind != "异名" else []
    why += [STATUS_WORDS[v["status"]]] if v.get("status") in STATUS_WORDS else []
    why += ["、".join(_strings(v.get("source")))] if _strings(v.get("source")) else []
    return "via " + ("、".join(names) + "→" if names else "") + drug + (f"（{'；'.join(why)}）" if why else "")


def _flag_note(flag: Any) -> str | None:
    if not isinstance(flag, str) or not flag:
        return None
    for pattern, word in FLAG_WORDS:
        m = pattern.match(flag)
        if m:
            return word(m)
    return flag  # a flag without words is kept as it is: a reason not to trust the hit is never dropped


def hit_note(hit: dict[str, Any]) -> str:
    """Why a search hit is in the ledger: its routes, and for a hit the alias layer found under another name or
    flagged, each ``via`` and flag (ADR 0023) — "routes: alias; via 国老→甘草（别名录）; 年代存疑（…）" — so the
    Skeptic and the report see what the passage writes and why it stands for the asked drug."""
    parts = ["routes: " + ",".join(hit.get("routes", []))]
    parts += [x for x in (_via_note(v) for v in hit.get("via") or []) if x]
    parts += [x for x in (_flag_note(f) for f in hit.get("flags") or []) if x]
    return "; ".join(dict.fromkeys(parts))


def _question_level(ctx: Any) -> list[EvidenceRecord]:
    retriever = ctx.cap("retriever")
    corpus = ctx.cap("corpus")
    queries = [q for q in ctx.inputs.get("queries", []) if q]
    queries += [surface(t) for t in focus_term_ids(ctx)]
    out: dict[str, EvidenceRecord] = {}
    for q in dict.fromkeys(queries):
        result = ctx.tool("classics.search", query=q, k=PER_QUERY)
        for hit in result["hits"]:
            passage = corpus.passage(hit["passage_id"])
            start, end = retriever.best_span(passage, hit.get("matched", []))
            rec = evidence_record(ctx, passage.id, start, end, method="retrieval:hybrid", stance=Stance.NEUTRAL, query=q,
                                  score=hit.get("score"), note=hit_note(hit))
            rec.routes = list(hit.get("routes", []))
            out.setdefault(rec.id, rec)
    return list(out.values())


def draft(ctx: Any) -> dict[str, Any]:
    ids = ctx.inputs.get("hypothesis_ids") or []
    records = _targeted(ctx, ids) if ids else _question_level(ctx)
    return {"records": [r.to_dict() for r in records]}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    in_scope = set(ctx.state.corpus.passage_ids) if ctx.state.corpus else None
    accepted: dict[str, dict[str, Any]] = {}
    rejected = 0
    for raw in output.get("records", []):
        if "id" in raw and "locator" in raw:
            rec = EvidenceRecord.from_dict(raw)
        else:  # model-proposed: the harness locates the span itself
            span = locate(ctx, raw.get("passage_id", ""), raw.get("quote", ""))
            if span is None:
                rejected += 1
                block(ctx, "provenance_validator", "BeforeGraphWrite", "evidence quote not found verbatim", raw.get("passage_id", ""))
                continue
            hid = raw.get("hypothesis_id")
            if hid and hid not in ctx.state.hypotheses:
                hid = None
            rec = evidence_record(ctx, raw["passage_id"], span[0], span[1], method=f"model:{ctx.route.model}",
                                  stance=Stance(raw.get("stance", "neutral")), hypothesis_id=hid,
                                  claim=ctx.state.claims.get(raw.get("claim_id") or ""), query=raw.get("query"), note=raw.get("note", ""))
        problems = verify_evidence(rec, corpus)
        if in_scope is not None and rec.passage_id not in in_scope:
            problems.append("passage outside research scope")
        if problems:
            rejected += 1
            block(ctx, "provenance_validator", "BeforeGraphWrite", "; ".join(problems), rec.id)
            continue
        accepted.setdefault(rec.id, rec.to_dict())
    records = [accepted[k] for k in sorted(accepted)]
    if records:
        ctx.emit(EventType.EVIDENCE_RETRIEVED, {"records": records}, generated=[r["id"] for r in records])
    proposals = _propose_closures(ctx, records)
    targeted = sum(1 for r in records if r.get("hypothesis_id"))
    books = len({r["book_id"] for r in records})
    note = f"; {'; '.join(ctx.notes[:3])}" if ctx.notes else ""
    return (f"{len(records)} evidence records from {books} books ({targeted} hypothesis-linked); {rejected} rejected"
            + (f"; {proposals} objection(s) proposed for closure with the new evidence" if proposals else "") + note)


SOURCE_CHECKS = ("single_source", "transcription_dependence")


def _propose_closures(ctx: Any, records: list[dict[str, Any]]) -> int:
    """New supporting witnesses may answer an objection about independent sources.  The agent only *proposes* that
    (basis: new evidence); a validator re-runs the check with the evidence and closes the objection only if it passes."""
    new_by_h: dict[str, list[str]] = {}
    for r in records:
        if r.get("hypothesis_id") and r.get("stance") == Stance.SUPPORTS.value:
            new_by_h.setdefault(r["hypothesis_id"], []).append(r["id"])
    n = 0
    for hid, ids in sorted(new_by_h.items()):
        reviews = ctx.state.reviews_for(hid)
        if not reviews:
            continue
        latest = max(reviews, key=lambda rv: (rv.round, rv.id))
        for o in latest.objections:
            if o.status == "raised" and o.check in SOURCE_CHECKS:
                ctx.emit(EventType.OBJECTION_RESOLUTION_PROPOSED, {
                    "hypothesis_id": hid, "review_id": latest.id, "objection_id": o.id, "basis": "new_evidence",
                    "evidence_ids": ids, "rationale": f"{len(ids)} new supporting record(s) from further witnesses"})
                n += 1
    return n
