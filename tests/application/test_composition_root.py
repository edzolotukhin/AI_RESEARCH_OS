import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agency.agency import Agency
from application.composition_root import create_application
from application.config import ApplicationConfig, ApplicationOverrides

from domain.ai.llm_response import LLMResponse
from domain.project_brief import ProjectBrief

from infrastructure.project_repository import ProjectRepository

from runtime.workflow_context import WorkflowContext

from tests.fixtures.planner_responses import VALID_PLANNER_JSON


class CompositionRootTests(unittest.TestCase):

    def test_create_application_returns_agency(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        agency = create_application(
            overrides=ApplicationOverrides(
                llm_client=mock_llm,
            ),
        )

        self.assertIsInstance(agency, Agency)

    def test_create_application_uses_llm_client_override_without_openai(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            agency = create_application(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    workflow_run_id="test-run",
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
            mock_llm.generate.assert_called()
            self.assertTrue(any(Path(temp_dir).iterdir()))

    def test_create_application_uses_project_repository_override(self):
        custom_repository = Mock(spec=ProjectRepository)
        custom_repository.create_project.return_value = Path("mock-dir")

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=VALID_PLANNER_JSON,
        )

        agency = create_application(
            overrides=ApplicationOverrides(
                llm_client=mock_llm,
                project_repository=custom_repository,
            ),
        )

        project = agency.create_project("Test Project")

        custom_repository.create_project.assert_called_once_with(project)
        custom_repository.save_project.assert_called_once_with(project)


if __name__ == "__main__":
    unittest.main()
