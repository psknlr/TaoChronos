"""Profiles and bundles: which plugins, agents, skills, gates and budgets a research run loads."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Profile:
    name: str
    description: str = ""
    extends: str | None = None
    bundles: list[dict[str, Any]] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tracks: list[str] = field(default_factory=list)
    models: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    hooks: list[str] = field(default_factory=list)
    gates: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    stop: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    discovery: dict[str, Any] = field(default_factory=dict)
    source: str | None = None

    def raw(self) -> dict[str, Any]:
        return {k: copy.deepcopy(v) for k, v in self.__dict__.items()}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge dictionaries; ``key+`` in the override appends to the base list ``key``."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key.endswith("+"):
            real = key[:-1]
            out[real] = list(out.get(real, [])) + list(value)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _find(name_or_path: str, search_dirs: list[Path]) -> Path:
    candidate = Path(name_or_path)
    if candidate.suffix in (".yaml", ".yml") and candidate.exists():
        return candidate
    for directory in search_dirs:
        for suffix in (".yaml", ".yml"):
            path = directory / f"{name_or_path}{suffix}"
            if path.exists():
                return path
    raise FileNotFoundError(f"profile '{name_or_path}' not found in {[str(d) for d in search_dirs]}")


def load_profile_dict(name_or_path: str, search_dirs: list[Path], _seen: tuple[str, ...] = ()) -> dict[str, Any]:
    path = _find(name_or_path, search_dirs)
    if str(path) in _seen:
        raise ValueError(f"profile inheritance cycle: {' -> '.join(_seen + (str(path),))}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("name", path.stem)
    data["source"] = str(path)
    parent = data.get("extends")
    if parent:
        base = load_profile_dict(parent, search_dirs, _seen + (str(path),))
        base.pop("source", None)
        merged = deep_merge(base, {k: v for k, v in data.items() if k != "extends"})
        merged["extends"] = parent
        return merged
    return data


def load_profile(name_or_path: str, search_dirs: list[Path], overrides: dict[str, Any] | None = None) -> Profile:
    data = load_profile_dict(name_or_path, search_dirs)
    if overrides:
        data = deep_merge(data, overrides)
    known = set(Profile.__dataclass_fields__)
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"profile {data.get('name')}: unknown keys {unknown}")
    return Profile(**data)


def list_profiles(search_dirs: list[Path]) -> list[str]:
    names: set[str] = set()
    for directory in search_dirs:
        if directory.exists():
            names.update(p.stem for p in directory.glob("*.yaml"))
    return sorted(names)
