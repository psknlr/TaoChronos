"""Analytics sandbox: arbitrary Python for statistics/figures in a separate, resource-limited process.

The sandbox gets JSON inputs and returns ``result`` as JSON.  It runs inside a
per-session workspace (``workspace/{data,notebooks,artifacts,tmp}``) and has no
handle on canonical stores (knowledge graph, ontology, gold data).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_BOOT = r"""
import json, sys
payload = json.loads(sys.stdin.read())
ns = {"inputs": payload["inputs"], "__name__": "__sandbox__"}
exec(compile(payload["code"], "<analytics>", "exec"), ns)
sys.stdout.write("\n__TAOCHRONOS_RESULT__" + json.dumps({"result": ns.get("result")}, ensure_ascii=False, default=str))
"""


class SubprocessSandbox:
    name = "subprocess"

    def __init__(self, root: str | Path, cpu_seconds: int = 20, memory_mb: int = 1024) -> None:
        self.root = Path(root)
        self.cpu_seconds = cpu_seconds
        self.memory_mb = memory_mb

    def workspace(self, session_id: str) -> Path:
        base = self.root / session_id / "workspace"
        for sub in ("data", "notebooks", "artifacts", "tmp"):
            (base / sub).mkdir(parents=True, exist_ok=True)
        return base

    def _limits(self) -> None:  # pragma: no cover - runs in the child
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_seconds, self.cpu_seconds))
            limit = self.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except Exception:
            pass

    def run(self, code: str, inputs: dict[str, Any] | None = None, *, session_id: str = "adhoc", timeout: float = 30.0) -> dict[str, Any]:
        cwd = self.workspace(session_id)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "HOME": str(cwd)}
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _BOOT],
            input=json.dumps({"code": code, "inputs": inputs or {}}, ensure_ascii=False),
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env=env,
            timeout=timeout,
            preexec_fn=self._limits if os.name == "posix" else None,
        )
        out = proc.stdout
        result = None
        if "__TAOCHRONOS_RESULT__" in out:
            out, raw = out.rsplit("__TAOCHRONOS_RESULT__", 1)
            result = json.loads(raw)["result"]
        return {"ok": proc.returncode == 0, "result": result, "stdout": out[-4000:], "stderr": proc.stderr[-4000:],
                "returncode": proc.returncode, "workspace": str(cwd)}


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    root = Path(getattr(context, "data_dir", ".taochronos")) / "sessions"
    registry.register("sandbox", "subprocess", SubprocessSandbox(root, config.get("cpu_seconds", 20), config.get("memory_mb", 1024)))
