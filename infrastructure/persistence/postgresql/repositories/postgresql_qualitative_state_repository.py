from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from application.ports.qualitative_state_repository import QualitativeStateRecord
from infrastructure.persistence.postgresql.models.qualitative_state_model import QualitativeStateModel


class PostgreSQLQualitativeStateRepository:
    def __init__(self, sessions): self._sessions = sessions
    @staticmethod
    def _record(model):
        payload = dict(model.payload)
        if model.private_bytes is not None: payload["private_bytes"] = bytes(model.private_bytes)
        return QualitativeStateRecord(model.record_id, model.project_id, model.run_id,
                                      model.record_type, payload, model.checksum, model.parent_record_id)
    def create(self, record):
        payload = dict(record.payload); private_bytes = payload.pop("private_bytes", None)
        with self._sessions.session() as session:
            try:
                session.add(QualitativeStateModel(project_id=record.project_id, record_id=record.record_id,
                    run_id=record.run_id, record_type=record.record_type, parent_record_id=record.parent_record_id,
                    checksum=record.checksum, payload=payload, private_bytes=private_bytes)); session.flush()
            except IntegrityError as exc:
                session.rollback(); raise ValueError("immutable Qualitative record already exists") from exc
    def get_for_project(self, record_id, *, project_id):
        with self._sessions.session() as session:
            model = session.scalars(select(QualitativeStateModel).where(
                QualitativeStateModel.record_id == record_id, QualitativeStateModel.project_id == project_id)).first()
            return None if model is None else self._record(model)
    def list_for_run(self, run_id, *, project_id, record_type=None):
        with self._sessions.session() as session:
            query = select(QualitativeStateModel).where(QualitativeStateModel.run_id == run_id,
                                                        QualitativeStateModel.project_id == project_id)
            if record_type: query = query.where(QualitativeStateModel.record_type == record_type)
            return tuple(self._record(x) for x in session.scalars(query.order_by(QualitativeStateModel.record_id)).all())
    def list_by_type(self, record_type):
        with self._sessions.session() as session:
            query = select(QualitativeStateModel).where(QualitativeStateModel.record_type == record_type)
            return tuple(self._record(x) for x in session.scalars(query.order_by(QualitativeStateModel.record_id)).all())
