"""Digital Philology (L1): normalisation, collation and reading assessment.

The philologist never forces a single reading.  Contested spans come back as
probability distributions over witnessed readings plus an explicit
``uncertain`` mass (e.g. Reading A 0.62 · Reading B 0.21 · uncertain 0.08).
"""

from __future__ import annotations

import difflib
from typing import Any

from ...protocol.documents import Passage
from ...protocol.outputs import ContestedSpan, PhilologyAssessment, ReadingOption
from .corpus import Corpus
from .domain import DomainPack

_BASE_BY_STATUS = {"unverified": 0.7, "collated": 0.86, "expert_verified": 0.97}


class PhilologyService:
    def __init__(self, pack: DomainPack, corpus: Corpus) -> None:
        self.pack = pack
        self.corpus = corpus
        self._cache: dict[str, PhilologyAssessment] = {}

    # ------------------------------------------------------------ normalise
    def normalize(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        out, applied = self.pack.variants.normalize(text)
        return out, [n.to_dict() for n in applied]

    def normalized(self, passage: Passage) -> str:
        return self.pack.variants.normalize_text(passage.text)

    # -------------------------------------------------------------- collate
    @staticmethod
    def collate(text_a: str, text_b: str) -> list[dict[str, Any]]:
        """Character-level collation (校勘) of two witnesses."""
        ops = []
        matcher = difflib.SequenceMatcher(None, text_a, text_b, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                ops.append({"op": tag, "a": text_a[i1:i2], "b": text_b[j1:j2], "a_span": [i1, i2], "b_span": [j1, j2]})
        return ops

    # ---------------------------------------------------------------- assess
    def assess(self, passage: Passage) -> PhilologyAssessment:
        cached = self._cache.get(passage.id)
        if cached is not None:
            return cached
        normalized, norms = self.normalize(passage.text)
        book = self.corpus.books.get(passage.book_id)
        edition = book.edition(passage.edition_id) if book else None
        quality = edition.quality if edition else 0.5
        status = passage.collation_status.value
        contested = self._contested_spans(passage, status)
        notes: list[str] = []
        if passage.ocr_confidence is None:
            notes.append("manual transcription (no OCR layer)")
        if status == "unverified":
            notes.append("not collated against a specific edition")
        if passage.abridged:
            notes.append("abridged excerpt (…)")
        for c in contested:
            notes.append(f"contested span “{c.base}”: " + " · ".join(f"{o.reading} {o.probability:.2f}" for o in c.options) + f" · uncertain {c.uncertain:.2f}")
        ocr = passage.ocr_confidence if passage.ocr_confidence is not None else 1.0
        confidence = _BASE_BY_STATUS.get(status, 0.7) * ocr * (0.85 + 0.15 * quality)
        confidence -= min(0.4, 0.15 * len(contested))
        confidence -= 0.05 if passage.abridged else 0.0
        assessment = PhilologyAssessment(
            passage_id=passage.id,
            normalized_text=normalized,
            normalizations=norms,
            contested=contested,
            ocr_confidence=passage.ocr_confidence,
            collation_status=status,
            edition_quality=quality,
            philological_confidence=round(max(0.05, min(1.0, confidence)), 4),
            notes=notes,
        )
        self._cache[passage.id] = assessment
        return assessment

    def span_confidence(self, assessment: PhilologyAssessment, start: int, end: int) -> float:
        """Probability that the base text of [start, end) is the right reading."""
        overlapping = assessment.contested_at(start, end)
        if not overlapping:
            return 1.0
        return round(min(c.base_probability() for c in overlapping), 4)

    # -------------------------------------------------------------- internals
    def _contested_spans(self, passage: Passage, status: str) -> list[ContestedSpan]:
        if not passage.variants:
            return []
        groups: list[list] = []
        for v in sorted(passage.variants, key=lambda v: (v.start, -v.end)):
            if groups and v.start < max(x.end for x in groups[-1]):
                groups[-1].append(v)
            else:
                groups.append([v])
        weights = self.pack.variants.witness_weights
        uncertain = self.pack.variants.uncertain_mass.get(status, 0.08)
        spans = []
        for group in groups:
            start = min(v.start for v in group)
            end = max(v.end for v in group)
            base = passage.text[start:end]
            candidates: list[tuple[str, str, str, float, str]] = [
                (base, "base text of the edition", "base", weights.get("base_edition", 1.0), "")
            ]
            for v in group:
                reading = base[: v.start - start] + v.reading + base[v.end - start:]
                w = weights.get(v.witness_type, 0.5)
                candidates.append((reading, v.witness, v.kind.value, w, v.note))
            scored = []
            rationale = []
            for reading, witness, kind, w, note in candidates:
                coherence, why = self._coherence(passage, reading)
                if why:
                    rationale.append(f"{reading}: {why}")
                scored.append((reading, witness, kind, w * coherence, note))
            total = sum(s[3] for s in scored) or 1.0
            options = [
                ReadingOption(reading=r, witness=wit, kind=k, probability=round((1 - uncertain) * w / total, 4), note=note)
                for r, wit, k, w, note in scored
            ]
            spans.append(
                ContestedSpan(start=start, end=end, base=base, options=options, uncertain=uncertain, rationale="; ".join(rationale))
            )
        return spans

    def _coherence(self, passage: Passage, reading: str) -> tuple[float, str]:
        """TCM-aware plausibility: does the reading's cold/heat claim fit the formula prescribed?

        A cold-natured formula (e.g. 白虎汤) prescribed for an explicitly *interior-cold*
        reading is internally incoherent; such readings are down-weighted, not deleted.
        """
        lex = self.pack.lexicon
        text = self.pack.variants.normalize_text(passage.text)
        formulas = [m.entry for m in lex.match(text) if m.category == "formula" and m.entry.nature is not None]
        if not formulas:
            return 1.0, ""
        reading_mentions = lex.match(self.pack.variants.normalize_text(reading))
        interior = [m.entry for m in reading_mentions if "cold_heat" in m.entry.polarity and m.entry.polarity.get("exterior_interior", 0) > 0]
        if not interior:
            return 1.0, ""
        for formula in formulas:
            for pat in interior:
                if formula.nature and pat.polarity["cold_heat"] and (formula.nature > 0) == (pat.polarity["cold_heat"] > 0):
                    return 0.5, f"{formula.term}（性{'温' if formula.nature > 0 else '寒'}）与“{pat.term}”寒热同向，方证不合"
        return 1.0, f"与{formulas[0].term}方性相合"
