from __future__ import annotations

from dataclasses import replace

from application.execution.budget_utils import SUFFICIENCY_STAGE_CAP_REASON
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget_context import get_execution_budget
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.research_termination_reason import (
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
