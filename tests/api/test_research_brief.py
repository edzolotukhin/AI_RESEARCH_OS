from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST, LEGACY_BRIEF_REQUEST


class ResearchBriefApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        project = self.client.post("/projects", json={"name": "Brief Project"}).json()
        self.project_id = project["id"]

    def test_submit_structured_brief(self) -> None:
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIsNotNone(payload.get("research_brief"))
        self.assertEqual(payload["research_brief"]["title"], "Brand Health 2026")

    def test_legacy_brief_shape_accepted(self) -> None:
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": LEGACY_BRIEF_REQUEST},
        )
        self.assertEqual(response.status_code, 202)

    def test_validation_error_returns_422(self) -> None:
        invalid = dict(CANONICAL_BRIEF_REQUEST)
        invalid["title"] = ""
        response = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": invalid},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_get_run_includes_brief_snapshot(self) -> None:
        started = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": CANONICAL_BRIEF_REQUEST},
        ).json()
        run = self.client.get(f"/workflow-runs/{started['run_id']}").json()
        self.assertEqual(run["research_brief"]["business_question"], "Assess market position.")


if __name__ == "__main__":
    unittest.main()
