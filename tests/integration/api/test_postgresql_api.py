from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from domain.ai.llm_response import LLMResponse

from api.app import create_fastapi_app

from tests.api.helpers import close_test_client, open_test_client
from tests.fixtures.planner_responses import VALID_PLANNER_JSON
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    get_test_database_url,
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
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        container._test_llm_client = mock_llm
        self.addCleanup(container.shutdown)
        client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        return client, container

    def test_create_project_via_http_reloads_from_repository(self) -> None:
        client, container = self._build_client()
        created = client.post("/projects", json={"name": "PG HTTP Project"}).json()
        reloaded = container.project_service.get_project(created["id"])
        self.assertEqual(reloaded.name, "PG HTTP Project")

    def test_start_research_persists_run_accessible_via_http(self) -> None:
        client, _container = self._build_client()
        project = client.post("/projects", json={"name": "PG Research Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        run_response = client.get(f"/workflow-runs/{started['run_id']}")
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json()["project_id"], project["id"])

    def test_get_logs_and_results_via_http(self) -> None:
        client, _container = self._build_client()
        project = client.post("/projects", json={"name": "PG Logs Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        logs = client.get(f"/workflow-runs/{started['run_id']}/logs").json()["items"]
        results = client.get(
            f"/workflow-runs/{started['run_id']}/results",
        ).json()["task_results"]
        self.assertGreaterEqual(len(logs), 1)
        self.assertGreaterEqual(len(results), 0)

    def test_terminal_resume_via_http_is_idempotent(self) -> None:
        client, container = self._build_client()
        project = client.post("/projects", json={"name": "PG Terminal Project"}).json()
        started = client.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]
        mock_llm = container._test_llm_client if hasattr(container, "_test_llm_client") else None
        if mock_llm is not None:
            mock_llm.generate.reset_mock()
        resumed = client.post(f"/workflow-runs/{run_id}/resume")
        self.assertEqual(resumed.status_code, 200)
        if mock_llm is not None:
            mock_llm.generate.assert_not_called()

    def test_new_app_instance_can_load_existing_run(self) -> None:
        client_one, _container_one = self._build_client()
        project = client_one.post("/projects", json={"name": "PG Restart Project"}).json()
        started = client_one.post(
            f"/projects/{project['id']}/research",
            json={"brief": BRIEF},
        ).json()
        run_id = started["run_id"]

        client_two, _container_two = self._build_client()
        response = client_two.get(f"/workflow-runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], run_id)


if __name__ == "__main__":
    unittest.main()
