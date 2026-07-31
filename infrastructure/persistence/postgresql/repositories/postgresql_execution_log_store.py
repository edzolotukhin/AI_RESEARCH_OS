from __future__ import annotations

from sqlalchemy import select

from application.persistence.records import ExecutionLogEntry
from application.ports.execution_log_store import ExecutionLogStore
from infrastructure.persistence.postgresql.mappers.execution_log_mapper import (
    execution_log_from_model,
    execution_log_to_model,
)
from infrastructure.persistence.postgresql.models.execution_log_model import (
    ExecutionLogEntryModel,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLExecutionLogStore:
    """Append-only PostgreSQL execution log adapter."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def append(self, entry: ExecutionLogEntry) -> None:
        with self._session_factory.session() as session:
            existing = session.scalars(
                select(ExecutionLogEntryModel).where(
                    ExecutionLogEntryModel.event_id == entry.event_id,
                )
            ).first()
            if existing is not None:
                return

            session.add(execution_log_to_model(entry))

    def list_for_run(self, run_id: str) -> list[ExecutionLogEntry]:
        with self._session_factory.session() as session:
            statement = (
                select(ExecutionLogEntryModel)
                .where(ExecutionLogEntryModel.run_id == run_id)
                .order_by(
                    ExecutionLogEntryModel.id,
                )
            )
            return [
                execution_log_from_model(model)
                for model in session.scalars(statement).all()
            ]

    def list_for_task(
        self,
        run_id: str,
        task_id: str,
    ) -> list[ExecutionLogEntry]:
        with self._session_factory.session() as session:
            statement = (
                select(ExecutionLogEntryModel)
                .where(
                    ExecutionLogEntryModel.run_id == run_id,
                    ExecutionLogEntryModel.task_id == task_id,
                )
                .order_by(
                    ExecutionLogEntryModel.id,
                )
            )
            return [
                execution_log_from_model(model)
                for model in session.scalars(statement).all()
            ]
