"""Research Code Mode.

Instead of exposing dozens of JSON-schema tools, the model receives a generated
Python SDK (``classics.search(...)``, ``kg.claims(...)``, ``analysis.concept_drift(...)``)
and writes a short program.  The harness validates the program's AST against a
whitelist, strips ``await``, runs it with a step budget, and routes every SDK
call through the tool scheduler — so permissions, hooks, budgets and the event
log apply exactly as for direct tool calls.

The AST whitelist is defence in depth, not a security boundary; untrusted models
should additionally run behind a process/container sandbox provider.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import sys
from contextlib import redirect_stdout
from typing import Any

from ...kernel.tools import ToolCall, ToolContext, ToolRegistry, ToolSpec

ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Return, ast.If, ast.For, ast.While,
    ast.Break, ast.Continue, ast.Pass, ast.Lambda, ast.Call, ast.Name, ast.Load, ast.Store, ast.Attribute,
    ast.Subscript, ast.Slice, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp, ast.DictComp,
    ast.SetComp, ast.GeneratorExp, ast.comprehension, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.JoinedStr, ast.FormattedValue, ast.keyword, ast.arguments, ast.arg, ast.Starred, ast.Await,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.And, ast.Or, ast.Not, ast.Eq,
    ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.USub, ast.UAdd,
)
SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in ("len", "range", "sorted", "sum", "min", "max", "abs", "round", "enumerate", "zip", "list", "dict",
                 "set", "tuple", "str", "int", "float", "bool", "any", "all", "map", "filter", "reversed", "isinstance")
}


class CodeModeError(RuntimeError):
    pass


class _StripAwait(ast.NodeTransformer):
    def visit_Await(self, node: ast.Await) -> Any:  # noqa: N802
        return self.visit(node.value)


def validate_code(code: str) -> ast.Module:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise CodeModeError(f"syntax error: {exc}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise CodeModeError(f"construct not allowed in Research Code Mode: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise CodeModeError(f"private names are not allowed: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise CodeModeError(f"private attributes are not allowed: {node.attr}")
    return tree


class _Namespace:
    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"<research sdk: {self._name}>"


def build_sdk(ctx: ToolContext, registry: ToolRegistry, calls: list[dict]) -> dict[str, Any]:
    sdk: dict[str, Any] = {}
    for spec in registry.list():
        if spec.name == "research.run_code":
            continue
        ns_name, fn_name = spec.name.split(".", 1)
        ns = sdk.setdefault(ns_name, _Namespace(ns_name))

        def make(tool_name: str):
            def fn(**kwargs: Any) -> Any:
                calls.append({"tool": tool_name, "arguments": kwargs})
                return ctx.call(tool_name, **kwargs)

            fn.__name__ = tool_name
            return fn

        setattr(ns, fn_name, make(spec.name))

    def batch(requests: list) -> list:
        """Run several SDK calls through the scheduler (parallel-safe ones run concurrently)."""
        tool_calls = [ToolCall(name, dict(args)) for name, args in requests]
        outcomes = ctx.scheduler.execute_batch(tool_calls, actor=ctx.actor, session=ctx.session, task_id=ctx.task_id,
                                               budget=ctx.budget, tx=ctx.tx)
        calls.extend({"tool": c.name, "arguments": c.arguments} for c in tool_calls)
        return [o.result if o.ok else {"error": o.error} for o in outcomes]

    sdk["batch"] = batch
    return sdk


def run_code(ctx: ToolContext, registry: ToolRegistry, code: str, *, max_steps: int = 200_000) -> dict[str, Any]:
    tree = _StripAwait().visit(validate_code(code))
    has_return = any(isinstance(n, ast.Return) for n in tree.body)
    if has_return:
        fn = ast.FunctionDef(name="_taochronos_main", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                             body=tree.body, decorator_list=[], returns=None)
        if "type_params" in ast.FunctionDef._fields:
            fn.type_params = []
        call = ast.Assign(targets=[ast.Name(id="result", ctx=ast.Store())], value=ast.Call(func=ast.Name(id="_taochronos_main", ctx=ast.Load()), args=[], keywords=[]))
        tree = ast.Module(body=[fn, call], type_ignores=[])
    ast.fix_missing_locations(tree)
    calls: list[dict] = []
    env: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS), **build_sdk(ctx, registry, calls)}
    steps = 0

    def tracer(frame, event, arg):  # noqa: ANN001
        nonlocal steps
        if frame.f_code.co_filename == "<research-code>":
            steps += 1
            if steps > max_steps:
                raise CodeModeError(f"step budget exceeded ({max_steps})")
        return tracer

    out = io.StringIO()
    previous = sys.gettrace()
    try:
        sys.settrace(tracer)
        with redirect_stdout(out):
            env["print"] = print
            exec(compile(tree, "<research-code>", "exec"), env)  # noqa: S102 — AST-validated
    finally:
        sys.settrace(previous)
    result = env.get("result")
    try:
        json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        result = str(result)
    return {"result": result, "stdout": out.getvalue()[-4000:], "tool_calls": calls, "steps": steps}


def sdk_reference(registry: ToolRegistry) -> str:
    """Generated SDK documentation handed to the model in Code Mode."""
    lines = ["# TaoChronos Research SDK (call tools as Python functions; assign the answer to `result` or `return` it)"]
    current = None
    for spec in registry.list():
        if spec.name == "research.run_code":
            continue
        ns, fn = spec.name.split(".", 1)
        if ns != current:
            lines.append(f"\n## {ns}")
            current = ns
        props = spec.input_schema.get("properties", {})
        required = set(spec.input_schema.get("required", []))
        params = ", ".join(f"{k}{'' if k in required else '=None'}" for k in props)
        lines.append(f"{ns}.{fn}({params})  # {spec.description}")
    lines.append("\nbatch([(\"classics.search\", {\"query\": ...}), ...])  # parallel-safe calls run concurrently")
    return "\n".join(lines)


def codemode_tool(registry: ToolRegistry) -> ToolSpec:
    return ToolSpec(
        name="research.run_code",
        description="Research Code Mode: run a short Python program against the TaoChronos Research SDK. " + sdk_reference(registry)[:1500],
        input_schema={"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
        fn=lambda ctx, a: run_code(ctx, registry, a["code"]),
        family="research",
        permission="codemode:exec",
        parallel_safe=False,
        expensive=True,
    )


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("sandbox", "codemode", {"run": run_code, "reference": sdk_reference}, default=True)
