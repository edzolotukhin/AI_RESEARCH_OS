from __future__ import annotations

from dataclasses import replace

from application.execution.budget_utils import (
    DOWNSTREAM_RESERVE_REASON,
    EVIDENCE_PURPOSE_REMEDIATION,
    EVIDENCE_REMEDIATION_BUDGET_REASON,
    EVIDENCE_STAGE_CAP_REASON,
    SUFFICIENCY_STAGE_CAP_REASON,
    is_evidence_graceful_budget_stop,
    is_sufficiency_graceful_budget_stop,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import get_execution_budget
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.research_termination_reason import (
    DOWNSTREAM_RESERVE_EXHAUSTED,
    EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
    SUFFICIENCY_BUDGET_EXHAUSTED,
)

from application.research_quality.research_loop_state import ResearchLoopState


def sufficiency_unavailable_reason() -> str | None:
    """Return the graceful Sufficiency stop reason, if another call is blocked.

    Stage-cap and downstream-reserve exhaustion are controlled research stops.
    Other BudgetExhaustedError reasons propagate as hard failures.
    """
    budget = get_execution_budget()
    if budget is None:
        return None
    try:
        budget.assert_can_call("sufficiency")
    except BudgetExhaustedError as exc:
        if is_sufficiency_graceful_budget_stop(exc):
            return exc.reason
        raise
    return None


def sufficiency_budget_available() -> bool:
    """Return False when another sufficiency-stage LLM call would exceed limits."""
    return sufficiency_unavailable_reason() is None


def evidence_remediation_unavailable_reason() -> str | None:
    """Return the graceful Evidence-remediation stop reason, if any."""
    budget = get_execution_budget()
    if budget is None:
        return None
    try:
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
    except BudgetExhaustedError as exc:
        if is_evidence_graceful_budget_stop(exc):
            return exc.reason
        raise
    return None


def evidence_remediation_budget_available() -> bool:
    """Return False when targeted Evidence cannot issue another LLM call."""
    return evidence_remediation_unavailable_reason() is None


def _canonicalize_sufficiency_stop_reason(reason: str | None) -> str:
    stop_reason = reason or SUFFICIENCY_BUDGET_EXHAUSTED
    if stop_reason == SUFFICIENCY_STAGE_CAP_REASON:
        return SUFFICIENCY_BUDGET_EXHAUSTED
    if stop_reason in {DOWNSTREAM_RESERVE_REASON, DOWNSTREAM_RESERVE_EXHAUSTED}:
        return DOWNSTREAM_RESERVE_EXHAUSTED
    return stop_reason


def apply_sufficiency_budget_termination(
    result: ResearchReadinessResult,
    *,
    loop_state: ResearchLoopState | None = None,
    reason: str | None = None,
) -> tuple[ResearchReadinessResult, ResearchLoopState | None]:
    """Convert sufficiency budget exhaustion into controlled research termination."""
    stop_reason = _canonicalize_sufficiency_stop_reason(reason)
    terminated = replace(
        result,
        targeted_research_required=False,
        termination_reason=stop_reason,
    )
    if loop_state is not None:
        loop_state.termination_reason = stop_reason
    return terminated, loop_state


def apply_evidence_remediation_budget_termination(
    result: ResearchReadinessResult,
    *,
    loop_state: ResearchLoopState | None = None,
    reason: str = EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
) -> tuple[ResearchReadinessResult, ResearchLoopState | None]:
    """Convert targeted Evidence exhaustion into controlled research termination."""
    stop_reason = reason or EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED
    if stop_reason in {EVIDENCE_STAGE_CAP_REASON, EVIDENCE_REMEDIATION_BUDGET_REASON}:
        stop_reason = EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED
    terminated = replace(
        result,
        targeted_research_required=False,
        termination_reason=stop_reason,
    )
    if loop_state is not None:
        loop_state.termination_reason = stop_reason
    return terminated, loop_state
