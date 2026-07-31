from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence.postgresql.database import Base


class WorkflowRunModel(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    task_results: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tasks: Mapped[list["WorkflowTaskModel"]] = relationship(
        "WorkflowTaskModel",
        back_populates="workflow_run",
        cascade="all, delete-orphan",
        order_by="WorkflowTaskModel.sort_order",
    )
