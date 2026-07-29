import unittest

from application.dto.planner_plan_dto import PlannerPlanDTO
from application.dto.planner_task_dto import PlannerTaskDTO
from application.dto.research_stage_dto import ResearchStageDTO
from application.factories.research_plan_factory import ResearchPlanFactory

from tests.fixtures.planner_responses import VALID_PLANNER_RESPONSE


class ResearchPlanFactoryTests(unittest.TestCase):

    def setUp(self):
        self.factory = ResearchPlanFactory()

    def test_create_from_dto(self):
        dto = PlannerPlanDTO(
            name=VALID_PLANNER_RESPONSE["name"],
            goal=VALID_PLANNER_RESPONSE["goal"],
            methodology=VALID_PLANNER_RESPONSE["methodology"],
            stages=(
                ResearchStageDTO(
                    id="stage-design",
                    name="Research Design",
                    description="Define methodology and sample design.",
                    tasks=(
                        PlannerTaskDTO(
                            id="task-methodology",
                            title="Define methodology",
                            description="Select research methods and metrics.",
                            suggested_agent="planner",
                            dependencies=(),
                        ),
                        PlannerTaskDTO(
                            id="task-sample",
                            title="Design sample plan",
                            description="Define target audience and sample size.",
                            suggested_agent="planner",
                            dependencies=("task-methodology",),
                        ),
                    ),
                ),
            ),
        )

        plan = self.factory.create(dto)

        self.assertEqual(plan.name, "Brand Health Workflow")
        self.assertEqual(plan.stage_count, 1)
        self.assertEqual(plan.stages[0].task_count, 2)
        self.assertEqual(
            plan.stages[0].tasks[0].suggested_agent,
            "planner",
        )
        self.assertEqual(
            plan.stages[0].tasks[1].dependencies,
            ("task-methodology",),
        )


if __name__ == "__main__":
    unittest.main()
