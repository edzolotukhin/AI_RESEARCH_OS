from __future__ import annotations

from typing import Protocol

from application.persistence.records import ExecutionLogEntry


class ExecutionLogStore(Protocol):
    """
    Append-only persistence port for execution audit events.

    Not a CRUD repository: entries are never updated or deleted.
    """

    def append(self, entry: ExecutionLogEntry) -> None:
        """
        Append a single log entry.

        Implementations must treat duplicate event_id values as idempotent no-ops.
        """
        ...

    def list_for_run(self, run_id: str) -> list[ExecutionLogEntry]:
        """Return log entries for a run in append order."""
        ...

    def list_for_task(
        self,
        run_id: str,
        task_id: str,
    ) -> list[ExecutionLogEntry]:
        """Return log entries for a specific task within a run."""
        ...
