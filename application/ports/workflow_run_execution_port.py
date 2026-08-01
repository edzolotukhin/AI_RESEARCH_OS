from __future__ import annotations

from datetime import datetime
from typing import Protocol

from application.execution.models import ClaimResult, RunLease


class WorkflowRunExecutionPort(Protocol):
    """
    Persistence port for worker claim/lease orchestration.

    Lease metadata lives in persistence; it is not part of the domain aggregate.
    """

    def try_claim_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> ClaimResult | None:
        """Atomically claim a specific runnable run, or return None on conflict."""
        ...

    def claim_next_runnable(
        self,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> ClaimResult | None:
        """Atomically claim the next runnable run using row-level locking."""
        ...

    def renew_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_until: datetime,
        now: datetime,
    ) -> None:
        """Renew lease ownership; raises on owner mismatch."""
        ...

    def release_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
    ) -> None:
        """Clear lease fields when the worker finishes or aborts safely."""
        ...

    def get_lease(self, run_id: str) -> RunLease | None:
        """Return current lease metadata for a run, if any."""
        ...
