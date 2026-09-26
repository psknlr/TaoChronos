"""Epistemic gates G0–G8: knowledge is promoted only after passing them.

G0 Source · G1 OCR/transcription · G2 Philology · G3 Semantic · G4 Claim
(provenance) · G5 Cross-source · G6 Falsification · G7 Expert · G8 Biomedical.
A gate returns pass / warn / fail / pending / not_applicable, never a silent skip.
"""

from __future__ import annotations

from typing import Any, Callable

from ..protocol.claims import Claim
from ..protocol.concepts import MODERN_EVIDENCE_DOMAINS, KnowledgeSpace
from ..protocol.evidence import EvidenceRecord, Stance
from ..protocol.hypothesis import Hypothesis
from ..protocol.research import GateResult, ResearchObject
from .provenance import verify_claim, verify_evidence

_RANK = {"fail": 0, "pending": 1, "warn": 2, "pass": 3, "not_applicable": 4}
GATE_NAMES = {
    "G0": "Source", "G1": "OCR / transcription", "G2": "Philology", "G3": "Semantic", "G4": "Claim provenance",
    "G5": "Cross-source", "G6": "Falsification", "G7": "Expert", "G8": "Biomedical evidence",
}


def worst(results: list[str]) -> str:
    return min(results, key=lambda s: _RANK[s]) if results else "pending"


class GateEvaluator:
    def __init__(
        self,
        corpus: Any,
        philology: Any,
        pack: Any,
        *,
        cluster_of: Callable[[str], str] = lambda b: b,
        min_independent_sources: int = 2,
        sense_threshold: float = 0.6,
    ) -> None:
        self.corpus = corpus
        self.philology = philology
        self.pack = pack
        self.cluster_of = cluster_of
        self.min_independent_sources = min_independent_sources
        self.sense_threshold = sense_threshold
        self.normalize = pack.variants.normalize_text

    # ------------------------------------------------------------- passages
    def g0(self, book_id: str, subject: str) -> GateResult:
        book = self.corpus.books.get(book_id)
        if book is None:
            return GateResult(gate="G0", subject_id=subject, status="fail", details="unknown book")
        src = book.source
        if not src.origin or not src.license:
            return GateResult(gate="G0", subject_id=subject, status="fail", details="missing origin/license metadata")
        note = "verified source" if src.verified else "licensed but unverified transcription"
        return GateResult(gate="G0", subject_id=subject, status="pass", score=1.0 if src.verified else 0.8, details=note)

    def g1(self, passage_id: str, subject: str) -> GateResult:
        p = self.corpus.passage(passage_id)
        if p.ocr_confidence is None:
            status = "pass" if p.collation_status.value != "unverified" else "warn"
            return GateResult(gate="G1", subject_id=subject, status=status, score=0.85 if status == "warn" else 1.0,
                              details="manual transcription (no OCR layer)")
        if p.ocr_confidence >= 0.9:
            return GateResult(gate="G1", subject_id=subject, status="pass", score=p.ocr_confidence, details="OCR confidence ≥ 0.9")
        status = "warn" if p.ocr_confidence >= 0.7 else "fail"
        return GateResult(gate="G1", subject_id=subject, status=status, score=p.ocr_confidence, details="low OCR confidence")

    def g2(self, passage_id: str, subject: str, span: tuple[int, int] | None = None) -> GateResult:
        p = self.corpus.passage(passage_id)
        a = self.philology.assess(p)
        if span is not None:
            contested = a.contested_at(*span)
            if contested:
                base = min(c.base_probability() for c in contested)
                status = "fail" if base < 0.4 else "warn"
                return GateResult(gate="G2", subject_id=subject, status=status, score=base,
                                  details=f"depends on a contested reading (base reading p={base:.2f})")
        if a.collation_status == "unverified":
            return GateResult(gate="G2", subject_id=subject, status="warn", score=a.philological_confidence,
                              details="text not collated against a specific edition")
        return GateResult(gate="G2", subject_id=subject, status="pass", score=a.philological_confidence, details="collated text")

    # ---------------------------------------------------------------- claims
    def g3(self, claim: Claim) -> GateResult:
        passage = self.corpus.passage(claim.passage_id)
        norm = self.normalize(passage.text)
        context = {m.entry.term for m in self.pack.lexicon.match(norm)}
        risks = []
        for arg in claim.arguments:
            if not arg.term_id:
                continue
            surface = arg.term_id.split(":", 1)[-1]
            if self.pack.terminology.term(surface) is None:
                continue
            sense, p, alts, _ = self.pack.terminology.resolve(surface, norm, context, self.corpus.year(passage))
            if len(alts) > 1 and p < self.sense_threshold:
                risks.append(f"{surface}→{sense} ({p:.2f})")
        if risks:
            return GateResult(gate="G3", subject_id=claim.id, status="warn", score=0.5, details="homonym risk: " + "; ".join(risks))
        return GateResult(gate="G3", subject_id=claim.id, status="pass", score=1.0, details="term senses resolved")

    def g4(self, claim: Claim) -> GateResult:
        problems = verify_claim(claim, self.corpus, self.normalize)
        if problems:
            return GateResult(gate="G4", subject_id=claim.id, status="fail", score=0.0, details="; ".join(problems[:3]))
        return GateResult(gate="G4", subject_id=claim.id, status="pass", score=1.0, details="verbatim quote and argument spans verified")

    def evaluate_claim(self, claim: Claim) -> list[GateResult]:
        return [
            self.g0(claim.book_id, claim.id),
            self.g1(claim.passage_id, claim.id),
            self.g2(claim.passage_id, claim.id, (claim.start, claim.end)),
            self.g3(claim),
            self.g4(claim),
        ]

    def evaluate_evidence(self, record: EvidenceRecord) -> list[GateResult]:
        problems = verify_evidence(record, self.corpus)
        g4 = GateResult(gate="G4", subject_id=record.id, status="fail" if problems else "pass",
                        score=0.0 if problems else 1.0, details="; ".join(problems) or "verbatim quote verified")
        return [self.g0(record.book_id, record.id), self.g1(record.passage_id, record.id),
                self.g2(record.passage_id, record.id, (record.start, record.end)), g4]

    # ------------------------------------------------------------ hypotheses
    def evaluate_hypothesis(self, h: Hypothesis, state: ResearchObject, *, required_sources: int | None = None) -> list[GateResult]:
        support = [state.evidence[e] for e in h.supporting_evidence if e in state.evidence]
        results: list[GateResult] = []
        for gate in ("G0", "G1", "G2", "G4"):
            statuses = []
            for rec in support:
                gates = state.gates.get(rec.id) or {g.gate: g for g in self.evaluate_evidence(rec)}
                if gate in gates:
                    statuses.append(gates[gate].status)
            status = worst(statuses) if statuses else "fail"
            if gate == "G2" and statuses and statuses.count("fail") < len(statuses):
                status = "warn" if "fail" in statuses or "warn" in statuses else "pass"
            results.append(GateResult(gate=gate, subject_id=h.id, status=status,
                                      details=f"{len(statuses)} supporting records; worst={worst(statuses) if statuses else 'none'}"))
        sem = [state.gates.get(c, {}).get("G3") for rec in support for c in ([rec.claim_id] if rec.claim_id else [])]
        sem_status = worst([g.status for g in sem if g]) if any(sem) else ("warn" if h.anachronism_risk == "high" else "pass")
        results.append(GateResult(gate="G3", subject_id=h.id, status=sem_status, details="sense resolution of supporting claims"))
        clusters = sorted({self.cluster_of(rec.book_id) for rec in support})
        need = required_sources or self.min_independent_sources
        g5 = "pass" if len(clusters) >= need else ("warn" if clusters else "fail")
        results.append(GateResult(gate="G5", subject_id=h.id, status=g5, score=round(len(clusters) / need, 3),
                                  details=f"{len(clusters)} independent source cluster(s) (need {need}): {', '.join(clusters)}"))
        reviews = state.reviews_for(h.id)
        if not reviews:
            g6 = GateResult(gate="G6", subject_id=h.id, status="pending", details="no skeptic review yet")
        else:
            latest = max(reviews, key=lambda r: (r.round, r.id))
            critical = latest.unresolved("critical")
            major = latest.unresolved("major")
            status = "fail" if critical else ("warn" if major else "pass")
            g6 = GateResult(gate="G6", subject_id=h.id, status=status,
                            details=f"verdict={latest.verdict}; unresolved critical={len(critical)} major={len(major)}")
        results.append(g6)
        g7 = state.gates.get(h.id, {}).get("G7") or GateResult(gate="G7", subject_id=h.id, status="pending", details="awaiting expert review")
        results.append(g7)
        modern = [e for e in state.evidence.values() if e.hypothesis_id == h.id and e.evidence_domain in MODERN_EVIDENCE_DOMAINS]
        if h.space in (KnowledgeSpace.BIOMEDICAL, KnowledgeSpace.MODERN_TCM):
            g8 = GateResult(gate="G8", subject_id=h.id, status="pass" if modern else "fail",
                            details=f"{len(modern)} modern evidence record(s)" if modern else "cross-space claim without modern evidence")
        else:
            g8 = GateResult(gate="G8", subject_id=h.id, status="not_applicable",
                            details="historical-text hypothesis: modern validity not asserted")
        results.append(g8)
        return results


def contradicting(state: ResearchObject, hypothesis_id: str) -> list[EvidenceRecord]:
    return [e for e in state.evidence.values() if e.hypothesis_id == hypothesis_id and e.stance == Stance.CONTRADICTS]
