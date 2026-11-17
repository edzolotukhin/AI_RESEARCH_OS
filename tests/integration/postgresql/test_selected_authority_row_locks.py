from __future__ import annotations

import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import datetime, timezone
from uuid import uuid4

from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require the disposable database harness.",
)
class PostgreSQLSelectedAuthorityRowLockTests(PostgreSQLIntegrationTestCase):
    def test_all_selected_authority_repositories_require_owned_transaction_and_fail_closed(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from tests.integration.postgresql.test_evidence_concurrency import _sample_evidence
        from tests.integration.postgresql.test_finding_concurrency import _sample_finding
        from tests.integration.postgresql.test_insight_concurrency import _sample_insight
        from tests.integration.postgresql.test_source_provenance_concurrency import _sample_source
        from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import PostgreSQLInsightRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository

        project = ProjectFactory().create("Selected authority lock project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        source = _sample_source(
            project_id=project.id,
            run_id="lock-run",
            canonical="https://example.com/selected-lock",
            content="selected source",
        )
        sources = PostgreSQLSourceRepository(self.session_factory)
        sources.create(source)
        finding = replace(_sample_finding(run_id="lock-run", key="selected"), project_id=project.id)
        insight = replace(_sample_insight(run_id="lock-run", key="selected"), project_id=project.id)
        evidence = replace(_sample_evidence(run_id="lock-run", key="selected"), project_id=project.id, source_id=source.id)
        findings = PostgreSQLFindingRepository(self.session_factory)
        insights = PostgreSQLInsightRepository(self.session_factory)
        evidences = PostgreSQLEvidenceRepository(self.session_factory)
        findings.create(finding)
        insights.create(insight)
        evidences.create(evidence)
        repositories = (
            (findings, finding.id),
            (insights, insight.id),
            (evidences, evidence.id),
            (sources, source.id),
        )
        for repository, identifier in repositories:
            with self.subTest(repository=type(repository).__name__):
                with self.assertRaises(RuntimeError):
                    repository.lock_selected_for_authority((identifier,))
                with self.session_factory.transaction():
                    selected = repository.lock_selected_for_authority((identifier,))
                    self.assertEqual(tuple(item.id for item in selected), (identifier,))
                    with self.assertRaises(ValueError):
                        repository.lock_selected_for_authority(("missing-authority-id",))

    def test_source_lock_blocks_versioned_update_and_unrelated_row_remains_writable(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from domain.sources.retrieval_status import RetrievalStatus
        from domain.sources.source import Source
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
        from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
        from sqlalchemy import text

        project = ProjectFactory().create("Source authority lock project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        now = datetime.now(timezone.utc).isoformat()
        sources = PostgreSQLSourceRepository(self.session_factory)
        selected = Source(str(uuid4()), project.id, "https://example.com/selected", "https://example.com/selected", "Selected", now, retrieval_status=RetrievalStatus.ACQUIRED, content_text="selected", content_checksum="selected-checksum")
        unrelated = Source(str(uuid4()), project.id, "https://example.com/unrelated", "https://example.com/unrelated", "Unrelated", now, retrieval_status=RetrievalStatus.ACQUIRED, content_text="unrelated", content_checksum="unrelated-checksum")
        sources.create(selected)
        sources.create(unrelated)
        entered, attempted, completed, unrelated_done, release = Event(), Event(), Event(), Event(), Event()

        def holder() -> None:
            factory = DatabaseSessionFactory(self.engine)
            try:
                with factory.transaction():
                    PostgreSQLSourceRepository(factory).lock_selected_for_authority((selected.id,))
                    entered.set()
                    release.wait(timeout=10)
            finally:
                release.set()

        def updater() -> None:
            attempted.set()
            current = sources.get_by_id(selected.id)
            updated = replace(current, metadata={"discovery_records": ("updated",)})
            sources.save(updated, expected_version=current.version)
            completed.set()

        def unrelated_updater() -> None:
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE sources SET version=version+1 WHERE id=:id"), {"id": unrelated.id})
            unrelated_done.set()

        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(holder)
            self.assertTrue(entered.wait(timeout=10))
            second = pool.submit(updater)
            third = pool.submit(unrelated_updater)
            try:
                self.assertTrue(attempted.wait(timeout=10))
                self.assertTrue(unrelated_done.wait(timeout=10))
                self.assertFalse(completed.wait(timeout=0.5))
            finally:
                release.set()
            first.result(timeout=10)
            second.result(timeout=10)
            third.result(timeout=10)
        self.assertTrue(completed.is_set())

    def test_selected_authority_output_order_is_deterministic(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from domain.sources.retrieval_status import RetrievalStatus
        from domain.sources.source import Source
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
        from infrastructure.persistence.postgresql.session import DatabaseSessionFactory

        project = ProjectFactory().create("Source lock order project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        now = datetime.now(timezone.utc).isoformat()
        sources = PostgreSQLSourceRepository(self.session_factory)
        items = [Source(str(uuid4()), project.id, f"https://example.com/order-{i}", f"https://example.com/order-{i}", str(i), now, retrieval_status=RetrievalStatus.ACQUIRED, content_text=str(i), content_checksum=f"order-{i}") for i in range(3)]
        for item in items:
            sources.create(item)
        ids = tuple(item.id for item in items)
        entered, release = Event(), Event()

        def locked(order: tuple[str, ...]) -> tuple[str, ...]:
            factory = DatabaseSessionFactory(self.engine)
            with factory.transaction():
                result = PostgreSQLSourceRepository(factory).lock_selected_for_authority(order)
                entered.set()
                release.wait(timeout=10)
                return tuple(item.id for item in result)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(locked, tuple(reversed(ids)))
            self.assertTrue(entered.wait(timeout=10))
            second = pool.submit(locked, ids)
            try:
                self.assertFalse(second.done())
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10), tuple(sorted(ids)))
            self.assertEqual(second.result(timeout=10), tuple(sorted(ids)))

    def test_selected_source_lock_releases_after_commit_and_rollback(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from domain.sources.retrieval_status import RetrievalStatus
        from domain.sources.source import Source
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
        from infrastructure.persistence.postgresql.session import DatabaseSessionFactory

        project = ProjectFactory().create("Source lock release project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        now = datetime.now(timezone.utc).isoformat()
        source = Source(str(uuid4()), project.id, "https://example.com/release", "https://example.com/release", "Release", now, retrieval_status=RetrievalStatus.ACQUIRED, content_text="release", content_checksum="release-checksum")
        repository = PostgreSQLSourceRepository(self.session_factory)
        repository.create(source)
        factory = DatabaseSessionFactory(self.engine)
        with factory.transaction():
            repository_for_lock = PostgreSQLSourceRepository(factory)
            repository_for_lock.lock_selected_for_authority((source.id,))
        with factory.transaction():
            PostgreSQLSourceRepository(factory).lock_selected_for_authority((source.id,))
        with self.assertRaises(ValueError):
            with factory.transaction():
                PostgreSQLSourceRepository(factory).lock_selected_for_authority((source.id,))
                raise ValueError("rollback lock holder")
        with factory.transaction():
            PostgreSQLSourceRepository(factory).lock_selected_for_authority((source.id,))


if __name__ == "__main__":
    unittest.main()
