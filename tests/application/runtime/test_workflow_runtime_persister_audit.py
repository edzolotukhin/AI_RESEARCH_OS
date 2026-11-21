from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from application.persistence.exceptions import CheckpointPersistenceError
from application.report.exceptions import ReportError
from application.runtime.workflow_execution_audit import WorkflowExecutionAudit
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.exceptions.structured_output_error import StructuredOutputError
from application.quantitative.execution_diagnostics import SEMANTIC_LEDGER_KEY
from domain.project import Project
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.memory.in_memory_execution_log_store import (
    InMemoryExecutionLogStore,
)
from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class WorkflowRuntimePersisterAuditOrderingTests(unittest.TestCase):

    def setUp(self) -> None:
        self.workflow_run = make_workflow_run(make_task("a"))
        self.workflow_run.ready()
        self.workflow_run.start()
        self.context = WorkflowContext(
            workflow_run=self.workflow_run,
            project=Project(id="project-1", name="Project"),
        )
        self.audit = Mock(spec=WorkflowExecutionAudit)
        self.workflow_service = Mock()
        self.workflow_service.save_workflow_run.return_value = 1

    def test_checkpoint_failure_does_not_emit_workflow_started_audit(self) -> None:
        self.workflow_service.save_workflow_run.side_effect = RuntimeError("save failed")
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )

        with self.assertRaises(CheckpointPersistenceError):
            persister.on_workflow_started(self.context)

        self.audit.workflow_started.assert_not_called()

    def test_audit_append_failure_does_not_roll_back_checkpoint(self) -> None:
        call_order: list[str] = []
        store = Mock()
        store.append.side_effect = lambda entry: call_order.append("audit")

        def save(*args, **kwargs):
            call_order.append("save")
            return 1

        self.workflow_service.save_workflow_run.side_effect = save
        audit = WorkflowExecutionAudit(store)

        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )
        persister.on_workflow_started(self.context)

        self.assertEqual(call_order, ["save", "audit"])
        self.workflow_service.save_workflow_run.assert_called_once()

    def test_final_checkpoint_contains_semantic_ledger(self) -> None:
        self.context.shared_state[SEMANTIC_LEDGER_KEY] = [
            {"stage": "QI", "status": "COMPLETED"}
        ]
        persisted = {}

        def save(run, expected_version, **kwargs):
            persisted.update(kwargs["task_results"])
            return expected_version + 1

        self.workflow_service.save_workflow_run.side_effect = save
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )
        persister.on_workflow_finalized(self.context, error=None)
        self.assertEqual(
            [{"stage": "QI", "status": "COMPLETED"}],
            persisted[SEMANTIC_LEDGER_KEY],
        )

    def test_failed_report_task_persists_only_bounded_report_diagnostics(self) -> None:
        task = self.workflow_run.tasks[0]
        task.definition_id = "task-write-report"
        self.context.current_task = task
        task.ready()
        task.start()
        task.fail()
        self.context.shared_state.update({
            "report_repair_diagnostics": {"version": 1, "attempts": []},
            "report_generation_diagnostics": {"phase": "coverage_validation"},
            "REPORT_PROSE": "must not persist",
            "arbitrary_shared_state": "must not persist",
        })
        persisted = {}

        def save(run, expected_version, **kwargs):
            persisted.update(kwargs["task_results"])
            return expected_version + 1

        self.workflow_service.save_workflow_run.side_effect = save
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )

        persister.on_task_finished(self.context, error=ReportError("failed"))

        snapshot = persisted[task.id]
        self.assertEqual(self.context.workflow_run.status, WorkflowStatus.RUNNING)
        self.assertEqual(
            snapshot["shared_state"]["report_repair_diagnostics"],
            {"version": 1, "attempts": []},
        )
        self.assertIn("report_generation_diagnostics", snapshot["shared_state"])
        self.assertNotIn("REPORT_PROSE", snapshot["shared_state"])
        self.assertNotIn("arbitrary_shared_state", snapshot["shared_state"])

    def test_failed_review_task_persists_only_bounded_review_diagnostics(self) -> None:
        task = self.workflow_run.tasks[0]
        task.definition_id = "task-review-report"
        self.context.current_task = task
        task.ready()
        task.start()
        task.fail()
        self.context.shared_state.update({
            "review_diagnostics": {
                "version": 1,
                "phase": "semantic_review",
                "status": "failed",
                "category": "semantic_parse_failure",
            },
            "review_prose": "must not persist",
            "arbitrary_shared_state": "must not persist",
        })
        persisted = {}

        def save(run, expected_version, **kwargs):
            persisted.update(kwargs["task_results"])
            return expected_version + 1

        self.workflow_service.save_workflow_run.side_effect = save
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )

        persister.on_task_finished(self.context, error=RuntimeError("review failed"))

        snapshot = persisted[task.id]
        self.assertEqual(snapshot["shared_state"]["review_diagnostics"]["status"], "failed")
        self.assertNotIn("review_prose", snapshot["shared_state"])
        self.assertNotIn("arbitrary_shared_state", snapshot["shared_state"])

    def test_failed_design_task_persists_only_bounded_design_diagnostic(self) -> None:
        task = self.workflow_run.tasks[0]
        task.definition_id = "task-generate-design"
        task.executor_id = "design_generation"
        self.context.current_task = task
        task.ready()
        task.start()
        task.fail()
        self.context.shared_state.update({
            "design_generation": {
                "version": 1,
                "status": "failed",
                "category": "provider_model_execution_failure",
                "project_id": "project-1",
                "workflow_run_id": "run-1",
                "input_fingerprint": "bounded-fingerprint",
            },
            "arbitrary_shared_state": "must not persist",
        })
        persisted = {}

        def save(run, expected_version, **kwargs):
            persisted.update(kwargs["task_results"])
            return expected_version + 1

        self.workflow_service.save_workflow_run.side_effect = save
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )

        persister.on_task_finished(self.context, error=RuntimeError("private"))

        snapshot = persisted[task.id]
        self.assertEqual(
            snapshot["shared_state"]["design_generation"]["category"],
            "provider_model_execution_failure",
        )
        self.assertNotIn("arbitrary_shared_state", snapshot["shared_state"])

    def test_unrelated_failed_task_cannot_persist_arbitrary_shared_state(self) -> None:
        task = self.workflow_run.tasks[0]
        self.context.current_task = task
        task.ready()
        task.start()
        task.fail()
        self.context.shared_state["arbitrary_shared_state"] = "must not persist"
        persisted = {}

        def save(run, expected_version, **kwargs):
            persisted.update(kwargs["task_results"])
            return expected_version + 1

        self.workflow_service.save_workflow_run.side_effect = save
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )

        persister.on_task_finished(self.context, error=RuntimeError("private"))

        self.assertNotIn(task.id, persisted)

    def test_failed_search_persists_all_safe_diagnostics(self) -> None:
        task = self.workflow_run.tasks[0]
        self.context.current_task = task
        task.definition_id = "task-collect-evidence"
        task.ready()
        task.start()
        task.fail()
        self.context.shared_state["source_acquisition"] = {
            "candidate_count_raw": 3,
            "acquired_count": 1,
            "failed_count": 2,
            "selection_decisions": [{"action": "fetch_failed", "reason": "http_error"}],
        }
        self.context.shared_state["research_product_outcome"] = {
            "outcome": "FAILED",
            "reason": "SourceAcquisitionError",
        }
        self.context.shared_state["research_funnel_v1"] = {
            "events": [{"phase": "acquisition", "status": "failed"}],
        }
        self.context.shared_state["provider_payload"] = {"raw": "must not persist"}
        self.context.shared_state["credentials"] = "must not persist"
        persisted = {}

        def save(run, expected_version, **kwargs):
            persisted.update(kwargs["task_results"])
            return expected_version + 1

        self.workflow_service.save_workflow_run.side_effect = save
        persister = WorkflowRuntimePersister(
            workflow_service=self.workflow_service,
            audit=self.audit,
            run_id=self.workflow_run.id,
            initial_version=0,
        )
        persister.on_task_finished(self.context, error=RuntimeError("source minimum"))

        snapshot = persisted[task.id]
        self.assertEqual(snapshot["shared_state"]["source_acquisition"]["acquired_count"], 1)
        self.assertEqual(
            snapshot["shared_state"]["research_product_outcome"]["outcome"],
            "FAILED",
        )
        self.assertEqual(
            snapshot["shared_state"]["research_funnel_v1"]["events"][0]["phase"],
            "acquisition",
        )
        self.assertNotIn("provider_payload", snapshot["shared_state"])
        self.assertNotIn("credentials", snapshot["shared_state"])


class WorkflowExecutionAuditResumeTests(unittest.TestCase):

    def test_duplicate_same_version_resume_is_idempotent(self) -> None:
        store = InMemoryExecutionLogStore()
        audit = WorkflowExecutionAudit(store)

        audit.workflow_resumed("run-resume", resume_version=4)
        audit.workflow_resumed("run-resume", resume_version=4)

        resumed = [
            entry
            for entry in store.list_for_run("run-resume")
            if entry.event_type == "workflow_resumed"
        ]
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0].event_id, "run-resume:workflow_resumed:4")

    def test_resume_after_version_change_creates_new_event(self) -> None:
        store = InMemoryExecutionLogStore()
        audit = WorkflowExecutionAudit(store)

        audit.workflow_resumed("run-resume", resume_version=4)
        audit.workflow_resumed("run-resume", resume_version=5)

        resumed = [
            entry.event_id
            for entry in store.list_for_run("run-resume")
            if entry.event_type == "workflow_resumed"
        ]
        self.assertEqual(
            resumed,
            ["run-resume:workflow_resumed:4", "run-resume:workflow_resumed:5"],
        )


class StructuredOutputContractAuditDiagnosticsTests(unittest.TestCase):
    def test_contract_failure_persists_safe_typed_diagnostic(self) -> None:
        store = InMemoryExecutionLogStore()
        audit = WorkflowExecutionAudit(store)
        context = SimpleNamespace(
            workflow_run=SimpleNamespace(id="run-contract"),
            current_task=SimpleNamespace(id="task-design", status=TaskStatus.FAILED),
        )
        error = StructuredOutputError(
            "contract failure",
            stage="contract",
            contract_validation_error="Duplicate research question id: secret-id",
            contract_validation_code="duplicate_research_question_id",
            contract_validation_reason="duplicate research question id",
        )

        audit.record_task_outcome(context, error=error)
        entry = store.list_for_run("run-contract")[0]

        self.assertEqual(entry.payload["reason"], "StructuredOutputError")
        self.assertEqual(
            entry.payload["diagnostic"],
            {
                "diagnostic_code": "duplicate_research_question_id",
                "safe_reason": "duplicate research question id",
            },
        )
        self.assertNotIn("secret-id", repr(entry.payload))

    def test_unknown_contract_failure_uses_generic_diagnostic(self) -> None:
        store = InMemoryExecutionLogStore()
        audit = WorkflowExecutionAudit(store)
        context = SimpleNamespace(
            workflow_run=SimpleNamespace(id="run-generic"),
            current_task=SimpleNamespace(id="task-design", status=TaskStatus.FAILED),
        )
        error = StructuredOutputError(
            "contract failure",
            stage="contract",
            contract_validation_error="brief secret content",
        )

        audit.record_task_outcome(context, error=error)
        diagnostic = store.list_for_run("run-generic")[0].payload["diagnostic"]
        self.assertEqual(diagnostic["diagnostic_code"], "planner_payload_contract_invalid")
        self.assertEqual(diagnostic["safe_reason"], "planner payload failed the contract")


if __name__ == "__main__":
    unittest.main()
