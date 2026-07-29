import unittest
from unittest.mock import Mock

from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine

from domain.project import Project
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class RecordingExecutor:
    def __init__(self, lifecycle: TaskLifecycleManager):
        self.lifecycle = lifecycle
        self.executed: list[str] = []

    def run(self, context):
        task = context.current_task
        self.executed.append(task.definition_id)
        return context


class WorkflowEngineSchedulerTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()
        self.lifecycle = TaskLifecycleManager()
        self.recording_executor = RecordingExecutor(self.lifecycle)

        resolver = Mock()
        resolver.resolve.return_value = self.recording_executor

        self.task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=self.lifecycle,
        )
        self.engine = WorkflowEngine(
            scheduler=self.scheduler,
            task_executor=self.task_executor,
        )

        self.project = Project(id="p1", name="Test")
        self.workflow_template = WorkflowTemplate(
            id="template-1",
            name="Test Template",
        )

    def _run_engine(self, workflow_run):
        return self.engine.execute(
            project=self.project,
            workflow_template=self.workflow_template,
            workflow_run=workflow_run,
        )

    def test_engine_creates_workflow_context(self):
        workflow_run = make_workflow_run(make_task("a"))

        context = self._run_engine(workflow_run)

        self.assertIsInstance(context, WorkflowContext)
        self.assertIs(context.workflow_run, workflow_run)
        self.assertIs(context.project, self.project)

    def test_linear_chain_executes_in_order(self):
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b", depends_on=["a"]),
            make_task("c", depends_on=["b"]),
        )

        self._run_engine(workflow_run)

        self.assertEqual(
            self.recording_executor.executed,
            ["a", "b", "c"],
        )
        self.assertEqual(
            workflow_run.status,
            WorkflowStatus.COMPLETED,
        )

    def test_branching_workflow_completes(self):
        workflow_run = make_workflow_run(
            make_task("a"),
            make_task("b", depends_on=["a"]),
            make_task("c", depends_on=["a"]),
        )

        self._run_engine(workflow_run)

        self.assertEqual(self.recording_executor.executed[0], "a")
        self.assertCountEqual(
            self.recording_executor.executed[1:],
            ["b", "c"],
        )
        self.assertEqual(
            workflow_run.status,
            WorkflowStatus.COMPLETED,
        )

    def test_failed_dependency_blocks_downstream_and_stops(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        context = self._run_engine(workflow_run)

        self.assertEqual(self.recording_executor.executed, [])
        self.assertEqual(task_b.status, TaskStatus.SKIPPED)
        self.assertEqual(
            context.workflow_run.status,
            WorkflowStatus.FAILED,
        )

    def test_engine_does_not_loop_when_no_ready_tasks(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        self._run_engine(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)
        self.assertEqual(task_c.status, TaskStatus.SKIPPED)

    def test_engine_raises_when_pending_tasks_cannot_progress(self):
        from application.exceptions.scheduler_error import SchedulerStuckError

        task_a = make_task("a", status=TaskStatus.RUNNING)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        with self.assertRaises(SchedulerStuckError):
            self._run_engine(workflow_run)


if __name__ == "__main__":
    unittest.main()
