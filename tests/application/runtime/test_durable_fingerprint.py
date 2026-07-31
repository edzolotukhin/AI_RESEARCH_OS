from __future__ import annotations

import copy
import unittest

from application.runtime.durable_fingerprint import durable_recovery_fingerprint
from domain.project import Project
from domain.runtime.task_dependency_graph import TaskDependencyGraph
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _context(workflow_run: WorkflowRun) -> WorkflowContext:
    return WorkflowContext(
        workflow_run=workflow_run,
        project=Project(id="project-1", name="Project"),
    )


def _running_run(*tasks) -> WorkflowRun:
    workflow_run = make_workflow_run(*tasks)
    workflow_run.ready()
    workflow_run.start()
    return workflow_run


class DurableFingerprintTests(unittest.TestCase):

    def test_same_durable_state_produces_same_fingerprint(self) -> None:
        run = _running_run(
            make_task("a", task_id="task-a", status=TaskStatus.COMPLETED),
            make_task("b", task_id="task-b", depends_on=["a"], status=TaskStatus.READY),
        )
        task_results = {
            "task-a": {
                "task_id": "task-a",
                "shared_state": {"alpha": "β"},
            }
        }
        context_one = _context(run)
        context_two = _context(copy.deepcopy(run))

        fingerprint_one = durable_recovery_fingerprint(context_one, task_results)
        fingerprint_two = durable_recovery_fingerprint(
            context_two,
            copy.deepcopy(task_results),
        )

        self.assertEqual(fingerprint_one, fingerprint_two)

    def test_changed_task_result_value_changes_fingerprint(self) -> None:
        run = _running_run(make_task("a", task_id="task-a", status=TaskStatus.COMPLETED))
        context = _context(run)

        baseline = durable_recovery_fingerprint(
            context,
            {"task-a": {"shared_state": {"value": "one"}}},
        )
        changed = durable_recovery_fingerprint(
            context,
            {"task-a": {"shared_state": {"value": "two"}}},
        )

        self.assertNotEqual(baseline, changed)

    def test_task_result_mapping_key_order_is_ignored(self) -> None:
        run = _running_run(make_task("a", task_id="task-a", status=TaskStatus.COMPLETED))
        context = _context(run)

        left = durable_recovery_fingerprint(
            context,
            {"task-a": {"shared_state": {"z": 1, "a": 2}}},
        )
        right = durable_recovery_fingerprint(
            context,
            {"task-a": {"shared_state": {"a": 2, "z": 1}}},
        )

        self.assertEqual(left, right)

    def test_dependency_graph_change_changes_fingerprint(self) -> None:
        task_a = make_task("a", task_id="task-a", status=TaskStatus.COMPLETED)
        task_b = make_task("b", task_id="task-b", status=TaskStatus.CREATED)
        task_c = make_task("c", task_id="task-c", status=TaskStatus.CREATED)

        linear = _running_run(
            task_a,
            make_task("b", task_id="task-b", depends_on=["a"]),
        )
        branched = WorkflowRun(
            id="run-branch",
            workflow_template_id="template-1",
            tasks=[task_a, task_b, task_c],
            dependency_graph=_branch_graph(["task-a", "task-b", "task-c"]),
        )
        branched.validate_dependency_graph()
        branched.ready()
        branched.start()

        task_results = {"task-a": {"shared_state": {"value": 1}}}
        linear_fingerprint = durable_recovery_fingerprint(_context(linear), task_results)
        branch_fingerprint = durable_recovery_fingerprint(_context(branched), task_results)

        self.assertNotEqual(linear_fingerprint, branch_fingerprint)

    def test_fingerprint_includes_unicode_content(self) -> None:
        run = _running_run(make_task("a", task_id="task-a", status=TaskStatus.COMPLETED))
        fingerprint = durable_recovery_fingerprint(
            _context(run),
            {"task-a": {"shared_state": {"greeting": "café"}}},
        )

        self.assertIn("café", fingerprint)


def _branch_graph(task_ids: list[str]) -> TaskDependencyGraph:
    graph = TaskDependencyGraph()
    for task_id in task_ids:
        graph.add_task(task_id)
    graph.add_dependency(task_ids[0], task_ids[1])
    graph.add_dependency(task_ids[0], task_ids[2])
    return graph


if __name__ == "__main__":
    unittest.main()
