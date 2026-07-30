from __future__ import annotations

from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus

from runtime.workflow_context import WorkflowContext

from application.runtime.runtime_progress import RuntimeProgress
from application.runtime.workflow_completion_policy import (
    WorkflowCompletionPolicy,
)
from application.task_executor import TaskExecutor
from application.task_scheduler import TaskScheduler


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
    ) -> WorkflowContext:
        workflow_run = context.workflow_run

        if workflow_run.status == WorkflowStatus.CANCELLED:
            return context

        self._ensure_running(workflow_run)

        while True:
            if workflow_run.status == WorkflowStatus.CANCELLED:
                break

            scheduling_result = self._scheduler.schedule(workflow_run)
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
                context = self._task_executor.execute(context)
                continue

            if progress.should_stop_iteration:
                break

        self._finalize_workflow_status(workflow_run)
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
