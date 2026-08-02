from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.analysis.analysis_service import AnalysisService

from runtime.workflow_context import WorkflowContext


class AnalysisExecutor(BaseExecutor):
    """Desk-research analysis stage executor (DR-05)."""

    def __init__(
        self,
        *,
        analysis_service: AnalysisService,
    ) -> None:
        self._analysis_service = analysis_service

    def run(self, context: WorkflowContext) -> WorkflowContext:
        summary = self._analysis_service.analyze_for_context(context)
        context.write_shared("analysis", summary.to_dict())

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
