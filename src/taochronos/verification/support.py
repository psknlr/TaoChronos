"""Claim–evidence support: do the quoted words bear the claim?

A true quote can carry a false claim.  「太阳病，头痛，发热，汗出，恶风，桂枝汤主之」 is verbatim in 《伤寒论》; filed as a
*contraindication* of 桂枝汤 it is a real quote with a false relation, and a verbatim check cannot see it.  This module
is the second reading, independent of whoever extracted the claim (rules or a model): it reads the quote for the
words that state each relation and returns one of

``supports``      the quote states the relation (its cue governs the claim's arguments);
``contradicts``   the quote states the opposite (a contraindication where an indication is claimed, or the reverse);
``insufficient``  nothing in the quote states the relation — the claim may be an inference, not an assertion;
``ambiguous``     the quote states both, and which governs the claim's arguments is not decidable by rule;

and, for every relation, the arguments must be read with their negation: 「非风、非寒、非暑、非湿，乃……异气所感」 does not
support "风 causes 温疫" — the claim asserts what the quote denies (``contradicts``), as does a claim that negates what
the quote asserts;

with the cue spans, and the **frame** of the statement: who says it (the author, a quoted book or person, 或曰),
whether the author endorses it or rejects it (「某家以为……然余不取」), its conditions (若…者, 凡…), negations and their
targets, its modality (不可, 未可, 非必, 若…则…) and its time or stage (五六日, 初起, 久病, 产后).

A model's confidence never replaces this reading; a model may be asked to adjudicate an ``ambiguous`` reading, never to
overrule a ``contradicts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..protocol.base import Model
from ..protocol.claims import Claim, ClaimRelation, Role

VERDICTS = ("supports", "contradicts", "insufficient", "ambiguous")
INTERVENTION_ROLES = (Role.FORMULA, Role.HERB, Role.TREATMENT_METHOD)
SENTENCE = re.compile(r"[^。；！？!?;]+[。；！？!?;]?")

# an indication: a cue right after the intervention (桂枝汤主之, 地黄丸：治…) or right before it (宜桂枝汤, 可与…, 与…汤)
IND_AFTER = re.compile(r"^[，,：:、]?(?:此方|本方|是方|此药)?(?:汤|散|丸|方|饮|膏)?(?:亦|复|仍|并|专|能|善)?"
                       r"(?:主之|主治|治之|主|治|疗|为主|良|佳|亦佳|最良|神效|甚效|立效|服之|解|除|消|化|通|止)")
IND_BEFORE = re.compile(r"(?:宜|可与|宜与|宜服|可服|宜用|可用|当以|当与|先与|更与|复与|乃与|却与|与服|投以|投|予|以|与|服|用|属)$")
IND_PRONOUN = re.compile(r"(?:主之|宜(?:与|服)之|可(?:与|服)之|(?:尽|顿|温|分|再|更)?服之|饮之)")
# a contraindication: a prohibition before the intervention (不可与桂枝汤, 不可更行…, 勿服…), a misuse (辄用麻黄, 妄投…),
# a prohibition after it or by pronoun (…不可与之), or a warning of what it causes (若下之，必…)
CONTRA_BEFORE = re.compile(r"(?:不可(?:再|更|复)?(?:与|服|用|以|行|投|予)?|不宜(?:与|服|用)?|不得(?:与|服|用)?|勿(?:与|服|用|再服|妄)?|禁(?:用|服|与)?|"
                           r"忌(?:用|服)?|慎(?:勿|不可)(?:与|服|用)?|不中与|非其所宜|无与|(?:辄|妄|误|滥|骤|遽|轻)(?:用|投|与|服|施|行))$")
CONTRA_AFTER = re.compile(r"^[，,]?(?:汤|散|丸|方)?[^。；]{0,4}?(?:不可与|不可服|不中与|禁用|慎用|忌服|忌用|不可用)")
CONTRA_PRONOUN = re.compile(r"(?:不可(?:与|服|用)之|勿(?:与|服)之|不中与之|不可与也|不可服也|禁(?:与|服)之|不宜(?:与|服|用)之)")
CONTRA_SELF = re.compile(r"^(?:不可|不宜|不得|勿|禁|忌|慎勿|莫)")  # the negation inside the argument (「不可下也」)
ADVERSE = re.compile(r"(?:若|误|妄|反|更|复)$")  # 若下之，必胸下结鞕: what the intervention causes
ADVERSE_AFTER = re.compile(r"^[之者]?[，,]?(?:则|必|即|便|遂|反)")
# a cue belongs to its own clause: 「大便微硬者，可与大承气汤，不硬者，不可与之」 — the prohibition governs the next
# 者-clause, not the formula before it
NEXT_CONDITION = re.compile(r"[，,；;][^，,。；;]{1,10}者[，,]")
# 「汗之则神昏」「下之则洞泄」 warn; 「汗之则愈」 recommends: the consequence decides
CONSEQUENCE = re.compile(r"^[之者]?[，,]?(?:则|必|即|便|遂|而)")
GOOD_OUTCOME = re.compile(r"^[之者]?[，,]?(?:则|必|即|便|遂|而)[^。；，]{0,3}?(?:愈|解|安|瘥|已|自止|和|平|汗出而解)")
BAD_OUTCOME = re.compile(r"^[之者]?[，,]?(?:则|必|即|便|遂|而)[^。；，]{0,4}?(?:死|昏|泄|利不止|结|厥|逆|谵|衄|痉|烦|亡阳|不止|躁|喘|益甚|更甚|加剧|"
                         r"不治|危|殆|发黄|惊|狂|耳聋|目瞑|动血|咽燥|吐|伤|虚)")

RELATION_CUES: dict[ClaimRelation, re.Pattern[str]] = {
    ClaimRelation.DEFINES: re.compile(r"之为病|名曰|名为|此名|谓之|是为|此为|名之曰|是名|号为|者[^。；]{0,24}也|者为|为[^。；，]{1,6}"),
    ClaimRelation.CAUSES: re.compile(r"因于|所致|所感|伤于|由于|得之|所发|客于|中于|感于|因|由|杂至|合而|犯|善病|易病|多病|令人|使人|致|未有不|"
                                     r"故[^。；]{0,10}(?:作|发|病|生)"),
    ClaimRelation.PATHOGENESIS: re.compile(r"皆属于|属于|所生|病机|所以然者|以其|化为|胜者|故|是以|乃[^。；]{0,6}所|之变|生|则|为"),
    ClaimRelation.TREATMENT_PRINCIPLE: re.compile(
        r"(?:寒|热|温|清|虚|实|燥|湿|结|留|散|急|缓|衰|盛|劳|逸|坚|客|损|惊|高|下|微|甚)者[^。；，]{1,2}之|治(?:宜|以|当|法)|法(?:当|宜)|"
        r"当(?:以|先|急|须)?(?:汗|下|吐|温|清|和|补|泻|散|消|利|攻|发汗|实)|宜(?:汗|下|吐|温|清|和|补|泻|散|消|利|攻)|可(?:汗|下|吐|温|攻)|"
        r"治未病|先实|当先|治[^。；，]{0,6}(?:必|当|宜|先)"),
    ClaimRelation.COMPOSED_OF: re.compile(r"[右上][一二三四五六七八九十]+味|各[一二三四五六七八九十半]+(?:两|钱|分|铢|枚)|"
                                          r"[一二三四五六七八九十百半]+(?:两|钱|分|铢|枚|升|合|斤)|为末|等分|方[：:]|右件|上件|[右上]为"),
    ClaimRelation.HERB_INDICATION: re.compile(r"味[甘苦辛酸咸淡涩]|[性气][寒热温凉平]|主[^之。；]|治|疗|为要药|功用|除|解|消|散"),
    ClaimRelation.TRANSFORMS_TO: re.compile(r"转为|传为|变为|转属|转成|变成|发为|成为|遂成|乃成|久则|久而|传入|化为|转入|致成|恐成|将为"),
    ClaimRelation.COMPLICATION: re.compile(r"必发|续发|并发|兼见|变生|发(?:痈|疽|黄|斑|狂|热|痉|衄|渴|疮)|致[^。；]{0,4}(?:痈|疽|疮)"),
    ClaimRelation.PROGNOSIS: re.compile(r"必愈|自愈|欲愈|欲解|可治|难治|不治|不可治|死|愈|易治|为逆|为顺|不死|可生|难已|自止|自已|自解"
                                        r"|(?:难|自|则|必|乃|即|当|者)(?:差|瘥)|瘥"),
}

# the frame of a statement
QUOTED = re.compile(r"(?P<src>《[^》]{1,20}》|经|论|书|方书|古人|前人|先贤|昔人|世医|俗医|俗|时医|或|有|诸家|旧说|[一-鿿]{1,4}(?:氏|子|公|先生))"
                    r"(?:所)?(?:曰|云|言|谓|以为|认为|称|说|论曰|论云)")
CITED_BOOK = re.compile(r"(?P<src>《[^》]{1,20}》)(?:论|曰|云|言|谓|称|说)?[：:]")
# the author's answer to a reported view or a question: 余曰 / 答曰 / 许曰非也 / 曰不然 / 是又不然 — what follows is not the report
ANSWER = re.compile(r"(?:余|予|吾|愚)(?:曰|谓|按)|[答荅对]曰|[一-鿿]{1,3}曰[：:]?(?:非也|不然|否)|曰[：:]?(?:非也|不然|是大不然|否)|"
                    r"是(?:又|大)?不然|(?:[一-鿿]{1,2})?按[：:]")
REJECTS = re.compile(r"然余不取|余不取|不可从|非也|误矣|谬矣|谬也|不足信|未可信|不然|殊不知|岂知|恐非|未必然|非是|此说非|其说非|大谬|失之|不足据|断不可从|余未敢信")
HEDGES = re.compile(r"或(?!曰|云|谓)|恐|疑|似|盖|大抵|未必|未可|或者|抑或|殆|庶几")
CONDITION = re.compile(r"(?:若|如|倘|凡|假令|设|其人|病人|病者)[^。；，]{0,24}(?:者|时|则|，)")
ZHE_CONDITION = re.compile(r"[^。；：，]{1,24}者(?=[，,])")
CONSEQUENT = re.compile(r"主之|宜|可(?:与|下|汗|吐|服|温|攻)|不可|当|则|必|死|愈|治|与|服|善病|易病|多病|难已")
NEGATORS = re.compile(r"不可|不能|不宜|不得|未可|非必|勿|莫|无|不|未|非")
STAGE = re.compile(r"[一二三四五六七八九十百]+日|初起|初得|初病|初发|久病|日久|新病|病后|产后|病愈后|愈后|瘥后|将愈|未愈|春|夏|秋|冬|四时|平旦|日晡|夜半|"
                   r"始得之|得之[一二三四五六七八九十]+日")
# an argument the quote negates: a negator right before it in its clause (非风, 不恶寒), not a double negation (未有不成消渴)
ARG_NEGATORS = ("不能", "不甚", "反不", "不", "无", "非", "未", "勿", "莫")
DOUBLE_NEGATION = ("未有不", "无非", "莫不", "无不")
CLINICAL = re.compile(r"诊|复诊|二诊|三诊|投以|服后|服[一二三四五六七八九十]+剂|案|病者|患者|一人|某|治[^。]{0,4}(?:一|某)")


@dataclass(kw_only=True)
class SupportAssessment(Model):
    verdict: str  # supports | contradicts | insufficient | ambiguous
    relation: str
    cues: list[dict] = field(default_factory=list)  # [{cue, start, end, reads: relation}]
    explanation: str = ""
    frame: dict = field(default_factory=dict)


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    for m in SENTENCE.finditer(text):
        if m.start() <= pos < m.end():
            return m.start(), m.end()
    return 0, len(text)


def _cue(kind: str, m: re.Match[str], offset: int, reads: str) -> dict[str, Any]:
    return {"cue": m.group(0), "start": offset + m.start(), "end": offset + m.end(), "reads": reads, "kind": kind}


def _pronoun_warning(norm: str, lo: int, hi: int) -> str | None:
    """「服之则厥逆」「与之必呕」: a warning of what taking the intervention named by 之 brings."""
    for m in re.finditer(r"(?:服|与|饮|用|得)之", norm[lo:hi]):
        at = lo + m.end() - 1
        if BAD_OUTCOME.search(norm[at: at + 14]):
            return norm[lo + m.start(): min(hi, at + 6)]
    return None


def _intervention_reading(norm: str, start: int, end: int, lo: int, hi: int) -> tuple[str | None, list[dict[str, Any]]]:
    """How the text governs one intervention argument at [start, end): 'indicated', 'contraindicated', 'both' or None.
    The cue nearest the intervention governs it (「不可发汗，宜桂枝汤」: 宜 governs 桂枝汤, 不可 governs 发汗); a cue inside
    a longer one does not count on its own (the 与 of 不可与)."""
    s_lo, s_hi = _sentence_bounds(norm, start)
    b0 = max(s_lo, start - 8)
    before, after = norm[b0: start], norm[end: min(max(s_hi, hi), end + 12)]
    nxt = NEXT_CONDITION.search(after)
    if nxt:
        after = after[: nxt.start()]
    cues: list[dict[str, Any]] = []

    def add(kind: str, m: re.Match[str] | None, offset: int, reads: str, distance: int) -> None:
        if m:
            cue = _cue(kind, m, offset, reads)
            cue["distance"] = distance
            cues.append(cue)

    m = CONTRA_SELF.search(norm[start:end])
    add("self", m, start, "contraindicated", 0)
    m = CONTRA_BEFORE.search(before)
    add("before", m, b0, "contraindicated", start - (b0 + m.end()) if m else 0)
    m = CONTRA_AFTER.search(after)
    add("after", m, end, "contraindicated", m.start() if m else 0)
    if ADVERSE.search(before) and ADVERSE_AFTER.search(after):
        add("warning", ADVERSE.search(before), b0, "contraindicated", 0)
    tail = norm[end - 1: end + 12] if norm[end - 1: end] == "之" else after  # 「汗之」: the consequence follows the 之
    nxt = NEXT_CONDITION.search(tail)
    if nxt:
        tail = tail[: nxt.start()]
    add("warning", BAD_OUTCOME.search(tail), end, "contraindicated", 0)
    add("outcome", GOOD_OUTCOME.search(tail), end, "indicated", 0)
    # a pronoun cue refers back only within the claim's own quote (a later 「…汤主之」 belongs to that formula)
    for m in CONTRA_PRONOUN.finditer(norm, end, hi):
        add("pronoun", m, 0, "contraindicated", m.start() - end)
    m = IND_AFTER.search(after)
    add("after", m, end, "indicated", m.start() if m else 0)
    m = IND_BEFORE.search(before)
    add("before", m, b0, "indicated", start - (b0 + m.end()) if m else 0)
    for m in IND_PRONOUN.finditer(norm, end, hi):
        add("pronoun", m, 0, "indicated", m.start() - end)
    # a cue that lies inside a longer cue of the other reading is part of it (不可与 contains 与)
    cues = [c for c in cues if not any(o is not c and o["reads"] != c["reads"] and o["start"] <= c["start"] and c["end"] <= o["end"]
                                       and (o["end"] - o["start"]) > (c["end"] - c["start"]) for o in cues)]
    if not cues:
        return None, cues
    nearest = min(c["distance"] for c in cues)
    reads = {c["reads"] for c in cues if c["distance"] <= nearest + 1}
    return ("both" if len(reads) > 1 else reads.pop()), cues


def statement_frame(text: str, start: int, end: int, normalize: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Who states the words at [start, end), with what stance, under which conditions, negations and time."""
    norm = normalize(text) if normalize else text
    s_lo, _ = _sentence_bounds(norm, start)
    _, s_hi = _sentence_bounds(norm, max(start, end - 1))
    # a view reported earlier in the passage (或曰……) governs until the author answers it
    head = norm[max(0, s_lo - 60): s_lo] + norm[s_lo: end]
    frame: dict[str, Any] = {"speaker": "author", "quoted_from": "", "stance": "asserted", "modality": "assertive",
                             "conditions": [], "negation_scope": [], "temporal_scope": [], "context": "textual"}
    offset = max(0, s_lo - 60)
    quoted = sorted([*QUOTED.finditer(head), *CITED_BOOK.finditer(head)], key=lambda m: m.start())
    if quoted:
        q = quoted[-1]
        # a report governs until the author answers it: the words after 余曰 / 答曰 / 曰不然 are the author's own
        answered = ANSWER.search(head, q.end(), max(q.end(), start - offset))
        if not answered:
            src = q.group("src").strip("《》")
            frame["quoted_from"] = src
            frame["speaker"] = {"或": "unnamed other (或曰)", "有": "unnamed other"}.get(src, src)
            frame["stance"] = "reported"
    tail = norm[end: min(len(norm), s_hi + 40)]
    # a rejection after the words (「……然余不取」「……是又不然」) rejects them, unless an answer of the author's lies between
    # (the words are then that answer: 「或曰……余曰非也，邪气客于下焦」)
    rejection = REJECTS.search(tail) or REJECTS.search(norm[start:end])
    if rejection and not (frame["stance"] == "asserted" and quoted and ANSWER.search(head, quoted[-1].end(), max(quoted[-1].end(), start - offset))):
        frame["stance"] = "rejected" if frame["stance"] == "reported" or REJECTS.search(tail) else frame["stance"]
    span = norm[s_lo: s_hi]
    for m in CONDITION.finditer(span):
        if s_lo + m.start() <= end:
            frame["conditions"].append(m.group(0).rstrip("，"))
    # 「……大便难而谵语者，下之则愈」: the clause closed by 者 conditions what the sentence says next — not in a definition
    # (「夫消渴者，渴不止，小便多是也」), where no action or consequence follows
    for m in ZHE_CONDITION.finditer(span):
        after = span[m.end(): max(m.end(), end - s_lo) + 8]
        if s_lo + m.start() < end and CONSEQUENT.search(after) and not any(m.group(0) in c or c in m.group(0) for c in frame["conditions"]):
            frame["conditions"].append(m.group(0))
    if frame["conditions"]:
        frame["modality"] = "conditional"
    if HEDGES.search(norm[max(s_lo, start - 6): end]) and frame["modality"] == "assertive":
        frame["modality"] = "hedged"
    for m in NEGATORS.finditer(norm, start, end):
        target = norm[m.end(): m.end() + 4]
        frame["negation_scope"].append({"negator": m.group(0), "at": m.start(), "target": target})
    frame["temporal_scope"] = sorted({m.group(0) for m in STAGE.finditer(span)})
    if CLINICAL.search(norm[max(0, s_lo - 40): s_hi]):
        frame["context"] = "clinical"
    return frame


def negated_in_text(norm: str, start: int, surface: str) -> bool:
    """Whether the text negates the term at ``start``: 「非风」「不恶寒」 yes; 「无汗」 (the negation is the term) and
    「未有不成消渴」 (a double negation) no."""
    if surface.startswith(("不", "无", "非", "未")):
        return False
    clause_start = max(norm.rfind(c, 0, start) for c in "，、。；：,;") + 1
    prefix = norm[max(clause_start, start - 3): start]
    return not prefix.endswith(DOUBLE_NEGATION) and prefix.endswith(ARG_NEGATORS)


def negation_disagreements(claim: Claim, norm: str) -> list[dict[str, Any]]:
    """Arguments whose negation in the claim differs from their negation in the quote.  An intervention of an
    indication or a contraindication is left to the cue reading (「不可与桂枝汤」 prohibits it, it does not negate it);
    claims read through machine segmentation are left out (the source has no clause marks to bound a negator)."""
    if "machine-segmented" in claim.tags:
        return []
    out = []
    for a in claim.arguments:
        if a.start is None or a.end is None or not (0 <= a.start < len(norm)):
            continue
        if a.role in INTERVENTION_ROLES and claim.relation in (ClaimRelation.INDICATED_FOR, ClaimRelation.CONTRAINDICATED):
            continue
        in_text = negated_in_text(norm, a.start, a.surface or norm[a.start:a.end])
        if in_text != bool(a.negated):
            out.append({"cue": a.surface, "start": a.start, "end": a.end, "kind": "negation",
                        "reads": "denied" if in_text else "asserted", "claimed": "negated" if a.negated else "asserted"})
    return out


def assess_support(claim: Claim, text: str, normalize: Callable[[str], str] | None = None, cruxes: Any = None) -> SupportAssessment:
    """Read the claim's quote in its passage for the words that state the claim's relation — and, given a registry of
    textual cruxes, whether the words it rests on are words the commentators doubt: a claim the literal wording would
    support, on a clause judged transposed, miswritten, interpolated or lacunose, is *ambiguous* (the reading waits for
    an expert), never *supported*."""
    reading = _assess(claim, text, normalize)
    if cruxes is None or reading.verdict != "supports":
        return reading
    norm = normalize(text) if normalize else text
    spans = [(a.start, a.end) for a in claim.arguments if a.start is not None and a.end is not None]
    hits = cruxes.overlapping(norm, max(0, claim.start), min(len(norm), claim.end), spans)
    if not hits:
        return reading
    who = "、".join(dict.fromkeys(p for h in hits for p in h["by"] if p))[:60] or "注家"
    words = next((h["target"] for h in hits if h.get("target")), None)
    kinds = "/".join(dict.fromkeys(k for h in hits for k in h["kinds"]))
    cues = reading.cues + [{"cue": words or "(全条)", "kind": "crux", "reads": kinds, "crux": h["id"], "by": h["by"]} for h in hits]
    return SupportAssessment(verdict="ambiguous", relation=reading.relation, cues=cues, frame=reading.frame,
                             explanation=f"the literal wording would support it, but {who} doubt "
                                         f"{'「' + words + '」' if words else 'this clause'} ({kinds}): a textual crux")


def _assess(claim: Claim, text: str, normalize: Callable[[str], str] | None = None) -> SupportAssessment:
    norm = normalize(text) if normalize else text
    lo, hi = max(0, claim.start), min(len(norm), claim.end)
    relation = claim.relation
    frame = statement_frame(text, lo, hi, normalize)

    def result(verdict: str, cues: list[dict[str, Any]], why: str) -> SupportAssessment:
        return SupportAssessment(verdict=verdict, relation=relation.value, cues=cues, explanation=why, frame=frame)

    disagree = negation_disagreements(claim, norm)
    if disagree:
        names = "、".join(f"{d['cue']}（{'原文否定' if d['reads'] == 'denied' else '原文肯定'}）" for d in disagree[:4])
        return result("contradicts", disagree, f"the claim reads the negation of its arguments against the quote: {names}")

    if relation in (ClaimRelation.INDICATED_FOR, ClaimRelation.CONTRAINDICATED):
        want = "indicated" if relation == ClaimRelation.INDICATED_FOR else "contraindicated"
        interventions = [a for a in claim.arguments if a.role in INTERVENTION_ROLES and a.start is not None and a.end is not None]
        if not interventions:
            referents = [a for a in claim.arguments if a.role in INTERVENTION_ROLES and a.qualifiers.get("referent")]
            m = CONTRA_BEFORE.search(norm[lo:hi]) or CONTRA_PRONOUN.search(norm, lo, hi) or re.search(r"忌|禁|勿|不可", norm[lo:hi])
            warning = _pronoun_warning(norm, lo, hi)
            prescribed = [x for x in IND_PRONOUN.finditer(norm, lo, hi) if not BAD_OUTCOME.search(norm[x.end() - 1: x.end() + 12])
                          and not CONTRA_PRONOUN.search(norm, max(lo, x.start() - 3), x.end())]
            forbids = m or warning
            if relation == ClaimRelation.CONTRAINDICATED:
                # a contraindication may concern a behaviour or food (忌生冷): a prohibition or a warning in the quote states it
                if forbids:
                    cue = m.group(0) if m else warning
                    return result("supports", [{"cue": cue, "reads": "contraindicated"}], "a prohibition or a warning in the quote")
                if referents and prescribed:
                    return result("contradicts", [{"cue": prescribed[0].group(0), "reads": "indicated"}],
                                  f"the quote prescribes what 之 refers to ({prescribed[0].group(0)})")
                return result("insufficient", [], "no word in the quote prohibits the intervention")
            if referents:
                # an indication of what 之 refers to: 「宜服之」 prescribes it, 「不可与之」「服之则厥逆」 forbid it
                if forbids and prescribed:
                    return result("ambiguous", [], "the quote both prescribes and forbids what 之 refers to")
                if forbids:
                    cue = m.group(0) if m else warning
                    return result("contradicts", [{"cue": cue, "reads": "contraindicated"}], f"the quote forbids what 之 refers to ({cue})")
                if prescribed:
                    return result("supports", [{"cue": prescribed[0].group(0), "reads": "indicated"}], "the quote prescribes what 之 refers to")
            return result("insufficient", [], "no intervention argument whose indication the quote could state")
        readings, cues = [], []
        for arg in interventions:
            reading, found = _intervention_reading(norm, arg.start, arg.end, lo, hi)
            readings.append(reading)
            cues += found
        if all(r == want for r in readings):
            return result("supports", cues, f"the quote states the {relation.value} relation for every intervention")
        opposite = "contraindicated" if want == "indicated" else "indicated"
        if any(r == opposite for r in readings) and not any(r in (want, "both") for r in readings):
            names = "、".join(a.surface for a, r in zip(interventions, readings) if r == opposite)
            return result("contradicts", cues, f"the quote states the opposite: {names} is {opposite} here, not {want}")
        if any(r in ("both", opposite) for r in readings):
            return result("ambiguous", cues, "the quote states both an indication and a prohibition near the intervention")
        if any(r == want for r in readings):
            return result("supports", cues, f"the quote states the {relation.value} relation for part of the interventions")
        return result("insufficient", cues, f"no word in the quote states that the intervention is {want}")

    if relation == ClaimRelation.THEORY:
        return result("supports", [], "a general assertion: no relation cue is required, the quote is its own statement")
    pattern = RELATION_CUES.get(relation)
    hits = [_cue("in-quote", m, lo, relation.value) for m in pattern.finditer(norm[lo:hi])] if pattern else []
    if hits:
        return result("supports", hits, f"the quote states the {relation.value} relation ({hits[0]['cue']})")
    return result("insufficient", [], f"no word in the quote states a {relation.value} relation")


def support_layers(claim: Claim, text: str, normalize: Callable[[str], str] | None = None, cruxes: Any = None) -> dict[str, Any]:
    """The G4 layers that concern meaning: semantic support and the statement's scope."""
    a = assess_support(claim, text, normalize, cruxes)
    return {"support": a.verdict, "support_explanation": a.explanation, "cues": [c.get("cue") for c in a.cues][:6],
            "scope": {k: a.frame.get(k) for k in ("speaker", "quoted_from", "stance", "modality", "conditions", "temporal_scope")}}
