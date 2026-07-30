import inspect
import unittest
from unittest.mock import Mock

from application.runtime.workflow_completion_policy import (
    WorkflowCompletionPolicy,
)
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine

from domain.project import Project
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class RecordingExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        assert task is not None
        self.executed.append(task.definition_id)
        return context


class WorkflowRuntimeLoopTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()
        self.lifecycle = TaskLifecycleManager()
        self.recording_executor = RecordingExecutor()

        resolver = Mock()
        resolver.resolve.return_value = self.recording_executor

        self.task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=self.lifecycle,
        )
        self.completion_policy = WorkflowCompletionPolicy()
        self.engine = WorkflowEngine(
            scheduler=self.scheduler,
            task_executor=self.task_executor,
            completion_policy=self.completion_policy,
        )

        self.project = Project(id="p1", name="Test")
        self.workflow_template = WorkflowTemplate(
            id="template-1",
            name="Test Template",
        )

    def _context(self, workflow_run: WorkflowRun) -> WorkflowContext:
        return WorkflowContext(
            project=self.project,
            workflow_template=self.workflow_template,
            workflow_run=workflow_run,
        )

    def _run(self, workflow_run: WorkflowRun) -> WorkflowContext:
        return self.engine.run(self._context(workflow_run))

    def test_successful_single_task_workflow_completes(self):
        workflow_run = make_workflow_run(make_task("a"))

        self._run(workflow_run)

        self.assertEqual(self.recording_executor.executed, ["a"])
        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

    def test_sequential_workflow_executes_in_order(self):
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b", depends_on=["a"]),
            make_task("c", depends_on=["b"]),
        )

        self._run(workflow_run)

        self.assertEqual(
            self.recording_executor.executed,
            ["a", "b", "c"],
        )
        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

    def test_branching_workflow_executes_all_tasks(self):
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b", depends_on=["a"]),
            make_task("c", depends_on=["a"]),
        )

        self._run(workflow_run)

        self.assertEqual(self.recording_executor.executed[0], "a")
        self.assertCountEqual(
            self.recording_executor.executed[1:],
            ["b", "c"],
        )
        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

    def test_skip_cascade_marks_workflow_failed(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        self._run(workflow_run)

        self.assertEqual(self.recording_executor.executed, [])
        self.assertEqual(task_b.status, TaskStatus.SKIPPED)
        self.assertEqual(task_c.status, TaskStatus.SKIPPED)
        self.assertEqual(workflow_run.status, WorkflowStatus.FAILED)

    def test_failed_task_during_execution_marks_workflow_failed(self):
        class FailingExecutor:
            def run(self, context: WorkflowContext) -> WorkflowContext:
                raise RuntimeError("execution failed")

        resolver = Mock()
        resolver.resolve.return_value = FailingExecutor()
        task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=self.lifecycle,
        )
        engine = WorkflowEngine(
            scheduler=self.scheduler,
            task_executor=task_executor,
            completion_policy=WorkflowCompletionPolicy(),
        )
        workflow_run = make_workflow_run(make_task("a"))

        with self.assertRaises(RuntimeError):
            engine.run(self._context(workflow_run))

        self.assertEqual(workflow_run.tasks[0].status, TaskStatus.FAILED)
        self.assertEqual(workflow_run.status, WorkflowStatus.RUNNING)

    def test_no_progress_stops_without_exception(self):
        task_a = make_task("a", status=TaskStatus.RUNNING)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        self._run(workflow_run)

        self.assertEqual(workflow_run.status, WorkflowStatus.RUNNING)
        self.assertEqual(task_b.status, TaskStatus.WAITING)

    def test_empty_workflow_completes(self):
        workflow_run = WorkflowRun(
            id="run-empty",
            workflow_template_id="template-1",
        )

        self._run(workflow_run)

        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

    def test_all_skipped_without_failed_is_completed(self):
        task_a = make_task("a", status=TaskStatus.SKIPPED)
        task_b = make_task("b", status=TaskStatus.SKIPPED)
        workflow_run = make_workflow_run(task_a, task_b)

        self._run(workflow_run)

        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

    def test_cancelled_workflow_is_not_started(self):
        workflow_run = make_workflow_run(make_task("a"))
        workflow_run.cancel()

        self._run(workflow_run)

        self.assertEqual(workflow_run.status, WorkflowStatus.CANCELLED)
        self.assertEqual(self.recording_executor.executed, [])

    def test_scheduler_called_on_each_iteration(self):
        scheduler = Mock(spec=TaskScheduler)
        scheduler.schedule.side_effect = TaskScheduler().schedule
        scheduler.find_ready_task.side_effect = TaskScheduler().find_ready_task

        completion_policy = WorkflowCompletionPolicy()

        engine = WorkflowEngine(
            scheduler=scheduler,
            task_executor=self.task_executor,
            completion_policy=completion_policy,
        )
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b", depends_on=["a"]),
        )

        engine.run(self._context(workflow_run))

        self.assertGreaterEqual(scheduler.schedule.call_count, 2)
        self.assertGreaterEqual(scheduler.find_ready_task.call_count, 2)

    def test_executor_called_only_for_ready_tasks(self):
        executor_calls: list[str | None] = []
        recording = RecordingExecutor()

        class TrackingExecutor:
            def run(self, context: WorkflowContext) -> WorkflowContext:
                task = context.current_task
                executor_calls.append(
                    None if task is None else task.definition_id,
                )
                return recording.run(context)

        resolver = Mock()
        resolver.resolve.return_value = TrackingExecutor()
        task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=self.lifecycle,
        )
        engine = WorkflowEngine(
            scheduler=self.scheduler,
            task_executor=task_executor,
            completion_policy=WorkflowCompletionPolicy(),
        )
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b", depends_on=["a"]),
        )

        engine.run(self._context(workflow_run))

        self.assertEqual(executor_calls, ["a", "b"])

    def test_multiple_ready_tasks_execute_one_per_iteration(self):
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b"),
            make_task("c"),
        )

        self._run(workflow_run)

        self.assertEqual(len(self.recording_executor.executed), 3)
        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

    def test_execute_delegates_to_run(self):
        workflow_run = make_workflow_run(make_task("a"))

        context = self.engine.execute(
            project=self.project,
            workflow_template=self.workflow_template,
            workflow_run=workflow_run,
        )

        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)


class WorkflowRuntimeLoopArchitectureTests(unittest.TestCase):

    def test_engine_does_not_call_task_readiness_methods(self):
        source = inspect.getsource(WorkflowEngine)

        self.assertNotIn("task.ready(", source)
        self.assertNotIn("task.skip(", source)
        self.assertNotIn("task.schedule(", source)

    def test_engine_uses_completion_policy_for_final_status(self):
        source = inspect.getsource(WorkflowEngine)

        self.assertIn("_completion_policy", source)
        self.assertIn("resolve(", source)

    def test_scheduler_does_not_contain_completion_policy(self):
        source = inspect.getsource(TaskScheduler)

        self.assertNotIn("WorkflowStatus", source)
        self.assertNotIn("resolve_completion", source)
        self.assertNotIn("all_tasks_terminal", source)

    def test_lifecycle_manager_start_only_calls_task_start(self):
        source = inspect.getsource(TaskLifecycleManager)

        self.assertIn("task.start()", source)
        self.assertNotIn("task.ready(", source)
        self.assertNotIn("task.schedule(", source)


if __name__ == "__main__":
    unittest.main()
