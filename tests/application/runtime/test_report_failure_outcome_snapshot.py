from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.report.exceptions import ReportError
from application.research_quality.readiness_result_codec import extract_research_product_outcome
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from domain.project import Project
from runtime.workflow_context import WorkflowContext
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class ReportFailureOutcomeSnapshotTests(unittest.TestCase):
    def test_failed_report_snapshot_retains_outcome_and_only_allowed_state(self):
        workflow_run = make_workflow_run(make_task("task-write-report"))
        workflow_run.ready()
        workflow_run.start()
        task = workflow_run.tasks[0]
        task.definition_id = "task-write-report"
        task.ready()
        task.start()
        task.fail()
        context = WorkflowContext(
            workflow_run=workflow_run,
            project=Project(id="project-1", name="Project"),
        )
        context.current_task = task
        context.shared_state.update({
            "report_generation_diagnostics": {"phase": "claim_generation"},
            "research_product_outcome": {"outcome": "FAILED", "reason": "ReportError"},
            "unrelated": "must not persist",
        })
        persisted = {}
        service = Mock()
        service.save_workflow_run.side_effect = lambda run, expected_version, **kwargs: (
            persisted.update(kwargs["task_results"]) or expected_version + 1
        )
        persister = WorkflowRuntimePersister(
            workflow_service=service, audit=Mock(), run_id=workflow_run.id,
        )
        persister.on_task_finished(context, error=ReportError("failed"))

        snapshot = persisted[task.id]
        self.assertIn("report_generation_diagnostics", snapshot["shared_state"])
        self.assertEqual(snapshot["shared_state"]["research_product_outcome"]["outcome"], "FAILED")
        self.assertEqual(extract_research_product_outcome(persisted)["outcome"], "FAILED")
        self.assertNotIn("unrelated", snapshot["shared_state"])


if __name__ == "__main__":
    unittest.main()
