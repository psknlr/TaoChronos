"""Sandbox plugins: Research Code Mode (in-process, AST-validated) and the subprocess analytics sandbox."""

from __future__ import annotations

from typing import Any

from . import codemode, subprocess_sandbox
from .codemode import CodeModeError, codemode_tool, run_code, sdk_reference, validate_code
from .subprocess_sandbox import SubprocessSandbox


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    codemode.register(registry, config, context)
    subprocess_sandbox.register(registry, config, context)


__all__ = ["CodeModeError", "SubprocessSandbox", "codemode_tool", "register", "run_code", "sdk_reference", "validate_code"]
