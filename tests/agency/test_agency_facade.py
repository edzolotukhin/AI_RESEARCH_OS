import inspect
import unittest
from unittest.mock import Mock

from agency.agency import Agency

from application.services.project_service import ProjectService


class AgencyFacadeTests(unittest.TestCase):

    def test_agency_import_does_not_require_openai_module(self):
        import importlib
        import sys

        openai_modules = [
            name
            for name in sys.modules
            if name == "openai" or name.startswith("openai.")
        ]

        for name in openai_modules:
            sys.modules.pop(name, None)

        module = importlib.import_module("agency.agency")

        self.assertTrue(hasattr(module, "Agency"))
        self.assertNotIn("openai", sys.modules)

    def test_agency_receives_dependencies_via_constructor(self):
        agency = Agency(
            agent_loader=Mock(),
            project_service=Mock(spec=ProjectService),
            planner_agent=Mock(),
            workflow_run_factory=Mock(),
            workflow_engine=Mock(),
        )

        self.assertFalse(hasattr(agency, "registry"))
        self.assertFalse(hasattr(agency, "llm_client"))
        self.assertFalse(hasattr(agency, "executor_resolver"))

    def test_agency_create_project_delegates_to_project_service(self):
        project_service = Mock(spec=ProjectService)
        expected_project = Mock()
        project_service.create_project.return_value = expected_project

        agency = Agency(
            agent_loader=Mock(),
            project_service=project_service,
            planner_agent=Mock(),
            workflow_run_factory=Mock(),
            workflow_engine=Mock(),
        )

        result = agency.create_project("Test Project")

        project_service.create_project.assert_called_once_with("Test Project")
        self.assertIs(result, expected_project)

    def test_agency_does_not_reference_project_repository(self):
        source = inspect.getsource(Agency)

        self.assertNotIn("ProjectRepository", source)
        self.assertNotIn("_project_repository", source)

    def test_agency_does_not_create_infrastructure_in_init(self):
        source = inspect.getsource(Agency.__init__)

        self.assertNotIn("Registry(", source)
        self.assertNotIn("OpenAIClient", source)
        self.assertNotIn("PlannerServiceImpl", source)
        self.assertNotIn("WorkflowEngine(", source)


if __name__ == "__main__":
    unittest.main()
