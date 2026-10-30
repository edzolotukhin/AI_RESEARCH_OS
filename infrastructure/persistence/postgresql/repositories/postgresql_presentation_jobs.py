"""DB-polled presentation outbox with leases and idempotent scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from application.deliverables.desk_finalization import MAX_PPTX_ATTEMPTS
from application.deliverables.presentation_jobs import PresentationJob
from application.deliverables.approved_delivery_provenance import (
    ApprovedDeliveryProvenance,
    validate_storage_binding,
)
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

    def list_recent(self, *, limit: int = 50) -> tuple[PresentationJob, ...]:
        bounded = max(1, min(limit, 50))
        with self._sessions.session() as session:
            values = session.scalars(select(PresentationJobModel).order_by(
                PresentationJobModel.updated_at.desc(), PresentationJobModel.id
            ).limit(bounded)).all()
            return tuple(self._record(value) for value in values)

    def schedule(self, *, project_id: str, method: str, run_id: str, study_id: str | None,
                 source_id: str, source_version: str, status_snapshot: str,
                 template_version: str, renderer_version: str,
                 initial_state: str = "pending", report_revision: int | None = None,
                 review_id: str | None = None, source_run_id: str | None = None,
                 claim_set_digest: str | None = None,
                 coverage_contract_digest: str | None = None,
                 authority_digest: str | None = None,
                 presentation_digest: str | None = None,
                 approved_delivery_provenance: ApprovedDeliveryProvenance | None = None) -> PresentationJob:
        validate_storage_binding(
            approved_delivery_provenance,
            report_id=source_id,
            report_workflow_run_id=run_id,
            revision_number=report_revision,
            review_id=review_id,
            source_workflow_run_id=source_run_id,
            claim_set_digest=claim_set_digest,
            coverage_contract_digest=coverage_contract_digest,
        )
        if approved_delivery_provenance is not None:
            if authority_digest is not None and authority_digest != approved_delivery_provenance.authority_digest:
                raise ValueError("authority_digest mismatch")
            if presentation_digest is not None and presentation_digest != approved_delivery_provenance.presentation_digest:
                raise ValueError("presentation_digest mismatch")
            report_revision = approved_delivery_provenance.revision_number
            review_id = approved_delivery_provenance.review_id
            source_run_id = approved_delivery_provenance.source_workflow_run_id
            claim_set_digest = approved_delivery_provenance.claim_set_digest
            coverage_contract_digest = approved_delivery_provenance.coverage_contract_digest
            authority_digest = approved_delivery_provenance.authority_digest
            presentation_digest = approved_delivery_provenance.presentation_digest
        now = datetime.now(timezone.utc)
        values = dict(id=str(uuid4()), project_id=project_id, method=method, run_id=run_id,
                      study_id=study_id, source_id=source_id, source_version=source_version,
                      status_snapshot=status_snapshot, template_version=template_version,
                      renderer_version=renderer_version, state=initial_state, attempts=0,
                      lease_until=None, claimed_by=None, created_at=now, updated_at=now,
                      completed_deliverable_id=None, failure_code=None,
                      report_revision=report_revision, review_id=review_id,
                      source_run_id=source_run_id, claim_set_digest=claim_set_digest,
                      coverage_contract_digest=coverage_contract_digest,
                      authority_digest=authority_digest,
                      presentation_digest=presentation_digest)
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
            if (model.state in {"failed", "retry_wait"}
                    and model.attempts < MAX_PPTX_ATTEMPTS):
                model.state = "pptx_pending" if model.report_revision is not None else "pending"
                model.failure_code = None
                model.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._record(model)

    def claim_next(self, worker_id: str, *, lease_seconds: int = 120) -> PresentationJob | None:
        now = datetime.now(timezone.utc)
        with self._sessions.session() as session:
            session.execute(update(PresentationJobModel).where(
                PresentationJobModel.state.in_(("processing", "pptx_processing")),
                PresentationJobModel.lease_until < now,
                PresentationJobModel.attempts >= MAX_PPTX_ATTEMPTS,
            ).values(state="failed_terminal", claimed_by=None, lease_until=None,
                     failure_code="lease_exhausted", updated_at=now))
            model = session.scalars(select(PresentationJobModel).where(or_(
                PresentationJobModel.state.in_(("pending", "review_approved", "pdf_generating",
                                                 "pdf_complete", "pptx_pending", "retry_wait")),
                (PresentationJobModel.state.in_(("processing", "pptx_processing"))) &
                (PresentationJobModel.lease_until < now) &
                (PresentationJobModel.attempts < MAX_PPTX_ATTEMPTS),
            )).order_by(PresentationJobModel.created_at, PresentationJobModel.id)
                .with_for_update(skip_locked=True)).first()
            if model is None:
                return None
            model.state = "pptx_processing" if model.report_revision is not None else "processing"
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
                PresentationJobModel.state.in_(("processing", "pptx_processing")),
                PresentationJobModel.claimed_by == worker_id,
                PresentationJobModel.lease_until > datetime.now(timezone.utc),
            ).values(state=("finalization_complete" if self._is_structured(job_id) else "completed"), completed_deliverable_id=deliverable_id,
                     claimed_by=None, lease_until=None, failure_code=None,
                     updated_at=datetime.now(timezone.utc)))
            return result.rowcount == 1

    def fail(self, job_id: str, worker_id: str, failure_code: str) -> bool:
        with self._sessions.session() as session:
            result = session.execute(update(PresentationJobModel).where(
                PresentationJobModel.id == job_id,
                PresentationJobModel.state.in_(("processing", "pptx_processing")),
                PresentationJobModel.claimed_by == worker_id,
            ).values(state=self._failure_state(session, job_id), claimed_by=None, lease_until=None,
                     failure_code=failure_code[:64], updated_at=datetime.now(timezone.utc)))
            return result.rowcount == 1

    def transition(self, job_id: str, *, expected: tuple[str, ...], state: str,
                   failure_code: str | None = None) -> PresentationJob | None:
        with self._sessions.session() as session:
            model = session.get(PresentationJobModel, job_id, with_for_update=True)
            if model is None or model.state not in expected:
                return self._record(model)
            model.state = state
            model.failure_code = failure_code
            model.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._record(model)

    def _is_structured(self, job_id: str) -> bool:
        with self._sessions.session() as session:
            model = session.get(PresentationJobModel, job_id)
            return bool(model and model.report_revision is not None)

    @staticmethod
    def _failure_state(session, job_id: str) -> str:
        model = session.get(PresentationJobModel, job_id)
        if model is not None and model.report_revision is not None:
            return ("failed_terminal"
                    if model.attempts >= MAX_PPTX_ATTEMPTS else "retry_wait")
        return "failed"
