from __future__ import annotations


class ClaimConflictError(Exception):
    """Raised when a run cannot be claimed by the requesting worker."""


class LeaseLostError(Exception):
    """Raised when the worker no longer owns the run lease."""


class BudgetExhaustedError(Exception):
    """Raised when a per-run or per-stage LLM budget limit is reached."""

    def __init__(self, reason: str, *, stage: str | None = None) -> None:
        self.reason = reason
        self.stage = stage
        message = f"Execution budget exhausted: {reason}"
        if stage is not None:
            message = f"{message} (stage={stage})"
        super().__init__(message)
