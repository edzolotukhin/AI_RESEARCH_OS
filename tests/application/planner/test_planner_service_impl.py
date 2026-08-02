import unittest



from application.factories.research_plan_factory import ResearchPlanFactory

from application.parsers.planner_response_parser import PlannerResponseParser

from application.planner.service import PlannerServiceImpl



from domain.planning.research_plan import ResearchPlan

from domain.project import Project



from tests.fixtures.planner_responses import LEGACY_PLANNER_RESPONSE





class PlannerServiceImplTests(unittest.TestCase):



    def setUp(self):

        self.service = PlannerServiceImpl(

            response_parser=PlannerResponseParser(),

            plan_factory=ResearchPlanFactory(),

        )

        self.project = Project(

            id="project-1",

            name="Brand Health 2026",

        )



    def test_create_plan_returns_research_plan(self):

        plan = self.service.create_plan(

            self.project,

            LEGACY_PLANNER_RESPONSE,

        )



        self.assertIsInstance(plan, ResearchPlan)

        self.assertEqual(plan.name, "Brand Health Workflow")

        self.assertEqual(plan.stage_count, 1)

        self.assertEqual(plan.stages[0].task_count, 2)



    def test_create_plan_does_not_create_workflow_template(self):

        plan = self.service.create_plan(

            self.project,

            LEGACY_PLANNER_RESPONSE,

        )



        self.assertFalse(hasattr(plan, "task_definitions"))





if __name__ == "__main__":

    unittest.main()

