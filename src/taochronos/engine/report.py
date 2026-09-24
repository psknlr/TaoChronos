"""The Discovery Report: research question → … → recommended human verification.

Twelve sections in a fixed order, every claim tied to evidence ids and every
score shown with its components.  What did not survive is reported as
clearly as what did.  Published as versioned artifacts (Markdown + JSON), with
the evidence table and knowledge graph beside them.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from typing import Any

from ..kernel.observability import agent_tree, research_metrics, research_tree
from ..protocol.base import to_jsonable
from ..protocol.confidence import DIMENSIONS
from ..protocol.evidence import Stance
from ..protocol.outputs import DiscoveryReport, ReportSection
from ..science.scoring import novelty

GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")
MARK = {"pass": "✓", "warn": "△", "fail": "✗", "pending": "…", "not_applicable": "—"}
STATUS_ZH = {"survived": "存活", "expert_approved": "专家认可", "proposed": "待审", "needs_revision": "待修订",
             "rejected": "被否决", "expert_rejected": "专家否决", "superseded": "已被修订版取代"}
KIND_ZH = {"lost_knowledge": "失传知识", "historical_testimony": "文本证词", "lost_source": "佚书线索", "concept_drift": "概念演变",
           "formula_evolution": "方剂演化", "renaming": "避讳改名", "association_rule": "关联规则", "hidden_association": "隐性关联",
           "contradiction": "矛盾分析", "cross_space_bridge": "跨空间桥接"}
DISCLAIMER = ("演示语料为未经核验的整理本（仅供方法演示）；本报告中的所有假说均为计算推断（Computational Hypothesis Space），"
              "不构成医学结论，需经专家核验（Gate G7）后方可视为研究发现。")


def _book(corpus: Any, book_id: str) -> str:
    return corpus.books[book_id].title if book_id in corpus.books else book_id


def _cite(corpus: Any, rec: Any) -> str:
    if rec.book_id == "modern-literature":
        return f"[现代文献] {rec.quote[:120]}（{rec.note}）"
    loc = rec.locator.label() if rec.locator else ""
    year = corpus.year(corpus.passage(rec.passage_id)) if corpus.has_passage(rec.passage_id) else None
    dyn = corpus.books[rec.book_id].dynasty if rec.book_id in corpus.books else ""
    when = f"{dyn}，约 {int(year)} 年" if year is not None else dyn
    return f"《{_book(corpus, rec.book_id)}》{loc}（{when}）「{rec.quote}」 `{rec.passage_id}[{rec.start}:{rec.end}]`"


def _gates(state: Any, hid: str) -> str:
    g = state.gates.get(hid, {})
    return " ".join(f"{name}{MARK.get(g[name].status, '?') if name in g else '…'}" for name in GATES)


def ranked(state: Any) -> list[Any]:
    live = [h for h in state.hypotheses.values() if h.status not in ("superseded", "rejected", "expert_rejected")]
    return sorted(live, key=lambda h: (-(h.discovery_score or 0.0), -h.elo, h.id))


def build(harness: Any, state: Any, session_id: str) -> tuple[DiscoveryReport, str, dict[str, Any]]:
    corpus = harness.corpus
    pack = harness.pack
    goal = state.goal
    top = ranked(state)
    sections: list[ReportSection] = []

    def add(title: str, lines: list[str], refs: list[str] | None = None) -> None:
        sections.append(ReportSection(title=title, body="\n".join(lines).strip() or "（无）", refs=sorted(set(refs or []))))

    # 1 ----------------------------------------------------------- question
    lines = [f"**{goal.question}**", ""]
    lines.append(f"- 焦点术语：{'、'.join(goal.focus_terms) or '（由问题自动识别）'}")
    lines.append(f"- 发现轨道：{', '.join(goal.tracks)}")
    lines.append(f"- 时间范围：{goal.temporal_scope.label() if goal.temporal_scope else '全部时期'}（时间基准：{goal.time_basis}）")
    if goal.holdout_after is not None:
        lines.append(f"- 时间留出：≥ {goal.holdout_after} 年的文本对研究不可见（Historical Time Machine）")
    if goal.forbidden_assumptions:
        lines.append(f"- 禁止假设：{'；'.join(goal.forbidden_assumptions)}")
    lines.append(f"- 必需门控：{', '.join(goal.required_validation)}；独立来源 ≥ {goal.required_evidence.min_independent_sources}")
    lines.append(f"- 研究契约摘要（不可变）：`{state.goal_digest[:16]}`")
    add("1. 研究问题 · Research Question", lines)

    # 2 ----------------------------------------------------------- existing understanding
    focus_labels = {t.split(":", 1)[-1] for t in goal.focus_terms}
    for h in top:
        focus_labels |= {t.split(":", 1)[-1] for t in h.terms[:2]}
    known = [f for f in pack.known_findings if focus_labels & set(f.get("terms", []))]
    lines = [f"- **{f.get('id')}**：{f.get('statement', '')}" + (f"（{f['source']}）" if f.get("source") else "") for f in known[:12]]
    m = state.corpus
    if m is not None:
        lines.append("")
        lines.append(f"语料范围：{len(m.book_ids)} 部书、{len(m.passage_ids)} 段文本；时期覆盖："
                     + "，".join(f"{pack.periods.label(p)} {n}" for p, n in m.coverage.items()))
        lines += [f"- ⚠ {w}" for w in m.warnings]
    add("2. 既有认识 · Existing Understanding", lines)

    # 3 ----------------------------------------------------------- corpus evidence
    ledger = sorted((e for e in state.evidence.values() if e.hypothesis_id is None and e.stance == Stance.NEUTRAL),
                    key=lambda e: (-(e.retrieval_score or 0), e.id))[:12]
    lines = [f"- {_cite(corpus, e)}" + (f" · 检索路径 {','.join(e.routes)}" if e.routes else "") for e in ledger]
    add("3. 语料证据 · Corpus Evidence", lines, [e.id for e in ledger])

    # 4 ----------------------------------------------------------- temporal pattern
    evo = sorted((a for a in state.analyses.values() if a.get("kind") == "evolution"), key=lambda a: a["analysis_id"])
    lines = []
    for a in evo:
        res = a.get("result", {})
        label = "概念演变" if res.get("kind") == "concept_timeline" else "方剂谱系"
        lines.append(f"- **{label}**：{res.get('narrative', '')}")
    add("4. 时间模式 · Temporal Pattern", lines, [a.get("target_id") for a in evo if a.get("target_id")])

    # 5 ----------------------------------------------------------- knowledge network
    relations = Counter(c.relation.value for c in state.claims.values())
    lineage = Counter(e.relation for e in state.lineage.values())
    lines = ["- 主张超边（claims）：" + "，".join(f"{k} {v}" for k, v in relations.most_common()),
             "- 知识谱系（lineage）：" + "，".join(f"{k} {v}" for k, v in lineage.most_common())]
    for o in sorted(state.observations.values(), key=lambda o: (-o.score, o.id)):
        if o.kind in ("association_rule", "hidden_association", "community"):
            lines.append(f"- {o.title}：{o.summary}")
    add("5. 知识网络 · Knowledge Network", lines)

    # 6 ----------------------------------------------------------- observations
    lines = ["| 观察 | 类型 | 标题 | 关键统计 |", "|---|---|---|---|"]
    for o in sorted(state.observations.values(), key=lambda o: (o.kind, -o.score, o.id)):
        s = o.statistics
        key = next((f"{k}={s[k]}" for k in ("p_absence", "p_value", "empirical_p", "lift", "jsd", "temporal_gap_years", "size") if k in s), "—")
        lines.append(f"| `{o.id}` | {KIND_ZH.get(o.kind, o.kind)} | {o.title} | {key} |")
    add("6. 新观察 · New Observations", lines, list(state.observations))

    # 7 ----------------------------------------------------------- hypotheses
    lines = []
    for i, h in enumerate(top, 1):
        comp = h.discovery_components or {}
        comp_s = " ".join(f"{k}={comp[k]:.2f}" for k in ("E", "N", "R", "T", "F", "A") if k in comp)
        lines.append(f"**H{i} `{h.id}`**（{KIND_ZH.get(h.kind, h.kind)} · {STATUS_ZH.get(h.status, h.status)} · 第 {h.generation} 代 · "
                     f"Elo {h.elo:.0f}）")
        lines.append(f"> {h.statement}")
        lines.append(f"- 发现分数 D = {h.discovery_score if h.discovery_score is not None else '—'}（{comp_s}）")
        lines.append(f"- 门控：{_gates(state, h.id)}")
        if h.qualifiers:
            lines.append(f"- 修订限定：{json.dumps(h.qualifiers, ensure_ascii=False)}；{h.revision_note}")
        if h.testable_prediction:
            lines.append(f"- 可检验预测：{h.testable_prediction}")
        lines.append("")
    add("7. 候选假说 · Candidate Hypotheses", lines, [h.id for h in top])

    # 8 ----------------------------------------------------------- supporting evidence
    lines, refs = [], []
    for i, h in enumerate(top[:10], 1):
        lines.append(f"**H{i}**")
        for eid in h.supporting_evidence[:6]:
            e = state.evidence.get(eid)
            if e is not None:
                lines.append(f"- {_cite(corpus, e)}")
                refs.append(eid)
        modern = [e for e in state.evidence.values() if e.hypothesis_id == h.id and e.stance == Stance.CONTEXT]
        for e in modern:
            lines.append(f"- （背景，不作为支持证据）{_cite(corpus, e)}")
    add("8. 支持证据 · Supporting Evidence", lines, refs)

    # 9 ----------------------------------------------------------- counter-evidence
    lines = []
    for i, h in enumerate(top[:10], 1):
        reviews = state.reviews_for(h.id)
        latest = max(reviews, key=lambda r: (r.round, r.id)) if reviews else None
        objections = [o for o in (latest.objections if latest else []) if o.severity != "info"]
        counter = [state.evidence[e] for e in h.contradictory_evidence if e in state.evidence]
        if not objections and not counter:
            continue
        lines.append(f"**H{i}**")
        for o in objections:
            lines.append(f"- [{o.severity}/{o.check}]{'（已由修订解决）' if o.resolved else ''} {o.detail}")
        for e in counter[:4]:
            lines.append(f"- 反证：{_cite(corpus, e)}")
    add("9. 反证 · Counterevidence", lines)

    # 10 ---------------------------------------------------------- alternatives
    lines = []
    for i, h in enumerate(top[:10], 1):
        if h.alternative_explanations:
            lines.append(f"**H{i}**：" + "；".join(h.alternative_explanations))
    add("10. 替代解释 · Alternative Explanations", lines)

    # 11 ---------------------------------------------------------- confidence
    lines = ["| 假说 | 文本 | 语义 | 历史归属 | 医学解释 | 现代生物医学有效性 | 向量 |", "|---|---|---|---|---|---|---|"]
    for i, h in enumerate(top[:12], 1):
        view = h.confidence.scholar_view()
        vec = ", ".join(f"{d}={getattr(h.confidence, d):.2f}" for d in DIMENSIONS if getattr(h.confidence, d) is not None)
        lines.append(f"| H{i} | {view['Text confidence']} | {view['Semantic confidence']} | {view['Historical attribution']} | "
                     f"{view['Medical interpretation']} | {view['Modern biomedical validity']} | {vec}; penalty={h.confidence.contradiction_penalty} |")
    lines.append("")
    lines.append("“现代生物医学有效性”默认为 unknown：历史文本中的记载不等于现代疗效证据。")
    add("11. 置信度 · Confidence", lines)

    # 12 ---------------------------------------------------------- human verification
    lines, recs = [], []
    for i, h in enumerate(top, 1):
        if h.status == "survived" and len(recs) < 8:
            recs.append(h.id)
            lines.append(f"- 专家评审 H{i} `{h.id}`（D={h.discovery_score}）：`taochronos review {session_id} {h.id} --approve|--reject --expert <姓名>`")
    for c in sorted(state.changes.values(), key=lambda c: c.id):
        if c.status == "proposed":
            p = c.payload
            flag = "（等价候选，仅专家可认定）" if p.get("equivalence_candidate") else ""
            lines.append(f"- 术语映射待决 `{c.id}`：{p.get('historical_label', p.get('sense_id'))} —{p.get('relation')}→ "
                         f"{p.get('modern_label', p.get('concept_id'))}{flag}")
    contested = sorted({pid for h in top for eid in h.supporting_evidence if (e := state.evidence.get(eid))
                        for pid in [e.passage_id] if (a := state.philology.get(pid)) and a.contested_at(e.start, e.end)})
    for pid in contested:
        lines.append(f"- 校勘核对：{pid} 的争议读法影响证据")
    failed = [h for h in state.hypotheses.values() if h.status in ("rejected", "expert_rejected")]
    if failed:
        lines.append("")
        lines.append("**未能存活的假说（同样是结果）**")
        for h in sorted(failed, key=lambda h: h.id):
            reasons = [o for r in state.reviews_for(h.id) for o in r.objections if o.severity == "critical" and not o.resolved]
            lines.append(f"- `{h.id}` {h.statement[:70]}… — " + ("；".join(f"{o.check}: {o.detail[:60]}" for o in reasons) or h.status))
    add("12. 建议人工核验 · Recommended Human Verification", lines, recs)

    # appendix ----------------------------------------------------- trace
    stop = state.stop or {}
    metrics = scientific_metrics(state)
    lines = [f"- 停止状态：{stop.get('status', state.status)}；原因：{'；'.join(stop.get('reasons', [])) or '—'}",
             "- 研究指标：" + json.dumps(metrics, ensure_ascii=False),
             "- 运行轨迹（智能体树、工具调用、模型用量）见 trace 制品；它们不属于科学结论。",
             "", "```", research_tree(state), "```"]
    add("附录 · 假说谱系 · Research Tree", lines)

    evidence_refs = sorted({e for h in top for e in h.supporting_evidence})
    report = DiscoveryReport(
        title=f"TaoChronos 发现报告：{goal.question}",
        question=goal.question,
        sections=sections,
        ranked_hypotheses=[h.id for h in top],
        recommended_verification=recs,
        evidence_refs=evidence_refs,
    )
    status = (state.stop or {}).get("status", state.status)
    md = [f"# {report.title}", "", f"> 会话 `{session_id}` · 画像 `{state.profile}` · 状态 {status} · 轮次 {state.round}", "",
          f"> {DISCLAIMER}", ""]
    for s in sections:
        md += [f"## {s.title}", "", s.body, ""]
    payload = {
        "report": report.to_dict(),
        "hypotheses": [to_jsonable(h) for h in top],
        "rejected": [to_jsonable(h) for h in failed],
        "metrics": metrics,
        "stop": {k: v for k, v in stop.items() if k != "signals"},
        "novelty_reference": [novelty(h.terms, pack.known_findings)[1] for h in top],
    }
    return report, "\n".join(md), payload


def evidence_table(harness: Any, state: Any) -> str:
    corpus = harness.corpus
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["evidence_id", "hypothesis_id", "stance", "book", "passage_id", "locator", "start", "end", "quote", "year",
                     "retrieval_method", "evidence_domain", "textual", "philological", "gates"])
    for e in sorted(state.evidence.values(), key=lambda e: e.id):
        year = corpus.year(corpus.passage(e.passage_id)) if corpus.has_passage(e.passage_id) else ""
        gates = ";".join(f"{g}={r.status}" for g, r in sorted(state.gates.get(e.id, {}).items()))
        writer.writerow([e.id, e.hypothesis_id or "", e.stance.value, _book(corpus, e.book_id), e.passage_id,
                         e.locator.label() if e.locator else "", e.start, e.end, e.quote, year, e.retrieval_method,
                         e.evidence_domain.value, e.confidence.textual, e.confidence.philological, gates])
    return buf.getvalue()


def publish_report(harness: Any, session: Any) -> list[Any]:
    state = session.state
    report, md, payload = build(harness, state, session.id)
    status = "published" if report.evidence_refs else "draft"
    arts = harness.artifacts
    main = arts.publish(session, kind="discovery_report", title="Discovery Report", content=md, filename="report.md",
                        media_type="text/markdown", generator="kernel:report", evidence_refs=report.evidence_refs,
                        hypothesis_refs=report.ranked_hypotheses, status=status)
    js = arts.publish(session, kind="discovery_report", title="Discovery Report (JSON)",
                      content=json.dumps(payload, ensure_ascii=False, indent=1, default=str), filename="report.json",
                      media_type="application/json", generator="kernel:report", evidence_refs=report.evidence_refs,
                      hypothesis_refs=report.ranked_hypotheses, parent_artifacts=[main.id], status=status)
    table = arts.publish(session, kind="evidence_table", title="Evidence Ledger", content=evidence_table(harness, state),
                         filename="evidence.csv", media_type="text/csv", generator="kernel:report",
                         evidence_refs=sorted(state.evidence), status="published" if state.evidence else "draft")
    export = harness.capabilities.get("graph_export", "json")
    graph = arts.publish(session, kind="knowledge_graph", title="Claim Hypergraph",
                         content=json.dumps(export(list(state.claims.values()), list(state.lineage.values()), corpus_books(harness)),
                                            ensure_ascii=False, default=str),
                         filename="graph.json", media_type="application/json", generator="kernel:report")
    trace = arts.publish(session, kind="trace", title="Run Trace",
                         content=json.dumps({"agent_tree": agent_tree(session.events()), "metrics": research_metrics(state),
                                             "stop_signals": (state.stop or {}).get("signals", {})}, ensure_ascii=False, indent=1,
                                            default=str),
                         filename="trace.json", media_type="application/json", generator="kernel:report")
    return [main, js, table, graph, trace]


SCIENTIFIC_METRICS = ("claims", "rejected_claims", "evidence_count", "counter_evidence", "observations", "contradictions",
                      "lineage_edges", "hypotheses", "hypothesis_survival", "source_diversity", "gates")


def scientific_metrics(state: Any) -> dict[str, Any]:
    m = research_metrics(state)
    return {k: m[k] for k in SCIENTIFIC_METRICS}


def corpus_books(harness: Any) -> dict[str, str]:
    return {b.id: b.title for b in harness.corpus.books.values()}
