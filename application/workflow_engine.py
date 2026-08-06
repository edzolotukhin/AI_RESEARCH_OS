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
    ) -> None:
        self._scheduler = scheduler
        self._task_executor = task_executor
        self._completion_policy = completion_policy

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
                        if runtime_checkpoint is not None:
                            runtime_checkpoint.on_task_finished(context, error=None)
                    except Exception as exc:
                        if runtime_checkpoint is not None:
                            try:
                                runtime_checkpoint.on_task_finished(context, error=exc)
                            except Exception as checkpoint_exc:
                                raise checkpoint_exc from exc
                        if first_execution_error is None:
                            first_execution_error = exc
                        continue

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
