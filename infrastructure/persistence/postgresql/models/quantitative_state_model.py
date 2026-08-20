from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class QuantitativeStateModel(Base):
    __tablename__ = "quantitative_state_records"
    __table_args__ = (UniqueConstraint("project_id", "record_id", name="uq_quantitative_state_project_record"),)

    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    dataset_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    parent_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    authority_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    codec_version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
