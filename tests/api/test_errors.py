from __future__ import annotations

import unittest

from tests.api.auth_helpers import auth_headers
from tests.api.helpers import ApiTestCase, AuthenticatedTestClient, build_test_container, close_test_client, open_test_client


class ErrorEnvelopeTests(ApiTestCase):

    def test_internal_error_does_not_leak_stack_trace(self) -> None:
        original = self.container.check_readiness

        def _boom() -> tuple[bool, str]:
            raise RuntimeError("secret internal detail")

        self.container.readiness_check = _boom
        try:
            response = self.client.get("/ready")
        finally:
            self.container.readiness_check = original

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "internal_error")
        self.assertNotIn("secret internal detail", response.text)
        self.assertNotIn("Traceback", response.text)
        self.assertNotIn("sqlalchemy", response.text.lower())

    def test_resume_on_non_durable_backend_returns_409(self) -> None:
        container = build_test_container(
            persistence_backend="file",
        )
        raw_client, _, context = open_test_client(container)
        client = AuthenticatedTestClient(
            raw_client,
            auth_headers(container._test_api_key_plaintext),
        )
        try:
            project = client.post("/projects", json={"name": "File Backend"}).json()
            response = client.post(f"/workflow-runs/{project['id']}/resume")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["code"],
                "durable_execution_unavailable",
            )
        finally:
            close_test_client(context, container)


if __name__ == "__main__":
    unittest.main()
