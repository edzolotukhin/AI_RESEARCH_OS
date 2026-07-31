from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.persistence.exceptions import CheckpointPersistenceError
from application.runtime.workflow_execution_audit import WorkflowExecutionAudit
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
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


if __name__ == "__main__":
    unittest.main()
