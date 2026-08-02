"""DR-03 end-to-end deterministic source acquisition test."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)
from application.executors.stage_executors import UnimplementedCapabilityExecutor

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


class Dr03EndToEndPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_deterministic_search_persists_sources_before_report_failure(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
            ),
            overrides=ApplicationOverrides(
                llm_client=mock_llm,
                report_executor=UnimplementedCapabilityExecutor(
                    capability="report",
                    stage="write_report",
                ),
            ),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "DR-03 E2E"}).json()["id"]
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]

        with self.assertRaises(CapabilityNotImplementedError) as exc:
            drain_background_runs(container)
        self.assertEqual(exc.exception.capability, "report")

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "completed")
        self.assertEqual(tasks["task-extract-evidence"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "failed")
        self.assertEqual(terminal["status"], "failed")

        sources = client.get(f"/projects/{project_id}/sources").json()["items"]
        self.assertGreaterEqual(len(sources), 1)
        acquired = [item for item in sources if item["retrieval_status"] == "acquired"]
        self.assertGreaterEqual(len(acquired), 1)

        results = client.get(f"/workflow-runs/{run_id}/results").json()
        collect_results = [
            item for item in results["task_results"]
            if item.get("snapshot", {}).get("definition_id") == "task-collect-evidence"
        ]
        self.assertEqual(len(collect_results), 1)
        shared = collect_results[0]["snapshot"]["shared_state"]["source_acquisition"]
        self.assertGreater(shared["sources_acquired"], 0)
        self.assertTrue(shared["source_ids"])


if __name__ == "__main__":
    unittest.main()
