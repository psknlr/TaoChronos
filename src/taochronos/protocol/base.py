"""Serialization, hashing and identity primitives shared by every protocol object.

All protocol objects are plain dataclasses that inherit :class:`Model`.  They
serialise to canonical JSON (sorted keys, no ASCII escaping) so that content
hashes, event logs and state digests are byte-stable across runs and machines.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import types
import typing
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T", bound="Model")


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / enums / containers into JSON-ready values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(to_jsonable(v) for v in obj)
    if isinstance(obj, float) and obj != obj:  # NaN is not valid JSON
        return None
    return obj


def canonical_json(obj: Any) -> str:
    """Byte-stable JSON used for hashing and ids."""
    return json.dumps(to_jsonable(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def stable_id(prefix: str, *parts: Any, length: int = 12) -> str:
    """Deterministic id derived from content, so re-running a task reproduces ids."""
    digest = hashlib.sha1(canonical_json(list(parts)).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def _is_union(tp: Any) -> bool:
    origin = get_origin(tp)
    return origin is Union or origin is types.UnionType


def _convert(tp: Any, value: Any) -> Any:
    if value is None or tp is Any:
        return value
    if _is_union(tp):
        options = [a for a in get_args(tp) if a is not type(None)]
        if len(options) == 1:
            return _convert(options[0], value)
        for option in options:
            try:
                return _convert(option, value)
            except (TypeError, ValueError, KeyError):
                continue
        return value
    origin = get_origin(tp)
    if origin is typing.Literal:
        return value
    if origin in (list, typing.List):
        (arg,) = get_args(tp) or (Any,)
        return [_convert(arg, v) for v in value]
    if origin in (set, frozenset):
        (arg,) = get_args(tp) or (Any,)
        return origin(_convert(arg, v) for v in value)
    if origin is tuple:
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], v) for v in value)
        if args:
            return tuple(_convert(a, v) for a, v in zip(args, value))
        return tuple(value)
    if origin in (dict, typing.Dict):
        args = get_args(tp)
        vt = args[1] if len(args) == 2 else Any
        return {k: _convert(vt, v) for k, v in value.items()}
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            if isinstance(value, tp):
                return value
            if not isinstance(value, dict):
                raise TypeError(f"expected mapping for {tp.__name__}, got {type(value).__name__}")
            return from_dict(tp, value)
        if issubclass(tp, enum.Enum):
            return value if isinstance(value, tp) else tp(value)
        if tp is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if tp in (str, int, bool, float) and not isinstance(value, tp):
            raise TypeError(f"expected {tp.__name__}, got {type(value).__name__}")
    return value


_HINT_CACHE: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    hints = _HINT_CACHE.get(cls)
    if hints is None:
        hints = get_type_hints(cls)
        _HINT_CACHE[cls] = hints
    return hints


def from_dict(cls: type[T], data: dict[str, Any]) -> T:
    """Build a dataclass instance from a mapping, converting nested values by type hints.

    Unknown keys are ignored so that newer event logs can still be read by older code.
    """
    hints = _hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if not f.init or f.name not in data:
            continue
        kwargs[f.name] = _convert(hints.get(f.name, Any), data[f.name])
    return cls(**kwargs)


class Model:
    """Mixin for protocol dataclasses."""

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        return from_dict(cls, data)

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    def replace(self: T, **changes: Any) -> T:
        return dataclasses.replace(self, **changes)  # type: ignore[type-var]

    def digest(self) -> str:
        return content_hash(self)


def field_list() -> Any:
    """Shorthand for ``dataclasses.field(default_factory=list)``."""
    return dataclasses.field(default_factory=list)


def field_dict() -> Any:
    return dataclasses.field(default_factory=dict)
