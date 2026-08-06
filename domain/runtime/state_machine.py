from __future__ import annotations

from typing import Generic, TypeVar

from domain.exceptions.runtime_state_transition_error import (
    RuntimeStateTransitionError,
)
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus

State = TypeVar("State")


class RuntimeStateMachine(Generic[State]):
    """
    Single source of truth for allowed runtime state transitions.
    """

    def __init__(
        self,
        *,
        entity_name: str,
        transitions: dict[State, frozenset[State]],
        terminal_states: frozenset[State],
    ) -> None:
        self._entity_name = entity_name
        self._transitions = transitions
        self._terminal_states = terminal_states

    def is_terminal(
        self,
        state: State,
    ) -> bool:
        return state in self._terminal_states

    def can_transition(
        self,
        current: State,
        target: State,
    ) -> bool:
        if self.is_terminal(current):
            return False

        return target in self._transitions.get(current, frozenset())

    def validate_transition(
        self,
        current: State,
        target: State,
    ) -> None:
        if not self.can_transition(current, target):
            raise RuntimeStateTransitionError(
                self._entity_name,
                current,
                target,
            )

    def allowed_targets(
        self,
        current: State,
    ) -> frozenset[State]:
        if self.is_terminal(current):
            return frozenset()

        return self._transitions.get(current, frozenset())


WORKFLOW_RUN_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.CREATED: frozenset(
        {
            WorkflowStatus.READY,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.READY: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.RUNNING: frozenset(
        {
            WorkflowStatus.PAUSED,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.PAUSED: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
}

WORKFLOW_RUN_TERMINAL_STATES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    }
)

WORKFLOW_RUN_STATE_MACHINE = RuntimeStateMachine(
    entity_name="WorkflowRun",
    transitions=WORKFLOW_RUN_TRANSITIONS,
    terminal_states=WORKFLOW_RUN_TERMINAL_STATES,
)

TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset(
        {
            TaskStatus.WAITING,
            TaskStatus.READY,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
    ),
    TaskStatus.WAITING: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
    ),
    TaskStatus.READY: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.PAUSED,
            TaskStatus.READY,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PAUSED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}

TASK_TERMINAL_STATES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    }
)

TASK_STATE_MACHINE = RuntimeStateMachine(
    entity_name="Task",
    transitions=TASK_TRANSITIONS,
    terminal_states=TASK_TERMINAL_STATES,
)
