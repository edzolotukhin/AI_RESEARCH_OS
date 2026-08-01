from __future__ import annotations

from application.persistence.records import ExecutionLogEntry
from application.ports.execution_log_store import ExecutionLogStore


class ExecutionLogService:
    """Read-only query service for append-only workflow execution logs."""

    def __init__(self, *, execution_log_store: ExecutionLogStore) -> None:
        self._execution_log_store = execution_log_store

    def list_logs_for_run(self, run_id: str) -> list[ExecutionLogEntry]:
        return self._execution_log_store.list_for_run(run_id)

    def list_logs_for_task(
        self,
        run_id: str,
        task_id: str,
    ) -> list[ExecutionLogEntry]:
        return self._execution_log_store.list_for_task(run_id, task_id)
