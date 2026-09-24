"""The composition root: profile → plugins → capabilities → tools → agents → runtime.

This is the only place that knows how the pieces fit together.  Everything it
wires is replaceable by configuration (a profile) without touching the kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .agents.context_views import VIEWS
from .agents.router import CognitiveRouter
from .agents.runtime import AgentRuntime
from .agents.skills import SkillLibrary
from .agents.spec import AgentSpec, SpecError, load_specs, validate_spec
from .config import data_dir as default_data_dir
from .config import find_home
from .kernel.artifacts import ArtifactManager
from .kernel.budget import Budget, BudgetLimits
from .kernel.context import ContextManager
from .kernel.hooks import HookRegistry
from .kernel.memory import MemoryStore
from .kernel.policy import PolicyEngine
from .kernel.profiles import Profile, list_profiles, load_profile
from .kernel.registry import CapabilityRegistry
from .kernel.store import EventStore, MemoryEventStore
from .kernel.tools import ToolRegistry, ToolScheduler
from .plugins.sandbox.codemode import codemode_tool
from .tools.adapters import author_clusters
from .tools.mesh import build_tool_registry
from .verification.gates import GateEvaluator
from .verification.hooks import install_default_hooks

MODEL_PLUGIN_KEYS = {
    "taochronos.plugins.models.anthropic_provider": "anthropic",
    "taochronos.plugins.models.openai_compat": "openai_compat",
    "taochronos.plugins.models.offline": "offline",
    "taochronos.plugins.models.scripted": "scripted",
}


@dataclass
class HarnessContext:
    home: Path
    data_dir: Path


class Harness:
    """A fully wired TaoChronos instance for one profile."""

    def __init__(
        self,
        profile: Profile,
        *,
        home: Path,
        data_dir: Path,
        store: EventStore | None = None,
        corpus: Any = None,
        extra_plugins: list[tuple[str, dict[str, Any]]] | None = None,
        providers: dict[str, Any] | None = None,
    ) -> None:
        self.profile = profile
        self.home = home
        self.data_dir = data_dir
        self.context = HarnessContext(home=home, data_dir=data_dir)
        self.capabilities = CapabilityRegistry()
        for bundle in profile.bundles:
            module = bundle["plugin"]
            config = dict(bundle.get("config") or {})
            key = MODEL_PLUGIN_KEYS.get(module)
            if key:
                config = {**config, **(profile.models.get(key) or {})}
            if corpus is not None and module == "taochronos.plugins.classics":
                config["corpus_object"] = corpus
            self.capabilities.load_plugin(module, config, self.context)
        for module, config in extra_plugins or []:
            self.capabilities.load_plugin(module, config, self.context)
        for name, provider in (providers or {}).items():
            self.capabilities.register("llm", name, provider)

        self.corpus = self.capabilities.get("corpus")
        self.pack = self.capabilities.get("domain")
        self.philology = self.capabilities.get("philology")
        self.policy = PolicyEngine(deny=list(profile.policy.get("deny", [])))
        self.hooks = HookRegistry()
        self.installed_hooks = install_default_hooks(self.hooks, corpus=self.corpus, pack=self.pack,
                                                     enabled=list(profile.hooks) or None)
        self.tools: ToolRegistry = build_tool_registry()
        self.codemode = codemode_tool(self.tools)
        self.tools.register(self.codemode)
        self.modern_evidence = self._load_modern_evidence()
        gate_cfg = profile.gates
        corpus_, philology_, pack_ = self.corpus, self.philology, self.pack

        def gates(state: Any) -> GateEvaluator:
            need = state.goal.required_evidence.min_independent_sources if state.goal else gate_cfg.get("min_independent_sources", 2)
            return GateEvaluator(corpus_, philology_, pack_, cluster_of=author_clusters(corpus_, list(state.lineage.values())),
                                 min_independent_sources=need, sense_threshold=float(gate_cfg.get("sense_threshold", 0.6)))

        self.gates = gates
        self.scheduler = ToolScheduler(self.tools, self.policy, self.hooks, self.capabilities,
                                       max_workers=int(profile.context.get("max_workers", 4)),
                                       services={"gates": gates, "modern_evidence": self.modern_evidence})
        self.skills = SkillLibrary.load(home / "skills")
        self.specs = self._load_specs()
        self.router = CognitiveRouter(self.capabilities, routing=profile.routing)
        self.memory = MemoryStore(data_dir / "memory")
        self.context_manager = ContextManager(int(profile.context.get("max_tokens", 24000)))
        subagents = {name: self.capabilities.get("subagent", name) for name in self.capabilities.names("subagent")}
        self.runtime = AgentRuntime(
            capabilities=self.capabilities, tools=self.tools, scheduler=self.scheduler, policy=self.policy,
            hooks=self.hooks, specs=self.specs, router=self.router, context=self.context_manager, memory=self.memory,
            skills=self.skills, subagents=subagents, config=dict(profile.discovery), codemode=self.codemode,
        )
        self.store = store if store is not None else self._open_store()
        self.artifacts = ArtifactManager(data_dir / "artifacts", self.hooks)

    # ----------------------------------------------------------------- factory
    @classmethod
    def from_profile(
        cls,
        name: str = "full-discovery",
        *,
        home: str | Path | None = None,
        data_dir: str | Path | None = None,
        store: EventStore | None = None,
        overrides: dict[str, Any] | None = None,
        corpus: Any = None,
        providers: dict[str, Any] | None = None,
        ephemeral: bool = False,
    ) -> "Harness":
        home_path = Path(home).resolve() if home else find_home()
        profile = load_profile(name, [home_path / "profiles"], overrides)
        data = Path(data_dir) if data_dir else default_data_dir(home_path)
        data.mkdir(parents=True, exist_ok=True)
        if ephemeral and store is None:
            store = MemoryEventStore()
        return cls(profile, home=home_path, data_dir=data, store=store, corpus=corpus, providers=providers)

    @staticmethod
    def profiles(home: str | Path | None = None) -> list[str]:
        home_path = Path(home) if home else find_home()
        return [p for p in list_profiles([home_path / "profiles"]) if p != "base"]

    # ----------------------------------------------------------------- pieces
    def _load_modern_evidence(self) -> list[dict[str, Any]]:
        rel = self.profile.retrieval.get("modern_evidence")
        if not rel:
            return []
        path = self.home / rel
        if not path.exists():
            return []
        return list((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("records", []))

    def _load_specs(self) -> dict[str, AgentSpec]:
        specs = load_specs(self.home / "agents")
        wanted = self.profile.agents or ["*"]
        if "*" not in wanted:
            missing = sorted(set(wanted) - set(specs))
            if missing:
                raise SpecError(f"profile {self.profile.name} names unknown agents {missing}")
            specs = {k: v for k, v in specs.items() if k in wanted}
        errors: list[str] = []
        for spec in specs.values():
            errors += validate_spec(spec, policy=self.policy, tools=self.tools, skills=self.skills, views=set(VIEWS))
        if errors:
            raise SpecError("invalid agent specs:\n  " + "\n  ".join(errors))
        return specs

    def _open_store(self) -> EventStore:
        factory = self.capabilities.get("event_store") if self.capabilities.has("event_store") else None
        return factory() if callable(factory) else MemoryEventStore()

    def make_goal(self, question: str, **fields: Any) -> Any:
        """A research contract with this profile's defaults (tracks, stop conditions, evidence requirements)."""
        from .protocol.research import CorpusScope, GoalSpec, RequiredEvidence, StopConfig

        if "stop" not in fields:
            fields["stop"] = StopConfig.from_dict(dict(self.profile.stop))
        elif isinstance(fields["stop"], dict):
            fields["stop"] = StopConfig.from_dict({**self.profile.stop, **fields["stop"]})
        if isinstance(fields.get("corpus"), dict):
            fields["corpus"] = CorpusScope.from_dict(fields["corpus"])
        if isinstance(fields.get("required_evidence"), dict):
            fields["required_evidence"] = RequiredEvidence.from_dict(fields["required_evidence"])
        fields.setdefault("tracks", list(self.profile.tracks) or ["D1", "D2", "D3", "D4", "D5"])
        fields.setdefault("profile", self.profile.name)
        if "min_independent_sources" in self.profile.gates and "required_evidence" not in fields:
            fields["required_evidence"] = RequiredEvidence(min_independent_sources=int(self.profile.gates["min_independent_sources"]))
        return GoalSpec(question=question, **fields)

    def new_budget(self) -> Budget:
        return Budget(BudgetLimits.from_dict(self.profile.budget), name="session")

    def engine(self) -> Any:
        from .engine.research import ResearchEngine

        return ResearchEngine(self)

    def describe(self) -> dict[str, Any]:
        return {
            "profile": self.profile.name,
            "home": str(self.home),
            "data_dir": str(self.data_dir),
            "plugins": list(self.capabilities.loaded_plugins),
            "capabilities": self.capabilities.capabilities(),
            "agents": {r: s.name for r, s in sorted(self.specs.items())},
            "skills": self.skills.names(),
            "tools": self.tools.names(),
            "hooks": self.hooks.names(),
            "routing": self.profile.routing,
        }
