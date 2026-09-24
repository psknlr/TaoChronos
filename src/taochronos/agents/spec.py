"""Declarative AgentSpecs: an agent is configuration, not a class.

    role: philologist
    name: TaoChronos-Philologist
    objective: Assess readings, variants and collation status; never force a single reading.
    mode: hybrid                      # procedure | llm | hybrid
    procedure: taochronos.agents.procedures.philologist
    skills: [philology-collation]
    tools: [philology.*, classics.get_passage, validation.verify_quote]
    context_view: philology
    permissions: [classics:read]
    output_schema: PhilologyReport
    model: {min_tier: medium, effort: high, prefer: classical_chinese}
    budget: {max_tool_calls: 60, max_llm_calls: 12}
    stop_conditions: [output_valid, max_turns:8]
    review_required: false

Specs are validated when loaded: commit-level permissions are refused, every
tool must exist and be covered by a granted permission, output schemas,
context views, skills and procedures must resolve.
"""

from __future__ import annotations

import fnmatch
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..capabilities.llm import TIERS
from ..kernel.budget import BudgetLimits
from ..kernel.policy import Actor, PolicyEngine
from ..kernel.tools import ToolRegistry
from .schemas import OUTPUT_SCHEMAS
from .skills import SkillLibrary

MODES = ("procedure", "llm", "hybrid")


class SpecError(ValueError):
    pass


@dataclass
class AgentSpec:
    role: str
    name: str
    objective: str
    output_schema: str
    mode: str = "procedure"
    procedure: str | None = None
    description: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    context_view: str = "default"
    permissions: list[str] = field(default_factory=list)
    model: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    stop_conditions: list[str] = field(default_factory=list)
    review_required: bool = False
    code_mode: bool = False
    subagent: str = "local"
    config: dict[str, Any] = field(default_factory=dict)
    source: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str | None = None) -> "AgentSpec":
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise SpecError(f"agent spec {data.get('role', source)}: unknown keys {unknown}")
        for key in ("role", "name", "objective", "output_schema"):
            if not data.get(key):
                raise SpecError(f"agent spec {source or '?'}: missing '{key}'")
        return cls(**{**data, "source": source})

    # ----------------------------------------------------------- derived
    @property
    def min_tier(self) -> str:
        return self.model.get("min_tier", "medium")

    @property
    def effort(self) -> str | None:
        return self.model.get("effort")

    @property
    def max_turns(self) -> int:
        for cond in self.stop_conditions:
            if cond.startswith("max_turns:"):
                return int(cond.split(":", 1)[1])
        return int(self.model.get("max_turns", 8))

    def limits(self) -> BudgetLimits:
        return BudgetLimits.from_dict(self.budget)

    def actor(self, task_id: str | None) -> Actor:
        """Agent ids are derived from role and task, so a resumed run attributes work identically."""
        return Actor(
            id=f"agent:{self.role}@{task_id}" if task_id else f"agent:{self.role}",
            role=self.role,
            principal="agent",
            permissions=frozenset(self.permissions),
            name=self.name,
        )

    def tool_names(self, registry: ToolRegistry) -> list[str]:
        names: list[str] = []
        for pattern in self.tools:
            for name in registry.names():
                if (fnmatch.fnmatchcase(name, pattern) or name == pattern) and name not in names:
                    names.append(name)
        return names

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "source"}


def load_specs(directory: str | Path) -> dict[str, AgentSpec]:
    specs: dict[str, AgentSpec] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        spec = AgentSpec.from_dict(data, str(path))
        if spec.role in specs:
            raise SpecError(f"duplicate agent role {spec.role!r} ({path} and {specs[spec.role].source})")
        specs[spec.role] = spec
    return specs


def load_procedure(path: str) -> Any:
    module = importlib.import_module(path)
    for attr in ("draft", "commit", "instructions"):
        if not callable(getattr(module, attr, None)):
            raise SpecError(f"procedure module {path} lacks {attr}()")
    return module


def validate_spec(
    spec: AgentSpec,
    *,
    policy: PolicyEngine,
    tools: ToolRegistry,
    skills: SkillLibrary | None = None,
    views: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    errors += policy.check_grant("agent", spec.permissions)
    if spec.mode not in MODES:
        errors.append(f"mode {spec.mode!r} not in {MODES}")
    if spec.output_schema not in OUTPUT_SCHEMAS:
        errors.append(f"unknown output_schema {spec.output_schema!r}")
    if spec.min_tier not in TIERS:
        errors.append(f"model.min_tier {spec.min_tier!r} not in {TIERS}")
    if spec.procedure:
        try:
            load_procedure(spec.procedure)
        except (ImportError, SpecError) as exc:
            errors.append(f"procedure: {exc}")
    elif spec.mode != "llm":
        errors.append(f"mode {spec.mode} needs a procedure")
    if views is not None and spec.context_view not in views:
        errors.append(f"unknown context_view {spec.context_view!r}")
    for name in spec.skills:
        if skills is not None and not skills.has(name):
            errors.append(f"unknown skill {name!r}")
    granted = set(spec.permissions)
    for pattern in spec.tools:
        matched = [n for n in tools.names() if fnmatch.fnmatchcase(n, pattern) or n == pattern]
        if not matched:
            errors.append(f"tool pattern {pattern!r} matches no registered tool")
        for name in matched:
            needed = tools.get(name).permission
            if not any(fnmatch.fnmatchcase(needed, g) for g in granted):
                errors.append(f"tool {name} requires permission {needed!r}, which the spec does not grant")
    return [f"{spec.role}: {e}" for e in errors]
