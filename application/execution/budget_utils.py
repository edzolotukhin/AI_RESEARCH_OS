from __future__ import annotations

from application.execution.exceptions import BudgetExhaustedError

EVIDENCE_STAGE_CAP_REASON = "evidence_max_llm_calls"
EVIDENCE_INITIAL_PARTITION_REASON = "evidence_initial_partition_exhausted"
EVIDENCE_REMEDIATION_BUDGET_REASON = "evidence_remediation_budget_exhausted"
SUFFICIENCY_STAGE_CAP_REASON = "sufficiency_max_llm_calls"
DOWNSTREAM_RESERVE_REASON = "downstream_reserve_exhausted"
GLOBAL_RUN_BUDGET_REASON = "llm_max_calls_per_run"
EVIDENCE_PURPOSE_INITIAL = "initial"
EVIDENCE_PURPOSE_REMEDIATION = "remediation"


def is_budget_exhaustion(error: BaseException | None) -> bool:
    """Return True when error or its cause chain includes BudgetExhaustedError."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return True
        current = current.__cause__
    return False


def is_evidence_stage_cap_exhaustion(error: BaseException | None) -> bool:
    """Return True when error is the evidence-stage LLM call cap."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return current.reason == EVIDENCE_STAGE_CAP_REASON
        current = current.__cause__
    return False


def is_downstream_reserve_exhaustion(error: BaseException | None) -> bool:
    """Return True when evidence hit the global downstream LLM reserve."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return current.reason == DOWNSTREAM_RESERVE_REASON
        current = current.__cause__
    return False


def is_global_run_budget_exhaustion(error: BaseException | None) -> bool:
    """Return True when the whole run LLM budget is exhausted."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return current.reason == GLOBAL_RUN_BUDGET_REASON
        current = current.__cause__
    return False


def is_evidence_initial_partition_exhaustion(error: BaseException | None) -> bool:
    """Return True when initial Evidence hit its reserved-safe partition."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return current.reason == EVIDENCE_INITIAL_PARTITION_REASON
        current = current.__cause__
    return False


def is_evidence_remediation_budget_exhaustion(error: BaseException | None) -> bool:
    """Return True when targeted Evidence has no remaining envelope."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return current.reason == EVIDENCE_REMEDIATION_BUDGET_REASON
        current = current.__cause__
    return False


def is_evidence_graceful_budget_stop(error: BaseException | None) -> bool:
    """Return True when evidence may stop gracefully with partial results."""
    return (
        is_evidence_stage_cap_exhaustion(error)
        or is_evidence_initial_partition_exhaustion(error)
        or is_evidence_remediation_budget_exhaustion(error)
        or is_downstream_reserve_exhaustion(error)
    )


def is_sufficiency_stage_cap_exhaustion(error: BaseException | None) -> bool:
    """Return True when error is the sufficiency-stage LLM call cap."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, BudgetExhaustedError):
            return current.reason == SUFFICIENCY_STAGE_CAP_REASON
        current = current.__cause__
    return False


def is_sufficiency_graceful_budget_stop(error: BaseException | None) -> bool:
    """Return True when sufficiency evaluation may terminate research gracefully."""
    return is_sufficiency_stage_cap_exhaustion(error)
