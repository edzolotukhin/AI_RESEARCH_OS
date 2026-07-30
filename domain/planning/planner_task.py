"""
AI Research OS

Planner Task entity.

Represents a single business planning task belonging to a
ResearchStage.

PlannerTask is a Domain Entity. It contains business state,
protects its own invariants and exposes controlled state changes.
"""

from __future__ import annotations

from typing import Self
from uuid import uuid4

from domain.common.exceptions import ValidationError


class PlannerTask:
    """
    Business planning task.

    PlannerTask is a Domain Entity and should be created only
    through PlannerTask.create().
    """

    def __init__(
        self,
        *,
        id: str,
        title: str,
        description: str,
        executor_id: str,
        dependencies: tuple[str, ...],
    ) -> None:
        self._id = id
        self._title = title
        self._description = description
        self._executor_id = executor_id
        self._dependencies = tuple(dependencies)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        description: str = "",
        executor_id: str = "",
        dependencies: tuple[str, ...] = (),
        id: str | None = None,
    ) -> Self:
        """
        Factory method.
        """

        title = title.strip()

        if not title:
            raise ValidationError(
                "Planner task title cannot be empty."
            )

        return cls(
            id=id or str(uuid4()),
            title=title,
            description=description.strip(),
            executor_id=executor_id.strip(),
            dependencies=tuple(dependencies),
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    @property
    def executor_id(self) -> str:
        return self._executor_id

    @property
    def dependencies(self) -> tuple[str, ...]:
        return self._dependencies

    @property
    def dependency_count(self) -> int:
        return len(self._dependencies)

    def rename(
        self,
        title: str,
    ) -> None:
        """
        Rename task.
        """

        title = title.strip()

        if not title:
            raise ValidationError(
                "Planner task title cannot be empty."
            )

        self._title = title

    def change_description(
        self,
        description: str,
    ) -> None:
        """
        Update task description.
        """

        self._description = description.strip()

    def assign_executor(
        self,
        executor_id: str,
    ) -> None:
        """
        Update the task executor reference.
        """

        self._executor_id = executor_id.strip()

    def change_dependencies(
        self,
        dependencies: tuple[str, ...],
    ) -> None:
        """
        Replace dependency list.
        """

        self._dependencies = tuple(dependencies)
