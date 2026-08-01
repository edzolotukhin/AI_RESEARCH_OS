from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from application.execution.lease_config import LeaseConfig
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.services.durable_workflow_service import DurableWorkflowService
from application.services.project_service import ProjectService
from application.services.workflow_service import WorkflowService
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder
from infrastructure.persistence.noop_run_queue import NoOpRunQueue
from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
    PostgreSQLExecutionLogStore,
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
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import (
    PostgreSQLWorkflowTemplateRepository,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


def _crash_template() -> WorkflowTemplate:
    return (
        WorkflowTemplateBuilder(id="crash-template", name="Crash")
        .add_task(
            id="task-a",
            name="Task A",
            executor_id="exec-a",
            executor_type=ExecutorType.AGENT,
        )
        .add_task(
            id="task-b",
            name="Task B",
            executor_id="exec-b",
            executor_type=ExecutorType.AGENT,
            depends_on=["task-a"],
        )
        .build()
    )


def _wait_until(predicate, *, timeout_seconds: float, interval: float = 0.1) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"Timed out after {timeout_seconds}s")


@unittest.skipUnless(
    integration_tests_enabled(),
    "Process crash recovery requires POSTGRESQL_INTEGRATION_TESTS=1.",
)
class ProcessCrashRecoveryIntegrationTests(PostgreSQLIntegrationTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.gate_dir = Path(tempfile.mkdtemp(prefix="worker-crash-gate-"))
        self.execution_repository = PostgreSQLWorkflowRunExecutionRepository(
            self.session_factory,
        )
        self.lease_seconds = 3.0

    def tearDown(self) -> None:
        for path in self.gate_dir.glob("*"):
            path.unlink(missing_ok=True)
        self.gate_dir.rmdir()
        super().tearDown()

    def _build_submit_service(self) -> DurableWorkflowService:
        resolver = Mock()
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(
                resolver=resolver,
                lifecycle=TaskLifecycleManager(),
            ),
            completion_policy=WorkflowCompletionPolicy(),
        )
        project_service = ProjectService(
            project_factory=ProjectFactory(),
            project_repository=PostgreSQLProjectRepository(self.session_factory),
        )
        workflow_service = WorkflowService(
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(
                self.session_factory,
            ),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(
                self.session_factory,
            ),
            workflow_run_factory=WorkflowRunFactory(task_factory=TaskFactory()),
        )
        return DurableWorkflowService(
            workflow_service=workflow_service,
            project_service=project_service,
            execution_log_store=PostgreSQLExecutionLogStore(self.session_factory),
            workflow_engine=engine,
            execution_port=self.execution_repository,
            run_queue=NoOpRunQueue(),
            lease_config=LeaseConfig(
                lease_duration_seconds=self.lease_seconds,
                heartbeat_interval_seconds=1.0,
                poll_interval_seconds=0.2,
            ),
        )

    def _worker_env(self, worker_id: str, mode: str = "loop") -> dict[str, str]:
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ["DATABASE_URL_TEST"]
        env["PERSISTENCE_BACKEND"] = "postgresql"
        env["WORKER_CRASH_TEST_GATE_DIR"] = str(self.gate_dir)
        env["WORKER_ID"] = worker_id
        env["WORKER_CRASH_TEST_MODE"] = mode
        env["WORKER_LEASE_DURATION_SECONDS"] = str(int(self.lease_seconds))
        env["WORKER_HEARTBEAT_INTERVAL_SECONDS"] = "1"
        return env

    def _start_worker(self, worker_id: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "tests.integration.worker.crash_harness"],
            env=self._worker_env(worker_id, mode="loop"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def test_worker_crash_lease_recovery_is_deterministic(self) -> None:
        service = self._build_submit_service()
        project = service._project_service.create_project("Crash Project")
        context = service.submit_research(
            project,
            _crash_template(),
            run_id="run-crash-recovery",
        )
        run_id = context.workflow_run.id

        worker_a = self._start_worker("worker-a-crash")
        try:
            _wait_until(
                lambda: (self.gate_dir / f"{run_id}.task-b.running").exists(),
                timeout_seconds=30.0,
            )
            lease = self.execution_repository.get_lease(run_id)
            self.assertIsNotNone(lease)
            assert lease is not None
            self.assertEqual(lease.claimed_by, "worker-a-crash")

            run_mid = service._workflow_service.get_workflow_run(run_id)
            self.assertEqual(run_mid.status, WorkflowStatus.RUNNING)
            task_b = next(task for task in run_mid.tasks if task.definition_id == "task-b")
            self.assertEqual(task_b.status, TaskStatus.RUNNING)
            task_a = next(task for task in run_mid.tasks if task.definition_id == "task-a")
            self.assertEqual(task_a.status, TaskStatus.COMPLETED)

            worker_a.kill()
            worker_a.wait(timeout=10)
            if worker_a.stderr is not None:
                worker_a.stderr.close()
            worker_a = None

            def _lease_owned_by_a() -> bool:
                lease = self.execution_repository.get_lease(run_id)
                if lease is None:
                    return False
                return (
                    lease.claimed_by == "worker-a-crash"
                    and lease.lease_expires_at >= datetime.now(timezone.utc)
                )

            _wait_until(_lease_owned_by_a, timeout_seconds=2.0)

            blocked = self.execution_repository.try_claim_run(
                run_id,
                worker_id="worker-b-early",
                lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
                now=datetime.now(timezone.utc),
            )
            self.assertIsNone(blocked)

            _wait_until(
                lambda: not _lease_owned_by_a(),
                timeout_seconds=self.lease_seconds + 3.0,
            )
        finally:
            if worker_a is not None:
                worker_a.kill()
                worker_a.wait(timeout=5)

        reclaim = subprocess.run(
            [sys.executable, "-m", "tests.integration.worker.crash_harness"],
            env=self._worker_env("worker-b-recover", mode="drain"),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            reclaim.returncode,
            0,
            msg=reclaim.stderr,
        )

        final = service._workflow_service.get_workflow_run(run_id)
        self.assertTrue(final.is_terminal)
        self.assertEqual(final.status, WorkflowStatus.FAILED)
        task_a = next(task for task in final.tasks if task.definition_id == "task-a")
        task_b = next(task for task in final.tasks if task.definition_id == "task-b")
        self.assertEqual(task_a.status, TaskStatus.COMPLETED)
        self.assertEqual(task_b.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
