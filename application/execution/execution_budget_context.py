from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_factory import create_execution_budget
from application.telemetry.run_usage_summary import RunUsageSummary

if TYPE_CHECKING:
    from runtime.workflow_context import WorkflowContext

EXECUTION_BUDGET_KEY = "execution_budget"
RUN_USAGE_SUMMARY_KEY = "run_usage_summary"

_current_budget: ContextVar[ExecutionBudget | None] = ContextVar(
    "execution_budget",
    default=None,
)
_current_stage: ContextVar[str | None] = ContextVar(
    "execution_budget_stage",
    default=None,
)
_current_evidence_purpose: ContextVar[str | None] = ContextVar(
    "evidence_call_purpose",
    default=None,
)

EXECUTOR_STAGE_MAP: dict[str, str] = {
    "evidence": "evidence",
    "research_quality": "sufficiency",
    "analysis": "analysis",
    "report": "report",
    "review": "review",
    "planner": "planner",
    "search": "search",
}


def get_execution_budget() -> ExecutionBudget | None:
    return _current_budget.get()


def get_execution_stage() -> str | None:
    return _current_stage.get()


def set_execution_stage(stage: str | None) -> None:
    _current_stage.set(stage)


def get_evidence_call_purpose() -> str | None:
    return _current_evidence_purpose.get()


def set_evidence_call_purpose(purpose: str | None) -> None:
    _current_evidence_purpose.set(purpose)


def stage_for_executor(executor_id: str) -> str:
    return EXECUTOR_STAGE_MAP.get(executor_id, executor_id)


def ensure_run_budget(context: WorkflowContext) -> ExecutionBudget:
    """Attach one ExecutionBudget to the workflow context for the whole run."""
    existing = context.execution_metadata.get(EXECUTION_BUDGET_KEY)
    if isinstance(existing, ExecutionBudget):
        _current_budget.set(existing)
        return existing

    budget = create_execution_budget()
    context.execution_metadata[EXECUTION_BUDGET_KEY] = budget
    context.execution_metadata.setdefault(
        RUN_USAGE_SUMMARY_KEY,
        RunUsageSummary(workflow_run_id=context.workflow_run.id),
    )
    _current_budget.set(budget)
    return budget


def finalize_run_budget(context: WorkflowContext) -> RunUsageSummary | None:
    """Merge live budget counters into the run usage summary."""
    budget = context.execution_metadata.get(EXECUTION_BUDGET_KEY)
    if not isinstance(budget, ExecutionBudget):
        _current_budget.set(None)
        _current_stage.set(None)
        _current_evidence_purpose.set(None)
        return None

    summary = context.execution_metadata.get(RUN_USAGE_SUMMARY_KEY)
    if not isinstance(summary, RunUsageSummary):
        summary = RunUsageSummary(workflow_run_id=context.workflow_run.id)
        context.execution_metadata[RUN_USAGE_SUMMARY_KEY] = summary

    summary.merge_budget(budget)
    context.shared_state["run_usage_summary"] = summary.to_dict()
    _current_budget.set(None)
    _current_stage.set(None)
    _current_evidence_purpose.set(None)
    return summary
