from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.postgresql.database import Base


class WorkflowTaskModel(Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "task_id",
            name="uq_workflow_tasks_run_task",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    executor_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    executor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    workflow_run: Mapped["WorkflowRunModel"] = relationship(
        "WorkflowRunModel",
        back_populates="tasks",
    )
