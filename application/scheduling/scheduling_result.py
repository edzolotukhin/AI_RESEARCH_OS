from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchedulingResult:
    ready_task_ids: tuple[str, ...]
    waiting_task_ids: tuple[str, ...]
    skipped_task_ids: tuple[str, ...]
    unchanged_task_ids: tuple[str, ...]
    evaluated_task_ids: tuple[str, ...]
    transition_count: int
    has_changes: bool
    has_dependency_failures: bool

    @classmethod
    def empty(cls) -> SchedulingResult:
        return cls(
            ready_task_ids=(),
            waiting_task_ids=(),
            skipped_task_ids=(),
            unchanged_task_ids=(),
            evaluated_task_ids=(),
            transition_count=0,
            has_changes=False,
            has_dependency_failures=False,
        )
