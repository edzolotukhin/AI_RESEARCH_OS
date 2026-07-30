from __future__ import annotations

from dataclasses import dataclass

from application.scheduling.scheduling_result import SchedulingResult
from domain.task import Task


@dataclass(frozen=True)
class RuntimeProgress:
    has_ready_tasks: bool
    has_state_changes: bool
    all_tasks_terminal: bool
    is_finished: bool
    should_stop_iteration: bool

    @classmethod
    def from_scheduling(
        cls,
        *,
        scheduling_result: SchedulingResult,
        ready_task: Task | None,
        all_tasks_terminal: bool,
    ) -> RuntimeProgress:
        has_ready_tasks = ready_task is not None
        has_state_changes = scheduling_result.has_changes
        is_finished = all_tasks_terminal
        should_stop_iteration = is_finished or (
            not has_ready_tasks and not has_state_changes
        )

        return cls(
            has_ready_tasks=has_ready_tasks,
            has_state_changes=has_state_changes,
            all_tasks_terminal=all_tasks_terminal,
            is_finished=is_finished,
            should_stop_iteration=should_stop_iteration,
        )
