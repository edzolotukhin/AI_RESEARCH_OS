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
        finding_repository=None,
        evidence_repository=None,
    ) -> None:
        self._report_service = report_service
        self._draft_generator = draft_generator
        self._finding_repository = finding_repository
        self._evidence_repository = evidence_repository

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
        from application.research_quality.authoritative_outcome import derive_authoritative_outcome
        design = context.workflow_template.research_design_snapshot
        readiness = context.read_shared("research_readiness")
        findings = self._finding_repository.list_for_project(context.project.id, workflow_run_id=context.workflow_run.id) if self._finding_repository is not None else ()
        evidence = self._evidence_repository.list_for_project(context.project.id, workflow_run_id=context.workflow_run.id) if self._evidence_repository is not None else ()
        outcome, unresolved = derive_authoritative_outcome(
            required_information_need_ids=(item.id for item in design.information_needs),
            readiness_payload=readiness if isinstance(readiness, dict) else None,
            findings=findings, evidence=evidence, project_id=context.project.id,
            workflow_run_id=context.workflow_run.id, research_design_id=design.id,
        )
        context.write_shared("research_product_outcome", {
            "outcome": outcome,
            "derivation_version": "p8d3-v1",
            "unresolved_information_need_ids": list(unresolved),
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
