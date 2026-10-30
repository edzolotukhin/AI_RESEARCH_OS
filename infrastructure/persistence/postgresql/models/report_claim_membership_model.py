from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ReportClaimMembershipModel(Base):
    """Immutable association of one Report revision with Claim authority."""

    __tablename__ = "report_revision_claims"
    __table_args__ = (
        CheckConstraint("report_revision > 0", name="ck_report_revision_claims_positive_revision"),
        Index("ix_report_revision_claims_report_revision", "report_id", "report_revision"),
        Index("ix_report_revision_claims_claim", "report_claim_id"),
    )

    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reports.id", ondelete="RESTRICT"), primary_key=True,
    )
    report_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_claims.id", ondelete="RESTRICT"), primary_key=True,
    )
