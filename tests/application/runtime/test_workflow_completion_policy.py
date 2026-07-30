import unittest

from application.runtime.workflow_completion_policy import (
    WorkflowCompletionPolicy,
)

from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class WorkflowCompletionPolicyTests(unittest.TestCase):

    def test_empty_workflow_returns_completed(self):
        workflow_run = WorkflowRun(
            id="run-empty",
            workflow_template_id="template-1",
        )

        self.assertEqual(
            WorkflowCompletionPolicy.resolve(workflow_run),
            WorkflowStatus.COMPLETED,
        )

    def test_all_completed_returns_completed(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.COMPLETED),
            make_task("b", status=TaskStatus.COMPLETED),
        )

        self.assertEqual(
            WorkflowCompletionPolicy.resolve(workflow_run),
            WorkflowStatus.COMPLETED,
        )

    def test_completed_and_skipped_returns_completed(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.COMPLETED),
            make_task("b", status=TaskStatus.SKIPPED),
        )

        self.assertEqual(
            WorkflowCompletionPolicy.resolve(workflow_run),
            WorkflowStatus.COMPLETED,
        )

    def test_all_skipped_returns_completed(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.SKIPPED),
            make_task("b", status=TaskStatus.SKIPPED),
        )

        self.assertEqual(
            WorkflowCompletionPolicy.resolve(workflow_run),
            WorkflowStatus.COMPLETED,
        )

    def test_failed_and_all_terminal_returns_failed(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.FAILED),
            make_task("b", status=TaskStatus.SKIPPED),
        )

        self.assertEqual(
            WorkflowCompletionPolicy.resolve(workflow_run),
            WorkflowStatus.FAILED,
        )

    def test_failed_with_non_terminal_task_returns_none(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.FAILED),
            make_task("b", status=TaskStatus.WAITING),
        )

        self.assertIsNone(
            WorkflowCompletionPolicy.resolve(workflow_run),
        )

    def test_non_terminal_workflow_returns_none(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.RUNNING),
            make_task("b", status=TaskStatus.WAITING),
        )

        self.assertIsNone(
            WorkflowCompletionPolicy.resolve(workflow_run),
        )

    def test_cancelled_workflow_returns_cancelled(self):
        workflow_run = make_workflow_run(
            make_task("a", status=TaskStatus.COMPLETED),
        )
        workflow_run.cancel()

        self.assertEqual(
            WorkflowCompletionPolicy.resolve(workflow_run),
            WorkflowStatus.CANCELLED,
        )


if __name__ == "__main__":
    unittest.main()
