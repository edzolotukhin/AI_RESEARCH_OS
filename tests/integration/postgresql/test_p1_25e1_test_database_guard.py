from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tests.integration.postgresql.helpers import integration_tests_enabled


class P125E1TestDatabaseGuardTests(unittest.TestCase):
    def enabled(self, *, url: str, disposable: str | None) -> bool:
        environment = {
            "POSTGRESQL_INTEGRATION_TESTS": "1",
            "DATABASE_URL_TEST": url,
        }
        if disposable is not None:
            environment["POSTGRESQL_DISPOSABLE_TEST_DATABASE"] = disposable
        with patch.dict(os.environ, environment, clear=True):
            return integration_tests_enabled()

    def test_destructive_tests_require_explicit_disposable_database_authority(self):
        url = "postgresql+psycopg://user:secret@localhost/ai_research_os_test_guard"
        self.assertFalse(self.enabled(url=url, disposable=None))
        self.assertFalse(self.enabled(url=url, disposable="0"))
        self.assertTrue(self.enabled(url=url, disposable="1"))

    def test_disposable_marker_does_not_authorize_non_test_database(self):
        url = "postgresql+psycopg://user:secret@localhost/ai_research_os_forensic"
        self.assertFalse(self.enabled(url=url, disposable="1"))

    def test_destructive_tests_never_fall_back_to_database_url(self):
        with patch.dict(os.environ, {
            "POSTGRESQL_INTEGRATION_TESTS": "1",
            "POSTGRESQL_DISPOSABLE_TEST_DATABASE": "1",
            "DATABASE_URL": "postgresql+psycopg://user:secret@localhost/ai_research_os_test",
        }, clear=True):
            self.assertFalse(integration_tests_enabled())

    def test_ci_requires_exact_local_database(self):
        environment = {
            "CI": "true",
            "POSTGRESQL_INTEGRATION_TESTS": "1",
            "POSTGRESQL_DISPOSABLE_TEST_DATABASE": "1",
            "CI_POSTGRESQL_TEST_DATABASE": "ai_research_os_test",
        }
        for url, expected in (
            ("postgresql+psycopg://user:secret@localhost/ai_research_os_test", True),
            ("postgresql+psycopg://user:secret@remote.example/ai_research_os_test", False),
            ("postgresql+psycopg://user:secret@localhost/other_test", False),
            ("sqlite:///ai_research_os_test", False),
        ):
            with self.subTest(url=url), patch.dict(
                os.environ, {**environment, "DATABASE_URL_TEST": url, "DATABASE_URL": url}, clear=True
            ):
                self.assertIs(integration_tests_enabled(), expected)

        with patch.dict(os.environ, {
            **environment,
            "DATABASE_URL_TEST": "postgresql+psycopg://user:secret@localhost/ai_research_os_test",
            "DATABASE_URL": "postgresql+psycopg://user:secret@localhost/other_test",
        }, clear=True):
            self.assertFalse(integration_tests_enabled())


if __name__ == "__main__":
    unittest.main()
