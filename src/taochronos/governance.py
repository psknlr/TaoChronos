"""Architecture governance: checks the codebase and agent specs against ``architecture-policy.yaml``.

* import layering (e.g. the protocol imports nothing; the kernel only the protocol)
* the kernel names no model vendor, database product or classic text
* vendor SDKs are imported only by model-provider plugins
* agents act through capabilities and tools, never by importing plugins
* agent specs: no commit-level permissions, an output schema each, and the director is named TaoChronos
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import yaml

from .config import find_home

PACKAGE = "taochronos"


def _module_of(path: Path, src: Path) -> str:
    rel = path.relative_to(src).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path, module: str) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    is_pkg = path.name == "__init__.py"
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                base = base if is_pkg else base[:-1]
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            out.append((target, node.lineno))
            if node.module is None or node.level:
                out += [(f"{target}.{alias.name}", node.lineno) for alias in node.names]
    return out


def _layer_of(module: str, layers: dict[str, list[str]]) -> str | None:
    rel = module[len(PACKAGE) + 1:] if module.startswith(PACKAGE + ".") else ""
    best, best_len = None, -1
    for layer, prefixes in layers.items():
        for prefix in prefixes:
            if (rel == prefix or rel.startswith(prefix + ".")) and len(prefix) > best_len:
                best, best_len = layer, len(prefix)
    return best


def check(home: Path | None = None) -> dict[str, Any]:
    home = Path(home) if home else find_home()
    policy = yaml.safe_load((home / "architecture-policy.yaml").read_text(encoding="utf-8"))
    src = home / "src"
    layers: dict[str, list[str]] = {}
    allowed: dict[str, list[str]] = {}
    for name, spec in policy["layers"].items():
        layers[name] = [p.replace("src/", "").replace("/", ".").removesuffix(".py").removeprefix(PACKAGE + ".").removeprefix(PACKAGE)
                        for p in spec["paths"]]
        layers[name] = [p.strip(".") for p in layers[name]]
        allowed[name] = list(spec.get("may_import", []))
    violations: list[dict[str, Any]] = []
    files = sorted((src / PACKAGE).rglob("*.py"))
    vendor = set(policy.get("vendor_sdks", []))
    vendor_ok = [p.replace("src/", "").replace("/", ".") for p in policy.get("vendor_sdk_allowed_in", [])]
    for path in files:
        module = _module_of(path, src)
        layer = _layer_of(module, layers)
        if layer is None:
            if module != PACKAGE:
                violations.append({"rule": "unlayered_module", "file": str(path.relative_to(home)), "detail": module})
            continue
        for target, line in _imports(path, module):
            root = target.split(".")[0]
            if root in vendor and not any(module.startswith(v) for v in vendor_ok):
                violations.append({"rule": "vendor_sdk", "file": str(path.relative_to(home)), "line": line, "detail": target})
            if not target.startswith(PACKAGE + "."):
                continue
            target_layer = _layer_of(target, layers)
            if target_layer is None or target_layer == layer or "*" in allowed[layer]:
                continue
            if target_layer not in allowed[layer]:
                violations.append({"rule": "layering", "file": str(path.relative_to(home)), "line": line,
                                   "detail": f"{layer} → {target_layer} ({target})"})
            if layer == "agents" and any(target.startswith(p) for p in policy.get("agents_may_not_import", [])):
                violations.append({"rule": "agents_import_plugins", "file": str(path.relative_to(home)), "line": line, "detail": target})
    terms = policy.get("kernel_forbidden_terms", [])
    for path in sorted((src / PACKAGE / "kernel").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for term in terms:
            pattern = re.compile(re.escape(term), re.IGNORECASE) if term.isascii() else re.compile(re.escape(term))
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                violations.append({"rule": "kernel_forbidden_term", "file": str(path.relative_to(home)), "line": line, "detail": term})
    violations += _check_agents(home, policy)
    return {"policy": str(home / "architecture-policy.yaml"), "files_checked": len(files), "violations": violations,
            "rules": ["layering", "kernel_forbidden_term", "vendor_sdk", "agents_import_plugins", "agent_specs"]}


def _check_agents(home: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    from .agents.schemas import OUTPUT_SCHEMAS
    from .agents.spec import load_specs
    from .kernel.policy import PolicyEngine

    rules = policy.get("agent_rules", {})
    out = []
    specs = load_specs(home / "agents")
    engine = PolicyEngine()
    for role, spec in specs.items():
        if rules.get("forbid_commit_permissions", True):
            for problem in engine.check_grant("agent", spec.permissions):
                out.append({"rule": "agent_specs", "file": spec.source, "detail": problem})
        if rules.get("require_output_schema", True) and spec.output_schema not in OUTPUT_SCHEMAS:
            out.append({"rule": "agent_specs", "file": spec.source, "detail": f"{role}: unknown output schema {spec.output_schema}"})
    director = specs.get("director")
    expected = rules.get("director_name")
    if expected and (director is None or director.name != expected):
        out.append({"rule": "agent_specs", "file": "agents/director.yaml", "detail": f"the research director must be named {expected}"})
    return out
