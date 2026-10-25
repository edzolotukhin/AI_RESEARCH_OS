"""DR-07 end-to-end quality gate tests."""

from __future__ import annotations

import unittest

from dataclasses import replace

from application.composition_root import create_application_container
from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    activate_approved_desk_project,
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


class Dr07EndToEndPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def _build_client(
        self,
        *,
        max_revision_attempts: int = 1,
        review_scenario: str = "approve",
    ):
        mock_llm = create_brief_aligned_llm_mock()
        review_engine = StructuredReviewScenarioEngine(review_scenario)
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
        return client, container

    def _assert_review_failed_closed(self, client, container, project_id, run_id):
        terminal = client.get(f"/workflow-runs/{run_id}").json()
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(tasks["task-review-report"], "failed")
        self.assertNotEqual(tasks["task-finalize-deliverables"], "completed")
        self.assertFalse(terminal["final_artifact_available"])

        reviews = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        self.assertTrue(reviews)
        self.assertNotIn("approve", [item["verdict"] for item in reviews])

        project = container.project_service.get_project(project_id)
        catalog = container.project_deliverables_service.catalog(
            project_id, owner_id=project.owner_principal_id
        )
        run_items = [item for item in catalog.desk if item.document.run_id == run_id]
        self.assertTrue(run_items)
        self.assertTrue(all(item.pdf is None and item.pptx is None for item in run_items))
        jobs = container.project_deliverables_service.presentation_jobs.list_recent()
        self.assertFalse(any(job.run_id == run_id for job in jobs))

        results = container.workflow_service.get_task_results(run_id)
        finalization_states = []
        direct = results.get("desk_deliverable_finalization")
        if isinstance(direct, dict):
            finalization_states.append(direct)
        for value in results.values():
            if isinstance(value, dict) and isinstance(value.get("shared_state"), dict):
                nested = value["shared_state"].get("desk_deliverable_finalization")
                if isinstance(nested, dict):
                    finalization_states.append(nested)
        self.assertNotIn(
            "finalization_complete",
            [state.get("status") for state in finalization_states],
        )
        return terminal, reviews

    def test_clean_report_approves_and_completes(self) -> None:
        client, container = self._build_client()
        project_id = client.post("/projects", json={"name": "DR-07 Approve"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id
        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        tasks = {task["definition_id"]: task["status"] for task in terminal["tasks"]}
        self.assertEqual(tasks["task-review-report"], "completed")
        self.assertEqual(terminal["status"], "completed")
        assert_structured_finalization_complete(self, container, run_id)
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
        client, container = self._build_client(
            max_revision_attempts=1,
            review_scenario="revise_once",
        )
        project_id = client.post("/projects", json={"name": "DR-07 Revise"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id
        drain_background_runs(container)

        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(terminal["status"], "completed")
        assert_structured_finalization_complete(self, container, run_id)
        self.assertEqual(terminal["final_review_verdict"], "approve")
        self.assertTrue(terminal["final_artifact_available"])

        reviews = client.get(
            f"/projects/{project_id}/reviews",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        verdicts = [item["verdict"] for item in reviews]
        self.assertEqual(verdicts, ["revise", "approve"])

        reports = container.report_query_service.list_reports_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        self.assertEqual(len(reports), 2)
        reports_by_revision = sorted(reports, key=lambda item: item.revision_number)
        original, revised = reports_by_revision
        self.assertEqual(original.revision_number, 1)
        self.assertEqual(revised.revision_number, 2)
        self.assertEqual(revised.previous_report_id, original.id)
        claim_repository = container.project_deliverables_service.report_claims
        original_claims = claim_repository.list_for_report(original.id, 1)
        revised_claims = claim_repository.list_for_report(revised.id, 2)
        self.assertTrue(original_claims)
        self.assertTrue(revised_claims)

        persisted_reviews = container.review_query_service.list_reviews_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        self.assertEqual(persisted_reviews[0].report_id, original.id)
        self.assertTrue(persisted_reviews[0].issues[0].report_section_id)
        self.assertTrue(persisted_reviews[0].issues[0].claim_refs)
        self.assertTrue(persisted_reviews[0].issues[0].research_question_refs)
        self.assertEqual(persisted_reviews[-1].report_id, revised.id)
        self.assertEqual(persisted_reviews[-1].metadata["report_revision"], 2)

        approved = [
            item
            for item in container.artifact_service.list_artifacts_for_run(run_id)
            if item.status == "approved"
        ]
        self.assertEqual(len(approved), 1)
        project = container.project_service.get_project(project_id)
        catalog = container.project_deliverables_service.catalog(
            project_id,
            owner_id=project.owner_principal_id,
        )
        run_items = [item for item in catalog.desk if item.document.run_id == run_id]
        original_item = next(item for item in run_items if item.document.source_id == original.id)
        revised_item = next(item for item in run_items if item.document.source_id == revised.id)
        self.assertIsNone(original_item.pdf)
        self.assertIsNone(original_item.pptx)
        self.assertIsNotNone(revised_item.pdf)
        self.assertIsNotNone(revised_item.pptx)

    def test_reject_fails_without_approved_artifact(self) -> None:
        client, container = self._build_client(review_scenario="reject")
        project_id = client.post("/projects", json={"name": "DR-07 Reject"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id
        drain_background_runs(container)

        _, reviews = self._assert_review_failed_closed(
            client, container, project_id, run_id
        )
        reviews = [item for item in reviews if item["verdict"] == "reject"]
        self.assertGreaterEqual(len(reviews), 1)

    def test_revise_exhaustion_fails_without_approved_artifact(self) -> None:
        client, container = self._build_client(
            max_revision_attempts=0,
            review_scenario="revise_once",
        )
        project_id = client.post("/projects", json={"name": "DR-07 Exhaust"}).json()["id"]
        run_id = activate_approved_desk_project(container, project_id, BRIEF).id
        drain_background_runs(container)

        _, reviews = self._assert_review_failed_closed(
            client, container, project_id, run_id
        )
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
