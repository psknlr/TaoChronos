"""Analytics sandboxes: Python for statistics and figures in a separate, resource-limited process — at an explicit
security tier (see :mod:`.isolation`).

* :class:`SubprocessSandbox` — the **process** tier: its own process, CPU/memory/time limits, a scrubbed environment
  (no API keys), the session workspace as working directory.  It does **not** isolate the filesystem: the code can
  read and write whatever the harness user can.  It is for trusted code, the system's own snippets.
* :class:`NamespaceSandbox` — the **namespace** tier: a new root in which the system directories are read-only and the
  session workspace is the only writable place, a private /tmp, no network, its own process namespace, no home or
  data directories, no credentials, and no capability over its own mounts.  Model-written code runs here.
* :class:`SandboxRouter` — picks the tier by the code's origin and refuses untrusted code when no isolating tier is
  available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .isolation import ISOLATES, RANK, REQUIRED, Launcher, SandboxUnavailable, namespace_available, run_boot

_BOOT = r"""
import json, sys
payload = json.loads(sys.stdin.read())
ns = {"inputs": payload["inputs"], "__name__": "__sandbox__"}
exec(compile(payload["code"], "<analytics>", "exec"), ns)
sys.stdout.write("\n__TAOCHRONOS_RESULT__" + json.dumps({"result": ns.get("result")}, ensure_ascii=False, default=str))
"""


class SubprocessSandbox:
    name = "subprocess"
    tier = "process"
    isolates = ISOLATES["process"]

    def __init__(self, root: str | Path, cpu_seconds: int = 20, memory_mb: int = 1024) -> None:
        self.root = Path(root)
        self.cpu_seconds = cpu_seconds
        self.memory_mb = memory_mb

    def available(self) -> bool:
        return Launcher(self.tier).available()

    def workspace(self, session_id: str) -> Path:
        base = self.root / session_id / "workspace"
        for sub in ("data", "notebooks", "artifacts", "tmp"):
            (base / sub).mkdir(parents=True, exist_ok=True)
        return base

    def run(self, code: str, inputs: dict[str, Any] | None = None, *, session_id: str = "adhoc", timeout: float = 30.0) -> dict[str, Any]:
        launcher = Launcher(self.tier, cpu_seconds=self.cpu_seconds, memory_mb=self.memory_mb)
        out = run_boot(launcher, _BOOT, {"code": code, "inputs": inputs or {}}, self.workspace(session_id), timeout)
        out["workspace"] = str(self.workspace(session_id))
        return out


class NamespaceSandbox(SubprocessSandbox):
    name = "namespace"
    tier = "namespace"
    isolates = ISOLATES["namespace"]

    def available(self) -> bool:
        return namespace_available()


class SandboxRouter:
    """Runs code at the tier its origin requires: ``trusted`` (the system's own snippets) → process or better;
    ``model`` / ``user`` → namespace or better.  With no tier good enough available it raises
    :class:`SandboxUnavailable` — it never runs untrusted code in a weaker tier."""

    def __init__(self, sandboxes: list[SubprocessSandbox]) -> None:
        self.sandboxes = sorted(sandboxes, key=lambda s: RANK[s.tier], reverse=True)

    def pick(self, origin: str) -> SubprocessSandbox:
        need = RANK[REQUIRED.get(origin, "namespace")]
        for sandbox in self.sandboxes:
            if RANK[sandbox.tier] >= need and sandbox.available():
                return sandbox
        raise SandboxUnavailable(f"code of origin {origin!r} needs isolation at tier ≥ {REQUIRED.get(origin, 'namespace')}; "
                                 "none is available here, so it is not run")

    def run(self, code: str, inputs: dict[str, Any] | None = None, *, origin: str = "model", session_id: str = "adhoc",
            timeout: float = 30.0) -> dict[str, Any]:
        return self.pick(origin).run(code, inputs, session_id=session_id, timeout=timeout)

    def tiers(self) -> list[dict[str, Any]]:
        return [{"tier": s.tier, "available": s.available(), "isolates": s.isolates} for s in self.sandboxes]


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    root = Path(getattr(context, "data_dir", ".taochronos")) / "sessions"
    cpu, mem = config.get("cpu_seconds", 20), config.get("memory_mb", 1024)
    process = SubprocessSandbox(root, cpu, mem)
    namespace = NamespaceSandbox(root, cpu, mem)
    registry.register("sandbox", "subprocess", process)
    registry.register("sandbox", "namespace", namespace)
    registry.register("sandbox", "router", SandboxRouter([process, namespace]))


__all__ = ["NamespaceSandbox", "SandboxRouter", "SandboxUnavailable", "SubprocessSandbox"]
