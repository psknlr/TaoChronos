"""Hierarchical budgets: a session budget with carved-out per-agent budgets.

Spending that cannot be known in advance (a model call) follows **reserve → execute → settle**: the estimate is held
before the call (so concurrent agents cannot overshoot together), the actual usage is charged when it returns, and a
failed call releases its hold.  The engine records reservations and settlements as events, and a resumed session seeds
its budget from the log (``Budget.seed``), so a crash does not reset what was spent.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, fields


class BudgetExceeded(RuntimeError):
    def __init__(self, budget: str, kind: str, limit: float, used: float) -> None:
        super().__init__(f"budget '{budget}' exceeded: {kind} used {used} > limit {limit}")
        self.budget = budget
        self.kind = kind
        self.limit = limit
        self.used = used


@dataclass
class BudgetLimits:
    max_tokens: int | None = None
    max_tool_calls: int | None = None
    max_llm_calls: int | None = None
    max_cost_usd: float | None = None
    max_wall_seconds: float | None = None
    max_agents: int | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "BudgetLimits":
        data = data or {}
        return cls(**{f.name: data.get(f.name) for f in fields(cls)})


_USAGE_KEYS = {
    "tokens": "max_tokens",
    "tool_calls": "max_tool_calls",
    "llm_calls": "max_llm_calls",
    "cost_usd": "max_cost_usd",
    "agents": "max_agents",
}


class Budget:
    def __init__(self, limits: BudgetLimits | None = None, *, name: str = "session", parent: "Budget | None" = None):
        self.name = name
        self.limits = limits or BudgetLimits()
        self.parent = parent
        self.used = {key: 0.0 for key in _USAGE_KEYS}
        self.held = {key: 0.0 for key in _USAGE_KEYS}  # reserved, not yet settled
        self.reservations: dict[str, dict[str, float]] = {}
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._counter = 0

    def child(self, limits: BudgetLimits | None = None, name: str = "agent") -> "Budget":
        return Budget(limits, name=name, parent=self)

    def _check(self, key: str, amount: float) -> None:
        limit = getattr(self.limits, _USAGE_KEYS[key])
        if limit is not None and self.used[key] + self.held[key] + amount > limit:
            raise BudgetExceeded(self.name, key, limit, self.used[key] + self.held[key] + amount)
        if self.limits.max_wall_seconds is not None:
            elapsed = time.monotonic() - self.started
            if elapsed > self.limits.max_wall_seconds:
                raise BudgetExceeded(self.name, "wall_seconds", self.limits.max_wall_seconds, elapsed)

    def charge(self, **amounts: float) -> None:
        """Charge usage (tokens=, tool_calls=, llm_calls=, cost_usd=, agents=) up the budget tree."""
        chain: list[Budget] = []
        node: Budget | None = self
        while node is not None:
            chain.append(node)
            node = node.parent
        for budget in chain:  # check everything first so a failed charge changes nothing
            with budget._lock:
                for key, amount in amounts.items():
                    if amount:
                        budget._check(key, amount)
        for budget in chain:
            with budget._lock:
                for key, amount in amounts.items():
                    budget.used[key] += amount

    def _chain(self) -> list["Budget"]:
        chain: list[Budget] = []
        node: Budget | None = self
        while node is not None:
            chain.append(node)
            node = node.parent
        return chain

    def reserve(self, **amounts: float) -> str:
        """Hold an estimate up the budget tree (raises BudgetExceeded and holds nothing if it does not fit)."""
        chain = self._chain()
        for budget in chain:
            with budget._lock:
                for key, amount in amounts.items():
                    if amount:
                        budget._check(key, amount)
        with self._lock:
            self._counter += 1
            rid = f"{self.name}#r{self._counter}"
        for budget in chain:
            with budget._lock:
                for key, amount in amounts.items():
                    budget.held[key] += amount
                budget.reservations[rid] = dict(amounts)
        return rid

    def settle(self, reservation: str, **actual: float) -> None:
        """Release a reservation and charge what was actually used (which may exceed the estimate: it was spent)."""
        for budget in self._chain():
            with budget._lock:
                held = budget.reservations.pop(reservation, {})
                for key, amount in held.items():
                    budget.held[key] = max(0.0, budget.held[key] - amount)
                for key, amount in actual.items():
                    budget.used[key] += amount

    def release(self, reservation: str) -> None:
        self.settle(reservation)

    def seed(self, **used: float) -> None:
        """Start from usage already recorded in the log (a resumed session)."""
        with self._lock:
            for key, amount in used.items():
                if key in self.used and amount:
                    self.used[key] = max(self.used[key], float(amount))

    def remaining(self) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for key, limit_name in _USAGE_KEYS.items():
            limit = getattr(self.limits, limit_name)
            out[key] = None if limit is None else max(0.0, limit - self.used[key])
        return out

    def exhausted(self) -> bool:
        for key, limit_name in _USAGE_KEYS.items():
            limit = getattr(self.limits, limit_name)
            if limit is not None and self.used[key] >= limit:
                return True
        if self.limits.max_wall_seconds is not None:
            return time.monotonic() - self.started > self.limits.max_wall_seconds
        return bool(self.parent and self.parent.exhausted())

    def snapshot(self) -> dict:
        return {"name": self.name, "used": dict(self.used), "held": dict(self.held), "remaining": self.remaining()}
