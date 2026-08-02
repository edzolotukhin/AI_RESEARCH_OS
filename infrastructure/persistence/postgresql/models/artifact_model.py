from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "deduplication_key",
            name="uq_artifacts_run_deduplication_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="Draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content_checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    report_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
