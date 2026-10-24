"""JSON Schema export for protocol objects and a small dependency-free validator.

Schemas are generated from the dataclass type hints so the Python protocol is
the single source of truth; other runtimes (a TypeScript kernel, a web UI, an
MCP server) consume ``taochronos schema`` output.

The arguments a model writes for a tool are read at the model's side with three more functions: :func:`coerce`
repairs a value whose form differs from the schema's (a number written as text, a list wrapped as ``{"item": …}``),
never its meaning; :func:`signature` says what a tool takes; :func:`fit_arguments` puts them together, and refuses a
parameter the tool does not have, which would otherwise be ignored without a word.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import math
import re
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


# ------------------------------------------------------------------ a model's arguments
_INTEGER = re.compile(r"[+-]?[0-9]+(?:\.0*)?")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
# a text that lists several values (「消渴、口渴」) is not one value of a list: it is left for the model to write as a list
_LIST_MARKS = re.compile(r"[,，、;；\n]")
WRAPPER = "item"  # how some models' tool grammars write a list, or a value: {"item": […]}, {"item": "消渴"}
_NO = object()


def _matches(value: Any, types_: list[str]) -> bool:
    for t in types_:
        py = _JSON_TYPES.get(t)
        if py is None or (t in ("integer", "number") and isinstance(value, bool)):
            continue
        if isinstance(value, py):
            return True
    return False


def _show(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text if len(text) <= 60 else text[:59] + "…"


def _unwrap(value: Any) -> Any:
    return value[WRAPPER] if isinstance(value, dict) and len(value) == 1 and WRAPPER in value else value


def _as(value: Any, t: str) -> Any:
    """``value`` written as JSON type ``t``, where only its form differs from it; ``_NO`` where more than its form does."""
    if t == "array":
        inner = _unwrap(value)
        if inner is not value:
            return inner if isinstance(inner, list) else [inner]
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except ValueError:
                    return _NO
                return parsed if isinstance(parsed, list) else _NO
            return [value] if text and not _LIST_MARKS.search(text) else _NO
        return [value] if isinstance(value, (int, float)) and not isinstance(value, bool) else _NO
    if t == "object":
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                parsed = json.loads(value)
            except ValueError:
                return _NO
            return parsed if isinstance(parsed, dict) else _NO
        return _NO
    inner = _unwrap(value)  # one value, written inside {"item": …} or as a list of one
    if isinstance(inner, list) and len(inner) == 1:
        inner = inner[0]
    if isinstance(inner, (dict, list)) or inner is None:
        return _NO
    text = inner.strip() if isinstance(inner, str) else None
    if t == "integer":
        if isinstance(inner, bool):
            return _NO
        if isinstance(inner, int):
            return inner
        if isinstance(inner, float):
            return int(inner) if math.isfinite(inner) and inner.is_integer() else _NO
        return int(float(text)) if text is not None and _INTEGER.fullmatch(text) else _NO
    if t == "number":
        if isinstance(inner, bool):
            return _NO
        if isinstance(inner, (int, float)):
            return inner
        if text is None or not _NUMBER.fullmatch(text) or not math.isfinite(float(text)):
            return _NO
        return int(float(text)) if _INTEGER.fullmatch(text) else float(text)
    if t == "boolean":
        if isinstance(inner, bool):
            return inner
        return text.lower() == "true" if text is not None and text.lower() in ("true", "false") else _NO
    if t == "string":
        if isinstance(inner, str):
            return inner
        if isinstance(inner, bool):
            return _NO
        if isinstance(inner, int):
            return str(inner)
        return str(int(inner)) if inner.is_integer() else repr(inner)
    return _NO


def _enum(value: Any, schema: dict[str, Any], path: str, repairs: list[str]) -> Any:
    """An enumerated word written in another case (``"OFF"`` for ``off``)."""
    members = schema.get("enum")
    if not isinstance(value, str) or not isinstance(members, list) or value in members:
        return value
    same = [m for m in members if isinstance(m, str) and m.casefold() == value.strip().casefold()]
    if len(same) != 1:
        return value
    repairs.append(f"{path}: {_show(value)} → {_show(same[0])}")
    return same[0]


def _inner(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str, repairs: list[str]) -> Any:
    """``value`` with its properties or items coerced (the same object when none changes)."""
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        extra = schema.get("additionalProperties")
        out = None
        for key, item in value.items():
            sub = props[key] if key in props else extra if isinstance(extra, dict) else None
            if sub is None:
                continue
            fixed = _coerce(item, sub, root, f"{path}.{key}", repairs)
            if fixed is not item:
                out = dict(value) if out is None else out
                out[key] = fixed
        return value if out is None else out
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        out = None
        for i, item in enumerate(value):
            fixed = _coerce(item, schema["items"], root, f"{path}[{i}]", repairs)
            if fixed is not item:
                out = list(value) if out is None else out
                out[i] = fixed
        return value if out is None else out
    return value


def _coerce(value: Any, schema: Any, root: dict[str, Any], path: str, repairs: list[str]) -> Any:
    if not isinstance(schema, dict):
        return value
    if "$ref" in schema:
        target = root.get("$defs", {}).get(schema["$ref"].split("/")[-1])
        return value if target is None else _coerce(value, target, root, path, repairs)
    if "anyOf" in schema:
        if any(not validate(value, s, root=root, path=path) for s in schema["anyOf"]):
            return value
        for branch in schema["anyOf"]:
            found: list[str] = []
            fixed = _coerce(value, branch, root, path, found)
            if fixed is not value and not validate(fixed, branch, root=root, path=path):
                repairs.extend(found)
                return fixed
        return value
    expected = schema.get("type")
    types_ = [expected] if isinstance(expected, str) else [t for t in expected or [] if isinstance(t, str)]
    if types_ and not _matches(value, types_):
        for t in types_:
            fixed = _as(value, t)
            if fixed is _NO:
                continue
            found = []
            fixed = _enum(_inner(fixed, schema, root, path, found), schema, path, found)
            if not validate(fixed, schema, root=root, path=path):
                repairs.append(f"{path}: {_show(value)} → {_show(fixed)}")
                repairs.extend(r for r in found if not r.startswith(f"{path}: "))
                return fixed
        return value
    return _enum(_inner(value, schema, root, path, repairs), schema, path, repairs)


def coerce(instance: Any, schema: dict[str, Any], *, root: dict[str, Any] | None = None) -> tuple[Any, list[str]]:
    """``instance`` in the form ``schema`` declares where only its form differs — and what was repaired, one line a value
    (``$.limit: "40" → 40``).  The meaning is never changed: repaired are a number or a boolean written as text, a whole
    float where an integer is expected and a number where a string is, a list or an object written as JSON text, a list
    or a value wrapped as ``{"item": …}``, one value where a list of them is expected (a text without list marks:
    「消渴」, not 「消渴、口渴」), a list of one value where that value is, an enumerated word in another case.  A repair is
    made only where it makes that value valid; whatever else is wrong is left as it is (the same object when nothing
    changes), for :func:`validate` to report."""
    repairs: list[str] = []
    return _coerce(instance, schema, root or schema, "$", repairs), repairs


def _label(schema: Any, root: dict[str, Any]) -> str:
    if not isinstance(schema, dict):
        return "any"
    if "$ref" in schema:
        target = root.get("$defs", {}).get(schema["$ref"].split("/")[-1])
        return _label(target, root) if target is not None else "any"
    if "anyOf" in schema:
        return " or ".join(dict.fromkeys(_label(s, root) for s in schema["anyOf"]))
    t = schema.get("type")
    if isinstance(t, list):
        label = " or ".join(str(x) for x in t)
    elif t == "array":
        label = f"list of {_label(schema['items'], root)}" if isinstance(schema.get("items"), dict) else "list"
    else:
        label = str(t or "any")
    members = schema.get("enum")
    if isinstance(members, list) and members:
        shown = " | ".join(m if isinstance(m, str) else json.dumps(m) for m in members[:6])
        label += f": {shown}" + (" | …" if len(members) > 6 else "")
    return label


def signature(schema: dict[str, Any], *, root: dict[str, Any] | None = None, limit: int = 14) -> str:
    """What an object schema takes, as a model reads it in an error — the required parameters first, then the others in
    their order: ``passage_id (string, required); k (integer); aliases (string: auto | off)``."""
    root = root or schema
    props = schema.get("properties") or {}
    required = [k for k in schema.get("required") or [] if k in props]
    names = required + [k for k in props if k not in required]
    if not names:
        return "no parameters"
    parts = [f"{k} ({_label(props[k], root)}{', required' if k in required else ''})" for k in names[:limit]]
    if len(names) > limit:
        parts.append(f"… {len(names) - limit} more")
    return "; ".join(parts)


def unknown_properties(instance: Any, schema: dict[str, Any]) -> list[str]:
    """The keys of ``instance`` that an object schema naming its properties does not name (and takes no others)."""
    props = schema.get("properties")
    if not isinstance(instance, dict) or not isinstance(props, dict) or schema.get("additionalProperties") not in (None, False):
        return []
    return [k for k in instance if k not in props]


def fit_arguments(arguments: Any, schema: dict[str, Any], *, tool: str) -> tuple[dict[str, Any], list[str], str | None]:
    """A model's arguments for ``tool``: repaired where only their form was wrong (:func:`coerce`), what was repaired, and
    the error to send back where they still do not fit — what :func:`validate` finds, then the parameters the tool does
    not have (a call would ignore them, and the model read an answer to a question it did not ask) — followed by what
    the tool takes (:func:`signature`), so that the model can correct the call in one step."""
    if not isinstance(arguments, dict):
        kind = "list" if isinstance(arguments, list) else "str" if isinstance(arguments, str) else type(arguments).__name__
        return {}, [], f"invalid arguments: $: expected object, got {kind} · {tool} takes: {signature(schema)}"
    fixed, repairs = coerce(arguments, schema)
    errors = validate(fixed, schema) + [f"$: unknown parameter '{k}'" for k in unknown_properties(fixed, schema)]
    if not errors:
        return fixed, repairs, None
    return fixed, repairs, f"invalid arguments: {'; '.join(errors[:5])} · {tool} takes: {signature(schema)}"
