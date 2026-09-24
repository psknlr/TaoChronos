"""TaoChronos agents: declarative specs, skills, the Cognitive Model Router and the agent runtime.

An agent is configuration (an AgentSpec), not a class: a role, an objective, skills, tools, a context view,
permissions, an output schema and a budget.  The research director is named TaoChronos; specialists are
TaoChronos-<Role>.  Agents are spawned per task by the engine — never as a fixed team.
"""

from .planning import KERNEL_ROLES, KIND_ROLE, wire
from .router import CognitiveRouter, RouteDecision
from .runtime import AgentContext, AgentError, AgentRefused, AgentRuntime, TaskResult, parse_json_output
from .schemas import OUTPUT_SCHEMAS, output_schema
from .skills import Skill, SkillLibrary
from .spec import AgentSpec, SpecError, load_specs, validate_spec

__all__ = [
    "AgentContext",
    "AgentError",
    "AgentRefused",
    "AgentRuntime",
    "AgentSpec",
    "CognitiveRouter",
    "KERNEL_ROLES",
    "KIND_ROLE",
    "OUTPUT_SCHEMAS",
    "RouteDecision",
    "Skill",
    "SkillLibrary",
    "SpecError",
    "TaskResult",
    "load_specs",
    "output_schema",
    "parse_json_output",
    "validate_spec",
    "wire",
]
