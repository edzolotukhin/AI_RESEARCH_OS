from __future__ import annotations

import unittest
from unittest.mock import Mock

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
from runtime.workflow_context import WorkflowContext

from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


class _DeterministicExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        assert task is not None
        self.executed.append(task.definition_id)
        context.write_shared(
            "task_results",
            {
                **dict(context.read_shared("task_results") or {}),
                task.definition_id: f"result-{task.definition_id}",
            },
        )
        return context


def _template(template_id: str = "pg-durable-template") -> WorkflowTemplate:
    return (
        WorkflowTemplateBuilder(id=template_id, name="PG Durable")
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


class PostgreSQLDurableWorkflowRuntimeTests(PostgreSQLIntegrationTestCase):

    def _build_service(self, executor: _DeterministicExecutor) -> DurableWorkflowService:
        from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
            PostgreSQLExecutionLogStore,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import (
            PostgreSQLWorkflowTemplateRepository,
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
        resolver = Mock()
        resolver.resolve.return_value = executor
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(
                resolver=resolver,
                lifecycle=TaskLifecycleManager(),
            ),
            completion_policy=WorkflowCompletionPolicy(),
        )
        return DurableWorkflowService(
            workflow_service=workflow_service,
            project_service=project_service,
            execution_log_store=PostgreSQLExecutionLogStore(self.session_factory),
            workflow_engine=engine,
        )

    def test_successful_durable_workflow_round_trip(self) -> None:
        executor = _DeterministicExecutor()
        service = self._build_service(executor)
        project = service._project_service.create_project("PG Durable Project")

        context = service.start_research(
            project,
            _template(),
            run_id="pg-run-success",
        )

        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        reloaded = service._workflow_service.get_workflow_run("pg-run-success")
        self.assertEqual(reloaded.status, WorkflowStatus.COMPLETED)
        results = service._workflow_service.get_task_results("pg-run-success")
        self.assertEqual(set(results), {"task-a", "task-b", "_run_usage_summary", "_quantitative_semantic_call_ledger"})
        self.assertIn("_run_usage_summary", results)
        usage = results["_run_usage_summary"]
        self.assertIsInstance(usage, dict)
        self.assertIn("total_llm_calls", usage)
        self.assertGreater(
            service._workflow_service.get_workflow_run_version("pg-run-success"),
            0,
        )

    def test_resume_after_partial_persistence(self) -> None:
        executor = _DeterministicExecutor()
        service = self._build_service(executor)
        project = service._project_service.create_project("PG Resume Project")
        template = _template("pg-template-resume")

        workflow_run = service._workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="pg-run-resume",
        )
        service._workflow_service.publish_template_snapshot(
            template,
            project_id=project.id,
        )

        first_task = workflow_run.tasks[0]
        first_task.ready()
        first_task.start()
        first_task.complete()
        workflow_run.ready()
        workflow_run.start()
        service._workflow_service.save_workflow_run(
            workflow_run,
            expected_version=0,
            task_results={
                first_task.id: {
                    "task_id": first_task.id,
                    "definition_id": "task-a",
                    "shared_state": {
                        "task_results": {"task-a": "result-task-a"},
                    },
                }
            },
        )

        executor.executed.clear()
        resumed = service.resume_research("pg-run-resume")

        self.assertEqual(resumed.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(executor.executed, ["task-b"])

    def test_terminal_resume_is_idempotent(self) -> None:
        executor = _DeterministicExecutor()
        service = self._build_service(executor)
        project = service._project_service.create_project("PG Terminal Project")
        template = _template("pg-template-terminal")

        workflow_run = service._workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="pg-run-terminal",
        )
        service._workflow_service.publish_template_snapshot(
            template,
            project_id=project.id,
        )
        workflow_run.ready()
        workflow_run.start()
        workflow_run.complete()
        service._workflow_service.save_workflow_run(
            workflow_run,
            expected_version=0,
        )

        executor.executed.clear()
        context = service.resume_research("pg-run-terminal")

        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(executor.executed, [])

    def test_execution_logs_are_ordered_and_idempotent(self) -> None:
        executor = _DeterministicExecutor()
        service = self._build_service(executor)
        project = service._project_service.create_project("PG Log Project")

        service.start_research(
            project,
            _template("pg-template-log"),
            run_id="pg-run-log",
        )

        logs = service._audit._execution_log_store.list_for_run("pg-run-log")
        event_ids = [entry.event_id for entry in logs]
        self.assertEqual(len(event_ids), len(set(event_ids)))
        self.assertGreaterEqual(len(logs), 4)
        self.assertEqual(logs[0].event_type, "workflow_created")


if __name__ == "__main__":
    unittest.main()
