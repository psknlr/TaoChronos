"""Locating the TaoChronos home (profiles, agents, skills, domains, corpus) and the data directory."""

from __future__ import annotations

import os
from pathlib import Path

MARKER = "architecture-policy.yaml"


class HomeNotFound(FileNotFoundError):
    pass


def find_home(start: str | Path | None = None) -> Path:
    """``$TAOCHRONOS_HOME``, else the nearest ancestor of *start* (or CWD, or this package) holding the marker file."""
    env = os.environ.get("TAOCHRONOS_HOME")
    if env:
        path = Path(env).expanduser().resolve()
        if not (path / MARKER).exists():
            raise HomeNotFound(f"TAOCHRONOS_HOME={path} does not contain {MARKER}")
        return path
    candidates = [Path(start).resolve()] if start else []
    candidates += [Path.cwd().resolve(), Path(__file__).resolve().parent]
    for base in candidates:
        for directory in (base, *base.parents):
            if (directory / MARKER).exists():
                return directory
    raise HomeNotFound(f"could not find {MARKER}; set TAOCHRONOS_HOME to the repository root")


def data_dir(home: Path | None = None) -> Path:
    env = os.environ.get("TAOCHRONOS_DATA")
    path = Path(env).expanduser() if env else (home or find_home()) / ".taochronos"
    path.mkdir(parents=True, exist_ok=True)
    return path
