"""Stop conditions are decided by the harness, never by a model saying "I'm done"."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..protocol.research import ResearchObject, StopConfig
from .budget import Budget


@dataclass
class RoundStats:
    round: int
    new_evidence: int = 0
    total_evidence: int = 0
    new_sources: int = 0
    new_hypotheses: int = 0
    surviving: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class StopDecision:
    stop: bool
    status: str  # continue | completed | awaiting_expert | budget_exhausted | max_rounds
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)


class StopEvaluator:
    def __init__(self, config: StopConfig, required_gates: list[str] | None = None) -> None:
        self.config = config
        self.required_gates = [g for g in (required_gates or []) if g not in ("G7", "G8")]

    def validation_passed(self, state: ResearchObject, top_k: int = 3) -> bool:
        ranked = sorted(state.active_hypotheses(), key=lambda h: (-h.elo, h.id))[:top_k]
        if not ranked:
            return False
        strict = set(self.config.strict_gates)
        for h in ranked:
            for gate in self.required_gates:
                status = state.gate_status(h.id, gate)
                allowed = ("pass", "not_applicable") if gate in strict else ("pass", "warn", "not_applicable")
                if status not in allowed:
                    return False
        return True

    def critical_objections(self, state: ResearchObject) -> list[str]:
        out = []
        for h in state.active_hypotheses():
            for review in state.reviews_for(h.id):
                if review.unresolved("critical") and h.status not in ("rejected", "superseded"):
                    out.append(h.id)
                    break
        return out

    def evaluate(self, state: ResearchObject, stats: RoundStats, budget: Budget | None = None) -> StopDecision:
        cfg = self.config
        reasons: list[str] = []
        saturation = stats.new_evidence / stats.total_evidence if stats.total_evidence else 0.0
        signals = {
            "round": stats.round,
            "evidence_gain_ratio": round(saturation, 4),
            "new_sources": stats.new_sources,
            "validation_passed": self.validation_passed(state),
            "unresolved_contradictions": sum(1 for c in state.contradictions.values() if not c.resolved),
            "critical_objections": self.critical_objections(state),
        }
        if budget is not None and budget.exhausted():
            return StopDecision(True, "budget_exhausted", ["budget exhausted"], signals)
        if stats.round >= 1 and saturation < cfg.evidence_saturation:
            reasons.append(f"evidence saturation ({saturation:.3f} < {cfg.evidence_saturation})")
        if stats.round >= 1 and stats.new_sources < cfg.min_novel_source_gain:
            reasons.append(f"novel source gain {stats.new_sources} < {cfg.min_novel_source_gain}")
        if cfg.stop_on_validation and signals["validation_passed"]:
            reasons.append("top hypotheses passed required gates")
        if cfg.require_contradictions_addressed and signals["unresolved_contradictions"]:
            reasons = [r for r in reasons if not r.startswith("top hypotheses")]
        if cfg.expert_intervention_on_critical and signals["critical_objections"] and stats.round >= cfg.max_rounds:
            return StopDecision(True, "awaiting_expert", reasons + ["critical objections need expert judgement"], signals)
        if stats.round >= cfg.max_rounds:
            return StopDecision(True, "max_rounds", reasons + [f"reached max_rounds={cfg.max_rounds}"], signals)
        saturated = any(r.startswith("evidence saturation") for r in reasons) and any(
            r.startswith("novel source gain") for r in reasons
        )
        if saturated or (signals["validation_passed"] and cfg.stop_on_validation and stats.round >= 1):
            return StopDecision(True, "completed", reasons, signals)
        return StopDecision(False, "continue", reasons, signals)
