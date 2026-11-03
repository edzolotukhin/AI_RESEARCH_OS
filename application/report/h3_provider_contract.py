from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol


class H3StructuralClaimProvider(Protocol):
    def generate_h3_claim_candidates(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def repair_h3_claim_candidates(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class H3EditorialProvider(Protocol):
    def compose(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class H3ReviewProvider(Protocol):
    def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class H3ProviderBudgetExceeded(RuntimeError):
    pass


@dataclass
class H3ProviderBudget:
    limit: int = 7
    used: int = 0
    _on_change: Callable[["H3ProviderBudget"], None] | None = field(
        default=None, repr=False, compare=False,
    )

    def consume(self) -> None:
        if self.used >= self.limit:
            raise H3ProviderBudgetExceeded("h3_provider_budget_exhausted")
        self.used += 1
        if self._on_change is not None:
            self._on_change(self)


_CURRENT_BUDGET: ContextVar[H3ProviderBudget | None] = ContextVar(
    "h3_provider_budget", default=None,
)


@contextmanager
def h3_provider_budget(budget: H3ProviderBudget):
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)


def debit_h3_provider_call() -> None:
    budget = _CURRENT_BUDGET.get()
    if budget is not None:
        budget.consume()


def budget_for_context(context) -> H3ProviderBudget:
    key = "h3_provider_budget"
    budget = context.services.get(key)
    if isinstance(budget, H3ProviderBudget):
        return budget
    snapshot = context.read_shared(key)
    limit = snapshot.get("limit", 7) if isinstance(snapshot, dict) else 7
    used = snapshot.get("used", 0) if isinstance(snapshot, dict) else 0
    if type(limit) is not int or type(used) is not int or limit <= 0 or not 0 <= used <= limit:
        raise H3ProviderBudgetExceeded("h3_provider_budget_state_invalid")

    def persist(value: H3ProviderBudget) -> None:
        context.write_shared(key, {"limit": value.limit, "used": value.used})

    budget = H3ProviderBudget(limit=limit, used=used, _on_change=persist)
    context.services[key] = budget
    persist(budget)
    return budget
