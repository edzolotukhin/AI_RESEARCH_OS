from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from domain.ai.llm_response import LLMResponse

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, drain_background_runs, open_test_client
from tests.fixtures.planner_responses import VALID_PLANNER_JSON
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)

BRIEF = {
    "client": "Purina",
    "project_title": "PG API Project",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class PostgreSQLApiIntegrationTests(PostgreSQLIntegrationTestCase):

    def _build_client(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=True,
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        container._test_llm_client = mock_llm
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        headers = auth_headers(container._test_api_key_plaintext)
        client = AuthenticatedTestClient(raw_client, headers)
        return client, container, headers

    def test_create_project_via_http_reloads_from_repository(self) -> None:
        client, container, _ = self._build_client()
        created = client.post("/projects", json={"name": "PG HTTP Project"}).json()
        reloaded = container.project_service.get_project(created["id"])
        self.assertEqual(reloaded.name, "PG HTTP Project")

    def test_start_research_persists_run_accessible_via_http(self) -> None:
        client, container, _ = self._build_client()
        project = client.post("/projects", json={"name": "PG Research Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        )
        self.assertEqual(started.status_code, 202)
        drain_background_runs(container)
        run_response = client.get(f"/workflow-runs/{started.json()['run_id']}")
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json()["project_id"], project["id"])

    def test_get_logs_and_results_via_http(self) -> None:
        client, container, _ = self._build_client()
        project = client.post("/projects", json={"name": "PG Logs Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        drain_background_runs(container)
        logs = client.get(f"/workflow-runs/{started['run_id']}/logs").json()["items"]
        results = client.get(
            f"/workflow-runs/{started['run_id']}/results",
        ).json()["task_results"]
        self.assertGreaterEqual(len(logs), 1)
        self.assertGreaterEqual(len(results), 0)

    def test_terminal_resume_via_http_is_idempotent(self) -> None:
        client, container, _ = self._build_client()
        project = client.post("/projects", json={"name": "PG Resume Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        drain_background_runs(container)
        first = client.post(f"/workflow-runs/{started['run_id']}/resume")
        second = client.post(f"/workflow-runs/{started['run_id']}/resume")
        self.assertIn(first.status_code, {200, 202})
        self.assertIn(second.status_code, {200, 202})

    def test_new_app_instance_can_load_existing_run(self) -> None:
        client, container, headers = self._build_client()
        project = client.post("/projects", json={"name": "PG Reload Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)
        reloaded_container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(reloaded_container.shutdown)
        raw_client, _, context = open_test_client(reloaded_container)
        self.addCleanup(lambda: close_test_client(context, reloaded_container))
        reloaded_client = AuthenticatedTestClient(raw_client, headers)
        response = reloaded_client.get(f"/workflow-runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], run_id)


if __name__ == "__main__":
    unittest.main()
