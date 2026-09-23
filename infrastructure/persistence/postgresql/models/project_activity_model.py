from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ProjectActivityModel(Base):
    __tablename__ = "project_activity"
    __table_args__ = (
        UniqueConstraint("project_id", "semantic_key", name="uq_project_activity_semantic"),
        CheckConstraint(
            "event_type IN ('PROJECT_CREATED', 'DESIGN_APPROVED', 'METHOD_ACTIVATED', "
            "'DESK_REPORT_DRAFT_CREATED', 'DESK_REVIEW_ATTENTION')",
            name="ck_project_activity_type",
        ),
        CheckConstraint("method IS NULL OR method IN ('DESK', 'QUANTITATIVE')", name="ck_project_activity_method"),
        CheckConstraint("verdict IS NULL OR verdict IN ('REVISE', 'REJECT')", name="ck_project_activity_verdict"),
        CheckConstraint("source_kind IN ('project', 'design', 'run', 'study', 'report', 'review')", name="ck_project_activity_source_kind"),
        CheckConstraint("event_version > 0", name="ck_project_activity_version"),
        CheckConstraint(
            "(event_type = 'DESK_REVIEW_ATTENTION') = (verdict IS NOT NULL)",
            name="ck_project_activity_attention_verdict",
        ),
        CheckConstraint(
            "event_type <> 'METHOD_ACTIVATED' OR (method IS NOT NULL AND run_id IS NOT NULL)",
            name="ck_project_activity_activation_shape",
        ),
        Index("ix_project_activity_project_order", "project_id", "occurred_at", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    semantic_key: Mapped[str] = mapped_column(String(192), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str | None] = mapped_column(String(16))
    run_id: Mapped[str | None] = mapped_column(String(64))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64))
    verdict: Mapped[str | None] = mapped_column(String(16))
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
