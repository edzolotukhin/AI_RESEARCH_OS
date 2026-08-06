from __future__ import annotations

import unittest

from application.runtime.task_result_codec import restore_runtime_state
from domain.project import Project
from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _restore(
    workflow_run: WorkflowRun,
    task_results: dict,
) -> WorkflowContext:
    context = WorkflowContext(
        workflow_run=workflow_run,
        project=Project(id="project-restore", name="Restore"),
    )
    restore_runtime_state(context, task_results)
    return context


def _branch_graph(task_ids: list[str]) -> TaskDependencyGraph:
    graph = TaskDependencyGraph()
    for task_id in task_ids:
        graph.add_task(task_id)
    graph.add_dependency(task_ids[0], task_ids[1])
    graph.add_dependency(task_ids[0], task_ids[2])
    return graph


class RestoreRuntimeStateTests(unittest.TestCase):

    def test_linear_workflow_applies_snapshots_in_topological_order(self) -> None:
        task_a = make_task("a", task_id="task-a", status=TaskStatus.COMPLETED)
        task_b = make_task(
            "b",
            task_id="task-b",
            depends_on=["a"],
            status=TaskStatus.COMPLETED,
        )
        workflow_run = make_workflow_run(task_b, task_a)
        context = _restore(
            workflow_run,
            {
                "task-a": {"shared_state": {"step": "a"}},
                "task-b": {"shared_state": {"step": "b", "from_a": "a"}},
            },
        )

        self.assertEqual(context.shared_state["step"], "b")
        self.assertEqual(context.shared_state["from_a"], "a")

    def test_branched_workflow_uses_graph_order_not_task_list_order(self) -> None:
        task_root = make_task("root", task_id="task-root", status=TaskStatus.COMPLETED)
        task_left = make_task(
            "left",
            task_id="task-left",
            depends_on=["root"],
            status=TaskStatus.COMPLETED,
        )
        task_right = make_task(
            "right",
            task_id="task-right",
            depends_on=["root"],
            status=TaskStatus.COMPLETED,
        )
        workflow_run = WorkflowRun(
            id="run-restore",
            workflow_template_id="template-restore",
            tasks=[task_right, task_root, task_left],
            dependency_graph=_branch_graph(["task-root", "task-left", "task-right"]),
        )
        workflow_run.validate_dependency_graph()

        context = _restore(
            workflow_run,
            {
                "task-root": {"shared_state": {"marker": "root"}},
                "task-left": {"shared_state": {"marker": "left"}},
                "task-right": {"shared_state": {"marker": "right"}},
            },
        )

        self.assertEqual(context.shared_state["marker"], "right")

    def test_conflicting_shared_state_keys_use_later_topological_snapshot(self) -> None:
        task_a = make_task("a", task_id="task-a", status=TaskStatus.COMPLETED)
        task_b = make_task(
            "b",
            task_id="task-b",
            depends_on=["a"],
            status=TaskStatus.COMPLETED,
        )
        workflow_run = make_workflow_run(task_b, task_a)
        context = _restore(
            workflow_run,
            {
                "task-a": {"shared_state": {"conflict": "first"}},
                "task-b": {"shared_state": {"conflict": "second"}},
            },
        )

        self.assertEqual(context.shared_state["conflict"], "second")

    def test_running_progress_checkpoint_is_restored(self) -> None:
        task_a = make_task("a", task_id="task-a", status=TaskStatus.COMPLETED)
        task_b = make_task(
            "b",
            task_id="task-b",
            depends_on=["a"],
            status=TaskStatus.RUNNING,
        )
        workflow_run = make_workflow_run(task_a, task_b)
        context = _restore(
            workflow_run,
            {
                "task-a": {"shared_state": {"kept": True}},
                "task-b": {
                    "progress": True,
                    "shared_state": {"loop": "partial"},
                },
            },
        )

        self.assertEqual(context.shared_state["kept"], True)
        self.assertEqual(context.shared_state["loop"], "partial")
        self.assertIn("task-b", context.intermediate_results)

    def test_non_completed_tasks_without_progress_are_ignored(self) -> None:
        task_a = make_task("a", task_id="task-a", status=TaskStatus.COMPLETED)
        task_b = make_task(
            "b",
            task_id="task-b",
            depends_on=["a"],
            status=TaskStatus.READY,
        )
        workflow_run = make_workflow_run(task_a, task_b)
        context = _restore(
            workflow_run,
            {
                "task-a": {"shared_state": {"kept": True}},
                "task-b": {"shared_state": {"kept": False}},
            },
        )

        self.assertEqual(context.shared_state, {"kept": True})
        self.assertEqual(set(context.intermediate_results), {"task-a"})


if __name__ == "__main__":
    unittest.main()
