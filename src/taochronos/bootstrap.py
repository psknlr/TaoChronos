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
from .verification.scope import capability_views

MODEL_PLUGIN_KEYS = {
    "taochronos.plugins.models.anthropic_provider": "anthropic",
    "taochronos.plugins.models.openai_compat": "openai_compat",
    "taochronos.plugins.models.litellm_provider": "litellm",
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
        sandbox_cfg = next((dict(b.get("config") or {}) for b in profile.bundles if b.get("plugin") == "taochronos.plugins.sandbox"), {})
        # model-written Code Mode programs run isolated unless a profile explicitly trusts its models to run in-process
        self.codemode = codemode_tool(self.tools, isolation=str(sandbox_cfg.get("codemode_isolation", "namespace")),
                                      workspace_root=data_dir / "sessions")
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
                                       services={"gates": gates, "modern_evidence": self.modern_evidence},
                                       views=capability_views())
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
        # a profile that names a judge has the study layer's uncertain decisions reviewed by it — when it is reachable
        if (profile.judge or {}).get("provider") and self.capabilities.has("study"):
            try:
                self.capabilities.get("study").judge = self.judge("auto")
            except ValueError:
                pass  # no key or no model: the rules decide alone

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

    # ------------------------------------------------------------------ judge
    def llm_provider(self, name: str) -> Any:
        """A registered LLM provider, or one made on the fly from an OpenAI-compatible preset (minimax, poe, qwen …)."""
        if self.capabilities.has("llm", name):
            return self.capabilities.get("llm", name)
        from .plugins.models.openai_compat import PRESETS, OpenAICompatibleProvider

        if name not in PRESETS:
            known = sorted(set(self.capabilities.names("llm")) | set(PRESETS))
            raise ValueError(f"unknown LLM provider {name!r}; known: {', '.join(known)}")
        provider = OpenAICompatibleProvider(name, {"preset": name})
        self.capabilities.register("llm", name, provider)
        return provider

    def use_llm(self, spec: str, *, tier: str = "frontier", classical_chinese: float = 0.7) -> tuple[str, str]:
        """One model for everything a model does in this run (``--llm provider:model``): the judgement roles of research
        are routed to it and it reviews rule decisions.  Returns (provider, model)."""
        name, _, model = spec.partition(":")
        provider = self.llm_provider(name)
        if model and hasattr(provider, "add_model"):
            provider.add_model(model, tier=tier, classical_chinese=classical_chinese)
        elif not model:
            models = [m for m in provider.models() if not m.deterministic]
            if not models:
                raise ValueError(f"name a model: --llm {name}:<model>")
            model = models[0].name
        self.profile.routing = {**(self.profile.routing or {}), "default_provider": name}
        self.router.routing = self.profile.routing
        self.profile.judge = {**(self.profile.judge or {}), "provider": name, "model": model, "tier": tier}
        return name, model

    def judge(self, spec: str | None = None, *, refresh: bool = False, max_calls: int | None = None,
              max_cost_usd: float | None = None) -> Any:
        """The model that reviews rule decisions: ``provider:model``, ``provider`` (its first model), ``auto`` (the
        profile's ``judge``, else the best available model), or None for rules only."""
        from datetime import date

        from .capabilities.judge import Judge, JudgeBudget

        cfg = dict(self.profile.judge or {})
        spec = spec or cfg.get("spec")
        if not spec or spec in ("none", "off", "rules"):
            return None
        if spec == "auto":
            if cfg.get("provider"):
                spec = f"{cfg['provider']}:{cfg['model']}" if cfg.get("model") else cfg["provider"]
            else:
                from .capabilities.llm import TIER_RANK

                pool = [(p, m) for p, m in self.router.candidates() if TIER_RANK.get(m.tier, 0) >= TIER_RANK["medium"]]
                if not pool:
                    raise ValueError("no LLM provider is available for --llm auto: configure one (see `taochronos llm presets`)")
                pool.sort(key=lambda pm: (-pm[1].classical_chinese, TIER_RANK.get(pm[1].tier, 0), pm[1].input_cost_per_mtok))
                spec = f"{pool[0][0]}:{pool[0][1].name}"
        name, _, model = spec.partition(":")
        provider = self.llm_provider(name)
        if model:
            add = getattr(provider, "add_model", None)
            if add is not None:
                add(model, tier=cfg.get("tier", "medium"), classical_chinese=float(cfg.get("classical_chinese", 0.5)))
            elif model not in {m.name for m in provider.models()}:
                raise ValueError(f"{name} does not offer {model!r}")
        else:
            models = [m for m in provider.models() if not m.deterministic]
            if not models:
                examples = getattr(provider, "examples", [])
                hint = f" (e.g. {name}:{examples[0]})" if examples else ""
                raise ValueError(f"name a model for {name}: --llm {name}:<model>{hint}")
            model = models[0].name
        if not provider.available():
            env = getattr(provider, "api_key_env", None)
            raise ValueError(f"{name} is not available" + (f": set {env}" if env else ""))
        budget = JudgeBudget(max_calls=int(max_calls or cfg.get("max_calls", 200)),
                             max_cost_usd=float(max_cost_usd or cfg.get("max_cost_usd", 5.0)))
        return Judge(provider, model, cache_dir=self.data_dir / "llm-cache", budget=budget, refresh=refresh,
                     log_path=self.data_dir / "llm-log" / f"{date.today().isoformat()}.jsonl",
                     temperature=cfg.get("temperature", 0.0))

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
