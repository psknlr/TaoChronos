"""Meta-Reviewer: reads all reviews and scores, finds systemic weaknesses, recommends the next round.

Recommendations are drawn from a closed action vocabulary the Director (and
the harness) understand: ``gather_evidence`` (replication gap, G5),
``revise`` (pending revisions), ``resolve_terms`` (homonymy),
``sensitivity`` (re-run lost-knowledge detection at another pivot),
``expert_review`` (a human must judge) and ``investigate_contradiction``.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any

from ...protocol.base import stable_id
from ...protocol.events import EventType
from ...protocol.research import Decision
from ...science.stats import jaccard
from .common import surface

OUTPUT = "MetaReview"
ACTIONS = ("gather_evidence", "revise", "resolve_terms", "sensitivity", "expert_review", "investigate_contradiction")
ISSUE_NOTES = {
    "sample_size": "语料覆盖不足：部分时期文本过少，缺失类结论证据力有限",
    "single_source": "独立来源不足：多数假说只有一个独立来源",
    "transcription_dependence": "证据相互转录：表面上的多源实为同一传本",
    "homonym": "同名异义：关键术语的义项判定不稳定",
    "edition_variant": "异文：证据落在有校勘争议的读法上",
    "statistical": "统计显著性不足：需更大样本或多重检验校正后仍显著的结果",
    "earliest_source": "后世仍有共现：失传结论需区分“不再明确记载”与“完全消失”",
    "counterexample": "反例：所谓隐性关联在文本中已有共现",
    "lineage_strength": "谱系证据薄弱：共同核心不足",
}


def instructions(ctx: Any) -> str:
    return ("Synthesise the reviews and scores of this round: name systemic weaknesses (with counts), flag duplicate "
            f"hypotheses, and recommend next steps using only these actions: {', '.join(ACTIONS)}. Each recommendation "
            "needs a target (hypothesis id, term or 'D1') and a reason. Summarise the state of the research honestly, "
            "including what did not survive.")


def draft(ctx: Any) -> dict[str, Any]:
    s = ctx.state
    issues: Counter = Counter()
    for r in s.reviews.values():
        for o in r.objections:
            if not o.resolved and o.severity in ("critical", "major"):
                issues[o.check] += 1
    systemic = [{"check": k, "count": v, "note": ISSUE_NOTES.get(k, "")} for k, v in issues.most_common()]
    recs: list[dict[str, Any]] = []
    active = sorted(s.active_hypotheses(), key=lambda h: (-h.elo, h.id))
    for h in active:
        if s.gate_status(h.id, "G5") in ("warn", "fail") and h.status in ("survived", "proposed"):
            recs.append({"action": "gather_evidence", "target": h.id, "reason": f"G5 {s.gate_status(h.id, 'G5')}: 需要独立来源复核"})
        if h.status == "needs_revision":
            recs.append({"action": "revise", "target": h.id, "reason": "Skeptic 退回修订"})
    homonym_terms = sorted({t for r in s.reviews.values() for o in r.objections if o.check == "homonym" and not o.resolved
                            for t in s.hypotheses[r.hypothesis_id].terms[:1]})
    for t in homonym_terms:
        recs.append({"action": "resolve_terms", "target": t, "reason": f"「{surface(t)}」义项判定不稳定"})
    lost = [h for h in s.hypotheses.values() if h.kind == "lost_knowledge"]
    already = any(a.get("method") == "absence_probability" and a.get("round", 0) > 1 for a in s.analyses.values())
    if lost and not already and not any(h.status in ("survived", "expert_approved") for h in lost) and ctx.task.round <= 1:
        recs.append({"action": "sensitivity", "target": "D1", "pivot_year": 1127,
                     "reason": "失传知识假说均未存活：以南宋（1127）为分界做敏感性分析"})
    for h in active:
        if h.status == "survived" and (h.discovery_score or 0) >= 0.5:
            recs.append({"action": "expert_review", "target": h.id, "reason": "已通过自动门控，需要专家判断（G7）"})
    for c in sorted(s.contradictions.values(), key=lambda c: c.id):
        if c.label == "contradiction" and not c.resolved:
            recs.append({"action": "investigate_contradiction", "target": c.id, "reason": c.explanation[:80]})
    duplicates = []
    for a, b in combinations(sorted(active, key=lambda h: h.id), 2):
        if a.kind == b.kind and a.terms and jaccard(set(a.terms), set(b.terms)) >= 0.8 and a.parent_id != b.id and b.parent_id != a.id:
            duplicates.append([a.id, b.id])
    board = [{"hypothesis_id": h.id, "elo": h.elo, "discovery_score": h.discovery_score, "status": h.status, "kind": h.kind}
             for h in active[:10]]
    statuses = Counter(h.status for h in s.hypotheses.values())
    summary = (f"第 {ctx.task.round} 轮：共 {len(s.hypotheses)} 个假说（" + "，".join(f"{k} {v}" for k, v in sorted(statuses.items()))
               + "）；主要系统性问题：" + ("、".join(f"{i['check']}×{i['count']}" for i in systemic[:4]) or "无") + "。")
    return {"summary": summary, "systemic_issues": systemic, "recommendations": recs, "duplicates": duplicates, "leaderboard": board}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    recs = [r for r in output.get("recommendations", []) if r.get("action") in ACTIONS]
    result = {**output, "recommendations": recs}
    aid = stable_id("meta", ctx.task.round, ctx.task.id)
    ctx.emit(EventType.ANALYSIS_RECORDED, {"analysis_id": aid, "target_id": None, "kind": "meta_review", "method": ctx.route.mode,
                                           "round": ctx.task.round, "result": result}, generated=[aid])
    decision = Decision(id=stable_id("dec", "meta", ctx.task.round, ctx.task.id), kind="recommendation",
                        summary=output.get("summary", "")[:300],
                        rationale="; ".join(f"{r['action']}→{r.get('target', '')}" for r in recs[:12]),
                        made_by=ctx.actor.id, refs=sorted({r["target"] for r in recs if r.get("target")}))
    ctx.emit(EventType.DECISION_RECORDED, {"decisions": [decision.to_dict()]}, generated=[decision.id])
    return f"{len(recs)} recommendation(s); {len(output.get('systemic_issues', []))} systemic issue(s)"
