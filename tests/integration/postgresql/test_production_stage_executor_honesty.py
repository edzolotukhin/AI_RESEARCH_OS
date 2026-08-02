"""PostgreSQL integration test for production stage executor honesty."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class ProductionStageExecutorHonestyPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_production_runtime_fails_honestly_on_unimplemented_report(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        container._test_llm_client = mock_llm
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "PG DR-05 Honesty"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()["run_id"]

        try:
            drain_background_runs(container)
        except CapabilityNotImplementedError as exc:
            self.assertEqual(exc.capability, "report")
            self.assertEqual(exc.stage, "write_report")
        else:
            self.fail("Expected CapabilityNotImplementedError from production report stage")

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["status"], "failed")
        self.assertTrue(terminal["sources_available"])
        self.assertGreater(terminal["source_count"], 0)
        self.assertTrue(terminal["evidence_available"])
        self.assertGreater(terminal["evidence_count"], 0)
        self.assertTrue(terminal["findings_available"])
        self.assertGreater(terminal["finding_count"], 0)
        self.assertTrue(terminal["insights_available"])
        self.assertGreater(terminal["insight_count"], 0)

        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "completed")
        self.assertEqual(tasks["task-extract-evidence"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "failed")

        sources = client.get(f"/projects/{project_id}/sources").json()["items"]
        self.assertGreater(len(sources), 0)
        self.assertTrue(all("provider" not in item.get("metadata", {}) for item in sources))


if __name__ == "__main__":
    unittest.main()
