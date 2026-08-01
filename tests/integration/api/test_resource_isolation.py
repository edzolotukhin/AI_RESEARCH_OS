from __future__ import annotations

import unittest
from uuid import uuid4
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from domain.ai.llm_response import LLMResponse

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, open_test_client
from tests.fixtures.planner_responses import VALID_PLANNER_JSON
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    get_test_database_url,
)

BRIEF = {
    "client": "Purina",
    "project_title": "Isolation Project",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class ResourceIsolationIntegrationTests(PostgreSQLIntegrationTestCase):

    def _build_two_clients(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        container_a = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container_a, name="principal-a")
        headers_a = auth_headers(container_a._test_api_key_plaintext)
        raw_a, _, context_a = open_test_client(container_a)

        container_b = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container_b, name="principal-b")
        headers_b = auth_headers(container_b._test_api_key_plaintext)
        raw_b, _, context_b = open_test_client(container_b)

        self.addCleanup(lambda: close_test_client(context_a, container_a))
        self.addCleanup(lambda: close_test_client(context_b, container_b))
        self.addCleanup(container_a.shutdown)
        self.addCleanup(container_b.shutdown)

        return (
            AuthenticatedTestClient(raw_a, headers_a),
            AuthenticatedTestClient(raw_b, headers_b),
            container_a,
        )

    def _create_owned_run(self, client_a):
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        run_id = client_a.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()["run_id"]
        return project_id, run_id

    def test_authorization_matrix_returns_404_for_foreign_principal(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id, run_id = self._create_owned_run(client_a)

        cases = [
            ("GET", f"/projects/{project_id}"),
            ("POST", f"/projects/{project_id}/research"),
            ("GET", f"/projects/{project_id}/workflow-runs"),
            ("GET", f"/projects/{project_id}/artifacts"),
            ("GET", f"/workflow-runs/{run_id}"),
            ("POST", f"/workflow-runs/{run_id}/resume"),
            ("GET", f"/workflow-runs/{run_id}/results"),
            ("GET", f"/workflow-runs/{run_id}/logs"),
            ("GET", f"/workflow-runs/{run_id}/artifacts"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                if method == "GET":
                    response = client_b.get(path)
                else:
                    body = {"brief": BRIEF} if "research" in path else None
                    response = client_b.post(path, json=body)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["error"]["code"], "entity_not_found")

    def test_project_list_excludes_foreign_projects(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        self._create_owned_run(client_a)
        self.assertEqual(client_b.get("/projects").json()["items"], [])

    def test_guessed_and_missing_uuid_responses_are_indistinguishable(self) -> None:
        _, client_b, _ = self._build_two_clients()
        guessed = client_b.get(f"/projects/{uuid4()}").json()
        missing = client_b.get(f"/projects/{uuid4()}").json()
        self.assertEqual(guessed["error"]["code"], missing["error"]["code"])
        self.assertEqual(guessed["error"]["code"], "entity_not_found")

    def test_principal_b_cannot_access_principal_a_project(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        self.assertEqual(client_b.get(f"/projects/{project_id}").status_code, 404)

    def test_principal_b_cannot_submit_research_to_foreign_project(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        response = client_b.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        )
        self.assertEqual(response.status_code, 404)

    def test_principal_b_cannot_read_foreign_run(self) -> None:
        client_a, client_b, container_a = self._build_two_clients()
        project_id, run_id = self._create_owned_run(client_a)
        self.assertEqual(client_b.get(f"/workflow-runs/{run_id}").status_code, 404)
        runs = container_a.workflow_service.list_workflow_runs_for_project(project_id)
        self.assertEqual(len(runs), 1)


if __name__ == "__main__":
    unittest.main()
