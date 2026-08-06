"""Tests for targeted research loop interrupt recovery."""

from __future__ import annotations

import unittest

from application.runtime.interrupted_task_recovery import recover_interrupted_running_tasks
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class InterruptedResearchLoopRecoveryTests(unittest.TestCase):
    def test_running_task_with_progress_checkpoint_is_requeued(self) -> None:
        task = make_task("readiness", task_id="task-readiness", status=TaskStatus.RUNNING)
        workflow_run = make_workflow_run(task)
        recover_interrupted_running_tasks(
            workflow_run,
            {
                task.id: {
                    "progress": True,
                    "shared_state": {"research_loop_state": {"research_loop_count": 1}},
                },
            },
        )
        self.assertEqual(task.status, TaskStatus.READY)

    def test_running_task_without_progress_is_failed(self) -> None:
        task = make_task("readiness", task_id="task-readiness", status=TaskStatus.RUNNING)
        workflow_run = make_workflow_run(task)
        recover_interrupted_running_tasks(workflow_run, {})
        self.assertEqual(task.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
