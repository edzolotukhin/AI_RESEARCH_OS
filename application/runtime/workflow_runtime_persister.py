from __future__ import annotations

from typing import Any

from application.persistence.exceptions import CheckpointPersistenceError
from application.ports.workflow_runtime_checkpoint import WorkflowRuntimeCheckpoint
from application.runtime.durable_fingerprint import durable_recovery_fingerprint
from application.runtime.task_result_codec import (
    capture_task_progress,
    capture_task_result,
)
from application.runtime.workflow_execution_audit import WorkflowExecutionAudit
from application.execution.execution_budget_context import RUN_USAGE_SUMMARY_KEY
from application.scheduling.scheduling_result import SchedulingResult
from application.services.workflow_service import WorkflowService
from domain.value_objects.task_status import TaskStatus
from runtime.workflow_context import WorkflowContext

from application.execution.heartbeat import LeaseGuard


class WorkflowRuntimePersister(WorkflowRuntimeCheckpoint):
    """Persists WorkflowRun checkpoints and emits best-effort audit events."""

    def __init__(
        self,
        *,
        workflow_service: WorkflowService,
        audit: WorkflowExecutionAudit,
        run_id: str,
        initial_version: int = 0,
        task_results: dict[str, Any] | None = None,
        lease_guard: LeaseGuard | None = None,
    ) -> None:
        self._workflow_service = workflow_service
        self._audit = audit
        self._run_id = run_id
        self._expected_version = initial_version
        self._task_results = dict(task_results or {})
        self._last_fingerprint: str | None = None
        self._lease_guard = lease_guard

    @property
    def expected_version(self) -> int:
        return self._expected_version

    @property
    def task_results(self) -> dict[str, Any]:
        return dict(self._task_results)

    def on_workflow_started(self, context: WorkflowContext) -> None:
        self._checkpoint(context)
        self._audit.workflow_started(context.workflow_run.id)

    def on_scheduling(
        self,
        context: WorkflowContext,
        scheduling_result: SchedulingResult,
    ) -> None:
        self._checkpoint(context)
        self._audit.record_scheduling(context, scheduling_result)

    def on_task_running(self, context: WorkflowContext) -> None:
        self._checkpoint(context)
        task = context.current_task
        if task is not None:
            self._audit.task_started(context.workflow_run.id, task.id)

    def on_task_progress(self, context: WorkflowContext) -> None:
        task = context.current_task
        if task is None:
            return
        self._task_results[task.id] = capture_task_progress(context, task.id)
        self._checkpoint(context, critical=True)

    def on_task_finished(
        self,
        context: WorkflowContext,
        *,
        error: BaseException | None,
    ) -> None:
        task = context.current_task
        if task is not None and task.status == TaskStatus.COMPLETED:
            self._task_results[task.id] = capture_task_result(context, task.id)

        self._checkpoint(context, critical=True)
        self._audit.record_task_outcome(context, error=error)

    def on_workflow_finalized(
        self,
        context: WorkflowContext,
        *,
        error: BaseException | None,
    ) -> None:
        usage = context.execution_metadata.get(RUN_USAGE_SUMMARY_KEY)
        if usage is not None and hasattr(usage, "to_dict"):
            self._task_results["_run_usage_summary"] = usage.to_dict()
        elif isinstance(context.shared_state.get("run_usage_summary"), dict):
            self._task_results["_run_usage_summary"] = dict(
                context.shared_state["run_usage_summary"],
            )
        self._checkpoint(context, critical=True)
        self._audit.record_workflow_outcome(context)

    def _checkpoint(
        self,
        context: WorkflowContext,
        *,
        critical: bool = False,
    ) -> None:
        if self._lease_guard is not None:
            self._lease_guard.validate()
        fingerprint = durable_recovery_fingerprint(context, self._task_results)
        if fingerprint == self._last_fingerprint:
            return

        try:
            self._expected_version = self._workflow_service.save_workflow_run(
                context.workflow_run,
                expected_version=self._expected_version,
                task_results=self._task_results,
            )
        except Exception as exc:
            raise CheckpointPersistenceError(
                f"Failed to checkpoint WorkflowRun {self._run_id}."
            ) from exc

        self._last_fingerprint = fingerprint
