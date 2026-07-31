from __future__ import annotations

import copy

from application.persistence.exceptions import ConcurrentModificationError
from application.persistence.records import ExecutionLogEntry
from application.ports.execution_log_store import ExecutionLogStore


class InMemoryExecutionLogStore:
    """Append-only in-memory execution log adapter."""

    def __init__(self) -> None:
        self._entries: list[ExecutionLogEntry] = []
        self._event_ids: set[str] = set()

    def append(self, entry: ExecutionLogEntry) -> None:
        if entry.event_id in self._event_ids:
            return

        self._entries.append(copy.deepcopy(entry))
        self._event_ids.add(entry.event_id)

    def list_for_run(self, run_id: str) -> list[ExecutionLogEntry]:
        return [
            copy.deepcopy(entry)
            for entry in self._entries
            if entry.run_id == run_id
        ]

    def list_for_task(
        self,
        run_id: str,
        task_id: str,
    ) -> list[ExecutionLogEntry]:
        return [
            copy.deepcopy(entry)
            for entry in self._entries
            if entry.run_id == run_id and entry.task_id == task_id
        ]
