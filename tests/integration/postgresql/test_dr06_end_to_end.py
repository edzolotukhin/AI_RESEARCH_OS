"""DR-06 end-to-end deterministic report writer test."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.report.deduplication import compute_content_checksum

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


class Dr06EndToEndPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_deterministic_pipeline_persists_report_and_artifact(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(
            raw_client,
            auth_headers(container._test_api_key_plaintext),
        )

        project_id = client.post("/projects", json={"name": "DR-06 E2E"}).json()["id"]
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]

        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-collect-evidence"], "completed")
        self.assertEqual(tasks["task-extract-evidence"], "completed")
        self.assertEqual(tasks["task-analyze"], "completed")
        self.assertEqual(tasks["task-write-report"], "completed")
        self.assertEqual(terminal["status"], "completed")
        self.assertGreater(terminal["report_count"], 0)
        self.assertGreater(terminal["artifact_count"], 0)
        self.assertTrue(terminal["artifacts_available"])

        reports = client.get(
            f"/projects/{project_id}/reports",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        artifacts = client.get(f"/workflow-runs/{run_id}/artifacts").json()["items"]
        self.assertGreater(len(reports), 0)
        self.assertGreater(len(artifacts), 0)

        artifact_id = artifacts[0]["id"]
        content = client.get(f"/artifacts/{artifact_id}/content").json()
        self.assertEqual(content["media_type"], "text/markdown")
        self.assertTrue(content["content"])
        self.assertEqual(
            content["content_checksum"],
            compute_content_checksum(content["content"]),
        )

        container.shutdown()
        container2 = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                report_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(container2.shutdown)
        reloaded = container2.artifact_service.get_artifact(artifact_id)
        self.assertEqual(reloaded.content_checksum, content["content_checksum"])
        self.assertEqual(
            reloaded.content_checksum,
            compute_content_checksum(reloaded.content),
        )


if __name__ == "__main__":
    unittest.main()
