from __future__ import annotations

from application.persistence.records import ExecutionLogEntry
from infrastructure.persistence.postgresql.models.execution_log_model import (
    ExecutionLogEntryModel,
)


def execution_log_to_model(entry: ExecutionLogEntry) -> ExecutionLogEntryModel:
    return ExecutionLogEntryModel(
        event_id=entry.event_id,
        run_id=entry.run_id,
        task_id=entry.task_id,
        event_type=entry.event_type,
        timestamp=entry.timestamp,
        payload=dict(entry.payload),
    )


def execution_log_from_model(model: ExecutionLogEntryModel) -> ExecutionLogEntry:
    return ExecutionLogEntry(
        event_id=model.event_id,
        run_id=model.run_id,
        task_id=model.task_id,
        event_type=model.event_type,
        timestamp=model.timestamp,
        payload=dict(model.payload or {}),
    )
