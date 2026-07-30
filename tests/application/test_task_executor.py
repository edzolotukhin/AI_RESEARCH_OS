import unittest
from unittest.mock import Mock

from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager

from domain.project import Project
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class TaskExecutorResolverIntegrationTests(unittest.TestCase):

    def test_task_executor_uses_only_executor_resolver(self):
        resolver = Mock()
        lifecycle = TaskLifecycleManager()
        executor = Mock()
        executor.run.side_effect = lambda context: context
        resolver.resolve.return_value = executor

        task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=lifecycle,
        )

        task = make_task(
            "task-1",
            executor_id="planner",
            executor_type=ExecutorType.AGENT,
            status=TaskStatus.READY,
        )
        workflow_run = make_workflow_run(task)
        context = WorkflowContext(
            workflow_run=workflow_run,
            project=Project(id="p1", name="Test"),
            current_task=task,
        )

        result = task_executor.execute(context)

        resolver.resolve.assert_called_once_with(task)
        executor.run.assert_called_once_with(context)
        self.assertIs(result, context)

    def test_task_executor_accepts_only_workflow_context(self):
        resolver = Mock()
        lifecycle = TaskLifecycleManager()

        task_executor = TaskExecutor(
            resolver=resolver,
            lifecycle=lifecycle,
        )

        task = make_task("task-1", status=TaskStatus.READY)
        context = WorkflowContext(
            workflow_run=make_workflow_run(task),
            project=Project(id="p1", name="Test"),
            current_task=task,
        )

        resolver.resolve.return_value = Mock(
            run=lambda workflow_context: workflow_context,
        )

        result = task_executor.execute(context)

        self.assertIsInstance(result, WorkflowContext)


if __name__ == "__main__":
    unittest.main()
