"""Historical Semanticist: period-bound sense resolution for homonym-risk terms.

Every mention of a curated historical term (e.g. 消渴, 伤寒, 中风, 痰, 湿) gets
a TermResolution with a probability distribution over its senses — context
cues, anti-cues and the passage's date decide; low-confidence resolutions are
flagged as homonym risks and reach Gate G3.
"""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.events import EventType
from ...protocol.outputs import TermResolution
from .common import scope_passages

OUTPUT = "TermResolutionReport"
RISK_THRESHOLD = 0.6


def instructions(ctx: Any) -> str:
    return ("Resolve the period-bound sense of each flagged historical term mention. Use the passage context, the date "
            "and the curated senses; keep a probability distribution over senses (alternatives) and explain the "
            "decisive cues. Never map a sense to a modern disease here.")


def draft(ctx: Any) -> dict[str, Any]:
    pack = ctx.cap("domain")
    corpus = ctx.cap("corpus")
    terminology = pack.terminology
    out = []
    for p in scope_passages(ctx):
        norm = pack.variants.normalize_text(p.text)
        mentions = pack.lexicon.match(norm)
        context = {m.entry.term for m in mentions}
        year = corpus.year(p)
        seen: set[tuple[str, int]] = set()
        for m in mentions:
            term = terminology.term(m.entry.term)
            if term is None or len(term.senses) < 2 or (m.term_id, m.start) in seen:
                continue
            seen.add((m.term_id, m.start))
            sense, prob, alts, why = terminology.resolve(m.entry.term, norm, context, year)
            out.append({"term_id": m.term_id, "surface": p.text[m.start:m.end], "passage_id": p.id, "start": m.start,
                        "end": m.end, "sense_id": sense, "probability": prob, "alternatives": alts, "rationale": why})
    return {"resolutions": out}


def llm_draft(ctx: Any, full: dict[str, Any]) -> dict[str, Any]:
    return {"resolutions": [r for r in full["resolutions"] if r["probability"] < RISK_THRESHOLD and len(r["alternatives"]) > 1]}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    normalize = pack.variants.normalize_text
    merged = {(r["passage_id"], r["term_id"], r["start"]): r for r in (ctx.draft or {}).get("resolutions", [])}
    rejected = 0
    for r in output.get("resolutions", []):
        key = (r.get("passage_id"), r.get("term_id"), r.get("start"))
        pid, start, end = r.get("passage_id"), r.get("start"), r.get("end")
        entry = pack.lexicon.entry(str(r.get("term_id", "")))
        term = pack.terminology.term(entry.term) if entry else None
        ok = corpus.has_passage(pid) and term is not None and isinstance(start, int) and isinstance(end, int)
        if ok:
            text = corpus.passage(pid).text
            forms = {normalize(s) for s in entry.surfaces()}
            ok = 0 <= start < end <= len(text) and normalize(text[start:end]) in forms
            ok = ok and (r.get("sense_id") is None or any(s.id == r["sense_id"] for s in term.senses))
            ok = ok and 0.0 <= float(r.get("probability", -1)) <= 1.0
        if not ok:
            rejected += 1
            continue
        merged[key] = {**merged.get(key, {}), **r}
    records = []
    for (pid, term_id, start), r in sorted(merged.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1])):
        alts = {k: float(v) for k, v in (r.get("alternatives") or {}).items()}
        prob = float(r["probability"])
        res = TermResolution(
            id=stable_id("res", pid, term_id, start),
            term_id=term_id,
            surface=r.get("surface", ""),
            passage_id=pid,
            start=start,
            end=r["end"],
            sense_id=r.get("sense_id"),
            probability=round(prob, 4),
            alternatives=alts,
            homonym_risk=len(alts) > 1 and prob < RISK_THRESHOLD,
            rationale=r.get("rationale", ""),
        )
        records.append(res.to_dict())
    ctx.emit(EventType.TERM_RESOLVED, {"resolutions": records}, generated=[r["id"] for r in records])
    risky = sum(1 for r in records if r["homonym_risk"])
    return f"{len(records)} term mentions resolved; {risky} homonym risk(s)" + (f"; {rejected} model edits rejected" if rejected else "")
