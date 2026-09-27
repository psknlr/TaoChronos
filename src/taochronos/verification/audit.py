"""证据审计 (S15 Evidence Audit) — a claim decomposed into atomic claims, each checked by what it asserts.

Decomposition (rules): sentences, then the inference connectives inside them (所以, 因此, 可见, 证明 …) split premise
from conclusion.  Each atomic claim is classified:

* **historical** (《金匮》载「男子消渴，小便反多」) — the work must be known, every 「quote」 found verbatim (after
  normalising variants) in it; a paraphrase without a quote can only be partially supported;
* **interpretive** (「几几」者，伸颈之貌) — needs a cited gloss or commentator;
* **mapping** (消渴与糖尿病表型相近) — the presentism guard (no equation, no retrospective diagnosis) and, where the
  bridge can score it, no stronger than its level (相似 at a low level passes; 即 never does);
* **modern** (黄连素可降低2型糖尿病患者血糖) — needs modern evidence of a design that can carry the claim's level: an
  animal study cannot carry efficacy in people, a network-pharmacology prediction cannot carry efficacy at all;
* **inference** (…，所以X可治疗糖尿病) — a step from the historical space to modern efficacy is an inference leap, unless
  it is put as a hypothesis to test;
* **clinical** (每日服30克) — never given: TaoChronos gives no clinical or dosage advice; toxic materials are flagged.

Verdicts: SUPPORTED (every atomic claim supported), PARTIALLY_SUPPORTED (none fails, some are not verifiable), CONTESTED
(the evidence speaks against a part), INSUFFICIENT_EVIDENCE (nothing to check it against), UNSUPPORTED (a check fails: a
quote not in the witness, an equation, an inference leap, cross-level evidence, clinical advice).  A model, when one is
given, may add concerns and lower a verdict — never raise one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..protocol.assertions import AuditVerdict, ClaimKind
from ..protocol.modern import ClaimLevel, EvidenceType, cross_level

V = AuditVerdict
K = ClaimKind
SENTENCE = re.compile(r"[^。；！？!?;\n]+[。；！？!?;]?")
INFER = re.compile(r"(所以|因此|因而|故而|可见|由此可见|这说明|说明|这证明|证明|提示|表明)")
QUOTE = re.compile(r"[「“]([^」”]{2,})[」”]")
WORK = re.compile(r"《([^》]{2,20})》")
CLINICAL = re.compile(r"(每日|每次|每天|日服|顿服|\d+\s*(?:克|g|毫克|mg|钱|两)|可用于治疗|建议(?:患者|服用|使用)|推荐(?:用于|服用)|"
                      r"适用于[^。，]{0,8}患者|处方|代替[^。，]{0,6}药)")
MODERN_WORDS = re.compile(r"(研究|试验|临床|患者|病人|机制|通路|靶点|血糖|血压|RCT|meta|Meta|荟萃|系统评价|动物|小鼠|大鼠|细胞|"
                          r"网络药理|分子对接|有效率|疗效|降低|改善|抑制|激活|表达|显著)")
HISTORICAL_WORDS = re.compile(r"(载|记载|记述|言|曰|云|称|谓|论|描述|提到|指出)")
INTERP_WORDS = re.compile(r"(者，[^。]{1,12}也|是指|指的是|意为|意思是|犹言|训为|释为|注云|注曰)")
MAPPING_WORDS = re.compile(r"(相当于|等同|等于|即是|就是|即为|即|对应|类似|相似|相近|相容|近似|重合|吻合|符合)")
STRONG = re.compile(r"(相当于|等同|等于|即是|就是|即为|(?<![不非])即|确诊|证明|无疑|必然是)")
HEDGED_HYPOTHESIS = re.compile(r"(假设|假说|有待|值得|尚需|需要验证|待验证|可能|或许|推测|可作为)")
EFFICACY = re.compile(r"(有效|疗效|治愈|改善|降低|升高|缓解|减少|优于|治疗[^。，]{0,6}(?:病|症))")
ASSOCIATION = re.compile(r"(相关|关联|风险|发生率)")
MECHANISM = re.compile(r"(机制|通路|靶点|抑制|激活|表达|受体|信号)")
PREDICTION = re.compile(r"(网络药理|分子对接|预测|计算)")
SAFETY = re.compile(r"(毒性|不良反应|相互作用|中毒|肝损|肾损)")


@dataclass
class AuditContext:
    """What an audit may consult; the service that runs it supplies the callables."""

    normalize: Callable[[str], str]
    work_of: Callable[[str], str | None]  # 《title》 → book id, or None
    locate: Callable[[str, str | None], list[str]]  # quote, book id → passage ids that carry it
    guard: Any  # verification.presentism.PresentismGuard
    bridge: Callable[[str], dict[str, Any]] | None = None  # a text → a bridge mapping
    modern: Callable[[str], list[dict[str, Any]]] | None = None  # a query → typed modern records
    modern_terms: list[str] = field(default_factory=list)  # modern disease / drug names
    ancient_terms: list[str] = field(default_factory=list)  # historical terms of the terminology
    safety: dict[str, dict[str, Any]] = field(default_factory=dict)  # toxic materials
    glossators: list[str] = field(default_factory=list)  # commentators whose name makes a gloss cited
    locate_by: Callable[[str, str], list[str]] | None = None  # a gloss, a commentator → passages of their works carrying it


def decompose(text: str) -> list[dict[str, Any]]:
    """Atomic claims: sentences, split at the inference connectives (premise / conclusion)."""
    out: list[dict[str, Any]] = []
    for m in SENTENCE.finditer(text):
        sent = m.group(0).strip()
        if len(sent) < 2:
            continue
        parts = INFER.split(sent)
        if len(parts) == 1:
            out.append({"text": sent, "role": "statement"})
            continue
        head = parts[0].strip("，, ")
        if head:
            out.append({"text": head, "role": "premise"})
        for k in range(1, len(parts), 2):
            body = (parts[k] + parts[k + 1]).strip("，, ") if k + 1 < len(parts) else parts[k]
            if body:
                out.append({"text": body, "role": "conclusion", "connective": parts[k]})
    for k, c in enumerate(out, 1):
        c["id"] = f"C{k}"
    return out


def classify(claim: dict[str, Any], ctx: AuditContext) -> ClaimKind:
    t = claim["text"]
    modern = bool(ctx.guard.modern_terms_in(t)) if ctx.guard is not None else False
    modern = modern or any(m and m in t for m in ctx.modern_terms)
    ancient = any(a and a in t for a in ctx.ancient_terms)
    if CLINICAL.search(t):
        return K.CLINICAL
    if claim.get("role") == "conclusion" and (modern or MODERN_WORDS.search(t)):
        return K.INFERENCE
    if ancient and modern and MAPPING_WORDS.search(t):
        return K.MAPPING
    if QUOTE.search(t) or WORK.search(t) or (HISTORICAL_WORDS.search(t) and ancient and not modern):
        if INTERP_WORDS.search(t) and not WORK.search(t):
            return K.INTERPRETIVE
        return K.HISTORICAL
    if INTERP_WORDS.search(t):
        return K.INTERPRETIVE
    if modern or MODERN_WORDS.search(t):
        return K.MODERN
    return K.HISTORICAL if ancient else K.MODERN


def claim_level(text: str) -> ClaimLevel:
    if SAFETY.search(text):
        return ClaimLevel.SAFETY
    if PREDICTION.search(text):
        return ClaimLevel.PREDICTION
    if MECHANISM.search(text) and not re.search(r"患者|病人|临床", text):
        return ClaimLevel.MECHANISM
    if EFFICACY.search(text):
        return ClaimLevel.HUMAN_EFFICACY
    if ASSOCIATION.search(text):
        return ClaimLevel.HUMAN_ASSOCIATION
    return ClaimLevel.HUMAN_EFFICACY


# ---------------------------------------------------------------- checks by kind
def _check(name: str, ok: bool | None, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"check": name, "ok": ok, **({"detail": detail} if detail else {}), **extra}


def check_historical(c: dict[str, Any], ctx: AuditContext) -> tuple[AuditVerdict, list[dict[str, Any]]]:
    checks = []
    books = []
    for title in WORK.findall(c["text"]):
        bid = ctx.work_of(title)
        checks.append(_check("source_exists", bid is not None, f"《{title}》" + ("" if bid else " is not in the corpus")))
        if bid:
            books.append(bid)
    quotes = QUOTE.findall(c["text"])
    found_all = True
    passages: list[str] = []
    for q in quotes:
        hits: list[str] = []
        for bid in books or [None]:
            hits += ctx.locate(q, bid)
        if not hits and books:
            elsewhere = ctx.locate(q, None)
            checks.append(_check("exact_span", False, f"「{q}」 not in the cited work" + (f"; found in {elsewhere[0]}" if elsewhere else ""),
                                 elsewhere=elsewhere[:3]))
            found_all = False
            continue
        checks.append(_check("exact_span", bool(hits), f"「{q}」" + (f" in {hits[0]}" if hits else " is in no witness"),
                             passages=hits[:3]))
        found_all = found_all and bool(hits)
        passages += hits[:3]
    c["passages"] = passages
    if any(ch["ok"] is False for ch in checks):
        return V.UNSUPPORTED, checks
    if not quotes:
        checks.append(_check("exact_span", None, "a paraphrase with no quote: the words cannot be checked against a witness"))
        return (V.PARTIALLY_SUPPORTED if books else V.INSUFFICIENT_EVIDENCE), checks
    return (V.SUPPORTED if found_all else V.PARTIALLY_SUPPORTED), checks


GLOSS = re.compile(r"者，?([^。，；]{2,24}?)(?:也|之谓)|(?:是指|指的是|意为|犹言|训为|释为)([^。，；]{2,24})")


def check_interpretive(c: dict[str, Any], ctx: AuditContext) -> tuple[AuditVerdict, list[dict[str, Any]]]:
    verdict, checks = check_historical(c, ctx) if (QUOTE.search(c["text"]) or WORK.search(c["text"])) else (V.INSUFFICIENT_EVIDENCE, [])
    glossators = [g for g in ctx.glossators if g in c["text"]]
    cited = glossators or WORK.findall(c["text"])
    checks.append(_check("interpretation", bool(cited), "cites " + "、".join(cited) if cited else
                         "an interpretation with no gloss or commentator cited: one reading among others"))
    if verdict == V.UNSUPPORTED:
        return verdict, checks
    if not cited:
        return (V.PARTIALLY_SUPPORTED if verdict == V.SUPPORTED else V.INSUFFICIENT_EVIDENCE), checks
    m = GLOSS.search(c["text"])
    gloss = (m.group(1) or m.group(2)) if m else None
    if glossators and gloss and ctx.locate_by is not None:
        hits = [pid for g in glossators for pid in ctx.locate_by(gloss, g)]
        checks.append(_check("gloss_found", bool(hits), f"「{gloss}」" + (f" in {hits[0]}" if hits else
                             f" not found in the works of {'、'.join(glossators)} in the corpus"), passages=hits[:3]))
        c.setdefault("passages", []).extend(hits[:3])
        if hits:
            return V.SUPPORTED, checks
        return V.PARTIALLY_SUPPORTED, checks
    return (verdict if verdict != V.INSUFFICIENT_EVIDENCE else V.PARTIALLY_SUPPORTED), checks


def check_mapping(c: dict[str, Any], ctx: AuditContext) -> tuple[AuditVerdict, list[dict[str, Any]]]:
    checks = []
    problems = ctx.guard.check(c["text"]) if ctx.guard is not None else []
    for p in problems:
        checks.append(_check("presentism", False, f"{p.kind}: {p.sentence}", suggestion=p.suggestion))
    strong = STRONG.search(c["text"])
    if strong and not problems:
        checks.append(_check("presentism", False, f"「{strong.group(0)}」 asserts more than a resemblance"))
    if any(ch["ok"] is False for ch in checks):
        return V.UNSUPPORTED, checks
    checks.append(_check("presentism", True, "a bounded comparison"))
    if ctx.bridge is None:
        return V.INSUFFICIENT_EVIDENCE, checks
    quoted = QUOTE.findall(c["text"])
    r = ctx.bridge(quoted[0] if quoted else c["text"])
    named = [x for x in r.get("candidates", []) if x["label"].split("（")[0] in c["text"] or x.get("en", "").lower() in c["text"].lower()]
    if not named:
        checks.append(_check("mapping", None, "the bridge scores no profile named in the claim"))
        return V.INSUFFICIENT_EVIDENCE, checks
    best = named[0]
    checks.append(_check("mapping", best["level"] in ("high", "moderate"), f"{best['label']}: level {best['level']}, fit {best['fit']}",
                         level=best["level"]))
    if best.get("conflicts"):
        checks.append(_check("contradiction", False, "the passage denies or contradicts: " +
                             "、".join(x["surface"] for x in best["conflicts"])))
        return V.CONTESTED, checks
    return {"high": V.SUPPORTED, "moderate": V.SUPPORTED, "low": V.PARTIALLY_SUPPORTED}.get(best["level"], V.INSUFFICIENT_EVIDENCE), checks


def check_modern(c: dict[str, Any], ctx: AuditContext) -> tuple[AuditVerdict, list[dict[str, Any]]]:
    level = claim_level(c["text"])
    c["level"] = level.value
    if ctx.modern is None:
        return V.INSUFFICIENT_EVIDENCE, [_check("modern_evidence", None, "no modern evidence consulted", claim_level=level.value)]
    records = ctx.modern(c["text"])
    if not records:
        return V.INSUFFICIENT_EVIDENCE, [_check("modern_evidence", None, "no modern record found", claim_level=level.value)]
    carry, cross = [], []
    for r in records:
        et = EvidenceType(r.get("evidence_type", "unknown"))
        why = cross_level(level, et)
        (cross if why else carry).append({"id": r.get("pmid") or r.get("id"), "type": et.value, **({"why": why} if why else {})})
    checks = [_check("evidence_level", bool(carry), f"{len(carry)} of {len(records)} records can carry a {level.value} claim",
                     carrying=carry[:5], cross_level=cross[:5], claim_level=level.value)]
    if carry:
        strong = any(x["type"] in ("systematic_review", "guideline", "rct") for x in carry)
        return (V.SUPPORTED if strong or level != ClaimLevel.HUMAN_EFFICACY else V.PARTIALLY_SUPPORTED), checks
    checks.append(_check("cross_level", False, "; ".join(sorted({x["why"] for x in cross}))))
    return V.UNSUPPORTED, checks


def check_inference(c: dict[str, Any], ctx: AuditContext) -> tuple[AuditVerdict, list[dict[str, Any]]]:
    if HEDGED_HYPOTHESIS.search(c["text"]):
        return V.INSUFFICIENT_EVIDENCE, [_check("inference", None, "put as a hypothesis to test: not a conclusion", hypothesis=True)]
    return V.UNSUPPORTED, [_check("inference", False, "an inference leap: a historical record does not show modern efficacy "
                                  "(it may motivate a hypothesis to test)")]


def check_clinical(c: dict[str, Any], ctx: AuditContext) -> tuple[AuditVerdict, list[dict[str, Any]]]:
    checks = [_check("clinical", False, "clinical or dosage advice: TaoChronos gives none (research and education only)")]
    return V.UNSUPPORTED, checks


CHECKS: dict[ClaimKind, Callable[[dict[str, Any], AuditContext], tuple[AuditVerdict, list[dict[str, Any]]]]] = {
    K.HISTORICAL: check_historical, K.INTERPRETIVE: check_interpretive, K.MAPPING: check_mapping, K.MODERN: check_modern,
    K.INFERENCE: check_inference, K.CLINICAL: check_clinical,
}
ORDER = [V.UNSUPPORTED, V.CONTESTED, V.INSUFFICIENT_EVIDENCE, V.PARTIALLY_SUPPORTED, V.SUPPORTED]


def overall(verdicts: list[AuditVerdict]) -> AuditVerdict:
    if not verdicts:
        return V.INSUFFICIENT_EVIDENCE
    if V.UNSUPPORTED in verdicts:
        return V.UNSUPPORTED
    if V.CONTESTED in verdicts:
        return V.CONTESTED
    if all(v == V.SUPPORTED for v in verdicts):
        return V.SUPPORTED
    if all(v == V.INSUFFICIENT_EVIDENCE for v in verdicts):
        return V.INSUFFICIENT_EVIDENCE
    return V.PARTIALLY_SUPPORTED


def safety_flags(text: str, ctx: AuditContext) -> list[dict[str, Any]]:
    out = []
    for name, row in ctx.safety.items():
        forms = [name, *row.get("aliases", [])]
        hit = next((f for f in forms if f in text), None)
        if hit:
            out.append({"material": name, "found": hit, "risk": row.get("risk"), "note": row.get("note", "")})
    return out


def audit(text: str, ctx: AuditContext, *, judge: Any = None, audit_id: str = "a1") -> dict[str, Any]:
    claims = decompose(text)
    for c in claims:
        kind = classify(c, ctx)
        verdict, checks = CHECKS[kind](c, ctx)
        c.update({"kind": kind.value, "verdict": verdict.value, "checks": checks, "decided_by": "rule"})
    review = _review(claims, judge) if judge is not None and claims else None
    verdict = overall([V(c["verdict"]) for c in claims])
    return {
        "id": audit_id, "text": text, "verdict": verdict.value, "claims": claims,
        "counts": {v.value: sum(1 for c in claims if c["verdict"] == v.value) for v in V},
        "safety": safety_flags(text, ctx), "review": review,
        "note": ("each atomic claim checked by what it asserts; SUPPORTED means the checks this system can run pass, not "
                 "that the claim is true — and no verdict is clinical advice"),
    }


def _review(claims: list[dict[str, Any]], judge: Any) -> dict[str, Any]:
    """A critic's pass: it may add a concern and lower a verdict, never raise one."""
    allowed = [v.value for v in ORDER]
    schema = {"type": "object", "required": ["reviews"], "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "required": ["id", "verdict"], "properties": {"id": {"type": "string"}, "verdict": {"enum": allowed},
                                                                         "concern": {"type": "string"}}}}}}
    lines = ["逐条审读下列原子论断与规则检查的结论。你可以指出规则未发现的问题并给出更低的结论，但不能给出比规则更高的结论。",
             "不作临床建议；古今病名只可言表型相似。"]
    for c in claims:
        lines.append(f"- {c['id']}（{c['kind']}，规则结论 {c['verdict']}）：{c['text']}；检查：" +
                     "；".join(f"{ch['check']}={ch['ok']}" + (f"（{ch['detail']}）" if ch.get("detail") else "") for ch in c["checks"]))
    lines.append('答 {"reviews": [{"id": "C1", "verdict": "SUPPORTED|PARTIALLY_SUPPORTED|CONTESTED|INSUFFICIENT_EVIDENCE|UNSUPPORTED", "concern": 说明}]}')
    ids = {c["id"] for c in claims}

    def check(d: Any) -> list[str]:
        return [f"unknown id {r.get('id')!r}" for r in d.get("reviews", []) if r.get("id") not in ids]

    res = judge.ask("audit.review", "你是证据审计的批评者：严格、只减不增。", "\n".join(lines), schema=schema, check=check)
    if not res.ok:
        return {"ok": False, "error": res.error}
    lowered = 0
    by_id = {c["id"]: c for c in claims}
    for r in res.data.get("reviews", []):
        c = by_id[r["id"]]
        if r.get("concern"):
            c.setdefault("concerns", []).append(str(r["concern"])[:300])
        if ORDER.index(V(r["verdict"])) < ORDER.index(V(c["verdict"])):
            c["verdict"], c["decided_by"] = r["verdict"], "model"
            lowered += 1
        elif r["verdict"] == c["verdict"]:
            c["decided_by"] = "both"
    return {"ok": True, "lowered": lowered, "judge": getattr(judge, "label", None)}


__all__ = ["AuditContext", "CHECKS", "audit", "claim_level", "classify", "decompose", "overall", "safety_flags"]
