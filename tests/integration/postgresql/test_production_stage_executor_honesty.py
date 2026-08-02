"""PostgreSQL integration test for DR-02 production stage executor honesty."""

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
    def test_production_runtime_fails_honestly_on_unimplemented_search(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
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

        project_id = client.post("/projects", json={"name": "PG Honest Failure"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()["run_id"]

        try:
            drain_background_runs(container)
        except CapabilityNotImplementedError as exc:
            self.assertEqual(exc.capability, "search")
            self.assertEqual(exc.stage, "collect_sources")
        else:
            self.fail("Expected CapabilityNotImplementedError from production search stage")

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["status"], "failed")
        self.assertFalse(terminal["artifacts_available"])

        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "failed")
        self.assertEqual(tasks["task-analyze"], "skipped")
        self.assertEqual(tasks["task-write-report"], "skipped")

        results = client.get(f"/workflow-runs/{run_id}/results").json()
        self.assertTrue(results["is_terminal"])
        self.assertEqual(results["status"], "failed")
        report_results = [
            item for item in results["task_results"]
            if item["task_id"] == "task-write-report"
        ]
        self.assertEqual(report_results, [])

        artifacts = client.get(f"/workflow-runs/{run_id}/artifacts").json()
        self.assertEqual(artifacts["items"], [])


if __name__ == "__main__":
    unittest.main()
