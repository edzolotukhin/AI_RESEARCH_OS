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
            "'DESK_REPORT_DRAFT_CREATED', 'DESK_REVIEW_ATTENTION', "
            "'QUANT_REVIEW_ATTENTION', 'QUANT_REVIEW_APPROVED', "
            "'QUANT_APPROVED_REVISION_CREATED', 'QUANT_PDF_GENERATED', "
            "'QUANT_PPTX_GENERATED', 'QUAL_RUN_CREATED', 'QUAL_SESSION_CREATED', 'QUAL_ARTIFACT_ACCEPTED', "
            "'QUAL_TRANSCRIPTION_STARTED', 'QUAL_TRANSCRIPTION_COMPLETED', 'QUAL_TRANSCRIPTION_FAILED', "
            "'QUAL_TRANSCRIPT_READY', 'QUAL_TRANSCRIPT_DOCX_GENERATED', 'QUAL_AUTHORITY_READY', "
            "'QUAL_ANALYSIS_CORPUS_FROZEN', 'QUAL_CODEBOOK_REVISION_CREATED', 'QUAL_AI_CODING_COMPLETED', "
            "'QUAL_CODING_REVISION_ACCEPTED', 'QUAL_THEMATIC_REVISION_CREATED', "
            "'QUAL_THEMATIC_ANALYSIS_ACCEPTED', 'QUAL_READY_FOR_FINDINGS', "
            "'QUAL_FINDINGS_REVISION_CREATED', 'QUAL_AI_FINDINGS_READY', 'QUAL_FINDING_ACCEPTED', "
            "'QUAL_INSIGHT_ACCEPTED', 'QUAL_REVIEW_REQUESTED', 'QUAL_REVIEW_CHANGES_REQUIRED', "
            "'QUAL_REVIEW_APPROVED', 'QUAL_APPROVED_REVISION_CREATED', 'QUAL_READY_FOR_DELIVERABLES', "
            "'QUAL_REPORT_DRAFT_CREATED', 'QUAL_REPORT_FINALIZED', 'QUAL_PDF_GENERATED', "
            "'QUAL_PPTX_GENERATED', 'QUAL_DELIVERABLE_READY')",
            name="ck_project_activity_type",
        ),
        CheckConstraint("method IS NULL OR method IN ('DESK', 'QUANTITATIVE', 'QUALITATIVE')", name="ck_project_activity_method"),
        CheckConstraint("verdict IS NULL OR verdict IN ('REVISE', 'REJECT')", name="ck_project_activity_verdict"),
        CheckConstraint("source_kind IN ('project', 'design', 'run', 'study', 'report', 'review', 'revision', 'deliverable', 'session', 'qual_artifact', 'transcription_job', 'transcript', 'transcript_export', 'qual_analysis_corpus', 'qual_codebook', 'qual_ai_proposal', 'qual_coding', 'qual_thematic_analysis', 'qual_finding', 'qual_insight', 'qual_post_analysis_revision', 'qual_review', 'qual_approved_revision', 'qual_report')", name="ck_project_activity_source_kind"),
        CheckConstraint("event_version > 0", name="ck_project_activity_version"),
        CheckConstraint(
            "(event_type IN ('DESK_REVIEW_ATTENTION', 'QUANT_REVIEW_ATTENTION')) = (verdict IS NOT NULL)",
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
