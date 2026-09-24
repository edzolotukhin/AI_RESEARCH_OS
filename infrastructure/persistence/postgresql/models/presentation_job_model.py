"""Durable PPTX job metadata; completed content uses the shared deliverable table."""

from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.postgresql.database import Base


class PresentationJobModel(Base):
    __tablename__ = "presentation_jobs"
    __table_args__ = (
        Index("ix_presentation_jobs_claim", "state", "lease_until", "created_at"),
        UniqueConstraint("project_id", "method", "source_id", "source_version",
                         "template_version", "renderer_version", name="uq_presentation_job_identity"),
        CheckConstraint("state IN ('pending', 'processing', 'completed', 'failed')",
                        name="ck_presentation_job_state"),
        CheckConstraint("attempts >= 0", name="ck_presentation_job_attempts"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    study_id: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(192), nullable=False)
    status_snapshot: Mapped[str] = mapped_column(String(96), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_deliverable_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("pdf_deliverables.id"))
    failure_code: Mapped[str | None] = mapped_column(String(64))
