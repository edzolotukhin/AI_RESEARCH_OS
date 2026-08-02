from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.findings.insight import Insight

from application.analysis.exceptions import DuplicateInsightError
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
    PostgreSQLInsightRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_insight(*, run_id: str, key: str, project_id: str = "project-concurrent") -> Insight:
    return Insight(
        id=str(uuid4()),
        project_id=project_id,
        workflow_run_id=run_id,
        research_design_id="design-1",
        statement=f"Insight statement {key}",
        implication="Implication",
        finding_refs=("finding-1",),
        deduplication_key=f"dedup-{key}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class InMemoryConcurrentInsightRepositoryTests(unittest.TestCase):
    def test_concurrent_create_resolves_single_insight(self) -> None:
        repository = InMemoryInsightRepository()

        def attempt(key: str) -> str:
            insight = _sample_insight(run_id="run-a", key=key)
            try:
                repository.create(insight)
                return insight.id
            except DuplicateInsightError:
                existing = repository.get_by_deduplication_key("run-a", insight.deduplication_key)
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
        self.assertEqual(stored.finding_refs, ("finding-1",))


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentInsightRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_row(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        project = ProjectFactory().create("Concurrent Insight Project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        repository = PostgreSQLInsightRepository(self.session_factory)

        def attempt() -> str:
            insight = Insight(
                id=str(uuid4()),
                project_id=project.id,
                workflow_run_id="run-a",
                research_design_id="design-1",
                statement="Concurrent insight statement",
                implication="Concurrent implication",
                finding_refs=("finding-1",),
                deduplication_key="shared-key",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            try:
                repository.create(insight)
                return insight.id
            except DuplicateInsightError:
                existing = repository.get_by_deduplication_key("run-a", "shared-key")
                assert existing is not None
                return existing.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt), executor.submit(attempt)]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_id(ids[0])
        assert stored is not None
        self.assertEqual(stored.finding_refs, ("finding-1",))


if __name__ == "__main__":
    unittest.main()
