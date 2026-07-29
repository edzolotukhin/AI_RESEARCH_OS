from __future__ import annotations

from dataclasses import dataclass, field

from domain.exceptions.runtime_state_transition_error import (
    RuntimeStateTransitionError,
)
from domain.runtime.state_machine import TASK_STATE_MACHINE
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus


@dataclass
class Task:
    """
    Экземпляр задачи в рамках WorkflowRun.
    Создается на основе TaskDefinition.
    """

    id: str

    definition_id: str

    name: str

    description: str = ""

    executor_id: str = ""

    executor_type: ExecutorType = ExecutorType.AGENT

    depends_on: list[str] = field(default_factory=list)

    status: TaskStatus = TaskStatus.CREATED

    created_at: str = ""

    updated_at: str = ""

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
                "Task.status must be changed via domain methods."
            )

        super().__setattr__(name, value)

    @property
    def is_terminal(self) -> bool:
        return TASK_STATE_MACHINE.is_terminal(self.status)

    def schedule(self) -> None:
        self._transition_to(TaskStatus.WAITING)

    def ready(self) -> None:
        self._transition_to(TaskStatus.READY)

    def start(self) -> None:
        if self.status != TaskStatus.READY:
            raise RuntimeStateTransitionError(
                "Task",
                self.status,
                TaskStatus.RUNNING,
            )

        self._transition_to(TaskStatus.RUNNING)

    def pause(self) -> None:
        if self.status != TaskStatus.RUNNING:
            raise RuntimeStateTransitionError(
                "Task",
                self.status,
                TaskStatus.PAUSED,
            )

        self._transition_to(TaskStatus.PAUSED)

    def resume(self) -> None:
        if self.status != TaskStatus.PAUSED:
            raise RuntimeStateTransitionError(
                "Task",
                self.status,
                TaskStatus.RUNNING,
            )

        self._transition_to(TaskStatus.RUNNING)

    def complete(self) -> None:
        if self.status != TaskStatus.RUNNING:
            raise RuntimeStateTransitionError(
                "Task",
                self.status,
                TaskStatus.COMPLETED,
            )

        self._transition_to(TaskStatus.COMPLETED)

    def fail(self) -> None:
        if self.status != TaskStatus.RUNNING:
            raise RuntimeStateTransitionError(
                "Task",
                self.status,
                TaskStatus.FAILED,
            )

        self._transition_to(TaskStatus.FAILED)

    def cancel(self) -> None:
        self._transition_to(TaskStatus.CANCELLED)

    def skip(self) -> None:
        self._transition_to(TaskStatus.SKIPPED)

    def _transition_to(
        self,
        target: TaskStatus,
    ) -> None:
        TASK_STATE_MACHINE.validate_transition(
            self.status,
            target,
        )
        object.__setattr__(self, "status", target)
