"""D5 · Contradiction Discovery.

Scientific questions often start from disagreement.  This module finds claim
pairs that make opposing assertions about a shared subject and classifies them
into the benchmark labels (design §23):

  support · contradiction · conditional · apparent · unrelated

with a finer internal type and candidate explanations (时代不同 / 病种含义变化 /
条件不同 / 理论体系不同 / 名同义异 / 文本异文).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

from ..protocol.base import stable_id
from ..protocol.claims import INTERVENTION_ROLES, Claim, ClaimRelation, Role
from ..protocol.research import Contradiction

FINDINGS = (Role.SYMPTOM, Role.SIGN, Role.PULSE, Role.TONGUE)
CAUSAL = (Role.ETIOLOGY, Role.PATHOGENESIS)
LABEL_ORDER = {"contradiction": 4, "conditional": 3, "apparent": 2, "support": 1, "unrelated": 0}


@dataclass
class ContradictionContext:
    polarity: dict[str, dict[str, float]] = field(default_factory=dict)  # term → {axis: value}
    origin: dict[str, str] = field(default_factory=dict)  # term → external | internal
    nature: dict[str, float] = field(default_factory=dict)  # intervention term → thermal direction
    related: dict[str, set[str]] = field(default_factory=dict)  # term → linked subject terms
    name_etiology: dict[str, list[str]] = field(default_factory=dict)  # disease term → etiology term ids
    opposites: dict[str, str] = field(default_factory=dict)  # finding term → opposite finding term
    components: dict[str, list[str]] = field(default_factory=dict)
    school_of: dict[str, str | None] = field(default_factory=dict)  # book → school
    year_fn: Callable[[Claim], float | None] = lambda c: c.year()
    sense_fn: Callable[[Claim, str], str | None] = lambda c, t: None
    contested_fn: Callable[[Claim, int | None, int | None], bool] = lambda c, s, e: False
    reuse_fn: Callable[[str, str], str | None] = lambda a, b: None  # passage pair → transcribes / rephrases / inherits


@dataclass
class Assertion:
    key: str  # etiology:<term> | origin | cold_heat | treatment_nature | finding:<term>
    value: float
    term: str
    start: int | None = None
    end: int | None = None


def _args(claim: Claim, *roles: Role, negated: bool | None = None, optional: bool = False):
    for a in claim.args(*roles):
        if a.term_id is None or a.qualifiers.get("outcome"):
            continue
        if not optional and a.qualifiers.get("optional"):
            continue
        if negated is not None and a.negated != negated:
            continue
        yield a


def subject_sets(claim: Claim, ctx: ContradictionContext) -> tuple[set[str], set[str]]:
    """(direct subjects, subjects expanded to broader/narrower terms)."""
    rel = claim.relation
    direct: set[str] = set()
    if rel in (ClaimRelation.CAUSES, ClaimRelation.PATHOGENESIS):
        direct |= {a.term_id for a in _args(claim, Role.DISEASE, Role.PATTERN, Role.SYMPTOM, Role.CONCEPT, negated=False)}
    elif rel == ClaimRelation.TREATMENT_PRINCIPLE:
        direct |= {a.term_id for a in _args(claim, Role.ETIOLOGY, Role.PATHOGENESIS, Role.SYMPTOM, Role.DISEASE, Role.PATTERN, negated=False)
                   if not a.qualifiers.get("from_heading")}
    elif rel == ClaimRelation.DEFINES:
        definiendum = next((a for a in _args(claim, Role.DISEASE, Role.PATTERN, negated=False) if not a.qualifiers.get("from_heading")), None)
        if definiendum is not None:
            direct.add(definiendum.term_id)
            if ctx.name_etiology.get(definiendum.term_id):
                # a definition by named etiology (风之为病 → 半身不遂) also speaks about its findings
                direct |= {a.term_id for a in _args(claim, *FINDINGS, negated=False)}
    elif rel == ClaimRelation.INDICATED_FOR:
        direct |= {a.term_id for a in _args(claim, Role.DISEASE, Role.PATTERN, negated=False) if not a.qualifiers.get("from_heading")}
    direct = {d for d in direct if d}
    expanded = set(direct)
    for d in direct:
        expanded |= ctx.related.get(d, set())
    return direct, expanded


def subjects(claim: Claim, ctx: ContradictionContext) -> set[str]:
    return subject_sets(claim, ctx)[1]


def assertions(claim: Claim, ctx: ContradictionContext) -> list[Assertion]:
    rel = claim.relation
    out: list[Assertion] = []
    if rel in (ClaimRelation.CAUSES, ClaimRelation.PATHOGENESIS):
        for a in _args(claim, *CAUSAL):
            sign = -1.0 if a.negated else 1.0
            out.append(Assertion(f"etiology:{a.term_id}", sign, a.term_id, a.start, a.end))
            if not a.negated:
                if a.term_id in ctx.origin:
                    out.append(Assertion("origin", 1.0 if ctx.origin[a.term_id] == "internal" else -1.0, a.term_id, a.start, a.end))
                for axis, value in ctx.polarity.get(a.term_id, {}).items():
                    out.append(Assertion(axis, value, a.term_id, a.start, a.end))
    if rel == ClaimRelation.DEFINES:
        for d in _args(claim, Role.DISEASE, Role.PATTERN, negated=False):
            for ety in ctx.name_etiology.get(d.term_id, []):
                out.append(Assertion(f"etiology:{ety}", 1.0, ety, d.start, d.end))
                if ety in ctx.origin:
                    out.append(Assertion("origin", 1.0 if ctx.origin[ety] == "internal" else -1.0, ety, d.start, d.end))
    if rel == ClaimRelation.TREATMENT_PRINCIPLE:
        for a in _args(claim, Role.TREATMENT_METHOD, Role.TREATMENT_PRINCIPLE):
            value = a.qualifiers.get("nature")
            nature = float(value) if value not in (None, "", "None") else ctx.nature.get(a.term_id)
            if nature:
                out.append(Assertion("treatment_nature", nature * (-1 if a.negated else 1), a.term_id, a.start, a.end))
    if rel in (ClaimRelation.DEFINES, ClaimRelation.INDICATED_FOR):
        for a in _args(claim, *FINDINGS, Role.DISEASE):
            terms = ctx.components.get(a.term_id) or [a.term_id]
            for t in terms:
                out.append(Assertion(f"finding:{t}", -1.0 if a.negated else 1.0, t, a.start, a.end))
    signs: dict[str, set[bool]] = {}
    for x in out:
        signs.setdefault(x.key, set()).add(x.value > 0)
    return [x for x in out if len(signs[x.key]) == 1 or x.key in ("cold_heat", "deficiency_excess", "exterior_interior")]


def internal_inconsistency(claim: Claim, ctx: ContradictionContext) -> dict | None:
    """A cold formula prescribed for an explicitly cold interior (or hot for hot) within one claim."""
    if claim.relation != ClaimRelation.INDICATED_FOR:
        return None
    formulas = [a for a in _args(claim, Role.FORMULA, Role.HERB) if ctx.nature.get(a.term_id)]
    for f in formulas:
        for p in _args(claim, Role.PATHOGENESIS, negated=False):
            pol = ctx.polarity.get(p.term_id, {})
            if pol.get("cold_heat") and pol.get("exterior_interior", 0) > 0 and (pol["cold_heat"] > 0) == (ctx.nature[f.term_id] > 0):
                return {"formula": f.term_id, "pathogenesis": p.term_id, "span": [p.start, p.end]}
    return None


def _unanimous(assertions_: list[Assertion], key: str) -> bool:
    values = {x.value > 0 for x in assertions_ if x.key == key}
    return len(values) == 1


def _opposed(a: list[Assertion], b: list[Assertion], ctx: ContradictionContext, *, findings_ok: bool = True) -> list[tuple[Assertion, Assertion]]:
    pairs: list[tuple[Assertion, Assertion]] = []
    by_key_b: dict[str, list[Assertion]] = {}
    for x in b:
        by_key_b.setdefault(x.key, []).append(x)
    for x in a:
        if x.key.startswith("finding:") and not findings_ok:
            continue
        if x.key in ("origin", "cold_heat", "deficiency_excess", "exterior_interior") and not (
            _unanimous(a, x.key) and _unanimous(b, x.key)
        ):
            continue  # mixed-cause claims do not take a side on this axis
        for y in by_key_b.get(x.key, []):
            if x.value * y.value < 0:
                pairs.append((x, y))
        if x.key.startswith("finding:"):
            opp = ctx.opposites.get(x.term)
            if opp:
                for y in by_key_b.get(f"finding:{opp}", []):
                    if x.value > 0 and y.value > 0:
                        pairs.append((x, y))
    return pairs


def _agreements(a: list[Assertion], b: list[Assertion]) -> int:
    keys_b = {(x.key, x.value > 0) for x in b if not x.key.startswith("finding:")}
    return sum(1 for x in a if (x.key, x.value > 0) in keys_b and x.key.startswith("etiology:"))


def _conditions(claim: Claim) -> set[str]:
    out = set()
    for a in claim.arguments:
        if a.term_id is None:
            continue
        if a.role == Role.CONDITION and a.qualifiers.get("kind") not in ("exposure_season", "onset_season"):
            if a.term_id.startswith("condition:") and a.term_id.split(":", 1)[1] in "春夏秋冬":
                continue
            out.add(a.term_id)
        elif a.qualifiers.get("from_heading") and a.role in (Role.ETIOLOGY, Role.PATTERN):
            out.add(a.term_id)
        elif claim.relation == ClaimRelation.TREATMENT_PRINCIPLE and a.role in (Role.PATTERN,):
            out.add(a.term_id)
    return out


def classify(a: Claim, b: Claim, ctx: ContradictionContext) -> dict:
    """Classify the relation between two claims. Returns a dict with label/type/explanations."""
    if a.id == b.id:
        inner = internal_inconsistency(a, ctx)
        if inner is None:
            return {"label": "unrelated", "type": "none"}
        span = inner["span"]
        if "machine-segmented" in a.tags:
            return {"label": "apparent", "type": "segmentation", "subject": inner["pathogenesis"], "axis": "cold_heat",
                    "explanations": ["白文机器断句：方药与病机可能出自相邻条文，单条主张内的寒热不一致需人工断句核对"]}
        contested = ctx.contested_fn(a, span[0], span[1])
        return {
            "label": "apparent" if contested else "contradiction",
            "type": "philological" if contested else "internal",
            "subject": inner["pathogenesis"],
            "axis": "cold_heat",
            "explanations": [
                f"方性与病机寒热同向：{inner['formula'].split(':', 1)[1]} vs {inner['pathogenesis'].split(':', 1)[1]}",
                *(["该处存在异文（校勘争议），可能为文本讹误而非学术矛盾"] if contested else []),
            ],
        }
    direct_a, exp_a = subject_sets(a, ctx)
    direct_b, exp_b = subject_sets(b, ctx)
    identical = direct_a & direct_b
    shared = identical | (direct_a & exp_b) | (exp_a & direct_b)  # same subject or parent–child, never siblings
    if not shared:
        return {"label": "unrelated", "type": "none"}
    asa, asb = assertions(a, ctx), assertions(b, ctx)
    # findings only disagree about the *same* entity; subtypes legitimately differ from their parent
    opposed = _opposed(asa, asb, ctx, findings_ok=bool(identical))
    subject = sorted(identical)[0] if identical else sorted(shared)[0]
    if not opposed:
        if _agreements(asa, asb):
            return {"label": "support", "type": "agreement", "subject": subject}
        return {"label": "unrelated", "type": "none", "subject": subject}
    x, y = opposed[0]
    ya, yb = ctx.year_fn(a), ctx.year_fn(b)
    gap = abs((ya or 0) - (yb or 0)) if ya is not None and yb is not None else None
    explanations: list[str] = []
    if gap is not None and gap > 300:
        explanations.append(f"时代不同：相隔约 {int(gap)} 年")
    school_a, school_b = ctx.school_of.get(a.book_id), ctx.school_of.get(b.book_id)
    if school_a and school_b and school_a != school_b:
        explanations.append(f"理论体系不同：{school_a} vs {school_b}")
    contested = ctx.contested_fn(a, x.start, x.end) or ctx.contested_fn(b, y.start, y.end)
    if contested:
        explanations.append("相关文字存在异文，可能是文本问题")
        return {"label": "apparent", "type": "philological", "subject": subject, "axis": x.key, "explanations": explanations,
                "evidence": {"a": [x.term, x.value], "b": [y.term, y.value]}}
    same_terms = [t for t in shared if t in {arg.term_id for arg in a.arguments} and t in {arg.term_id for arg in b.arguments}]
    for t in same_terms:
        sa, sb = ctx.sense_fn(a, t), ctx.sense_fn(b, t)
        if sa and sb and sa != sb:
            explanations.insert(0, f"病种含义变化 / 名同义异：{t.split(':', 1)[1]} 在两处分别为「{sa}」与「{sb}」")
            return {"label": "apparent", "type": "sense_shift", "subject": t, "axis": x.key, "explanations": explanations,
                    "evidence": {"a": [x.term, x.value], "b": [y.term, y.value], "senses": [sa, sb]}}
    if a.relation == b.relation == ClaimRelation.INDICATED_FOR and x.key.startswith("finding:"):
        ia = {arg.term_id for arg in a.args(*INTERVENTION_ROLES) if arg.term_id and not arg.negated}
        ib = {arg.term_id for arg in b.args(*INTERVENTION_ROLES) if arg.term_id and not arg.negated}
        if ia and ib and not ia & ib:
            # different presentations, different prescriptions: the texts partition the disease (辨证), they do not conflict
            return {"label": "unrelated", "type": "differential", "subject": subject, "axis": x.key,
                    "explanations": ["辨证分治：不同表现用不同方药，属鉴别而非矛盾"],
                    "evidence": {"a": [x.term, x.value], "b": [y.term, y.value]}}
    if x.key.startswith("finding:") and ("machine-segmented" in a.tags or "machine-segmented" in b.tags):
        # in unpunctuated text a claim may absorb a neighbouring clause (an adjacent 条文 with the opposite finding):
        # finding-level oppositions read through machine segmentation are not evidence of a disagreement
        explanations.insert(0, "白文机器断句：主张范围可能并入相邻条文，症状层面的对立需人工断句核对")
        return {"label": "apparent", "type": "segmentation", "subject": subject, "axis": x.key, "explanations": explanations,
                "evidence": {"a": [x.term, x.value], "b": [y.term, y.value]}}
    ca, cb = _conditions(a), _conditions(b)
    if ca ^ cb:
        diff = sorted(ca ^ cb)
        explanations.insert(0, "条件不同：" + "、".join(d.split(":", 1)[1] for d in diff))
        return {"label": "conditional", "type": "conditional", "subject": subject, "axis": x.key, "explanations": explanations,
                "evidence": {"a": [x.term, x.value], "b": [y.term, y.value], "conditions": diff}}
    kind = "theoretical" if (gap and gap > 300) or (school_a and school_b and school_a != school_b) else "direct"
    if not explanations:
        explanations.append("同一主题下的直接对立主张")
    return {"label": "contradiction", "type": kind, "subject": subject, "axis": x.key, "explanations": explanations,
            "evidence": {"a": [x.term, x.value], "b": [y.term, y.value]}}


def find_contradictions(claims: list[Claim], ctx: ContradictionContext, *, cross_book_only: bool = True,
                        detector: str = "contradiction@0.1") -> list[Contradiction]:
    out: list[Contradiction] = []
    for c in claims:
        verdict = classify(c, c, ctx)
        if verdict["label"] != "unrelated":
            out.append(_record(c, c, verdict, detector))
    relevant = [c for c in claims if c.relation in (
        ClaimRelation.CAUSES, ClaimRelation.PATHOGENESIS, ClaimRelation.TREATMENT_PRINCIPLE,
        ClaimRelation.DEFINES, ClaimRelation.INDICATED_FOR)]
    for a, b in combinations(sorted(relevant, key=lambda c: c.id), 2):
        if a.passage_id == b.passage_id or (cross_book_only and a.book_id == b.book_id):
            continue
        verdict = classify(a, b, ctx)
        if verdict["label"] in ("contradiction", "conditional", "apparent"):
            out.append(_record(a, b, verdict, detector))
    return out


def _record(a: Claim, b: Claim, verdict: dict, detector: str) -> Contradiction:
    confidence = {"contradiction": 0.7, "conditional": 0.6, "apparent": 0.55}.get(verdict["label"], 0.4)
    return Contradiction(
        id=stable_id("ctr", a.id, b.id),
        claim_a=a.id,
        claim_b=b.id,
        subject=verdict.get("subject", ""),
        axis=verdict.get("axis", ""),
        label=verdict["label"],
        type=verdict["type"],
        explanation="；".join(verdict.get("explanations", [])),
        candidate_explanations=list(verdict.get("explanations", [])),
        evidence={"detector": detector, **verdict.get("evidence", {})},
        confidence=confidence,
    )


def classify_passages(claims_a: list[Claim], claims_b: list[Claim], ctx: ContradictionContext,
                      passage_a: str | None = None, passage_b: str | None = None) -> dict:
    """Strongest relation between two passages (used by ContradictionEval).

    Text reuse (transcription, rephrasing, inheritance) between the passages counts as support when the
    claims themselves take no opposing positions.
    """
    best = {"label": "unrelated", "type": "none"}
    pairs = [(a, a) for a in claims_a] if claims_a == claims_b else [(a, b) for a in claims_a for b in claims_b]
    for a, b in pairs:
        verdict = classify(a, b, ctx)
        if LABEL_ORDER[verdict["label"]] > LABEL_ORDER[best["label"]]:
            best = {**verdict, "claims": [a.id, b.id]}
    pa = passage_a or (claims_a[0].passage_id if claims_a else None)
    pb = passage_b or (claims_b[0].passage_id if claims_b else None)
    if best["label"] == "unrelated" and pa and pb and pa != pb:
        reuse = ctx.reuse_fn(pa, pb) or ctx.reuse_fn(pb, pa)
        if reuse:
            best = {"label": "support", "type": f"text_reuse:{reuse}", "explanations": [f"文本承袭（{reuse}）：两处表达同一学说"]}
    return best
