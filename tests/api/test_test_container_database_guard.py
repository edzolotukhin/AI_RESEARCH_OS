import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.api.helpers import build_test_container


class TestContainerDatabaseGuardTests(unittest.TestCase):
    def test_postgresql_requires_database_url_test(self):
        with patch.dict(os.environ, {"DATABASE_URL_TEST": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL_TEST is required"):
                build_test_container(persistence_backend="postgresql")

    def test_postgresql_does_not_fallback_when_variable_is_absent(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://must-not-be-used"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL_TEST is required"):
                build_test_container(persistence_backend="postgresql")

    def test_postgresql_passes_test_url_to_application_config(self):
        captured = {}
        fake = SimpleNamespace(
            agency=SimpleNamespace(initialize=lambda: None),
            authentication_service=None,
        )

        def capture(*, config, overrides):
            captured["config"] = config
            return fake

        with patch.dict(os.environ, {"DATABASE_URL_TEST": "postgresql://isolated-test"}, clear=False):
            with patch("tests.api.helpers.create_application_container", side_effect=capture):
                self.assertIs(build_test_container(persistence_backend="postgresql"), fake)
        self.assertEqual(captured["config"].database_url, "postgresql://isolated-test")

    def test_memory_backend_does_not_require_database_url_test(self):
        container = build_test_container(persistence_backend="memory")
        container.shutdown()


if __name__ == "__main__":
    unittest.main()
