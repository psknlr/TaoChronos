"""Classics domain pack: periods, variant tables, lexicon, terminology, ontology.

Everything TCM-specific that the rest of the system consults lives here as
data (``domains/classics/*.yaml``) — not inside agent prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from ...protocol.concepts import (
    ConceptMapping,
    HistoricalTerm,
    KnowledgeSpace,
    MappingRelation,
    Sense,
    StandardConcept,
    Synonym,
    SynonymKind,
)
from ...protocol.base import stable_id
from ...protocol.documents import YearRange

CATEGORY_PRIORITY = [
    "formula",
    "herb",
    "disease",
    "pattern",
    "symptom",
    "sign",
    "tongue",
    "pulse",
    "pathogenesis",
    "etiology",
    "treatment_method",
    "treatment_principle",
    "organ",
    "condition",
    "concept",
]
PULSE_QUALITIES = "浮沉迟数滑涩弦紧缓洪大微细弱濡虚实小芤结代促"


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- periods
@dataclass
class Period:
    id: str
    label: str
    start: int
    end: int

    def contains(self, year: float) -> bool:
        return self.start <= year < self.end


class Periods:
    def __init__(self, data: dict[str, Any]) -> None:
        self.analysis = [Period(**p) for p in data["analysis_periods"]]
        self.dynasties = [dict(d) for d in data["dynasties"]]
        self.expressions: dict[str, YearRange] = {
            k: YearRange(int(v[0]), int(v[1])) for k, v in data.get("expressions", {}).items()
        }
        self._expr_re = re.compile(
            "(" + "|".join(sorted(map(re.escape, self.expressions), key=len, reverse=True)) + ")"
        )

    def period_of(self, year: float | None) -> str | None:
        if year is None:
            return None
        for p in self.analysis:
            if p.contains(year):
                return p.id
        return self.analysis[0].id if year < self.analysis[0].start else self.analysis[-1].id

    def label(self, period_id: str) -> str:
        for p in self.analysis:
            if p.id == period_id:
                return p.label
        return period_id

    def order(self, period_id: str) -> int:
        for i, p in enumerate(self.analysis):
            if p.id == period_id:
                return i
        return -1

    def ids(self) -> list[str]:
        return [p.id for p in self.analysis]

    _SINGLE_CHAR_TAIL = re.compile(r"^(代|朝|以前|之前|以后|之后|以来|以降|至|到|—|~|时期|初|末|医家|文献|人)")

    def _expression_matches(self, text: str) -> list[re.Match]:
        out = []
        for match in self._expr_re.finditer(text):
            expr = match.group(1)
            # single-character dynasty names (明/清/金/元/宋…) are only temporal when
            # followed by a temporal cue; otherwise 明目 / 清热 / 金疮 / 元气 would be dates
            if len(expr) == 1 and not self._SINGLE_CHAR_TAIL.match(text[match.end():]):
                continue
            out.append(match)
        return out

    def parse_constraint(self, text: str) -> tuple[int | None, int | None]:
        """Parse 宋代以前 / 唐以后 / 汉至宋 / 明清 into (after, before) year bounds."""
        matches = self._expression_matches(text)
        for a, b in zip(matches, matches[1:]):
            between = text[a.end(): b.start()]
            if re.fullmatch(r"代?(至|到|—|-|~)", between) or (
                re.search(r"从$|自$", text[max(0, a.start() - 1): a.start()]) and re.search(r"(至|到)$", between) and len(between) <= 8
            ):
                return self.expressions[a.group(1)].start, self.expressions[b.group(1)].end
        for match in matches:
            rng = self.expressions[match.group(1)]
            tail = text[match.end(): match.end() + 3]
            if re.match(r"^[代朝]?(以前|之前|前)", tail):
                return None, rng.start
            if re.match(r"^[代朝]?(以后|之后|以来|以降|后)", tail):
                return rng.start, None
            return rng.start, rng.end
        return None, None


# --------------------------------------------------------------------------- variants
@dataclass
class Normalization:
    start: int
    end: int
    source: str
    target: str
    kind: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "from": self.source, "to": self.target, "kind": self.kind}


class VariantTable:
    """Length-preserving normalisation so offsets into the original text stay valid."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.chars: dict[str, tuple[str, str]] = {}
        for src, spec in (data.get("char_variants") or {}).items():
            to = spec["to"] if isinstance(spec, dict) else spec
            if len(src) == len(to) == 1 and src != to:
                self.chars[src] = (to, spec.get("note", "") if isinstance(spec, dict) else "")
        self.words: list[dict[str, str]] = []
        for w in data.get("word_variants") or []:
            if len(w["from"]) != len(w["to"]):
                raise ValueError(f"word variant {w['from']}→{w['to']} must preserve length")
            self.words.append(dict(w))
        self.words.sort(key=lambda w: -len(w["from"]))
        self.witness_weights: dict[str, float] = dict(data.get("witness_weights") or {})
        self.uncertain_mass: dict[str, float] = dict(data.get("uncertain_mass") or {})

    def normalize(self, text: str) -> tuple[str, list[Normalization]]:
        chars = list(text)
        applied: list[Normalization] = []
        for i, ch in enumerate(chars):
            if ch in self.chars:
                to, note = self.chars[ch]
                chars[i] = to
                applied.append(Normalization(i, i + 1, ch, to, "variant_char", note))
        out = "".join(chars)
        for w in self.words:
            start = 0
            while True:
                idx = out.find(w["from"], start)
                if idx < 0:
                    break
                out = out[:idx] + w["to"] + out[idx + len(w["to"]):]
                applied.append(Normalization(idx, idx + len(w["to"]), w["from"], w["to"], w.get("kind", "variant"), w.get("note", "")))
                start = idx + len(w["to"])
        applied.sort(key=lambda n: n.start)
        return out, applied

    def normalize_text(self, text: str) -> str:
        return self.normalize(text)[0]


# --------------------------------------------------------------------------- lexicon
@dataclass
class LexEntry:
    term_id: str
    term: str
    category: str
    aliases: list[str] = field(default_factory=list)
    synonyms: dict[str, str] = field(default_factory=dict)  # surface -> SynonymKind value
    synonym_notes: dict[str, str] = field(default_factory=dict)
    polarity: dict[str, float] = field(default_factory=dict)
    origin: str | None = None
    nature: float | None = None
    components: list[str] = field(default_factory=list)
    broader: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    weak: bool = False
    kind: str | None = None
    school: str | None = None
    name_herbs: list[str] = field(default_factory=list)
    name_complete: bool = False
    name_etiology: list[str] = field(default_factory=list)  # etiology encoded in the disease name (中风 → 风)

    def surfaces(self) -> list[str]:
        return [self.term, *self.aliases, *self.synonyms]


@dataclass
class Mention:
    entry: LexEntry
    surface: str
    start: int
    end: int
    synonym_kind: str | None = None

    @property
    def term_id(self) -> str:
        return self.entry.term_id

    @property
    def category(self) -> str:
        return self.entry.category

    @property
    def weak(self) -> bool:
        return self.entry.weak and len(self.surface) == 1


class Lexicon:
    def __init__(self, files: Iterable[Path]) -> None:
        self.entries: dict[str, LexEntry] = {}
        self._by_surface: dict[str, list[tuple[LexEntry, str | None]]] = {}
        for path in files:
            data = _load(path)
            blocks = data if isinstance(data, list) else [data]
            for block in blocks:
                default_cat = block["category"]
                for raw in block.get("entries", []):
                    self._add(self._parse(raw, default_cat))
        for q in PULSE_QUALITIES:
            self._add(LexEntry(term_id=f"pulse:{q}", term=f"脉{q}", category="pulse"))
        self.max_len = max(len(s) for s in self._by_surface)
        self._rank = {c: i for i, c in enumerate(CATEGORY_PRIORITY)}

    @staticmethod
    def _parse(raw: Any, default_cat: str) -> LexEntry:
        if isinstance(raw, str):
            raw = {"term": raw}
        elif isinstance(raw, dict) and "term" not in raw and len(raw) == 1:
            (term, aliases), = raw.items()
            raw = {"term": term, "aliases": aliases or []}
        category = raw.get("category", default_cat)
        synonyms: dict[str, str] = {}
        notes: dict[str, str] = {}
        for syn in raw.get("synonyms", []) or []:
            synonyms[syn["surface"]] = SynonymKind(syn.get("kind", "alias")).value
            if syn.get("note"):
                notes[syn["surface"]] = syn["note"]
        return LexEntry(
            term_id=f"{category}:{raw['term']}",
            term=raw["term"],
            category=category,
            aliases=list(raw.get("aliases") or []),
            synonyms=synonyms,
            synonym_notes=notes,
            polarity={k: float(v) for k, v in (raw.get("polarity") or {}).items()},
            origin=raw.get("origin"),
            nature=None if raw.get("nature") is None else float(raw["nature"]),
            components=list(raw.get("components") or []),
            broader=list(raw.get("broader") or []),
            related=list(raw.get("related") or []),
            weak=bool(raw.get("weak", False)),
            kind=raw.get("kind"),
            school=raw.get("school"),
            name_herbs=list(raw.get("name_herbs") or []),
            name_complete=bool(raw.get("name_complete", False)),
            name_etiology=list(raw.get("name_etiology") or []),
        )

    def _add(self, entry: LexEntry) -> None:
        if entry.term_id in self.entries:
            raise ValueError(f"duplicate lexicon entry {entry.term_id}")
        self.entries[entry.term_id] = entry
        for surface in entry.surfaces():
            kind = entry.synonyms.get(surface)
            bucket = self._by_surface.setdefault(surface, [])
            if all(e.term_id != entry.term_id for e, _ in bucket):
                bucket.append((entry, kind))

    # ---------------------------------------------------------------- lookup
    def entry(self, term_id: str) -> LexEntry | None:
        return self.entries.get(term_id)

    def lookup(self, surface: str) -> list[tuple[LexEntry, str | None]]:
        return sorted(self._by_surface.get(surface, []), key=lambda t: self._rank.get(t[0].category, 99))

    def resolve(self, surface_or_id: str, category: str | None = None) -> LexEntry | None:
        if surface_or_id in self.entries:
            return self.entries[surface_or_id]
        for entry, _ in self.lookup(surface_or_id):
            if category is None or entry.category == category:
                return entry
        return None

    def canonical(self, surface: str, category: str | None = None) -> str | None:
        entry = self.resolve(surface, category)
        return None if entry is None else entry.term_id

    def by_category(self, *categories: str) -> list[LexEntry]:
        return [e for e in self.entries.values() if e.category in categories]

    def match(self, text: str, *, include_weak: bool = True) -> list[Mention]:
        """Longest-first, left-to-right matching on (already normalised) text."""
        mentions: list[Mention] = []
        i, n = 0, len(text)
        while i < n:
            found = None
            for length in range(min(self.max_len, n - i), 0, -1):
                cands = self._by_surface.get(text[i: i + length])
                if cands:
                    entry, kind = sorted(cands, key=lambda t: self._rank.get(t[0].category, 99))[0]
                    found = Mention(entry, text[i: i + length], i, i + length, kind)
                    break
            if found is None:
                i += 1
                continue
            if include_weak or not found.weak:
                mentions.append(found)
            i = found.end
        return mentions


# --------------------------------------------------------------------------- terminology
_MAPPING_FINDINGS = ("symptom", "sign", "tongue", "pulse")


class Terminology:
    def __init__(self, data: dict[str, Any], modern: dict[str, Any]) -> None:
        self.terms: dict[str, HistoricalTerm] = {}
        self.sense_meta: dict[str, dict[str, Any]] = {}
        for raw in data.get("terms", []):
            senses = []
            for s in raw.get("senses", []):
                sense = Sense(
                    id=s["id"],
                    term_id=raw["id"],
                    label=s["label"],
                    gloss=s.get("gloss", s["label"]),
                    category=s["category"],
                    period=YearRange.parse(s.get("period")),
                    cues=list(s.get("cues", [])),
                    anti_cues=list(s.get("anti_cues", [])),
                    exemplars=list(s.get("exemplars", [])),
                    notes=s.get("notes", ""),
                )
                senses.append(sense)
                self.sense_meta[sense.id] = {"scope": s.get("scope", "specific"), "candidates": list(s.get("candidates", []))}
            self.terms[raw["id"]] = HistoricalTerm(
                id=raw["id"],
                surface=raw["id"],
                category=raw.get("category", "disease"),
                senses=senses,
                related=list(raw.get("related", [])),
                broader=list(raw.get("broader", [])),
                notes=raw.get("notes", ""),
            )
        self.concepts: dict[str, StandardConcept] = {}
        for c in modern.get("concepts", []):
            self.concepts[c["id"]] = StandardConcept(
                id=c["id"], label=c["label"], system="modern-biomedical", space=KnowledgeSpace(c.get("space", "biomedical")),
                category=c["category"],
            )

    def term(self, surface: str) -> HistoricalTerm | None:
        return self.terms.get(surface)

    def sense(self, sense_id: str) -> Sense | None:
        term = self.terms.get(sense_id.split("#")[0])
        return None if term is None else term.sense(sense_id)

    def resolve(self, term: str, context_text: str, context_terms: set[str], year: float | None) -> tuple[str | None, float, dict[str, float], str]:
        """Pick the most plausible period-bound sense. Returns (sense_id, p, alternatives, rationale)."""
        ht = self.terms.get(term)
        if ht is None or not ht.senses:
            return None, 0.0, {}, "no curated senses"
        raw: dict[str, float] = {}
        notes: list[str] = []
        for s in ht.senses:
            fit = 1.0
            if year is not None and s.period is not None and not s.period.contains(year):
                distance = min(abs(year - s.period.start), abs(year - s.period.end))
                fit = max(0.15, 1.0 - distance / 600.0)
            hits = [c for c in s.cues if c in context_terms or c in context_text]
            anti = [c for c in s.anti_cues if c in context_terms or c in context_text]
            raw[s.id] = fit * (1.0 + len(hits)) * (0.35 ** len(anti))
            if hits:
                notes.append(f"{s.id}: cues {','.join(hits[:4])}")
        total = sum(raw.values()) or 1.0
        probs = {k: round(v / total, 4) for k, v in raw.items()}
        best = max(probs, key=lambda k: (probs[k], k))
        return best, probs[best], probs, "; ".join(notes) or "period prior only"

    def propose_mapping(self, sense_id: str, concept_id: str, proposer: str = "ontologist") -> ConceptMapping:
        """Conservative, anachronism-averse mapping rules (see docs/discovery.md)."""
        sense = self.sense(sense_id)
        concept = self.concepts.get(concept_id)
        if sense is None or concept is None:
            raise KeyError(f"unknown sense/concept {sense_id} / {concept_id}")
        scope = self.sense_meta.get(sense_id, {}).get("scope", "specific")
        relation, why = map_relation(sense.category, scope, concept.category)
        return ConceptMapping(
            id=stable_id("map", sense_id, concept_id),
            sense_id=sense_id,
            concept_id=concept_id,
            relation=relation,
            rationale=why,
            proposed_by=proposer,
        )


def map_relation(hist_category: str, scope: str, modern_category: str) -> tuple[MappingRelation, str]:
    if hist_category == "organ" and modern_category == "organ":
        return MappingRelation.PARTIALLY_OVERLAPPING, "脏象系统与解剖器官仅部分重叠"
    if hist_category == "herb" and modern_category == "species":
        return MappingRelation.UNCERTAIN, "药名与物种的对应需本草考证（同名异物风险）"
    if scope == "sparse":
        return MappingRelation.UNCERTAIN, "古籍用例过少，无法判定对应关系"
    if hist_category in _MAPPING_FINDINGS:
        if modern_category in _MAPPING_FINDINGS:
            return (
                (MappingRelation.EQUIVALENT, "描述性症状/体征的对应")
                if scope == "descriptive"
                else (MappingRelation.RELATED, "症状层面相关但定义不同")
            )
        return MappingRelation.NOT_EQUIVALENT, "症状不能等同于现代疾病"
    if hist_category == "pattern":
        return MappingRelation.NOT_EQUIVALENT, "证候是辨证框架内的概念，不等同于现代疾病"
    if hist_category in ("pathology", "etiology"):
        if modern_category == "pathology":
            return MappingRelation.RELATED, "病理概念相关但理论体系不同"
        return MappingRelation.NOT_EQUIVALENT, "病机/病因概念不等同于现代疾病或物质"
    if hist_category == "disease_class":
        if modern_category == "disease_class":
            return MappingRelation.RELATED, "病类层面相关"
        return MappingRelation.NOT_EQUIVALENT, "历史病类范围远大于单一现代疾病"
    if hist_category == "disease":
        if modern_category != "disease":
            return MappingRelation.NOT_EQUIVALENT, "类别不同"
        if scope == "broad":
            return MappingRelation.NOT_EQUIVALENT, "历史病名为宽泛范畴，不能等同于特定现代疾病"
        return MappingRelation.PARTIALLY_OVERLAPPING, "历史病名与现代疾病部分重叠（不可等同）"
    return MappingRelation.UNCERTAIN, "缺少判断依据"


# --------------------------------------------------------------------------- pack
class DomainPack:
    """Everything under ``domains/<name>/``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.periods = Periods(_load(self.root / "periods.yaml"))
        self.variants = VariantTable(_load(self.root / "variants.yaml"))
        self.lexicon = Lexicon(sorted((self.root / "lexicon").glob("*.yaml")))
        self.terminology = Terminology(_load(self.root / "terminology.yaml"), _load(self.root / "modern_concepts.yaml"))
        self.ontology = _load(self.root / "ontology.yaml")
        self.citations = _load(self.root / "citations.yaml")
        self.known_findings = _load(self.root / "known_findings.yaml").get("findings", [])
        self.treatment_verbs: dict[str, float] = {k: float(v) for k, v in self.ontology.get("treatment_verbs", {}).items()}
        self.opposition_markers: list[str] = list(self.ontology.get("opposition_markers", []))

    def role_of(self, category: str) -> str:
        return self.ontology["categories"].get(category, {}).get("role", category)

    def synonym_kind_label(self, kind: str | None) -> str:
        return {
            SynonymKind.TABOO_RENAME.value: "避讳改名",
            SynonymKind.PART_NAME.value: "药用部位名",
            SynonymKind.PROCESSING.value: "炮制/加工名",
            SynonymKind.ABBREVIATION.value: "简称",
            SynonymKind.VARIETY.value: "品种/产地名",
            SynonymKind.ALIAS.value: "异名",
        }.get(kind or "", "")


__all__ = [
    "DomainPack",
    "Lexicon",
    "LexEntry",
    "Mention",
    "Periods",
    "Period",
    "Terminology",
    "VariantTable",
    "Normalization",
    "Synonym",
    "map_relation",
    "PULSE_QUALITIES",
]
