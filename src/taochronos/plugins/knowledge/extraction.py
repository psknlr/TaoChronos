"""Claim extraction — the deterministic "small model" layer.

Lexicon matching (longest-first, on variant-normalised text) plus classical-Chinese
pattern rules turn a passage into hyperedge Claims.  Every claim carries a
verbatim quote and character span, so Gate G4 can verify it against the text.
An LLM may *add* claims later (semantic verification), but it must pass the same
provenance check.

Rules (see docs/discovery.md for examples):
  COMP   formula composition with doses / processing           → composed_of
  HERB   本草 “X，味…，性…。主…”                                 → herb_indication
  META   “昔人称其…为要药 / 后世称其…”                            → herb_indication (period-marked)
  IND    “…X主之 / 宜X / 可与X / X：治… / 此方治… / 治之以X”        → indicated_for
  CONTRA “不可服之 / 不可更行X / 不可与 / 不可下 / 辄用X / 忌 / 所慎” → contraindicated
  ADV    “汗之则… / 下之则…” (adverse outcome of a method)         → contraindicated
  DEF    “X之为病… / …名为X / 此名X / …者为X / X者，…”             → defines
  CAUSE  “冬伤于寒，春必温病 / 因于X / …所感 / 未有不成X / 善病X / 由…” → causes
  PATHO  “诸X，皆属于Y / …所生 / 乃生X / …是其本源 / 则实 / 则虚”   → pathogenesis
  TREAT  “X者Y之 / 当以…和之 / 温能除大热 / 在卫汗之…”             → treatment_principle
  COMPL  “消渴之人…发痈疽”                                      → complication
  TRANS  “转为X”                                               → transforms_to
  THEORY fallback for dense theoretical sentences               → theory
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from ...protocol.base import stable_id
from ...protocol.claims import Claim, ClaimArgument, ClaimRelation, ExtractionInfo, Role
from ...protocol.confidence import ConfidenceVector
from ...protocol.documents import Passage
from ...protocol.outputs import PhilologyAssessment
from ..classics.domain import PULSE_QUALITIES, DomainPack, LexEntry, Mention

EXTRACTOR_VERSION = "lexicon-rules@0.1"
SENT_END = "。；！？"
NEG_PREFIXES = ("不能", "不甚", "反不", "不", "无", "非", "未", "勿", "莫")
NUM = "[一二三四五六七八九十百千半]+"
UNIT = "(?:两|钱|分|铢|斤|升|合|枚|个|握|片)"
DOSE_RE = re.compile(rf"(?:以上)?(?:各)?(?:{NUM}{UNIT}(?:{NUM}{UNIT}|半)*(?:或{NUM}{UNIT})?|等分)")
PULSE_RE = re.compile(rf"(寸口脉|脉|关上|尺中)(阴阳俱|反)?([{PULSE_QUALITIES}而]{{1,8}})")
PAREN_RE = re.compile(r"（[^）]*）")

RULE_CONFIDENCE = {
    "COMP": 0.85, "HERB": 0.85, "META": 0.75, "IND": 0.85, "IND-advisory": 0.8, "IND-hedged": 0.75,
    "IND-heading": 0.6, "IND-zhi": 0.8, "CONTRA": 0.75, "ADV": 0.7, "DEF": 0.82, "DEF-generic": 0.65,
    "CAUSE": 0.78, "CAUSE-season": 0.82, "PATHO": 0.8, "PATHO-generic": 0.62, "TREAT": 0.82,
    "TREAT-generic": 0.62, "COMPL": 0.72, "TRANS": 0.75, "THEORY": 0.5,
}
TEXTUAL_BY_MODALITY = {"assertive": 0.9, "advisory": 0.82, "hedged": 0.68, "conditional": 0.72}
ATTRIBUTION_TEMPORAL = {"traditional": 0.9, "compiled": 0.78, "disputed": 0.62, "pseudepigraphic": 0.62}
FINDING_CATEGORIES = ("symptom", "sign", "tongue", "pulse")
CONDITION_CATEGORIES = ("disease", "pattern")
CAUSAL_MARKERS = ("伤于", "因于", "属于", "所生", "所感", "杂至", "合而", "胜者", "化为", "客于", "成痹", "所发", "犯")


@dataclass
class _Sentence:
    start: int
    end: int  # exclusive, excluding the terminator
    text: str


@dataclass
class _Ctx:
    passage: Passage
    norm: str
    mentions: list[Mention]
    sentences: list[_Sentence]
    paren_spans: list[tuple[int, int]]
    heading: list[Mention]
    claims: list[Claim] = field(default_factory=list)
    covered: list[tuple[int, int]] = field(default_factory=list)
    passage_prep: tuple | None = None  # (herb mention, dose, preparation) of a bare single-herb prescription
    contra_spans: list[tuple[int, int]] = field(default_factory=list)  # anchor spans of 不可… clauses

    def in_paren(self, pos: int) -> bool:
        return any(s <= pos < e for s, e in self.paren_spans)

    def sentence_of(self, pos: int) -> _Sentence:
        for s in self.sentences:
            if s.start <= pos <= s.end:
                return s
        return self.sentences[-1]

    def mentions_in(self, start: int, end: int, *categories: str, include_weak: bool = False) -> list[Mention]:
        return [
            m for m in self.mentions
            if start <= m.start and m.end <= end and not self.in_paren(m.start)
            and (not categories or m.category in categories)
            and (include_weak or not m.weak)
        ]


class ClaimExtractor:
    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack
        self.lex = pack.lexicon

    # ================================================================== API
    def extract(self, passage: Passage, assessment: PhilologyAssessment | None = None) -> list[Claim]:
        ctx = self._context(passage)
        if passage.kind == "materia_medica":
            self._rule_herb(ctx)
        self._rule_meta(ctx)
        self._rule_composition(ctx)
        self._rule_define(ctx)
        self._rule_contra(ctx)
        self._rule_indicated(ctx)
        self._rule_cause(ctx)
        self._rule_pathogenesis(ctx)
        self._rule_treatment(ctx)
        self._rule_complication_transform(ctx)
        self._rule_heading_indication(ctx)
        self._rule_theory(ctx)
        claims = self._dedupe(ctx.claims)
        for claim in claims:
            claim.confidence = self._confidence(claim, passage, assessment)
        return claims

    def extract_many(self, passages: Iterable[Passage], assessments: dict[str, PhilologyAssessment] | None = None) -> list[Claim]:
        out: list[Claim] = []
        for p in passages:
            out.extend(self.extract(p, (assessments or {}).get(p.id)))
        return out

    # ============================================================ context
    def _context(self, passage: Passage) -> _Ctx:
        norm = self.pack.variants.normalize_text(passage.text)
        mentions = self.lex.match(norm)
        pulses, pulse_spans = self._pulses(norm)
        if pulses:
            mentions = [m for m in mentions if not any(s <= m.start < e for s, e in pulse_spans)] + pulses
            mentions.sort(key=lambda m: m.start)
        sentences: list[_Sentence] = []
        start = 0
        for i, ch in enumerate(norm):
            if ch in SENT_END or norm.startswith("……", i):
                if i > start:
                    sentences.append(_Sentence(start, i, norm[start:i]))
                start = i + (2 if norm.startswith("……", i) else 1)
        if start < len(norm):
            sentences.append(_Sentence(start, len(norm), norm[start:]))
        if not sentences:
            sentences = [_Sentence(0, len(norm), norm)]
        parens = [(m.start(), m.end()) for m in PAREN_RE.finditer(norm)]
        heading_text = self.pack.variants.normalize_text(
            " ".join(x for x in (passage.locator.chapter, passage.locator.section) if x)
        )
        heading = [m for m in self.lex.match(heading_text) if m.category in ("disease", "pattern", "etiology", "formula") and not m.weak]
        return _Ctx(passage, norm, mentions, sentences, parens, heading)

    def _pulses(self, norm: str) -> tuple[list[Mention], list[tuple[int, int]]]:
        out = []
        spans = []
        for m in PULSE_RE.finditer(norm):
            spans.append((m.start(), m.end()))
            qualities = m.group(3)
            base = m.start(3)
            for i, q in enumerate(qualities):
                if q == "而":
                    continue
                entry = self.lex.entry(f"pulse:{q}")
                if entry is not None:
                    # surface is the character actually present in the text (provenance must be verbatim)
                    out.append(Mention(entry, q, base + i, base + i + 1))
        return out, spans

    # ============================================================ helpers
    def _negated(self, ctx: _Ctx, m: Mention) -> bool:
        if m.surface.startswith(("不", "无", "非", "未")):
            return False
        clause_start = max(ctx.norm.rfind(c, 0, m.start) for c in "，、。；：") + 1
        prefix = ctx.norm[max(clause_start, m.start - 3): m.start]
        if prefix.endswith(("未有不", "无非", "莫不", "无不")):
            return False  # double negation: 未有不成消渴 = always becomes 消渴; 无非 = nothing but
        return prefix.endswith(NEG_PREFIXES)

    def _optional(self, ctx: _Ctx, m: Mention) -> bool:
        clause_start = max(ctx.norm.rfind(c, 0, m.start) for c in "，。；") + 1
        return ctx.norm[clause_start: m.start].startswith("或")

    def _arg(self, ctx: _Ctx, m: Mention, *, role: Role | None = None, **qualifiers: str) -> ClaimArgument:
        q = {k: v for k, v in qualifiers.items() if v}
        if m.synonym_kind:
            q["synonym_kind"] = m.synonym_kind
        if m.weak:
            q["weak"] = "true"
        if self._optional(ctx, m):
            q["optional"] = "或"
        return ClaimArgument(
            role=role or Role(self.pack.role_of(m.category)),
            surface=m.surface,
            term_id=m.term_id,
            start=m.start,
            end=m.end,
            negated=self._negated(ctx, m),
            qualifiers=q,
        )

    def _heading_arg(self, m: Mention) -> ClaimArgument:
        return ClaimArgument(
            role=Role(self.pack.role_of(m.category)), surface=m.surface, term_id=m.term_id, qualifiers={"from_heading": "true"}
        )

    def _new(self, ctx: _Ctx, relation: ClaimRelation, args: list[ClaimArgument], start: int, end: int, rule: str,
             *, modality: str = "assertive", polarity: str = "affirm", context: str = "") -> Claim | None:
        unique: list[ClaimArgument] = []
        seen_keys: set[tuple] = set()
        for a in args:
            if a is None:
                continue
            key = (a.role, a.key, a.negated, a.qualifiers.get("optional"), a.qualifiers.get("outcome"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique.append(a)
        args = unique
        if len(args) < 2 and relation not in (ClaimRelation.THEORY,):
            return None
        spans = [(a.start, a.end) for a in args if a.start is not None]
        if spans:
            start = min(start, min(s for s, _ in spans))
            end = max(end, max(e for _, e in spans))
        p = ctx.passage
        key_args = sorted(f"{a.role.value}:{a.key}:{a.start}:{int(a.negated)}" for a in args)
        claim = Claim(
            id=stable_id("clm", p.id, relation.value, start, end, key_args),
            passage_id=p.id,
            book_id=p.book_id,
            edition_id=p.edition_id,
            relation=relation,
            arguments=args,
            quote=p.text[start:end],
            start=start,
            end=end,
            temporal=p.temporal,
            extraction=ExtractionInfo(method="lexicon-rule", rule=rule, model=EXTRACTOR_VERSION, confidence=RULE_CONFIDENCE.get(rule, 0.6)),
            polarity=polarity,
            modality=modality,
            context=context,
        )
        ctx.claims.append(claim)
        ctx.covered.append((start, end))
        return claim

    def _scope_args(self, ctx: _Ctx, start: int, end: int, *, causal: bool = False) -> list[ClaimArgument]:
        """Findings, conditions and mechanisms in a text scope, minus adverse-outcome clauses."""
        excluded = [
            (start + m.start(), ctx.sentence_of(start + m.start()).end)
            for m in re.finditer(r"(汗|下|润|服)之(则|徒)", ctx.norm[start:end])
        ]
        excluded += ctx.contra_spans
        cats = FINDING_CATEGORIES + CONDITION_CATEGORIES + ("pathogenesis", "condition", "treatment_method", "treatment_principle")
        weak_ok = causal or any(mk in ctx.norm[start:end] for mk in CAUSAL_MARKERS)
        out = []
        for m in ctx.mentions_in(start, end, *cats, "etiology", "organ", include_weak=weak_ok):
            if any(s <= m.start < e for s, e in excluded):
                continue
            if m.weak and m.category not in ("etiology", "organ"):
                continue
            out.append(self._arg(ctx, m))
        return out

    # ============================================================== rules
    def _rule_herb(self, ctx: _Ctx) -> None:
        m = re.match(r"^(?P<herb>[^，。]{1,6})，味(?P<flavor>[酸苦甘辛咸淡]{1,2})，(?P<nature>微寒|微温|大寒|大热|寒|热|温|凉|平)(?:，无毒)?。主(?:治)?(?P<ind>[^。]+)", ctx.norm)
        if not m:
            return
        herb_m = next((x for x in ctx.mentions if x.category == "herb" and x.start == m.start("herb")), None)
        if herb_m is None:
            entry = self.lex.resolve(m.group("herb"), "herb")
            if entry is None:
                return
            herb_m = Mention(entry, m.group("herb"), m.start("herb"), m.end("herb"))
        nature_val = {"微寒": -0.5, "寒": -1, "大寒": -1, "凉": -0.5, "微温": 0.5, "温": 1, "热": 1, "大热": 1, "平": 0}[m.group("nature")]
        args = [
            self._arg(ctx, herb_m, role=Role.HERB),
            ClaimArgument(role=Role.FLAVOR, surface=m.group("flavor"), term_id=f"flavor:{m.group('flavor')}", start=m.start("flavor"), end=m.end("flavor")),
            ClaimArgument(role=Role.NATURE, surface=m.group("nature"), term_id=f"nature:{m.group('nature')}", start=m.start("nature"), end=m.end("nature"), qualifiers={"value": str(nature_val)}),
        ]
        args.extend(self._indication_items(ctx, m.start("ind"), m.end("ind")))
        alias = re.search(r"一名([^，。]{1,4})", ctx.norm)
        if alias:
            args[0].qualifiers["alias"] = alias.group(1)
        self._new(ctx, ClaimRelation.HERB_INDICATION, args, m.start(), m.end("ind"), "HERB")

    def _indication_items(self, ctx: _Ctx, start: int, end: int) -> list[ClaimArgument]:
        out: list[ClaimArgument] = []
        pos = start
        for item in re.split(r"[，、]", ctx.norm[start:end]):
            s, e = pos, pos + len(item)
            pos = e + 1
            if not item:
                continue
            found = [x for x in ctx.mentions_in(s, e, include_weak=False) if x.category not in ("condition", "concept")]
            if found:
                out.extend(self._arg(ctx, x) for x in found)
            else:
                out.append(ClaimArgument(role=Role.INDICATION, surface=item, term_id=None, start=s, end=e))
        return out

    def _rule_meta(self, ctx: _Ctx) -> None:
        subject = next((x for x in ctx.mentions if x.category == "herb"), None)
        if subject is None:
            return
        for m in re.finditer(r"(昔人|后世|今人|古人)称其([^为]{2,12})为要药", ctx.norm):
            args = [self._arg(ctx, subject, role=Role.HERB)]
            seg_s, seg_e = m.start(2), m.end(2)
            for unit in re.finditer(r"[治除解逐消散疗止破去]([^治除解逐消散疗止破去，]{1,2})", ctx.norm[seg_s:seg_e]):
                us, ue = seg_s + unit.start(), seg_s + unit.end()
                found = ctx.mentions_in(us, ue, "disease", "symptom", "pathogenesis", include_weak=False)
                if found:
                    args.extend(self._arg(ctx, f) for f in found)
                else:
                    args.append(ClaimArgument(role=Role.INDICATION, surface=unit.group(0), start=us, end=ue))
            claim = self._new(ctx, ClaimRelation.HERB_INDICATION, args, m.start(), m.end(), "META", context=f"period_marker:{m.group(1)}")
            if claim is not None:
                claim.tags.append(f"period:{m.group(1)}")

    def _formula_name(self, ctx: _Ctx) -> Mention | None:
        first = next((x for x in ctx.mentions if x.category == "formula"), None)
        if first is not None and first.start == 0:
            return first
        for m in ctx.heading:
            if m.category == "formula":
                return Mention(m.entry, m.surface, -1, -1)
        return first if first is not None and ctx.passage.kind == "formula" else None

    def _rule_composition(self, ctx: _Ctx) -> None:
        if ctx.passage.kind == "materia_medica":
            return
        herbs = [m for m in ctx.mentions if m.category == "herb" and not ctx.in_paren(m.start)]
        dosed: list[tuple[Mention, str | None, str | None]] = []
        pending: list[int] = []
        region_start = None
        for m in herbs:
            pos = m.end
            processing = None
            if ctx.norm.startswith("（", pos):
                close = ctx.norm.find("）", pos)
                processing = ctx.norm[pos + 1: close]
                pos = close + 1
            dose_m = DOSE_RE.match(ctx.norm, pos)
            dose = None
            if dose_m and dose_m.group(0):
                dose = dose_m.group(0)
                after = dose_m.end()
                if ctx.norm.startswith("（", after):
                    close = ctx.norm.find("）", after)
                    processing = (processing + "；" if processing else "") + ctx.norm[after + 1: close]
                if dose.startswith(("各", "以上各")):
                    shared = dose.replace("以上", "").lstrip("各")
                    for idx in pending:
                        h, _, proc = dosed[idx]
                        dosed[idx] = (h, shared, proc)
                    dose = shared
                pending = []
                region_start = m.start if region_start is None else region_start
                dosed.append((m, dose, processing))
            elif ctx.norm[pos: pos + 1] in ("、", "，") and region_start is not None or ctx.norm[pos: pos + 1] == "、":
                pending.append(len(dosed))
                dosed.append((m, None, processing))
                region_start = m.start if region_start is None else region_start
        with_dose = [d for d in dosed if d[1]]
        if not with_dose:
            return
        name = self._formula_name(ctx)
        region_end = max(m.end for m, _, _ in dosed)
        tail = ctx.sentence_of(region_end)
        args: list[ClaimArgument] = []
        if name is not None:
            if name.start >= 0:
                args.append(self._arg(ctx, name, role=Role.FORMULA))
            else:
                args.append(ClaimArgument(role=Role.FORMULA, surface=name.surface, term_id=name.term_id, qualifiers={"from_heading": "true"}))
        for m, dose, proc in dosed:
            if dose is None and not any(d is not None for _, d, _ in dosed):
                continue
            args.append(self._arg(ctx, m, role=Role.HERB, dose=dose or "", processing=proc or ""))
        if name is None:
            # a bare single-herb prescription (e.g. 青蒿一握…) is recorded by the heading rule instead
            if len(dosed) == 1:
                herb_m, dose, _ = dosed[0]
                prep = ctx.norm[region_end: tail.end].lstrip("，")
                ctx.passage_prep = (herb_m, dose, prep)
            return
        self._new(ctx, ClaimRelation.COMPOSED_OF, args, region_start or 0, max(region_end, tail.end), "COMP")

    def _interventions(self, ctx: _Ctx) -> list[tuple[Mention, str, str, int]]:
        """(mention, modality, rule, anchor_end) for every prescribed intervention."""
        out = []
        for m in ctx.mentions:
            if m.category not in ("formula", "herb") or ctx.in_paren(m.start):
                continue
            after = ctx.norm[m.end: m.end + 2]
            before = ctx.norm[max(0, m.start - 4): m.start]
            if after == "主之":
                out.append((m, "assertive", "IND", m.end + 2))
            elif re.search(r"宜(服)?$", before):
                out.append((m, "advisory", "IND-advisory", m.end))
            elif before.endswith("可与"):
                out.append((m, "hedged", "IND-hedged", m.end))
            elif m.category == "herb" and before.endswith("治之以"):
                out.append((m, "assertive", "IND", m.end))
        return out

    def _rule_indicated(self, ctx: _Ctx) -> None:
        interventions = self._interventions(ctx)
        prev_end = 0
        head_args: list[ClaimArgument] | None = None
        for m, modality, rule, anchor in interventions:
            scope_start = prev_end
            for s in ctx.sentences:
                if scope_start <= s.start < m.start and re.match(r"^(若|如)", s.text):
                    scope_start = s.start
            args = [self._arg(ctx, m, role=Role.FORMULA if m.category == "formula" else Role.HERB)]
            scope = self._scope_args(ctx, scope_start, m.start)
            if ctx.norm[max(0, m.start - 3): m.start] == "治之以":
                scope = [a for a in scope if a.role in (Role.DISEASE, Role.PATTERN)][:1]
            args.extend(a for a in scope if a.term_id != m.term_id)
            if head_args is None:
                # shared head context: clauses before the last “…者” clause of the first scope
                cut = ctx.norm.rfind("，", scope_start, max(scope_start, ctx.norm.rfind("者", scope_start, m.start)))
                head_args = [a for a in scope if a.start is not None and cut > 0 and a.start < cut and a.role in (Role.DISEASE, Role.PATTERN, *[Role(r) for r in ("symptom", "sign", "pulse")])]
            elif not any(a.role in (Role.DISEASE, Role.PATTERN) for a in args):
                for a in head_args:
                    args.append(a.replace(qualifiers={**a.qualifiers, "inherited": "true"}))
            if not any(a.role in (Role.DISEASE, Role.PATTERN) for a in args):
                defined = [c for c in ctx.claims if c.relation == ClaimRelation.DEFINES]
                for c in defined:
                    for a in c.args(Role.DISEASE, Role.PATTERN):
                        args.append(a.replace(qualifiers={**a.qualifiers, "inherited": "true"}))
            self._new(ctx, ClaimRelation.INDICATED_FOR, args, scope_start, anchor, rule, modality=modality)
            prev_end = anchor
        # “X：治… / 此方治… / X，治…” formula monographs
        name = self._formula_name(ctx)
        zhi = re.search(r"(?:^|[：:，])(?:此方)?治", ctx.norm)
        if name is not None and zhi and not interventions:
            seg_start = zhi.end()
            comp_start = min(
                (a.start for c in ctx.claims if c.relation == ClaimRelation.COMPOSED_OF for a in c.args(Role.HERB) if a.start is not None),
                default=len(ctx.norm),
            )
            seg_end = min(comp_start, ctx.norm.find("。", seg_start) if "。" in ctx.norm[seg_start:] else len(ctx.norm))
            if ctx.norm.find("……", seg_start) != -1:
                seg_end = min(seg_end, ctx.norm.find("……", seg_start))
            args = [
                self._arg(ctx, name, role=Role.FORMULA) if name.start >= 0
                else ClaimArgument(role=Role.FORMULA, surface=name.surface, term_id=name.term_id, qualifiers={"from_heading": "true"})
            ]
            args.extend(self._scope_args(ctx, seg_start, seg_end))
            self._new(ctx, ClaimRelation.INDICATED_FOR, args, max(0, zhi.start()), seg_end, "IND-zhi")
        # “解诸郁” style monographs without 治
        elif name is not None and not interventions and name.start == 0:
            first_end = ctx.sentences[0].end
            principles = ctx.mentions_in(name.end, first_end, "treatment_principle", "treatment_method")
            if principles:
                args = [self._arg(ctx, name, role=Role.FORMULA)] + [self._arg(ctx, p) for p in principles]
                self._new(ctx, ClaimRelation.INDICATED_FOR, args, 0, first_end, "IND-zhi")

    def _previous_intervention(self, ctx: _Ctx, pos: int) -> Mention | None:
        cands = [m for m in ctx.mentions if m.category in ("formula", "herb") and m.end <= pos and not ctx.in_paren(m.start)]
        return cands[-1] if cands else None

    def _rule_contra(self, ctx: _Ctx) -> None:
        norm = ctx.norm
        for m in re.finditer(r"不可(服之|与也|与之|下也|下|更行|发汗|汗)", norm):
            sent = ctx.sentence_of(m.start())
            clause_start = sent.start
            verb = m.group(1)
            args: list[ClaimArgument] = []
            if verb in ("服之", "与也", "与之"):
                target = self._previous_intervention(ctx, m.start())
                if target is None:
                    continue
                args.append(self._arg(ctx, target).replace(start=None, end=None, qualifiers={"referent": "之"}) if target.start < clause_start else self._arg(ctx, target))
            elif verb == "更行":
                target = next((x for x in ctx.mentions if x.category in ("formula", "herb") and x.start >= m.end()), None)
                if target is None:
                    continue
                args.append(self._arg(ctx, target))
            else:
                entry = self.lex.resolve("下法" if verb.startswith("下") else "发汗")
                args.append(ClaimArgument(role=Role.TREATMENT_METHOD, surface=m.group(0), term_id=entry.term_id if entry else None, start=m.start(), end=m.end()))
            args.extend(a for a in self._scope_args(ctx, clause_start, m.start()) if a.role != Role.TREATMENT_METHOD)
            if len(args) == 1:
                head = self._scope_args(ctx, 0, clause_start)
                args.extend(a for a in head if a.role in (Role.DISEASE, Role.PATTERN, Role.CONDITION))
            ctx.contra_spans.append((clause_start, m.end()))
            self._new(ctx, ClaimRelation.CONTRAINDICATED, args, clause_start, m.end(), "CONTRA")
        for m in re.finditer(r"辄用([^之]{2,10})之类", norm):
            herbs = ctx.mentions_in(m.start(1), m.end(1), "herb", "formula")
            if not herbs:
                continue
            sent_start = ctx.sentence_of(m.start()).start
            args = [self._arg(ctx, h) for h in herbs]
            conds = [a for a in self._scope_args(ctx, 0, m.start()) if a.role in (Role.DISEASE, Role.PATTERN)]
            if not conds:
                conds = [self._arg(ctx, x) for x in ctx.mentions if x.category == "disease" and x.start < m.start()][:1]
            args.extend(conds)
            ctx.contra_spans.append((sent_start, ctx.sentence_of(m.start()).end))
            self._new(ctx, ClaimRelation.CONTRAINDICATED, args, sent_start, m.end(), "CONTRA")
        for m in re.finditer(r"(大忌|忌)([^，。]{2,8})", norm):
            items = ctx.mentions_in(m.start(2), m.end(2), "treatment_principle", "treatment_method", "herb", "etiology")
            if items:
                conds = [self._heading_arg(h) for h in ctx.heading if h.category in ("disease", "pattern", "etiology")]
                self._new(ctx, ClaimRelation.CONTRAINDICATED, [self._arg(ctx, i) for i in items] + conds, m.start(), m.end(), "CONTRA")
        m = re.search(r"所慎者", norm)
        if m:
            items = ctx.mentions_in(m.end(), len(norm), "etiology", include_weak=False)
            subj = [self._heading_arg(h) for h in ctx.heading if h.category == "disease"]
            if items and subj:
                self._new(ctx, ClaimRelation.CONTRAINDICATED, [self._arg(ctx, i) for i in items] + subj, m.start(), ctx.sentence_of(m.end()).end, "CONTRA", context="调护禁忌")
        # adverse outcomes of a method: 汗之则神昏耳聋 …
        for m in re.finditer(r"(汗|下|润)之(则|，必|，|徒)?", norm):
            if re.match(r"(则|乃|即)?愈", norm[m.end(): m.end() + 2]) or norm[m.end(): m.end() + 1] == "可":
                continue
            method = {"汗": "发汗", "下": "下法", "润": "润法"}[m.group(1)]
            entry = self.lex.resolve(method)
            ends = [x for x in (norm.find("，", m.end()), norm.find("。", m.end()), norm.find("；", m.end())) if x != -1]
            clause_end = min(ends or [len(norm)])
            outcomes = [self._arg(ctx, x, outcome="adverse") for x in ctx.mentions_in(m.end(), clause_end, *FINDING_CATEGORIES, "disease")]
            if not outcomes:
                continue
            defined = [a for c in ctx.claims if c.relation == ClaimRelation.DEFINES for a in c.args(Role.DISEASE, Role.PATTERN)]
            if not defined:
                defined = [self._heading_arg(h) for h in ctx.heading if h.category in ("disease", "pattern")][:1]
            args = [ClaimArgument(role=Role.TREATMENT_METHOD, surface=m.group(0)[:2], term_id=entry.term_id if entry else None, start=m.start(), end=m.start() + 2)]
            args += outcomes + [a.replace(qualifiers={**a.qualifiers, "inherited": "true"}) for a in defined[:1]]
            self._new(ctx, ClaimRelation.CONTRAINDICATED, args, m.start(), clause_end, "ADV", context="adverse_outcome")

    def _rule_define(self, ctx: _Ctx) -> None:
        norm = ctx.norm
        for s in ctx.sentences:
            causal_sentence = bool(re.search(r"所感|所致|所生", s.text))
            subject = None
            for m in ctx.mentions_in(s.start, s.end, *CONDITION_CATEGORIES):
                if m.surface.endswith("之为病") or norm.startswith(("之为病", "之状", "病之状"), m.end):
                    subject = m
                    break
            if subject is not None:
                if causal_sentence:
                    continue  # “温疫之为病…异气所感” is an etiology claim, handled by CAUSE
                args = [self._arg(ctx, subject)] + [
                    a for a in self._scope_args(ctx, subject.end, s.end) if a.role not in (Role.TREATMENT_METHOD, Role.TREATMENT_PRINCIPLE)
                ]
                self._new(ctx, ClaimRelation.DEFINES, args, s.start, s.end, "DEF")
                continue
            matched = False
            # …名为X / 名曰X / 此名X / 此为X / 者为X / 是X病也 / 胜者为X / 合而为X
            for m in ctx.mentions_in(s.start, s.end, *CONDITION_CATEGORIES):
                before = norm[max(s.start, m.start - 3): m.start]
                if not re.search(r"(名为|名曰|此名|名|此为|者为|是|皆是|此是|为|合而成)$", before) or before.endswith(("认为", "转为")):
                    continue
                after = norm[m.end: s.end]
                if not re.fullmatch(r"(病)?(也|使然)?", after.rstrip("，")) and not after.startswith("，"):
                    continue
                if "胜者为" in norm[m.start - 4: m.start]:
                    clause_start = max(s.start, norm.rfind("，", s.start, m.start - 3) + 1)
                else:
                    mechanisms = [x for x in ctx.mentions_in(s.start, m.start, "pathogenesis") if not x.weak]
                    clause_start = mechanisms[-1].start if mechanisms and not re.search(r"(名为|名曰|此名|名)$", before) else s.start
                scope = self._scope_args(ctx, clause_start, m.start, causal=True)
                scope = [a for a in scope if a.term_id != m.term_id and a.role not in (Role.TREATMENT_METHOD, Role.TREATMENT_PRINCIPLE)]
                if not scope:
                    continue
                roles = {a.role for a in scope}
                findings = roles & {Role.SYMPTOM, Role.SIGN, Role.PULSE, Role.TONGUE}
                causes_only = roles <= {Role.ETIOLOGY, Role.PATHOGENESIS, Role.CONDITION}
                segment = norm[clause_start: m.start]
                mechanism_scoped = clause_start != s.start and "胜者为" not in norm[m.start - 4: m.start]
                if "伤于" in s.text and "合而" not in segment:
                    continue  # seasonal etiology sentences are handled by CAUSE-season
                if mechanism_scoped:
                    relation, rule = ClaimRelation.PATHOGENESIS, "PATHO-generic"
                elif "合而" in segment:
                    relation, rule = ClaimRelation.CAUSES, "CAUSE"
                elif causes_only and "胜者为" not in norm[m.start - 4: m.start]:
                    continue  # plain causal chains (伤于寒…则为病热) are handled by CAUSE rules
                elif Role.PATHOGENESIS in roles and not findings.issuperset({Role.SYMPTOM}) and not re.search(r"(名为|名曰|此名)$", before):
                    relation, rule = ClaimRelation.PATHOGENESIS, "PATHO-generic"
                else:
                    relation, rule = ClaimRelation.DEFINES, "DEF"
                self._new(ctx, relation, [self._arg(ctx, m)] + scope, clause_start, m.end, rule)
                matched = True
            if matched:
                continue
            # “X者，findings” where X is a disease at the start of the sentence
            lead = ctx.mentions_in(s.start, min(s.end, s.start + 6), *CONDITION_CATEGORIES)
            if lead and norm.startswith("者", lead[0].end) and not re.search(r"(所生|由|所致)", s.text):
                subject = lead[0]
                scope = [a for a in self._scope_args(ctx, subject.end, s.end) if a.role in (Role.SYMPTOM, Role.SIGN, Role.PULSE, Role.TONGUE)]
                if scope:
                    self._new(ctx, ClaimRelation.DEFINES, [self._arg(ctx, subject)] + scope, s.start, s.end, "DEF-generic")

    def _rule_cause(self, ctx: _Ctx) -> None:
        norm = ctx.norm
        seasons = list(re.finditer(r"(春|夏|秋|冬)伤于(风|寒|暑|湿)", norm))
        for i, m in enumerate(seasons):
            end = seasons[i + 1].start() if i + 1 < len(seasons) else ctx.sentence_of(m.end()).end
            end = min(end, ctx.sentence_of(m.end()).end if norm[ctx.sentence_of(m.end()).end: ctx.sentence_of(m.end()).end + 1] == "。" else end)
            etiology = self.lex.resolve(m.group(2), "etiology")
            args = [ClaimArgument(role=Role.ETIOLOGY, surface=m.group(2), term_id=etiology.term_id if etiology else None, start=m.start(2), end=m.end(2)),
                    ClaimArgument(role=Role.CONDITION, surface=m.group(1), term_id=f"condition:{m.group(1)}", start=m.start(1), end=m.end(1), qualifiers={"kind": "exposure_season"})]
            outcomes = ctx.mentions_in(m.end(), end, "disease", "symptom")
            if not outcomes:
                continue
            args += [self._arg(ctx, o) for o in outcomes]
            onset = re.search(r"(春|夏|秋|冬)(必|为|生)", norm[m.end(): end])
            if onset:
                s0 = m.end() + onset.start(1)
                args.append(ClaimArgument(role=Role.CONDITION, surface=onset.group(1), term_id=f"condition:{onset.group(1)}", start=s0, end=s0 + 1, qualifiers={"kind": "onset_season"}))
            self._new(ctx, ClaimRelation.CAUSES, args, m.start(), end, "CAUSE-season")
        for m in re.finditer(r"因于(风|寒|暑|湿|热)", norm):
            sent = ctx.sentence_of(m.start())
            clause_end = norm.find("，", m.end() + 1)
            clause_end = clause_end if clause_end != -1 and clause_end < sent.end else sent.end
            found = ctx.mentions_in(m.end(), clause_end, "symptom", "disease")
            if found:
                ety = self.lex.resolve(m.group(1), "etiology")
                args = [ClaimArgument(role=Role.ETIOLOGY, surface=m.group(1), term_id=ety.term_id if ety else None, start=m.start(1), end=m.end(1))]
                self._new(ctx, ClaimRelation.CAUSES, args + [self._arg(ctx, f) for f in found], m.start(), clause_end, "CAUSE")
        for s in ctx.sentences:
            text = s.text
            if "所感" in text or re.search(r"未有不成|善病|所发|所致|伤于寒也，则为|(^|，)由", text):
                diseases = ctx.mentions_in(s.start, s.end, "disease")
                causes = ctx.mentions_in(s.start, s.end, "etiology", "pathogenesis", include_weak=True)
                subject_args: list[ClaimArgument] = []
                if diseases:
                    subject_args = [self._arg(ctx, diseases[0])]
                else:
                    first = next((x for x in ctx.mentions if x.category == "disease"), None)
                    if first is not None:
                        subject_args = [self._arg(ctx, first, inherited="true")]
                    else:
                        subject_args = [self._heading_arg(h) for h in ctx.heading if h.category == "disease"][:1]
                if subject_args and causes:
                    args = subject_args + [self._arg(ctx, c) for c in causes]
                    args += [self._arg(ctx, o) for o in ctx.mentions_in(s.start, s.end, "organ", include_weak=True)]
                    self._new(ctx, ClaimRelation.CAUSES, args, s.start, s.end, "CAUSE")

    def _rule_pathogenesis(self, ctx: _Ctx) -> None:
        norm = ctx.norm
        for m in re.finditer(r"诸([^，。]{1,3})，皆属于(.)", norm):
            head = ctx.mentions_in(m.start(1), m.end(1), include_weak=True)
            target_pos = m.start(2)
            target = next((x for x in ctx.mentions if x.start == target_pos), None)
            if not head or target is None:
                continue
            args = [self._arg(ctx, h) for h in head] + [self._arg(ctx, target, role=Role.ORGAN if target.category == "organ" else None)]
            self._new(ctx, ClaimRelation.PATHOGENESIS, args, m.start(), m.end(), "PATHO")
        for s in ctx.sentences:
            text = s.text
            if re.search(r"所生|乃生|足生|本源|所由生|生焉|多生于|原是.{1,4}生", text):
                subject = ctx.mentions_in(s.start, s.end, "disease", "symptom", "concept")
                baibing = [x for x in subject if x.term_id == "concept:百病"]
                subject = baibing or subject
                causes = ctx.mentions_in(s.start, s.end, "pathogenesis", "etiology", include_weak=True)
                if subject and causes:
                    args = [self._arg(ctx, subject[0])] + [self._arg(ctx, c) for c in causes if c.term_id != subject[0].term_id]
                    self._new(ctx, ClaimRelation.PATHOGENESIS, args, s.start, s.end, "PATHO")
                    continue
            for m in re.finditer(r"([^，。]{2,6})则(实|虚|阳微)", text):
                mech = ctx.mentions_in(s.start + m.start(1), s.start + m.end(1), "pathogenesis", "etiology", include_weak=True)
                target = ctx.mentions_in(s.start + m.start(2), s.start + m.end(2), "pattern", "pathogenesis", include_weak=True)
                if mech and target:
                    self._new(ctx, ClaimRelation.PATHOGENESIS, [self._arg(ctx, x) for x in mech + target], s.start + m.start(), s.start + m.end(), "PATHO")
            if re.search(r"故(痈肿|为脓)|则为脓|化为热|受病|首先犯|逆传", text):
                args = [self._arg(ctx, x) for x in ctx.mentions_in(s.start, s.end, "pathogenesis", "etiology", "organ", "disease", "symptom", include_weak=True)]
                if len(args) >= 2:
                    self._new(ctx, ClaimRelation.PATHOGENESIS, args, s.start, s.end, "PATHO-generic")

    def _rule_treatment(self, ctx: _Ctx) -> None:
        norm = ctx.norm
        verbs = self.pack.treatment_verbs
        for m in re.finditer(r"([一-鿿])者([一-鿿])之", norm):
            subj_char, verb = m.group(1), m.group(2)
            subject = next((x for x in ctx.mentions if x.start <= m.start(1) < x.end), None)
            if subject is not None and subject.category in ("formula", "herb", "disease"):
                continue
            subj_entry = subject.entry if subject is not None else self.lex.resolve(subj_char)
            subj_arg = ClaimArgument(
                role=Role.PATHOGENESIS if subj_entry is None else Role(self.pack.role_of(subj_entry.category)),
                surface=subj_char if subject is None else subject.surface,
                term_id=None if subj_entry is None else subj_entry.term_id,
                start=m.start(1) if subject is None else subject.start,
                end=m.end(1) if subject is None else subject.end,
            )
            direction = verbs.get(verb)
            method_entry = {1: self.lex.resolve("温法"), -1: self.lex.resolve("清法")}.get(int(direction)) if direction else None
            method = ClaimArgument(
                role=Role.TREATMENT_METHOD, surface=f"{verb}之",
                term_id=method_entry.term_id if method_entry else f"treatment_method:{verb}之",
                start=m.start(2), end=m.end(2) + 1, qualifiers={"nature": str(direction)} if direction else {},
            )
            self._new(ctx, ClaimRelation.TREATMENT_PRINCIPLE, [subj_arg, method], m.start(), m.end(), "TREAT")
        for m in re.finditer(r"([温寒凉清热])能除(大热|热|寒|大寒)", norm):
            direction = verbs.get(m.group(1), 0)
            target = next((x for x in ctx.mentions if x.start == m.start(2)), None)
            entry = self.lex.resolve("甘温除热") if direction > 0 else None
            args = [
                ClaimArgument(role=Role.SYMPTOM, surface=m.group(2), term_id=target.term_id if target else None, start=m.start(2), end=m.end(2)),
                ClaimArgument(role=Role.TREATMENT_PRINCIPLE, surface=m.group(0), term_id=entry.term_id if entry else None, start=m.start(), end=m.end(), qualifiers={"nature": str(direction)}),
            ]
            args += [self._heading_arg(h) for h in ctx.heading if h.category in ("etiology", "pattern")]
            self._new(ctx, ClaimRelation.TREATMENT_PRINCIPLE, args, m.start(), m.end(), "TREAT")
        for s in ctx.sentences:
            principles = ctx.mentions_in(s.start, s.end, "treatment_principle", "treatment_method")
            if not principles or any(s.start <= c.start and c.end <= s.end + 1 and c.relation == ClaimRelation.TREATMENT_PRINCIPLE for c in ctx.claims):
                continue
            if any(
                c.start <= s.start + 2 and s.end - 2 <= c.end
                and c.relation in (ClaimRelation.INDICATED_FOR, ClaimRelation.CONTRAINDICATED, ClaimRelation.HERB_INDICATION, ClaimRelation.COMPOSED_OF)
                for c in ctx.claims
            ) or any(s.start <= c.start < s.end and c.extraction.rule == "ADV" for c in ctx.claims):
                continue
            subjects = ctx.mentions_in(s.start, s.end, "disease", "pattern", "pathogenesis", "condition", "organ", "concept")
            if not subjects:
                prev = [a for c in ctx.claims if c.relation == ClaimRelation.DEFINES for a in c.args(Role.DISEASE, Role.PATTERN)]
                subj_args = [a.replace(qualifiers={**a.qualifiers, "inherited": "true"}) for a in prev[:1]]
                subj_args += [self._heading_arg(h) for h in ctx.heading if h.category in ("disease", "pattern", "etiology")] if not subj_args else []
            else:
                subj_args = [self._arg(ctx, x) for x in subjects]
            if not subj_args:
                subj_args = []
            args = subj_args + [self._arg(ctx, p) for p in principles]
            if len(args) >= 2 and (subj_args or len(principles) >= 2):
                self._new(ctx, ClaimRelation.TREATMENT_PRINCIPLE, args, s.start, s.end, "TREAT-generic")

    def _rule_complication_transform(self, ctx: _Ctx) -> None:
        norm = ctx.norm
        for m in re.finditer(r"转为([^，。]{1,4})", norm):
            target = ctx.mentions_in(m.start(1), m.end(1), "disease")
            source = next((x for x in ctx.mentions if x.category == "disease" and x.start < m.start() and x.term_id != (target[0].term_id if target else None)), None)
            if target and source:
                self._new(ctx, ClaimRelation.TRANSFORMS_TO, [self._arg(ctx, source), self._arg(ctx, target[0])], source.start, m.end(), "TRANS")
        for s in ctx.sentences:
            m = re.search(r"发([^，。]{1,4})", s.text)
            if not m or "之人" not in norm[: s.end]:
                continue
            target = ctx.mentions_in(s.start + m.start(1), s.start + m.end(1), "disease")
            subject = next((x for x in ctx.mentions if x.category == "disease" and norm.startswith("之人", x.end)), None)
            if target and subject and target[0].term_id != subject.term_id:
                args = [self._arg(ctx, subject), self._arg(ctx, target[0])] + [self._arg(ctx, x) for x in ctx.mentions_in(s.start, s.end, "organ", include_weak=False)]
                self._new(ctx, ClaimRelation.COMPLICATION, args, subject.start, s.end, "COMPL")

    def _rule_heading_indication(self, ctx: _Ctx) -> None:
        if any(c.relation == ClaimRelation.INDICATED_FOR for c in ctx.claims):
            return
        section_diseases = [h for h in ctx.heading if h.category == "disease"]
        chapter = ctx.passage.locator.chapter or ""
        prep = ctx.passage_prep
        if prep is not None and re.search(r"治.+方", chapter) and section_diseases:
            herb_m, dose, preparation = prep
            args = [self._arg(ctx, herb_m, role=Role.HERB, dose=dose or "", preparation=preparation)] + [self._heading_arg(h) for h in section_diseases]
            self._new(ctx, ClaimRelation.INDICATED_FOR, args, 0, len(ctx.norm), "IND-heading", context="disease from chapter heading")
            return
        comp = next((c for c in ctx.claims if c.relation == ClaimRelation.COMPOSED_OF), None)
        section = self.pack.variants.normalize_text(ctx.passage.locator.section or "")
        sec_diseases = [m for m in self.lex.match(section) if m.category == "disease" and not m.weak]
        if comp is not None and sec_diseases:
            formula = comp.args(Role.FORMULA)
            if formula:
                args = [formula[0]] + [self._heading_arg(h) for h in sec_diseases]
                self._new(ctx, ClaimRelation.INDICATED_FOR, args, comp.start, comp.end, "IND-heading", context="disease from section heading")

    def _rule_theory(self, ctx: _Ctx) -> None:
        for s in ctx.sentences:
            if any(c.start <= s.start + 1 and s.end - 1 <= c.end for c in ctx.claims) or any(s.start <= c.start < s.end for c in ctx.claims):
                continue
            ms = ctx.mentions_in(s.start, s.end, "disease", "pattern", "pathogenesis", "etiology", "concept", "treatment_principle", "organ", "condition")
            if len({m.term_id for m in ms}) >= 2:
                rel_ctx = "classification" if re.search(r"之类|有.+有", s.text) else ""
                self._new(ctx, ClaimRelation.THEORY, [self._arg(ctx, m) for m in ms], s.start, s.end, "THEORY", context=rel_ctx)

    # =========================================================== finishing
    @staticmethod
    def _dedupe(claims: list[Claim]) -> list[Claim]:
        seen: dict[str, Claim] = {}
        for c in claims:
            seen.setdefault(c.id, c)
        return sorted(seen.values(), key=lambda c: (c.start, c.relation.value, c.id))

    def _confidence(self, claim: Claim, passage: Passage, assessment: PhilologyAssessment | None) -> ConfidenceVector:
        textual = TEXTUAL_BY_MODALITY.get(claim.modality, 0.8)
        if any(a.qualifiers.get("from_heading") for a in claim.arguments):
            textual = min(textual, 0.6)
        philological = None
        if assessment is not None:
            span_p = 1.0
            for c in assessment.contested_at(claim.start, claim.end):
                span_p = min(span_p, c.base_probability())
            philological = round(assessment.philological_confidence * (0.4 + 0.6 * span_p), 4)
        return ConfidenceVector(
            textual=textual,
            philological=philological,
            extraction=claim.extraction.confidence,
            temporal=None,
        )


def claim_terms(claim: Claim, *roles: Role) -> list[str]:
    return claim.terms(*roles)


__all__ = ["ClaimExtractor", "EXTRACTOR_VERSION", "RULE_CONFIDENCE", "claim_terms", "LexEntry"]
