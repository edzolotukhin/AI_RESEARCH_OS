from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase


class HealthEndpointTests(ApiTestCase):

    def test_health_returns_200(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "ai-research-os")
        self.assertEqual(payload["persistence_backend"], "memory")

    def test_health_does_not_require_database(self) -> None:
        self.container.readiness_check = lambda: (False, "database_unavailable")
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_ready_returns_200_for_memory_backend(self) -> None:
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_ready_returns_503_when_alembic_schema_missing(self) -> None:
        self.container.readiness_check = lambda: (False, "schema_not_ready")
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "schema_not_ready")

    def test_ready_returns_503_when_dependency_check_fails(self) -> None:
        self.container.readiness_check = lambda: (False, "database_unavailable")
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertEqual(response.json()["reason"], "database_unavailable")
        self.assertNotIn("password", response.text.lower())


if __name__ == "__main__":
    unittest.main()
