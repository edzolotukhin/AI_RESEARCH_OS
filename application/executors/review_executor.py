from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.review.review_service import ReviewService

from runtime.workflow_context import WorkflowContext


class ReviewExecutor(BaseExecutor):
    """Desk-research report quality gate executor (DR-07)."""

    def __init__(self, *, review_service: ReviewService, deliverable_finalizer=None) -> None:
        self._review_service = review_service
        self._deliverable_finalizer = deliverable_finalizer

    def run(self, context: WorkflowContext) -> WorkflowContext:
        summary = self._review_service.review_for_context(context)
        context.write_shared("review", summary.to_dict())
        if summary.verdict == "approve" and self._deliverable_finalizer is not None:
            context.write_shared("desk_deliverable_finalization", {
                "status": "pending", "report_id": summary.report_id,
                "review_id": summary.review_id,
            })
            try:
                state = self._deliverable_finalizer.finalize_approved_review(
                    project_id=context.project.id, report_id=summary.report_id,
                    review_id=summary.review_id,
                )
            except Exception as exc:
                context.write_shared("desk_deliverable_finalization", {
                    "status": getattr(exc, "state", "pdf_failed"),
                    "failure_code": getattr(exc, "code", "deliverable_finalization_failed"),
                    "report_id": summary.report_id,
                    "review_id": summary.review_id,
                })
                raise
            context.write_shared("desk_deliverable_finalization", state)

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
