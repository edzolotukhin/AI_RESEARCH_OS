from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
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


if __name__ == "__main__":
    unittest.main()
