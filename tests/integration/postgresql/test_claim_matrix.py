from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
    PostgreSQLWorkflowRunExecutionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
    PostgreSQLWorkflowRunRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _seed_project(session_factory, project_id: str = "project-claim") -> None:
    project = ProjectFactory().create("Claim Project")
    project.id = project_id
    PostgreSQLProjectRepository(session_factory).create(project)


def _seed_created_run(
    session_factory,
    *,
    run_id: str,
    project_id: str = "project-claim",
) -> None:
    template = WorkflowTemplate(
        id=f"template-{run_id}",
        name="Claim",
        task_definitions=[
            TaskDefinition(
                id="task-a",
                name="Task A",
                executor_id="planner",
                executor_type=ExecutorType.AGENT,
            ),
        ],
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template,
        run_id=run_id,
        project_id=project_id,
    )
    PostgreSQLWorkflowRunRepository(session_factory).create(
        run,
        project_id=project_id,
    )


def _seed_running_run(session_factory, *, run_id: str) -> None:
    _seed_created_run(session_factory, run_id=run_id)
    repository = PostgreSQLWorkflowRunRepository(session_factory)
    loaded = repository.get_by_id(run_id)
    assert loaded is not None
    loaded.ready()
    loaded.start()
    repository.save(loaded, expected_version=0)


def _seed_completed_run(session_factory, *, run_id: str) -> None:
    _seed_created_run(session_factory, run_id=run_id)
    repository = PostgreSQLWorkflowRunRepository(session_factory)
    loaded = repository.get_by_id(run_id)
    assert loaded is not None
    loaded.ready()
    loaded.start()
    for task in loaded.tasks:
        task.ready()
        task.start()
        task.complete()
    loaded.complete()
    repository.save(loaded, expected_version=0)


def _seed_paused_run(session_factory, *, run_id: str) -> None:
    _seed_running_run(session_factory, run_id=run_id)
    repository = PostgreSQLWorkflowRunRepository(session_factory)
    loaded = repository.get_by_id(run_id)
    assert loaded is not None
    loaded.pause()
    repository.save(loaded, expected_version=1)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL claim matrix tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLClaimMatrixIntegrationTests(PostgreSQLIntegrationTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.execution_repository = PostgreSQLWorkflowRunExecutionRepository(
            self.session_factory,
        )
        _seed_project(self.session_factory)
        self.now = datetime.now(timezone.utc)
        self.lease_until = self.now + timedelta(seconds=30)

    def test_created_run_is_claimable(self) -> None:
        _seed_created_run(self.session_factory, run_id="run-created")
        claim = self.execution_repository.try_claim_run(
            "run-created",
            worker_id="worker-a",
            lease_until=self.lease_until,
            now=self.now,
        )
        self.assertIsNotNone(claim)

    def test_terminal_run_is_not_claimable(self) -> None:
        _seed_completed_run(self.session_factory, run_id="run-completed")
        claim = self.execution_repository.try_claim_run(
            "run-completed",
            worker_id="worker-a",
            lease_until=self.lease_until,
            now=self.now,
        )
        self.assertIsNone(claim)

    def test_paused_run_is_not_claimable(self) -> None:
        _seed_paused_run(self.session_factory, run_id="run-paused")
        claim = self.execution_repository.try_claim_run(
            "run-paused",
            worker_id="worker-a",
            lease_until=self.lease_until,
            now=self.now,
        )
        self.assertIsNone(claim)

    def test_active_lease_blocks_other_worker(self) -> None:
        _seed_created_run(self.session_factory, run_id="run-active-lease")
        first = self.execution_repository.try_claim_run(
            "run-active-lease",
            worker_id="worker-a",
            lease_until=self.lease_until,
            now=self.now,
        )
        self.assertIsNotNone(first)
        second = self.execution_repository.try_claim_run(
            "run-active-lease",
            worker_id="worker-b",
            lease_until=self.lease_until,
            now=self.now,
        )
        self.assertIsNone(second)

    def test_expired_running_lease_is_reclaimable(self) -> None:
        _seed_running_run(self.session_factory, run_id="run-running-reclaim")
        past = self.now - timedelta(seconds=60)
        expired = past + timedelta(seconds=5)
        self.execution_repository.try_claim_run(
            "run-running-reclaim",
            worker_id="worker-a",
            lease_until=expired,
            now=past,
        )
        reclaimed = self.execution_repository.try_claim_run(
            "run-running-reclaim",
            worker_id="worker-b",
            lease_until=self.lease_until,
            now=self.now,
        )
        self.assertIsNotNone(reclaimed)
        lease = self.execution_repository.get_lease("run-running-reclaim")
        assert lease is not None
        self.assertEqual(lease.claimed_by, "worker-b")


if __name__ == "__main__":
    unittest.main()
