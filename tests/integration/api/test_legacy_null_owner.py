from __future__ import annotations

import unittest
from uuid import uuid4

from domain.project import Project
from domain.value_objects.project_status import ProjectStatus
from domain.ai.llm_response import LLMResponse
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, open_test_client
from tests.fixtures.planner_responses import VALID_PLANNER_JSON
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    get_test_database_url,
)

BRIEF = {
    "client": "Purina",
    "project_title": "Legacy Project",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class LegacyNullOwnerIntegrationTests(PostgreSQLIntegrationTestCase):

    def _build_authenticated_client(self):
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
        bootstrap_test_api_key(container, name="legacy-principal")
        headers = auth_headers(container._test_api_key_plaintext)
        raw, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        self.addCleanup(container.shutdown)
        return AuthenticatedTestClient(raw, headers), container

    def _insert_legacy_project(self) -> str:
        repo = PostgreSQLProjectRepository(self.session_factory)
        project = Project(
            id=str(uuid4()),
            name="Legacy",
            status=ProjectStatus.LEAD,
            owner_principal_id=None,
        )
        repo.create(project)
        return project.id

    def test_legacy_null_owner_project_is_inaccessible(self) -> None:
        client, container = self._build_authenticated_client()
        project_id = self._insert_legacy_project()

        self.assertEqual(client.get(f"/projects/{project_id}").status_code, 404)
        listed = client.get("/projects").json()["items"]
        self.assertNotIn(project_id, [item["id"] for item in listed])

        research = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
            headers={"Idempotency-Key": "legacy-key"},
        )
        self.assertEqual(research.status_code, 404)
        self.assertNotIn("run_id", research.text)

        project = container.project_service.get_project(project_id)
        self.assertIsNone(project.owner_principal_id)


if __name__ == "__main__":
    unittest.main()
