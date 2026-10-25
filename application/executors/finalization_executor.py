from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.replay.desk_downstream_replay import update_replay_stage


class FinalizationExecutor(BaseExecutor):
    """Pause the workflow at an explicit deliverable boundary until PPTX settles."""

    def __init__(self, finalizer) -> None:
        self._finalizer = finalizer

    def run(self, context):
        review = context.read_shared("review")
        if not isinstance(review, dict) or review.get("verdict") != "approve":
            raise RuntimeError("approved_review_required_for_finalization")
        update_replay_stage(context, "deliverables", "running")
        context.write_shared("desk_deliverable_finalization", {
            "status": "review_approved",
            "report_id": str(review.get("report_id") or ""),
            "review_id": str(review.get("review_id") or ""),
        })
        try:
            state = self._finalizer.finalize_approved_review(
                project_id=context.project.id,
                report_id=str(review["report_id"]),
                review_id=str(review["review_id"]),
            )
        except Exception as exc:
            state = {
                "status": getattr(exc, "state", "finalization_failed"),
                "failure_code": getattr(exc, "code", "deliverable_finalization_failed"),
                "report_id": str(review.get("report_id") or ""),
                "review_id": str(review.get("review_id") or ""),
            }
            context.write_shared("desk_deliverable_finalization", state)
            update_replay_stage(context, "deliverables", "failed",
                                failure_code=state["failure_code"])
            raise
        context.write_shared("desk_deliverable_finalization", state)
        if state.get("status") == "finalization_complete":
            update_replay_stage(context, "deliverables", "completed")
            return context
        update_replay_stage(context, "deliverables", state.get("status", "running"))
        context.current_task.pause()
        context.workflow_run.pause()
        return context
