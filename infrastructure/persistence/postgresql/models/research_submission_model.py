from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ResearchSubmissionModel(Base):
    __tablename__ = "research_submissions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_research_submissions_project_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
