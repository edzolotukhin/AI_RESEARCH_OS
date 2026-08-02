from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class SourceModel(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "canonical_url",
            name="uq_sources_project_canonical_url",
        ),
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
