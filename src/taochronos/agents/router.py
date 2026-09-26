"""Cognitive Model Router: which intelligence (if any) runs an agent.

The router routes by *cognitive task*, not by vendor:

* tool-first roles (pattern mining, statistics, lineage…) never get a model;
* judgement roles get the cheapest available model that meets the spec's
  ``min_tier``, preferring strong classical-Chinese readers where the spec
  asks for it;
* adversarial roles (the Skeptic) prefer a *different* model from the one
  that generated the hypotheses they review;
* profile ``routing`` overrides everything per role;
* when nothing suitable is available the role falls back to its
  deterministic procedure — the harness never stops for lack of a model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..capabilities.llm import TIER_RANK, ModelInfo
from .spec import AgentSpec

OFFLINE = ("offline", "taochronos-offline")
DEFAULT_EFFORT = {"frontier": "high", "medium": "medium", "small": "low"}


@dataclass
class RouteDecision:
    role: str
    mode: str  # procedure | llm | hybrid | subagent
    provider: str
    model: str
    tier: str
    effort: str | None
    reason: str
    subagent: str | None = None
    fallback: str | None = None

    @property
    def uses_model(self) -> bool:
        return self.mode in ("llm", "hybrid", "subagent")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CognitiveRouter:
    def __init__(self, capabilities: Any, routing: dict[str, Any] | None = None) -> None:
        self.capabilities = capabilities
        self.routing = routing or {}
        self.history: dict[str, RouteDecision] = {}

    @property
    def default_provider(self) -> str:
        return self.routing.get("default_provider", "offline")

    def candidates(self, providers: list[str] | None = None) -> list[tuple[str, ModelInfo]]:
        names = providers or self.capabilities.names("llm")
        out = []
        for name in names:
            if not self.capabilities.has("llm", name):
                continue
            provider = self.capabilities.get("llm", name)
            if getattr(provider, "deterministic", False) or not provider.available():
                continue
            out.extend((name, m) for m in provider.models() if not m.deterministic)
        return out

    def _procedure(self, spec: AgentSpec, reason: str) -> RouteDecision:
        return RouteDecision(role=spec.role, mode="procedure", provider=OFFLINE[0], model=OFFLINE[1], tier="deterministic",
                             effort=None, reason=reason)

    def route(self, spec: AgentSpec, task: Any = None) -> RouteDecision:
        decision = self._route(spec)
        self.history[spec.role] = decision
        return decision

    def _route(self, spec: AgentSpec) -> RouteDecision:
        override = dict((self.routing.get("roles") or {}).get(spec.role) or {})
        if override.get("mode") == "procedure":
            return self._procedure(spec, "profile routing pins this role to its deterministic procedure")
        if spec.mode == "procedure" and not override.get("mode"):
            return self._procedure(spec, "tool-first role: deterministic procedure (no model needed)")
        provider_name = override.get("provider") or self.default_provider
        if provider_name == "offline" and not override:
            return self._procedure(spec, "offline profile: deterministic procedure")
        subagent = override.get("subagent") or (spec.subagent if spec.subagent != "local" else None)
        if subagent:
            mode = "subagent"
        else:
            mode = override.get("mode") or ("hybrid" if spec.mode == "procedure" else spec.mode)
        preferred = [provider_name] + [p for p in self.routing.get("prefer", []) if p != provider_name]
        pool = self.candidates(preferred)
        if override.get("model"):
            pool = [(p, m) for p, m in pool if m.name == override["model"]]
        min_rank = TIER_RANK.get(override.get("min_tier", spec.min_tier), TIER_RANK["medium"])
        pool = [(p, m) for p, m in pool if TIER_RANK.get(m.tier, 0) >= min_rank]
        if not pool and not subagent:
            fallback = self._procedure(spec, f"no available model meets tier {spec.min_tier}; deterministic procedure")
            fallback.fallback = "procedure"
            return fallback
        if subagent:
            return RouteDecision(role=spec.role, mode="subagent", provider=f"subagent:{subagent}", model=override.get("model", subagent),
                                 tier=override.get("min_tier", spec.min_tier), effort=spec.effort, reason="profile routes this role to a subagent provider",
                                 subagent=subagent, fallback="procedure" if spec.procedure else None)
        paired = (self.routing.get("diversity") or {"skeptic": "hypothesis"}).get(spec.role)
        paired_model = self.history.get(paired).model if paired and paired in self.history else None

        def score(item: tuple[str, ModelInfo]) -> tuple:
            prov, m = item
            provider_rank = preferred.index(prov) if prov in preferred else len(preferred)
            tier_excess = TIER_RANK.get(m.tier, 0) - min_rank  # cheapest adequate tier first
            reader = -m.classical_chinese if spec.model.get("prefer") == "classical_chinese" else 0.0
            same_as_paired = 1 if paired_model and m.name == paired_model else 0
            return (provider_rank, same_as_paired, tier_excess, reader, m.input_cost_per_mtok, m.name)

        provider, model = sorted(pool, key=score)[0]
        reasons = [f"{spec.role} needs tier ≥ {spec.min_tier}"]
        if spec.model.get("prefer") == "classical_chinese":
            reasons.append(f"classical-Chinese prior {model.classical_chinese:.2f}")
        if paired_model:
            reasons.append("different model from the reviewed generator" if model.name != paired_model
                           else "no alternative model for adversarial diversity")
        effort = override.get("effort") or spec.effort or DEFAULT_EFFORT.get(model.tier)
        return RouteDecision(role=spec.role, mode=mode, provider=provider, model=model.name, tier=model.tier, effort=effort,
                             reason="; ".join(reasons), fallback="procedure" if spec.procedure else None)
