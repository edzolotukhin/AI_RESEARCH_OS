from __future__ import annotations

from domain.value_objects.task_status import TaskStatus


class TaskSchedulingInvariantError(Exception):
    """Raised when WorkflowRun contains an unsafe runtime scheduling state."""

    def __init__(
        self,
        *,
        workflow_run_id: str,
        task_id: str,
        message: str,
        dependency_ids: tuple[str, ...] = (),
        dependency_statuses: dict[str, TaskStatus] | None = None,
    ) -> None:
        self.workflow_run_id = workflow_run_id
        self.task_id = task_id
        self.message = message
        self.dependency_ids = dependency_ids
        self.dependency_statuses = (
            dict(dependency_statuses)
            if dependency_statuses is not None
            else {}
        )
        super().__init__(message)
