import inspect
import unittest

from application.exceptions.task_scheduling_invariant_error import (
    TaskSchedulingInvariantError,
)
from application.scheduling.scheduling_result import SchedulingResult
from application.task_scheduler import TaskScheduler

from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class TaskSchedulerRootTaskTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_empty_workflow_run(self):
        workflow_run = WorkflowRun(
            id="run-empty",
            workflow_template_id="template-1",
        )

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(result, SchedulingResult.empty())
        self.assertFalse(result.has_changes)

    def test_single_root_created_becomes_ready(self):
        task_a = make_task("a")
        workflow_run = make_workflow_run(task_a)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_a.id,))
        self.assertEqual(result.transition_count, 1)

    def test_multiple_root_tasks_become_ready(self):
        task_a = make_task("a")
        task_b = make_task("b")
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.READY)
        self.assertEqual(task_b.status, TaskStatus.READY)
        self.assertEqual(
            result.ready_task_ids,
            (task_a.id, task_b.id),
        )

    def test_root_ready_stays_ready(self):
        task_a = make_task("a", status=TaskStatus.READY)
        workflow_run = make_workflow_run(task_a)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.READY)
        self.assertEqual(result.transition_count, 0)
        self.assertIn(task_a.id, result.unchanged_task_ids)

    def test_root_running_is_unchanged(self):
        task_a = make_task("a", status=TaskStatus.RUNNING)
        workflow_run = make_workflow_run(task_a)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.RUNNING)
        self.assertEqual(result.transition_count, 0)

    def test_root_terminal_states_are_unchanged(self):
        for status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        ):
            with self.subTest(status=status):
                task_a = make_task("a", status=status)
                workflow_run = make_workflow_run(task_a)

                result = self.scheduler.schedule(workflow_run)

                self.assertEqual(task_a.status, status)
                self.assertEqual(result.transition_count, 0)

    def test_root_waiting_becomes_ready(self):
        task_a = make_task("a", status=TaskStatus.WAITING)
        workflow_run = make_workflow_run(task_a)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_a.id,))

    def test_repeated_pass_is_idempotent(self):
        task_a = make_task("a")
        workflow_run = make_workflow_run(task_a)

        first = self.scheduler.schedule(workflow_run)
        second = self.scheduler.schedule(workflow_run)

        self.assertTrue(first.has_changes)
        self.assertFalse(second.has_changes)
        self.assertEqual(second.transition_count, 0)


class TaskSchedulerDependentTaskTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_created_with_incomplete_dependency_becomes_waiting(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.WAITING)
        self.assertEqual(result.waiting_task_ids, (task_b.id,))

    def test_waiting_with_incomplete_dependency_stays_waiting(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.WAITING)
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.WAITING)
        self.assertIn(task_b.id, result.unchanged_task_ids)

    def test_created_with_completed_dependencies_becomes_ready(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_b.id,))

    def test_waiting_with_completed_dependencies_becomes_ready(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.WAITING)
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_b.id,))

    def test_ready_with_completed_dependencies_stays_ready(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.READY)
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.READY)
        self.assertIn(task_b.id, result.unchanged_task_ids)

    def test_failed_dependency_skips_dependent(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)
        self.assertEqual(result.skipped_task_ids, (task_b.id,))
        self.assertTrue(result.has_dependency_failures)

    def test_cancelled_dependency_skips_dependent(self):
        task_a = make_task("a", status=TaskStatus.CANCELLED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)

    def test_skipped_dependency_skips_dependent(self):
        task_a = make_task("a", status=TaskStatus.SKIPPED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.SKIPPED)

    def test_multiple_dependencies_all_completed_becomes_ready(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", status=TaskStatus.COMPLETED)
        task_c = make_task("c", depends_on=["a", "b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_c.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_c.id,))

    def test_one_running_dependency_keeps_dependent_waiting(self):
        task_a = make_task("a", status=TaskStatus.RUNNING)
        task_b = make_task("b", status=TaskStatus.COMPLETED)
        task_c = make_task("c", depends_on=["a", "b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_c.status, TaskStatus.WAITING)
        self.assertEqual(result.waiting_task_ids, (task_c.id,))

    def test_one_failed_dependency_skips_dependent(self):
        task_a = make_task("a", status=TaskStatus.FAILED)
        task_b = make_task("b", status=TaskStatus.COMPLETED)
        task_c = make_task("c", depends_on=["a", "b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_c.status, TaskStatus.SKIPPED)
        self.assertEqual(result.skipped_task_ids, (task_c.id,))

    def test_dependency_order_does_not_affect_decision(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", status=TaskStatus.COMPLETED)
        task_c = make_task("c", depends_on=["b", "a"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        self.scheduler.schedule(workflow_run)

        self.assertEqual(task_c.status, TaskStatus.READY)

    def test_diamond_graph(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.COMPLETED)
        task_c = make_task("c", depends_on=["a"], status=TaskStatus.COMPLETED)
        task_d = make_task("d", depends_on=["b", "c"])
        workflow_run = make_workflow_run(task_a, task_b, task_c, task_d)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_d.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_d.id,))

    def test_evaluated_in_topological_order(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(
            result.evaluated_task_ids,
            workflow_run.dependency_graph.topological_order(),
        )

    def test_dependent_idempotency_after_dependency_completion(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        first = self.scheduler.schedule(workflow_run)
        second = self.scheduler.schedule(workflow_run)

        self.assertTrue(first.has_changes)
        self.assertFalse(second.has_changes)

        task_a.start()
        task_a.complete()

        third = self.scheduler.schedule(workflow_run)
        fourth = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.READY)
        self.assertTrue(third.has_changes)
        self.assertFalse(fourth.has_changes)


class TaskSchedulerInvariantTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_duplicate_task_id_raises(self):
        task_a = make_task("a", task_id="same-id")
        task_b = make_task("b", task_id="same-id")
        workflow_run = WorkflowRun(
            id="run-dup",
            workflow_template_id="template-1",
            tasks=[task_a, task_b],
            dependency_graph=TaskDependencyGraph(),
        )

        with self.assertRaises(TaskSchedulingInvariantError) as ctx:
            self.scheduler.schedule(workflow_run)

        self.assertEqual(ctx.exception.task_id, "same-id")

    def test_task_missing_from_graph_raises(self):
        task_a = make_task("a")
        workflow_run = WorkflowRun(
            id="run-missing",
            workflow_template_id="template-1",
            tasks=[task_a],
            dependency_graph=TaskDependencyGraph(),
        )

        with self.assertRaises(TaskSchedulingInvariantError):
            self.scheduler.schedule(workflow_run)

    def test_ready_with_incomplete_dependency_raises(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.READY)
        workflow_run = make_workflow_run(task_a, task_b)

        with self.assertRaises(TaskSchedulingInvariantError) as ctx:
            self.scheduler.schedule(workflow_run)

        self.assertEqual(ctx.exception.task_id, task_b.id)
        self.assertIn(task_a.id, ctx.exception.dependency_ids)

    def test_running_with_incomplete_dependency_raises(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.RUNNING)
        workflow_run = make_workflow_run(task_a, task_b)

        with self.assertRaises(TaskSchedulingInvariantError) as ctx:
            self.scheduler.schedule(workflow_run)

        self.assertEqual(ctx.exception.task_id, task_b.id)

    def test_completed_with_incomplete_dependency_raises(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.COMPLETED)
        workflow_run = make_workflow_run(task_a, task_b)

        with self.assertRaises(TaskSchedulingInvariantError) as ctx:
            self.scheduler.schedule(workflow_run)

        self.assertEqual(ctx.exception.task_id, task_b.id)

    def test_analysis_error_does_not_mutate_tasks(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"], status=TaskStatus.READY)
        workflow_run = make_workflow_run(task_a, task_b)

        statuses_before = {
            task.id: task.status
            for task in workflow_run.tasks
        }

        with self.assertRaises(TaskSchedulingInvariantError):
            self.scheduler.schedule(workflow_run)

        statuses_after = {
            task.id: task.status
            for task in workflow_run.tasks
        }

        self.assertEqual(statuses_before, statuses_after)


class TaskSchedulerIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_first_pass_promotes_root_and_waits_for_dependents(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.READY)
        self.assertEqual(task_b.status, TaskStatus.WAITING)
        self.assertEqual(result.ready_task_ids, (task_a.id,))
        self.assertEqual(result.waiting_task_ids, (task_b.id,))

    def test_second_pass_promotes_dependent_after_root_completion(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        self.scheduler.schedule(workflow_run)
        task_a.start()
        task_a.complete()

        result = self.scheduler.schedule(workflow_run)

        self.assertEqual(task_b.status, TaskStatus.READY)
        self.assertEqual(result.ready_task_ids, (task_b.id,))

    def test_scheduler_does_not_change_workflow_run_status(self):
        from domain.workflow_status import WorkflowStatus

        task_a = make_task("a")
        workflow_run = make_workflow_run(task_a)

        self.assertEqual(workflow_run.status, WorkflowStatus.CREATED)

        self.scheduler.schedule(workflow_run)

        self.assertEqual(workflow_run.status, WorkflowStatus.CREATED)

    def test_scheduler_does_not_mutate_graph(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        graph_before = workflow_run.dependency_graph.topological_order()

        self.scheduler.schedule(workflow_run)

        self.assertEqual(
            workflow_run.dependency_graph.topological_order(),
            graph_before,
        )

    def test_scheduler_ignores_incorrect_task_depends_on(self):
        task_a = make_task("a", task_id="runtime-a")
        task_b = make_task(
            "b",
            task_id="runtime-b",
            depends_on=[],
        )

        graph = TaskDependencyGraph()
        graph.add_task(task_a.id)
        graph.add_task(task_b.id)
        graph.add_dependency(task_a.id, task_b.id)
        graph.validate()

        workflow_run = WorkflowRun(
            id="run-graph-only",
            workflow_template_id="template-1",
            tasks=[task_a, task_b],
            dependency_graph=graph,
        )
        workflow_run.validate_dependency_graph()

        self.scheduler.schedule(workflow_run)

        self.assertEqual(task_a.status, TaskStatus.READY)
        self.assertEqual(task_b.status, TaskStatus.WAITING)


class TaskSchedulerArchitectureTests(unittest.TestCase):

    def test_scheduler_does_not_read_task_depends_on(self):
        source = inspect.getsource(TaskScheduler)

        self.assertNotIn("depends_on", source)

    def test_scheduler_uses_domain_methods_for_transitions(self):
        source = inspect.getsource(TaskScheduler)

        self.assertIn("task.ready()", source)
        self.assertIn("task.schedule()", source)
        self.assertIn("task.skip()", source)


if __name__ == "__main__":
    unittest.main()
