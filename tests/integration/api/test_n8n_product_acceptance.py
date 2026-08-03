"""n8n product-acceptance E2E tests (deterministic contract, no live n8n UI)."""

from __future__ import annotations

import unittest
from uuid import uuid4

from application.composition_root import create_application_container
from application.config import ApplicationOverrides

from api.app import create_fastapi_app

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.api.n8n_orchestration_harness import (
    N8N_ACCEPTANCE_BRIEF,
    N8nOrchestrationHarness,
)
from tests.integration.n8n.workflow_contract_helpers import (
    resolve_artifact_content_url,
    resolve_artifact_metadata_url,
    resolve_terminal_outcome,
    terminal_route_target_node,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class N8nProductAcceptanceTests(PostgreSQLIntegrationTestCase):
    def _build_harness(self):
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
                review_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        headers = auth_headers(container._test_api_key_plaintext)
        client = AuthenticatedTestClient(raw_client, headers)
        harness = N8nOrchestrationHarness(
            client,
            auth_headers=headers,
            worker_drain=drain_background_runs,
        )
        return harness, container, headers

    def test_valid_authenticated_e2e_returns_approved_artifact(self) -> None:
        harness, container, _ = self._build_harness()
        result = harness.run_acceptance_flow(container)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.review_verdict, "approve")
        self.assertTrue(result.artifact_content.strip())
        self.assertEqual(result.artifact_media_type, "text/markdown")

    def test_canonical_brief_shape_is_accepted(self) -> None:
        harness, container, _ = self._build_harness()
        project_id = harness.create_project()
        response = harness.submit_research(
            project_id,
            idempotency_key=f"brief-shape-{uuid4()}",
            correlation_id=f"corr-{uuid4()}",
            brief=N8N_ACCEPTANCE_BRIEF,
        )
        self.assertEqual(response.status_code, 202)
        for field in (
            "title",
            "business_question",
            "objectives",
            "geography",
            "market",
            "target_entities",
            "timeframe",
            "deliverables",
            "language",
        ):
            self.assertIn(field, N8N_ACCEPTANCE_BRIEF)

    def test_idempotent_replay_same_key_returns_same_run(self) -> None:
        harness, container, _ = self._build_harness()
        key = f"idempotent-{uuid4()}"
        corr = f"corr-{uuid4()}"
        project_id = harness.create_project()
        first = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=corr,
        )
        second = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=corr,
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["run_id"], second.json()["run_id"])
        self.assertTrue(second.json()["idempotent_replay"])
        runs = container.workflow_service.list_workflow_runs_for_project(project_id)
        self.assertEqual(len(runs), 1)

    def test_same_key_different_payload_returns_409(self) -> None:
        harness, _, _ = self._build_harness()
        key = f"conflict-{uuid4()}"
        project_id = harness.create_project()
        first = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=f"corr-{uuid4()}",
        )
        self.assertEqual(first.status_code, 202)
        second = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=f"corr-{uuid4()}",
            brief={**BRIEF, "objectives": ["Different objective."]},
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "idempotency_conflict")

    def test_new_idempotency_key_creates_new_run(self) -> None:
        harness, container, _ = self._build_harness()
        project_id = harness.create_project()
        first = harness.submit_research(
            project_id,
            idempotency_key=f"run-a-{uuid4()}",
            correlation_id=f"corr-{uuid4()}",
        )
        second = harness.submit_research(
            project_id,
            idempotency_key=f"run-b-{uuid4()}",
            correlation_id=f"corr-{uuid4()}",
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(first.json()["run_id"], second.json()["run_id"])
        runs = container.workflow_service.list_workflow_runs_for_project(project_id)
        self.assertEqual(len(runs), 2)

    def test_polling_requires_approved_review_not_completed_alone(self) -> None:
        harness, container, _ = self._build_harness()
        result = harness.run_acceptance_flow(container)
        terminal = harness.poll_until_terminal(result.run_id)
        self.assertTrue(terminal["is_terminal"])
        self.assertEqual(terminal["final_review_verdict"], "approve")
        self.assertTrue(terminal["final_artifact_available"])

    def test_artifact_checksum_matches_content(self) -> None:
        harness, container, _ = self._build_harness()
        result = harness.run_acceptance_flow(container)
        artifact = harness.fetch_approved_artifact(result.artifact_id)
        self.assertEqual(
            artifact["checksum"],
            artifact["content"]["content_checksum"],
        )

    def test_invalid_api_key_returns_401_before_research(self) -> None:
        harness, _, valid_headers = self._build_harness()
        project_id = harness.create_project()
        bad_headers = {
            **valid_headers,
            "Authorization": "Bearer airos_deadbeef_not-a-real-key",
        }
        response = harness._client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n"},
            headers={**bad_headers, "Idempotency-Key": f"bad-key-{uuid4()}"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")
        self.assertNotIn("airos_deadbeef_not-a-real-key", response.text)

    def test_transient_5xx_retries_then_succeeds(self) -> None:
        harness, _, _ = self._build_harness()
        attempts = {"count": 0}

        def flaky_transport(method, path, *, json=None, headers=None):
            attempts["count"] += 1
            if attempts["count"] == 1:
                class FakeResponse:
                    status_code = 503
                    text = "temporary unavailable"

                return FakeResponse()
            if method == "POST":
                return harness._client.post(path, json=json, headers=headers)
            return harness._client.get(path, headers=headers)

        response = harness._request_with_retry(
            "POST",
            "/projects",
            json={"name": "Retry Project"},
            transport=flaky_transport,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(attempts["count"], 2)

    def test_orchestrator_interruption_replay_same_key(self) -> None:
        harness, container, headers = self._build_harness()
        key = f"interrupt-{uuid4()}"
        corr = f"corr-{uuid4()}"
        project_id = harness.create_project()
        first = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=corr,
        )
        run_id = first.json()["run_id"]

        mock_llm = create_brief_aligned_llm_mock()
        replay_container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
                review_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(replay_container.shutdown)
        replay_container.agency.initialize()
        replay_app = create_fastapi_app(container=replay_container)
        from fastapi.testclient import TestClient

        with TestClient(replay_app) as replay_raw:
            replay_client = AuthenticatedTestClient(replay_raw, headers)
            replay_harness = N8nOrchestrationHarness(
                replay_client,
                auth_headers=headers,
                worker_drain=drain_background_runs,
            )
            replay = replay_harness.submit_research(
                project_id,
                idempotency_key=key,
                correlation_id=corr,
            )
            self.assertEqual(replay.status_code, 202)
            self.assertEqual(replay.json()["run_id"], run_id)
            self.assertTrue(replay.json()["idempotent_replay"])
            replay_harness.drain_workers(replay_container)
            terminal = replay_harness.poll_until_terminal(run_id)
            replay_harness.assert_approved_finality(terminal)

        runs = replay_container.workflow_service.list_workflow_runs_for_project(
            project_id,
        )
        self.assertEqual(len(runs), 1)

    def test_worker_restart_continues_to_approved_artifact(self) -> None:
        harness, container, headers = self._build_harness()
        key = f"worker-restart-{uuid4()}"
        project_id = harness.create_project()
        submit = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=f"corr-{uuid4()}",
        )
        run_id = submit.json()["run_id"]

        mock_llm = create_brief_aligned_llm_mock()
        worker_b = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
                review_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(worker_b.shutdown)
        worker_b.agency.initialize()
        drain_background_runs(worker_b)

        terminal = harness.poll_until_terminal(run_id)
        harness.assert_approved_finality(terminal)
        artifact = harness.fetch_approved_artifact(terminal["final_artifact_id"])
        self.assertTrue(artifact["content"]["content"].strip())

    def test_api_restart_preserves_run_and_finality(self) -> None:
        harness, container, headers = self._build_harness()
        key = f"api-restart-{uuid4()}"
        corr = f"corr-{uuid4()}"
        project_id = harness.create_project()
        submit = harness.submit_research(
            project_id,
            idempotency_key=key,
            correlation_id=corr,
        )
        run_id = submit.json()["run_id"]
        harness.drain_workers(container)

        mock_llm = create_brief_aligned_llm_mock()
        reloaded = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
                review_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(reloaded.shutdown)
        reloaded_app = create_fastapi_app(container=reloaded)
        from fastapi.testclient import TestClient

        with TestClient(reloaded_app) as reloaded_raw:
            reloaded_client = AuthenticatedTestClient(reloaded_raw, headers)
            payload = reloaded_client.get(f"/workflow-runs/{run_id}").json()
            self.assertTrue(payload["is_terminal"])
            self.assertEqual(payload["final_review_verdict"], "approve")
            self.assertTrue(payload["final_artifact_available"])
            artifact_id = payload["final_artifact_id"]
            content = reloaded_client.get(
                f"/artifacts/{artifact_id}/content",
                headers=headers,
            ).json()
            self.assertTrue(content["content"].strip())

    def test_workflow_run_final_artifact_id_maps_to_artifact_metadata_url(self) -> None:
        """Canonical n8n artifact fetch must not resolve /artifacts/null when ID is present."""
        terminal = {
            "status": "completed",
            "is_terminal": True,
            "final_review_verdict": "approve",
            "final_artifact_available": True,
            "final_artifact_id": "artifact-123",
        }
        api_url = "http://api:8000"
        metadata_url = resolve_artifact_metadata_url(
            api_url=api_url,
            final_artifact_id=terminal["final_artifact_id"],
        )
        content_url = resolve_artifact_content_url(
            api_url=api_url,
            final_artifact_id=terminal["final_artifact_id"],
        )
        self.assertEqual(metadata_url, "http://api:8000/artifacts/artifact-123")
        self.assertNotIn("/artifacts/null", metadata_url)
        self.assertEqual(content_url, "http://api:8000/artifacts/artifact-123/content")
        self.assertNotIn("/artifacts/null", content_url)

    def test_failed_terminal_workflow_run_does_not_map_to_artifact_fetch(self) -> None:
        terminal = {
            "status": "failed",
            "is_terminal": True,
            "final_review_verdict": "none",
            "final_artifact_available": False,
            "final_artifact_id": None,
        }
        outcome = resolve_terminal_outcome(terminal)
        self.assertEqual(outcome, "failed")
        self.assertEqual(terminal_route_target_node(outcome), "Failed Payload")
        with self.assertRaises(ValueError):
            resolve_artifact_metadata_url(
                api_url="http://api:8000",
                final_artifact_id=terminal["final_artifact_id"],
            )


if __name__ == "__main__":
    unittest.main()
