"""DR-07 two-run review isolation PostgreSQL tests."""

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


class TwoRunReviewIsolationPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def _build_client(self):
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

    def test_two_runs_keep_independent_review_and_artifact_state(self) -> None:
        client, container = self._build_client()
        project_id = client.post("/projects", json={"name": "Two-Run Review"}).json()["id"]

        run_a = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": f"dr07-run-a-{uuid4()}"},
        ).json()["run_id"]
        drain_background_runs(container)
        terminal_a = client.get(f"/workflow-runs/{run_a}").json()
        self.assertEqual(terminal_a["status"], "completed")
        self.assertEqual(terminal_a["final_review_verdict"], "approve")
        review_count_a = terminal_a["review_count"]
        artifact_a = terminal_a["final_artifact_id"]

        os.environ["DETERMINISTIC_REVIEW_SCENARIO"] = "reject"
        self.addCleanup(os.environ.pop, "DETERMINISTIC_REVIEW_SCENARIO", None)
        run_b = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": f"dr07-run-b-{uuid4()}"},
        ).json()["run_id"]
        with self.assertRaises(ReviewError):
            drain_background_runs(container)
        terminal_b = client.get(f"/workflow-runs/{run_b}").json()
        self.assertEqual(terminal_b["status"], "failed")
        self.assertFalse(terminal_b["final_artifact_available"])

        terminal_a_after = client.get(f"/workflow-runs/{run_a}").json()
        self.assertEqual(terminal_a_after["review_count"], review_count_a)
        self.assertEqual(terminal_a_after["final_review_verdict"], "approve")
        self.assertEqual(terminal_a_after["final_artifact_id"], artifact_a)

        approved_a = [
            item
            for item in container.artifact_service.list_artifacts_for_run(run_a)
            if item.status == "approved"
        ]
        approved_b = [
            item
            for item in container.artifact_service.list_artifacts_for_run(run_b)
            if item.status == "approved"
        ]
        self.assertEqual(len(approved_a), 1)
        self.assertEqual(len(approved_b), 0)


if __name__ == "__main__":
    unittest.main()
