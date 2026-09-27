"""Research Code Mode.

Instead of exposing dozens of JSON-schema tools, the model receives a generated
Python SDK (``classics.search(...)``, ``kg.claims(...)``, ``analysis.concept_drift(...)``)
and writes a short program.  The harness validates the program's AST against a
whitelist, strips ``await``, runs it with a step budget, and routes every SDK
call through the tool scheduler — so permissions, hooks, budgets and the event
log apply exactly as for direct tool calls.

The program is model-written, so it is **not run in the harness process**: it runs in the namespace-tier sandbox
(:mod:`.isolation` — read-only system, the session workspace the only writable place, no network, no credentials, no
capability over its mounts).  Its only channel out is a line-based RPC on stdin/stdout: each SDK call is sent to the
harness, which executes it through the tool scheduler (permissions, hooks, budgets, receipts, the event log) under the
calling agent's identity and sends the result back.  The AST whitelist, the restricted builtins and the step budget
remain, as defence in depth.  Where no isolating tier exists, Code Mode refuses to run — unless a profile explicitly
sets ``codemode_isolation: in_process`` for models it trusts.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import sys
import threading
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from ...kernel.tools import ToolCall, ToolContext, ToolRegistry, ToolSpec
from ...protocol.base import to_jsonable
from .isolation import ISOLATES, Launcher, SandboxUnavailable, Watchdog

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


_RPC_BOOT = r"""
import io, json, sys
_in, _out = sys.stdin, sys.__stdout__
payload = json.loads(_in.readline())
def _rpc(message):
    _out.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
    _out.flush()
    reply = json.loads(_in.readline())
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error") or "tool call failed")
    return reply.get("result")
class _NS:
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return "<research sdk: " + self.name + ">"
sdk = {}
for name in payload["tools"]:
    ns, fn = name.split(".", 1)
    obj = sdk.setdefault(ns, _NS(ns))
    setattr(obj, fn, (lambda n: (lambda **kw: _rpc({"call": n, "arguments": kw})))(name))
sdk["batch"] = lambda requests: _rpc({"batch": [[n, a] for n, a in requests]})
_b = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
buf = io.StringIO()
safe = {k: _b[k] for k in payload["builtins"] if k in _b}
safe["print"] = lambda *a, **k: print(*a, file=buf, **{x: y for x, y in k.items() if x in ("sep", "end")})
env = {"__builtins__": safe, **sdk}
steps = [0]
limit = payload["max_steps"]
def _trace(frame, event, arg):
    if frame.f_code.co_filename == "<research-code>":
        steps[0] += 1
        if steps[0] > limit:
            raise RuntimeError("step budget exceeded")
    return _trace
sys.settrace(_trace)
error = None
try:
    exec(compile(payload["code"], "<research-code>", "exec"), env)
except BaseException as e:
    error = type(e).__name__ + ": " + str(e)
sys.settrace(None)
_out.write(json.dumps({"done": True, "result": env.get("result"), "stdout": buf.getvalue()[-4000:], "steps": steps[0],
                       "error": error}, ensure_ascii=False, default=str) + "\n")
_out.flush()
"""


def _prepare(code: str) -> ast.Module:
    tree = _StripAwait().visit(validate_code(code))
    has_return = any(isinstance(n, ast.Return) for n in tree.body)
    if has_return:
        fn = ast.FunctionDef(name="taochronos_main", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                             body=tree.body, decorator_list=[], returns=None)
        if "type_params" in ast.FunctionDef._fields:
            fn.type_params = []
        call = ast.Assign(targets=[ast.Name(id="result", ctx=ast.Store())], value=ast.Call(func=ast.Name(id="taochronos_main", ctx=ast.Load()), args=[], keywords=[]))
        tree = ast.Module(body=[fn, call], type_ignores=[])
    ast.fix_missing_locations(tree)
    return tree


def run_code_isolated(ctx: ToolContext, registry: ToolRegistry, code: str, *, tier: str = "namespace", workspace: Path | None = None,
                      max_steps: int = 200_000, max_calls: int = 200, timeout: float = 120.0) -> dict[str, Any]:
    """Run a Code Mode program in an isolated child; its SDK calls come back here and go through the scheduler."""
    source = ast.unparse(_prepare(code))
    launcher = Launcher(tier)
    if not launcher.available():
        raise SandboxUnavailable(f"Code Mode runs model-written code at the {tier} tier, which is not available here")
    names = sorted(s.name for s in registry.list() if s.name != "research.run_code")
    allowed = set(names)
    base = Path(workspace) if workspace is not None else Path(".taochronos") / "sessions" / "adhoc" / "workspace"
    (base / "tmp").mkdir(parents=True, exist_ok=True)
    proc = launcher.spawn(_RPC_BOOT, base)
    errors: list[str] = []
    drain = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    drain.start()
    dog = Watchdog(proc, timeout)
    calls: list[dict] = []
    done: dict[str, Any] = {}

    def reply(message: dict[str, Any]) -> None:
        proc.stdin.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
        proc.stdin.flush()

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in allowed:
            return {"ok": False, "error": f"unknown tool {name}"}
        if len(calls) >= max_calls:
            return {"ok": False, "error": f"tool-call budget exceeded ({max_calls})"}
        calls.append({"tool": name, "arguments": arguments})
        outcome = ctx.scheduler.execute(ToolCall(name, dict(arguments)), actor=ctx.actor, session=ctx.session, task_id=ctx.task_id,
                                        budget=ctx.budget, tx=ctx.tx)
        return {"ok": outcome.ok, "result": to_jsonable(outcome.result), "error": outcome.error}

    try:
        reply({"code": source, "tools": names, "builtins": sorted(SAFE_BUILTINS), "max_steps": max_steps})
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("done"):
                done = msg
                break
            if "call" in msg:
                reply(call(str(msg["call"]), dict(msg.get("arguments") or {})))
            elif "batch" in msg:
                results = [call(str(n), dict(a or {})) for n, a in msg["batch"]]
                reply({"ok": True, "result": [r["result"] if r["ok"] else {"error": r["error"]} for r in results]})
    except (BrokenPipeError, OSError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        dog.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        drain.join(timeout=2)
    if dog.fired:
        raise CodeModeError(f"time limit exceeded ({timeout}s)")
    if not done:
        raise CodeModeError("the sandboxed program ended without a result: " + "".join(errors)[-400:])
    if done.get("error"):
        raise CodeModeError(done["error"])
    return {"result": done.get("result"), "stdout": done.get("stdout", ""), "tool_calls": calls, "steps": done.get("steps", 0),
            "tier": tier, "isolates": ISOLATES[tier]}


def run_code(ctx: ToolContext, registry: ToolRegistry, code: str, *, max_steps: int = 200_000,
             isolation: str = "namespace", workspace_root: Path | None = None) -> dict[str, Any]:
    """Run a Code Mode program: isolated by default; ``in_process`` only when a profile says so explicitly."""
    if isolation != "in_process":
        sid = getattr(getattr(ctx, "session", None), "id", None) or "adhoc"
        workspace = Path(workspace_root) / sid / "workspace" if workspace_root is not None else None
        return run_code_isolated(ctx, registry, code, tier=isolation, max_steps=max_steps, workspace=workspace)
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
    return {"result": result, "stdout": out.getvalue()[-4000:], "tool_calls": calls, "steps": steps, "tier": "in_process",
            "isolates": ISOLATES["in_process"]}


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


def codemode_tool(registry: ToolRegistry, *, isolation: str = "namespace", workspace_root: Path | None = None) -> ToolSpec:
    return ToolSpec(
        name="research.run_code",
        description="Research Code Mode: run a short Python program against the TaoChronos Research SDK. " + sdk_reference(registry)[:1500],
        input_schema={"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
        fn=lambda ctx, a: run_code(ctx, registry, a["code"], isolation=isolation, workspace_root=workspace_root),
        family="research",
        permission="codemode:exec",
        parallel_safe=False,
        expensive=True,
    )


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    registry.register("sandbox", "codemode", {"run": run_code, "reference": sdk_reference}, default=True)
