"""DR-07 two-run review isolation PostgreSQL tests."""

from __future__ import annotations

import unittest
from uuid import uuid4

from dataclasses import replace

from application.composition_root import create_application_container
from application.review.exceptions import ReviewError
from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    prepare_approved_desk_project,
    submit_approved_desk_run,
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.helpers.dated_desk_integration_fixture import dated_desk_overrides
from tests.integration.postgresql.helpers import (
    assert_structured_finalization_complete,
    configure_structured_finalization_test_boundary,
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)
from tests.integration.postgresql.dr07_fixtures import StructuredReviewScenarioEngine


class TwoRunReviewIsolationPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def _build_client(self):
        mock_llm = create_brief_aligned_llm_mock()
        review_engine = StructuredReviewScenarioEngine()
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
            overrides=dated_desk_overrides(
                llm_client=mock_llm,
                review_engine=review_engine,
            ),
        )
        configure_structured_finalization_test_boundary(container)
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(
            raw_client,
            auth_headers(container._test_api_key_plaintext),
        )
        return client, container, review_engine

    def test_two_runs_keep_independent_review_and_artifact_state(self) -> None:
        client, container, review_engine = self._build_client()
        project_id = client.post("/projects", json={"name": "Two-Run Review"}).json()["id"]
        approved = prepare_approved_desk_project(container, project_id, BRIEF)
        subject = approved.current_research_design.research_subject

        run_a = submit_approved_desk_run(
            container, project_id, run_id=str(uuid4()),
        ).id
        drain_background_runs(container)
        terminal_a = client.get(f"/workflow-runs/{run_a}").json()
        self.assertEqual(terminal_a["status"], "completed")
        assert_structured_finalization_complete(self, container, run_a)
        finalization_a = dict(container.workflow_service.get_task_results(run_a)[
            "desk_deliverable_finalization"
        ])
        self.assertEqual(terminal_a["final_review_verdict"], "approve")
        review_count_a = terminal_a["review_count"]
        artifact_a = terminal_a["final_artifact_id"]

        review_engine.scenario = "reject"
        run_b = submit_approved_desk_run(
            container, project_id, run_id=str(uuid4()),
        ).id
        frozen_b = container.workflow_service.get_template(
            container.workflow_service.get_workflow_run(run_b).workflow_template_id,
        ).research_design_snapshot.research_subject
        self.assertEqual(
            (frozen_b.subject_id, frozen_b.version, frozen_b.semantic_fingerprint,
             frozen_b.lexical_representations),
            (subject.subject_id, subject.version, subject.semantic_fingerprint,
             subject.lexical_representations),
        )
        with self.assertRaises(ReviewError):
            drain_background_runs(container)
        terminal_b = client.get(f"/workflow-runs/{run_b}").json()
        self.assertEqual(terminal_b["status"], "failed")
        tasks_b = {task["definition_id"]: task["status"] for task in terminal_b["tasks"]}
        self.assertEqual(tasks_b["task-review-report"], "failed")
        self.assertNotEqual(tasks_b["task-finalize-deliverables"], "completed")
        self.assertFalse(terminal_b["final_artifact_available"])
        reviews_b = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_b},
        ).json()["items"]
        self.assertTrue(reviews_b)
        self.assertNotIn("approve", [item["verdict"] for item in reviews_b])
        project = container.project_service.get_project(project_id)
        catalog = container.project_deliverables_service.catalog(
            project_id,
            owner_id=project.owner_principal_id,
        )
        run_b_items = [item for item in catalog.desk if item.document.run_id == run_b]
        self.assertTrue(run_b_items)
        self.assertTrue(
            all(item.pdf is None and item.pptx is None for item in run_b_items)
        )
        finalization_b = container.workflow_service.get_task_results(run_b).get(
            "desk_deliverable_finalization"
        )
        self.assertFalse(
            isinstance(finalization_b, dict)
            and finalization_b.get("status") == "finalization_complete"
        )

        terminal_a_after = client.get(f"/workflow-runs/{run_a}").json()
        self.assertEqual(terminal_a_after["review_count"], review_count_a)
        self.assertEqual(terminal_a_after["final_review_verdict"], "approve")
        self.assertEqual(terminal_a_after["final_artifact_id"], artifact_a)
        self.assertEqual(
            container.workflow_service.get_task_results(run_a)[
                "desk_deliverable_finalization"
            ],
            finalization_a,
        )
        jobs = container.project_deliverables_service.presentation_jobs.list_recent()
        self.assertEqual(len([job for job in jobs if job.run_id == run_a]), 1)
        self.assertEqual(len([job for job in jobs if job.run_id == run_b]), 0)

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
