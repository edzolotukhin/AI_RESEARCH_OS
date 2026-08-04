from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from application.execution.exceptions import ClaimConflictError
from application.execution.lease_config import LeaseConfig
from application.services.durable_workflow_service import DurableWorkflowService
from application.services.worker_execution_service import WorkerExecutionService
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
from infrastructure.persistence.noop_run_queue import NoOpRunQueue
from application.services.project_service import ProjectService


def _template(template_id: str = "template-worker") -> WorkflowTemplate:
    return WorkflowTemplate(
        id=template_id,
        name="Worker Template",
        task_definitions=[
            TaskDefinition(
                id="task-a",
                name="Task A",
                executor_id="planner",
                executor_type=ExecutorType.AGENT,
            ),
        ],
    )


class WorkerExecutionServiceTests(unittest.TestCase):

    def setUp(self) -> None:
        self.project_repository = InMemoryProjectRepository()
        self.workflow_run_repository = InMemoryWorkflowRunRepository()
        self.execution_repository = InMemoryWorkflowRunExecutionRepository(
            self.workflow_run_repository,
        )
        self.project_service = ProjectService(
            project_factory=ProjectFactory(),
            project_repository=self.project_repository,
        )
        self.workflow_service = WorkflowService(
            workflow_template_repository=InMemoryWorkflowTemplateRepository(),
            workflow_run_repository=self.workflow_run_repository,
            workflow_run_factory=WorkflowRunFactory(task_factory=TaskFactory()),
        )
        self.workflow_engine = Mock()
        self.workflow_engine.run.side_effect = lambda context, checkpoint=None: context
        self.durable_service = DurableWorkflowService(
            workflow_service=self.workflow_service,
            project_service=self.project_service,
            execution_log_store=InMemoryExecutionLogStore(),
            workflow_engine=self.workflow_engine,
            execution_port=self.execution_repository,
            run_queue=NoOpRunQueue(),
            lease_config=LeaseConfig(
                lease_duration_seconds=30,
                heartbeat_interval_seconds=0.05,
                poll_interval_seconds=0.01,
            ),
        )
        self.worker_service = WorkerExecutionService(
            durable_workflow_service=self.durable_service,
            execution_port=self.execution_repository,
            lease_config=self.durable_service._lease_config,
        )
        self.project = self.project_service.create_project("Worker Project")

    def test_claim_and_execute_invokes_engine_once(self) -> None:
        context = self.durable_service.submit_research(self.project, _template())
        self.worker_service.process_once("worker-a")
        self.workflow_engine.run.assert_called_once()
        self.assertEqual(
            self.workflow_engine.run.call_args.args[0].workflow_run.id,
            context.workflow_run.id,
        )

    def test_concurrent_claim_only_one_worker_wins(self) -> None:
        self.durable_service.submit_research(self.project, _template())
        first = self.execution_repository.claim_next_runnable(
            worker_id="worker-a",
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
            now=datetime.now(timezone.utc),
        )
        second = self.execution_repository.claim_next_runnable(
            worker_id="worker-b",
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
            now=datetime.now(timezone.utc),
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_release_lease_wrong_owner_raises(self) -> None:
        self.durable_service.submit_research(self.project, _template())
        claim = self.execution_repository.claim_next_runnable(
            worker_id="worker-a",
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
            now=datetime.now(timezone.utc),
        )
        assert claim is not None
        with self.assertRaises(ClaimConflictError):
            self.execution_repository.release_lease(
                claim.run_id,
                worker_id="worker-b",
            )

    def test_execution_failure_does_not_block_next_runnable_claim(self) -> None:
        from application.analysis.exceptions import AnalysisError

        self.durable_service.submit_research(
            self.project,
            _template("template-worker-fail"),
            run_id="run-fail",
        )
        self.durable_service.submit_research(
            self.project,
            _template("template-worker-success"),
            run_id="run-success",
        )
        self.workflow_engine.run.side_effect = [
            AnalysisError(
                "No valid findings produced for workflow run run-fail",
            ),
            lambda context, checkpoint=None: context,
        ]

        self.assertTrue(self.worker_service.process_once("worker-a"))
        self.assertTrue(self.worker_service.process_once("worker-a"))
        self.assertEqual(self.workflow_engine.run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
