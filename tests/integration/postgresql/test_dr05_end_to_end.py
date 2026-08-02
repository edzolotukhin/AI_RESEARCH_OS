"""DR-05 end-to-end deterministic analysis test."""

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


class Dr05EndToEndPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_deterministic_pipeline_persists_findings_before_report_failure(self) -> None:
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
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(raw_client, auth_headers(
            container._test_api_key_plaintext,
        ))

        project_id = client.post("/projects", json={"name": "DR-05 E2E"}).json()["id"]
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
        self.assertTrue(terminal["findings_available"])
        self.assertGreater(terminal["finding_count"], 0)
        self.assertTrue(terminal["insights_available"])
        self.assertGreater(terminal["insight_count"], 0)
        self.assertFalse(terminal["artifacts_available"])

        findings = client.get(
            f"/projects/{project_id}/findings",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        insights = client.get(
            f"/projects/{project_id}/insights",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        evidence = client.get(
            f"/projects/{project_id}/evidence",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        sources = client.get(
            f"/projects/{project_id}/sources",
            params={"workflow_run_id": run_id},
        ).json()["items"]

        self.assertGreater(len(findings), 0)
        self.assertGreater(len(insights), 0)
        for finding in findings:
            self.assertEqual(finding["workflow_run_id"], run_id)
            self.assertTrue(finding["evidence_refs"])
            for evidence_id in finding["evidence_refs"]:
                self.assertTrue(any(item["id"] == evidence_id for item in evidence))
        for insight in insights:
            self.assertEqual(insight["workflow_run_id"], run_id)
            self.assertTrue(insight["finding_refs"])
            for finding_id in insight["finding_refs"]:
                self.assertTrue(any(item["id"] == finding_id for item in findings))
        for item in evidence:
            self.assertTrue(any(source["id"] == item["source_id"] for source in sources))


if __name__ == "__main__":
    unittest.main()
