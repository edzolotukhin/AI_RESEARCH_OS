from __future__ import annotations

from dataclasses import replace

from application.execution.budget_utils import (
    EVIDENCE_PURPOSE_REMEDIATION,
    EVIDENCE_REMEDIATION_BUDGET_REASON,
    EVIDENCE_STAGE_CAP_REASON,
    SUFFICIENCY_STAGE_CAP_REASON,
    is_evidence_graceful_budget_stop,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import get_execution_budget
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.research_termination_reason import (
    EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
    SUFFICIENCY_BUDGET_EXHAUSTED,
)

from application.research_quality.research_loop_state import ResearchLoopState


def sufficiency_budget_available() -> bool:
    """Return False when another sufficiency-stage LLM call would exceed the cap."""
    budget = get_execution_budget()
    if budget is None:
        return True
    try:
        budget.assert_can_call("sufficiency")
    except BudgetExhaustedError as exc:
        if exc.reason == SUFFICIENCY_STAGE_CAP_REASON:
            return False
        raise
    return True


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


def apply_sufficiency_budget_termination(
    result: ResearchReadinessResult,
    *,
    loop_state: ResearchLoopState | None = None,
) -> tuple[ResearchReadinessResult, ResearchLoopState | None]:
    """Convert sufficiency budget exhaustion into controlled research termination."""
    terminated = replace(
        result,
        targeted_research_required=False,
        termination_reason=SUFFICIENCY_BUDGET_EXHAUSTED,
    )
    if loop_state is not None:
        loop_state.termination_reason = SUFFICIENCY_BUDGET_EXHAUSTED
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
