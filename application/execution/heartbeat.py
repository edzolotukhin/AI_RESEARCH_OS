from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from application.execution.exceptions import LeaseLostError
from application.execution.lease_config import LeaseConfig
from application.ports.workflow_run_execution_port import WorkflowRunExecutionPort


class LeaseGuard:
    """Signals when heartbeat renewal detects lost lease ownership."""

    def __init__(self) -> None:
        self._lost = threading.Event()

    def mark_lost(self) -> None:
        self._lost.set()

    def validate(self) -> None:
        if self._lost.is_set():
            raise LeaseLostError("Worker lost lease ownership for the run.")

    @property
    def lost(self) -> bool:
        return self._lost.is_set()


class HeartbeatManager:
    """Renews run leases on a background thread until stopped."""

    def __init__(
        self,
        *,
        execution_port: WorkflowRunExecutionPort,
        run_id: str,
        worker_id: str,
        lease_config: LeaseConfig,
        initial_version: int,
        lease_guard: LeaseGuard,
    ) -> None:
        self._execution_port = execution_port
        self._run_id = run_id
        self._worker_id = worker_id
        self._lease_config = lease_config
        self._version = initial_version
        self._lease_guard = lease_guard
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> HeartbeatManager:
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self._run_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._lease_config.heartbeat_interval_seconds + 1)

    @property
    def version(self) -> int:
        return self._version

    def _run(self) -> None:
        while not self._stop.wait(self._lease_config.heartbeat_interval_seconds):
            try:
                now = datetime.now(timezone.utc)
                lease_until = now + timedelta(
                    seconds=self._lease_config.lease_duration_seconds,
                )
                self._execution_port.renew_lease(
                    self._run_id,
                    worker_id=self._worker_id,
                    lease_until=lease_until,
                    now=now,
                )
            except Exception:
                self._lease_guard.mark_lost()
                return
