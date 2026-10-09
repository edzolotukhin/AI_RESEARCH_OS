"""Repeated same-project / same-brief desk research runs (DR-06 product integrity)."""

from __future__ import annotations

import unittest
from uuid import uuid4

from application.composition_root import create_application_container

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
    prepare_approved_desk_project,
    submit_approved_desk_run,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.helpers.dated_desk_integration_fixture import dated_desk_overrides
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class RepeatedRunSameProjectPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def _build_client(self):
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=dated_desk_overrides(llm_client=mock_llm),
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

    def _assert_completed_run(self, client: AuthenticatedTestClient, run_id: str) -> dict:
        terminal = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(terminal["status"], "completed")
        self.assertGreater(terminal["source_count"], 0)
        self.assertGreater(terminal["evidence_count"], 0)
        self.assertGreater(terminal["finding_count"], 0)
        self.assertGreater(terminal["insight_count"], 0)
        self.assertEqual(terminal["report_count"], 1)
        self.assertEqual(terminal["artifact_count"], 1)
        return terminal

    def test_two_same_brief_runs_complete_with_shared_sources(self) -> None:
        client, container = self._build_client()
        project_id = client.post("/projects", json={"name": "Repeated Brief Project"}).json()[
            "id"
        ]
        approved = prepare_approved_desk_project(container, project_id, BRIEF)
        subject = approved.current_research_design.research_subject

        run_1_id = submit_approved_desk_run(
            container, project_id, run_id=str(uuid4()),
        ).id
        drain_background_runs(container)
        run_1 = self._assert_completed_run(client, run_1_id)

        run_2_id = submit_approved_desk_run(
            container, project_id, run_id=str(uuid4()),
        ).id
        self.assertNotEqual(run_1_id, run_2_id)
        frozen_2 = container.workflow_service.get_template(
            container.workflow_service.get_workflow_run(run_2_id).workflow_template_id,
        ).research_design_snapshot.research_subject
        self.assertEqual(
            (frozen_2.subject_id, frozen_2.version, frozen_2.semantic_fingerprint,
             frozen_2.lexical_representations),
            (subject.subject_id, subject.version, subject.semantic_fingerprint,
             subject.lexical_representations),
        )
        drain_background_runs(container)
        run_2 = self._assert_completed_run(client, run_2_id)

        sources = container.source_service.list_sources_for_project(project_id)
        acquired = [source for source in sources if source.content_text.strip()]
        self.assertGreater(len(acquired), 0)
        self.assertEqual(
            len({source.canonical_url for source in sources}),
            len(sources),
            "Sources remain project-deduplicated by canonical URL",
        )
        shared = next(
            source
            for source in sources
            if "example.com/market-report" in source.canonical_url
        )
        self.assertIn(run_1_id, shared.workflow_run_refs)
        self.assertIn(run_2_id, shared.workflow_run_refs)
        records = shared.metadata.get("discovery_records") or []
        self.assertTrue(
            any(str(record.get("workflow_run_id")) == run_1_id for record in records),
        )
        self.assertTrue(
            any(str(record.get("workflow_run_id")) == run_2_id for record in records),
        )

        evidence_1 = client.get(
            f"/projects/{project_id}/evidence",
            params={"workflow_run_id": run_1_id},
        ).json()["items"]
        evidence_2 = client.get(
            f"/projects/{project_id}/evidence",
            params={"workflow_run_id": run_2_id},
        ).json()["items"]
        self.assertGreater(len(evidence_1), 0)
        self.assertGreater(len(evidence_2), 0)
        self.assertTrue(all(item["workflow_run_id"] == run_1_id for item in evidence_1))
        self.assertTrue(all(item["workflow_run_id"] == run_2_id for item in evidence_2))
        self.assertNotEqual(
            {item["id"] for item in evidence_1},
            {item["id"] for item in evidence_2},
        )

        findings_1 = client.get(
            f"/projects/{project_id}/findings",
            params={"workflow_run_id": run_1_id},
        ).json()["items"]
        findings_2 = client.get(
            f"/projects/{project_id}/findings",
            params={"workflow_run_id": run_2_id},
        ).json()["items"]
        self.assertGreater(len(findings_1), 0)
        self.assertGreater(len(findings_2), 0)
        self.assertNotEqual(
            {item["id"] for item in findings_1},
            {item["id"] for item in findings_2},
        )

        insights_1 = client.get(
            f"/projects/{project_id}/insights",
            params={"workflow_run_id": run_1_id},
        ).json()["items"]
        insights_2 = client.get(
            f"/projects/{project_id}/insights",
            params={"workflow_run_id": run_2_id},
        ).json()["items"]
        self.assertGreater(len(insights_1), 0)
        self.assertGreater(len(insights_2), 0)
        self.assertNotEqual(
            {item["id"] for item in insights_1},
            {item["id"] for item in insights_2},
        )

        reports_1 = client.get(
            f"/projects/{project_id}/reports",
            params={"workflow_run_id": run_1_id},
        ).json()["items"]
        reports_2 = client.get(
            f"/projects/{project_id}/reports",
            params={"workflow_run_id": run_2_id},
        ).json()["items"]
        self.assertEqual(len(reports_1), 1)
        self.assertEqual(len(reports_2), 1)
        self.assertNotEqual(reports_1[0]["id"], reports_2[0]["id"])

        artifacts_1 = client.get(f"/workflow-runs/{run_1_id}/artifacts").json()["items"]
        artifacts_2 = client.get(f"/workflow-runs/{run_2_id}/artifacts").json()["items"]
        self.assertEqual(len(artifacts_1), 1)
        self.assertEqual(len(artifacts_2), 1)
        self.assertNotEqual(artifacts_1[0]["id"], artifacts_2[0]["id"])

        self.assertEqual(run_1["report_count"], 1)
        self.assertEqual(run_2["report_count"], 1)

    def test_same_idempotency_key_replays_run_without_duplicates(self) -> None:
        client, container = self._build_client()
        project_id = client.post("/projects", json={"name": "Idempotent Project"}).json()[
            "id"
        ]
        approved = prepare_approved_desk_project(container, project_id, BRIEF)
        idempotency_key = f"shared-key-{uuid4()}"
        fingerprint = approved.current_research_design.research_subject.semantic_fingerprint
        first = container.research_submission_service.resolve_submission(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=None,
            source="ow10-postgresql-fixture",
        )
        run_id = submit_approved_desk_run(
            container, project_id, run_id=first.run_id,
        ).id
        container.research_submission_service.mark_completed(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        drain_background_runs(container)
        self._assert_completed_run(client, run_id)

        replay = container.research_submission_service.resolve_submission(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=None,
            source="ow10-postgresql-fixture",
        )
        self.assertTrue(replay.replay)
        self.assertEqual(replay.run_id, run_id)

        runs = client.get(f"/projects/{project_id}/workflow-runs").json()["items"]
        self.assertEqual(len(runs), 1)
        reports = client.get(
            f"/projects/{project_id}/reports",
            params={"workflow_run_id": run_id},
        ).json()["items"]
        self.assertEqual(len(reports), 1)

    def test_restart_then_second_run_completes(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container_1 = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=dated_desk_overrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container_1)
        self.addCleanup(container_1.shutdown)
        raw_1, _, ctx_1 = open_test_client(container_1)
        self.addCleanup(lambda: close_test_client(ctx_1, container_1))
        client_1 = AuthenticatedTestClient(
            raw_1,
            auth_headers(container_1._test_api_key_plaintext),
        )

        project_id = client_1.post("/projects", json={"name": "Restart Project"}).json()[
            "id"
        ]
        approved = prepare_approved_desk_project(container_1, project_id, BRIEF)
        subject = approved.current_research_design.research_subject
        run_1_id = submit_approved_desk_run(
            container_1, project_id, run_id=str(uuid4()),
        ).id
        drain_background_runs(container_1)
        self._assert_completed_run(client_1, run_1_id)

        container_1.shutdown()
        container_2 = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                report_engine="deterministic",
            ),
            overrides=dated_desk_overrides(llm_client=mock_llm),
        )
        self.addCleanup(container_2.shutdown)
        raw_2, _, ctx_2 = open_test_client(container_2)
        self.addCleanup(lambda: close_test_client(ctx_2, container_2))
        client_2 = AuthenticatedTestClient(
            raw_2,
            auth_headers(container_1._test_api_key_plaintext),
        )

        run_2_id = submit_approved_desk_run(
            container_2, project_id, run_id=str(uuid4()),
        ).id
        drain_background_runs(container_2)
        self._assert_completed_run(client_2, run_2_id)
        self.assertNotEqual(run_1_id, run_2_id)
        frozen_2 = container_2.workflow_service.get_template(
            container_2.workflow_service.get_workflow_run(run_2_id).workflow_template_id,
        ).research_design_snapshot.research_subject
        self.assertEqual(
            (frozen_2.subject_id, frozen_2.version, frozen_2.semantic_fingerprint,
             frozen_2.lexical_representations),
            (subject.subject_id, subject.version, subject.semantic_fingerprint,
             subject.lexical_representations),
        )


if __name__ == "__main__":
    unittest.main()
