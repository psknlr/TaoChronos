"""SKILL.md capability packs (M4 skill memory).

A skill is a reusable research method written for agents: a front-matter
header (name, description, tools, applies_to) and a Markdown body.  Agents see
the index of all skills (name + one line) and the full body only of the
skills their AgentSpec loads — progressive disclosure keeps context small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Skill:
    name: str
    description: str
    body: str
    tools: list[str] = field(default_factory=list)
    applies_to: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    path: str = ""

    def render(self) -> str:
        return f"### Skill: {self.name}\n{self.description}\n\n{self.body.strip()}"


def parse_skill(text: str, path: str = "") -> Skill:
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        _, header, body = text.split("---", 2)
        meta = yaml.safe_load(header) or {}
    name = meta.get("name") or Path(path).parent.name
    if not name:
        raise ValueError(f"skill at {path or '?'} has no name")
    return Skill(
        name=name,
        description=str(meta.get("description", "")).strip(),
        body=body.strip(),
        tools=list(meta.get("tools", [])),
        applies_to=list(meta.get("applies_to", [])),
        tags=list(meta.get("tags", [])),
        path=path,
    )


class SkillLibrary:
    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills = {s.name: s for s in skills or []}

    @classmethod
    def load(cls, root: str | Path) -> "SkillLibrary":
        root = Path(root)
        skills = []
        if root.exists():
            for path in sorted(root.glob("*/SKILL.md")):
                skills.append(parse_skill(path.read_text(encoding="utf-8"), str(path)))
        return cls(skills)

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError:
            raise KeyError(f"unknown skill {name!r}") from None

    def has(self, name: str) -> bool:
        return name in self._skills

    def names(self) -> list[str]:
        return sorted(self._skills)

    def for_role(self, role: str) -> list[Skill]:
        return [s for s in self._skills.values() if role in s.applies_to]

    def index(self) -> list[str]:
        return [f"{s.name}: {s.description}" for s in sorted(self._skills.values(), key=lambda s: s.name)]

    def render(self, names: list[str]) -> str:
        return "\n\n".join(self.get(n).render() for n in names if n in self._skills)
