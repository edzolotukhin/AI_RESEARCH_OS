from __future__ import annotations

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ReportModel(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_reports_run_deduplication_key",
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
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    sections: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    generation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    insight_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    citation_registry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False, default=1)
    previous_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
