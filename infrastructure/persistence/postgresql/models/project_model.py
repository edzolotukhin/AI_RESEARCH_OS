from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.postgresql.database import Base


class ProjectModel(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "selected_methods IS NULL OR jsonb_typeof(selected_methods) = 'array'",
            name="ck_projects_selected_methods_array",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    client_request: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    qualification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    research_design: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    selected_methods: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    planning_design: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    planning_design_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planning_design_input_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    planning_design_approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    planning_design_approved_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
