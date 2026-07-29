import tempfile
import unittest
from unittest.mock import Mock

from application.composition_root import create_application
from application.config import ApplicationConfig, ApplicationOverrides

from domain.ai.llm_response import LLMResponse
from domain.project_brief import ProjectBrief

from runtime.workflow_context import WorkflowContext

from tests.fixtures.planner_responses import VALID_PLANNER_JSON


class AgencyStartResearchTests(unittest.TestCase):

    def test_start_research_without_real_openai(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = create_application(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                ),
                overrides=ApplicationOverrides(
                    llm_client=mock_llm,
                ),
            )
            agency.initialize()

            project = agency.create_project("Brand Health 2026")
            project.brief = ProjectBrief(
                client="Purina",
                project_title="Brand Health 2026",
                business_problem="Assess market position.",
                research_goal="Evaluate brand awareness.",
            )

            context = agency.start_research(project)

        self.assertIsInstance(context, WorkflowContext)
        self.assertIsNotNone(context.workflow_template)
        self.assertEqual(len(context.workflow_template.task_definitions), 2)
        self.assertIsNotNone(context.workflow_run)
        self.assertEqual(len(context.workflow_run.tasks), 2)
        mock_llm.generate.assert_called()


if __name__ == "__main__":
    unittest.main()
