from __future__ import annotations

from contextvars import ContextVar

_mark_retry: ContextVar[bool] = ContextVar(
    "execution_budget_mark_retry",
    default=False,
)


def mark_llm_call_as_retry() -> None:
    _mark_retry.set(True)


def consume_llm_call_retry_flag() -> bool:
    retry = _mark_retry.get()
    _mark_retry.set(False)
    return retry
