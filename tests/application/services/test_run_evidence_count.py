from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType

from application.services.evidence_service import EvidenceService
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)


class RunEvidenceCountTests(unittest.TestCase):
    def test_evidence_count_is_run_specific(self) -> None:
        repository = InMemoryEvidenceRepository()
        service = EvidenceService(evidence_repository=repository)
        now = datetime.now(timezone.utc).isoformat()

        def _record(*, run_id: str, need_id: str) -> None:
            evidence = Evidence(
                id=str(uuid4()),
                project_id="project-1",
                source_id="source-1",
                source_content_checksum="checksum",
                workflow_run_id=run_id,
                research_design_id="design-1",
                information_need_refs=(need_id,),
                statement=f"Statement for {need_id}",
                source_excerpt="Acquired market report body text.",
                deduplication_key=f"key-{run_id}-{need_id}",
                created_at=now,
            )
            repository.create(evidence)

        _record(run_id="run-1", need_id="in-1")
        _record(run_id="run-1", need_id="in-2")
        _record(run_id="run-2", need_id="in-1")

        self.assertEqual(service.count_for_run("project-1", "run-1"), 2)
        self.assertEqual(service.count_for_run("project-1", "run-2"), 1)
        self.assertEqual(service.count_for_run("project-1", "run-3"), 0)


if __name__ == "__main__":
    unittest.main()
