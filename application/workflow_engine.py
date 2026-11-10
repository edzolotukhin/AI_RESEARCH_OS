from __future__ import annotations

from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus

from runtime.workflow_context import WorkflowContext

from application.ports.workflow_runtime_checkpoint import WorkflowRuntimeCheckpoint
from application.runtime.runtime_progress import RuntimeProgress
from application.scheduling.scheduling_result import SchedulingResult
from application.runtime.workflow_completion_policy import (
    WorkflowCompletionPolicy,
)
from application.task_executor import TaskExecutor
from application.task_scheduler import TaskScheduler
from application.execution.execution_budget_context import (
    ensure_run_budget,
    finalize_run_budget,
)
from application.research_quality.authoritative_outcome import derive_authoritative_outcome
from application.research_quality.workflow_task_ids import DOWNSTREAM_TASK_DEFINITION_IDS
from application.analysis.analysis_coverage_service import assess_analysis_coverage


class WorkflowEngine:
    """
    Canonical owner of WorkflowRun execution.

    Orchestrates scheduling passes, task execution, and WorkflowRun status.
    """

    def __init__(
        self,
        scheduler: TaskScheduler,
        task_executor: TaskExecutor,
        completion_policy: WorkflowCompletionPolicy,
        finding_repository=None,
        evidence_repository=None,
        source_repository=None,
    ) -> None:
        self._scheduler = scheduler
        self._task_executor = task_executor
        self._completion_policy = completion_policy
        self._finding_repository = finding_repository
        self._evidence_repository = evidence_repository
        self._source_repository = source_repository

    def run(
        self,
        context: WorkflowContext,
        *,
        checkpoint: WorkflowRuntimeCheckpoint | None = None,
    ) -> WorkflowContext:
        workflow_run = context.workflow_run
        runtime_checkpoint = checkpoint

        if workflow_run.status == WorkflowStatus.CANCELLED:
            return context

        self._ensure_running(workflow_run)
        self._reconcile_h3_review_branch(context)
        ensure_run_budget(context)
        if runtime_checkpoint is not None:
            runtime_checkpoint.on_workflow_started(context)

        first_execution_error: BaseException | None = None

        try:
            while True:
                if workflow_run.status == WorkflowStatus.CANCELLED:
                    break

                scheduling_result = self._scheduler.schedule(workflow_run)
                if runtime_checkpoint is not None and scheduling_result.has_changes:
                    runtime_checkpoint.on_scheduling(context, scheduling_result)

                ready_task = self._scheduler.find_ready_task(workflow_run)
                progress = RuntimeProgress.from_scheduling(
                    scheduling_result=scheduling_result,
                    ready_task=ready_task,
                    all_tasks_terminal=self._completion_policy.all_tasks_terminal(
                        workflow_run,
                    ),
                )

                if ready_task is not None:
                    context.current_task = ready_task
                    try:
                        context = self._task_executor.execute(
                            context,
                            runtime_checkpoint=runtime_checkpoint,
                        )
                        self._apply_post_analysis_outcome(context, ready_task)
                        if runtime_checkpoint is not None:
                            runtime_checkpoint.on_task_finished(context, error=None)
                    except Exception as exc:
                        # Product outcome is separate from WorkflowStatus. Only
                        # confirmed execution failures are marked FAILED;
                        # graceful budget stops retain their methodological
                        # outcome and historical/ambiguous state stays absent.
                        if exc.__class__.__name__ not in {
                            "BudgetExhaustedError",
                            "ExtensionBudgetExceeded",
                        }:
                            context.write_shared("research_product_outcome", {
                                "outcome": "FAILED",
                                "derivation_version": "p8d3-v1",
                                "reason": getattr(exc, "code", exc.__class__.__name__),
                            })
                        if runtime_checkpoint is not None:
                            try:
                                runtime_checkpoint.on_task_finished(context, error=exc)
                            except Exception as checkpoint_exc:
                                raise checkpoint_exc from exc
                        if first_execution_error is None:
                            first_execution_error = exc
                        continue

                if workflow_run.status == WorkflowStatus.PAUSED:
                    break

                if progress.should_stop_iteration:
                    break

            self._finalize_workflow_status(workflow_run)
        finally:
            finalize_run_budget(context)

        if runtime_checkpoint is not None:
            runtime_checkpoint.on_workflow_finalized(
                context,
                error=first_execution_error,
            )

        if first_execution_error is not None:
            raise first_execution_error

        return context

    def _apply_post_analysis_outcome(self, context, task) -> None:
        if task.definition_id != "task-analyze":
            return
        design = getattr(context.workflow_template, "research_design_snapshot", None)
        if design is None or not self._is_h3_workflow(context):
            return
        if self._finding_repository is None or self._evidence_repository is None:
            return
        findings = self._finding_repository.list_for_project(
            context.project.id, workflow_run_id=context.workflow_run.id,
        )
        evidence = self._evidence_repository.list_for_project(
            context.project.id, workflow_run_id=context.workflow_run.id,
        )
        brief = getattr(context.workflow_template, "research_brief_snapshot", None)
        coverage = assess_analysis_coverage(
            project_id=context.project.id,
            design=design,
            findings=findings,
            evidence=evidence,
            brief=brief,
            source_repository=self._source_repository,
        )
        context.write_shared("analysis_coverage", coverage.to_dict())
        readiness = context.read_shared("research_readiness")
        outcome, unresolved = derive_authoritative_outcome(
            required_information_need_ids=(item.id for item in design.information_needs),
            readiness_payload=readiness,
            findings=findings,
            evidence=evidence,
            project_id=context.project.id,
            workflow_run_id=context.workflow_run.id,
            research_design_id=design.id,
            coverage_missing_information_need_ids=coverage.missing_information_need_ids,
        )
        if not coverage.fully_covered:
            context.write_shared("research_product_outcome", {
                "outcome": outcome,
                "derivation_version": "p8d3-v1",
                "authoritative_post_analysis": True,
                "unresolved_information_need_ids": list(unresolved),
                "reason": "analysis_coverage_incomplete",
            })
            self._scheduler.skip_definition_ids(
                context.workflow_run, DOWNSTREAM_TASK_DEFINITION_IDS,
            )
            return
        if outcome != "INSUFFICIENT":
            return
        context.write_shared("research_product_outcome", {
            "outcome": outcome,
            "derivation_version": "p8d3-v1",
            "authoritative_post_analysis": True,
            "unresolved_information_need_ids": list(unresolved),
            "reason": "no_defensible_findings",
        })
        self._scheduler.skip_definition_ids(
            context.workflow_run, DOWNSTREAM_TASK_DEFINITION_IDS,
        )

    @staticmethod
    def _is_h3_workflow(context: WorkflowContext) -> bool:
        from application.report.contract_selection import (
            DESK_REPORT_CONTRACT_PIN,
            H3_REPORT_CONTRACT,
        )

        pin = context.read_shared(DESK_REPORT_CONTRACT_PIN)
        if pin is not None:
            return pin == H3_REPORT_CONTRACT
        template = context.workflow_template
        if template is None:
            return False
        definition_ids = {item.id for item in template.task_definitions}
        return {
            "task-review-report-1",
            "task-revise-report",
            "task-review-report-2",
        }.issubset(definition_ids)

    def execute(
        self,
        project: Project,
        workflow_template: WorkflowTemplate,
        workflow_run: WorkflowRun,
    ) -> WorkflowContext:
        context = WorkflowContext(
            project=project,
            workflow_template=workflow_template,
            workflow_run=workflow_run,
        )
        return self.run(context)

    @staticmethod
    def _ensure_running(
        workflow_run: WorkflowRun,
    ) -> None:
        if workflow_run.status == WorkflowStatus.CREATED:
            workflow_run.ready()

        if workflow_run.status == WorkflowStatus.READY:
            workflow_run.start()

    @staticmethod
    def _reconcile_h3_review_branch(context: WorkflowContext) -> None:
        """Restore the finite H3 branch before the first durable checkpoint."""
        from application.review.h3_review_branch import H3ReviewBranchController

        H3ReviewBranchController().reconcile(context)

    def _finalize_workflow_status(
        self,
        workflow_run: WorkflowRun,
    ) -> None:
        if workflow_run.is_terminal:
            return

        target = self._completion_policy.resolve(workflow_run)

        if target is None:
            return

        self._apply_workflow_status(workflow_run, target)

    @staticmethod
    def _apply_workflow_status(
        workflow_run: WorkflowRun,
        target: WorkflowStatus,
    ) -> None:
        if workflow_run.status == target:
            return

        if target == WorkflowStatus.COMPLETED:
            workflow_run.complete()
            return

        if target == WorkflowStatus.FAILED:
            workflow_run.fail()
            return

        if target == WorkflowStatus.CANCELLED:
            workflow_run.cancel()
