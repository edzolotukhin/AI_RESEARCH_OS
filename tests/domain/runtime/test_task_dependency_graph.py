import copy
import unittest

from domain.common.exceptions import ValidationError
from domain.exceptions.task_dependency_graph_error import (
    TaskDependencyCycleError,
    TaskNotFoundInDependencyGraphError,
    TaskSelfDependencyError,
)
from domain.runtime.task_dependency_graph import TaskDependencyGraph


class TaskDependencyGraphTests(unittest.TestCase):

    def test_empty_graph(self):
        graph = TaskDependencyGraph()

        self.assertFalse(graph.has_task("a"))
        self.assertEqual(graph.root_tasks(), ())
        self.assertEqual(graph.leaf_tasks(), ())
        self.assertEqual(graph.topological_order(), ())
        graph.validate()

    def test_add_single_task(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")

        self.assertTrue(graph.has_task("a"))
        self.assertEqual(graph.root_tasks(), ("a",))
        self.assertEqual(graph.leaf_tasks(), ("a",))
        self.assertEqual(graph.topological_order(), ("a",))

    def test_add_multiple_tasks(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c"):
            graph.add_task(task_id)

        self.assertEqual(
            graph.topological_order(),
            ("a", "b", "c"),
        )

    def test_add_valid_dependency(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("b")
        graph.add_dependency("a", "b")

        self.assertTrue(graph.has_dependency("a", "b"))
        self.assertEqual(graph.dependencies_of("b"), ("a",))
        self.assertEqual(graph.dependents_of("a"), ("b",))

    def test_linear_graph(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")

        self.assertEqual(graph.root_tasks(), ("a",))
        self.assertEqual(graph.leaf_tasks(), ("c",))
        self.assertEqual(
            graph.topological_order(),
            ("a", "b", "c"),
        )

    def test_branching_graph(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c", "d"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("a", "c")
        graph.add_dependency("b", "d")
        graph.add_dependency("c", "d")

        self.assertEqual(graph.root_tasks(), ("a",))
        self.assertEqual(graph.leaf_tasks(), ("d",))
        self.assertEqual(graph.topological_order()[0], "a")
        self.assertEqual(graph.topological_order()[-1], "d")

    def test_multiple_independent_branches(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c", "d"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("c", "d")

        self.assertEqual(graph.root_tasks(), ("a", "c"))
        self.assertEqual(graph.leaf_tasks(), ("b", "d"))
        self.assertEqual(
            graph.topological_order(),
            ("a", "b", "c", "d"),
        )

    def test_multiple_roots_and_leaves(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c", "d", "e"):
            graph.add_task(task_id)

        graph.add_dependency("a", "c")
        graph.add_dependency("b", "d")

        self.assertEqual(graph.root_tasks(), ("a", "b", "e"))
        self.assertEqual(graph.leaf_tasks(), ("c", "d", "e"))

    def test_topological_order_is_deterministic(self):
        graph = TaskDependencyGraph()

        for task_id in ("b", "a", "d", "c"):
            graph.add_task(task_id)

        graph.add_dependency("a", "c")
        graph.add_dependency("b", "d")

        first = graph.topological_order()
        second = graph.topological_order()

        self.assertEqual(first, second)
        self.assertEqual(first, ("b", "a", "d", "c"))

    def test_self_dependency_is_rejected(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")

        with self.assertRaises(TaskSelfDependencyError):
            graph.add_dependency("a", "a")

        self.assertFalse(graph.has_dependency("a", "a"))

    def test_direct_cycle_is_rejected(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("b")
        graph.add_dependency("a", "b")

        with self.assertRaises(TaskDependencyCycleError) as ctx:
            graph.add_dependency("b", "a")

        self.assertEqual(ctx.exception.dependency_task_id, "b")
        self.assertEqual(ctx.exception.dependent_task_id, "a")
        self.assertFalse(graph.has_dependency("b", "a"))

    def test_indirect_cycle_is_rejected(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")

        with self.assertRaises(TaskDependencyCycleError) as ctx:
            graph.add_dependency("c", "a")

        self.assertIn("a", ctx.exception.cycle_path)
        self.assertFalse(graph.has_dependency("c", "a"))

    def test_longer_cycle_is_rejected(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c", "d"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")
        graph.add_dependency("c", "d")

        with self.assertRaises(TaskDependencyCycleError):
            graph.add_dependency("d", "a")

        self.assertEqual(len(graph.topological_order()), 4)

    def test_unknown_dependency_task_id(self):
        graph = TaskDependencyGraph()
        graph.add_task("b")

        with self.assertRaises(TaskNotFoundInDependencyGraphError):
            graph.add_dependency("a", "b")

    def test_unknown_dependent_task_id(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")

        with self.assertRaises(TaskNotFoundInDependencyGraphError):
            graph.add_dependency("a", "b")

    def test_read_dependencies_of_unknown_task(self):
        graph = TaskDependencyGraph()

        with self.assertRaises(TaskNotFoundInDependencyGraphError):
            graph.dependencies_of("missing")

    def test_read_dependents_of_unknown_task(self):
        graph = TaskDependencyGraph()

        with self.assertRaises(TaskNotFoundInDependencyGraphError):
            graph.dependents_of("missing")

    def test_repeated_task_add_is_idempotent(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("a")

        self.assertEqual(graph.topological_order(), ("a",))

    def test_repeated_dependency_add_is_idempotent(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("b")
        graph.add_dependency("a", "b")
        graph.add_dependency("a", "b")

        self.assertEqual(graph.dependencies_of("b"), ("a",))
        self.assertEqual(len(graph.topological_order()), 2)

    def test_graph_state_preserved_after_failed_dependency(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("b")
        graph.add_dependency("a", "b")

        with self.assertRaises(TaskDependencyCycleError):
            graph.add_dependency("b", "a")

        self.assertEqual(
            graph.topological_order(),
            ("a", "b"),
        )

    def test_returned_collections_are_immutable(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("b")
        graph.add_dependency("a", "b")

        roots = graph.root_tasks()
        leaves = graph.leaf_tasks()
        order = graph.topological_order()
        dependencies = graph.dependencies_of("b")
        dependents = graph.dependents_of("a")

        with self.assertRaises(TypeError):
            roots[0] = "x"

        self.assertEqual(graph.root_tasks(), roots)
        self.assertEqual(graph.leaf_tasks(), leaves)
        self.assertEqual(graph.topological_order(), order)
        self.assertEqual(graph.dependencies_of("b"), dependencies)
        self.assertEqual(graph.dependents_of("a"), dependents)

    def test_validate_accepts_correct_graph(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")

        graph.validate()

    def test_topological_order_respects_every_edge(self):
        graph = TaskDependencyGraph()

        for task_id in ("a", "b", "c", "d"):
            graph.add_task(task_id)

        graph.add_dependency("a", "b")
        graph.add_dependency("a", "c")
        graph.add_dependency("b", "d")
        graph.add_dependency("c", "d")

        order = graph.topological_order()
        positions = {task_id: index for index, task_id in enumerate(order)}

        self.assertLess(positions["a"], positions["b"])
        self.assertLess(positions["a"], positions["c"])
        self.assertLess(positions["b"], positions["d"])
        self.assertLess(positions["c"], positions["d"])

    def test_cycle_error_contains_path(self):
        graph = TaskDependencyGraph()
        graph.add_task("a")
        graph.add_task("b")
        graph.add_dependency("a", "b")

        with self.assertRaises(TaskDependencyCycleError) as ctx:
            graph.add_dependency("b", "a")

        self.assertEqual(ctx.exception.cycle_path, ("b", "a"))


class TaskDependencyGraphIntegrationNotesTests(unittest.TestCase):
    """
    Documents expected mapping from existing Task.depends_on semantics.
    """

    def test_graph_models_definition_id_dependencies(self):
        graph = TaskDependencyGraph()
        graph.add_task("task-methodology")
        graph.add_task("task-sample")
        graph.add_dependency("task-methodology", "task-sample")

        self.assertEqual(
            graph.dependencies_of("task-sample"),
            ("task-methodology",),
        )


if __name__ == "__main__":
    unittest.main()
