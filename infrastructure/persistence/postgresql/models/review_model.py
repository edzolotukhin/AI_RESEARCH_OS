from __future__ import annotations

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ReviewModel(Base):
    __tablename__ = "review_results"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_review_results_run_deduplication_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    research_design_id: Mapped[str] = mapped_column(String(36), nullable=False)
    report_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    review_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_dimensions: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    issues: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_method: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
