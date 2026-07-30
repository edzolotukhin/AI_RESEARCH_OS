import unittest

from domain.workflow import Workflow


class WorkflowTests(unittest.TestCase):

    def test_workflow_is_created(self):
        workflow = (
            Workflow(
                id="brand_health",
                name="Brand Health",
            )
            .task(
                id="planner",
                name="Planner",
                executor_id="planner",
            )
            .task(
                id="search",
                name="Search",
                executor_id="search",
                depends_on=["planner"],
            )
            .build()
        )

        self.assertEqual(workflow.id, "brand_health")
        self.assertEqual(workflow.name, "Brand Health")
        self.assertEqual(len(workflow.task_definitions), 2)

    def test_duplicate_task_id_raises_error(self):
        with self.assertRaises(ValueError):
            (
                Workflow(
                    id="duplicate",
                    name="Duplicate",
                )
                .task(
                    id="planner",
                    name="Planner",
                    executor_id="planner",
                )
                .task(
                    id="planner",
                    name="Planner 2",
                    executor_id="planner",
                )
                .build()
            )

    def test_unknown_dependency_raises_error(self):
        with self.assertRaises(ValueError):
            (
                Workflow(
                    id="dependency",
                    name="Dependency",
                )
                .task(
                    id="search",
                    name="Search",
                    executor_id="search",
                    depends_on=["planner"],
                )
                .build()
            )

    def test_circular_dependency_raises_error(self):
        with self.assertRaises(ValueError):
            (
                Workflow(
                    id="cycle",
                    name="Cycle",
                )
                .task(
                    id="planner",
                    name="Planner",
                    executor_id="planner",
                    depends_on=["writer"],
                )
                .task(
                    id="writer",
                    name="Writer",
                    executor_id="writer",
                    depends_on=["planner"],
                )
                .build()
            )


if __name__ == "__main__":
    unittest.main()