from __future__ import annotations

from domain.runtime.state_machine import TASK_STATE_MACHINE
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus


class WorkflowCompletionPolicy:
    """
    Resolves the final WorkflowRun status after runtime execution stops.
    """

    @staticmethod
    def all_tasks_terminal(
        workflow_run: WorkflowRun,
    ) -> bool:
        if not workflow_run.tasks:
            return True

        return all(
            TASK_STATE_MACHINE.is_terminal(task.status)
            for task in workflow_run.tasks
        )

    @staticmethod
    def resolve(
        workflow_run: WorkflowRun,
    ) -> WorkflowStatus | None:
        if workflow_run.status == WorkflowStatus.CANCELLED:
            return WorkflowStatus.CANCELLED

        if not workflow_run.tasks:
            return WorkflowStatus.COMPLETED

        if not WorkflowCompletionPolicy.all_tasks_terminal(workflow_run):
            return None

        statuses = {
            task.status
            for task in workflow_run.tasks
        }

        if TaskStatus.FAILED in statuses:
            return WorkflowStatus.FAILED

        if statuses <= {
            TaskStatus.COMPLETED,
            TaskStatus.SKIPPED,
        }:
            return WorkflowStatus.COMPLETED

        if TaskStatus.CANCELLED in statuses:
            return WorkflowStatus.CANCELLED

        return None
