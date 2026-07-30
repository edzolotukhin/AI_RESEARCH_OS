"""
AI Research OS

Research Plan Factory.

Creates ResearchPlan aggregate roots from immutable DTO objects.

Responsibilities:
- construct domain objects;
- preserve aggregate invariants;
- isolate DTO-to-Domain conversion.

The factory contains no workflow logic and no infrastructure
dependencies.
"""

from __future__ import annotations

from application.dto.planner_plan_dto import PlannerPlanDTO
from application.dto.planner_task_dto import PlannerTaskDTO
from application.dto.research_stage_dto import ResearchStageDTO

from domain.planning.planner_task import PlannerTask
from domain.planning.research_plan import ResearchPlan
from domain.planning.research_stage import ResearchStage


class ResearchPlanFactory:
    """Creates ResearchPlan aggregates from planner DTOs."""

    def create(
        self,
        dto: PlannerPlanDTO,
    ) -> ResearchPlan:
        """
        Build a ResearchPlan aggregate from PlannerPlanDTO.
        """

        plan = self._create_plan(dto)

        for stage_dto in dto.stages:
            plan.add_stage(
                self._create_stage(stage_dto)
            )

        return plan

    @staticmethod
    def _create_plan(
        dto: PlannerPlanDTO,
    ) -> ResearchPlan:
        """
        Create the aggregate root.
        """

        return ResearchPlan.create(
            name=dto.name,
            goal=dto.goal,
            methodology=dto.methodology,
        )

    def _create_stage(
        self,
        stage_dto: ResearchStageDTO,
    ) -> ResearchStage:
        """
        Create a ResearchStage entity.
        """

        stage = ResearchStage.create(
            id=stage_dto.id,
            name=stage_dto.name,
            description=stage_dto.description,
        )

        for task_dto in stage_dto.tasks:
            stage.add_task(
                self._create_task(task_dto)
            )

        return stage

    @staticmethod
    def _create_task(
        task_dto: PlannerTaskDTO,
    ) -> PlannerTask:
        """
        Create a PlannerTask entity.
        """

        return PlannerTask.create(
            id=task_dto.id,
            title=task_dto.title,
            description=task_dto.description,
            executor_id=task_dto.executor_id,
            dependencies=tuple(task_dto.dependencies),
        )