from __future__ import annotations

import json
import unittest

from sqlalchemy import text

from tests.application.report.test_report_claim_contract import ReportClaimContractTests
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
    reset_schema,
)


@unittest.skipUnless(integration_tests_enabled(), "isolated PostgreSQL integration database required")
class PostgreSQLSchemaLifecycleTests(PostgreSQLIntegrationTestCase):
    def test_reset_schema_restores_alembic_head_and_migration_objects(self) -> None:
        reset_schema(self.engine)
        with self.engine.begin() as connection:
            self.assertEqual(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                "027_h3_claim_membership",
            )
            self.assertEqual(
                connection.execute(text(
                    "SELECT COUNT(*) FROM pg_constraint "
                    "WHERE conrelid = 'report_claims'::regclass "
                    "AND conname = 'ck_report_claims_contract_version'"
                )).scalar_one(),
                1,
            )
            self.assertEqual(
                connection.execute(text(
                    "SELECT COUNT(*) FROM pg_class "
                    "WHERE relname = 'report_revision_claims'"
                )).scalar_one(),
                1,
            )
            trigger_names = set(connection.execute(text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid IN ('report_claims'::regclass, 'report_revision_claims'::regclass) "
                "AND NOT tgisinternal"
            )).scalars())
        self.assertEqual(
            trigger_names,
            {
                "trg_report_claims_immutable",
                "trg_report_claims_membership_compatibility",
                "trg_report_revision_claims_immutable",
            },
        )

    def test_reset_schema_restores_h2_membership_and_rejection_behaviors(self) -> None:
        reset_schema(self.engine)
        fixture = ReportClaimContractTests()
        fixture.setUp()
        claim = fixture.claim()
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO projects (id,name,status,created_at,updated_at,version) "
                "VALUES ('lifecycle-project','Lifecycle','ACTIVE','', '', 1)"
            ))
            connection.execute(text(
                "INSERT INTO reports (id,project_id,workflow_run_id,research_design_id,title,language,sections,executive_summary,limitations,created_at,generation_method,finding_refs,insight_refs,evidence_refs,citation_registry,deduplication_key,revision_number,approval_status,metadata,version) "
                "VALUES ('lifecycle-report','lifecycle-project','run','design-1','R','uk','[]','','[]',CURRENT_TIMESTAMP,'h2','[]','[]','[]','{}','lifecycle-key',1,'draft','{}',0)"
            ))
            connection.execute(text(
                "INSERT INTO report_claims (id,report_id,report_revision,project_id,source_workflow_run_id,report_workflow_run_id,research_design_id,contract_version,claim_payload,authority_digest,created_at) "
                "VALUES ('lifecycle-claim','lifecycle-report',1,'lifecycle-project','source-run','run','design-1','desk_report_claim_v1',CAST(:payload AS jsonb),'digest',CURRENT_TIMESTAMP)"
            ), {"payload": json.dumps(claim.to_dict())})
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM report_revision_claims WHERE report_claim_id='lifecycle-claim'"
            )).scalar_one(), 1)
            with self.assertRaises(Exception):
                connection.execute(text(
                    "INSERT INTO report_claims (id,report_id,report_revision,project_id,source_workflow_run_id,report_workflow_run_id,research_design_id,contract_version,claim_payload,authority_digest,created_at) "
                    "VALUES ('lifecycle-editorial','lifecycle-report',1,'lifecycle-project','source-run','run','design-1','desk_editorial_v1','{}','digest-2',CURRENT_TIMESTAMP)"
                ))
            with self.assertRaises(Exception):
                connection.execute(text(
                    "UPDATE report_claims SET authority_digest='changed' WHERE id='lifecycle-claim'"
                ))
            with self.assertRaises(Exception):
                connection.execute(text(
                    "UPDATE report_revision_claims SET report_revision=2 "
                    "WHERE report_claim_id='lifecycle-claim'"
                ))
