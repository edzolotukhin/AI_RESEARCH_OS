from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType

from application.analysis.exceptions import DuplicateFindingError
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
    PostgreSQLFindingRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_finding(*, run_id: str, key: str, project_id: str = "project-concurrent") -> Finding:
    return Finding(
        id=str(uuid4()),
        project_id=project_id,
        workflow_run_id=run_id,
        research_design_id="design-1",
        statement=f"Finding statement {key}",
        rationale="Rationale",
        evidence_refs=("evidence-1",),
        finding_type=FindingType.SYNTHESIS,
        analysis_method="deterministic",
        deduplication_key=f"dedup-{key}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class InMemoryConcurrentFindingRepositoryTests(unittest.TestCase):
    def test_concurrent_create_resolves_single_finding(self) -> None:
        repository = InMemoryFindingRepository()

        def attempt(key: str) -> str:
            finding = _sample_finding(run_id="run-a", key=key)
            try:
                repository.create(finding)
                return finding.id
            except DuplicateFindingError:
                existing = repository.get_by_deduplication_key("run-a", finding.deduplication_key)
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "shared"),
                executor.submit(attempt, "shared"),
            ]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_id(ids[0])
        assert stored is not None
        self.assertEqual(stored.evidence_refs, ("evidence-1",))


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentFindingRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_row(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        project = ProjectFactory().create("Concurrent Finding Project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        repository = PostgreSQLFindingRepository(self.session_factory)

        def attempt() -> str:
            finding = Finding(
                id=str(uuid4()),
                project_id=project.id,
                workflow_run_id="run-a",
                research_design_id="design-1",
                statement="Concurrent finding statement",
                rationale="Concurrent rationale",
                evidence_refs=("evidence-1",),
                finding_type=FindingType.SYNTHESIS,
                analysis_method="deterministic",
                deduplication_key="shared-key",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            try:
                repository.create(finding)
                return finding.id
            except DuplicateFindingError:
                existing = repository.get_by_deduplication_key("run-a", "shared-key")
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_id(ids[0])
        assert stored is not None
        self.assertEqual(stored.evidence_refs, ("evidence-1",))


if __name__ == "__main__":
    unittest.main()
