from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
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


def _seed_project(session_factory, project_id: str = "project-worker") -> None:
    project = ProjectFactory().create("Worker Contract Project")
    project.id = project_id
    PostgreSQLProjectRepository(session_factory).create(project)


def _seed_run(session_factory, *, project_id: str, run_id: str) -> None:
    template = WorkflowTemplate(
        id="template-worker-pg",
        name="Worker",
        task_definitions=[
            TaskDefinition(
                id="task-a",
                name="Task A",
                executor_id="planner",
                executor_type=ExecutorType.AGENT,
            ),
        ],
    )
    workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template,
        run_id=run_id,
        project_id=project_id,
    )
    PostgreSQLWorkflowRunRepository(session_factory).create(
        workflow_run,
        project_id=project_id,
    )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLWorkflowRunExecutionIntegrationTests(PostgreSQLIntegrationTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.execution_repository = PostgreSQLWorkflowRunExecutionRepository(
            self.session_factory,
        )

    def test_concurrent_claim_exactly_one_winner(self) -> None:
        _seed_project(self.session_factory)
        _seed_run(
            self.session_factory,
            project_id="project-worker",
            run_id="run-concurrent",
        )
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=30)
        first = self.execution_repository.claim_next_runnable(
            worker_id="worker-a",
            lease_until=lease_until,
            now=now,
        )
        second = self.execution_repository.claim_next_runnable(
            worker_id="worker-b",
            lease_until=lease_until,
            now=now,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_stale_lease_can_be_reclaimed(self) -> None:
        _seed_project(self.session_factory)
        _seed_run(
            self.session_factory,
            project_id="project-worker",
            run_id="run-stale",
        )
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        expired = past + timedelta(seconds=5)
        claim = self.execution_repository.try_claim_run(
            "run-stale",
            worker_id="worker-a",
            lease_until=expired,
            now=past,
        )
        self.assertIsNotNone(claim)
        reclaimed = self.execution_repository.try_claim_run(
            "run-stale",
            worker_id="worker-b",
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
            now=datetime.now(timezone.utc),
        )
        self.assertIsNotNone(reclaimed)


if __name__ == "__main__":
    unittest.main()
