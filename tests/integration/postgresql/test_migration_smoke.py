from __future__ import annotations

import os
import unittest

from alembic import command
from alembic.config import Config

from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL migration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLMigrationSmokeTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database_url = os.environ["DATABASE_URL_TEST"]

    def test_upgrade_and_downgrade_head(self) -> None:
        alembic_cfg = Config("alembic.ini")
        os.environ["DATABASE_URL"] = self.database_url

        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")

        with self.engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()

        table_names = {row[0] for row in tables}
        self.assertIn("projects", table_names)
        self.assertIn("workflow_runs", table_names)


if __name__ == "__main__":
    unittest.main()
