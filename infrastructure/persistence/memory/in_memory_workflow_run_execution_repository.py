from __future__ import annotations

from datetime import datetime, timezone

from application.execution.exceptions import ClaimConflictError
from application.execution.models import ClaimResult, RunLease
from domain.workflow_status import WorkflowStatus

_TERMINAL_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.PAUSED,
    }
)
_RUNNABLE_STATUSES = frozenset(
    {
        WorkflowStatus.CREATED,
        WorkflowStatus.RUNNING,
    }
)


def _utc_now(now: datetime | None = None) -> datetime:
    resolved = now or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved


class InMemoryWorkflowRunExecutionRepository:
    """In-memory claim/lease adapter for tests."""

    def __init__(self, workflow_run_repository: object) -> None:
        self._runs = workflow_run_repository

    def try_claim_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> ClaimResult | None:
        resolved_now = _utc_now(now)
        workflow_run = self._runs.get_by_id(run_id)
        if workflow_run is None:
            return None
        if workflow_run.status in _TERMINAL_STATUSES:
            return None

        lease = self._leases.get(run_id)
        if lease is not None and lease.claimed_by not in {None, worker_id}:
            if lease.lease_expires_at >= resolved_now:
                return None

        version = self._runs.get_version(run_id)
        self._set_lease(
            run_id,
            worker_id=worker_id,
            lease_until=lease_until,
            heartbeat_at=resolved_now,
            version=version,
        )
        return ClaimResult(run_id=run_id, version=version)

    def claim_next_runnable(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> ClaimResult | None:
        resolved_now = _utc_now(now)
        for run_id in sorted(self._runs._runs):
            workflow_run = self._runs.get_by_id(run_id)
            assert workflow_run is not None
            if workflow_run.status not in _RUNNABLE_STATUSES:
                continue
            lease = self._leases.get(run_id)
            if lease is not None and lease.claimed_by not in {None, worker_id}:
                if lease.lease_expires_at >= resolved_now:
                    continue
            version = self._runs.get_version(run_id)
            self._set_lease(
                run_id,
                worker_id=worker_id,
                lease_until=lease_until,
                heartbeat_at=resolved_now,
                version=version,
            )
            return ClaimResult(run_id=run_id, version=version)
        return None

    def renew_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> None:
        lease = self._leases.get(run_id)
        if lease is None or lease.claimed_by != worker_id:
            raise ClaimConflictError(
                f"WorkflowRun {run_id} is not owned by {worker_id!r}."
            )
        version = self._runs.get_version(run_id)
        self._set_lease(
            run_id,
            worker_id=worker_id,
            lease_until=lease_until,
            heartbeat_at=_utc_now(now),
            version=version,
        )

    def release_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
    ) -> None:
        lease = self._leases.get(run_id)
        if lease is None or lease.claimed_by != worker_id:
            raise ClaimConflictError(
                f"WorkflowRun {run_id} is not owned by {worker_id!r}."
            )
        self._leases.pop(run_id, None)

    def get_lease(self, run_id: str) -> RunLease | None:
        return self._leases.get(run_id)

    @property
    def _leases(self) -> dict[str, RunLease]:
        store = getattr(self._runs, "_execution_leases", None)
        if store is None:
            store = {}
            setattr(self._runs, "_execution_leases", store)
        return store

    def _set_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        heartbeat_at: datetime,
        version: int,
    ) -> None:
        self._leases[run_id] = RunLease(
            run_id=run_id,
            claimed_by=worker_id,
            lease_expires_at=lease_until,
            heartbeat_at=heartbeat_at,
            version=version,
        )
