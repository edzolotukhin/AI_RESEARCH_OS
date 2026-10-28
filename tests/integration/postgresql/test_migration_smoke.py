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
            command.upgrade(alembic_cfg, "025_desk_structured_finalization")
            with self.engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO projects "
                    "(id,name,status,created_at,updated_at,version) "
                    "VALUES ('legacy-project','Legacy','ACTIVE','','',1)"
                ))
                connection.execute(text(
                    "INSERT INTO artifacts "
                    "(id,project_id,run_id,artifact_type,title,content,status,version,"
                    "media_type,filename,content_checksum,deduplication_key,report_id) "
                    "VALUES ('legacy-artifact','legacy-project','legacy-run','legacy',"
                    "'Legacy','legacy','Draft',1,'text/plain','legacy.txt','',"
                    "'legacy-key','legacy-report')"
                ))
                connection.execute(text(
                    "INSERT INTO pdf_deliverables "
                    "(id,project_id,method,run_id,study_id,source_id,source_version,"
                    "status_snapshot,renderer_version,created_at,storage_key,checksum,"
                    "byte_size,filename,media_type,state,content,format,template_version) "
                    "VALUES ('00000000-0000-0000-0000-000000000001','legacy-project',"
                    "'DESK','legacy-run',NULL,'legacy-report','legacy-v1','Draft',"
                    "'legacy-renderer',CURRENT_TIMESTAMP,'legacy-storage',:checksum,"
                    "5,'legacy.pdf','application/pdf','completed',:content,'PDF','pdf-v1')"
                ), {"checksum": "0" * 64, "content": b"%PDF-"})
                connection.execute(text(
                    "INSERT INTO presentation_jobs "
                    "(id,project_id,method,run_id,study_id,source_id,source_version,"
                    "status_snapshot,template_version,renderer_version,state,attempts,"
                    "lease_until,claimed_by,created_at,updated_at,completed_deliverable_id,"
                    "failure_code,report_revision,review_id,source_run_id,claim_set_digest,"
                    "coverage_contract_digest) VALUES "
                    "('00000000-0000-0000-0000-000000000002','legacy-project','DESK',"
                    "'legacy-run',NULL,'legacy-report','legacy-v1','Draft','legacy-template',"
                    "'legacy-renderer','pending',0,NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,"
                    "NULL,NULL,NULL,NULL,NULL,NULL,NULL)"
                ))
            command.upgrade(alembic_cfg, "head")
            with self.engine.connect() as connection:
                self.assertEqual(connection.execute(text(
                    "SELECT COUNT(*) FROM artifacts WHERE id='legacy-artifact'"
                )).scalar_one(), 1)
                self.assertEqual(connection.execute(text(
                    "SELECT COUNT(*) FROM pdf_deliverables "
                    "WHERE id='00000000-0000-0000-0000-000000000001' "
                    "AND approved_revision_number IS NULL"
                )).scalar_one(), 1)
                self.assertEqual(connection.execute(text(
                    "SELECT COUNT(*) FROM presentation_jobs "
                    "WHERE id='00000000-0000-0000-0000-000000000002' "
                    "AND authority_digest IS NULL AND presentation_digest IS NULL"
                )).scalar_one(), 1)
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
        self.assertIn("presentation_jobs", table_names)
        self.assertIn("report_claims", table_names)
        self.assertTrue({"users", "browser_sessions", "project_memberships"}.issubset(table_names))
        with self.engine.connect() as connection:
            columns = set(connection.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'pdf_deliverables'"
            )).scalars())
        self.assertTrue({"format", "template_version"}.issubset(columns))
        self.assertTrue({
            "approved_revision_number",
            "approved_authority_digest",
            "approved_presentation_digest",
            "approved_review_id",
            "approved_source_workflow_run_id",
            "approved_claim_set_digest",
            "approved_coverage_contract_digest",
        }.issubset(columns))
        with self.engine.connect() as connection:
            presentation_columns = set(connection.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'presentation_jobs'"
            )).scalars())
        self.assertTrue({"authority_digest", "presentation_digest"}.issubset(
            presentation_columns
        ))
        with self.engine.connect() as connection:
            trigger_exists = connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = "
                "'pdf_deliverables'::regclass AND tgname = 'trg_pdf_deliverable_immutable')"
            )).scalar_one()
        self.assertTrue(trigger_exists, "Completed PDF immutability trigger must survive migration round-trip")


if __name__ == "__main__":
    unittest.main()
