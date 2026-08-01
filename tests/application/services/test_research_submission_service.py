from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from application.persistence.exceptions import EntityNotFoundError
from application.persistence.records import (
    ResearchSubmissionRecord,
    ResearchSubmissionStatus,
)
from application.services.research_submission_service import (
    RECONCILE_POLL_INTERVAL_SECONDS,
    ResearchSubmissionService,
)
from domain.workflow_run import WorkflowRun
from infrastructure.persistence.memory.in_memory_research_submission_repository import (
    InMemoryResearchSubmissionRepository,
)


class ResearchSubmissionServiceReconciliationTests(unittest.TestCase):

    def setUp(self) -> None:
        self.repository = InMemoryResearchSubmissionRepository()
        self.service = ResearchSubmissionService(
            submission_repository=self.repository,
        )
        self.project_id = "project-1"
        self.idempotency_key = "key-peer"
        self.run_id = str(uuid4())
        self.record = ResearchSubmissionRecord(
            project_id=self.project_id,
            idempotency_key=self.idempotency_key,
            request_fingerprint="fp",
            run_id=self.run_id,
            correlation_id=None,
            source="n8n",
            created_at=datetime.now(timezone.utc),
            status=ResearchSubmissionStatus.PENDING,
        )
        self.repository._by_key[(self.project_id, self.idempotency_key)] = self.record
        self.repository._by_run_id[self.run_id] = self.record

    def test_wait_for_peer_completion_returns_run_when_peer_finishes(self) -> None:
        workflow_run = WorkflowRun(id=self.run_id, project_id=self.project_id)

        def _complete_peer() -> None:
            time.sleep(RECONCILE_POLL_INTERVAL_SECONDS * 2)
            self.repository.mark_completed(
                project_id=self.project_id,
                idempotency_key=self.idempotency_key,
            )

        thread = threading.Thread(target=_complete_peer)
        thread.start()
        resolved = self.service.wait_for_peer_completion(
            project_id=self.project_id,
            idempotency_key=self.idempotency_key,
            run_id=self.run_id,
            load_workflow_run=lambda run_id: workflow_run,
        )
        thread.join()
        self.assertIs(resolved, workflow_run)

    def test_wait_for_peer_completion_returns_none_when_no_progress(self) -> None:
        def _missing_run(_run_id: str) -> WorkflowRun:
            raise EntityNotFoundError("missing")

        resolved = self.service.wait_for_peer_completion(
            project_id=self.project_id,
            idempotency_key=self.idempotency_key,
            run_id=self.run_id,
            load_workflow_run=_missing_run,
        )
        self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
