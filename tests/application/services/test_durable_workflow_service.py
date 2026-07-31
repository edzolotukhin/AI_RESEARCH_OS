from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.persistence.exceptions import (
    CheckpointPersistenceError,
    ConcurrentModificationError,
)
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
from domain.project import Project
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder
from infrastructure.persistence.memory.in_memory_execution_log_store import (
    InMemoryExecutionLogStore,
)
from infrastructure.persistence.memory.in_memory_project_repository import (
    InMemoryProjectRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_template_repository import (
    InMemoryWorkflowTemplateRepository,
)
from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class RecordingExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        assert task is not None
        self.executed.append(task.definition_id)
        context.write_shared("task_results", {
            **dict(context.read_shared("task_results") or {}),
            task.definition_id: f"result-{task.definition_id}",
        })
        return context


class SelectiveExecutor:
    def __init__(
        self,
        *,
        fail_ids: set[str] | None = None,
    ) -> None:
        self.fail_ids = fail_ids or set()
        self.executed: list[str] = []

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        assert task is not None
        self.executed.append(task.definition_id)
        if task.definition_id in self.fail_ids:
            raise RuntimeError(f"{task.definition_id} failed")
        context.write_shared("task_results", {
            **dict(context.read_shared("task_results") or {}),
            task.definition_id: f"result-{task.definition_id}",
        })
        return context


def _linear_template(template_id: str = "template-durable") -> WorkflowTemplate:
    return (
        WorkflowTemplateBuilder(id=template_id, name="Durable")
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


def _build_durable_service(
    executor,
) -> tuple[DurableWorkflowService, RecordingExecutor | SelectiveExecutor, WorkflowService]:
    template_repository = InMemoryWorkflowTemplateRepository()
    run_repository = InMemoryWorkflowRunRepository()
    log_store = InMemoryExecutionLogStore()
    project_repository = InMemoryProjectRepository()
    project_factory = ProjectFactory()
    project_service = ProjectService(
        project_factory=project_factory,
        project_repository=project_repository,
    )
    workflow_service = WorkflowService(
        workflow_template_repository=template_repository,
        workflow_run_repository=run_repository,
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

    durable_service = DurableWorkflowService(
        workflow_service=workflow_service,
        project_service=project_service,
        execution_log_store=log_store,
        workflow_engine=engine,
    )
    return durable_service, executor, workflow_service


class DurableWorkflowServiceTests(unittest.TestCase):

    def test_new_workflow_persists_template_run_and_terminal_state(self) -> None:
        recording = RecordingExecutor()
        durable_service, _, workflow_service = _build_durable_service(recording)
        project = durable_service._project_service.create_project("Project")

        context = durable_service.start_research(
            project,
            _linear_template(),
            run_id="run-durable-1",
        )

        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(recording.executed, ["task-a", "task-b"])
        self.assertIsNotNone(
            workflow_service.get_template("template-durable"),
        )
        loaded = workflow_service.get_workflow_run("run-durable-1")
        self.assertEqual(loaded.status, WorkflowStatus.COMPLETED)
        self.assertGreater(workflow_service.get_workflow_run_version("run-durable-1"), 0)
        results = workflow_service.get_task_results("run-durable-1")
        self.assertIn(loaded.tasks[0].id, results)

    def test_executor_failure_persists_failed_state_and_reraises(self) -> None:
        selective = SelectiveExecutor(fail_ids={"task-a"})
        durable_service, _, workflow_service = _build_durable_service(selective)
        project = durable_service._project_service.create_project("Project")

        with self.assertRaises(RuntimeError):
            durable_service.start_research(
                project,
                _linear_template("template-fail"),
                run_id="run-fail",
            )

        loaded = workflow_service.get_workflow_run("run-fail")
        self.assertEqual(loaded.status, WorkflowStatus.FAILED)
        self.assertEqual(loaded.tasks[0].status, TaskStatus.FAILED)
        self.assertEqual(loaded.tasks[1].status, TaskStatus.SKIPPED)

    def test_independent_failure_and_success_both_persist(self) -> None:
        template = (
            WorkflowTemplateBuilder(id="template-branch", name="Branch")
            .add_task(
                id="root",
                name="Root",
                executor_id="exec-root",
                executor_type=ExecutorType.AGENT,
            )
            .add_task(
                id="fail-branch",
                name="Fail",
                executor_id="exec-fail",
                executor_type=ExecutorType.AGENT,
                depends_on=["root"],
            )
            .add_task(
                id="ok-branch",
                name="Ok",
                executor_id="exec-ok",
                executor_type=ExecutorType.AGENT,
                depends_on=["root"],
            )
            .build()
        )

        class BranchExecutor:
            def __init__(self) -> None:
                self.executed: list[str] = []

            def run(self, context: WorkflowContext) -> WorkflowContext:
                task = context.current_task
                assert task is not None
                self.executed.append(task.definition_id)
                if task.definition_id == "fail-branch":
                    raise RuntimeError("branch failed")
                context.write_shared("task_results", {"ok": True})
                return context

        branch_executor = BranchExecutor()
        durable_service, _, workflow_service = _build_durable_service(branch_executor)
        project = durable_service._project_service.create_project("Project")

        with self.assertRaises(RuntimeError):
            durable_service.start_research(
                project,
                template,
                run_id="run-branch",
            )

        loaded = workflow_service.get_workflow_run("run-branch")
        statuses = {task.definition_id: task.status for task in loaded.tasks}
        self.assertEqual(statuses["root"], TaskStatus.COMPLETED)
        self.assertEqual(statuses["fail-branch"], TaskStatus.FAILED)
        self.assertEqual(statuses["ok-branch"], TaskStatus.COMPLETED)
        self.assertEqual(loaded.status, WorkflowStatus.FAILED)

    def test_resume_skips_completed_tasks_and_restores_results(self) -> None:
        recording = RecordingExecutor()
        durable_service, _, workflow_service = _build_durable_service(recording)
        project = durable_service._project_service.create_project("Project")

        template = _linear_template("template-resume")
        workflow_run = workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="run-resume",
        )
        workflow_service.publish_template_snapshot(template, project_id=project.id)

        first_task = workflow_run.tasks[0]
        first_task.ready()
        first_task.start()
        first_task.complete()
        workflow_run.ready()
        workflow_run.start()
        task_results = {
            first_task.id: {
                "task_id": first_task.id,
                "definition_id": "task-a",
                "shared_state": {"task_results": {"task-a": "result-task-a"}},
            }
        }
        workflow_service.save_workflow_run(
            workflow_run,
            expected_version=0,
            task_results=task_results,
        )

        recording.executed.clear()
        context = durable_service.resume_research("run-resume")

        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(recording.executed, ["task-b"])
        self.assertEqual(
            context.read_shared("task_results"),
            {"task-a": "result-task-a", "task-b": "result-task-b"},
        )

    def test_terminal_resume_does_not_execute_tasks(self) -> None:
        recording = RecordingExecutor()
        durable_service, _, workflow_service = _build_durable_service(recording)
        project = durable_service._project_service.create_project("Project")

        template = _linear_template("template-terminal")
        workflow_run = workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="run-terminal",
        )
        workflow_service.publish_template_snapshot(template, project_id=project.id)
        workflow_run.ready()
        workflow_run.start()
        workflow_run.complete()
        workflow_service.save_workflow_run(workflow_run, expected_version=0)

        context = durable_service.resume_research("run-terminal")

        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(recording.executed, [])

    def test_stale_checkpoint_raises_concurrent_modification(self) -> None:
        recording = RecordingExecutor()
        durable_service, _, workflow_service = _build_durable_service(recording)
        project = durable_service._project_service.create_project("Project")

        template = _linear_template("template-stale")
        workflow_run = workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="run-stale",
        )
        workflow_service.publish_template_snapshot(template, project_id=project.id)

        stale_run = workflow_service.get_workflow_run("run-stale")
        stale_run.ready()
        workflow_service.save_workflow_run(stale_run, expected_version=0)

        fresh_run = workflow_service.get_workflow_run("run-stale")
        fresh_run.start()
        workflow_service.save_workflow_run(fresh_run, expected_version=1)

        with self.assertRaises(ConcurrentModificationError):
            workflow_service.save_workflow_run(stale_run, expected_version=0)

    def test_duplicate_log_event_is_idempotent(self) -> None:
        recording = RecordingExecutor()
        durable_service, _, _ = _build_durable_service(recording)
        project = durable_service._project_service.create_project("Project")

        durable_service.start_research(
            project,
            _linear_template("template-log"),
            run_id="run-log",
        )

        logs = durable_service._audit._execution_log_store.list_for_run("run-log")
        event_ids = [entry.event_id for entry in logs]
        self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_running_task_recovery_marks_failed_on_resume(self) -> None:
        selective = SelectiveExecutor()
        durable_service, _, workflow_service = _build_durable_service(selective)
        project = durable_service._project_service.create_project("Project")

        template = _linear_template("template-running")
        workflow_run = workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="run-running",
        )
        workflow_service.publish_template_snapshot(template, project_id=project.id)
        workflow_run.ready()
        workflow_run.start()
        running_task = workflow_run.tasks[0]
        running_task.ready()
        running_task.start()
        workflow_service.save_workflow_run(workflow_run, expected_version=0)

        selective.executed.clear()
        context = durable_service.resume_research("run-running")

        loaded = workflow_service.get_workflow_run("run-running")
        self.assertEqual(loaded.tasks[0].status, TaskStatus.FAILED)
        self.assertEqual(loaded.status, WorkflowStatus.FAILED)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.FAILED)

    def test_checkpoint_failure_supersedes_executor_error(self) -> None:
        selective = SelectiveExecutor(fail_ids={"task-a"})
        durable_service, _, workflow_service = _build_durable_service(selective)
        project = durable_service._project_service.create_project("Project")

        original_save = workflow_service.save_workflow_run

        def failing_save(workflow_run, *, expected_version=None, task_results=None):
            if any(task.status == TaskStatus.FAILED for task in workflow_run.tasks):
                raise CheckpointPersistenceError("save failed")
            return original_save(
                workflow_run,
                expected_version=expected_version,
                task_results=task_results,
            )

        workflow_service.save_workflow_run = failing_save  # type: ignore[method-assign]

        with self.assertRaises(CheckpointPersistenceError) as ctx:
            durable_service.start_research(
                project,
                _linear_template("template-checkpoint-fail"),
                run_id="run-checkpoint-fail",
            )

        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)


if __name__ == "__main__":
    unittest.main()
