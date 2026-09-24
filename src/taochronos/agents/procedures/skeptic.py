"""Skeptic (falsification): tries to break every hypothesis before anyone believes it.

Checks: provenance of every quote · anachronism · contested readings in the
evidence (edition variants) · homonymy · transcription dependence · single
source · corpus coverage (sample size) · statistics · later co-mentions that
contradict “lost” knowledge · text-level co-mentions that contradict “hidden”
associations · earlier attestation for testimony · weak formula lineages ·
overlap with known findings.

The verdict is harness policy, not model opinion: any unresolved critical
objection rejects; unresolved major objections send a first-generation
hypothesis back for revision; a revision resolves an objection only through
the matching qualifier (scope, sense, reading, status, tradition, level).
A model may add objections, but a critical objection without verifiable
counter-evidence is downgraded to major — the Skeptic is evidence-bound too.
"""

from __future__ import annotations

from typing import Any

from ...kernel.hooks import HookPoint
from ...protocol.base import stable_id
from ...protocol.claims import ClaimRelation, Role
from ...protocol.events import EventType
from ...protocol.evidence import Stance
from ...protocol.hypothesis import HypothesisReview, Objection
from ...science.scoring import novelty
from .common import cluster_fn, co_mentions, evidence_record, locate, related_terms, scope_passages, surface, year_fn

OUTPUT = "ReviewSet"
MAX_REVISIONS = 1
QUALIFIER_FOR = {
    "sample_size": "scope", "single_source": "scope", "homonym": "sense", "edition_variant": "reading",
    "statistical": "status", "transcription_dependence": "tradition", "earliest_source": "level", "counterexample": "level",
    "partial_persistence": "level", "hub_driven": "status",
}
LOCAL_KINDS = ("lost_source", "historical_testimony", "contradiction", "renaming")
MIN_LATE_PASSAGES = 20


def instructions(ctx: Any) -> str:
    return ("Try to falsify each hypothesis under review. Look for earlier or later sources that contradict it, "
            "counterexamples, edition variants inside the quoted evidence, homonymy, transcription dependence between "
            "witnesses, thin corpus coverage and weak statistics. Every objection needs a check name, a severity "
            "(critical / major / minor / info) and a detail; a critical objection must quote counter-evidence verbatim "
            "(passage_id + quote) or it will be downgraded. Mark an objection resolved only if the hypothesis's "
            "qualifiers already address it.")


def _degrees(ctx: Any) -> dict[str, int]:
    """Term degree in the positive claim hypergraph (cached per agent run)."""
    cache = ctx.__dict__.setdefault("_degree_cache", {})
    if not cache:
        neighbours: dict[str, set[str]] = {}
        for c in ctx.state.claims.values():
            if c.relation in (ClaimRelation.INDICATED_FOR, ClaimRelation.HERB_INDICATION, ClaimRelation.COMPOSED_OF):
                members = _terms(c)
                for m in members:
                    neighbours.setdefault(m, set()).update(members - {m})
        cache.update({k: len(v) for k, v in neighbours.items()})
    return cache


def _terms(claim: Any) -> set[str]:
    return {a.term_id for a in claim.arguments if a.term_id and not a.negated and not a.qualifiers.get("outcome")}


def _obj(h: Any, check: str, severity: str, detail: str, **kw: Any) -> dict[str, Any]:
    return {"check": check, "severity": severity, "detail": detail, **kw}


def _targets(ctx: Any) -> list[Any]:
    state = ctx.state
    explicit = [state.hypotheses[h] for h in ctx.inputs.get("hypothesis_ids") or [] if h in state.hypotheses]
    reviewed = {r.hypothesis_id for r in state.reviews.values()}
    # every proposed, unreviewed hypothesis — revisions and late arrivals (e.g. cross-space bridges) included
    fresh = [h for h in state.hypotheses.values() if h.status == "proposed" and h.id not in reviewed]
    chosen = {h.id: h for h in explicit + fresh if h.status not in ("rejected", "superseded", "expert_rejected", "expert_approved")}
    return [chosen[k] for k in sorted(chosen)]


def _review(ctx: Any, h: Any) -> dict[str, Any]:
    state = ctx.state
    corpus = ctx.cap("corpus")
    need = ctx.goal.required_evidence.min_independent_sources if ctx.goal else 2
    support = [state.evidence[e] for e in h.supporting_evidence if e in state.evidence]
    obs = [state.observations[o] for o in h.observation_ids if o in state.observations]
    data = obs[0].data if obs else {}
    stats = obs[0].statistics if obs else {}
    objections: list[dict[str, Any]] = []
    checks: list[str] = []

    checks.append("provenance")
    for r in support:
        hits = ctx.tool("validation.verify_quote", quote=r.quote, passage_id=r.passage_id)
        if not hits:
            objections.append(_obj(h, "provenance", "critical", f"证据 {r.id} 的引文无法在 {r.passage_id} 中逐字核实"))

    checks.append("anachronism")
    if not ctx.hook(HookPoint.AFTER_HYPOTHESIS, h, subject_id=h.id).allow:
        objections.append(_obj(h, "anachronism", "critical", "陈述将历史概念等同于现代医学范畴或违反研究契约中的禁止假设"))

    checks.append("edition_variant")
    contested = []
    for r in support:
        a = state.philology.get(r.passage_id)
        spans = a.contested_at(r.start, r.end) if a else []
        if spans:
            contested.append((r, min(c.base_probability() for c in spans), spans[0].base))
    if h.kind == "contradiction" and data.get("type") == "philological":
        if not contested:
            objections.append(_obj(h, "edition_variant", "major", "假说以异文解释矛盾，但证据中未见任何校勘争议"))
    elif contested:
        all_contested = len(contested) == len(support)
        worst = min(p for _, p, _ in contested)
        detail = "；".join(f"{r.passage_id}「{base}」底本读法 p={p:.2f}" for r, p, base in contested[:3])
        severity = ("critical" if worst < 0.4 else "major") if all_contested else "minor"
        objections.append(_obj(h, "edition_variant", severity, f"证据依赖存在异文的读法：{detail}",
                               passage_ids=[r.passage_id for r, _, _ in contested]))

    checks.append("homonym")
    passages = {r.passage_id for r in support}
    for term in h.terms[:3]:
        risky = [x for x in state.term_resolutions.values() if x.term_id == term and x.passage_id in passages and x.homonym_risk]
        if risky and (h.kind != "concept_drift" or len(risky) * 2 >= len(passages)):
            objections.append(_obj(h, "homonym", "major",
                                   f"「{surface(term)}」在 {len(risky)} 处证据中存在同名异义风险（义项判定概率 < 0.6），关联可能混合了不同义项",
                                   passage_ids=sorted({x.passage_id for x in risky})))

    checks.append("transcription_dependence")
    cluster = cluster_fn(ctx)
    books = sorted({r.book_id for r in support})
    clusters = sorted({cluster(b) for b in books})
    if len(clusters) < len(books):
        objections.append(_obj(h, "transcription_dependence", "major" if len(clusters) < need else "minor",
                               f"{len(books)} 部书的证据只构成 {len(clusters)} 个独立来源（同一作者或转录关系）"))

    checks.append("single_source")
    if len(clusters) < need:
        severity = "minor" if h.kind in LOCAL_KINDS else "major"
        objections.append(_obj(h, "single_source", severity, f"仅有 {len(clusters)} 个独立来源（要求 ≥ {need}）"))

    if h.kind == "lost_knowledge":
        pivot = float(data.get("pivot_year", 960))
        checks += ["sample_size", "statistical", "earliest_source"]
        late = [p for p in scope_passages(ctx) if (corpus.year(p) or 0) >= pivot]
        if len(late) < MIN_LATE_PASSAGES:
            objections.append(_obj(h, "sample_size", "major", f"{int(pivot)} 年后仅有 {len(late)} 段文本在研究范围内，“不再出现”的证据力有限"))
        p_abs = stats.get("p_absence")
        if isinstance(p_abs, (int, float)) and p_abs >= 0.05:
            objections.append(_obj(h, "statistical", "major", f"按早期关联率推算，后世未见共现的概率为 {p_abs}，缺失并不显著"))
        head = surface(data["right"])[-1:]
        year = year_fn(ctx)
        later = [c for c in state.claims.values() if (year(c) or 0) >= pivot and data["left"] in _terms(c)]
        echoes = sorted({a.surface for c in later for a in c.arguments if head and head in a.surface
                         and a.term_id != data["left"] and not a.negated})
        if echoes:
            first = next(c for c in later if any(head in a.surface for a in c.arguments if a.term_id != data["left"]))
            objections.append(_obj(h, "partial_persistence", "major",
                                   f"后世文献仍以相近表述将「{surface(data['left'])}」与「{'、'.join(echoes[:3])}」相联（{first.passage_id}），"
                                   f"与「{surface(data['right'])}」同属一类，关联可能是转化而非失传",
                                   counter=[(first.passage_id, first.start, first.end)]))
        hits = co_mentions(ctx, data["left"], data["right"], after=pivot, exclude_passages=passages)
        if hits:
            objections.append(_obj(h, "earliest_source", "major",
                                   f"{int(pivot)} 年后仍有 {len(hits)} 处文本同时提及二者（如 {hits[0][0]}），失传结论需限定为“不再形成明确记载”",
                                   counter=hits[:3]))
    elif h.kind == "historical_testimony":
        checks.append("earliest_source")
        herb = data.get("herb")
        year = year_fn(ctx)
        marker_years = [corpus.year(corpus.passage(t["passage_id"])) for t in data.get("testimony", []) if corpus.has_passage(t["passage_id"])]
        before = min((y for y in marker_years if y is not None), default=None)
        early = [c for c in state.claims.values() if c.relation == ClaimRelation.HERB_INDICATION
                 and herb in {a.term_id for a in c.args(Role.HERB)} and before is not None and (year(c) or 9999) < before]
        if early:
            uses = "、".join(sorted({a.surface for c in early for a in c.arguments if a.role not in (Role.HERB, Role.NATURE, Role.FLAVOR)})[:6])
            objections.append(_obj(h, "earliest_source", "info", f"更早文献确有该药的其他主治记载（{uses}），与“昔人”用法的证词相互印证",
                                   resolved=True, resolution="corroborating earlier attestation"))
        else:
            objections.append(_obj(h, "earliest_source", "major", "语料中找不到早期用法的独立记载，证词无法佐证"))
    elif h.kind == "concept_drift":
        checks += ["sample_size", "statistical"]
        occ = data.get("occurrences", {})
        thin = [p for p, n in occ.items() if n < 3]
        if thin:
            objections.append(_obj(h, "sample_size", "major", f"{len(thin)} 个时期的用例少于 3 条（{', '.join(thin)}）"))
        if stats.get("bh_significant") is False:
            objections.append(_obj(h, "statistical", "major", f"语境差异未通过置换检验 + BH 校正（p={stats.get('p_value')}）"))
    elif h.kind == "association_rule":
        checks.append("statistical")
        if stats.get("bh_significant") is False:
            objections.append(_obj(h, "statistical", "major", f"Fisher 检验经 BH 校正后不显著（p={stats.get('p_value')}）"))
    elif h.kind == "hidden_association":
        checks += ["contraindication", "taxonomy", "differential", "counterexample", "statistical"]
        left, right = data["left"], data["right"]
        contra = [c for c in state.claims.values() if c.relation == ClaimRelation.CONTRAINDICATED and {left, right} <= _terms(c)]
        if contra:
            objections.append(_obj(h, "contraindication", "critical", f"文本明确禁忌：{contra[0].passage_id}「{contra[0].quote}」",
                                   counter=[(c.passage_id, c.start, c.end) for c in contra[:3]]))
        implied = related_terms(ctx, left)
        taxonomic = [c for c in state.claims.values() if c.relation == ClaimRelation.INDICATED_FOR and right in _terms(c)
                     and implied & _terms(c)]
        if taxonomic:
            via = sorted(implied & _terms(taxonomic[0]))
            objections.append(_obj(h, "taxonomy", "critical",
                                   f"关联已由术语层级蕴含：{surface(right)} 用于「{'、'.join(surface(v) for v in via)}」（属于/包含「{surface(left)}」），"
                                   f"见 {taxonomic[0].passage_id}「{taxonomic[0].quote[:40]}」",
                                   counter=[(c.passage_id, c.start, c.end) for c in taxonomic[:3]]))
        rivals = []
        for pid, _, _ in co_mentions(ctx, left, right, level="passage"):
            for c in state.claims.values():
                members = _terms(c)
                if c.passage_id == pid and c.relation == ClaimRelation.INDICATED_FOR and left in members and right not in members \
                        and any(m.split(":")[0] == right.split(":")[0] for m in members):
                    rivals.append(c)
        if rivals:
            other = sorted({m for c in rivals for m in _terms(c) if m.split(":")[0] == right.split(":")[0]})
            objections.append(_obj(h, "differential", "critical",
                                   f"同段文本作鉴别：「{surface(left)}」归于 {'、'.join(surface(o) for o in other)} 而非 {surface(right)}"
                                   f"（{rivals[0].passage_id}「{rivals[0].quote[:40]}」）",
                                   counter=[(c.passage_id, c.start, c.end) for c in rivals[:3]]))
        degree = _degrees(ctx)
        cutoff = sorted(degree.values())[int(len(degree) * 0.9)] if degree else 0
        hubs = [v for v in data.get("via", []) if degree.get(v, 0) >= cutoff]
        if len(hubs) >= 2:
            objections.append(_obj(h, "hub_driven", "major",
                                   f"连接主要经由高频枢纽概念（{'、'.join(surface(v) for v in hubs)}，度数位于前 10%），推断特异性低"))
        hits = co_mentions(ctx, left, right)
        if hits:
            objections.append(_obj(h, "counterexample", "major",
                                   f"二者已在 {len(hits)} 处文本中共现（如 {hits[0][0]}），并非完全隐性的关联", counter=hits[:3]))
        if isinstance(stats.get("empirical_p"), (int, float)) and stats["empirical_p"] > 0.1:
            objections.append(_obj(h, "statistical", "minor", f"链接得分在候选对中的经验排名 p={stats['empirical_p']}"))
    elif h.kind == "formula_evolution":
        checks.append("lineage_strength")
        if not data.get("stable_core"):
            objections.append(_obj(h, "lineage_strength", "major", "家族内没有共同核心药物，谱系证据薄弱（可能为趋同组方）"))
        weak = [s for s in data.get("steps", []) if (s.get("overlap") or 0) < 0.5]
        if weak:
            objections.append(_obj(h, "lineage_strength", "minor", f"{len(weak)} 个化裁步骤的组成重叠 < 0.5"))
    elif h.kind == "contradiction" and data.get("label") == "contradiction" and stats.get("same_school"):
        checks.append("school")
        objections.append(_obj(h, "school", "minor", "两说出自同一学派，可能是学派内部的争鸣而非范式转换"))

    checks.append("known_finding")
    score, rationale = novelty(h.terms, ctx.cap("domain").known_findings)
    if score <= 0.5:
        objections.append(_obj(h, "known_finding", "info", f"与既有认识高度重叠（{rationale}），更可能是再发现而非新发现",
                               resolved=True, resolution="affects novelty, not validity"))
    return {"hypothesis_id": h.id, "checks_run": checks, "objections": objections}


def draft(ctx: Any) -> dict[str, Any]:
    reviews = []
    for h in _targets(ctx):
        item = _review(ctx, h)
        item["verdict"] = verdict(item["objections"], h)
        item["summary"] = ""
        reviews.append(item)
    return {"reviews": reviews}


def verdict(objections: list[dict[str, Any]], h: Any) -> str:
    open_ = [o for o in objections if not o.get("resolved")]
    critical = [o for o in open_ if o["severity"] == "critical"]
    if critical:
        revisable = all(o["check"] == "edition_variant" for o in critical) and h.generation < MAX_REVISIONS
        return "revise" if revisable else "reject"
    majors = [o for o in open_ if o["severity"] == "major"]
    if majors and h.generation < MAX_REVISIONS and any(o["check"] in QUALIFIER_FOR for o in majors):
        return "revise"
    return "survives"


def _counter_records(ctx: Any, h: Any, raw: dict[str, Any]) -> list[Any]:
    records = []
    for item in raw.get("counter", []) or []:
        pid, start, end = item
        records.append(evidence_record(ctx, pid, start, end, method="falsification:co_mention", stance=Stance.CONTRADICTS,
                                       hypothesis_id=h.id, note=raw["check"], textual=0.5))
    for q in raw.get("counter_evidence", []) or []:
        span = locate(ctx, q.get("passage_id", ""), q.get("quote", ""))
        if span is not None:
            records.append(evidence_record(ctx, q["passage_id"], span[0], span[1], method=f"falsification:{ctx.route.model}",
                                           stance=Stance.CONTRADICTS, hypothesis_id=h.id, note=raw["check"], textual=0.6))
    return records


def commit(ctx: Any, output: dict[str, Any]) -> str:
    state = ctx.state
    counts = {"survives": 0, "revise": 0, "reject": 0}
    # a model may add objections, but it cannot skip a review: missing ones come from the deterministic checks
    items = {r["hypothesis_id"]: r for r in (ctx.draft or {}).get("reviews", [])}
    if output is not ctx.draft:
        for r in output.get("reviews", []):
            base = items.get(r.get("hypothesis_id"), {})
            merged = {**base, **r}
            seen = {(o["check"], o["detail"]) for o in r.get("objections", [])}
            merged["objections"] = list(r.get("objections", [])) + [
                o for o in base.get("objections", []) if (o["check"], o["detail"]) not in seen and o["severity"] in ("critical", "major")]
            items[r.get("hypothesis_id")] = merged
    for item in [items[k] for k in sorted(items)]:
        h = state.hypotheses.get(item.get("hypothesis_id", ""))
        if h is None:
            continue
        objections: list[Objection] = []
        counter_ids: list[str] = []
        all_counter = []
        checked = []
        for raw in item.get("objections", []):
            records = _counter_records(ctx, h, raw)
            severity = raw["severity"]
            if severity == "critical" and raw["check"] not in ("provenance", "anachronism", "edition_variant") and not records:
                severity = "major"  # evidence-bound skepticism
            resolved = bool(raw.get("resolved", False))
            resolution = raw.get("resolution", "")
            key = QUALIFIER_FOR.get(raw["check"])
            if not resolved and key and key in h.qualifiers and severity != "critical":
                resolved, resolution = True, f"addressed by revision: {key}={h.qualifiers[key]}"
            oid = stable_id("obj", h.id, raw["check"], raw["detail"])
            objections.append(Objection(id=oid, check=raw["check"], severity=severity, detail=raw["detail"],
                                        evidence_ids=[r.id for r in records], passage_ids=list(raw.get("passage_ids", [])),
                                        resolved=resolved, resolution=resolution))
            all_counter += records
            counter_ids += [r.id for r in records]
            checked.append({**raw, "severity": severity, "resolved": resolved})
        final = verdict(checked, h)
        if all_counter:
            unique = list({r.id: r for r in all_counter}.values())
            ctx.emit(EventType.COUNTER_EVIDENCE_FOUND, {"hypothesis_id": h.id, "records": [r.to_dict() for r in unique]},
                     generated=[r.id for r in unique])
        review = HypothesisReview(
            id=stable_id("rev", h.id, ctx.task.round, ctx.task.kind),
            hypothesis_id=h.id,
            reviewer=ctx.actor.id,
            verdict=final,
            objections=objections,
            summary=item.get("summary") or f"{final}: " + "; ".join(f"{o.severity}/{o.check}{'✓' if o.resolved else ''}" for o in objections),
            round=ctx.task.round,
            checks_run=list(item.get("checks_run", [])),
        )
        ctx.emit(EventType.HYPOTHESIS_REVIEWED, {"review": review.to_dict()}, generated=[review.id], used=[h.id])
        counts[final] += 1
    return f"reviewed {sum(counts.values())}: survives {counts['survives']}, revise {counts['revise']}, reject {counts['reject']}"
