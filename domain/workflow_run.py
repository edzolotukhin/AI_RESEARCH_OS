from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from domain.exceptions.runtime_state_transition_error import (
    RuntimeStateTransitionError,
)
from domain.runtime.state_machine import (
    TASK_STATE_MACHINE,
    WORKFLOW_RUN_STATE_MACHINE,
)
from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.task import Task
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.common.exceptions import ValidationError


@dataclass
class WorkflowRun:
    """
    Экземпляр выполнения WorkflowTemplate.

    Domain-модель состояния Workflow.
    Выполнение Workflow осуществляется Application-слоем.
    """

    id: str = field(default_factory=lambda: str(uuid4()))

    project_id: str = ""

    workflow_template_id: str = ""

    tasks: list[Task] = field(default_factory=list)

    dependency_graph: TaskDependencyGraph = field(
        default_factory=TaskDependencyGraph,
    )

    satisfied_skipped_task_ids: set[str] = field(default_factory=set)

    status: WorkflowStatus = WorkflowStatus.CREATED

    def __post_init__(self) -> None:
        object.__setattr__(self, "_status_initialized", True)

    def __setattr__(
        self,
        name: str,
        value: object,
    ) -> None:
        if (
            name == "status"
            and getattr(self, "_status_initialized", False)
        ):
            raise AttributeError(
                "WorkflowRun.status must be changed via domain methods."
            )

        super().__setattr__(name, value)

    @property
    def is_terminal(self) -> bool:
        return WORKFLOW_RUN_STATE_MACHINE.is_terminal(self.status)

    def ready(self) -> None:
        self._transition_to(WorkflowStatus.READY)

    def start(self) -> None:
        if self.status != WorkflowStatus.READY:
            raise RuntimeStateTransitionError(
                "WorkflowRun",
                self.status,
                WorkflowStatus.RUNNING,
            )

        self._transition_to(WorkflowStatus.RUNNING)

    def pause(self) -> None:
        if self.status != WorkflowStatus.RUNNING:
            raise RuntimeStateTransitionError(
                "WorkflowRun",
                self.status,
                WorkflowStatus.PAUSED,
            )

        self._transition_to(WorkflowStatus.PAUSED)

    def resume(self) -> None:
        if self.status != WorkflowStatus.PAUSED:
            raise RuntimeStateTransitionError(
                "WorkflowRun",
                self.status,
                WorkflowStatus.RUNNING,
            )

        self._transition_to(WorkflowStatus.RUNNING)

    def complete(self) -> None:
        if self.status != WorkflowStatus.RUNNING:
            raise RuntimeStateTransitionError(
                "WorkflowRun",
                self.status,
                WorkflowStatus.COMPLETED,
            )

        self._transition_to(WorkflowStatus.COMPLETED)

    def fail(self) -> None:
        if self.status != WorkflowStatus.RUNNING:
            raise RuntimeStateTransitionError(
                "WorkflowRun",
                self.status,
                WorkflowStatus.FAILED,
            )

        self._transition_to(WorkflowStatus.FAILED)

    def cancel(self) -> None:
        self._transition_to(WorkflowStatus.CANCELLED)

    def validate_dependency_graph(self) -> None:
        task_ids = {task.id for task in self.tasks}
        graph_task_ids = set(self.dependency_graph.topological_order())

        if graph_task_ids - task_ids:
            raise ValidationError(
                "Dependency graph contains task ids that are not in WorkflowRun."
            )

        if task_ids - graph_task_ids:
            raise ValidationError(
                "WorkflowRun contains tasks that are missing from dependency graph."
            )

        if self.satisfied_skipped_task_ids - task_ids:
            raise ValidationError(
                "Satisfied skipped dependencies reference unknown tasks."
            )

        task_index = {task.id: task for task in self.tasks}
        if any(
            task_index[task_id].status != TaskStatus.SKIPPED
            for task_id in self.satisfied_skipped_task_ids
        ):
            raise ValidationError(
                "Satisfied skipped dependency must have SKIPPED task status."
            )

        if self.tasks:
            self.dependency_graph.validate()

    def skip_task_as_satisfied_dependency(self, task: Task) -> None:
        """Record an explicit application-authorized no-op dependency."""
        if task not in self.tasks:
            raise ValidationError("Satisfied skipped dependency is not in WorkflowRun.")
        if not task.is_terminal:
            task.skip()
        if task.status != TaskStatus.SKIPPED:
            raise ValidationError("Satisfied dependency must be skipped.")
        self.satisfied_skipped_task_ids.add(task.id)

    @property
    def progress(self) -> int:
        """
        Процент выполнения Workflow.
        Пока заглушка.
        """
        return 0

    @property
    def artifacts(self) -> list[Any]:
        """
        Артефакты, созданные данным WorkflowRun.

        Пока заглушка.
        """
        return []

    def _transition_to(
        self,
        target: WorkflowStatus,
    ) -> None:
        WORKFLOW_RUN_STATE_MACHINE.validate_transition(
            self.status,
            target,
        )
        object.__setattr__(self, "status", target)
