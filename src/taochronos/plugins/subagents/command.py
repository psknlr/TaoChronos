"""External-process subagents (JSON in on stdin, JSON out on stdout).

Lets any command-line agent act as a TaoChronos role — e.g. a CLI coding agent
in print mode, a local model runner, or a colleague's script — configured in a
profile:

    subagents:
      command:
        providers:
          reviewer-cli:
            command: ["my-agent", "--json"]
            timeout: 600

The subprocess receives ``{agent, role, task, system, prompt, output_schema}``
and must print one JSON object.  Its output is untrusted: the runtime validates
it against the role's schema and the role's commit checks verify every quote.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class SubagentError(RuntimeError):
    pass


class CommandSubagentProvider:
    def __init__(self, name: str, command: list[str], *, timeout: float = 600.0, env: dict[str, str] | None = None) -> None:
        if not command:
            raise ValueError(f"subagent {name}: empty command")
        self.name = name
        self.command = list(command)
        self.timeout = timeout
        self.env = env

    def available(self) -> bool:
        return shutil.which(self.command[0]) is not None

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            proc = subprocess.run(self.command, input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                                  text=True, timeout=self.timeout, env=self.env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SubagentError(f"subagent {self.name} timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise SubagentError(f"subagent {self.name} exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        text = proc.stdout.strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise SubagentError(f"subagent {self.name} printed no JSON object")
        try:
            data = json.loads(text[start: end + 1])
        except json.JSONDecodeError as exc:
            raise SubagentError(f"subagent {self.name} printed invalid JSON: {exc}") from exc
        # a wrapper envelope such as {"result": "<json>"} is unwrapped once
        if isinstance(data.get("result"), str) and data["result"].strip().startswith("{"):
            try:
                data = json.loads(data["result"])
            except json.JSONDecodeError:
                pass
        return data
