from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock

from application.execution.lease_config import LeaseConfig
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.services.durable_workflow_service import DurableWorkflowService
from application.services.project_service import ProjectService
from application.services.worker_execution_service import WorkerExecutionService
from application.services.workflow_service import WorkflowService
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
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
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.persistence.postgresql.database import create_database_engine
from runtime.workflow_context import WorkflowContext
from worker.identity import generate_worker_id


class _CrashTestExecutor:
    def __init__(self, gate_dir: Path) -> None:
        self.gate_dir = gate_dir
        self.executed: list[str] = []

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        assert task is not None
        run_id = context.workflow_run.id
        self.executed.append(task.definition_id)
        if task.definition_id == "task-b":
            self.gate_dir.mkdir(parents=True, exist_ok=True)
            (self.gate_dir / f"{run_id}.task-b.running").write_text("1", encoding="utf-8")
            release = self.gate_dir / f"{run_id}.release"
            deadline = time.time() + 120
            while not release.exists() and time.time() < deadline:
                time.sleep(0.05)
        context.write_shared(
            "task_results",
            {
                **dict(context.read_shared("task_results") or {}),
                task.definition_id: f"result-{task.definition_id}",
            },
        )
        return context


def _build_services(database_url: str, gate_dir: Path):
    engine = create_database_engine(database_url)
    session_factory = DatabaseSessionFactory(engine)
    executor = _CrashTestExecutor(gate_dir)
    resolver = Mock()
    resolver.resolve.return_value = executor
    workflow_engine = WorkflowEngine(
        scheduler=TaskScheduler(),
        task_executor=TaskExecutor(
            resolver=resolver,
            lifecycle=TaskLifecycleManager(),
        ),
        completion_policy=WorkflowCompletionPolicy(),
    )
    project_service = ProjectService(
        project_factory=ProjectFactory(),
        project_repository=PostgreSQLProjectRepository(session_factory),
    )
    workflow_service = WorkflowService(
        workflow_template_repository=PostgreSQLWorkflowTemplateRepository(session_factory),
        workflow_run_repository=PostgreSQLWorkflowRunRepository(session_factory),
        workflow_run_factory=WorkflowRunFactory(task_factory=TaskFactory()),
    )
    execution_port = PostgreSQLWorkflowRunExecutionRepository(session_factory)
    lease_config = LeaseConfig(
        lease_duration_seconds=float(os.environ.get("WORKER_LEASE_DURATION_SECONDS", "3")),
        heartbeat_interval_seconds=float(
            os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS", "1"),
        ),
        poll_interval_seconds=0.2,
    )
    durable_service = DurableWorkflowService(
        workflow_service=workflow_service,
        project_service=project_service,
        execution_log_store=PostgreSQLExecutionLogStore(session_factory),
        workflow_engine=workflow_engine,
        execution_port=execution_port,
        run_queue=NoOpRunQueue(),
        lease_config=lease_config,
    )
    worker_service = WorkerExecutionService(
        durable_workflow_service=durable_service,
        execution_port=execution_port,
        lease_config=lease_config,
    )
    return engine, executor, worker_service, durable_service, execution_port


def main() -> int:
    database_url = os.environ["DATABASE_URL"]
    gate_dir = Path(os.environ["WORKER_CRASH_TEST_GATE_DIR"])
    worker_id = os.environ.get("WORKER_ID") or generate_worker_id()
    mode = os.environ.get("WORKER_CRASH_TEST_MODE", "loop")
    engine, _executor, worker_service, _durable, _port = _build_services(
        database_url,
        gate_dir,
    )
    try:
        if mode == "once":
            worker_service.process_once(worker_id)
            return 0
        if mode == "drain":
            worker_service.drain_runnable_runs(worker_id, max_runs=10)
            return 0
        while True:
            if not worker_service.process_once(worker_id):
                time.sleep(worker_service._lease_config.poll_interval_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
