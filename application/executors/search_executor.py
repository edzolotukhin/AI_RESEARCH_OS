from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.sources.source_acquisition_service import SourceAcquisitionService

from runtime.workflow_context import WorkflowContext


class SearchExecutor(BaseExecutor):
    """
    Desk-research search stage executor (DR-03).

    Delegates to SourceAcquisitionService and persists a structured summary
    in shared_state for downstream tasks.
    """

    def __init__(
        self,
        *,
        source_acquisition_service: SourceAcquisitionService,
    ) -> None:
        self._source_acquisition_service = source_acquisition_service

    def run(self, context: WorkflowContext) -> WorkflowContext:
        summary = self._source_acquisition_service.acquire_for_context(context)
        context.write_shared("source_acquisition", summary.to_dict())

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
