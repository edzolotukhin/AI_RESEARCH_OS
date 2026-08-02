from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.review.review_service import ReviewService

from runtime.workflow_context import WorkflowContext


class ReviewExecutor(BaseExecutor):
    """Desk-research report quality gate executor (DR-07)."""

    def __init__(self, *, review_service: ReviewService) -> None:
        self._review_service = review_service

    def run(self, context: WorkflowContext) -> WorkflowContext:
        summary = self._review_service.review_for_context(context)
        context.write_shared("review", summary.to_dict())

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
