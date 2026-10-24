from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ReportClaimModel(Base):
    __tablename__ = "report_claims"
    __table_args__ = (
        UniqueConstraint("report_id", "report_revision", "id", name="uq_report_claims_revision_identity"),
        Index("ix_report_claims_report_revision", "report_id", "report_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("reports.id", ondelete="RESTRICT"), nullable=False)
    report_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    source_workflow_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    report_workflow_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    research_design_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    authority_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
