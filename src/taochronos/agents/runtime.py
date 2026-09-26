"""Agent runtime: spawn → route → (procedure | LLM tool loop | hybrid | subagent) → verify → commit.

One task runs one agent instance.  Everything the agent writes goes through a
transaction that commits atomically *together with* ``TaskCompleted``, so a
crash never leaves half a task on the blackboard.  Tool calls pass the same
permission / budget / hook gauntlet whether a model or a deterministic
procedure makes them.  Model output is untrusted: it must validate against the
role's output schema and then survives the role's commit checks (verbatim
quotes, spans, sense ids, anachronism guard) or it is dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..capabilities.llm import LLMError, LLMRequest, Message, ToolResultBlock, ToolSchema
from ..kernel.budget import Budget, BudgetExceeded
from ..kernel.context import ContextManager
from ..kernel.hooks import HookContext, HookPoint, HookRegistry, HookResult
from ..kernel.policy import Actor, PolicyEngine
from ..kernel.store import SimulatedCrash
from ..kernel.tools import ToolCall, ToolOutcome, ToolRegistry, ToolScheduler, ToolSpec
from ..protocol.base import stable_id
from ..protocol.events import EventType
from ..protocol.research import AgentInstance, Decision, TaskNode
from ..protocol.schema import validate
from .context_views import ViewInput, build_sections
from .prompts import output_instructions, system_prompt
from .router import CognitiveRouter, RouteDecision
from .schemas import output_schema
from .spec import AgentSpec, load_procedure


class AgentError(RuntimeError):
    pass


class AgentRefused(AgentError):
    pass


class ToolError(RuntimeError):
    pass


@dataclass
class TaskResult:
    task_id: str
    role: str
    agent_id: str
    status: str  # done | failed | skipped
    summary: str = ""
    outputs: list[str] = field(default_factory=list)
    route: RouteDecision | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    fallback: str | None = None
    pending: Any = None  # an uncommitted transaction when run with defer_commit=True

    def commit(self) -> None:
        if self.pending is not None:
            self.pending.commit()
            self.pending = None


def parse_json_output(text: str, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None, "no JSON object found"
    try:
        data = json.loads(body[start: end + 1])
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    errors = validate(data, schema)
    if errors:
        return None, "; ".join(errors[:6])
    return data, None


class AgentContext:
    """What an agent's procedure (and commit logic) can see and do."""

    def __init__(self, runtime: "AgentRuntime", session: Any, task: TaskNode, spec: AgentSpec, route: RouteDecision,
                 actor: Actor, tx: Any, budget: Budget) -> None:
        self.runtime = runtime
        self.session = session
        self.task = task
        self.spec = spec
        self.route = route
        self.actor = actor
        self.tx = tx
        self.budget = budget
        self.generated: list[str] = []
        self.notes: list[str] = []
        self.usage: dict[str, Any] = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "tool_calls": 0}
        self.draft: dict[str, Any] | None = None
        self._spawned = 0

    # ------------------------------------------------------------- reading
    @property
    def state(self) -> Any:
        return self.session.state

    @property
    def goal(self) -> Any:
        return self.session.state.goal

    @property
    def inputs(self) -> dict[str, Any]:
        return self.task.inputs

    @property
    def config(self) -> dict[str, Any]:
        return {**self.runtime.config, **self.spec.config}

    @property
    def services(self) -> dict[str, Any]:
        return self.runtime.scheduler.services

    def cap(self, capability: str, name: str | None = None) -> Any:
        return self.runtime.capabilities.get(capability, name)

    def has_cap(self, capability: str, name: str | None = None) -> bool:
        return self.runtime.capabilities.has(capability, name)

    def gates(self) -> Any:
        factory = self.services.get("gates")
        if factory is None:
            raise AgentError("no gate evaluator configured")
        return factory(self.state)

    # --------------------------------------------------------------- tools
    def try_tool(self, name: str, /, **arguments: Any) -> ToolOutcome:
        self.usage["tool_calls"] += 1
        return self.runtime.scheduler.execute(ToolCall(name, arguments), actor=self.actor, session=self.session,
                                              task_id=self.task.id, budget=self.budget, tx=self.tx)

    def tool(self, name: str, /, **arguments: Any) -> Any:
        outcome = self.try_tool(name, **arguments)
        if not outcome.ok:
            raise ToolError(f"{name}: {outcome.error}")
        return outcome.result

    # --------------------------------------------------------------- writing
    def emit(self, type_: EventType, payload: dict[str, Any], *, generated: list[str] | None = None,
             used: list[str] | None = None) -> Any:
        event = self.tx.emit(type_, payload, generated=generated or [], used=used or [])
        self.generated.extend(g for g in (generated or []) if g not in self.generated)
        return event

    def hook(self, point: HookPoint, subject: Any, data: dict[str, Any] | None = None, subject_id: str = "") -> HookResult:
        result = self.runtime.hooks.run(HookContext(point, subject=subject, actor=self.actor, session=self.session, data=data or {}))
        if not result.allow:
            self.session.emit(EventType.HOOK_BLOCKED, {"hook": result.hook, "point": point.value, "reason": result.reason,
                                                       "subject": subject_id}, actor=self.actor.id, task_id=self.task.id)
        return result

    def note(self, text: str) -> None:
        self.notes.append(text)

    # ------------------------------------------------------------- subagents
    def spawn(self, role: str, kind: str, inputs: dict[str, Any] | None = None) -> TaskResult:
        """Dynamically spawn a subagent task (planned, attributed and committed on its own)."""
        self._spawned += 1
        child = TaskNode(id=f"{self.task.id}/{kind}.{self._spawned}", kind=kind, role=role, round=self.task.round,
                         inputs={**(inputs or {}), "parent_task": self.task.id, "parent_agent": self.actor.id},
                         priority=self.task.priority)
        existing = self.state.task_graph.get(child.id)
        if existing is not None and existing.status == "done":
            return TaskResult(child.id, role, "", "done", existing.summary, list(existing.outputs))
        if existing is None:
            self.session.emit(EventType.TASK_PLANNED, {"tasks": [child.to_dict()]}, actor=self.actor.id, task_id=self.task.id)
        provider = self.runtime.subagents.get("local")
        if provider is None:
            return self.runtime.run_task(self.session, child, budget=self.budget)
        return provider.run_task(self.runtime, self.session, child, budget=self.budget)


class AgentRuntime:
    def __init__(
        self,
        *,
        capabilities: Any,
        tools: ToolRegistry,
        scheduler: ToolScheduler,
        policy: PolicyEngine,
        hooks: HookRegistry,
        specs: dict[str, AgentSpec],
        router: CognitiveRouter,
        context: ContextManager | None = None,
        memory: Any = None,
        skills: Any = None,
        subagents: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        codemode: ToolSpec | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.tools = tools
        self.scheduler = scheduler
        self.policy = policy
        self.hooks = hooks
        self.specs = specs
        self.router = router
        self.context = context or ContextManager()
        self.memory = memory
        self.skills = skills
        self.subagents = subagents or {}
        self.config = config or {}
        self.codemode = codemode

    def spec(self, role: str) -> AgentSpec:
        try:
            return self.specs[role]
        except KeyError:
            raise AgentError(f"no AgentSpec for role {role!r}") from None

    # ------------------------------------------------------------------ run
    def run_task(self, session: Any, task: TaskNode, *, budget: Budget | None = None, defer_commit: bool = False) -> TaskResult:
        spec = self.spec(task.role)
        module = load_procedure(spec.procedure) if spec.procedure else None
        actor = spec.actor(task.id)
        if budget is not None:
            try:
                budget.charge(agents=1)
            except BudgetExceeded as exc:
                session.emit(EventType.TASK_SKIPPED, {"task_id": task.id, "reason": f"budget: {exc}"}, task_id=task.id)
                return TaskResult(task.id, spec.role, actor.id, "skipped", error=str(exc))
        route = self.router.route(spec, task)
        agent_budget = budget.child(spec.limits(), name=actor.id) if budget is not None else Budget(spec.limits(), name=actor.id)
        session.emit(EventType.TASK_STARTED, {"task_id": task.id, "agent_id": actor.id}, task_id=task.id)
        instance = AgentInstance(id=actor.id, role=spec.role, name=spec.name, task_id=task.id, model=route.model,
                                 provider=route.provider, parent=task.inputs.get("parent_agent"))
        session.emit(EventType.AGENT_SPAWNED, {"agent": instance.to_dict()}, task_id=task.id)
        session.emit(EventType.MODEL_ROUTED, {"agent_id": actor.id, "route": route.to_dict()}, task_id=task.id)
        tx = session.transaction(actor.id, task.id)
        ctx = AgentContext(self, session, task, spec, route, actor, tx, agent_budget)
        try:
            if module is None:
                raise AgentError(f"{spec.role} has no procedure module")
            output, fallback = self._produce(ctx, module)
            summary = module.commit(ctx, output) or ""
            if fallback:
                decision = Decision(id=stable_id("dec", "fallback", task.id), kind="fallback",
                                    summary=f"{spec.role}: model route failed, deterministic procedure used",
                                    rationale=fallback, made_by="kernel", refs=[task.id])
                ctx.emit(EventType.DECISION_RECORDED, {"decisions": [decision.to_dict()]}, generated=[decision.id])
                summary = f"{summary} [fallback: {fallback}]"
            tx.emit(EventType.TASK_COMPLETED, {"task_id": task.id, "summary": summary, "outputs": list(ctx.generated),
                                               "mode": route.mode})
            result = TaskResult(task.id, spec.role, actor.id, "done", summary, list(ctx.generated), route,
                                self._usage(ctx), fallback=fallback, pending=tx)
            if not defer_commit:
                result.commit()
            session.emit(EventType.AGENT_RELEASED, {"agent_id": actor.id, "usage": self._usage(ctx)}, task_id=task.id)
            return result
        except SimulatedCrash:
            raise
        except Exception as exc:  # a failed agent is data: the task fails, research continues
            tx.abort()
            error = f"{type(exc).__name__}: {exc}"
            session.emit(EventType.TASK_FAILED, {"task_id": task.id, "error": error[:500]}, task_id=task.id)
            session.emit(EventType.AGENT_RELEASED, {"agent_id": actor.id, "usage": self._usage(ctx)}, task_id=task.id)
            return TaskResult(task.id, spec.role, actor.id, "failed", route=route, usage=self._usage(ctx), error=error)

    @staticmethod
    def _usage(ctx: AgentContext) -> dict[str, Any]:
        usage = dict(ctx.usage)
        usage["cost_usd"] = round(usage.get("cost_usd", 0.0), 6)
        return usage

    def _produce(self, ctx: AgentContext, module: Any) -> tuple[dict[str, Any], str | None]:
        route = ctx.route
        if route.mode == "procedure":
            ctx.draft = module.draft(ctx)
            return ctx.draft, None
        ctx.draft = module.draft(ctx) if route.mode in ("hybrid", "subagent") else None
        try:
            if route.mode == "subagent":
                return self._subagent(ctx, module), None
            return self._llm_loop(ctx, module), None
        except (AgentError, LLMError, BudgetExceeded, ToolError) as exc:
            if route.fallback != "procedure":
                raise
            if ctx.draft is None:
                ctx.draft = module.draft(ctx)
            return ctx.draft, f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------ prompting
    @staticmethod
    def schema_name(ctx: AgentContext, module: Any) -> str:
        """A role may produce different outputs per task kind (e.g. generate vs revise hypotheses)."""
        chooser = getattr(module, "output_schema_for", None)
        return chooser(ctx) if chooser else ctx.spec.output_schema

    def _prompt(self, ctx: AgentContext, module: Any) -> tuple[str, str, dict[str, Any]]:
        spec = ctx.spec
        name = self.schema_name(ctx, module)
        schema = output_schema(name)
        view_input = ViewInput(state=ctx.state, task=ctx.task, spec=spec, capabilities=self.capabilities,
                               skills=self.skills, memory=self.memory)
        view = self.context.build(build_sections(spec.context_view, view_input),
                                  max_tokens=int(spec.model.get("context_tokens", self.context.max_tokens)))
        ctx.usage["context_tokens"] = view.tokens
        language = ctx.goal.language if ctx.goal else "zh"
        index = [s for s in self.skills.index() if s.split(":")[0] not in spec.skills] if self.skills else None
        system = system_prompt(spec, language=language, skills_index=index)
        llm_draft = getattr(module, "llm_draft", None)
        draft = llm_draft(ctx, ctx.draft) if (llm_draft and ctx.draft is not None) else ctx.draft
        user = "\n\n".join([view.render(), "## Instructions\n" + module.instructions(ctx),
                            output_instructions(name, schema, draft)])
        return system, user, schema

    def _llm_loop(self, ctx: AgentContext, module: Any) -> dict[str, Any]:
        spec, route = ctx.spec, ctx.route
        provider = self.capabilities.get("llm", route.provider)
        tool_specs = [self.tools.get(n) for n in spec.tool_names(self.tools)]
        if spec.code_mode and self.codemode is not None:
            tool_specs.append(self.codemode)
        exposed = {t.llm_name: t for t in tool_specs}
        schemas = [ToolSchema(t.llm_name, t.to_llm_schema()["description"], t.input_schema) for t in tool_specs]
        system, user, schema = self._prompt(ctx, module)
        messages = [Message("user", user)]
        for turn in range(spec.max_turns):
            request = LLMRequest(model=route.model, system=system, messages=messages, tools=schemas,
                                 max_tokens=int(spec.model.get("max_tokens", 16000)), effort=route.effort,
                                 metadata={"agent": ctx.actor.id, "task": ctx.task.id, "turn": turn})
            verdict = ctx.hook(HookPoint.BEFORE_LLM_CALL, request, {"spec": spec, "route": route}, subject_id=ctx.task.id)
            if not verdict.allow:
                raise AgentError(f"LLM call blocked by {verdict.hook}: {verdict.reason}")
            ctx.budget.charge(llm_calls=1)
            response = provider.complete(request)
            u = response.usage
            ctx.usage["llm_calls"] += 1
            ctx.usage["input_tokens"] += u.input_tokens
            ctx.usage["output_tokens"] += u.output_tokens
            ctx.usage["cost_usd"] += u.cost_usd
            ctx.session.emit(EventType.LLM_CALLED, {"agent_id": ctx.actor.id, "provider": route.provider,
                                                    "model": response.model or route.model, "turn": turn,
                                                    "stop_reason": response.stop_reason, "usage": u.to_dict(),
                                                    "note": response.note}, actor=ctx.actor.id, task_id=ctx.task.id)
            ctx.budget.charge(tokens=u.input_tokens + u.output_tokens, cost_usd=u.cost_usd)
            if response.stop_reason == "refusal":
                raise AgentRefused(f"model declined the request ({response.note or 'refusal'})")
            messages.append(Message("assistant", text=response.text, tool_uses=list(response.tool_uses), raw=response.raw))
            if response.tool_uses:
                results: list[ToolResultBlock] = []
                calls, slots = [], []
                for use in response.tool_uses:
                    spec_ = exposed.get(use.name)
                    if spec_ is None:
                        results.append(ToolResultBlock(use.id, f"ERROR: tool {use.name} is not available to {spec.name}", True))
                        continue
                    calls.append(ToolCall(spec_.name, dict(use.input or {}), id=use.id))
                    slots.append(use.id)
                outcomes = self.scheduler.execute_batch(calls, actor=ctx.actor, session=ctx.session, task_id=ctx.task.id,
                                                        budget=ctx.budget, tx=ctx.tx) if calls else []
                ctx.usage["tool_calls"] += len(calls)
                for use_id, outcome in zip(slots, outcomes):
                    results.append(ToolResultBlock(use_id, outcome.as_text(), not outcome.ok))
                order = {u.id: i for i, u in enumerate(response.tool_uses)}
                results.sort(key=lambda r: order.get(r.tool_use_id, 0))
                messages.append(Message("user", tool_results=results))
                continue
            if response.stop_reason == "max_tokens":
                messages.append(Message("user", "Your reply was cut off (max_tokens). Reply again with only the final JSON object, more concisely."))
                continue
            data, error = parse_json_output(response.text, schema)
            if error:
                messages.append(Message("user", f"The output did not validate against {self.schema_name(ctx, module)}: {error}. "
                                                "Return only the corrected JSON object."))
                continue
            return data  # type: ignore[return-value]
        raise AgentError(f"no valid {self.schema_name(ctx, module)} output within {spec.max_turns} turns")

    def _subagent(self, ctx: AgentContext, module: Any) -> dict[str, Any]:
        provider = self.subagents.get(ctx.route.subagent or "")
        if provider is None or not provider.available():
            raise AgentError(f"subagent provider {ctx.route.subagent!r} is not available")
        system, user, schema = self._prompt(ctx, module)
        payload = {"agent": ctx.spec.name, "role": ctx.spec.role, "task": ctx.task.to_dict(), "system": system,
                   "prompt": user, "output_schema": schema}
        output = provider.run(payload)
        if not isinstance(output, dict):
            raise AgentError("subagent returned no JSON object")
        errors = validate(output, schema)
        if errors:
            raise AgentError("subagent output invalid: " + "; ".join(errors[:5]))
        ctx.usage.update({k: v for k, v in (output.pop("_usage", None) or {}).items() if k in ctx.usage})
        return output
