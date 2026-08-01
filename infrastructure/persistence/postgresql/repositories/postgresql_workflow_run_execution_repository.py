from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select, update

from application.execution.exceptions import ClaimConflictError
from application.execution.models import ClaimResult, RunLease
from application.persistence.exceptions import ConcurrentModificationError
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.postgresql.models.workflow_run_model import (
    WorkflowRunModel,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory

_RUNNABLE_STATUSES = (
    WorkflowStatus.CREATED.value,
    WorkflowStatus.RUNNING.value,
)
_TERMINAL_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED.value,
        WorkflowStatus.FAILED.value,
        WorkflowStatus.CANCELLED.value,
        WorkflowStatus.PAUSED.value,
    }
)


def _utc_now(now: datetime | None = None) -> datetime:
    resolved = now or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved


class PostgreSQLWorkflowRunExecutionRepository:
    """PostgreSQL adapter for worker claim and lease operations."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def try_claim_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> ClaimResult | None:
        resolved_now = _utc_now(now)
        with self._session_factory.session() as session:
            model = session.get(WorkflowRunModel, run_id)
            if model is None:
                return None
            if model.status in _TERMINAL_STATUSES:
                return None
            if not self._lease_claimable(model, resolved_now, worker_id):
                return None

            stored_version = int(model.version)
            result = session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.id == run_id,
                    WorkflowRunModel.version == stored_version,
                )
                .values(
                    claimed_by=worker_id,
                    lease_expires_at=lease_until,
                    heartbeat_at=resolved_now,
                )
            )
            if result.rowcount != 1:
                return None
            return ClaimResult(run_id=run_id, version=stored_version)

    def claim_next_runnable(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> ClaimResult | None:
        resolved_now = _utc_now(now)
        with self._session_factory.session() as session:
            statement = (
                select(WorkflowRunModel.id, WorkflowRunModel.version)
                .where(
                    WorkflowRunModel.status.in_(_RUNNABLE_STATUSES),
                    or_(
                        WorkflowRunModel.claimed_by.is_(None),
                        WorkflowRunModel.lease_expires_at.is_(None),
                        WorkflowRunModel.lease_expires_at < resolved_now,
                    ),
                )
                .order_by(WorkflowRunModel.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            candidate = session.execute(statement).first()
            if candidate is None:
                return None

            run_id, stored_version = candidate
            result = session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.id == run_id,
                    WorkflowRunModel.version == stored_version,
                )
                .values(
                    claimed_by=worker_id,
                    lease_expires_at=lease_until,
                    heartbeat_at=resolved_now,
                )
            )
            if result.rowcount != 1:
                return None
            return ClaimResult(run_id=run_id, version=stored_version)

    def renew_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> None:
        resolved_now = _utc_now(now)
        with self._session_factory.session() as session:
            result = session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.id == run_id,
                    WorkflowRunModel.claimed_by == worker_id,
                )
                .values(
                    lease_expires_at=lease_until,
                    heartbeat_at=resolved_now,
                )
            )
            if result.rowcount != 1:
                raise ClaimConflictError(
                    f"WorkflowRun {run_id} is not owned by {worker_id!r}."
                )

    def release_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
    ) -> None:
        with self._session_factory.session() as session:
            result = session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.id == run_id,
                    WorkflowRunModel.claimed_by == worker_id,
                )
                .values(
                    claimed_by=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                )
            )
            if result.rowcount != 1:
                raise ClaimConflictError(
                    f"WorkflowRun {run_id} is not owned by {worker_id!r}."
                )

    def get_lease(self, run_id: str) -> RunLease | None:
        with self._session_factory.session() as session:
            model = session.get(WorkflowRunModel, run_id)
            if model is None or model.claimed_by is None:
                return None
            assert model.lease_expires_at is not None
            assert model.heartbeat_at is not None
            return RunLease(
                run_id=run_id,
                claimed_by=model.claimed_by,
                lease_expires_at=model.lease_expires_at,
                heartbeat_at=model.heartbeat_at,
                version=int(model.version),
            )

    @staticmethod
    def _lease_claimable(
        model: WorkflowRunModel,
        now: datetime,
        worker_id: str,
    ) -> bool:
        if model.status in _TERMINAL_STATUSES:
            return False
        if model.claimed_by is None:
            return True
        if model.claimed_by == worker_id:
            return True
        if model.lease_expires_at is None:
            return True
        return model.lease_expires_at < now
