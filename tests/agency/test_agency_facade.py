import inspect
import unittest
from unittest.mock import Mock

from agency.agency import Agency

from loaders.agent_loader import AgentLoader


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
            agent_loader=Mock(spec=AgentLoader),
            project_factory=Mock(),
            project_repository=Mock(),
            planner_agent=Mock(),
            workflow_run_factory=Mock(),
            workflow_engine=Mock(),
            workflow_run_id="run-test",
        )

        self.assertFalse(hasattr(agency, "registry"))
        self.assertFalse(hasattr(agency, "llm_client"))
        self.assertFalse(hasattr(agency, "executor_resolver"))

    def test_agency_does_not_create_infrastructure_in_init(self):
        source = inspect.getsource(Agency.__init__)

        self.assertNotIn("Registry(", source)
        self.assertNotIn("OpenAIClient", source)
        self.assertNotIn("PlannerServiceImpl", source)
        self.assertNotIn("WorkflowEngine(", source)


if __name__ == "__main__":
    unittest.main()
