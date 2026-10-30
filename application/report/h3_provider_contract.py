from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


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

    def consume(self) -> None:
        if self.used >= self.limit:
            raise H3ProviderBudgetExceeded("h3_provider_budget_exhausted")
        self.used += 1


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
    budget = context.read_shared("h3_provider_budget")
    if not isinstance(budget, H3ProviderBudget):
        budget = H3ProviderBudget()
        context.write_shared("h3_provider_budget", budget)
    return budget
