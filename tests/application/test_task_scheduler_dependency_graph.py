import inspect
import unittest

from application.task_scheduler import TaskScheduler

from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class TaskSchedulerDependencyGraphIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = TaskScheduler()

    def test_root_task_is_determined_via_graph(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        root_ids = set(workflow_run.dependency_graph.root_tasks())

        self.assertEqual(root_ids, {task_a.id})
        self.assertIs(self.scheduler.get_next_task(workflow_run), task_a)

    def test_task_with_incomplete_dependency_stays_waiting(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_a)
        self.assertIn(task_b.status, {TaskStatus.CREATED, TaskStatus.WAITING})

    def test_task_becomes_ready_after_all_dependencies_complete(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_b)

    def test_task_not_ready_when_only_some_dependencies_complete(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b")
        task_c = make_task("c", depends_on=["a", "b"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_b)
        self.assertNotEqual(ready, task_c)

    def test_multiple_dependents_of_one_task(self):
        task_a = make_task("a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b, task_c)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIn(ready, [task_b, task_c])

    def test_scheduler_works_when_definition_id_differs_from_task_id(self):
        task_a = make_task("def-a", task_id="runtime-a")
        task_b = make_task(
            "def-b",
            task_id="runtime-b",
            depends_on=["def-a"],
        )
        workflow_run = make_workflow_run(task_a, task_b)

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_a)

        task_a.start()
        task_a.complete()
        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_b)

    def test_scheduler_ignores_incorrect_task_depends_on_when_graph_is_correct(
        self,
    ):
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

        ready = self.scheduler.get_next_task(workflow_run)

        self.assertIs(ready, task_a)
        self.assertNotEqual(ready, task_b)

    def test_scheduler_does_not_mutate_dependency_graph(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        workflow_run = make_workflow_run(task_a, task_b)

        graph_before = workflow_run.dependency_graph.topological_order()

        self.scheduler.resolve_blocked_tasks(workflow_run)
        self.scheduler.get_next_task(workflow_run)
        self.scheduler.validate_dependencies(workflow_run)

        self.assertEqual(
            workflow_run.dependency_graph.topological_order(),
            graph_before,
        )

    def test_scheduler_is_independent_of_task_collection_order(self):
        task_a = make_task("a")
        task_b = make_task("b", depends_on=["a"])
        task_c = make_task("c", depends_on=["b"])

        workflow_run_forward = make_workflow_run(task_a, task_b, task_c)
        workflow_run_reverse = make_workflow_run(task_c, task_b, task_a)

        ready_forward = self.scheduler.get_next_task(workflow_run_forward)
        ready_reverse = self.scheduler.get_next_task(workflow_run_reverse)

        self.assertEqual(
            ready_forward.definition_id,
            ready_reverse.definition_id,
        )


class TaskSchedulerArchitectureTests(unittest.TestCase):

    def test_scheduler_does_not_read_task_depends_on(self):
        source = inspect.getsource(TaskScheduler)

        self.assertNotIn("depends_on", source)

    def test_scheduler_does_not_import_task_definition(self):
        module = inspect.getmodule(TaskScheduler)
        assert module is not None

        self.assertNotIn(
            "TaskDefinition",
            inspect.getsource(module),
        )


if __name__ == "__main__":
    unittest.main()
