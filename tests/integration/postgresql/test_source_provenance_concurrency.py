from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.sources.exceptions import DuplicateSourceError
from application.sources.provenance_merge import ProvenanceDelta, apply_provenance_delta
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _sample_source(*, project_id: str, run_id: str, canonical: str, content: str) -> Source:
    return Source(
        id=str(uuid4()),
        project_id=project_id,
        url=canonical,
        canonical_url=canonical,
        title="Title",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=content,
        workflow_run_refs=(run_id,),
        research_design_refs=("design-1",),
        query_refs=("sq-1",),
    )


class InMemoryConcurrentSourceRepositoryTests(unittest.TestCase):
    def test_concurrent_create_resolves_single_source(self) -> None:
        repository = InMemorySourceRepository()
        project_id = "project-concurrent"
        canonical = "https://example.com/shared"
        def attempt(run_id: str) -> str:
            source = _sample_source(
                project_id=project_id,
                run_id=run_id,
                canonical=canonical,
                content="shared-content",
            )
            try:
                repository.create(source)
                return source.id
            except DuplicateSourceError:
                existing = repository.get_by_canonical_url_for_project(
                    project_id,
                    canonical,
                )
                assert existing is not None
                merged = apply_provenance_delta(
                    existing,
                    ProvenanceDelta(
                        workflow_run_id=run_id,
                        research_design_id="design-1",
                        query_refs=(f"sq-{run_id}",),
                        research_question_refs=("rq-1",),
                        information_need_refs=("in-1",),
                        discovery_records=(),
                    ),
                )
                repository.save(merged, expected_version=merged.version)
                return merged.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "run-a"),
                executor.submit(attempt, "run-b"),
            ]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_canonical_url_for_project(project_id, canonical)
        assert stored is not None
        self.assertEqual(stored.content_text, "shared-content")
        self.assertEqual(set(stored.workflow_run_refs), {"run-a", "run-b"})


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLConcurrentSourceRepositoryTests(PostgreSQLIntegrationTestCase):
    def test_concurrent_create_resolves_single_row(self) -> None:
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        project = ProjectFactory().create("Concurrent Source Project")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        repository = PostgreSQLSourceRepository(self.session_factory)
        canonical = "https://example.com/concurrent-shared"

        def attempt(run_id: str) -> str:
            source = _sample_source(
                project_id=project.id,
                run_id=run_id,
                canonical=canonical,
                content="pg-shared-content",
            )
            try:
                repository.create(source)
                return source.id
            except DuplicateSourceError:
                existing = repository.get_by_canonical_url_for_project(
                    project.id,
                    canonical,
                )
                assert existing is not None
                merged = apply_provenance_delta(
                    existing,
                    ProvenanceDelta(
                        workflow_run_id=run_id,
                        research_design_id="design-1",
                        query_refs=(f"sq-{run_id}",),
                        research_question_refs=("rq-1",),
                        information_need_refs=("in-1",),
                        discovery_records=(),
                    ),
                )
                repository.save(merged, expected_version=merged.version)
                return merged.id

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "run-a"),
                executor.submit(attempt, "run-b"),
            ]
            ids = [future.result() for future in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(set(ids)), 1)
        stored = repository.get_by_canonical_url_for_project(project.id, canonical)
        assert stored is not None
        self.assertEqual(stored.content_text, "pg-shared-content")
        self.assertEqual(set(stored.workflow_run_refs), {"run-a", "run-b"})


if __name__ == "__main__":
    unittest.main()
