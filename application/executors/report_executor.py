from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.report.report_service import ReportService

from runtime.workflow_context import WorkflowContext


class ReportExecutor(BaseExecutor):
    """Desk-research report writer stage executor (DR-06)."""

    def __init__(
        self,
        *,
        report_service: ReportService,
    ) -> None:
        self._report_service = report_service

    def run(self, context: WorkflowContext) -> WorkflowContext:
        summary = self._report_service.write_for_context(context)
        context.write_shared("report", summary.to_dict())

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
