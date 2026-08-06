from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.runtime.task_result_codec import capture_task_result

from runtime.workflow_context import WorkflowContext


class ResearchReadinessExecutor(BaseExecutor):
    """Desk-research research readiness gate stage executor (P1-04)."""

    def __init__(
        self,
        *,
        research_readiness_service: ResearchReadinessService,
    ) -> None:
        self._service = research_readiness_service

    def run(self, context: WorkflowContext) -> WorkflowContext:
        self._service.assess_and_apply(context)

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
