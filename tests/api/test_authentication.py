from __future__ import annotations

import logging
import unittest

from tests.api.helpers import ApiTestCase
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST


class AuthenticationApiTests(ApiTestCase):

    def test_health_without_credentials_returns_200(self) -> None:
        response = self._raw_client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_ready_without_credentials_returns_readiness(self) -> None:
        response = self._raw_client.get("/ready")
        self.assertIn(response.status_code, {200, 503})

    def test_protected_endpoint_without_key_returns_401(self) -> None:
        response = self._raw_client.get("/projects")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_malformed_authorization_header_returns_401(self) -> None:
        response = self._raw_client.get(
            "/projects",
            headers={"Authorization": "NotBearer token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_unknown_key_returns_401(self) -> None:
        response = self._raw_client.get(
            "/projects",
            headers={"Authorization": "Bearer airos_deadbeef_not-a-real-key"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("airos_deadbeef_not-a-real-key", response.text)

    def test_valid_key_allows_project_creation(self) -> None:
        response = self.client.post("/projects", json={"name": "Secure Project"})
        self.assertEqual(response.status_code, 201)

    def test_revoked_key_returns_401(self) -> None:
        from datetime import datetime, timezone

        assert self.container.authentication_service is not None
        principal = self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext,
        )
        assert principal.api_key_id is not None
        self.container.authentication_service._api_key_repository.revoke(
            principal.api_key_id,
            revoked_at=datetime.now(timezone.utc),
        )
        response = self._raw_client.get("/projects", headers=self.auth_headers)
        self.assertEqual(response.status_code, 401)

    def test_error_response_never_contains_raw_key(self) -> None:
        secret = self.container._test_api_key_plaintext
        response = self._raw_client.get(
            "/projects",
            headers={"Authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret, response.text)

    def test_structured_logs_do_not_contain_raw_key(self) -> None:
        secret = self.container._test_api_key_plaintext
        with self.assertLogs("api.routers.workflow_runs", level="INFO") as captured:
            project = self.client.post("/projects", json={"name": "Log Safe Project"}).json()
            self.client.post(
                f"/projects/{project['id']}/research",
                json={"brief": CANONICAL_BRIEF_REQUEST},
            )
        combined = "\n".join(record.getMessage() for record in captured.records)
        for record in captured.records:
            if record.__dict__.get("run_id"):
                combined += str(record.__dict__)
        self.assertNotIn(secret, combined)

    def test_openapi_declares_bearer_security_scheme(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        self.assertIn("ApiKeyBearer", schema["components"]["securitySchemes"])

    def test_openapi_marks_projects_as_protected(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        create_op = schema["paths"]["/projects"]["post"]
        self.assertIn({"ApiKeyBearer": []}, create_op["security"])

    def test_openapi_leaves_health_public(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        self.assertNotIn("security", schema["paths"]["/health"]["get"])


if __name__ == "__main__":
    unittest.main()
