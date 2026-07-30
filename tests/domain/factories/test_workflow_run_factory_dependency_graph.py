import unittest

from domain.exceptions.workflow_run_factory_error import (
    DuplicateTaskDefinitionIdError,
    UnknownTaskDefinitionDependencyError,
    WorkflowRunDependencyGraphBuildError,
)
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_dependency_graph_builder import (
    WorkflowRunDependencyGraphBuilder,
)
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate


def _definition(
    definition_id: str,
    *,
    depends_on: list[str] | None = None,
) -> TaskDefinition:
    return TaskDefinition(
        id=definition_id,
        name=definition_id,
        executor_id="agent",
        executor_type=ExecutorType.AGENT,
        depends_on=list(depends_on or []),
    )


def _template(
    *definitions: TaskDefinition,
    template_id: str = "template-1",
) -> WorkflowTemplate:
    return WorkflowTemplate(
        id=template_id,
        name="Test Template",
        task_definitions=list(definitions),
    )


class WorkflowRunDependencyGraphBuilderTests(unittest.TestCase):

    def setUp(self):
        self.task_factory = TaskFactory()
        self.factory = WorkflowRunFactory(self.task_factory)

    def test_empty_workflow_run_has_empty_graph(self):
        workflow_run = self.factory.create(
            _template(),
            run_id="run-empty",
        )

        self.assertEqual(workflow_run.tasks, [])
        self.assertEqual(
            workflow_run.dependency_graph.topological_order(),
            (),
        )
        workflow_run.validate_dependency_graph()

    def test_single_task_is_root(self):
        workflow_run = self.factory.create(
            _template(_definition("a")),
            run_id="run-single",
        )

        task = workflow_run.tasks[0]
        graph = workflow_run.dependency_graph

        self.assertEqual(graph.dependencies_of(task.id), ())
        self.assertEqual(graph.root_tasks(), (task.id,))
        self.assertEqual(graph.topological_order(), (task.id,))

    def test_multiple_independent_tasks_are_roots(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b"),
                _definition("c"),
            ),
            run_id="run-independent",
        )

        graph = workflow_run.dependency_graph
        task_ids = {task.id for task in workflow_run.tasks}

        self.assertEqual(set(graph.root_tasks()), task_ids)
        self.assertEqual(set(graph.topological_order()), task_ids)

    def test_linear_dependency_chain(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b", depends_on=["a"]),
                _definition("c", depends_on=["b"]),
            ),
            run_id="run-linear",
        )

        by_definition = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }
        graph = workflow_run.dependency_graph

        self.assertTrue(
            graph.has_dependency(by_definition["a"], by_definition["b"]),
        )
        self.assertTrue(
            graph.has_dependency(by_definition["b"], by_definition["c"]),
        )
        self.assertEqual(
            graph.topological_order(),
            (
                by_definition["a"],
                by_definition["b"],
                by_definition["c"],
            ),
        )

    def test_branching_dependencies(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b", depends_on=["a"]),
                _definition("c", depends_on=["a"]),
            ),
            run_id="run-branch",
        )

        by_definition = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }
        graph = workflow_run.dependency_graph

        self.assertEqual(graph.root_tasks(), (by_definition["a"],))
        self.assertEqual(
            set(graph.dependents_of(by_definition["a"])),
            {by_definition["b"], by_definition["c"]},
        )

    def test_merge_dependencies(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b"),
                _definition("c", depends_on=["a", "b"]),
            ),
            run_id="run-merge",
        )

        by_definition = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }
        graph = workflow_run.dependency_graph

        self.assertTrue(
            graph.has_dependency(by_definition["a"], by_definition["c"]),
        )
        self.assertTrue(
            graph.has_dependency(by_definition["b"], by_definition["c"]),
        )
        self.assertEqual(
            set(graph.dependencies_of(by_definition["c"])),
            {by_definition["a"], by_definition["b"]},
        )

    def test_multiple_independent_branches(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b", depends_on=["a"]),
                _definition("c"),
                _definition("d", depends_on=["c"]),
            ),
            run_id="run-branches",
        )

        by_definition = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }
        graph = workflow_run.dependency_graph

        self.assertEqual(
            set(graph.root_tasks()),
            {by_definition["a"], by_definition["c"]},
        )
        self.assertEqual(len(graph.topological_order()), 4)

    def test_definitions_in_arbitrary_order_still_build_valid_graph(self):
        workflow_run = self.factory.create(
            _template(
                _definition("c", depends_on=["b"]),
                _definition("a"),
                _definition("b", depends_on=["a"]),
            ),
            run_id="run-shuffled",
        )

        by_definition = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }

        self.assertEqual(
            workflow_run.dependency_graph.topological_order(),
            (
                by_definition["a"],
                by_definition["b"],
                by_definition["c"],
            ),
        )

    def test_definition_id_maps_to_unique_runtime_task_id(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b", depends_on=["a"]),
            ),
            run_id="run-mapping",
        )

        mapping = {
            task.definition_id: task.id
            for task in workflow_run.tasks
        }

        self.assertEqual(len(mapping), 2)
        self.assertNotEqual(mapping["a"], mapping["b"])
        self.assertNotEqual(mapping["a"], "a")
        self.assertNotEqual(mapping["b"], "b")

    def test_all_runtime_tasks_are_present_in_graph(self):
        workflow_run = self.factory.create(
            _template(
                _definition("a"),
                _definition("b", depends_on=["a"]),
            ),
            run_id="run-membership",
        )

        task_ids = {task.id for task in workflow_run.tasks}
        graph_ids = set(workflow_run.dependency_graph.topological_order())

        self.assertEqual(task_ids, graph_ids)

    def test_graph_does_not_contain_foreign_task_ids(self):
        workflow_run = self.factory.create(
            _template(_definition("a")),
            run_id="run-foreign",
        )

        graph_ids = set(workflow_run.dependency_graph.topological_order())
        task_ids = {task.id for task in workflow_run.tasks}

        self.assertEqual(graph_ids, task_ids)
        self.assertNotIn("foreign-task", graph_ids)

    def test_unknown_declarative_dependency_raises(self):
        template = _template(
            _definition("a", depends_on=["missing"]),
        )

        with self.assertRaises(UnknownTaskDefinitionDependencyError) as ctx:
            self.factory.create(template, run_id="run-unknown")

        error = ctx.exception
        self.assertEqual(error.workflow_template_id, "template-1")
        self.assertEqual(error.task_definition_id, "a")
        self.assertEqual(error.dependency_definition_id, "missing")

    def test_self_dependency_raises(self):
        template = _template(
            _definition("a", depends_on=["a"]),
        )

        with self.assertRaises(WorkflowRunDependencyGraphBuildError) as ctx:
            self.factory.create(template, run_id="run-self")

        self.assertEqual(ctx.exception.task_definition_id, "a")

    def test_direct_cycle_raises(self):
        template = _template(
            _definition("a", depends_on=["b"]),
            _definition("b", depends_on=["a"]),
        )

        with self.assertRaises(WorkflowRunDependencyGraphBuildError):
            self.factory.create(template, run_id="run-cycle")

    def test_indirect_cycle_raises(self):
        template = _template(
            _definition("a", depends_on=["c"]),
            _definition("b", depends_on=["a"]),
            _definition("c", depends_on=["b"]),
        )

        with self.assertRaises(WorkflowRunDependencyGraphBuildError):
            self.factory.create(template, run_id="run-indirect-cycle")

    def test_duplicate_definition_id_raises(self):
        template = _template(
            _definition("a"),
            _definition("a"),
        )

        with self.assertRaises(DuplicateTaskDefinitionIdError) as ctx:
            self.factory.create(template, run_id="run-duplicate")

        self.assertEqual(ctx.exception.definition_id, "a")

    def test_build_from_tasks_unknown_dependency_raises(self):
        tasks = [
            self.task_factory.create(_definition("a", depends_on=["missing"])),
        ]

        with self.assertRaises(UnknownTaskDefinitionDependencyError):
            WorkflowRunDependencyGraphBuilder.build_from_tasks(
                tasks,
                workflow_template_id="template-1",
            )


class WorkflowRunFactoryGraphOwnershipTests(unittest.TestCase):

    def test_factory_attaches_graph_to_workflow_run(self):
        factory = WorkflowRunFactory(TaskFactory())
        template = _template(
            _definition("a"),
            _definition("b", depends_on=["a"]),
        )

        workflow_run = factory.create(template, run_id="run-owned")

        self.assertIsNotNone(workflow_run.dependency_graph)
        self.assertEqual(len(workflow_run.dependency_graph.topological_order()), 2)


if __name__ == "__main__":
    unittest.main()
