from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class EvidenceModel(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_evidence_run_deduplication_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id"),
        index=True,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sources.id"),
        index=True,
    )
    source_content_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    research_design_id: Mapped[str] = mapped_column(String(36), nullable=False)
    research_question_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    information_need_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    source_locator: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    quality_signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
