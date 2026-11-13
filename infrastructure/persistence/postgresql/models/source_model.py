from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class SourceModel(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "terminal_resource_key", "content_revision", "extraction_revision",
            name="uq_sources_resource_revision",
        ),
        UniqueConstraint("project_id", "terminal_resource_key", "raw_checksum_kind", "raw_content_checksum", "extraction_revision", name="uq_sources_snapshot"),
        CheckConstraint("content_revision > 0", name="ck_source_revision_positive"),
        Index("ix_sources_terminal_latest", "project_id", "terminal_resource_key", "content_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id"),
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retrieved_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    query_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    research_question_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    information_need_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    workflow_run_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    research_design_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    retrieval_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    terminal_resource_key: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_content_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_checksum_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_revision: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceAcquisitionPathModel(Base):
    __tablename__ = "source_acquisition_paths"
    __table_args__ = (UniqueConstraint("workflow_run_id", "path_digest", "source_id", name="uq_source_path_observation"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    path_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    landing_url: Mapped[str] = mapped_column(Text, nullable=False)
    terminal_url: Mapped[str] = mapped_column(Text, nullable=False)
    navigation_chain: Mapped[list] = mapped_column(JSON, nullable=False)
    diagnostics: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
