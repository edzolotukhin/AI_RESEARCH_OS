import unittest



from application.factories.research_plan_factory import ResearchPlanFactory

from application.parsers.planner_response_parser import PlannerResponseParser

from application.planner.service import PlannerServiceImpl

from application.planner.workflow_template_mapper import (

    ResearchPlanWorkflowTemplateMapper,

)



from domain.factories.task_factory import TaskFactory

from domain.factories.workflow_run_factory import WorkflowRunFactory

from domain.project import Project



from tests.fixtures.planner_responses import VALID_PLANNER_RESPONSE





class WorkflowRunFactoryPlannerTests(unittest.TestCase):



    def setUp(self):

        self.service = PlannerServiceImpl(

            response_parser=PlannerResponseParser(),

            plan_factory=ResearchPlanFactory(),

        )

        self.workflow_mapper = ResearchPlanWorkflowTemplateMapper()

        self.project = Project(

            id="project-1",

            name="Brand Health 2026",

        )

        self.workflow_run_factory = WorkflowRunFactory(

            task_factory=TaskFactory(),

        )



    def test_create_run_from_planner_template(self):

        plan = self.service.create_plan(

            self.project,

            VALID_PLANNER_RESPONSE,

        )

        template = self.workflow_mapper.from_research_plan(

            plan,

            self.project,

        )



        workflow_run = self.workflow_run_factory.create(

            template=template,

            run_id="run-001",

        )



        self.assertEqual(workflow_run.id, "run-001")

        self.assertEqual(len(workflow_run.tasks), 2)

        self.assertEqual(

            workflow_run.tasks[0].executor_id,

            "planner",

        )

        self.assertEqual(

            workflow_run.tasks[1].depends_on,

            ["task-methodology"],

        )

        by_definition = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }
        graph = workflow_run.dependency_graph

        self.assertTrue(
            graph.has_dependency(
                by_definition["task-methodology"],
                by_definition["task-sample"],
            ),
        )
        workflow_run.validate_dependency_graph()

    def test_create_generates_uuid_when_run_id_is_omitted(self):
        plan = self.service.create_plan(
            self.project,
            VALID_PLANNER_RESPONSE,
        )
        template = self.workflow_mapper.from_research_plan(
            plan,
            self.project,
        )

        workflow_run = self.workflow_run_factory.create(template=template)

        from uuid import UUID

        UUID(workflow_run.id)


if __name__ == "__main__":

    unittest.main()

