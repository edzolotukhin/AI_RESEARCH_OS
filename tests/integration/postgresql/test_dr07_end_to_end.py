"""DR-07 end-to-end quality gate tests."""

from __future__ import annotations

import os
import unittest
from uuid import uuid4

from dataclasses import replace

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.review.exceptions import ReviewError

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


class Dr07EndToEndPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def _build_client(self, *, max_revision_attempts: int = 1):
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=replace(
                postgresql_application_config(
                    deterministic_stage_executors=False,
                    search_provider="deterministic",
                    evidence_extractor="deterministic",
                    analysis_engine="deterministic",
                    report_engine="deterministic",
                    review_engine="deterministic",
                ),
                review_max_revision_attempts=max_revision_attempts,
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
        return client, container

    def test_clean_report_approves_and_completes(self) -> None:
        client, container = self._build_client()
        project_id = client.post("/projects", json={"name": "DR-07 Approve"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": f"dr07-approve-{uuid4()}"},
        ).json()["run_id"]
        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-review-report"], "completed")
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["final_review_verdict"], "approve")
        self.assertTrue(terminal["final_artifact_available"])
        self.assertIsNotNone(terminal["final_artifact_id"])

        reviews = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        self.assertGreaterEqual(len(reviews), 1)
        self.assertEqual(reviews[-1]["verdict"], "approve")

        artifact = container.artifact_service.get_artifact(terminal["final_artifact_id"])
        self.assertEqual(artifact.status, "approved")

    def test_revise_then_approve_completes(self) -> None:
        os.environ["DETERMINISTIC_REVIEW_SCENARIO"] = "revise_once"
        self.addCleanup(os.environ.pop, "DETERMINISTIC_REVIEW_SCENARIO", None)
        client, container = self._build_client(max_revision_attempts=1)
        project_id = client.post("/projects", json={"name": "DR-07 Revise"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": f"dr07-revise-{uuid4()}"},
        ).json()["run_id"]
        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["final_review_verdict"], "approve")
        self.assertTrue(terminal["final_artifact_available"])

        reviews = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        verdicts = [item["verdict"] for item in reviews]
        self.assertIn("revise", verdicts)
        self.assertEqual(verdicts[-1], "approve")

        reports = client.get(
            f"/projects/{project_id}/reports",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        self.assertGreaterEqual(len(reports), 2)

        approved = [
            item
            for item in container.artifact_service.list_artifacts_for_run(run_id)
            if item.status == "approved"
        ]
        self.assertEqual(len(approved), 1)

    def test_reject_fails_without_approved_artifact(self) -> None:
        os.environ["DETERMINISTIC_REVIEW_SCENARIO"] = "reject"
        self.addCleanup(os.environ.pop, "DETERMINISTIC_REVIEW_SCENARIO", None)
        client, container = self._build_client()
        project_id = client.post("/projects", json={"name": "DR-07 Reject"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": f"dr07-reject-{uuid4()}"},
        ).json()["run_id"]
        with self.assertRaises(ReviewError):
            drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(terminal["status"], "failed")
        self.assertFalse(terminal["final_artifact_available"])
        reviews = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_id, "verdict": "reject"},
        ).json()["items"]
        self.assertGreaterEqual(len(reviews), 1)

    def test_revise_exhaustion_fails_without_approved_artifact(self) -> None:
        os.environ["DETERMINISTIC_REVIEW_SCENARIO"] = "revise_once"
        self.addCleanup(os.environ.pop, "DETERMINISTIC_REVIEW_SCENARIO", None)
        client, container = self._build_client(max_revision_attempts=0)
        project_id = client.post("/projects", json={"name": "DR-07 Exhaust"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": f"dr07-exhaust-{uuid4()}"},
        ).json()["run_id"]
        with self.assertRaises(ReviewError):
            drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(terminal["status"], "failed")
        self.assertFalse(terminal["final_artifact_available"])

        reviews = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        self.assertGreaterEqual(len(reviews), 1)
        verdicts = [item["verdict"] for item in reviews]
        self.assertIn("revise", verdicts)

        approved = [
            item
            for item in container.artifact_service.list_artifacts_for_run(run_id)
            if item.status == "approved"
        ]
        self.assertEqual(len(approved), 0)


if __name__ == "__main__":
    unittest.main()
