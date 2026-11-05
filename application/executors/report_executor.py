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
        draft_generator=None,
    ) -> None:
        self._report_service = report_service
        self._draft_generator = draft_generator

    def run(self, context: WorkflowContext) -> WorkflowContext:
        from application.replay.desk_downstream_replay import update_replay_stage
        update_replay_stage(context, "report", "running")
        try:
            summary = self._report_service.write_for_context(context)
        except Exception as exc:
            context.write_shared("research_product_outcome", {
                "outcome": "FAILED",
                "derivation_version": "p8d3-v1",
                "reason": getattr(exc, "code", exc.__class__.__name__),
            })
            update_replay_stage(
                context, "report", "failed",
                failure_code=getattr(exc, "code", exc.__class__.__name__),
            )
            raise
        context.write_shared("report", summary.to_dict())
        readiness = context.read_shared("research_readiness")
        blocking = (
            readiness.get("blocking_information_need_ids", [])
            if isinstance(readiness, dict) else []
        )
        sections = int(summary.section_count)
        outcome = "COMPLETED" if sections > 0 and not blocking else (
            "PARTIAL" if sections > 0 else "INSUFFICIENT"
        )
        context.write_shared("research_product_outcome", {
            "outcome": outcome,
            "derivation_version": "p8d3-v1",
            "unresolved_information_need_ids": list(blocking),
            "report_id": summary.report_id,
        })
        if self._draft_generator is not None:
            context.write_shared(
                "draft_report_package",
                self._draft_generator.generate_draft_package(
                    project_id=context.project.id,
                    report_id=summary.report_id,
                ),
            )
        update_replay_stage(context, "report", "completed")

        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(
                context,
                task.id,
            )
        return context
