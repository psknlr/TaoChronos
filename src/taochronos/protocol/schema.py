"""JSON Schema export for protocol objects and a small dependency-free validator.

Schemas are generated from the dataclass type hints so the Python protocol is
the single source of truth; other runtimes (a TypeScript kernel, a web UI, an
MCP server) consume ``taochronos schema`` output.
"""

from __future__ import annotations

import dataclasses
import enum
import types
import typing
from typing import Any, Union, get_args, get_origin

from .base import _hints


def _is_union(tp: Any) -> bool:
    origin = get_origin(tp)
    return origin is Union or origin is types.UnionType


def type_schema(tp: Any, defs: dict[str, Any]) -> dict[str, Any]:
    if tp is Any:
        return {}
    if _is_union(tp):
        options = [a for a in get_args(tp)]
        nullable = type(None) in options
        options = [a for a in options if a is not type(None)]
        if len(options) == 1:
            inner = type_schema(options[0], defs)
            return {"anyOf": [inner, {"type": "null"}]} if nullable else inner
        schemas = [type_schema(o, defs) for o in options]
        if nullable:
            schemas.append({"type": "null"})
        return {"anyOf": schemas}
    origin = get_origin(tp)
    if origin is typing.Literal:
        return {"enum": list(get_args(tp))}
    if origin in (list, set, frozenset, tuple):
        args = get_args(tp)
        return {"type": "array", "items": type_schema(args[0], defs) if args else {}}
    if origin is dict:
        args = get_args(tp)
        return {"type": "object", "additionalProperties": type_schema(args[1], defs) if len(args) == 2 else {}}
    if tp is dict:
        return {"type": "object"}
    if tp is list:
        return {"type": "array"}
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            name = tp.__name__
            if name not in defs:
                defs[name] = {}  # placeholder breaks recursion
                defs[name] = dataclass_schema(tp, defs)
            return {"$ref": f"#/$defs/{name}"}
        if issubclass(tp, enum.Enum):
            return {"type": "string", "enum": [m.value for m in tp]}
        if tp is bool:
            return {"type": "boolean"}
        if tp is int:
            return {"type": "integer"}
        if tp is float:
            return {"type": "number"}
        if tp is str:
            return {"type": "string"}
    return {}


def dataclass_schema(cls: type, defs: dict[str, Any]) -> dict[str, Any]:
    hints = _hints(cls)
    props: dict[str, Any] = {}
    required: list[str] = []
    for f in dataclasses.fields(cls):
        props[f.name] = type_schema(hints.get(f.name, Any), defs)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:  # type: ignore[misc]
            required.append(f.name)
    schema: dict[str, Any] = {"type": "object", "title": cls.__name__, "properties": props}
    if cls.__doc__:
        schema["description"] = " ".join(cls.__doc__.split())
    if required:
        schema["required"] = required
    return schema


def schema_for(cls: type) -> dict[str, Any]:
    defs: dict[str, Any] = {}
    root = type_schema(cls, defs)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **root, "$defs": defs}


def bundle_schema(classes: list[type]) -> dict[str, Any]:
    defs: dict[str, Any] = {}
    for cls in classes:
        type_schema(cls, defs)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": defs}


_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate(instance: Any, schema: dict[str, Any], *, root: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    """Validate against the subset of JSON Schema used by TaoChronos. Returns error strings."""
    root = root or schema
    errors: list[str] = []
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        target = root.get("$defs", {}).get(name)
        if target is None:
            return [f"{path}: unresolved $ref {schema['$ref']}"]
        return validate(instance, target, root=root, path=path)
    if "anyOf" in schema:
        branches = [validate(instance, s, root=root, path=path) for s in schema["anyOf"]]
        if all(branches):
            return [f"{path}: no anyOf branch matched ({branches[0][0] if branches[0] else ''})"]
        return []
    expected = schema.get("type")
    if expected:
        types_ = expected if isinstance(expected, list) else [expected]
        ok = False
        for t in types_:
            py = _JSON_TYPES.get(t)
            if py is None:
                continue
            if t in ("integer", "number") and isinstance(instance, bool):
                continue
            if isinstance(instance, py):
                ok = True
                break
        if not ok:
            return [f"{path}: expected {expected}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property '{key}'")
        for key, value in instance.items():
            if key in props:
                errors.extend(validate(value, props[key], root=root, path=f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{key}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate(value, schema["additionalProperties"], root=root, path=f"{path}.{key}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], root=root, path=f"{path}[{i}]"))
    return errors
