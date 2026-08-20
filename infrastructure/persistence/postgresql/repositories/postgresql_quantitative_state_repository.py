from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from application.ports.quantitative_state_repository import QuantitativeStateRecord
from infrastructure.persistence.postgresql.models.quantitative_state_model import QuantitativeStateModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLQuantitativeStateRepository:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None: self._sessions = session_factory

    @staticmethod
    def _record(model):
        return QuantitativeStateRecord(model.record_id, model.project_id, model.run_id, model.record_type, model.payload, model.payload_checksum, model.authority_fingerprint, model.dataset_version_id, model.parent_record_id, model.accepted, model.codec_version)

    def create(self, record: QuantitativeStateRecord) -> None:
        with self._sessions.session() as session:
            try:
                session.add(QuantitativeStateModel(**record.__dict__)); session.flush()
            except IntegrityError as exc:
                session.rollback(); raise ValueError("immutable Quantitative record already exists") from exc

    def get_for_project(self, record_id: str, *, project_id: str):
        with self._sessions.session() as session:
            model = session.scalars(select(QuantitativeStateModel).where(QuantitativeStateModel.record_id == record_id, QuantitativeStateModel.project_id == project_id)).first()
            return None if model is None else self._record(model)

    def list_for_run(self, run_id: str, *, project_id: str, record_type: str | None = None):
        with self._sessions.session() as session:
            query = select(QuantitativeStateModel).where(QuantitativeStateModel.run_id == run_id, QuantitativeStateModel.project_id == project_id)
            if record_type is not None: query = query.where(QuantitativeStateModel.record_type == record_type)
            return tuple(self._record(item) for item in session.scalars(query.order_by(QuantitativeStateModel.record_id)).all())
