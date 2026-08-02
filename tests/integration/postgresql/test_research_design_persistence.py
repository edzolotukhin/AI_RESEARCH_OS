"""PostgreSQL persistence tests for ResearchDesign snapshots."""

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


class ResearchDesignPostgreSQLIntegrationTests(PostgreSQLIntegrationTestCase):
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

    def test_design_snapshot_persists_and_is_immutable(self) -> None:
        client, container = self._build_client()
        project = client.post("/projects", json={"name": "PG Design"}).json()
        project_id = project["id"]

        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
        ).json()
        run_id = started["run_id"]
        original_question_id = started["research_design"]["research_questions"][0]["id"]

        template = container.workflow_service.get_template(
            started["workflow_template_id"],
        )
        self.assertIsNotNone(template.research_design_snapshot)
        assert template.research_design_snapshot is not None
        self.assertEqual(
            template.research_design_snapshot.research_questions[0].id,
            original_question_id,
        )

        replay_headers = {"Idempotency-Key": "pg-design-replay"}
        replay = client.post(
            f"/projects/{project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
            headers=replay_headers,
        ).json()
        replay_again = client.post(
            f"/projects/{project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
            headers=replay_headers,
        ).json()
        self.assertEqual(replay["run_id"], replay_again["run_id"])

        reloaded = client.get(f"/workflow-runs/{run_id}").json()
        self.assertEqual(
            reloaded["research_design"]["research_questions"][0]["id"],
            original_question_id,
        )


if __name__ == "__main__":
    unittest.main()
