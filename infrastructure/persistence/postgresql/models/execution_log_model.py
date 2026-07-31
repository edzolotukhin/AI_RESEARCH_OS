from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ExecutionLogEntryModel(Base):
    __tablename__ = "execution_log_entries"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_execution_log_entries_event_id"),
        Index("ix_execution_log_entries_run_id", "run_id"),
        Index("ix_execution_log_entries_run_id_task_id", "run_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
