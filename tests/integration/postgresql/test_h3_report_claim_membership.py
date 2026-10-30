from __future__ import annotations

import unittest
from dataclasses import replace
from uuid import uuid4
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from application.ports.report_claim_repository import ReportClaimConflictError
from domain.factories.project_factory import ProjectFactory
from domain.reports.report import Report
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_report_claim_repository import (
    PostgreSQLReportClaimRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
    PostgreSQLReportRepository,
)
from tests.application.report.test_h3_claim_generation import _Fixture, _valid_response
from application.report.h3_claim_generation import generate_h3_structural_claims
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


@unittest.skipUnless(integration_tests_enabled(), "isolated PostgreSQL integration database required")
class PostgreSQLMigration027Tests(unittest.TestCase):
    def test_upgrade_026_to_027_backfills_h2_membership(self) -> None:
        database_url = os.environ.get("DATABASE_URL_MIGRATION_TEST")
        self.assertTrue(database_url, "DATABASE_URL_MIGRATION_TEST is required")
        integration_url = make_url(os.environ["DATABASE_URL_TEST"])
        migration_url = make_url(database_url)
        self.assertNotEqual(migration_url.database, integration_url.database)
        engine = create_engine(database_url, future=True, poolclass=NullPool)
        config = Config("alembic.ini")
        previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")).scalar_one(), 0)
            command.upgrade(config, "026_approved_delivery_provenance")
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO projects (id,name,status,created_at,updated_at,version) VALUES ('m027-project','M027','ACTIVE','', '', 1)"))
                connection.execute(text("INSERT INTO reports (id,project_id,workflow_run_id,research_design_id,title,language,sections,executive_summary,limitations,created_at,generation_method,finding_refs,insight_refs,evidence_refs,citation_registry,deduplication_key,revision_number,approval_status,metadata,version) VALUES ('m027-report','m027-project','m027-run','m027-design','R','uk','[]','','[]',CURRENT_TIMESTAMP,'h2','[]','[]','[]','{}','m027-key',1,'draft','{}',0)"))
                connection.execute(text("INSERT INTO report_claims (id,report_id,report_revision,project_id,source_workflow_run_id,report_workflow_run_id,research_design_id,contract_version,claim_payload,authority_digest,created_at) VALUES ('m027-claim','m027-report',1,'m027-project','m027-source','m027-run','m027-design','desk_report_claim_v1','{}','m027-digest',CURRENT_TIMESTAMP)"))
            command.upgrade(config, "027_h3_report_revision_claim_membership")
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM report_revision_claims WHERE report_claim_id='m027-claim'")).scalar_one(), 1)
                self.assertEqual(connection.execute(text("SELECT contract_version FROM report_claims WHERE id='m027-claim'")).scalar_one(), "desk_report_claim_v1")
                self.assertEqual(connection.execute(text("SELECT id FROM reports WHERE id='m027-report'")).scalar_one(), "m027-report")
        finally:
            try:
                command.downgrade(config, "base")
            finally:
                engine.dispose()
                if previous_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = previous_url

    def test_downgrade_refuses_after_h3_multi_membership(self) -> None:
        database_url = os.environ.get("DATABASE_URL_MIGRATION_TEST")
        self.assertTrue(database_url, "DATABASE_URL_MIGRATION_TEST is required")
        engine = create_engine(database_url, future=True, poolclass=NullPool)
        config = Config("alembic.ini")
        previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")).scalar_one(), 0)
            command.upgrade(config, "027_h3_report_revision_claim_membership")
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO projects (id,name,status,created_at,updated_at,version) VALUES ('d027-project','D027','ACTIVE','', '', 1)"))
                connection.execute(text("INSERT INTO reports (id,project_id,workflow_run_id,research_design_id,title,language,sections,executive_summary,limitations,created_at,generation_method,finding_refs,insight_refs,evidence_refs,citation_registry,deduplication_key,revision_number,approval_status,metadata,version) VALUES ('d027-r1','d027-project','run','design','R','uk','[]','','[]',CURRENT_TIMESTAMP,'h3','[]','[]','[]','{}','d027-r1',1,'draft','{}',0),('d027-r2','d027-project','run','design','R','uk','[]','','[]',CURRENT_TIMESTAMP,'h3','[]','[]','[]','{}','d027-r2',2,'draft','{}',0)"))
                connection.execute(text("INSERT INTO report_claims (id,report_id,report_revision,project_id,source_workflow_run_id,report_workflow_run_id,research_design_id,contract_version,claim_payload,authority_digest,created_at) VALUES ('d027-claim','d027-r1',1,'d027-project','source','run','design','desk_h3_structural_claim_v1','{}','d027-digest',CURRENT_TIMESTAMP)"))
                connection.execute(text("INSERT INTO report_revision_claims (report_id,report_revision,report_claim_id) VALUES ('d027-r2',2,'d027-claim')"))
            with self.assertRaises(RuntimeError):
                command.downgrade(config, "026_approved_delivery_provenance")
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM report_revision_claims WHERE report_claim_id='d027-claim'")).scalar_one(), 2)
                self.assertEqual(connection.execute(text("SELECT authority_digest FROM report_claims WHERE id='d027-claim'")).scalar_one(), "d027-digest")
        finally:
            try:
                command.downgrade(config, "base")
            except Exception:
                pass
            engine.dispose()
            if previous_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_url


@unittest.skipUnless(integration_tests_enabled(), "isolated PostgreSQL integration database required")
class PostgreSQLH3ReportClaimMembershipTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.project = ProjectFactory().create("H3 membership project")
        PostgreSQLProjectRepository(self.session_factory).create(self.project)
        self.claims = PostgreSQLReportClaimRepository(self.session_factory)

    def _report(self, report_id: str, revision: int, *, workflow: str = "report-run", previous: str | None = None) -> Report:
        return Report(
            id=report_id, project_id=self.project.id, workflow_run_id=workflow,
            research_design_id="design-1", title="R", language="uk", sections=(),
            executive_summary="", limitations=(), created_at="2026-01-01T00:00:00Z",
            generation_method="h3-test", finding_refs=(), insight_refs=(), evidence_refs=(),
            citation_registry={}, deduplication_key=report_id, revision_number=revision,
            previous_report_id=previous,
            metadata={"structured_claim_contract": "desk_h3_structural_claim_v1"},
        )

    def _claim(self):
        fixture = _Fixture()
        result = generate_h3_structural_claims(
            project_id=self.project.id, source_workflow_run_id="source-run",
            report_workflow_run_id="report-run", design=fixture.design,
            findings=tuple(fixture.findings), insights=(),
            evidence_by_id={item.id: item for item in fixture.evidence},
            citation_id_by_source={"source-1": "citation-1"},
            candidate_provider=_valid_response,
            correction_provider=None, required_research_question_ids=("rq-1",),
            required_information_need_ids=("in-1",),
        )
        return replace(result.claims[0], design_id="design-1")

    def test_h3_contract_and_revision_membership_round_trip(self) -> None:
        claim = self._claim()
        r1 = self._report("r1", 1)
        r2 = self._report("r2", 2, previous="r1")
        self.assertEqual(self.claims.create_with_report(r1, (claim,)), 1)
        PostgreSQLReportRepository(self.session_factory).create(r2)
        self.assertEqual(self.claims.attach_claims_to_report_revision(r2, (claim,)), 1)
        self.assertEqual([c.claim_id for c in self.claims.list_for_report("r1", 1)], [claim.claim_id])
        self.assertEqual([c.claim_id for c in self.claims.list_for_report("r2", 2)], [claim.claim_id])
        self.assertEqual(self.claims.get_by_id(claim.claim_id).authority_digest, claim.authority_digest)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM report_claims")).scalar_one(), 1)
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM report_revision_claims")).scalar_one(), 2)

    def test_exact_attachment_is_idempotent_and_partial_or_extra_fails_closed(self) -> None:
        claim = self._claim()
        r1 = self._report("r1", 1)
        self.claims.create_with_report(r1, (claim,))
        self.assertEqual(self.claims.attach_claims_to_report_revision(r1, (claim,)), 1)
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(r1, ())
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(r1, (replace(claim, proposition="changed"),))

    def test_h2_compatibility_trigger_and_claim_immutability(self) -> None:
        claim = self._claim()
        payload = claim.to_dict()
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO reports (id, project_id, workflow_run_id, research_design_id, title, language, sections, executive_summary, limitations, created_at, generation_method, finding_refs, insight_refs, evidence_refs, citation_registry, deduplication_key, revision_number, approval_status, metadata, version) VALUES (:id,:project,:run,'design-1','R','uk','[]','', '[]', CURRENT_TIMESTAMP,'h2','[]','[]','[]','{}',:key,1,'draft','{}',0)"), {"id": "h2-report", "project": self.project.id, "run": "h2-run", "key": str(uuid4())})
            conn.execute(text("INSERT INTO report_claims (id, report_id, report_revision, project_id, source_workflow_run_id, report_workflow_run_id, research_design_id, contract_version, claim_payload, authority_digest, created_at) VALUES (:id,'h2-report',1,:project,'source-run','h2-run','design-1','desk_report_claim_v1',CAST(:payload AS jsonb),'digest',CURRENT_TIMESTAMP)"), {"id": "h2-claim", "project": self.project.id, "payload": __import__('json').dumps(payload)})
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM report_revision_claims WHERE report_claim_id='h2-claim'")).scalar_one(), 1)
            with self.assertRaises(Exception):
                conn.execute(text("UPDATE report_claims SET authority_digest='changed' WHERE id='h2-claim'"))
            with self.assertRaises(Exception):
                conn.execute(text("DELETE FROM report_claims WHERE id='h2-claim'"))

    def test_h3_and_editorial_contract_constraints(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO reports (id, project_id, workflow_run_id, research_design_id, title, language, sections, executive_summary, limitations, created_at, generation_method, finding_refs, insight_refs, evidence_refs, citation_registry, deduplication_key, revision_number, approval_status, metadata, version) VALUES ('constraint-report',:project,'run','design-1','R','uk','[]','', '[]', CURRENT_TIMESTAMP,'h3','[]','[]','[]','{}',:key,1,'draft','{}',0)"), {"project": self.project.id, "key": str(uuid4())})
            conn.execute(text("INSERT INTO report_claims (id, report_id, report_revision, project_id, source_workflow_run_id, report_workflow_run_id, research_design_id, contract_version, claim_payload, authority_digest, created_at) VALUES ('accepted-h3','constraint-report',1,:project,'source','run','design-1','desk_h3_structural_claim_v1','{}','digest',CURRENT_TIMESTAMP)"), {"project": self.project.id})
            with self.assertRaises(Exception):
                conn.execute(text("INSERT INTO report_claims (id, report_id, report_revision, project_id, source_workflow_run_id, report_workflow_run_id, research_design_id, contract_version, claim_payload, authority_digest, created_at) VALUES (:id,'constraint-report',1,:project,'source','run','design-1','desk_editorial_v1','{}','digest',CURRENT_TIMESTAMP)"), {"id": str(uuid4()), "project": self.project.id})

    def test_membership_update_and_delete_are_immutable(self) -> None:
        claim = self._claim()
        report = self._report("immutable-report", 1)
        self.claims.create_with_report(report, (claim,))
        with self.engine.begin() as conn:
            with self.assertRaises(Exception):
                conn.execute(text("UPDATE report_revision_claims SET report_revision=2 WHERE report_id='immutable-report'"))
            with self.assertRaises(Exception):
                conn.execute(text("DELETE FROM report_revision_claims WHERE report_id='immutable-report'"))
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM report_revision_claims WHERE report_id='immutable-report'")).scalar_one(), 1)

    def test_foreign_project_design_and_lineage_are_rejected(self) -> None:
        claim = self._claim()
        report = self._report("lineage-report", 1)
        self.claims.create_with_report(report, (claim,))
        foreign = replace(report, id="foreign-report", project_id="foreign-project", revision_number=2, previous_report_id="lineage-report")
        PostgreSQLReportRepository(self.session_factory).create(foreign)
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(foreign, (claim,))
        wrong_design = replace(report, id="wrong-design-report", revision_number=2, previous_report_id="lineage-report", research_design_id="other-design")
        PostgreSQLReportRepository(self.session_factory).create(wrong_design)
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(wrong_design, (claim,))
        wrong_source = replace(claim, claim_id="wrong-report-claim", report_workflow_run_id="other-report")
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(report, (wrong_source,))

    def test_legitimate_replay_split_lineage_reuses_authority_and_rejects_third_run(self) -> None:
        source_run, report_run, third_run = "source-run", "report-run", "third-run"
        claim = replace(self._claim(), source_workflow_run_id=source_run, report_workflow_run_id=report_run)
        r1 = self._report("replay-r1", 1, workflow=report_run)
        r2 = self._report("replay-r2", 2, workflow=report_run, previous="replay-r1")
        r3 = self._report("replay-r3", 3, workflow=third_run, previous="replay-r1")
        self.claims.create_with_report(r1, (claim,))
        PostgreSQLReportRepository(self.session_factory).create(r2)
        PostgreSQLReportRepository(self.session_factory).create(r3)
        before = self._authority_count()
        self.claims.attach_claims_to_report_revision(r2, (claim,))
        self.assertNotEqual(source_run, report_run)
        self.assertEqual(self.claims.list_for_report("replay-r1", 1)[0].claim_id, claim.claim_id)
        self.assertEqual(self.claims.list_for_report("replay-r2", 2)[0].claim_id, claim.claim_id)
        loaded = self.claims.get_by_id(claim.claim_id)
        self.assertEqual((loaded.source_workflow_run_id, loaded.report_workflow_run_id), (source_run, report_run))
        self.assertEqual(self._authority_count(), before)
        with self.assertRaises(ReportClaimConflictError):
            self.claims.attach_claims_to_report_revision(r3, (claim,))
        self.assertEqual(self._authority_count(), before)
        self.assertEqual(self.claims.list_for_report("replay-r3", 3), [])

    def test_finding_evidence_digest_and_structural_scope_round_trip(self) -> None:
        claim = self._claim()
        r1 = self._report("digest-r1", 1)
        r2 = self._report("digest-r2", 2, previous="digest-r1")
        self.claims.create_with_report(r1, (claim,))
        PostgreSQLReportRepository(self.session_factory).create(r2)
        self.claims.attach_claims_to_report_revision(r2, (claim,))
        first = self.claims.list_for_report("digest-r1", 1)[0]
        second = self.claims.list_for_report("digest-r2", 2)[0]
        for field in ("claim_id", "finding_ids", "evidence_ids", "finding_content_digests", "evidence_content_digests", "support_evidence_ids", "structural_assertion", "authority_digest", "scope"):
            with self.subTest(field=field):
                self.assertEqual(getattr(first, field), getattr(claim, field))
                self.assertEqual(getattr(second, field), getattr(claim, field))

    def _authority_count(self) -> int:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT COUNT(*) FROM report_claims")).scalar_one()


if __name__ == "__main__":
    unittest.main()
