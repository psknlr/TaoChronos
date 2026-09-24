"""Hypothesis Generator: observations → testable, evidence-bound hypotheses; revisions after review.

Every hypothesis carries verbatim supporting evidence, structured predictions
that a later corpus (or the Historical Time Machine) can check, alternative
explanations, and philological / anachronism risk labels.  It lives in the
Computational-Hypothesis space: it is an inference *about* the texts, never
a statement of medical fact.  Revisions narrow a hypothesis (scope, sense,
reading, status) in response to specific objections; they never delete the
counter-evidence.
"""

from __future__ import annotations

from typing import Any

from ...kernel.hooks import HookPoint
from ...protocol.base import stable_id
from ...protocol.concepts import KnowledgeSpace
from ...protocol.confidence import ConfidenceVector
from ...protocol.documents import YearRange
from ...protocol.events import EventType
from ...protocol.evidence import EvidenceRecord, Stance
from ...protocol.hypothesis import Hypothesis, Prediction
from .common import cluster_fn, evidence_from_claim, evidence_record, locate, surface, year_fn

OUTPUT = "HypothesisSet"
CAPS = {"contradiction": 4, "lost_knowledge": 3, "hidden_association": 2, "concept_drift": 3, "formula_evolution": 3,
        "association_rule": 2, "renaming": 1, "lost_source": 2, "historical_testimony": 2}
MAX_SUPPORT = 6


def output_schema_for(ctx: Any) -> str:
    return "RevisionSet" if ctx.task.kind == "revise_hypotheses" else "HypothesisSet"


def instructions(ctx: Any) -> str:
    if ctx.task.kind == "revise_hypotheses":
        return ("Revise each hypothesis listed under 'Hypotheses to revise' so that it answers the Skeptic's unresolved "
                "objections by narrowing it: restrict its scope (e.g. 'in the surveyed corpus'), specify the sense of an "
                "ambiguous term, make it conditional on a reading, or mark it exploratory. Record what you narrowed in "
                "'qualifiers' (keys: scope, sense, reading, status, tradition, level) and explain in 'revision_note'. "
                "Never drop counter-evidence and never strengthen the claim.")
    return ("Turn the new observations into hypotheses. Each hypothesis must: cite the observation ids it explains; quote "
            "supporting passages verbatim (passage_id + quote, or claim_id); state a testable prediction; list "
            "alternative explanations (sampling, homonymy, transcription, genre, extraction error…); label philological "
            "and anachronism risk. Hypotheses are inferences about the texts, not medical facts; never equate historical "
            "and modern disease concepts.")


# ----------------------------------------------------------------- helpers
def _books(ctx: Any, book_ids: list[str]) -> str:
    corpus = ctx.cap("corpus")
    return "、".join(f"《{corpus.books[b].title}》" for b in book_ids if b in corpus.books)


def _period(ctx: Any, period_id: str) -> str:
    return ctx.cap("domain").periods.label(period_id)


def _sense_label(ctx: Any, sense_id: str | None) -> str:
    if not sense_id:
        return "（未定）"
    sense = ctx.cap("domain").terminology.sense(sense_id)
    return sense.label if sense else sense_id.split("#")[-1]


def _support_from_claims(ctx: Any, claim_ids: list[str]) -> list[dict[str, Any]]:
    claims = [ctx.state.claims[c] for c in claim_ids if c in ctx.state.claims]
    year = year_fn(ctx)
    cluster = cluster_fn(ctx)
    claims.sort(key=lambda c: (year(c) if year(c) is not None else 9999, c.id))
    picked, seen = [], set()
    for c in claims:  # spread across independent clusters first
        if cluster(c.book_id) not in seen:
            picked.append(c)
            seen.add(cluster(c.book_id))
    for c in claims:
        if c not in picked:
            picked.append(c)
    return [{"passage_id": c.passage_id, "quote": c.quote, "claim_id": c.id} for c in picked[:MAX_SUPPORT]]


def _support_from_citations(ctx: Any, obs: Any) -> list[dict[str, Any]]:
    out = []
    for e in ctx.state.lineage.values():
        if e.relation == "cites" and e.target_id == obs.data.get("source") and e.source_passage:
            quote = e.evidence.get("quote") or ""
            span = locate(ctx, e.source_passage, quote)
            if span is None:
                continue
            text = ctx.cap("corpus").passage(e.source_passage).text
            out.append({"passage_id": e.source_passage, "quote": text[span[0]: span[1]]})
    return out[:MAX_SUPPORT]


def _position(claim: Any, subject: str | None) -> str:
    """The doctrinal position a claim takes on a subject: its etiology / pathogenesis / concept arguments."""
    from ...protocol.claims import Role

    roles = (Role.ETIOLOGY, Role.PATHOGENESIS, Role.CONCEPT)
    parts = [a.surface for a in claim.arguments if a.role in roles and a.term_id != subject and not a.negated]
    return "、".join(dict.fromkeys(parts))


def _range(start: float | None, end: float | None) -> dict[str, int] | None:
    if start is None or end is None:
        return None
    return {"start": int(start), "end": int(end)}


GENERIC_ALTERNATIVES = {
    "lost_knowledge": [
        "语料覆盖不足：后世样本有限，缺失可能源于抽样（absence of evidence ≠ evidence of absence）",
        "术语更替：后世可能以同义词或新名称表达同一关联",
        "知识被整合进其他方剂或理论而不再单独表述",
        "被临床实践淘汰（弃用）而非失传",
        "抽取遗漏：后世文本中存在该关联但未被规则抽取",
    ],
    "historical_testimony": ["作者对“昔人”用法的概括可能不完整或带有学派立场", "“后世”用法的转移可能只反映部分地区或流派"],
    "lost_source": ["可能为转引（二手引用），并非直接见到原书", "书名可能为异称，所指或为语料中已有之书", "引文可能经后人改写或节录"],
    "concept_drift": [
        "文献类型（方书 / 医论 / 本草）构成的变化造成语境差异，而非概念本身演变",
        "样本量小：部分时期仅有少数用例",
        "同名异义：不同学派在同一时期使用不同含义，而非历时演变",
        "义项标注误差：义项判定依赖线索词",
    ],
    "formula_evolution": [
        "趋同组方：不同医家独立组成相似方剂，并非传承",
        "核心药物在同类方剂中普遍使用，重叠不足以证明谱系",
        "同名异方或异名同方",
        "成书年代或归属存疑，传承方向可能相反",
    ],
    "renaming": ["地域习称或药材规格差异，而非避讳", "可能为不同药物（同名异物）"],
    "association_rule": ["同一条文被多次转引造成的重复计数", "该组合为方剂所属类别的通用症状，特异性有限"],
    "hidden_association": [
        "图结构伪关联：高频枢纽概念导致的虚假邻近",
        "二者属于同一证候群的不同阶段，临床上并不共用",
        "抽取遗漏：二者其实已在文本中共现",
    ],
    "contradiction": ["两说适用条件不同（体质、时令、病程）", "文本讹误或异文", "同名异义", "学派立场或时代范式不同"],
}


# ----------------------------------------------------------------- templates
def _from_observation(ctx: Any, obs: Any) -> dict[str, Any] | None:
    d = obs.data
    k = obs.kind
    alternatives = list(GENERIC_ALTERNATIVES.get(k, []))
    predictions: list[dict[str, Any]] = []
    support = _support_from_claims(ctx, obs.claim_ids)
    if k == "lost_knowledge":
        pivot = int(d["pivot_year"])
        statement = (f"「{surface(d['left'])}」与「{surface(d['right'])}」的关联见于 {pivot} 年以前的{_books(ctx, d['support_books'])}，"
                     f"但此后的文献不再出现该关联，而两个概念本身仍在使用：这可能是一条在后世失传或被取代的知识。")
        predictions.append({"kind": "absent_after", "subject": d["left"], "object": d["right"], "period": _range(pivot, 1911),
                            "description": f"若为失传知识，{pivot} 年以后的独立文献中不应再出现二者的直接关联"})
        test = f"扩大 {pivot} 年以后的文献样本（含其他版本与类书）：若该关联普遍存在则假说不成立；若只见于转引前代的文本则支持失传。"
    elif k == "historical_testimony":
        items = d["testimony"]
        old = [t for t in items if t["marker"] in ("昔人", "古人", "古方")]
        new = [t for t in items if t not in old]
        statement = (f"文本自述了「{surface(d['herb'])}」用法的转移："
                     + "；".join(f"{t['marker']}用于{'、'.join(t['uses'])}" for t in old + new)
                     + "。早期用法在该书成书时已不为人所用，属于有直接证词的失传用法。")
        for t in old:
            predictions.append({"kind": "earlier_attestation", "subject": d["herb"], "object": "、".join(t["uses"]),
                                "description": f"更早的本草或方书中应能找到「{surface(d['herb'])}」用于{'、'.join(t['uses'])}的记载", "period": None})
        test = "在该书成书以前的本草与方书中检索早期用法；若能找到独立记载，则证词得到佐证。"
    elif k == "lost_source":
        support = _support_from_citations(ctx, obs)
        bound = f"其成书早于约 {int(d['must_predate'])} 年" if d.get("must_predate") is not None else "其成书年代下限待定"
        statement = f"佚书《{d['title']}》曾经流传，并被 {len(d['cited_by'])} 处文本直接引用，{bound}；现存引文可作为辑佚线索。"
        predictions.append({"kind": "link_appears", "subject": f"work:{d['source']}", "object": None, "period": None,
                            "description": f"同时代或稍后的其他类书、方书中应能找到引自《{d['title']}》的佚文"})
        test = f"在语料之外的唐宋类书与方书中检索《{d['title']}》的引文，比对文字异同。"
    elif k == "concept_drift":
        changes = d.get("sense_changes") or []
        shift = d["max_shift"]
        if changes:
            ch = changes[0]
            statement = (f"「{surface(d['term'])}」的主导含义在{_period(ctx, ch['from_period'])}至{_period(ctx, ch['to_period'])}间发生转变："
                         f"由「{_sense_label(ctx, ch['from'])}」转为「{_sense_label(ctx, ch['to'])}」（语境差异 JSD={shift['jsd']}）；"
                         f"不同时代文本中的「{surface(d['term'])}」不能按同一概念直接比较。")
            predictions.append({"kind": "sense_shift", "subject": d["term"], "object": ch["to"],
                                "description": f"{_period(ctx, ch['to_period'])}以后的新文本中，「{surface(d['term'])}」应以「{_sense_label(ctx, ch['to'])}」义为主",
                                "period": None})
        else:
            gained = "、".join(surface(t) for t, _ in d.get("gained", [])[:4]) or "—"
            statement = (f"「{surface(d['term'])}」的使用语境在{_period(ctx, shift['from'])}至{_period(ctx, shift['to'])}间显著变化"
                         f"（JSD={shift['jsd']}），新出现的语境包括 {gained}，提示其所指范围发生了扩展或转移。")
            predictions.append({"kind": "sense_shift", "subject": d["term"], "object": None, "period": None,
                                "description": "更晚时期的文本应延续新的语境分布"})
        test = "在更多同期文献中复核义项分布；按文献类型分层后差异仍存在，则支持概念演变。"
    elif k == "formula_evolution":
        members = d["members"]
        core = "、".join(surface(h) for h in d["stable_core"])
        chain = " → ".join(surface(m) for m in members)
        if core:
            statement = f"{chain} 构成一个化裁谱系，{core} 为贯穿各代的稳定核心；后世通过加减药物在同一核心上衍生出新方。"
            predictions.append({"kind": "herb_retained", "subject": ",".join(d["stable_core"]), "object": None, "period": None,
                                "description": f"同一谱系中更晚出现的衍生方应保留核心药物 {core}"})
        else:
            statement = f"{chain} 之间存在组成上的承袭关系（无全族共有的核心药物），可能为一条较松散的化裁线索。"
            predictions.append({"kind": "herb_retained", "subject": ",".join(members), "object": None, "period": None,
                                "description": "若为谱系，后出方应保留前方的主要药物"})
        test = "查找后世医家对这些方剂源流的明确记述（如“即某方加减”），并核对各方的成书年代。"
    elif k == "renaming":
        statement = (f"「{d['parent_surface']}」在 {surface(d['child'])} 中作「{d['child_surface']}」，是避讳改名在方剂传承中的痕迹；"
                     f"比较不同时代的方剂组成时应将二者视为同一药物。")
        predictions.append({"kind": "renaming", "subject": d["herb"], "object": d["parent_surface"], "period": None,
                            "description": f"避讳改名后，原名「{d['parent_surface']}」不应在后世方书中复现"})
        test = "核对改名写法首次出现的年代与相关帝王名讳的年代是否一致。"
    elif k == "association_rule":
        lhs = "、".join(surface(x) for x in d["lhs"])
        statement = f"在主治类记载中，{lhs} 并见时多用 {surface(d['rhs'])}（置信度 {d['confidence']}，lift {d['lift']}）：该组合可视为 {surface(d['rhs'])} 的特征性指征。"
        predictions.append({"kind": "cooccurrence_after", "subject": ",".join(d["lhs"]), "object": d["rhs"], "period": None,
                            "description": f"更晚或语料之外的文献中，{lhs} 并见时仍应多用 {surface(d['rhs'])}"})
        test = "在独立的后世方书中统计该症状组合的用方分布。"
    elif k == "hidden_association":
        via = "、".join(surface(v) for v in d["via"])
        statement = (f"「{surface(d['left'])}」与「{surface(d['right'])}」没有直接记载的联系，但经由 {via} 在知识超图中紧密相连："
                     f"{surface(d['right'])} 或可用于 {surface(d['left'])}（纯计算推断，需文献验证）。")
        predictions.append({"kind": "link_appears", "subject": d["left"], "object": d["right"], "period": None,
                            "description": "本语料之外或更晚的文献中可能出现二者的直接关联"})
        test = "检索语料之外的方书与医案；若出现二者的直接关联，则为时间外推验证（Historical Time Machine）的正例。"
    elif k == "contradiction":
        claims = [ctx.state.claims[c] for c in obs.claim_ids if c in ctx.state.claims]
        a, b = (claims + claims)[:2] if claims else (None, None)
        if a is None:
            return None
        corpus = ctx.cap("corpus")
        ta, tb = corpus.books[a.book_id].title, corpus.books[b.book_id].title
        subject = surface(d.get("subject") or "")
        if d["label"] == "apparent" and d["type"] == "philological":
            statement = f"《{ta}》该条关于「{subject}」的内在矛盾很可能源于文本异文（校勘问题），而非医学理论分歧。"
            test = "比对该条文在其他版本中的读法；若他本作相反读法，则矛盾消解。"
        elif d["label"] == "apparent":
            statement = f"《{ta}》与《{tb}》关于「{subject}」的表面矛盾源于同名异义：两处「{subject}」分属不同义项，不构成理论冲突。"
            test = "核对两处上下文的义项线索；若义项判定稳定，则矛盾为表面矛盾。"
        elif d["label"] == "conditional":
            statement = f"《{ta}》与《{tb}》关于「{subject}」的分歧可由适用条件的差异解释（{'；'.join(d.get('explanations', [])[:2])}），两说并非互斥。"
            test = "寻找同时论及两种条件的文本；若其明确区分适用情形，则支持条件性解释。"
        else:
            pa, pb = _position(a, d.get("subject")), _position(b, d.get("subject"))
            if pa and pb and pa != pb:
                statement = (f"关于「{subject}」，《{ta}》归因于「{pa}」，《{tb}》则归因于「{pb}」："
                             f"两说存在实质性理论分歧（{'；'.join(d.get('explanations', [])[:2]) or d['type']}），反映了学术范式的变化。")
            else:
                statement = (f"《{ta}》与《{tb}》关于「{subject}」的论述存在实质性理论分歧"
                             f"（{'；'.join(d.get('explanations', [])[:2]) or d['type']}），反映了学术范式的变化。")
            test = "查找后出文本是否明确反驳前说（如“非……也”），并考察两说在各自学派中的承续。"
        alternatives = list(dict.fromkeys(d.get("explanations", []) + alternatives))
        predictions.append({"kind": "resolution", "subject": d.get("subject") or "", "object": d["label"], "period": None,
                            "description": test})
    else:
        return None
    if not support:
        return None
    return {
        "statement": statement,
        "kind": k,
        "observation_ids": [obs.id],
        "terms": list(obs.terms),
        "support": support,
        "alternative_explanations": alternatives,
        "testable_prediction": test,
        "predictions": predictions,
        "novelty_rationale": "",
        "space": KnowledgeSpace.COMPUTATIONAL_HYPOTHESIS.value,
    }


def _generate_draft(ctx: Any) -> dict[str, Any]:
    """Round-robin over observation kinds (best first) so every requested track is represented."""
    used = {o for h in ctx.state.hypotheses.values() for o in h.observation_ids}
    limit = int(ctx.config.get("max_hypotheses", 16))
    queues: dict[str, list[Any]] = {}
    for obs in sorted(ctx.state.observations.values(), key=lambda o: (-o.score, o.id)):
        if obs.id not in used:
            queues.setdefault(obs.kind, []).append(obs)
    order = sorted(queues, key=lambda k: (-queues[k][0].score, k))
    taken: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    while len(out) < limit and any(queues.values()):
        progressed = False
        for kind in order:
            if len(out) >= limit:
                break
            while queues[kind] and taken.get(kind, 0) < CAPS.get(kind, 2):
                item = _from_observation(ctx, queues[kind].pop(0))
                if item is not None:
                    out.append(item)
                    taken[kind] = taken.get(kind, 0) + 1
                    progressed = True
                    break
        if not progressed:
            break
    return {"hypotheses": out}


# ----------------------------------------------------------------- revisions
STRATEGIES = {
    "sample_size": ("scope", "surveyed_corpus", "在本次调查的语料范围内，", ""),
    "single_source": ("scope", "surveyed_corpus", "在本次调查的语料范围内，", "（目前仅有单一独立来源，需更多文献复核）"),
    "homonym": ("sense", None, "", ""),
    "edition_variant": ("reading", "base", "若依底本读法，", ""),
    "statistical": ("status", "exploratory", "", "（探索性发现，未通过多重检验校正）"),
    "transcription_dependence": ("tradition", "single", "", "（现有证据可能出自同一传本系统）"),
    "earliest_source": ("level", "explicit_claim", "", "（后世文本中仍有二者共现，但不再形成明确的主治记载）"),
    "counterexample": ("level", "text_attested", "", "（二者在文本中已有共现，属未被结构化的关联，而非完全隐性）"),
    "partial_persistence": ("level", "transformed", "", "（后世仍以相近表述出现，失传结论仅限于原表述）"),
    "hub_driven": ("status", "exploratory", "", "（主要经由高频枢纽概念连接，属探索性推断）"),
}


def _revise_draft(ctx: Any) -> dict[str, Any]:
    state = ctx.state
    targets = ctx.inputs.get("hypothesis_ids") or sorted(h.id for h in state.hypotheses.values() if h.status == "needs_revision")
    out = []
    for hid in targets:
        h = state.hypotheses.get(hid)
        if h is None or h.status != "needs_revision":
            continue
        reviews = state.reviews_for(hid)
        if not reviews:
            continue
        latest = max(reviews, key=lambda r: (r.round, r.id))
        qualifiers = dict(h.qualifiers)
        prefix, suffixes, notes = "", [], []
        for o in latest.unresolved("critical", "major"):
            strategy = STRATEGIES.get(o.check)
            if strategy is None:
                continue
            key, value, pre, suf = strategy
            if key == "sense":
                value = _dominant_sense(ctx, h)
                suf = f"（此处「{surface(h.terms[0]) if h.terms else ''}」取「{_sense_label(ctx, value)}」义）" if value else ""
            if key in qualifiers and qualifiers[key] == value:
                continue
            qualifiers[key] = value
            prefix = prefix or pre
            if suf:
                suffixes.append(suf)
            notes.append(f"{o.id}[{o.check}] → {key}={value}")
        if not notes:
            continue
        statement = h.statement
        if prefix and not statement.startswith(prefix):
            statement = prefix + statement
        notes_text = [x.strip("（）") for x in dict.fromkeys(suffixes)]
        body = statement.rstrip("。") + (f"（{'；'.join(notes_text)}）" if notes_text else "") + "。"
        out.append({"parent_id": hid, "statement": body, "revision_note": "针对异议：" + "；".join(notes),
                    "qualifiers": qualifiers, "alternative_explanations": list(h.alternative_explanations),
                    "testable_prediction": h.testable_prediction})
    return {"revisions": out}


def _dominant_sense(ctx: Any, h: Any) -> str | None:
    evidence = [ctx.state.evidence[e] for e in h.supporting_evidence if e in ctx.state.evidence]
    counts: dict[str, float] = {}
    for r in ctx.state.term_resolutions.values():
        if h.terms and r.term_id == h.terms[0] and any(e.passage_id == r.passage_id for e in evidence) and r.sense_id:
            counts[r.sense_id] = counts.get(r.sense_id, 0) + r.probability
    return max(counts, key=lambda s: (counts[s], s)) if counts else None


def draft(ctx: Any) -> dict[str, Any]:
    return _revise_draft(ctx) if ctx.task.kind == "revise_hypotheses" else _generate_draft(ctx)


# ----------------------------------------------------------------- commit
def _risk(ctx: Any, records: list[EvidenceRecord]) -> tuple[str, str]:
    worst, notes = 1.0, []
    unverified = 0
    for r in records:
        a = ctx.state.philology.get(r.passage_id)
        if a is None:
            continue
        for c in a.contested_at(r.start, r.end):
            worst = min(worst, c.base_probability())
            notes.append(f"{r.passage_id}「{c.base}」底本读法 p={c.base_probability():.2f}")
        if a.collation_status == "unverified":
            unverified += 1
    if worst < 0.6:
        return "high", "；".join(notes)
    if unverified == len(records) and records:
        return "medium", "全部证据来自未经校勘的整理本"
    if unverified:
        return "medium", f"{unverified}/{len(records)} 条证据来自未经校勘的整理本"
    return "low", "证据文本已校勘"


def _confidence(ctx: Any, records: list[EvidenceRecord], obs: list[Any]) -> ConfidenceVector:
    cluster = cluster_fn(ctx)
    need = ctx.goal.required_evidence.min_independent_sources if ctx.goal else 2
    clusters = {cluster(r.book_id) for r in records}
    base = ConfidenceVector.mean([r.confidence for r in records])
    stats = [o.statistics for o in obs]
    p_values = [s.get("p_value") or s.get("p_absence") or s.get("empirical_p") for s in stats]
    p_values = [p for p in p_values if isinstance(p, (int, float))]
    statistical = round(max(0.0, 1.0 - min(p_values)), 4) if p_values else None
    dated = [r for r in records if r.temporal and r.temporal.effective() is not None]
    return ConfidenceVector(
        textual=base.textual, philological=base.philological, semantic=base.semantic, extraction=base.extraction,
        cross_source=round(min(1.0, len(clusters) / max(1, need)), 4),
        temporal=round(len(dated) / len(records), 4) if records else None,
        statistical=statistical, modern_mapping=None,
    )


def _commit_generate(ctx: Any, output: dict[str, Any]) -> str:
    state = ctx.state
    made, dropped = [], 0
    for item in output.get("hypotheses", []):
        obs_ids = [o for o in item.get("observation_ids", []) if o in state.observations]
        if not obs_ids:
            dropped += 1
            continue
        hid = stable_id("hyp", item["kind"], sorted(obs_ids), item["statement"])
        if hid in state.hypotheses:
            continue
        records: list[EvidenceRecord] = []
        for s in item.get("support", []):
            claim = state.claims.get(s.get("claim_id") or "")
            if claim is not None and (not s.get("quote") or s["quote"] in claim.quote or claim.quote in s["quote"]):
                records.append(evidence_from_claim(ctx, claim, hypothesis_id=hid))
                continue
            span = locate(ctx, s.get("passage_id", ""), s.get("quote", ""))
            if span is None:
                ctx.note(f"unverifiable quote dropped for {hid}")
                continue
            records.append(evidence_record(ctx, s["passage_id"], span[0], span[1], method="hypothesis:citation",
                                           stance=Stance.SUPPORTS, hypothesis_id=hid))
        records = list({r.id: r for r in records}.values())
        if not records:
            dropped += 1  # Evidence-first: no verified support, no hypothesis
            continue
        year = ctx.cap("corpus").year
        earliest = min(records, key=lambda r: (year(ctx.cap("corpus").passage(r.passage_id)) or 9999, r.id))
        philo_risk, philo_note = _risk(ctx, records)
        predictions = []
        for p in item.get("predictions", []):
            period = p.get("period")
            predictions.append(Prediction(kind=p["kind"], subject=p["subject"], object=p.get("object"), description=p["description"],
                                          period=YearRange(start=period["start"], end=period["end"]) if period else None))
        h = Hypothesis(
            id=hid,
            statement=item["statement"],
            kind=item["kind"],
            observation_ids=obs_ids,
            terms=list(item.get("terms", [])),
            supporting_evidence=[r.id for r in records],
            earliest_evidence=earliest.id,
            replication_sources=sorted({r.book_id for r in records}),
            novelty_rationale=item.get("novelty_rationale", ""),
            alternative_explanations=list(item.get("alternative_explanations", [])),
            philological_risk=item.get("philological_risk") or philo_risk,
            philological_risk_note=philo_note,
            anachronism_risk=item.get("anachronism_risk") or "low",
            anachronism_risk_note="历史文本内部推断，未跨入现代医学空间" if not item.get("anachronism_risk") else "",
            testable_prediction=item.get("testable_prediction", ""),
            predictions=predictions,
            confidence=_confidence(ctx, records, [state.observations[o] for o in obs_ids]),
            space=KnowledgeSpace(item.get("space") or KnowledgeSpace.COMPUTATIONAL_HYPOTHESIS.value),
            generated_by=ctx.actor.id,
            round=ctx.task.round,
        )
        verdict = ctx.hook(HookPoint.AFTER_HYPOTHESIS, h, subject_id=h.id)
        if not verdict.allow:
            dropped += 1
            continue
        ctx.emit(EventType.EVIDENCE_RETRIEVED, {"records": [r.to_dict() for r in records]}, generated=[r.id for r in records])
        made.append(h)
    if made:
        ctx.emit(EventType.HYPOTHESIS_GENERATED, {"hypotheses": [h.to_dict() for h in made]}, generated=[h.id for h in made])
    kinds: dict[str, int] = {}
    for h in made:
        kinds[h.kind] = kinds.get(h.kind, 0) + 1
    return f"{len(made)} hypotheses (" + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())) + f"); {dropped} dropped"


def _commit_revise(ctx: Any, output: dict[str, Any]) -> str:
    state = ctx.state
    made, dropped = 0, 0
    for item in output.get("revisions", []):
        parent = state.hypotheses.get(item.get("parent_id", ""))
        if parent is None or parent.status != "needs_revision":
            dropped += 1
            continue
        qualifiers = {k: v for k, v in (item.get("qualifiers") or {}).items() if v is not None}
        child = parent.replace(
            id=stable_id("hyp", parent.id, "rev", parent.generation + 1, qualifiers),
            statement=item["statement"],
            status="proposed",
            generation=parent.generation + 1,
            parent_id=parent.id,
            revision_note=item.get("revision_note", ""),
            qualifiers=qualifiers,
            alternative_explanations=list(item.get("alternative_explanations") or parent.alternative_explanations),
            testable_prediction=item.get("testable_prediction") or parent.testable_prediction,
            scores=None, discovery_score=None, discovery_components={}, elo=parent.elo,
            generated_by=ctx.actor.id, round=ctx.task.round,
        )
        verdict = ctx.hook(HookPoint.AFTER_HYPOTHESIS, child, subject_id=child.id)
        if not verdict.allow:
            dropped += 1
            continue
        ctx.emit(EventType.HYPOTHESIS_REVISED, {"hypothesis": child.to_dict()}, generated=[child.id], used=[parent.id])
        made += 1
    return f"{made} hypotheses revised; {dropped} revisions dropped"


def commit(ctx: Any, output: dict[str, Any]) -> str:
    return _commit_revise(ctx, output) if ctx.task.kind == "revise_hypotheses" else _commit_generate(ctx, output)
