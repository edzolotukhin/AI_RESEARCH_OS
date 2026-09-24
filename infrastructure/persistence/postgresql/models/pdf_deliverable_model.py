"""Completed PDF and private bytes share one PostgreSQL transaction."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.postgresql.database import Base


class PdfDeliverableModel(Base):
    __tablename__ = "pdf_deliverables"
    __table_args__ = (
        UniqueConstraint("project_id", "method", "source_id", "source_version", "renderer_version",
                         name="uq_pdf_deliverable_source_renderer"),
        CheckConstraint("byte_size > 0 AND byte_size <= 5000000", name="ck_pdf_deliverable_size"),
        CheckConstraint("method IN ('DESK', 'QUANTITATIVE')", name="ck_pdf_deliverable_method"),
        CheckConstraint("state = 'completed' AND media_type = 'application/pdf'", name="ck_pdf_deliverable_state"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    study_id: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[str] = mapped_column(String(192), nullable=False)
    status_snapshot: Mapped[str] = mapped_column(String(96), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(160), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
