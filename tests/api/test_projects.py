from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase


class ProjectEndpointTests(ApiTestCase):

    def test_create_project_returns_201(self) -> None:
        response = self.client.post("/projects", json={"name": "Brand Health 2026"})
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["name"], "Brand Health 2026")
        self.assertTrue(payload["id"])
        self.assertIn("/projects/", response.headers.get("location", ""))

    def test_get_created_project_returns_200(self) -> None:
        created = self.client.post("/projects", json={"name": "Demo Project"}).json()
        response = self.client.get(f"/projects/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

    def test_get_missing_project_returns_404_envelope(self) -> None:
        response = self.client.get("/projects/missing-project")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "entity_not_found")

    def test_list_projects_supports_pagination(self) -> None:
        self.client.post("/projects", json={"name": "One"})
        self.client.post("/projects", json={"name": "Two"})
        response = self.client.get("/projects", params={"offset": 0, "limit": 1})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["limit"], 1)
        self.assertEqual(len(payload["items"]), 1)

    def test_create_project_validation_error_returns_422(self) -> None:
        response = self.client.post("/projects", json={"name": ""})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "request_validation_error")


if __name__ == "__main__":
    unittest.main()
