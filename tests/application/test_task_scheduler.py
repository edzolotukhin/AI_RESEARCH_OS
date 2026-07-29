import unittest

from domain.exceptions.workflow_run_factory_error import (
    UnknownTaskDefinitionDependencyError,
)
from application.task_scheduler import TaskScheduler

from domain.value_objects.task_status import TaskStatus

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class TaskSchedulerTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_task_without_dependencies_is_ready(self):
        task_a = make_task("a")
        workflow_run = make_workflow_run(task_a)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_a)

    def test_task_with_completed_dependencies_is_ready(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_b)

    def test_task_with_pending_dependency_is_not_ready(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_a)
        self.assertNotEqual(ready, task_b)

    def test_task_with_running_dependency_is_not_ready(self):
        task_a = make_task("a", status=TaskStatus.RUNNING)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIsNone(ready)

    def test_failed_dependency_blocks_task(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        self.scheduler.resolve_blocked_tasks(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)
        self.assertIsNone(self.scheduler.get_next_task(workflow_run))

    def test_cancelled_dependency_blocks_task(self):
        task_a = make_task("a", status=TaskStatus.CANCELLED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        self.scheduler.resolve_blocked_tasks(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)

    def test_blocked_dependency_propagates_to_downstream_in_single_pass(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)
        self.assertEqual(task_c.status, TaskStatus.SKIPPED)
        self.assertEqual(
            result.skipped_task_ids,
            (task_b.id, task_c.id),
        )

    def test_unknown_dependency_raises_error(self):
        task_b = make_task("b", depends_on=["missing"])

        with self.assertRaises(UnknownTaskDefinitionDependencyError):
            make_workflow_run(task_b)

    def test_linear_chain_executes_in_order(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        execution_order: list[str] = []

        while True:
            self.scheduler.resolve_blocked_tasks(workflow_run)
            self.scheduler.validate_dependencies(workflow_run)

            task = self.scheduler.get_next_task(workflow_run)
            if task is None:
                break

            execution_order.append(task.definition_id)
            task.start()
            task.complete()

        self.assertEqual(execution_order, ["a", "b", "c"])

    def test_branching_dependencies_execute_after_shared_parent(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        execution_order: list[str] = []

        while True:
            self.scheduler.resolve_blocked_tasks(workflow_run)
            self.scheduler.validate_dependencies(workflow_run)

            task = self.scheduler.get_next_task(workflow_run)
            if task is None:
                break

            execution_order.append(task.definition_id)
            task.start()
            task.complete()

        self.assertEqual(execution_order[0], "a")
        self.assertCountEqual(execution_order[1:], ["b", "c"])


if __name__ == "__main__":
    unittest.main()
