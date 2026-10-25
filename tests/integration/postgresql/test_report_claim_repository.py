from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from application.ports.report_claim_repository import ReportClaimConflictError
from domain.factories.project_factory import ProjectFactory
from domain.reports.report import Report
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import PostgreSQLReportRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_claim_repository import PostgreSQLReportClaimRepository
import tests.application.report.test_report_claim_contract as claim_fixtures
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "PostgreSQL integration tests require an isolated disposable database.")
class PostgreSQLReportClaimRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_atomic_report_and_claim_creation(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        project = ProjectFactory().create("Atomic ReportClaim project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        report = Report(id=str(uuid4()), project_id=project.id, workflow_run_id="source-run", research_design_id="design-1", title="R", language="en", sections=(), executive_summary="S", limitations=(), created_at=datetime.now(timezone.utc).isoformat(), generation_method="claim-first:deterministic", finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={}, deduplication_key=str(uuid4()), revision_number=1)
        claim = fixture.claim().__class__.from_dict({**fixture.claim().to_dict(), "project_id": project.id})
        repository = PostgreSQLReportClaimRepository(self.session_factory)

        self.assertEqual(repository.create_with_report(report, (claim,)), 1)
        self.assertIsNotNone(PostgreSQLReportRepository(self.session_factory).get_by_id(report.id))
        self.assertEqual(repository.list_for_report(report.id, 1), [claim])

    def test_atomic_creation_rolls_back_report_when_claim_batch_fails(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        project = ProjectFactory().create("Atomic ReportClaim rollback project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        report = Report(id=str(uuid4()), project_id=project.id, workflow_run_id="source-run", research_design_id="design-1", title="R", language="en", sections=(), executive_summary="S", limitations=(), created_at=datetime.now(timezone.utc).isoformat(), generation_method="claim-first:deterministic", finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={}, deduplication_key=str(uuid4()), revision_number=1)
        claim = fixture.claim().__class__.from_dict({**fixture.claim().to_dict(), "project_id": project.id})
        duplicate = replace(claim)
        repository = PostgreSQLReportClaimRepository(self.session_factory)

        with self.assertRaises(ReportClaimConflictError):
            repository.create_with_report(report, (claim, duplicate))

        self.assertIsNone(PostgreSQLReportRepository(self.session_factory).get_by_id(report.id))
        self.assertEqual(repository.list_for_report(report.id, 1), [])

    def test_round_trip_conflict_and_exact_revision_ownership(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        project = ProjectFactory().create("ReportClaim project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        report = Report(id=str(uuid4()), project_id=project.id, workflow_run_id="source-run", research_design_id="design-1", title="R", language="en", sections=(), executive_summary="S", limitations=(), created_at=datetime.now(timezone.utc).isoformat(), generation_method="deterministic", finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={}, deduplication_key=str(uuid4()), revision_number=2)
        PostgreSQLReportRepository(self.session_factory).create(report)
        claim = fixture.claim()
        claim = claim.__class__.from_dict({**claim.to_dict(), "project_id": project.id})
        repository = PostgreSQLReportClaimRepository(self.session_factory)
        repository.create(claim, report_id=report.id, report_revision=2)
        self.assertEqual(repository.get_by_id(claim.claim_id), claim)
        self.assertEqual(repository.list_for_report(report.id, 2), [claim])
        with self.assertRaises(ReportClaimConflictError): repository.create(claim, report_id=report.id, report_revision=2)
        second = claim.__class__.from_dict({**claim.to_dict(), "claim_id": "claim-2"})
        with self.assertRaises(ReportClaimConflictError): repository.create(second, report_id=report.id, report_revision=1)


if __name__ == "__main__":
    unittest.main()
