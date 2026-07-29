import unittest

from application.planner.exceptions import PlannerMappingError
from application.planner.workflow_template_mapper import (
    ResearchPlanWorkflowTemplateMapper,
)

from domain.planning.planner_task import PlannerTask
from domain.planning.research_plan import ResearchPlan
from domain.planning.research_stage import ResearchStage
from domain.project import Project
from domain.value_objects.executor_type import ExecutorType


class WorkflowTemplateMapperTests(unittest.TestCase):

    def setUp(self):
        self.mapper = ResearchPlanWorkflowTemplateMapper()
        self.project = Project(
            id="project-1",
            name="Brand Health 2026",
        )

    def _build_plan(self) -> ResearchPlan:
        plan = ResearchPlan.create(
            id="plan-1",
            name="Brand Health Workflow",
            goal="Evaluate brand awareness.",
            methodology="Survey",
        )

        stage = ResearchStage.create(
            id="stage-design",
            name="Research Design",
            description="Design phase",
        )

        stage.add_task(
            PlannerTask.create(
                id="task-methodology",
                title="Define methodology",
                description="Select methods",
                suggested_agent="planner",
            )
        )
        stage.add_task(
            PlannerTask.create(
                id="task-sample",
                title="Design sample plan",
                description="Define sample",
                suggested_agent="planner",
                dependencies=("task-methodology",),
            )
        )

        plan.add_stage(stage)
        return plan

    def test_from_research_plan_creates_workflow_template(self):
        plan = self._build_plan()

        template = self.mapper.from_research_plan(
            plan,
            self.project,
        )

        self.assertEqual(template.name, "Brand Health Workflow")
        self.assertEqual(len(template.task_definitions), 2)
        self.assertEqual(
            template.task_definitions[0].executor_id,
            "planner",
        )
        self.assertEqual(
            template.task_definitions[0].executor_type,
            ExecutorType.AGENT,
        )
        self.assertEqual(
            template.task_definitions[1].depends_on,
            ["task-methodology"],
        )
        self.assertEqual(
            template.task_definitions[0].metadata["project_id"],
            "project-1",
        )

    def test_empty_suggested_agent_raises_error(self):
        plan = ResearchPlan.create(
            name="Broken Workflow",
            goal="Broken goal",
        )
        stage = ResearchStage.create(
            id="stage-1",
            name="Stage",
        )
        stage.add_task(
            PlannerTask.create(
                id="task-1",
                title="Task 1",
                suggested_agent="planner",
            )
        )
        stage.add_task(
            PlannerTask.create(
                id="task-2",
                title="Task 2",
                suggested_agent="",
            )
        )
        plan.add_stage(stage)

        with self.assertRaises(PlannerMappingError):
            self.mapper.from_research_plan(plan, self.project)

    def test_single_task_raises_error(self):
        plan = ResearchPlan.create(
            name="Single Task Workflow",
            goal="Goal",
        )
        stage = ResearchStage.create(
            id="stage-1",
            name="Stage",
        )
        stage.add_task(
            PlannerTask.create(
                id="task-1",
                title="Only task",
                suggested_agent="planner",
            )
        )
        plan.add_stage(stage)

        with self.assertRaises(PlannerMappingError):
            self.mapper.from_research_plan(plan, self.project)


if __name__ == "__main__":
    unittest.main()
