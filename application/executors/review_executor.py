from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
from application.review.h3_review_branch import H3ReviewBranchController, h3_review_round

from runtime.workflow_context import WorkflowContext


class ReviewExecutor(BaseExecutor):
    """Desk-research report quality gate executor (DR-07)."""

    def __init__(self, *, review_service, deliverable_finalizer=None, branch_controller=None) -> None:
        self._review_service = review_service
        self._deliverable_finalizer = deliverable_finalizer
        self._branch_controller = branch_controller or H3ReviewBranchController()

    def run(self, context: WorkflowContext) -> WorkflowContext:
        from application.replay.desk_downstream_replay import update_replay_stage
        update_replay_stage(context, "review", "running")
        try:
            summary = self._review_service.review_for_context(context)
        except Exception as exc:
            update_replay_stage(
                context, "review", "failed",
                failure_code=getattr(exc, "code", exc.__class__.__name__),
            )
            raise
        payload = summary.to_dict()
        if context.read_shared(DESK_REPORT_CONTRACT_PIN) == H3_REPORT_CONTRACT:
            round_number = h3_review_round(context)
            if round_number is None:
                raise RuntimeError("h3_review_task_identity_invalid")
            context.write_shared(f"review_{round_number}", payload)
            self._branch_controller.apply_review_result(context, summary)
        else:
            context.write_shared("review", payload)
        update_replay_stage(context, "review", "completed")
        tasks = getattr(context.workflow_run, "tasks", ())
        has_finalization_task = isinstance(tasks, (list, tuple)) and any(
            task.executor_id == "finalization" for task in tasks
        )
        if summary.verdict == "approve" and self._deliverable_finalizer is not None and not has_finalization_task:
            update_replay_stage(context, "deliverables", "running")
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
                state = {
                    "status": getattr(exc, "state", "pdf_failed"),
                    "failure_code": getattr(exc, "code", "deliverable_finalization_failed"),
                    "report_id": summary.report_id,
                    "review_id": summary.review_id,
                }
                diagnostics = getattr(exc, "diagnostics", None)
                if isinstance(diagnostics, dict) and diagnostics:
                    state["diagnostics"] = diagnostics
                context.write_shared("desk_deliverable_finalization", state)
                update_replay_stage(
                    context, "deliverables", "failed",
                    failure_code=getattr(exc, "code", exc.__class__.__name__),
                )
                raise
            context.write_shared("desk_deliverable_finalization", state)
            final_status = "completed" if state.get("status") in {"complete", "finalization_complete"} else state.get("status", "running")
            update_replay_stage(context, "deliverables", final_status)
            if final_status != "completed" and context.current_task is not None:
                context.current_task.pause()
                context.workflow_run.pause()
        else:
            if summary.verdict != "approve":
                update_replay_stage(context, "deliverables", "skipped")

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
