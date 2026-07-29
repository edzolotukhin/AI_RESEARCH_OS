from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from domain.value_objects.task_status import TaskStatus


class SchedulingDecisionReason(str, Enum):
    ROOT_TASK = "ROOT_TASK"
    ALL_DEPENDENCIES_COMPLETED = "ALL_DEPENDENCIES_COMPLETED"
    WAITING_FOR_DEPENDENCIES = "WAITING_FOR_DEPENDENCIES"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    NO_CHANGE = "NO_CHANGE"


@dataclass(frozen=True)
class TaskSchedulingDecision:
    task_id: str
    current_status: TaskStatus
    target_status: TaskStatus | None
    reason: SchedulingDecisionReason
    dependency_ids: tuple[str, ...] = ()
