from __future__ import annotations

from domain.planning.planner_task import PlannerTask
from domain.planning.research_plan import ResearchPlan
from domain.project import Project
from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder

from domain.value_objects.executor_type import ExecutorType

from .exceptions import PlannerMappingError


class ResearchPlanWorkflowTemplateMapper:
    """
    Maps a ResearchPlan aggregate to an executable WorkflowTemplate.
    """

    def from_research_plan(
        self,
        plan: ResearchPlan,
        project: Project,
    ) -> WorkflowTemplate:
        if plan.stage_count == 0:
            raise PlannerMappingError(
                "ResearchPlan must contain at least one stage."
            )

        task_count = sum(
            stage.task_count
            for stage in plan.stages
        )

        if task_count < 2:
            raise PlannerMappingError(
                "ResearchPlan must contain at least two tasks."
            )

        builder = WorkflowTemplateBuilder(
            id=plan.id,
            name=plan.name,
        )

        for stage in plan.stages:
            for task in stage.tasks:
                self._add_task(
                    builder,
                    task,
                    stage.id,
                    stage.name,
                    project,
                )

        return builder.build()

    @staticmethod
    def _add_task(
        builder: WorkflowTemplateBuilder,
        task: PlannerTask,
        stage_id: str,
        stage_name: str,
        project: Project,
    ) -> None:
        executor_id = task.suggested_agent.strip()

        if not executor_id:
            raise PlannerMappingError(
                f"Task '{task.id}' has an empty suggested_agent."
            )

        builder.add_task(
            id=task.id,
            name=task.title,
            executor_id=executor_id,
            executor_type=ExecutorType.AGENT,
            depends_on=list(task.dependencies),
            metadata={
                "description": task.description,
                "stage_id": stage_id,
                "stage_name": stage_name,
                "project_id": project.id,
            },
        )
