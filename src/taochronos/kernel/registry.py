"""Capability registry: ``Capability → Provider Registry → Provider``.

Business code asks for ``registry.get("retriever", "hybrid")`` and never
imports a concrete provider.  Plugins are loaded by dotted module path from a
profile, so the kernel itself contains no vendor or corpus names.
"""

from __future__ import annotations

import importlib
from typing import Any


class CapabilityError(LookupError):
    pass


class CapabilityRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, dict[str, Any]] = {}
        self._defaults: dict[str, str] = {}
        self.loaded_plugins: list[str] = []

    def register(self, capability: str, name: str, provider: Any, *, default: bool = False) -> None:
        self._providers.setdefault(capability, {})[name] = provider
        if default or capability not in self._defaults:
            self._defaults[capability] = name

    def get(self, capability: str, name: str | None = None) -> Any:
        providers = self._providers.get(capability)
        if not providers:
            raise CapabilityError(f"no provider registered for capability '{capability}'")
        key = name or self._defaults[capability]
        if key not in providers:
            raise CapabilityError(f"capability '{capability}' has no provider '{key}' (have: {sorted(providers)})")
        return providers[key]

    def has(self, capability: str, name: str | None = None) -> bool:
        providers = self._providers.get(capability, {})
        return bool(providers) if name is None else name in providers

    def names(self, capability: str) -> list[str]:
        return sorted(self._providers.get(capability, {}))

    def default_name(self, capability: str) -> str | None:
        return self._defaults.get(capability)

    def set_default(self, capability: str, name: str) -> None:
        if name not in self._providers.get(capability, {}):
            raise CapabilityError(f"cannot default '{capability}' to unknown provider '{name}'")
        self._defaults[capability] = name

    def capabilities(self) -> dict[str, list[str]]:
        return {cap: sorted(providers) for cap, providers in sorted(self._providers.items())}

    def load_plugin(self, module: str, config: dict | None = None, context: Any = None) -> None:
        """Import ``module`` and call its ``register(registry, config, context)``."""
        mod = importlib.import_module(module)
        register = getattr(mod, "register", None)
        if register is None:
            raise CapabilityError(f"plugin {module} has no register() function")
        register(self, config or {}, context)
        self.loaded_plugins.append(module)
