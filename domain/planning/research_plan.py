"""
AI Research OS

Research Plan Aggregate Root.

ResearchPlan represents a complete business research plan.

Responsibilities:
- own ResearchStage entities;
- protect aggregate invariants;
- manage lifecycle;
- expose controlled modification methods.

ResearchPlan is the Aggregate Root of the Planning domain.
"""

from __future__ import annotations

from typing import Iterable, Self
from uuid import uuid4

from domain.common.exceptions import (
    InvariantViolationError,
    ValidationError,
)

from .research_plan_status import ResearchPlanStatus
from .research_stage import ResearchStage


class ResearchPlan:
    """
    Aggregate Root of the Planning domain.
    """

    def __init__(
        self,
        *,
        id: str,
        name: str,
        goal: str,
        methodology: str,
        status: ResearchPlanStatus,
        stages: Iterable[ResearchStage],
    ) -> None:
        self._id = id
        self._name = name
        self._goal = goal
        self._methodology = methodology
        self._status = status
        self._stages: list[ResearchStage] = list(stages)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        goal: str,
        methodology: str = "",
        id: str | None = None,
    ) -> Self:
        """
        Factory method.
        """

        name = name.strip()
        goal = goal.strip()
        methodology = methodology.strip()

        if not name:
            raise ValidationError(
                "Research plan name cannot be empty."
            )

        if not goal:
            raise ValidationError(
                "Research plan goal cannot be empty."
            )

        return cls(
            id=id or str(uuid4()),
            name=name,
            goal=goal,
            methodology=methodology,
            status=ResearchPlanStatus.DRAFT,
            stages=(),
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def goal(self) -> str:
        return self._goal

    @property
    def methodology(self) -> str:
        return self._methodology

    @property
    def status(self) -> ResearchPlanStatus:
        return self._status

    @property
    def stages(self) -> tuple[ResearchStage, ...]:
        """
        Immutable view of research stages.
        """
        return tuple(self._stages)

    @property
    def stage_count(self) -> int:
        return len(self._stages)

    def rename(
        self,
        name: str,
    ) -> None:
        """
        Rename research plan.
        """

        name = name.strip()

        if not name:
            raise ValidationError(
                "Research plan name cannot be empty."
            )

        self._name = name

    def change_goal(
        self,
        goal: str,
    ) -> None:
        """
        Update business goal.
        """

        goal = goal.strip()

        if not goal:
            raise ValidationError(
                "Research plan goal cannot be empty."
            )

        self._goal = goal

    def change_methodology(
        self,
        methodology: str,
    ) -> None:
        """
        Update methodology.
        """

        self._methodology = methodology.strip()

    def change_status(
        self,
        status: ResearchPlanStatus,
    ) -> None:
        """
        Update lifecycle status.
        """

        if self._status == status:
            return

        self._status = status

    def add_stage(
        self,
        stage: ResearchStage,
    ) -> None:
        """
        Add a research stage.
        """

        if any(
            existing.id == stage.id
            for existing in self._stages
        ):
            raise InvariantViolationError(
                f"ResearchStage '{stage.id}' already exists."
            )

        self._stages.append(stage)

    def remove_stage(
        self,
        stage_id: str,
    ) -> None:
        """
        Remove a research stage.
        """

        for index, stage in enumerate(self._stages):
            if stage.id == stage_id:
                del self._stages[index]
                return

        raise InvariantViolationError(
            f"ResearchStage '{stage_id}' does not exist."
        )

    def get_stage(
        self,
        stage_id: str,
    ) -> ResearchStage:
        """
        Return a stage by identifier.
        """

        for stage in self._stages:
            if stage.id == stage_id:
                return stage

        raise InvariantViolationError(
            f"ResearchStage '{stage_id}' does not exist."
        )

    def has_stage(
        self,
        stage_id: str,
    ) -> bool:
        """
        Check whether stage exists.
        """

        return any(
            stage.id == stage_id
            for stage in self._stages
        )