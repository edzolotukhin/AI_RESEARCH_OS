"""DB-polled presentation outbox with leases and idempotent scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from application.deliverables.presentation_jobs import PresentationJob
from infrastructure.persistence.postgresql.models.presentation_job_model import PresentationJobModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLPresentationJobs:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self._sessions = sessions

    @staticmethod
    def _record(model: PresentationJobModel | None) -> PresentationJob | None:
        return (PresentationJob(**{key: getattr(model, key) for key in PresentationJob.__dataclass_fields__})
                if model is not None else None)

    def find(self, *, project_id: str, method: str, source_id: str, source_version: str,
             template_version: str, renderer_version: str) -> PresentationJob | None:
        with self._sessions.session() as session:
            model = session.scalars(select(PresentationJobModel).where(
                PresentationJobModel.project_id == project_id,
                PresentationJobModel.method == method,
                PresentationJobModel.source_id == source_id,
                PresentationJobModel.source_version == source_version,
                PresentationJobModel.template_version == template_version,
                PresentationJobModel.renderer_version == renderer_version,
            )).one_or_none()
            return self._record(model)

    def schedule(self, *, project_id: str, method: str, run_id: str, study_id: str | None,
                 source_id: str, source_version: str, status_snapshot: str,
                 template_version: str, renderer_version: str) -> PresentationJob:
        now = datetime.now(timezone.utc)
        values = dict(id=str(uuid4()), project_id=project_id, method=method, run_id=run_id,
                      study_id=study_id, source_id=source_id, source_version=source_version,
                      status_snapshot=status_snapshot, template_version=template_version,
                      renderer_version=renderer_version, state="pending", attempts=0,
                      lease_until=None, claimed_by=None, created_at=now, updated_at=now,
                      completed_deliverable_id=None, failure_code=None)
        with self._sessions.session() as session:
            session.execute(insert(PresentationJobModel).values(**values).on_conflict_do_nothing(
                constraint="uq_presentation_job_identity"))
        found = self.find(project_id=project_id, method=method, source_id=source_id,
                          source_version=source_version, template_version=template_version,
                          renderer_version=renderer_version)
        if found is None:
            raise RuntimeError("presentation job unavailable after scheduling")
        return found

    def retry(self, job_id: str) -> PresentationJob | None:
        with self._sessions.session() as session:
            model = session.get(PresentationJobModel, job_id, with_for_update=True)
            if model is None:
                return None
            if model.state == "failed" and model.attempts < 3:
                model.state = "pending"
                model.failure_code = None
                model.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._record(model)

    def claim_next(self, worker_id: str, *, lease_seconds: int = 120) -> PresentationJob | None:
        now = datetime.now(timezone.utc)
        with self._sessions.session() as session:
            session.execute(update(PresentationJobModel).where(
                PresentationJobModel.state == "processing",
                PresentationJobModel.lease_until < now,
                PresentationJobModel.attempts >= 3,
            ).values(state="failed", claimed_by=None, lease_until=None,
                     failure_code="lease_exhausted", updated_at=now))
            model = session.scalars(select(PresentationJobModel).where(or_(
                PresentationJobModel.state == "pending",
                (PresentationJobModel.state == "processing") &
                (PresentationJobModel.lease_until < now) &
                (PresentationJobModel.attempts < 3),
            )).order_by(PresentationJobModel.created_at, PresentationJobModel.id)
                .with_for_update(skip_locked=True)).first()
            if model is None:
                return None
            model.state = "processing"
            model.attempts += 1
            model.claimed_by = worker_id
            model.lease_until = now + timedelta(seconds=lease_seconds)
            model.updated_at = now
            session.flush()
            return self._record(model)

    def complete(self, job_id: str, worker_id: str, deliverable_id: str) -> bool:
        with self._sessions.session() as session:
            result = session.execute(update(PresentationJobModel).where(
                PresentationJobModel.id == job_id,
                PresentationJobModel.state == "processing",
                PresentationJobModel.claimed_by == worker_id,
                PresentationJobModel.lease_until > datetime.now(timezone.utc),
            ).values(state="completed", completed_deliverable_id=deliverable_id,
                     claimed_by=None, lease_until=None, failure_code=None,
                     updated_at=datetime.now(timezone.utc)))
            return result.rowcount == 1

    def fail(self, job_id: str, worker_id: str, failure_code: str) -> bool:
        with self._sessions.session() as session:
            result = session.execute(update(PresentationJobModel).where(
                PresentationJobModel.id == job_id,
                PresentationJobModel.state == "processing",
                PresentationJobModel.claimed_by == worker_id,
            ).values(state="failed", claimed_by=None, lease_until=None,
                     failure_code=failure_code[:64], updated_at=datetime.now(timezone.utc)))
            return result.rowcount == 1
