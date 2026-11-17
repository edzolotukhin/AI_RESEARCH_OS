from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType

from application.evidence.exceptions import DuplicateEvidenceError
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_evidence(*, run_id: str, key: str) -> Evidence:
    return Evidence(
        id=str(uuid4()),
        project_id="project-concurrent",
        source_id="source-1",
        source_content_checksum="checksum-a",
        workflow_run_id=run_id,
        research_design_id="design-1",
        statement=f"Statement {key}",
        source_excerpt="Acquired market report body text.",
        evidence_type=EvidenceType.DIRECT_EXCERPT,
        deduplication_key=f"dedup-{key}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class InMemoryConcurrentEvidenceRepositoryTests(unittest.TestCase):
    def test_concurrent_create_resolves_single_evidence(self) -> None:
        repository = InMemoryEvidenceRepository()

        def attempt(key: str) -> str:
            evidence = _sample_evidence(run_id="run-a", key=key)
            try:
                repository.create(evidence)
                return evidence.id
            except DuplicateEvidenceError:
                existing = repository.get_by_deduplication_key("run-a", evidence.deduplication_key)
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "shared"),
                executor.submit(attempt, "shared"),
            ]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentEvidenceRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_row(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
            PostgreSQLSourceRepository,
        )
        from domain.sources.retrieval_status import RetrievalStatus
        from domain.sources.source import Source

        project = ProjectFactory().create("Concurrent Evidence Project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        source_repo = PostgreSQLSourceRepository(self.session_factory)
        now = datetime.now(timezone.utc).isoformat()
        source_repo.create(
            Source(
                id=str(uuid4()),
                project_id=project.id,
                url="https://example.com/report",
                canonical_url="https://example.com/report",
                title="Report",
                retrieved_at=now,
                retrieval_status=RetrievalStatus.ACQUIRED,
                content_text="Acquired market report body text.",
                content_checksum="checksum-a",
            ),
        )
        repository = PostgreSQLEvidenceRepository(self.session_factory)
        source_id = source_repo.list_for_project(project.id)[0].id

        def attempt() -> str:
            evidence = Evidence(
                id=str(uuid4()),
                project_id=project.id,
                source_id=source_id,
                source_content_checksum="checksum-a",
                workflow_run_id="run-a",
                research_design_id="design-1",
                statement="Concurrent statement",
                source_excerpt="Acquired market report body text.",
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key="shared-key",
                created_at=now,
            )
            try:
                repository.create(evidence)
                return evidence.id
            except DuplicateEvidenceError:
                existing = repository.get_by_deduplication_key("run-a", "shared-key")
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)

    def test_lock_selected_for_authority_blocks_concurrent_update(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from domain.sources.retrieval_status import RetrievalStatus
        from domain.sources.source import Source
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
            PostgreSQLSourceRepository,
        )
        from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
        from sqlalchemy import text

        project = ProjectFactory().create("Authority lock project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        now = datetime.now(timezone.utc).isoformat()
        source = Source(
            id=str(uuid4()),
            project_id=project.id,
            url="https://example.com/authority-lock",
            canonical_url="https://example.com/authority-lock",
            title="Authority lock source",
            retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="source body",
            content_checksum="checksum-lock",
        )
        source_repository = PostgreSQLSourceRepository(self.session_factory)
        source_repository.create(source)
        evidence = Evidence(
            id=str(uuid4()),
            project_id=project.id,
            source_id=source.id,
            source_content_checksum="checksum-lock",
            workflow_run_id="authority-lock-run",
            research_design_id="design-1",
            statement="locked evidence",
            source_excerpt="source body",
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            deduplication_key="authority-lock-evidence",
            created_at=now,
        )
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        evidence_repository.create(evidence)
        entered = Event()
        attempted = Event()
        completed = Event()
        release = Event()

        def holder() -> None:
            factory = DatabaseSessionFactory(self.engine)
            try:
                with factory.transaction():
                    PostgreSQLEvidenceRepository(factory).lock_selected_for_authority((evidence.id,))
                    entered.set()
                    release.wait(timeout=10)
            finally:
                release.set()

        def updater() -> None:
            attempted.set()
            with self.engine.begin() as connection:
                connection.execute(
                    text("UPDATE evidence SET statement=:statement WHERE id=:id"),
                    {"statement": "updated evidence", "id": evidence.id},
                )
            completed.set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(holder)
            self.assertTrue(entered.wait(timeout=10), "authority transaction did not acquire lock")
            second = executor.submit(updater)
            try:
                self.assertTrue(attempted.wait(timeout=10), "update transaction did not start")
                self.assertFalse(
                    completed.wait(timeout=0.5),
                    "UPDATE completed while authority lock was held",
                )
            finally:
                release.set()
            first.result(timeout=10)
            second.result(timeout=10)
        self.assertTrue(completed.is_set())

    def test_lock_selected_for_authority_blocks_concurrent_delete_until_release(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from domain.sources.retrieval_status import RetrievalStatus
        from domain.sources.source import Source
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
        from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
        from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
        from sqlalchemy import text

        project = ProjectFactory().create("Evidence delete lock project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        now = datetime.now(timezone.utc).isoformat()
        source = Source(str(uuid4()), project.id, "https://example.com/delete-lock", "https://example.com/delete-lock", "S", now, retrieval_status=RetrievalStatus.ACQUIRED, content_text="body", content_checksum="delete-checksum")
        PostgreSQLSourceRepository(self.session_factory).create(source)
        evidence = Evidence(str(uuid4()), project.id, source.id, "delete-checksum", "delete-run", "design-1", "statement", "body", now, evidence_type=EvidenceType.DIRECT_EXCERPT, deduplication_key="delete-lock")
        repository = PostgreSQLEvidenceRepository(self.session_factory)
        repository.create(evidence)
        entered, attempted, completed, release = Event(), Event(), Event(), Event()

        def holder() -> None:
            factory = DatabaseSessionFactory(self.engine)
            try:
                with factory.transaction():
                    PostgreSQLEvidenceRepository(factory).lock_selected_for_authority((evidence.id,))
                    entered.set()
                    release.wait(timeout=10)
            finally:
                release.set()

        def deleter() -> None:
            attempted.set()
            with self.engine.begin() as connection:
                connection.execute(text("DELETE FROM evidence WHERE id=:id"), {"id": evidence.id})
            completed.set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(holder)
            self.assertTrue(entered.wait(timeout=10))
            second = pool.submit(deleter)
            try:
                self.assertTrue(attempted.wait(timeout=10))
                self.assertFalse(completed.wait(timeout=0.5))
            finally:
                release.set()
            first.result(timeout=10)
            second.result(timeout=10)
        self.assertTrue(completed.is_set())


if __name__ == "__main__":
    unittest.main()
