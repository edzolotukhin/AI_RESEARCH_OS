from __future__ import annotations

import concurrent.futures
import time
import unittest
from dataclasses import replace
from threading import Barrier, Event

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from application.report.claim_lineage_verification_v2 import ClaimLineageVerificationV2Error
from application.report.claim_revision_orchestration_v2 import create_report_claim_v2_successor
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import PostgreSQLInsightRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_claim_repository import PostgreSQLReportClaimRepository
from application.ports.report_claim_repository import ReportClaimConflictError
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import PostgreSQLReportRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import PostgreSQLWorkflowTemplateRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase
import tests.integration.postgresql.test_report_claim_v2_verification as _verification_module


class PostgreSQLClaimRevisionOrchestrationV2Tests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        fixture = _verification_module.PostgreSQLReportClaimV2VerificationTests()
        fixture._class_engine = self._class_engine
        fixture.setUp()
        # The auxiliary fixture only populates rows. It owns no class-level
        # engine lifecycle or teardown; the outer PostgreSQL test case remains
        # the sole owner of shared engine disposal.
        for name in (
            "engine", "session_factory", "project", "design", "brief", "template",
            "templates", "run", "runs", "sources", "source", "evidence",
            "evidence_repo", "finding", "insight", "findings", "insights", "scope",
            "claim", "report", "claims",
        ):
            setattr(self, name, getattr(fixture, name))

    def successor(self, report_id: str = "successor-v2"):
        return replace(
            self.report,
            id=report_id,
            revision_number=self.report.revision_number + 1,
            previous_report_id=self.report.id,
            deduplication_key=report_id,
        )

    def invoke(self, *, factory=None, report=None, claim_repo=None):
        factory = factory or self.session_factory
        return create_report_claim_v2_successor(
            session_factory=factory,
            parent_report_id=self.report.id,
            parent_claim_id=self.claim.claim_id,
            successor_report=report or self.successor(),
            validated_at="2026-01-01T00:00:00Z",
            report_repository=PostgreSQLReportRepository(factory),
            report_claim_repository=claim_repo or PostgreSQLReportClaimRepository(factory),
            finding_repository=PostgreSQLFindingRepository(factory),
            insight_repository=PostgreSQLInsightRepository(factory),
            evidence_repository=PostgreSQLEvidenceRepository(factory),
            source_repository=PostgreSQLSourceRepository(factory),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(factory),
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(factory),
        )

    def test_successful_atomic_creation_persists_report_claim_and_membership(self) -> None:
        successor, claim, _ = self.invoke()
        loaded = PostgreSQLReportClaimRepository(self.session_factory)
        self.assertIsNotNone(PostgreSQLReportRepository(self.session_factory).get_by_id(successor.id))
        self.assertIsNotNone(loaded.get_by_id(claim.claim_id))
        self.assertEqual([item.claim_id for item in loaded.list_for_report(successor.id, 2)], [claim.claim_id])
        self.assertEqual(claim.report_workflow_run_id, successor.workflow_run_id)

    def test_persistence_failure_rolls_back_all_successor_rows(self) -> None:
        class FailingClaims(PostgreSQLReportClaimRepository):
            def create_with_report(self, report, claims):
                super().create_with_report(report, claims)
                raise RuntimeError("forced post-flush failure")

        successor = self.successor("rollback-successor")
        with self.assertRaises(RuntimeError):
            self.invoke(report=successor, claim_repo=FailingClaims(self.session_factory))
        self.assertIsNone(PostgreSQLReportRepository(self.session_factory).get_by_id(successor.id))
        self.assertEqual(PostgreSQLReportClaimRepository(self.session_factory).list_for_report(successor.id, 2), [])
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM report_claims WHERE report_id=:id"), {"id": successor.id}).scalar_one(), 0)

    def test_two_concurrent_attempts_have_one_successor_winner(self) -> None:
        entered = Barrier(2)
        lock_held = Event()
        release = Event()
        holder_pid: dict[str, int] = {}

        def holder() -> None:
            factory = DatabaseSessionFactory(self.engine)
            try:
                with factory.repeatable_read_transaction():
                    PostgreSQLReportRepository(factory).lock_revision(
                        self.report.id,
                        expected_revision=self.report.revision_number,
                    )
                    session = factory.require_write_transaction()
                    holder_pid["value"] = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                    lock_held.set()
                    release.wait(timeout=10)
            finally:
                release.set()

        def attempt() -> tuple[str, str | None]:
            factory = DatabaseSessionFactory(self.engine)
            try:
                entered.wait(timeout=10)
                self.invoke(factory=factory, report=self.successor("concurrent-successor"))
                return "won", None
            except (ClaimLineageVerificationV2Error, ReportClaimConflictError, OperationalError, DBAPIError) as exc:
                return "lost", type(exc).__name__

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            lock_holder = pool.submit(holder)
            self.assertTrue(lock_held.wait(timeout=10))
            futures = [pool.submit(attempt), pool.submit(attempt)]
            try:
                for future in futures:
                    # Both workers must reach the call before the parent lock
                    # is released; the holder makes the PostgreSQL wait real.
                    self.assertFalse(future.done())
                with self.engine.connect() as connection:
                    deadline = time.monotonic() + 10
                    blocked = False
                    while time.monotonic() < deadline:
                        blocked = bool(connection.execute(text(
                            "SELECT COUNT(*) FROM pg_stat_activity "
                            "WHERE wait_event_type='Lock' AND state='active' "
                            "AND :holder_pid = ANY(pg_blocking_pids(pid))"
                        ), {"holder_pid": holder_pid["value"]}).scalar_one())
                        if blocked:
                            break
                        time.sleep(0.05)
                    self.assertTrue(blocked, "orchestration attempts did not block on PostgreSQL lock")
            finally:
                release.set()
            outcomes = [future.result(timeout=30) for future in futures]
            lock_holder.result(timeout=30)
        self.assertEqual(sorted(item[0] for item in outcomes), ["lost", "won"])
        loser = next(item for item in outcomes if item[0] == "lost")
        self.assertIn(loser[1], {
            "ClaimLineageVerificationV2Error", "ReportClaimConflictError",
            "OperationalError", "DBAPIError",
        })
        reports = PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id)
        self.assertEqual(len([item for item in reports if item.previous_report_id == self.report.id]), 1)

    def test_duplicate_successor_is_rejected_without_additional_rows(self) -> None:
        self.invoke(report=self.successor("duplicate-successor"))
        before = len(PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id))
        with self.assertRaises((ReportClaimConflictError, ValueError, ClaimLineageVerificationV2Error)):
            self.invoke(report=self.successor("duplicate-successor"))
        after = len(PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id))
        self.assertEqual(before, after)

    def test_stale_source_authority_prevents_successor_persistence(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE sources SET content_checksum=:checksum WHERE id=:id"), {"checksum": "e" * 64, "id": self.source.id})
        successor = self.successor("stale-successor")
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.invoke(report=successor)
        self.assertIsNone(PostgreSQLReportRepository(self.session_factory).get_by_id(successor.id))


if __name__ == "__main__":
    unittest.main()
