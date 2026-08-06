from __future__ import annotations

from domain.task import Task
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun

from application.runtime.task_result_codec import is_progress_checkpoint


INTERRUPTED_RUNNING_TASK_REASON = (
    "Task was RUNNING when the process stopped; marked FAILED during "
    "single-process recovery (no worker lease)."
)


def recover_interrupted_running_tasks(
    workflow_run: WorkflowRun,
    task_results: dict[str, object] | None = None,
) -> list[Task]:
    """
    Single-process recovery policy for PF-04.

    RUNNING tasks with a durable progress checkpoint are requeued for retry.
    Other RUNNING tasks are marked FAILED so dependents can be skipped and the
    workflow can finalize deterministically.
    """
    recovered: list[Task] = []
    snapshots = task_results or {}

    for task in workflow_run.tasks:
        if task.status != TaskStatus.RUNNING:
            continue

        snapshot = snapshots.get(task.id)
        if is_progress_checkpoint(snapshot if isinstance(snapshot, dict) else None):
            task.requeue_after_interrupt()
        else:
            task.fail()
        recovered.append(task)

    return recovered
