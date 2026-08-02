"""API tests for ResearchDesign exposure on workflow runs."""

from __future__ import annotations

import unittest

from tests.api.auth_helpers import auth_headers, bootstrap_second_test_api_key
from tests.api.helpers import ApiTestCase, AuthenticatedTestClient
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST


class ResearchDesignApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        project = self.client.post("/projects", json={"name": "Design Project"}).json()
        self.project_id = project["id"]

    def test_start_research_exposes_research_design(self) -> None:
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        design = payload.get("research_design")
        self.assertIsNotNone(design)
        self.assertGreaterEqual(len(design["research_questions"]), 1)
        self.assertGreaterEqual(len(design["source_strategy"]), 1)
        self.assertGreaterEqual(len(design["analysis_plan"]), 1)
        self.assertGreaterEqual(len(design["deliverable_plan"]), 1)

    def test_get_run_includes_research_design(self) -> None:
        started = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
        ).json()
        run = self.client.get(f"/workflow-runs/{started['run_id']}").json()
        self.assertIsNotNone(run.get("research_design"))
        self.assertEqual(
            run["research_design"]["research_questions"][0]["id"],
            started["research_design"]["research_questions"][0]["id"],
        )

    def test_idempotent_replay_returns_same_design(self) -> None:
        headers = {"Idempotency-Key": "design-replay-key"}
        first = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
            headers=headers,
        ).json()
        second = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
            headers=headers,
        ).json()
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(
            first["research_design"]["research_questions"],
            second["research_design"]["research_questions"],
        )

    def test_foreign_principal_cannot_see_design(self) -> None:
        started = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
        ).json()
        other_key = bootstrap_second_test_api_key(self.container, name="foreign")
        foreign = AuthenticatedTestClient(self._raw_client, auth_headers(other_key))
        response = foreign.get(f"/workflow-runs/{started['run_id']}")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
