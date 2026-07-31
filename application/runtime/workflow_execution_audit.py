from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from application.persistence.records import ExecutionLogEntry
from application.ports.execution_log_store import ExecutionLogStore
from application.scheduling.scheduling_result import SchedulingResult
from domain.value_objects.task_status import TaskStatus
from runtime.workflow_context import WorkflowContext


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowExecutionAudit:
    """Best-effort append-only audit trail for durable workflow execution."""

    def __init__(self, execution_log_store: ExecutionLogStore) -> None:
        self._execution_log_store = execution_log_store

    def append(
        self,
        *,
        event_id: str,
        run_id: str,
        event_type: str,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._execution_log_store.append(
                ExecutionLogEntry(
                    event_id=event_id,
                    run_id=run_id,
                    event_type=event_type,
                    timestamp=_utc_timestamp(),
                    task_id=task_id,
                    payload=payload or {},
                )
            )
        except Exception:
            # Audit append is best-effort and must not undo a saved aggregate.
            return

    def workflow_created(self, run_id: str) -> None:
        self.append(
            event_id=f"{run_id}:workflow_created",
            run_id=run_id,
            event_type="workflow_created",
        )

    def workflow_started(self, run_id: str) -> None:
        self.append(
            event_id=f"{run_id}:workflow_started",
            run_id=run_id,
            event_type="workflow_started",
        )

    def workflow_resumed(self, run_id: str, *, resume_version: int) -> None:
        self.append(
            event_id=f"{run_id}:workflow_resumed:{resume_version}",
            run_id=run_id,
            event_type="workflow_resumed",
            payload={"resume_version": resume_version},
        )

    def task_started(self, run_id: str, task_id: str) -> None:
        self.append(
            event_id=f"{run_id}:task_started:{task_id}",
            run_id=run_id,
            event_type="task_started",
            task_id=task_id,
        )

    def task_completed(self, run_id: str, task_id: str) -> None:
        self.append(
            event_id=f"{run_id}:task_completed:{task_id}",
            run_id=run_id,
            event_type="task_completed",
            task_id=task_id,
        )

    def task_failed(
        self,
        run_id: str,
        task_id: str,
        *,
        reason: str | None = None,
    ) -> None:
        payload = {"reason": reason} if reason else {}
        self.append(
            event_id=f"{run_id}:task_failed:{task_id}",
            run_id=run_id,
            event_type="task_failed",
            task_id=task_id,
            payload=payload,
        )

    def task_skipped(self, run_id: str, task_id: str) -> None:
        self.append(
            event_id=f"{run_id}:task_skipped:{task_id}",
            run_id=run_id,
            event_type="task_skipped",
            task_id=task_id,
        )

    def workflow_completed(self, run_id: str) -> None:
        self.append(
            event_id=f"{run_id}:workflow_completed",
            run_id=run_id,
            event_type="workflow_completed",
        )

    def workflow_failed(self, run_id: str) -> None:
        self.append(
            event_id=f"{run_id}:workflow_failed",
            run_id=run_id,
            event_type="workflow_failed",
        )

    def workflow_cancelled(self, run_id: str) -> None:
        self.append(
            event_id=f"{run_id}:workflow_cancelled",
            run_id=run_id,
            event_type="workflow_cancelled",
        )

    def record_scheduling(
        self,
        context: WorkflowContext,
        scheduling_result: SchedulingResult,
    ) -> None:
        run_id = context.workflow_run.id
        for task_id in scheduling_result.skipped_task_ids:
            self.task_skipped(run_id, task_id)

    def record_task_outcome(
        self,
        context: WorkflowContext,
        *,
        error: BaseException | None,
        recovery_reason: str | None = None,
    ) -> None:
        task = context.current_task
        if task is None:
            return

        run_id = context.workflow_run.id
        if task.status == TaskStatus.COMPLETED:
            self.task_completed(run_id, task.id)
            return

        if task.status == TaskStatus.FAILED:
            reason = recovery_reason
            if error is not None and reason is None:
                reason = type(error).__name__
            self.task_failed(run_id, task.id, reason=reason)
            return

        if task.status == TaskStatus.SKIPPED:
            self.task_skipped(run_id, task.id)

    def record_workflow_outcome(self, context: WorkflowContext) -> None:
        run_id = context.workflow_run.id
        status = context.workflow_run.status

        if status.value == "completed":
            self.workflow_completed(run_id)
        elif status.value == "failed":
            self.workflow_failed(run_id)
        elif status.value == "cancelled":
            self.workflow_cancelled(run_id)
