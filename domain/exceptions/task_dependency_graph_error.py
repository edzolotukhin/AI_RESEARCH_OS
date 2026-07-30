from __future__ import annotations

from domain.common.exceptions import DomainError


class TaskDependencyGraphError(DomainError):
    """Base class for TaskDependencyGraph errors."""


class TaskNotFoundInDependencyGraphError(TaskDependencyGraphError):
    """Raised when a task id is not present in the graph."""

    def __init__(
        self,
        task_id: str,
    ) -> None:
        self.task_id = task_id
        super().__init__(
            f"Task '{task_id}' was not found in the dependency graph."
        )


class TaskSelfDependencyError(TaskDependencyGraphError):
    """Raised when a task depends on itself."""

    def __init__(
        self,
        task_id: str,
    ) -> None:
        self.task_id = task_id
        super().__init__(
            f"Task '{task_id}' cannot depend on itself."
        )


class TaskDependencyCycleError(TaskDependencyGraphError):
    """Raised when adding a dependency would create a cycle."""

    def __init__(
        self,
        dependency_task_id: str,
        dependent_task_id: str,
        cycle_path: tuple[str, ...],
    ) -> None:
        self.dependency_task_id = dependency_task_id
        self.dependent_task_id = dependent_task_id
        self.cycle_path = cycle_path

        path = " -> ".join(cycle_path)
        super().__init__(
            "Adding dependency "
            f"'{dependency_task_id}' -> '{dependent_task_id}' "
            f"would create a cycle: {path}."
        )
