from __future__ import annotations

import unittest
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
    "project_title": "Idempotency Boundary",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class CrossPrincipalIdempotencyIntegrationTests(PostgreSQLIntegrationTestCase):

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
        )

    def test_foreign_principal_cannot_replay_idempotency_key(self) -> None:
        client_a, client_b = self._build_two_clients()
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        idempotency_key = "shared-key-boundary"
        first = client_a.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n", "correlation_id": "corr-a"},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(first.status_code, 202)
        run_id = first.json()["run_id"]

        blocked = client_b.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF, "source": "n8n", "correlation_id": "corr-a"},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(blocked.status_code, 404)
        self.assertEqual(blocked.json()["error"]["code"], "entity_not_found")
        self.assertNotIn("run_id", blocked.text)
        self.assertNotIn(run_id, blocked.text)
        self.assertNotIn("corr-a", blocked.text)
        self.assertNotIn("idempotent", blocked.text.lower())


if __name__ == "__main__":
    unittest.main()
