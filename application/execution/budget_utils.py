from __future__ import annotations

from application.execution.exceptions import BudgetExhaustedError


def is_budget_exhaustion(error: BaseException | None) -> bool:
    """Return True when error or its cause chain includes BudgetExhaustedError."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return True
        current = current.__cause__
    return False
