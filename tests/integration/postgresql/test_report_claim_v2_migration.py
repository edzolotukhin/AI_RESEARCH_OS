from __future__ import annotations

import os
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from tests.integration.postgresql.helpers import integration_tests_enabled


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL migration tests require an isolated test database",
)
class PostgreSQLReportClaimV2MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        database_url = os.environ.get("DATABASE_URL_MIGRATION_TEST")
        if not database_url:
            self.fail("DATABASE_URL_MIGRATION_TEST must name an isolated database")
        self._previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        self.engine = create_engine(database_url, future=True, poolclass=NullPool)
        self.config = Config("alembic.ini")
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
        command.upgrade(self.config, "030_source_revisions")

    def tearDown(self) -> None:
        try:
            with self.engine.begin() as connection:
                connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
                connection.exec_driver_sql("CREATE SCHEMA public")
        finally:
            self.engine.dispose()
            if self._previous_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = self._previous_url

    def _upgrade_031(self) -> None:
        command.upgrade(self.config, "031_report_claim_v2_contract")

    def _insert_v2_claim(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO projects "
                "(id,name,status,created_at,updated_at,version) "
                "VALUES ('migration-project','Migration','ACTIVE','','',1)"
            ))
            connection.execute(text(
                "INSERT INTO reports "
                "(id,project_id,workflow_run_id,research_design_id,title,language,"
                "sections,executive_summary,limitations,created_at,generation_method,"
                "finding_refs,insight_refs,evidence_refs,citation_registry,"
                "deduplication_key,revision_number,approval_status,metadata,version) "
                "VALUES ('migration-report','migration-project','run','design','R','en',"
                "'[]','','[]',CURRENT_TIMESTAMP,'test','[]','[]','[]','{}',"
                "'migration-key',1,'draft','{}',0)"
            ))
            connection.execute(text(
                "INSERT INTO report_claims "
                "(id,report_id,report_revision,project_id,source_workflow_run_id,"
                "report_workflow_run_id,research_design_id,contract_version,"
                "claim_payload,authority_digest,created_at) VALUES "
                "('migration-claim','migration-report',1,'migration-project','source',"
                "'run','design','desk_report_claim_v2','{}','digest',CURRENT_TIMESTAMP)"
            ))

    def test_downgrade_succeeds_without_v2_rows(self) -> None:
        self._upgrade_031()
        command.downgrade(self.config, "030_source_revisions")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                "030_source_revisions",
            )
            definition = connection.execute(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='ck_report_claims_contract_version'"
            )).scalar_one()
        self.assertIn("desk_report_claim_v1", definition)
        self.assertIn("desk_h3_structural_claim_v1", definition)
        self.assertNotIn("desk_report_claim_v2", definition)

    def test_downgrade_rejects_v2_without_schema_change(self) -> None:
        self._upgrade_031()
        self._insert_v2_claim()
        with self.assertRaisesRegex(RuntimeError, "desk_report_claim_v2"):
            command.downgrade(self.config, "030_source_revisions")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                "031_report_claim_v2_contract",
            )
            self.assertEqual(
                connection.execute(text(
                    "SELECT COUNT(*) FROM report_claims "
                    "WHERE contract_version='desk_report_claim_v2'"
                )).scalar_one(),
                1,
            )

    def test_upgrade_restores_v2_support(self) -> None:
        self._upgrade_031()
        command.downgrade(self.config, "030_source_revisions")
        command.upgrade(self.config, "031_report_claim_v2_contract")
        self._insert_v2_claim()
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text(
                    "SELECT contract_version FROM report_claims "
                    "WHERE id='migration-claim'"
                )).scalar_one(),
                "desk_report_claim_v2",
            )


if __name__ == "__main__":
    unittest.main()
