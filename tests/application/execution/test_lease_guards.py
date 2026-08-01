from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from application.execution.exceptions import ClaimConflictError, LeaseLostError
from application.execution.heartbeat import LeaseGuard
from application.runtime.workflow_execution_audit import WorkflowExecutionAudit
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.services.workflow_service import WorkflowService
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.memory.in_memory_execution_log_store import (
    InMemoryExecutionLogStore,
)
from infrastructure.persistence.memory.in_memory_project_repository import (
    InMemoryProjectRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_execution_repository import (
    InMemoryWorkflowRunExecutionRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_template_repository import (
    InMemoryWorkflowTemplateRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
    PostgreSQLWorkflowRunExecutionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
    PostgreSQLWorkflowRunRepository,
)
from runtime.workflow_context import WorkflowContext
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


class LeaseGuardTests(unittest.TestCase):

    def test_checkpoint_raises_after_lease_marked_lost(self) -> None:
        workflow_run_repository = InMemoryWorkflowRunRepository()
        workflow_service = WorkflowService(
            workflow_template_repository=InMemoryWorkflowTemplateRepository(),
            workflow_run_repository=workflow_run_repository,
            workflow_run_factory=WorkflowRunFactory(task_factory=TaskFactory()),
        )
        template = WorkflowTemplate(
            id="template-lease-guard",
            name="Lease",
            task_definitions=[
                TaskDefinition(
                    id="task-a",
                    name="Task A",
                    executor_id="planner",
                    executor_type=ExecutorType.AGENT,
                ),
            ],
        )
        project = ProjectFactory().create("Lease Project")
        InMemoryProjectRepository().create(project)
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template,
            run_id="run-lease-guard",
            project_id=project.id,
        )
        workflow_run_repository.create(run, project_id=project.id)

        lease_guard = LeaseGuard()
        lease_guard.mark_lost()
        persister = WorkflowRuntimePersister(
            workflow_service=workflow_service,
            audit=WorkflowExecutionAudit(InMemoryExecutionLogStore()),
            run_id="run-lease-guard",
            initial_version=0,
            lease_guard=lease_guard,
        )
        context = WorkflowContext(
            project=project,
            workflow_template=template,
            workflow_run=run,
        )
        with self.assertRaises(LeaseLostError):
            persister.on_workflow_started(context)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL lease ownership tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLLeaseOwnershipIntegrationTests(PostgreSQLIntegrationTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.execution_repository = PostgreSQLWorkflowRunExecutionRepository(
            self.session_factory,
        )

    def _seed_run(self, run_id: str = "run-owner-release") -> None:
        project = ProjectFactory().create("Owner Project")
        project.id = "project-owner"
        PostgreSQLProjectRepository(self.session_factory).create(project)
        template = WorkflowTemplate(
            id="template-owner",
            name="Owner",
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
            project_id=project.id,
        )
        PostgreSQLWorkflowRunRepository(self.session_factory).create(
            run,
            project_id=project.id,
        )

    def test_stale_owner_cannot_release_or_renew_reclaimed_lease(self) -> None:
        self._seed_run()
        past = datetime.now(timezone.utc) - timedelta(seconds=30)
        expired = past + timedelta(seconds=2)
        claim_a = self.execution_repository.try_claim_run(
            "run-owner-release",
            worker_id="worker-a",
            lease_until=expired,
            now=past,
        )
        self.assertIsNotNone(claim_a)
        claim_b = self.execution_repository.try_claim_run(
            "run-owner-release",
            worker_id="worker-b",
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
            now=datetime.now(timezone.utc),
        )
        self.assertIsNotNone(claim_b)
        with self.assertRaises(ClaimConflictError):
            self.execution_repository.release_lease(
                "run-owner-release",
                worker_id="worker-a",
            )
        with self.assertRaises(ClaimConflictError):
            self.execution_repository.renew_lease(
                "run-owner-release",
                worker_id="worker-a",
                lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
                now=datetime.now(timezone.utc),
            )
        lease = self.execution_repository.get_lease("run-owner-release")
        assert lease is not None
        self.assertEqual(lease.claimed_by, "worker-b")


if __name__ == "__main__":
    unittest.main()
