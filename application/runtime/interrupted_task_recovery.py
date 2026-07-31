from __future__ import annotations

from domain.task import Task
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun


INTERRUPTED_RUNNING_TASK_REASON = (
    "Task was RUNNING when the process stopped; marked FAILED during "
    "single-process recovery (no worker lease)."
)


def recover_interrupted_running_tasks(
    workflow_run: WorkflowRun,
) -> list[Task]:
    """
    Single-process recovery policy for PF-04.

    RUNNING tasks are not re-executed automatically. They are marked FAILED so
    dependents can be skipped and the workflow can finalize deterministically.
    """
    recovered: list[Task] = []

    for task in workflow_run.tasks:
        if task.status != TaskStatus.RUNNING:
            continue

        task.fail()
        recovered.append(task)

    return recovered
