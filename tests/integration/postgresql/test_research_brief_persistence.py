from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, open_test_client
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class ResearchBriefPostgreSQLIntegrationTests(PostgreSQLIntegrationTestCase):
    def _build_client(self):
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        container._test_llm_client = mock_llm
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        headers = auth_headers(container._test_api_key_plaintext)
        client = AuthenticatedTestClient(raw_client, headers)
        return client, container

    def test_project_brief_persists_and_run_snapshot_is_immutable(self) -> None:
        client, container = self._build_client()
        project = client.post("/projects", json={"name": "PG Brief"}).json()
        project_id = project["id"]

        updated_brief = dict(CANONICAL_BRIEF_REQUEST)
        updated_brief["title"] = "Original Title"
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": updated_brief},
        ).json()
        run_id = started["run_id"]

        reloaded_project = container.project_service.get_project(project_id)
        self.assertIsNotNone(reloaded_project.research_brief)
        self.assertEqual(reloaded_project.research_brief.title, "Original Title")

        changed = dict(CANONICAL_BRIEF_REQUEST)
        changed["title"] = "Changed Title"
        client.post(
            f"/projects/{project_id}/research",
            json={"brief": changed},
        )
        reloaded_project = container.project_service.get_project(project_id)
        self.assertEqual(reloaded_project.research_brief.title, "Changed Title")

        template = container.workflow_service.get_template(
            started["workflow_template_id"],
        )
        self.assertIsNotNone(template.research_brief_snapshot)
        self.assertEqual(template.research_brief_snapshot.title, "Original Title")

        run = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(run["research_brief"]["title"], "Original Title")


if __name__ == "__main__":
    unittest.main()
