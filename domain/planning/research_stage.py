"""
AI Research OS

Research Stage entity.

Represents a logical stage within a ResearchPlan.

Responsibilities:
- own PlannerTask entities;
- protect stage invariants;
- expose controlled modification methods.

ResearchStage is a Domain Entity and is always owned by
ResearchPlan.
"""

from __future__ import annotations

from typing import Iterable, Self
from uuid import uuid4

from domain.common.exceptions import (
    InvariantViolationError,
    ValidationError,
)

from .planner_task import PlannerTask


class ResearchStage:
    """
    Logical research stage.

    Examples:
        - Desk Research
        - Questionnaire Design
        - Fieldwork
        - Analysis
        - Reporting
    """

    def __init__(
        self,
        *,
        id: str,
        name: str,
        description: str,
        tasks: Iterable[PlannerTask],
    ) -> None:
        self._id = id
        self._name = name
        self._description = description
        self._tasks: list[PlannerTask] = list(tasks)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        description: str = "",
        id: str | None = None,
    ) -> Self:
        """
        Factory method.

        Generates an identifier when one is not provided.
        """

        name = name.strip()

        if not name:
            raise ValidationError(
                "Research stage name cannot be empty."
            )

        return cls(
            id=id or str(uuid4()),
            name=name,
            description=description.strip(),
            tasks=(),
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def tasks(self) -> tuple[PlannerTask, ...]:
        """
        Immutable view of tasks.
        """
        return tuple(self._tasks)

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def rename(
        self,
        name: str,
    ) -> None:
        """
        Rename the stage.
        """

        name = name.strip()

        if not name:
            raise ValidationError(
                "Research stage name cannot be empty."
            )

        self._name = name

    def change_description(
        self,
        description: str,
    ) -> None:
        """
        Update stage description.
        """

        self._description = description.strip()

    def add_task(
        self,
        task: PlannerTask,
    ) -> None:
        """
        Add a planning task.
        """

        if any(existing.id == task.id for existing in self._tasks):
            raise InvariantViolationError(
                f"PlannerTask '{task.id}' already exists."
            )

        self._tasks.append(task)

    def remove_task(
        self,
        task_id: str,
    ) -> None:
        """
        Remove a planning task.
        """

        for index, task in enumerate(self._tasks):
            if task.id == task_id:
                del self._tasks[index]
                return

        raise InvariantViolationError(
            f"PlannerTask '{task_id}' does not exist."
        )

    def get_task(
        self,
        task_id: str,
    ) -> PlannerTask:
        """
        Return a task by identifier.
        """

        for task in self._tasks:
            if task.id == task_id:
                return task

        raise InvariantViolationError(
            f"PlannerTask '{task_id}' does not exist."
        )

    def has_task(
        self,
        task_id: str,
    ) -> bool:
        """
        Check whether a task exists.
        """

        return any(
            task.id == task_id
            for task in self._tasks
        )