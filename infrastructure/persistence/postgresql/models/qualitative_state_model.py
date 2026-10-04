from sqlalchemy import ForeignKey, JSON, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column
from infrastructure.persistence.postgresql.database import Base


class QualitativeStateModel(Base):
    __tablename__ = "qualitative_state_records"
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    private_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
