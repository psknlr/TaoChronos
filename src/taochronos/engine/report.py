"""The Discovery Report: research question → … → recommended human verification.

Twelve numbered sections in a fixed order, the contract's evaluation right after the question, and the
appendices (sources dossier, research tree); every claim tied to evidence ids and every score shown with its
components.  What did not survive is reported as clearly as what did.  Published as versioned artifacts (Markdown + JSON), with
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
HYPOTHESIS_NOTE = "本报告中的所有假说均为计算推断（Computational Hypothesis Space），不构成医学结论，需经专家核验（Gate G7）后方可视为研究发现。"


ACCEPTANCE_ZH = {"research_accepted": "研究被接受", "needs_expert": "需专家判定", "inconclusive": "不确定（正式结论）",
                 "budget_exhausted": "预算耗尽", "execution_finished": "已执行、未评估"}
HYP_ACCEPTANCE_ZH = {"accepted": "接受", "needs_expert": "需专家", "inconclusive": "不确定", "rejected": "已否证"}
INFERENCE_ZH = {"absence": "默证（后世不再记载）", "testimony": "证词", "statistical_comparison": "统计比较", "statistical_association": "统计关联",
                "abduction": "溯因", "lineage": "谱系", "comparison": "比较", "analogy": "类比"}
STRENGTH_ZH = {"robust": "稳健", "supported": "有支持", "consistent_with": "仅相容"}
RIVAL_ZH = {"excluded": "［已排除］", "open": "［未排除］", "unaddressed": "［未处理］", "not_applicable": "［不适用］"}
CLOSURE_ZH = {"validator_rerun": "验证器复核通过", "new_evidence": "新证据经验证", "scope_restriction": "修订收窄经验证", "expert": "专家判定"}
CONFIRM_ZH = {"confirmed": "预测在留存材料中成立", "refuted": "预测在留存材料中不成立", "untestable": "留存材料无法判定"}


def disclaimer(corpus: Any) -> str:
    """What the evidence rests on: the demo corpus, or the licensed sources of a full corpus store."""
    if not getattr(corpus, "large", False):
        return DISCLAIMER
    licences = sorted({b.source.license.removesuffix("（本书为近代著作）") for b in corpus.books.values() if b.source.license})
    origins = sorted({b.source.origin for b in corpus.books.values() if b.source.origin})
    verified = sum(1 for b in corpus.books.values() if b.source.verified)
    sources = set(getattr(corpus, "sources", {}).values())
    reading = "白文经机器断句抽取" if sources <= {"kanripo"} else "白文（四库本）经机器断句抽取，笈成本沿用整理者标点"
    undated = sum(1 for b in corpus.books.values() if "成书年代无从考定" in (b.notes or ""))
    dating = f"{undated} 部成书年代无从考定，按清代保守计；" if undated else ""
    return (f"语料：{len(corpus.books)} 部古籍录文（来源：{'；'.join(origins)}；授权：{'、'.join(licences)}），"
            f"{len(corpus.books) - verified} 部未经本项目逐字校勘；{dating}{reading}，引文均为原文逐字。" + HYPOTHESIS_NOTE)


def _book(corpus: Any, book_id: str) -> str:
    return corpus.books[book_id].title if book_id in corpus.books else book_id


def _cite(corpus: Any, rec: Any) -> str:
    if rec.book_id == "modern-literature":
        return f"[现代文献] {rec.quote[:120]}（{rec.note}）"
    loc = rec.locator.label() if rec.locator else ""
    passage = corpus.passage(rec.passage_id) if corpus.has_passage(rec.passage_id) else None
    year = corpus.year(passage) if passage is not None else None
    dyn = corpus.books[rec.book_id].dynasty if rec.book_id in corpus.books else ""
    layer = next((t.split(":", 1)[1] for t in (passage.tags if passage is not None else []) if t.startswith("layer:")), None)
    if layer:
        dyn = f"{layer}·{passage.temporal.dynasty}" if passage.temporal.dynasty and passage.temporal.dynasty != dyn else layer
    when = f"{dyn}，约 {int(year)} 年" if year is not None else dyn
    return f"《{_book(corpus, rec.book_id)}》{loc}（{when}）「{rec.quote}」 `{rec.passage_id}[{rec.start}:{rec.end}]`"


def note_labels(note: str | None) -> list[str]:
    """What a ledger record's note says of the search hit it came from (``hit_note`` in agents/procedures/evidence.py,
    ADR 0023): the parts after ``routes: …`` — each ``via`` (the pair of names that found the passage, what it writes,
    how the names relate, the sources) and each flag in words (年代存疑, 同名异物 …).  [] for a note that is not a hit's (a
    replication's reason), or a hit's found as asked.  Only a search's own record says them (:func:`record_labels`)."""
    parts = (note or "").split("; ")
    if not parts[0].startswith("routes:"):
        return []
    return [" ".join(p.split()) for p in parts[1:] if p.strip() and not p.startswith("routes:")]


def record_labels(rec: Any) -> list[str]:
    """The labels of a ledger record the search put there (``retrieval:hybrid``, the one path that writes
    ``hit_note``): :func:`note_labels` of its note; [] for any other record — a model's note is its own words, whatever
    it looks like."""
    return note_labels(rec.note) if getattr(rec, "retrieval_method", None) == "retrieval:hybrid" else []


# what the labels mean, under a list that shows them.  A via says which pair of names found the passage, not which of
# the two was asked: asked for the drug itself, the name the passage writes stands before the arrow, and a span two
# queries found (金铃子 and 川楝子) keeps the labels of both (agents/procedures/evidence.py _via_notes)
LABELS_NOTE = ("注：「via 甲→乙」表示此段是经乙（所指之药）与它的另一名甲这一对名字检出的：或问甲而此段写乙，或问乙而此段写甲"
               "（几个检索词都检出同一段时两种情形可能并存，以原文为准）；无箭头的「via 乙（写作丙）」为检索乙时检出、此段写作丙。"
               "括注依次为：此段所写之名（写作，甲、乙之外者）；二名关系（未注即异名，品种/产地名、炮制/加工名等未必同物，"
               "「相关」为词表所关联之词、并非同一味药）；「候选」为未经核定的配对，「多作普通词语」为此名多不指药；依据。"
               "「读作 甲→乙」为多义之名甲在此段的读法（p 为其概率）。年代存疑、同名异物等标记表示此段未必指所问之药。引用前须核对原文。")


def _cell(text: str) -> str:
    """A free-text cell of the evidence table, kept text in a spreadsheet: one starting like a formula gets a quote."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


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

    # 1b ---------------------------------------------------------- contract evaluation (execution is not acceptance)
    acc = state.acceptance or {}
    lines = [f"**研究结论：{ACCEPTANCE_ZH.get(acc.get('status', ''), acc.get('status', '未评估'))}**（执行状态：{acc.get('execution', state.status)}）", ""]
    lines += [f"- {r}" for r in acc.get("reasons", [])]
    outputs = acc.get("outputs") or {}
    if outputs:
        lines.append("- 必需产出：" + "，".join(f"{k} {'✓' if v else '✗'}" for k, v in outputs.items()))
    if acc.get("human_criteria"):
        lines.append("- 仅能由人判定的合同条款：" + "；".join(acc["human_criteria"]))
    judged = {j["hypothesis_id"]: j for j in acc.get("hypotheses", [])}
    if judged:
        lines += ["", "| 假说 | 结论 | 未满足的条款 |", "|---|---|---|"]
        for i, h in enumerate(top, 1):
            j = judged.get(h.id)
            if j is None:
                continue
            missing = [f"{c['id']}（{c['observed'][:40]}）" for c in j["criteria"] if c["status"] != "pass"]
            lines.append(f"| H{i} | {HYP_ACCEPTANCE_ZH.get(j['status'], j['status'])} | {'；'.join(missing) or '—'} |")
    lines.append("")
    lines.append("研究结论由验证器按研究合同判定：任务执行完毕不等于研究被接受；“需专家”表示机器可检条款已满足、仍待专家（G7）判断；"
                 "“不确定”是正式结论，不是失败。")
    add("研究合同评估 · Contract Evaluation", lines, list(judged))

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
    labels = {e.id: record_labels(e) for e in ledger}  # found under another name of a drug, or flagged: says so
    lines = [f"- {_cite(corpus, e)}" + (f" · 检索路径 {','.join(e.routes)}" if e.routes else "")
             + "".join(f" · {x}" for x in labels[e.id]) for e in ledger]
    lines += ["", LABELS_NOTE] if any(labels.values()) else []
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
                     f"探索优先级 {h.elo:.0f}）")
        lines.append(f"> {h.statement}")
        lines.append(f"- 发现分数 D = {h.discovery_score if h.discovery_score is not None else '—'}（{comp_s}；启发式排序，不是可信度）")
        lines.append(f"- 门控：{_gates(state, h.id)}")
        w = state.warrants.get(h.warrant_id or "") if h.warrant_id else None
        if w:
            rivals = [c for c in w.get("competing", []) if c.get("status") in ("open", "unaddressed")]
            lines.append(f"- 推理依据：{INFERENCE_ZH.get(w['inference'], w['inference'])} · 强度 {STRENGTH_ZH.get(w['strength'], w['strength'])}"
                         + (f" · 未排除的替代解释：{'、'.join(c['label'] for c in rivals)}" if rivals else " · 替代解释均已排除"))
        if h.confirmation:
            lines.append(f"- 留存材料确认：{CONFIRM_ZH.get(h.confirmation.get('status'), h.confirmation.get('status'))}"
                         f"（{h.confirmation.get('passages')} 段留存文本）")
        st = h.statistics or {}
        if st.get("method"):
            effect = "，".join(f"{k}={v}" for k, v in (st.get("effect") or {}).items())
            p_ = next((f"{k}={st[k]}" for k in ("p_value", "p_absence", "empirical_p") if isinstance(st.get(k), (int, float))), "")
            lines.append(f"- 统计：{st['method']}；原假设：{st.get('null', '—')}；效应 {effect or '—'}；{p_}"
                         f"；来源家族 {st.get('clusters', '—')}；校正：{st.get('correction', '—')}")
            absence = st.get("absence") or {}
            if absence:
                lines.append(f"- 缺失的陈述层级：第 {absence.get('level')} 层 — {absence.get('statement')}；{absence.get('not_asserted', '')}")
        if h.novelty_profile:
            lines.append(f"- 新颖性：{h.novelty_profile.get('statement')}（文献检索：{(h.novelty_profile.get('literature') or {}).get('status', '未评估')}；"
                         "从不声称“首次发现”）")
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
            state_note = ""
            if o.resolved:
                state_note = f"（已关闭：{CLOSURE_ZH.get(o.closure, o.closure)}）"
            elif o.status == "resolution_proposed":
                state_note = f"（已提出解决方案，待验证器或专家裁决：{(o.proposal or {}).get('basis', '')}）"
            lines.append(f"- [{o.severity}/{o.check}{'·硬' if o.hard else ''}]{state_note} {o.detail}")
        for e in counter[:4]:
            lines.append(f"- 反证：{_cite(corpus, e)}")
    add("9. 反证 · Counterevidence", lines)

    # 10 ---------------------------------------------------------- alternatives
    lines = []
    for i, h in enumerate(top[:10], 1):
        w = state.warrants.get(h.warrant_id or "") if h.warrant_id else None
        if w and w.get("competing"):
            lines.append(f"**H{i}**（{w['discovery_type']}）")
            for c in w["competing"]:
                lines.append(f"- {RIVAL_ZH.get(c['status'], c['status'])} {c['label']}：{c.get('basis', '')}"
                             + (f"；判别检验：{c['test']}" if c.get("status") in ("open", "unaddressed") and c.get("test") else ""))
        elif h.alternative_explanations:
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

    # appendix ----------------------------------------------------- sources (治学)
    dossiers = sorted((a for a in state.analyses.values() if a.get("kind") == "sources_dossier"), key=lambda a: a["analysis_id"])
    if dossiers:
        lines = ["由 TaoChronos-Scholar 在全部语料上逐字检得：这是文本源流的描述，不是假说，不经门控；剂量折算为历史计量的学术估值，"
                 "不构成用药建议。", ""]
        for a in dossiers:
            r = a.get("result", {})
            kind = {"formula": "方源考", "herb": "药性源流", "term": "术语源流"}.get(r.get("kind"), r.get("kind"))
            lines.append(f"**{r.get('target')}**（{kind}）：{r.get('headline', '')}")
            lines += [f"- {x}" for x in r.get("lines", [])]
            for w in r.get("witnesses", []):
                lines.append(f"  - {w.get('role', '')}：{w.get('locator', '')} `{w['passage_id']}`「{w.get('quote', '')[:80]}」")
            lines.append("")
        add("附录 · 源流考证 · Sources Dossier", lines, [a["analysis_id"] for a in dossiers])

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
    verdict = ACCEPTANCE_ZH.get((state.acceptance or {}).get("status", ""), "未评估")
    md = [f"# {report.title}", "", f"> 会话 `{session_id}` · 画像 `{state.profile}` · 执行 {status} · 研究结论 {verdict} · 轮次 {state.round}", "",
          f"> {disclaimer(corpus)}", ""]
    for s in sections:
        md += [f"## {s.title}", "", s.body, ""]
    payload = {
        "report": report.to_dict(),
        "hypotheses": [to_jsonable(h) for h in top],
        "rejected": [to_jsonable(h) for h in failed],
        "metrics": metrics,
        "stop": {k: v for k, v in stop.items() if k != "signals"},
        "acceptance": dict(state.acceptance or {}),
        "warrants": [state.warrants[h.warrant_id] for h in top if h.warrant_id in state.warrants],
        "novelty_reference": [novelty(h.terms, pack.known_findings)[1] for h in top],
    }
    return report, "\n".join(md), payload


def evidence_table(harness: Any, state: Any) -> str:
    """The Evidence Ledger as CSV, one row per record; ``note`` last: why the record is there — a search hit's routes and
    labels (``routes: alias; via 国老→甘草（别名录（中醫笈成））``, see :func:`note_labels`), a replication's reason."""
    corpus = harness.corpus
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["evidence_id", "hypothesis_id", "stance", "book", "passage_id", "locator", "start", "end", "quote", "year",
                     "retrieval_method", "evidence_domain", "textual", "philological", "gates", "note"])
    for e in sorted(state.evidence.values(), key=lambda e: e.id):
        year = corpus.year(corpus.passage(e.passage_id)) if corpus.has_passage(e.passage_id) else ""
        gates = ";".join(f"{g}={r.status}" for g, r in sorted(state.gates.get(e.id, {}).items()))
        writer.writerow([e.id, e.hypothesis_id or "", e.stance.value, _book(corpus, e.book_id), e.passage_id,
                         e.locator.label() if e.locator else "", e.start, e.end, e.quote, year, e.retrieval_method,
                         e.evidence_domain.value, e.confidence.textual, e.confidence.philological, gates, _cell(e.note or "")])
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
                         evidence_refs=sorted(e for e in state.evidence if e not in state.retractions),
                         status="published" if state.evidence else "draft")
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
