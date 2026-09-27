"""Reading YAML fast: every file the harness reads is parsed once per content.

PyYAML without libyaml parses about a hundred kilobytes a second, and the harvested lexicon alone is 2.7 MB: building a
full-corpus harness spent 26 of its 29 seconds in the YAML scanner.  Every YAML read goes through :func:`load_yaml` or
:func:`loads_yaml`, which key the parsed value by the SHA-256 of the bytes and keep it in a local cache — so an edited
file is simply another key, and a stale entry can never be read.  The cache lives in ``$TAOCHRONOS_CACHE`` (``off``
turns it off), else ``$XDG_CACHE_HOME/taochronos``, else ``~/.cache/taochronos``; it holds only values this module
parsed, as pickled plain data, and it is safe to delete at any time.  The C loader is used when PyYAML has one; a
document an older libyaml refuses is read by the Python loader (both give the same value wherever both read it).
"""

from __future__ import annotations

import hashlib
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any

import yaml

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
FORMAT = 1  # bumped whenever the cached representation changes
_OFF = ("off", "0", "no", "none", "false")


def cache_dir() -> Path | None:
    """Where parsed YAML is kept, or None when caching is off."""
    env = os.environ.get("TAOCHRONOS_CACHE", "").strip()
    if env.lower() in _OFF:
        return None
    if env:
        return Path(env) / "yaml"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "taochronos" / "yaml"


def _parse(raw: bytes) -> Any:
    text = raw.decode("utf-8")
    if _LOADER is not yaml.SafeLoader:
        try:
            return yaml.load(text, Loader=_LOADER)  # noqa: S506 — CSafeLoader, a safe loader
        except yaml.YAMLError:
            pass  # an older libyaml refuses plain scalars the Python loader reads (``[modern:x]`` in a flow sequence)
    return yaml.load(text, Loader=yaml.SafeLoader)  # noqa: S506


def _cached(raw: bytes) -> Any:
    root = cache_dir()
    if root is None:
        return _parse(raw)
    key = hashlib.sha256(raw).hexdigest()
    target = root / key[:2] / f"{key}.v{FORMAT}.pickle"
    try:
        with open(target, "rb") as fh:
            return pickle.load(fh)  # noqa: S301 — only values this module wrote, named by the hash of their source
    except FileNotFoundError:
        pass
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ValueError):
        pass  # a damaged entry is parsed again and replaced
    value = _parse(raw)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".pickle")
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, target)  # atomic: a concurrent reader sees the old file or the whole new one
    except OSError:
        pass  # a read-only home: parse every time, as before
    return value


def load_yaml(path: str | Path) -> Any:
    """The parsed content of a YAML file (a fresh object on every call: callers may modify it)."""
    return _cached(Path(path).read_bytes())


def loads_yaml(text: str | bytes) -> Any:
    """The parsed content of a YAML string."""
    return _cached(text.encode("utf-8") if isinstance(text, str) else text)


__all__ = ["cache_dir", "load_yaml", "loads_yaml"]
