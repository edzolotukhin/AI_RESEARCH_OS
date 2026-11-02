from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.postgresql.database import Base


class AuthorityExtensionModel(Base):
    __tablename__ = "research_authority_extensions"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_authority_extensions_idempotency"),)
    extension_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    research_design_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_source_workflow_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_runs.id"), nullable=False)
    extension_workflow_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_runs.id"), nullable=False, unique=True)
    selected_information_need_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    gap_contract_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    terminal_reason: Mapped[str | None] = mapped_column(String(256))


class ComposedAuthorityModel(Base):
    __tablename__ = "composed_research_authorities"
    __table_args__ = (UniqueConstraint("composition_digest", name="uq_composed_authorities_digest"),)
    composition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    research_design_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_source_workflow_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_runs.id"), nullable=False)
    selected_information_need_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    composition_version: Mapped[str] = mapped_column(String(64), nullable=False)
    composition_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class ComposedAuthorityMemberModel(Base):
    __tablename__ = "composed_research_authority_members"
    composition_id: Mapped[str] = mapped_column(ForeignKey("composed_research_authorities.composition_id", ondelete="CASCADE"), primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), primary_key=True)
