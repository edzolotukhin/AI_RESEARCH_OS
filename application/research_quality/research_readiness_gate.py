from __future__ import annotations

from application.research_quality.workflow_task_ids import DOWNSTREAM_TASK_DEFINITION_IDS
from application.task_lifecycle_manager import TaskLifecycleManager
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.research_readiness_result import ResearchReadinessResult

from runtime.workflow_context import WorkflowContext


class ResearchReadinessGate:
    """Applies workflow gate decisions from a ResearchReadinessResult."""

    def __init__(
        self,
        *,
        lifecycle: TaskLifecycleManager | None = None,
    ) -> None:
        self._lifecycle = lifecycle or TaskLifecycleManager()

    def research_outcome(
        self,
        result: ResearchReadinessResult,
    ) -> ResearchOutcome:
        if result.ready_for_analysis:
            return ResearchOutcome.READY_FOR_ANALYSIS
        return ResearchOutcome.INSUFFICIENT_RESEARCH

    def apply_not_ready(self, context: WorkflowContext) -> None:
        """Skip downstream analysis/report/review tasks without failing the workflow."""
        for task in context.workflow_run.tasks:
            if task.definition_id not in DOWNSTREAM_TASK_DEFINITION_IDS:
                continue
            if task.is_terminal:
                continue
            self._lifecycle.skip(task)
