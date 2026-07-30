from __future__ import annotations

from domain.common.exceptions import DomainError
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus


class RuntimeStateTransitionError(DomainError):
    """
    Raised when a runtime state transition is not allowed.
    """

    def __init__(
        self,
        entity: str,
        current: TaskStatus | WorkflowStatus,
        target: TaskStatus | WorkflowStatus,
    ) -> None:
        self.entity = entity
        self.current = current
        self.target = target

        super().__init__(
            f"{entity} cannot transition from {current.value} to {target.value}."
        )
