from __future__ import annotations

import concurrent.futures
import unittest
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import text

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
)
from domain.ai.llm_response import LLMResponse

from api.app import create_fastapi_app
from api.schemas.workflow_runs import StartResearchRequest

from infrastructure.persistence.postgresql.repositories.postgresql_research_submission_repository import (
    PostgreSQLResearchSubmissionRepository,
)

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, drain_background_runs, open_test_client
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)

from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF


class ExternalOrchestrationIntegrationTests(PostgreSQLIntegrationTestCase):

    def _build_client(self):
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=True,
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        container._test_llm_client = mock_llm
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        self.auth_headers = auth_headers(container._test_api_key_plaintext)
        return client, container

    def _create_project(self, client) -> str:
        response = client.post(
            "/projects",
            json={"name": "External Project"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def _assert_accepted_research_response(
        self,
        response,
        *,
        label: str,
    ) -> dict:
        self.assertEqual(
            response.status_code,
            202,
            f"{label}: status={response.status_code} body={response.text}",
        )
        payload = response.json()
        self.assertIn(
            "run_id",
            payload,
            f"{label}: missing run_id in body={payload}",
        )
        return payload

    def _submit_concurrent(
        self,
        *,
        container,
        project_id: str,
        body: dict,
        headers: dict,
        workers: int = 2,
    ) -> list:
        def _submit():
            app = create_fastapi_app(container=container)
            from fastapi.testclient import TestClient

            with TestClient(app) as thread_client:
                return thread_client.post(
                    f"/projects/{project_id}/research",
                    json=body,
                    headers=headers,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_submit) for _ in range(workers)]
            return [future.result() for future in futures]

    def test_first_submission_with_idempotency_key_returns_202(self) -> None:
        client, _ = self._build_client()
        project_id = self._create_project(client)
        response = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n", "correlation_id": "corr-1"},
            headers={"Idempotency-Key": "key-first", **self.auth_headers},
        )
        payload = self._assert_accepted_research_response(response, label="first")
        self.assertFalse(payload["idempotent_replay"])
        self.assertEqual(payload["external"]["source"], "n8n")
        self.assertEqual(payload["external"]["correlation_id"], "corr-1")
        self.assertEqual(payload["external"]["external_request_id"], "key-first")

    def test_duplicate_same_request_returns_same_run(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-replay", **self.auth_headers}
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
        first_payload = self._assert_accepted_research_response(first, label="first")
        second_payload = self._assert_accepted_research_response(second, label="second")
        self.assertEqual(first_payload["run_id"], second_payload["run_id"])
        self.assertTrue(second_payload["idempotent_replay"])
        self.assertEqual(container._test_llm_client.generate.call_count, 1)

    def test_same_key_different_request_returns_409(self) -> None:
        client, _ = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-conflict", **self.auth_headers}
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
                    "objectives": ["Different objective."],
                },
            },
            headers=headers,
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "idempotency_conflict")

    def test_concurrent_same_key_different_payload_returns_202_and_409(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-concurrent-conflict", **self.auth_headers}

        def _submit(body: dict):
            app = create_fastapi_app(container=container)
            from fastapi.testclient import TestClient

            with TestClient(app) as thread_client:
                return thread_client.post(
                    f"/projects/{project_id}/research",
                    json=body,
                    headers=headers,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(_submit, {"brief": BRIEF, "source": "n8n"})
            second_future = pool.submit(
                _submit,
                {
                    "brief": {
                        **BRIEF,
                        "objectives": ["Different objective."],
                    },
                },
            )
            responses = [first_future.result(), second_future.result()]

        statuses = sorted(response.status_code for response in responses)
        self.assertEqual(statuses, [202, 409])
        accepted = [
            response for response in responses if response.status_code == 202
        ]
        conflict = [
            response for response in responses if response.status_code == 409
        ]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(conflict), 1)
        self._assert_accepted_research_response(accepted[0], label="accepted")
        self.assertEqual(conflict[0].json()["error"]["code"], "idempotency_conflict")

    def test_concurrent_duplicate_submissions_create_one_run(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-concurrent", **self.auth_headers}
        body = {"brief": BRIEF, "source": "n8n"}

        responses = self._submit_concurrent(
            container=container,
            project_id=project_id,
            body=body,
            headers=headers,
        )

        payloads = [
            self._assert_accepted_research_response(
                response,
                label=f"worker-{index}",
            )
            for index, response in enumerate(responses)
        ]
        run_ids = {payload["run_id"] for payload in payloads}
        self.assertEqual(len(run_ids), 1)

        runs = container.workflow_service.list_workflow_runs_for_project(project_id)
        matching = [run for run in runs if run.id in run_ids]
        self.assertEqual(len(matching), 1)

    def test_concurrent_duplicate_submissions_stress(self) -> None:
        for iteration in range(25):
            with self.subTest(iteration=iteration):
                client, container = self._build_client()
                project_id = self._create_project(client)
                headers = {"Idempotency-Key": f"key-concurrent-stress-{iteration}", **self.auth_headers}
                body = {"brief": BRIEF, "source": "n8n"}

                responses = self._submit_concurrent(
                    container=container,
                    project_id=project_id,
                    body=body,
                    headers=headers,
                )

                payloads = [
                    self._assert_accepted_research_response(
                        response,
                        label=f"iter-{iteration}-worker-{index}",
                    )
                    for index, response in enumerate(responses)
                ]
                run_ids = {payload["run_id"] for payload in payloads}
                self.assertEqual(len(run_ids), 1)

                runs = container.workflow_service.list_workflow_runs_for_project(
                    project_id,
                )
                matching = [run for run in runs if run.id in run_ids]
                self.assertEqual(len(matching), 1)

    def test_submission_metadata_survives_reload(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n", "correlation_id": "corr-reload"},
            headers={"Idempotency-Key": "key-reload", **self.auth_headers},
        ).json()
        run_id = started["run_id"]

        mock_llm = create_brief_aligned_llm_mock()
        reloaded_container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(reloaded_container.shutdown)
        reloaded_raw, _, context = open_test_client(reloaded_container)
        self.addCleanup(lambda: close_test_client(context, reloaded_container))
        reloaded_client = AuthenticatedTestClient(reloaded_raw, self.auth_headers)

        payload = reloaded_client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(payload["external"]["correlation_id"], "corr-reload")
        self.assertEqual(payload["external"]["source"], "n8n")

    def test_polling_exposes_terminal_and_availability_flags(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers=self.auth_headers,
        ).json()
        run_id = started["run_id"]
        drain_background_runs(container)
        payload = client.get(
            f"/workflow-runs/{run_id}",
            headers=self.auth_headers,
        ).json()
        self.assertTrue(payload["is_terminal"])
        self.assertIn("results_available", payload)
        self.assertIn("artifacts_available", payload)

    def test_results_endpoint_distinguishes_terminal_state(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers=self.auth_headers,
        ).json()
        run_id = started["run_id"]
        pending = client.get(
            f"/workflow-runs/{run_id}/results",
            headers=self.auth_headers,
        ).json()
        self.assertFalse(pending["results_ready"])
        drain_background_runs(container)
        terminal = client.get(
            f"/workflow-runs/{run_id}/results",
            headers=self.auth_headers,
        ).json()
        self.assertTrue(terminal["results_ready"])
        self.assertTrue(terminal["is_terminal"])

    def test_api_restart_replay_returns_same_run_id(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-restart-replay", **self.auth_headers}
        body = {"brief": BRIEF, "source": "n8n", "correlation_id": "corr-restart"}
        first = client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        first_payload = self._assert_accepted_research_response(first, label="first")
        run_id = first_payload["run_id"]
        self.assertFalse(first_payload["idempotent_replay"])

        mock_llm = create_brief_aligned_llm_mock()
        replay_container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(replay_container.shutdown)
        replay_raw, _, replay_context = open_test_client(replay_container)
        self.addCleanup(lambda: close_test_client(replay_context, replay_container))
        replay_client = AuthenticatedTestClient(replay_raw, self.auth_headers)
        second = replay_client.post(
            f"/projects/{project_id}/research",
            json=body,
            headers=headers,
        )
        second_payload = self._assert_accepted_research_response(second, label="replay")
        self.assertEqual(second_payload["run_id"], run_id)
        self.assertTrue(second_payload["idempotent_replay"])

    def test_pending_submission_recovers_after_crash_before_planning(self) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        original_auth_headers = dict(self.auth_headers)
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
            headers={"Idempotency-Key": idempotency_key, **original_auth_headers},
        )
        payload = self._assert_accepted_research_response(response, label="recovery")
        self.assertEqual(payload["run_id"], run_id)
        recovery_container.workflow_service.get_workflow_run(run_id)
        self.assertEqual(recovery_container._test_llm_client.generate.call_count, 1)

    def test_pending_submission_with_existing_run_recovers_without_duplicate(
        self,
    ) -> None:
        client, container = self._build_client()
        project_id = self._create_project(client)
        headers = {"Idempotency-Key": "key-crash-before-complete", **self.auth_headers}
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
        payload = self._assert_accepted_research_response(second, label="replay")
        self.assertEqual(payload["run_id"], run_id)
        self.assertTrue(payload["idempotent_replay"])
        runs = replay_container.workflow_service.list_workflow_runs_for_project(
            project_id,
        )
        matching = [run for run in runs if run.id == run_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(replay_container._test_llm_client.generate.call_count, 0)


if __name__ == "__main__":
    unittest.main()
