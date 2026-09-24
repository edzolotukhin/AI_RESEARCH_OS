"""PostgreSQL-backed private immutable PDF storage."""

from __future__ import annotations

import hashlib
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from application.deliverables.contracts import PdfDeliverable
from infrastructure.persistence.postgresql.models.pdf_deliverable_model import PdfDeliverableModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLPdfStore:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self._sessions = sessions

    @staticmethod
    def _record(model: PdfDeliverableModel) -> PdfDeliverable:
        return PdfDeliverable(**{name: getattr(model, name) for name in PdfDeliverable.__dataclass_fields__})

    def get(self, deliverable_id: str) -> tuple[PdfDeliverable, bytes] | None:
        with self._sessions.session() as session:
            model = session.get(PdfDeliverableModel, deliverable_id)
            return (self._record(model), bytes(model.content)) if model else None

    def find(self, *, project_id: str, method: str, source_id: str,
             source_version: str, renderer_version: str) -> PdfDeliverable | None:
        with self._sessions.session() as session:
            model = session.scalars(select(PdfDeliverableModel).where(
                PdfDeliverableModel.project_id == project_id,
                PdfDeliverableModel.method == method,
                PdfDeliverableModel.source_id == source_id,
                PdfDeliverableModel.source_version == source_version,
                PdfDeliverableModel.renderer_version == renderer_version,
            )).one_or_none()
            return self._record(model) if model else None

    def complete(self, record: PdfDeliverable, data: bytes) -> PdfDeliverable:
        if (not data.startswith(b"%PDF-") or len(data) != record.byte_size
                or not 0 < len(data) <= 5_000_000
                or hashlib.sha256(data).hexdigest() != record.checksum):
            raise ValueError("invalid completed PDF content")
        values = {name: getattr(record, name) for name in PdfDeliverable.__dataclass_fields__}
        values["content"] = data
        with self._sessions.session() as session:
            session.execute(insert(PdfDeliverableModel).values(**values).on_conflict_do_nothing(
                constraint="uq_pdf_deliverable_source_renderer"))
        found = self.find(project_id=record.project_id, method=record.method,
                          source_id=record.source_id, source_version=record.source_version,
                          renderer_version=record.renderer_version)
        if found is None:
            raise RuntimeError("completed PDF metadata unavailable")
        return found
