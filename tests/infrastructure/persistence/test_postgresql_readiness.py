from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from infrastructure.persistence.postgresql.readiness import (
    build_postgresql_readiness_check,
    resolve_expected_alembic_head,
)

from tests.api.helpers import ApiTestCase


def _mock_connection(
    *,
    alembic_table_exists: bool = True,
    current_revision: str | None = "001_pf03_initial",
    connect_raises: bool = False,
) -> MagicMock:
    connection = MagicMock()
    if connect_raises:
        raise RuntimeError("connection failed")

    def execute(statement):
        sql = str(statement)
        result = MagicMock()
        if "SELECT 1" in sql and "information_schema" not in sql and "alembic_version" not in sql:
            result.scalar_one.return_value = 1
        elif "information_schema.tables" in sql:
            result.scalar_one.return_value = alembic_table_exists
        elif "alembic_version" in sql:
            result.scalar_one_or_none.return_value = current_revision
        return result

    connection.execute.side_effect = execute
    return connection


def _mock_engine(connection: MagicMock) -> MagicMock:
    engine = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = connection
    context.__exit__.return_value = False
    engine.connect.return_value = context
    return engine


class PostgreSQLReadinessLogicTests(unittest.TestCase):

    def test_resolve_expected_head_matches_repository(self) -> None:
        self.assertEqual(resolve_expected_alembic_head(), "010_dr07_review_quality_gate")

    def test_connection_failure_returns_database_unavailable(self) -> None:
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("connection failed")
        check = build_postgresql_readiness_check(
            engine,
            "001_pf03_initial",
            [],
        )
        ready, reason = check()
        self.assertFalse(ready)
        self.assertEqual(reason, "database_unavailable")

    def test_missing_alembic_version_table_returns_schema_not_ready(self) -> None:
        engine = _mock_engine(_mock_connection(alembic_table_exists=False))
        check = build_postgresql_readiness_check(
            engine,
            "001_pf03_initial",
            [],
        )
        ready, reason = check()
        self.assertFalse(ready)
        self.assertEqual(reason, "schema_not_ready")

    def test_revision_differs_from_head_returns_schema_outdated(self) -> None:
        engine = _mock_engine(
            _mock_connection(current_revision="000_legacy_revision"),
        )
        check = build_postgresql_readiness_check(
            engine,
            "001_pf03_initial",
            [],
        )
        ready, reason = check()
        self.assertFalse(ready)
        self.assertEqual(reason, "schema_outdated")

    def test_revision_equals_head_returns_ready(self) -> None:
        engine = _mock_engine(_mock_connection(current_revision="001_pf03_initial"))
        check = build_postgresql_readiness_check(
            engine,
            "001_pf03_initial",
            [],
        )
        ready, reason = check()
        self.assertTrue(ready)
        self.assertEqual(reason, "ready")

    def test_ready_never_mutates_schema(self) -> None:
        connection = _mock_connection(current_revision="001_pf03_initial")
        engine = _mock_engine(connection)
        check = build_postgresql_readiness_check(
            engine,
            "001_pf03_initial",
            [],
        )
        check()
        check()
        for call in connection.execute.call_args_list:
            sql = str(call.args[0]).upper()
            self.assertNotIn("CREATE", sql)
            self.assertNotIn("ALTER", sql)
            self.assertNotIn("DROP", sql)
            self.assertNotIn("INSERT", sql)
            self.assertNotIn("UPDATE", sql)
            self.assertNotIn("DELETE", sql)


class ReadinessEndpointTests(ApiTestCase):

    def test_memory_backend_ready_returns_200(self) -> None:
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)

    def test_health_stays_200_when_schema_outdated(self) -> None:
        self.container.readiness_check = lambda: (False, "schema_outdated")
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_ready_returns_503_for_schema_outdated(self) -> None:
        self.container.readiness_check = lambda: (False, "schema_outdated")
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "schema_outdated")
        self.assertNotIn("001_pf03_initial", response.text)

    def test_ready_returns_503_for_postgresql_unavailable(self) -> None:
        self.container.readiness_check = lambda: (False, "database_unavailable")
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "database_unavailable")


class PostgreSQLReadinessIntegrationTests(unittest.TestCase):
    """Live revision check against migrated PostgreSQL."""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.integration.postgresql.helpers import require_integration_tests

        require_integration_tests()

    def test_revision_equals_head_after_migration(self) -> None:
        from application.composition_root import create_application_container
        from application.config import ApplicationConfig
        from tests.integration.postgresql.helpers import get_test_database_url

        container = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
            ),
        )
        try:
            ready, reason = container.check_readiness()
            self.assertTrue(ready, reason)
            self.assertEqual(reason, "ready")
        finally:
            container.shutdown()


if __name__ == "__main__":
    unittest.main()
