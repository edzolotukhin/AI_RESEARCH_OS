from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase


PUBLIC_PATHS = {"/health", "/ready", "/openapi.json", "/docs", "/redoc"}


class OpenAPISecurityContractTests(ApiTestCase):

    def test_api_key_bearer_declared_exactly_once(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        schemes = schema["components"]["securitySchemes"]
        bearer_schemes = [
            name
            for name, definition in schemes.items()
            if definition.get("type") == "http"
            and definition.get("scheme") == "bearer"
        ]
        self.assertEqual(bearer_schemes, ["ApiKeyBearer"])

    def test_business_routes_require_security(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        for path, methods in schema["paths"].items():
            if path in PUBLIC_PATHS:
                continue
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                with self.subTest(path=path, method=method):
                    self.assertIn(
                        {"ApiKeyBearer": []},
                        operation.get("security", []),
                    )

    def test_public_routes_do_not_require_security(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        for path in ("/health", "/ready"):
            operation = schema["paths"][path]["get"]
            self.assertNotIn("security", operation)

    def test_openapi_examples_do_not_contain_real_credentials(self) -> None:
        schema = self._raw_client.get("/openapi.json").json()
        serialized = str(schema)
        self.assertNotRegex(serialized, r"Bearer airos_[0-9a-f]{12}_[A-Za-z0-9_-]{20,}")


if __name__ == "__main__":
    unittest.main()
