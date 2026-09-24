from __future__ import annotations

import os
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from tests.integration.postgresql.helpers import (
    integration_tests_enabled,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL migration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLMigrationSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL_MIGRATION_TEST")
        if not self.database_url:
            self.fail("DATABASE_URL_MIGRATION_TEST must name an isolated migration database")
        integration_url = make_url(os.environ["DATABASE_URL_TEST"])
        migration_url = make_url(self.database_url)
        if (
            migration_url.drivername != integration_url.drivername
            or migration_url.host != integration_url.host
            or migration_url.port != integration_url.port
            or not migration_url.database
            or "test" not in migration_url.database.lower()
            or migration_url.database == integration_url.database
        ):
            self.fail("Migration database must be a separate PostgreSQL test database on the same server")
        if os.environ.get("CI") == "true" and migration_url.database != os.environ.get(
            "CI_POSTGRESQL_MIGRATION_DATABASE"
        ):
            self.fail("Migration database does not match the CI isolated database")
        self.engine = create_engine(self.database_url, future=True, poolclass=NullPool)
        self.addCleanup(self.engine.dispose)

    def test_upgrade_and_downgrade_head(self) -> None:
        alembic_cfg = Config("alembic.ini")
        with self.engine.connect() as connection:
            existing = connection.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )).scalars().all()
        self.assertEqual(existing, [], "Migration smoke requires a pristine database")
        previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = self.database_url
        try:
            command.upgrade(alembic_cfg, "head")
            command.downgrade(alembic_cfg, "base")
            command.upgrade(alembic_cfg, "head")
        finally:
            if previous_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_url

        with self.engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()

        table_names = {row[0] for row in tables}
        self.assertIn("projects", table_names)
        self.assertIn("workflow_runs", table_names)
        self.assertIn("pdf_deliverables", table_names)
        with self.engine.connect() as connection:
            trigger_exists = connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = "
                "'pdf_deliverables'::regclass AND tgname = 'trg_pdf_deliverable_immutable')"
            )).scalar_one()
        self.assertTrue(trigger_exists, "Completed PDF immutability trigger must survive migration round-trip")


if __name__ == "__main__":
    unittest.main()
