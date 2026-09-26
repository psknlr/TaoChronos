"""Tool registry and the bounded-parallel tool scheduler.

Consecutive ``parallel_safe`` calls run concurrently; an ``exclusive`` (or
non-parallel-safe) call forms a barrier and runs alone.  Every call passes the
same gauntlet: permission → budget → BeforeToolCall hooks → execution → events
→ AfterToolCall hooks.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from ..protocol.base import stable_id, to_jsonable
from ..protocol.events import EventType
from ..protocol.schema import validate
from .budget import Budget, BudgetExceeded
from .hooks import HookContext, HookPoint, HookRegistry
from .policy import Actor, PolicyEngine


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[["ToolContext", dict[str, Any]], Any]
    family: str = "general"
    permission: str = "research:read"
    read_only: bool = True
    parallel_safe: bool = True
    exclusive: bool = False
    expensive: bool = False
    irreversible: bool = False
    cost: float = 0.0
    returns: str = ""

    @property
    def llm_name(self) -> str:
        """Provider-safe name (dots are not allowed in most tool-name grammars)."""
        return self.name.replace(".", "__")

    def to_llm_schema(self) -> dict[str, Any]:
        desc = self.description + (f" Returns: {self.returns}" if self.returns else "")
        return {"name": self.llm_name, "description": desc, "input_schema": self.input_schema}

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family,
            "permission": self.permission,
            "read_only": self.read_only,
            "parallel_safe": self.parallel_safe and not self.exclusive,
            "exclusive": self.exclusive,
            "expensive": self.expensive,
            "irreversible": self.irreversible,
        }


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass
class ToolOutcome:
    call_id: str
    name: str
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0

    def as_text(self, limit: int = 12000) -> str:
        if not self.ok:
            return f"ERROR: {self.error}"
        text = json.dumps(to_jsonable(self.result), ensure_ascii=False, default=str)
        return text if len(text) <= limit else text[:limit] + f"… [truncated {len(text) - limit} chars]"


@dataclass
class ToolContext:
    """What a tool function can see: never the model, always the harness services."""

    actor: Actor
    capabilities: Any
    scheduler: "ToolScheduler"
    session: Any = None
    task_id: str | None = None
    budget: Budget | None = None
    services: dict[str, Any] = field(default_factory=dict)
    tx: Any = None  # the calling agent's transaction, if any

    def cap(self, capability: str, name: str | None = None) -> Any:
        return self.capabilities.get(capability, name)

    def emit(self, type_: Any, payload: dict[str, Any], *, generated: list[str] | None = None) -> Any:
        """Write tools emit through the agent transaction when there is one (atomic with the task)."""
        if self.tx is not None:
            return self.tx.emit(type_, payload, actor=self.actor.id, generated=generated or [])
        if self.session is not None:
            return self.session.emit(type_, payload, actor=self.actor.id, task_id=self.task_id, generated=generated or [])
        return None

    def call(self, name: str, /, **arguments: Any) -> Any:
        """Nested tool call through the same scheduler (permissions and hooks still apply)."""
        outcome = self.scheduler.execute(
            ToolCall(name, arguments), actor=self.actor, session=self.session, task_id=self.task_id, budget=self.budget, tx=self.tx
        )
        if not outcome.ok:
            raise RuntimeError(outcome.error)
        return outcome.result


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name} already registered")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        spec = self._tools.get(name) or self._tools.get(name.replace("__", "."))
        if spec is None:
            raise KeyError(f"unknown tool: {name}")
        return spec

    def has(self, name: str) -> bool:
        return name in self._tools or name.replace("__", ".") in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def list(self, names: list[str] | None = None, family: str | None = None) -> list[ToolSpec]:
        specs = [self._tools[n] for n in sorted(self._tools)]
        if names is not None:
            wanted = set(names)
            specs = [s for s in specs if s.name in wanted or any(s.name.startswith(w.rstrip("*")) for w in wanted if w.endswith("*"))]
        if family:
            specs = [s for s in specs if s.family == family]
        return specs


class ToolScheduler:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        hooks: HookRegistry,
        capabilities: Any,
        max_workers: int = 4,
        services: dict[str, Any] | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.hooks = hooks
        self.capabilities = capabilities
        self.max_workers = max_workers
        self.services = services or {}

    # ------------------------------------------------------------- planning
    def plan_batches(self, calls: list[ToolCall]) -> list[list[int]]:
        """Group call indices: runs of parallel-safe calls share a batch; exclusive calls are barriers."""
        batches: list[list[int]] = []
        parallel_open = False
        for i, call in enumerate(calls):
            try:
                spec = self.registry.get(call.name)
                safe = spec.parallel_safe and not spec.exclusive
            except KeyError:
                safe = True  # unknown tools fail fast inside their own slot
            if safe and parallel_open:
                batches[-1].append(i)
            else:
                batches.append([i])
            parallel_open = safe
        return batches

    # ------------------------------------------------------------ execution
    def execute_batch(
        self,
        calls: list[ToolCall],
        *,
        actor: Actor,
        session: Any = None,
        task_id: str | None = None,
        budget: Budget | None = None,
        tx: Any = None,
    ) -> list[ToolOutcome]:
        outcomes: list[ToolOutcome | None] = [None] * len(calls)
        for batch in self.plan_batches(calls):
            if len(batch) == 1:
                i = batch[0]
                outcomes[i] = self.execute(calls[i], actor=actor, session=session, task_id=task_id, budget=budget, tx=tx)
                continue
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(batch))) as pool:
                futures = {
                    i: pool.submit(self.execute, calls[i], actor=actor, session=session, task_id=task_id, budget=budget, tx=tx)
                    for i in batch
                }
                for i, fut in futures.items():
                    outcomes[i] = fut.result()
        return [o for o in outcomes if o is not None]

    def execute(
        self,
        call: ToolCall,
        *,
        actor: Actor,
        session: Any = None,
        task_id: str | None = None,
        budget: Budget | None = None,
        tx: Any = None,
    ) -> ToolOutcome:
        call_id = call.id or stable_id("call", call.name, call.arguments, actor.id, task_id)
        try:
            spec = self.registry.get(call.name)
        except KeyError as exc:
            return ToolOutcome(call_id, call.name, False, error=str(exc))

        def emit(type_: EventType, payload: dict[str, Any]) -> None:
            if session is not None:
                session.emit(type_, payload, actor=actor.id, task_id=task_id)

        if not self.policy.allowed(actor, spec.permission):
            reason = f"{actor.id} lacks permission '{spec.permission}' for tool {spec.name}"
            emit(EventType.TOOL_DENIED, {"tool": spec.name, "reason": reason})
            return ToolOutcome(call_id, spec.name, False, error=reason)

        arguments = dict(call.arguments or {})
        errors = validate(arguments, spec.input_schema)
        if errors:
            return ToolOutcome(call_id, spec.name, False, error="invalid arguments: " + "; ".join(errors[:5]))

        if budget is not None:
            try:
                budget.charge(tool_calls=1, cost_usd=spec.cost)
            except BudgetExceeded as exc:
                emit(EventType.BUDGET_EXCEEDED, {"budget": exc.budget, "kind": exc.kind, "limit": exc.limit})
                return ToolOutcome(call_id, spec.name, False, error=str(exc))

        before = self.hooks.run(
            HookContext(HookPoint.BEFORE_TOOL_CALL, subject=arguments, actor=actor, session=session, data={"tool": spec})
        )
        if not before.allow:
            emit(EventType.HOOK_BLOCKED, {"hook": before.hook, "point": "BeforeToolCall", "reason": before.reason, "tool": spec.name})
            return ToolOutcome(call_id, spec.name, False, error=f"blocked by hook {before.hook}: {before.reason}")
        if isinstance(before.subject, dict):
            arguments = before.subject

        emit(EventType.TOOL_CALLED, {"tool": spec.name, "call_id": call_id, "arguments": _preview(arguments)})
        ctx = ToolContext(
            actor=actor,
            capabilities=self.capabilities,
            scheduler=self,
            session=session,
            task_id=task_id,
            budget=budget,
            services=self.services,
            tx=tx,
        )
        started = time.perf_counter()
        try:
            result = spec.fn(ctx, arguments)
            outcome = ToolOutcome(call_id, spec.name, True, result=result)
        except Exception as exc:  # tool failures are data, not crashes
            outcome = ToolOutcome(call_id, spec.name, False, error=f"{type(exc).__name__}: {exc}")
        outcome.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        emit(
            EventType.TOOL_RESULT,
            {
                "tool": spec.name,
                "call_id": call_id,
                "ok": outcome.ok,
                "duration_ms": outcome.duration_ms,
                "summary": _summary(outcome),
            },
        )
        self.hooks.run(
            HookContext(HookPoint.AFTER_TOOL_CALL, subject=outcome, actor=actor, session=session, data={"tool": spec})
        )
        return outcome


def _preview(arguments: dict[str, Any], limit: int = 400) -> dict[str, Any]:
    text = json.dumps(to_jsonable(arguments), ensure_ascii=False, default=str)
    return arguments if len(text) <= limit else {"_preview": text[:limit] + "…"}


def _summary(outcome: ToolOutcome) -> str:
    if not outcome.ok:
        return (outcome.error or "")[:300]
    result = outcome.result
    if isinstance(result, list):
        return f"{len(result)} items"
    if isinstance(result, dict):
        return "keys: " + ", ".join(list(result)[:8])
    return str(result)[:200]
