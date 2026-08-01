from __future__ import annotations

import concurrent.futures
import unittest
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import text

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
)
from domain.ai.llm_response import LLMResponse

from api.app import create_fastapi_app

from infrastructure.persistence.postgresql.repositories.postgresql_research_submission_repository import (
    PostgreSQLResearchSubmissionRepository,
)

from api.schemas.workflow_runs import StartResearchRequest

from tests.api.helpers import close_test_client, drain_background_runs, open_test_client
from tests.fixtures.planner_responses import VALID_PLANNER_JSON
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    get_test_database_url,
)

BRIEF = {
    "client": "Purina",
    "project_title": "External Orchestration",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class ExternalOrchestrationIntegrationTests(PostgreSQLIntegrationTestCase):

    def _build_client(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)
        container = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        container._test_llm_client = mock_llm
        self.addCleanup(container.shutdown)
        client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        return client, container

    def _create_project(self, client) -> str:
        response = client.post("/projects", json={"name": "External Project"})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_first_submission_with_idempotency_key_returns_202(self) -> None:
        client, _ = self._build_client()
        project_id = self._create_project(client)
        response = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n", "correlation_id": "corr-1"},
            headers={"Idempotency-Key": "key-first"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertFalse(payload["idempotent_replay"])
        self.assertEqual(payload["external"]["source"], "n8n")
        self.assertEqual(payload["external"]["correlation_id"], "corr-1")
        self.assertEqual(payload["external"]["external_request_id"], "key-first")

    def test_duplicate_same_request_returns_same_run(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-replay"}
        body = {"brief": BRIEF, "source": "n8n", "correlation_id": "corr-replay"}
        first = client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        second = client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["run_id"], second.json()["run_id"])
        self.assertTrue(second.json()["idempotent_replay"])
        self.assertEqual(container._test_llm_client.generate.call_count, 1)

    def test_same_key_different_request_returns_409(self) -> None:
        client, _ = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-conflict"}
        first = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers=headers,
        )
        self.assertEqual(first.status_code, 202)
        second = client.post(
            f"/projects/{project_id}/research",
            json={
                "brief": {
                    **BRIEF,
                    "research_goal": "Different goal.",
                },
            },
            headers=headers,
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "idempotency_conflict")

    def test_concurrent_duplicate_submissions_create_one_run(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-concurrent"}
        body = {"brief": BRIEF, "source": "n8n"}

        def _submit():
            app = create_fastapi_app(container=container)
            from fastapi.testclient import TestClient

            with TestClient(app) as thread_client:
                return thread_client.post(
                    f"/projects/{project_id}/research",
                    json=body,
                    headers=headers,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_submit) for _ in range(2)]
            responses = [future.result() for future in futures]

        run_ids = {response.json()["run_id"] for response in responses}
        self.assertEqual(len(run_ids), 1)
        self.assertTrue(all(response.status_code == 202 for response in responses))

    def test_submission_metadata_survives_reload(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n", "correlation_id": "corr-reload"},
            headers={"Idempotency-Key": "key-reload"},
        ).json()
        run_id = started["run_id"]

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)
        reloaded_container = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(reloaded_container.shutdown)
        reloaded_client, _, context = open_test_client(reloaded_container)
        self.addCleanup(lambda: close_test_client(context, reloaded_container))

        payload = reloaded_client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(payload["external"]["correlation_id"], "corr-reload")
        self.assertEqual(payload["external"]["source"], "n8n")

    def test_polling_exposes_terminal_and_availability_flags(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]
        drain_background_runs(container)
        payload = client.get(f"/workflow-runs/{run_id}").json()
        self.assertTrue(payload["is_terminal"])
        self.assertIn("results_available", payload)
        self.assertIn("artifacts_available", payload)

    def test_results_endpoint_distinguishes_terminal_state(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]
        pending = client.get(f"/workflow-runs/{run_id}/results").json()
        self.assertFalse(pending["results_ready"])
        drain_background_runs(container)
        terminal = client.get(f"/workflow-runs/{run_id}/results").json()
        self.assertTrue(terminal["results_ready"])
        self.assertTrue(terminal["is_terminal"])

    def test_api_restart_replay_returns_same_run_id(self) -> None:
        client, _ = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-restart-replay"}
        body = {"brief": BRIEF, "source": "n8n", "correlation_id": "corr-restart"}
        first = client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        self.assertEqual(first.status_code, 202)
        run_id = first.json()["run_id"]
        self.assertFalse(first.json()["idempotent_replay"])

        replay_client, _ = self._build_client()
        second = replay_client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["run_id"], run_id)
        self.assertTrue(second.json()["idempotent_replay"])

    def test_pending_submission_recovers_after_crash_before_planning(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        idempotency_key = "key-crash-before-planning"
        run_id = str(uuid4())
        body = {"brief": BRIEF, "source": "n8n", "correlation_id": "corr-crash"}
        parsed = StartResearchRequest.model_validate(body)
        fingerprint = compute_research_request_fingerprint(
            project_id=project_id,
            brief=parsed.brief.model_dump(mode="json"),
        )
        repo = PostgreSQLResearchSubmissionRepository(self.session_factory)
        created, _ = repo.try_register(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            run_id=run_id,
            correlation_id="corr-crash",
            source="n8n",
        )
        self.assertTrue(created)

        recovery_client, recovery_container = self._build_client()
        response = recovery_client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["run_id"], run_id)
        recovery_container.workflow_service.get_workflow_run(run_id)
        self.assertEqual(recovery_container._test_llm_client.generate.call_count, 1)

    def test_pending_submission_with_existing_run_recovers_without_duplicate(
        self,
    ) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-crash-before-complete"}
        body = {"brief": BRIEF, "source": "n8n"}
        first = client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        run_id = first.json()["run_id"]

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE research_submissions "
                    "SET status = 'pending' "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )

        replay_client, replay_container = self._build_client()
        second = replay_client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["run_id"], run_id)
        self.assertTrue(second.json()["idempotent_replay"])
        runs = replay_container.workflow_service.list_workflow_runs_for_project(
            project_id,
        )
        matching = [run for run in runs if run.id == run_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(replay_container._test_llm_client.generate.call_count, 0)


if __name__ == "__main__":
    unittest.main()
