from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.services.source_service import SourceService
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)


class RunSourceCountTests(unittest.TestCase):
    def test_source_count_is_run_specific(self) -> None:
        repository = InMemorySourceRepository()
        service = SourceService(source_repository=repository)
        project_id = "project-1"
        now = datetime.now(timezone.utc).isoformat()

        source_a = Source(
            id=str(uuid4()),
            project_id=project_id,
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="A",
            retrieved_at=now,
            workflow_run_refs=("run-1",),
            research_design_refs=("design-1",),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="A",
        )
        source_b = Source(
            id=str(uuid4()),
            project_id=project_id,
            url="https://example.com/b",
            canonical_url="https://example.com/b",
            title="B",
            retrieved_at=now,
            workflow_run_refs=("run-1",),
            research_design_refs=("design-1",),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="B",
        )
        shared = Source(
            id=str(uuid4()),
            project_id=project_id,
            url="https://example.com/shared",
            canonical_url="https://example.com/shared",
            title="Shared",
            retrieved_at=now,
            workflow_run_refs=("run-1", "run-2"),
            research_design_refs=("design-1", "design-2"),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="shared",
        )
        repository.create(source_a)
        repository.create(source_b)
        repository.create(shared)

        self.assertEqual(service.count_acquired_for_run(project_id, "run-1"), 3)
        self.assertEqual(service.count_acquired_for_run(project_id, "run-2"), 1)
        self.assertEqual(service.count_acquired_for_run(project_id, "run-3"), 0)


if __name__ == "__main__":
    unittest.main()
