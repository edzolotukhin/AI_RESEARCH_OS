import unittest

from application.planner.executor_catalog import ExecutorCatalog
from application.planner.executor_definitions import AGENT_EXECUTOR_CAPABILITIES
from domain.value_objects.executor_type import ExecutorType


class ExecutorCatalogTests(unittest.TestCase):

    def test_catalog_contains_registered_executor_ids(self):
        catalog = ExecutorCatalog.from_capabilities(
            AGENT_EXECUTOR_CAPABILITIES,
        )

        self.assertEqual(
            catalog.executor_ids,
            (
                "planner",
                "search",
                "evidence",
                "research_quality",
                "analysis",
                "report",
                "review",
                "proposal",
            ),
        )

    def test_catalog_rejects_duplicate_ids(self):
        duplicate = (
            AGENT_EXECUTOR_CAPABILITIES[0],
            AGENT_EXECUTOR_CAPABILITIES[0],
        )

        with self.assertRaises(ValueError):
            ExecutorCatalog.from_capabilities(duplicate)

    def test_catalog_is_immutable(self):
        catalog = ExecutorCatalog.from_capabilities(
            AGENT_EXECUTOR_CAPABILITIES,
        )

        with self.assertRaises(TypeError):
            catalog.capabilities[0] = catalog.capabilities[0]

    def test_catalog_matches_agent_executor_definitions(self):
        catalog = ExecutorCatalog.from_capabilities(
            AGENT_EXECUTOR_CAPABILITIES,
        )

        for capability in AGENT_EXECUTOR_CAPABILITIES:
            self.assertTrue(catalog.contains(capability.executor_id))
            self.assertEqual(capability.executor_type, ExecutorType.AGENT)


if __name__ == "__main__":
    unittest.main()
