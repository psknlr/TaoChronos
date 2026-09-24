"""Pattern Miner (tool-first, no model): runs the discovery engines D1–D5 and records observations.

Observations are *patterns*, not claims about medicine: an association that
vanishes after a pivot year (D1), a sense or context shift of a term (D2), a
formula family with a stable core (D3), a statistically unusual or
graph-predicted association (D4), a conflict between texts (D5), or a cited
work absent from the corpus (source rediscovery).  Hypotheses come later,
from other agents, and must survive the Skeptic.
"""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.claims import ClaimRelation
from ...protocol.events import EventType
from ...protocol.hypothesis import Observation
from ...protocol.research import Contradiction
from .common import focus_term_ids, surface

OUTPUT = "ObservationSet"
MAX_PER_TRACK = 6


def instructions(ctx: Any) -> str:
    return "Run the discovery engines for the requested tracks and record observations (tool-first; no interpretation)."


def _boost(terms: list[str], focus: set[str]) -> float:
    return 1.5 if focus and focus & set(terms) else 1.0


def _members(claim: Any) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated}


def _passages(ctx: Any, claim_ids: list[str]) -> list[str]:
    claims = ctx.state.claims
    return sorted({claims[c].passage_id for c in claim_ids if c in claims})


def _label(ctx: Any, period_id: str) -> str:
    return ctx.cap("domain").periods.label(period_id)


def _book_titles(ctx: Any, book_ids: list[str]) -> str:
    corpus = ctx.cap("corpus")
    return "、".join(f"《{corpus.books[b].title}》" for b in book_ids if b in corpus.books)


# ------------------------------------------------------------------ D1
def _d1(ctx: Any, focus: set[str], pivot: float) -> list[Observation]:
    res = ctx.tool("analysis.lost_knowledge", pivot_year=pivot)
    pool = [c for c in res["candidates"] if c["replicated"] or c["score"] >= 0.3]
    pool.sort(key=lambda c: (-c["replicated"], -c["score"] * _boost([c["left"], c["right"]], focus), c["left"], c["right"]))
    out = []
    for c in pool[:MAX_PER_TRACK]:
        left, right = c["left"], c["right"]
        tag = "（多源复现）" if c["replicated"] else "（单一来源）"
        out.append(Observation(
            id=stable_id("obs", "lost_knowledge", left, right, c["kind"], pivot),
            kind="lost_knowledge",
            title=f"{surface(left)}—{surface(right)}：{int(pivot)} 年后不再出现的关联{tag}",
            summary=(f"{_book_titles(ctx, c['support_books'])}记载「{surface(left)}」与「{surface(right)}」的关联（{c['kind']}），"
                     f"{int(pivot)} 年以后的文献中不再出现该关联，而两个概念本身仍被使用"
                     f"（后世提及：{surface(left)} {c['later_mentions']['left']} 次，{surface(right)} {c['later_mentions']['right']} 次）。"),
            detector="lost_knowledge@0.1",
            data={**c, "pivot_year": pivot},
            statistics={"independent_support": c["independent_support"], "replicated": c["replicated"]},
            claim_ids=list(c["claim_ids"]),
            passage_ids=_passages(ctx, c["claim_ids"]),
            terms=[left, right],
            score=round(c["score"] * _boost([left, right], focus), 4),
        ))
    by_herb: dict[str, list[dict]] = {}
    for t in res.get("testimony", []):
        if t.get("herb"):
            by_herb.setdefault(t["herb"], []).append(t)
    for herb, items in sorted(by_herb.items()):
        markers = "；".join(f"{t['marker']}：{'、'.join(t['uses'])}" for t in items)
        out.append(Observation(
            id=stable_id("obs", "historical_testimony", herb, [t["claim_id"] for t in items]),
            kind="historical_testimony",
            title=f"{surface(herb)}：古籍自述的用法变迁",
            summary=f"文本自身记载了「{surface(herb)}」用途的前后变化（{markers}），可作为失传用法的直接证词。",
            detector="lost_knowledge.testimony@0.1",
            data={"herb": herb, "testimony": items},
            claim_ids=[t["claim_id"] for t in items],
            passage_ids=sorted({t["passage_id"] for t in items}),
            terms=[herb],
            score=round(0.6 * _boost([herb], focus), 4),
        ))
    return out


def _sources(ctx: Any, focus: set[str]) -> list[Observation]:
    corpus = ctx.cap("corpus")
    out = []
    for s in ctx.tool("analysis.missing_sources"):
        work = corpus.external.get(s["source"])
        title = work.title if work else s["source"]
        bound = f"成书应早于约 {int(s['must_predate'])} 年" if s.get("must_predate") is not None else "年代下限未知"
        out.append(Observation(
            id=stable_id("obs", "lost_source", s["source"]),
            kind="lost_source",
            title=f"佚书《{title}》的线索",
            summary=f"《{title}》不在语料中，但被 {len(s['cited_by'])} 处文本引用（{', '.join(s['cited_by'][:4])}）；{bound}。"
                    + (f"已知状态：{work.status}。" if work else ""),
            detector="source_rediscovery@0.1",
            data={**s, "title": title},
            passage_ids=list(s["cited_by"]),
            terms=[f"work:{s['source']}"],
            score=round(min(1.0, 0.5 + s["support"] / 2), 4),
        ))
    return out


# ------------------------------------------------------------------ D2
def _drift_terms(ctx: Any, focus: set[str]) -> list[str]:
    pack = ctx.cap("domain")
    lex = pack.lexicon
    terms = [t for t in sorted(focus) if pack.terminology.term(surface(t))]
    if not terms:
        counted: dict[str, int] = {}
        for c in ctx.state.claims.values():
            for m in _members(c):
                if pack.terminology.term(surface(m)) and len(pack.terminology.term(surface(m)).senses) > 1:
                    counted[m] = counted.get(m, 0) + 1
        terms = [t for t, _ in sorted(counted.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
    return [t for t in terms if lex.entry(t)]


def _d2(ctx: Any, focus: set[str]) -> list[Observation]:
    out = []
    for term in _drift_terms(ctx, focus):
        res = ctx.tool("analysis.concept_drift", term=term)
        if not res:
            continue
        shift = res["max_shift"]
        if not res["sense_changes"] and shift["jsd"] < 0.5:
            continue
        senses = "；".join(f"{p}：{s}" for p, s in res["dominant_sense"].items())
        out.append(Observation(
            id=stable_id("obs", "concept_drift", res["family"]),
            kind="concept_drift",
            title=f"「{surface(term)}」的概念演变（{_label(ctx, shift['from'])}→{_label(ctx, shift['to'])}）",
            summary=(f"「{surface(term)}」在 {len(res['periods'])} 个时期中的主导义项：{senses}。"
                     f"相邻时期最大语境差异 JSD={shift['jsd']}（置换检验 p={shift['p_value']}）；"
                     f"新增语境：{'、'.join(surface(t) for t, _ in res['gained'][:4]) or '—'}；"
                     f"消失语境：{'、'.join(surface(t) for t, _ in res['lost'][:4]) or '—'}。"),
            detector="concept_drift@0.1",
            data={k: res[k] for k in ("term", "family", "periods", "occurrences", "books", "jsd_series", "max_shift", "first_last",
                                      "gained", "lost", "dominant_sense", "sense_changes")},
            statistics={"jsd": shift["jsd"], "p_value": shift["p_value"], "first_last_p": res["first_last"]["p_value"],
                        "occurrences": res["occurrences"]},
            claim_ids=res["claim_ids"][:40],
            passage_ids=res["passage_ids"][:40],
            terms=[res["term"]],
            score=round((shift["jsd"] * (1.0 if res["sense_changes"] else 0.6)) * _boost([res["term"]], focus), 4),
        ))
    return out[:MAX_PER_TRACK]


# ------------------------------------------------------------------ D3
def _d3(ctx: Any, focus: set[str]) -> list[Observation]:
    res = ctx.tool("analysis.formula_evolution")
    claims = ctx.state.claims
    out = []
    for fam in res["families"]:
        members = fam["members"]
        comp = sorted(c.id for c in claims.values() if c.relation == ClaimRelation.COMPOSED_OF and _members(c) & set(members))
        steps = "；".join(
            f"{surface(s['child'])}←{surface(s['parent'])}"
            + (f"（加 {'、'.join(surface(h) for h in s['added'][:5])}" if s["added"] else "（")
            + (f"；去 {'、'.join(surface(h) for h in s['removed'][:5])}" if s["removed"] else "")
            + (f"；{ '、'.join(surface(x['from']) + '→' + surface(x['to']) for x in s['substituted'])}" if s["substituted"] else "")
            + "）"
            for s in fam["steps"])
        core = "、".join(surface(h) for h in fam["stable_core"]) or "（无共同核心）"
        out.append(Observation(
            id=stable_id("obs", "formula_evolution", members),
            kind="formula_evolution",
            title="方剂家族：" + " → ".join(surface(m) for m in members),
            summary=f"{len(members)} 首方剂构成化裁谱系，稳定核心药物：{core}。演变步骤：{steps}。",
            detector="formula_evolution@0.1",
            data=fam,
            statistics={"size": fam["size"], "core_size": len(fam["stable_core"])},
            claim_ids=comp[:30],
            passage_ids=_passages(ctx, comp),
            terms=list(members) + list(fam["stable_core"]),
            score=round((0.45 + 0.1 * min(fam["size"], 4) + (0.1 if fam["stable_core"] else -0.2)) * _boost(members, focus), 4),
        ))
        for step in fam["steps"]:
            for rename in step.get("renames", []):
                if "taboo_rename" not in (rename.get("kinds") or []):
                    continue
                out.append(Observation(
                    id=stable_id("obs", "renaming", rename["herb"], step["child"], step["parent"]),
                    kind="renaming",
                    title=f"{rename['parent_surface']}→{rename['child_surface']}：避讳改名在方剂传承中的痕迹",
                    summary=(f"{surface(step['parent'])} 中的「{rename['parent_surface']}」在 {surface(step['child'])} 中作「{rename['child_surface']}」"
                             f"（同一药物 {surface(rename['herb'])}，改名类型：{'、'.join(k for k in rename['kinds'] if k)}）。"),
                    detector="formula_evolution.renames@0.1",
                    data={**rename, "child": step["child"], "parent": step["parent"]},
                    claim_ids=comp[:10],
                    passage_ids=_passages(ctx, comp),
                    terms=[rename["herb"], step["child"], step["parent"]],
                    score=0.55,
                ))
    return out[: MAX_PER_TRACK * 2]


# ------------------------------------------------------------------ D4
def _d4(ctx: Any, focus: set[str]) -> list[Observation]:
    claims = ctx.state.claims
    out = []
    rules = [r for r in ctx.tool("analysis.association_rules") if r["lift"] >= 2 and r["p_value"] <= 0.05]
    rules.sort(key=lambda r: (-_boost(r["lhs"] + [r["rhs"]], focus), -r["lift"], r["lhs"], r["rhs"]))
    for r in rules[:MAX_PER_TRACK]:
        items = set(r["lhs"]) | {r["rhs"]}
        support = sorted(c.id for c in claims.values() if c.relation == ClaimRelation.INDICATED_FOR and items <= _members(c))
        out.append(Observation(
            id=stable_id("obs", "association_rule", r["lhs"], r["rhs"]),
            kind="association_rule",
            title=f"{'+'.join(surface(x) for x in r['lhs'])} ⇒ {surface(r['rhs'])}",
            summary=(f"在「主治」类主张中，{'、'.join(surface(x) for x in r['lhs'])} 出现时 {surface(r['rhs'])} 的置信度为 "
                     f"{r['confidence']}（lift={r['lift']}，支持数 {r['support']}，Fisher p={r['p_value']}）。"),
            detector="association_rules@0.1",
            data=r,
            statistics={"support": r["support"], "confidence": r["confidence"], "lift": r["lift"], "p_value": r["p_value"]},
            claim_ids=support,
            passage_ids=_passages(ctx, support),
            terms=list(r["lhs"]) + [r["rhs"]],
            score=round(min(1.0, 0.3 + r["lift"] / 40) * _boost(list(items), focus), 4),
        ))
    preds = ctx.tool("analysis.link_prediction", k=12)
    preds.sort(key=lambda p: (-_boost([p["left"], p["right"]], focus), -p["score"], p["left"], p["right"]))
    for p in preds[:MAX_PER_TRACK]:
        via = set(p["via"])
        path_claims = sorted(c.id for c in claims.values() if (_members(c) & {p["left"], p["right"]}) and (_members(c) & via))[:12]
        out.append(Observation(
            id=stable_id("obs", "hidden_association", p["left"], p["right"]),
            kind="hidden_association",
            title=f"{surface(p['left'])} ⇢ {surface(p['right'])}（未直接共现的候选关联）",
            summary=(f"「{surface(p['left'])}」与「{surface(p['right'])}」在任何主张中都未直接共现，但经由 "
                     f"{'、'.join(surface(v) for v in p['via'])} 在知识超图中紧密相连（Adamic–Adar={p['score']}）。"),
            detector="link_prediction.adamic_adar@0.1",
            data=p,
            statistics={"adamic_adar": p["score"]},
            claim_ids=path_claims,
            passage_ids=_passages(ctx, path_claims),
            terms=[p["left"], p["right"]],
            score=round(min(1.0, p["score"] / 4) * _boost([p["left"], p["right"]], focus), 4),
        ))
    return out


# ------------------------------------------------------------------ D5
def _d5(ctx: Any, focus: set[str]) -> tuple[list[Observation], list[dict]]:
    raw = ctx.tool("analysis.contradictions")
    records = [Contradiction.from_dict(c) for c in raw if c.get("label") in ("contradiction", "conditional", "apparent")]
    claims = ctx.state.claims
    out = []
    labels = {"contradiction": "学术矛盾", "conditional": "条件性差异", "apparent": "表面矛盾"}
    for c in records:
        a, b = claims.get(c.claim_a), claims.get(c.claim_b)
        if a is None or b is None:
            continue
        if c.type == "segmentation":
            continue  # an artefact of machine segmentation: recorded as a contradiction record, not an observation
        pair = f"{a.passage_id}（同一条文内部）" if c.claim_a == c.claim_b else f"{a.passage_id} ↔ {b.passage_id}"
        terms = [c.subject] if c.subject else []
        axis = c.axis.split(":")[-1] if c.axis else c.type
        out.append(Observation(
            id=stable_id("obs", "contradiction", c.id),
            kind="contradiction",
            title=f"{labels[c.label]}：{surface(c.subject) if c.subject else ''}（{axis}）",
            summary=f"{pair}：{c.explanation or c.type}",
            detector=str(c.evidence.get("detector", "contradiction@0.1")),
            data={"contradiction_id": c.id, "label": c.label, "type": c.type, "axis": c.axis, "subject": c.subject,
                  "explanations": c.candidate_explanations},
            claim_ids=sorted({c.claim_a, c.claim_b}),
            passage_ids=sorted({a.passage_id, b.passage_id}),
            terms=terms,
            score=round(c.confidence * _boost(terms, focus), 4),
        ))
    return out[: MAX_PER_TRACK * 2], [c.to_dict() for c in records]


def draft(ctx: Any) -> dict[str, Any]:
    tracks = ctx.inputs.get("tracks") or (list(ctx.goal.tracks) if ctx.goal else ["D1", "D2", "D3", "D4", "D5"])
    focus = set(focus_term_ids(ctx))
    pivot = float(ctx.inputs.get("pivot_year", ctx.config.get("pivot_year", 960)))
    observations: list[Observation] = []
    contradictions: list[dict] = []
    if "D1" in tracks:
        observations += _d1(ctx, focus, pivot)
        if not ctx.inputs.get("sensitivity"):
            observations += _sources(ctx, focus)
    if "D2" in tracks:
        observations += _d2(ctx, focus)
    if "D3" in tracks:
        observations += _d3(ctx, focus)
    if "D4" in tracks:
        observations += _d4(ctx, focus)
    if "D5" in tracks:
        found, contradictions = _d5(ctx, focus)
        observations += found
    unique = {o.id: o for o in observations}
    return {"observations": [o.to_dict() for o in unique.values()], "contradictions": contradictions}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    fresh = [o for o in output.get("observations", []) if o["id"] not in ctx.state.observations]
    fresh_c = [c for c in output.get("contradictions", []) if c["id"] not in ctx.state.contradictions]
    if fresh_c:
        ctx.emit(EventType.CONTRADICTION_FOUND, {"contradictions": fresh_c}, generated=[c["id"] for c in fresh_c])
    if fresh:
        ctx.emit(EventType.OBSERVATION_RECORDED, {"observations": fresh}, generated=[o["id"] for o in fresh])
    kinds: dict[str, int] = {}
    for o in fresh:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    return f"{len(fresh)} new observations (" + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())) + f"); {len(fresh_c)} contradictions"
