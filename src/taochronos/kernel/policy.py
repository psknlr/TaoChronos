"""Capability-based permissions.

Hard invariant: an LLM-backed agent can never hold a *commit* permission on
canonical knowledge (ontology, terminology, gold data, domain memory).  Agents
``propose``; validators and humans ``commit``.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

PRIVILEGED_PRINCIPALS = frozenset({"human", "validator", "kernel"})

COMMIT_PATTERNS = (
    "*:commit",
    "gold:write",
    "canonical:write",
    "ontology:write",
    "terminology:write",
)


class PolicyViolation(PermissionError):
    pass


@dataclass(frozen=True)
class Actor:
    id: str
    role: str
    principal: str = "agent"  # agent | human | validator | kernel
    permissions: frozenset[str] = field(default_factory=frozenset)
    name: str = ""

    @property
    def label(self) -> str:
        return f"{self.principal}:{self.id}" if not self.id.startswith(f"{self.principal}:") else self.id

    @staticmethod
    def kernel() -> "Actor":
        return Actor(id="kernel", role="kernel", principal="kernel")

    @staticmethod
    def validator(name: str = "gates") -> "Actor":
        return Actor(id=f"validator:{name}", role="validator", principal="validator")

    @staticmethod
    def human(name: str) -> "Actor":
        return Actor(id=f"human:{name}", role="expert", principal="human", name=name)


def is_commit_permission(permission: str) -> bool:
    return any(fnmatch.fnmatchcase(permission, pattern) for pattern in COMMIT_PATTERNS)


class PolicyEngine:
    def __init__(self, deny: list[str] | None = None) -> None:
        self.deny = list(deny or [])

    def check_grant(self, principal: str, permissions: frozenset[str] | set[str] | list[str]) -> list[str]:
        """Return violations for a permission grant (used when AgentSpecs are loaded)."""
        if principal in PRIVILEGED_PRINCIPALS:
            return []
        return [
            f"{principal} may not be granted commit-level permission '{p}' (propose instead)"
            for p in permissions
            if is_commit_permission(p) or p == "*"
        ]

    def allowed(self, actor: Actor, permission: str) -> bool:
        if any(fnmatch.fnmatchcase(permission, pattern) for pattern in self.deny):
            return actor.principal in ("human", "kernel")
        if actor.principal in PRIVILEGED_PRINCIPALS:
            return True
        if is_commit_permission(permission):
            return False
        return any(fnmatch.fnmatchcase(permission, granted) for granted in actor.permissions)

    def require(self, actor: Actor, permission: str) -> None:
        if not self.allowed(actor, permission):
            raise PolicyViolation(f"{actor.id} lacks permission '{permission}'")
