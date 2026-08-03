"""PostgreSQL claim regression for external-worker runnable runs."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.research.brief_normalizer import normalize_research_brief_payload
from application.research.brief_validator import validate_research_brief
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
    PostgreSQLWorkflowRunExecutionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
    PostgreSQLWorkflowRunRepository,
)

from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
    postgresql_application_config,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL worker claim tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLWorkerClaimLiveShapeTests(PostgreSQLIntegrationTestCase):

    def _submit_created_desk_research_run(self, *, run_id: str):
        container = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
        )
        self.addCleanup(container.shutdown)
        project = container.project_service.create_project("Claim Live Shape Project")
        brief = normalize_research_brief_payload(BRIEF)
        validate_research_brief(brief)
        project.research_brief = brief
        context = container.agency.start_research(project, run_id=run_id)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.CREATED)
        return context.workflow_run.id, container

    def test_claim_next_runnable_claims_created_desk_research_run_once(self) -> None:
        run_id = "run-live-shape-claim"
        run_id, container = self._submit_created_desk_research_run(run_id=run_id)

        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        loaded = run_repository.get_by_id(run_id)
        assert loaded is not None
        tasks = {task.definition_id: task for task in loaded.tasks}
        self.assertEqual(loaded.status, WorkflowStatus.CREATED)
        self.assertEqual(container.workflow_service.get_workflow_run_version(run_id), 0)
        self.assertEqual(tasks["task-collect-evidence"].status.value, "created")
        self.assertEqual(list(tasks["task-collect-evidence"].depends_on), [])

        execution_repository = PostgreSQLWorkflowRunExecutionRepository(
            self.session_factory,
        )
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=30)
        first = execution_repository.claim_next_runnable(
            worker_id="worker-live-shape",
            lease_until=lease_until,
            now=now,
        )
        second = execution_repository.claim_next_runnable(
            worker_id="worker-other",
            lease_until=lease_until,
            now=now,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first.run_id, run_id)
        self.assertIsNone(second)

        lease = execution_repository.get_lease(run_id)
        assert lease is not None
        self.assertEqual(lease.claimed_by, "worker-live-shape")
        self.assertIsNotNone(lease.lease_expires_at)
        self.assertIsNotNone(lease.heartbeat_at)


if __name__ == "__main__":
    unittest.main()
