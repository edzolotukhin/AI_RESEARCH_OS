from __future__ import annotations

import signal
import threading
import time

from application.container import ApplicationContainer
from worker.identity import generate_worker_id


class WorkerLoop:
    """Polls PostgreSQL for runnable runs and delegates execution."""

    def __init__(
        self,
        container: ApplicationContainer,
        *,
        worker_id: str | None = None,
    ) -> None:
        if container.worker_execution_service is None:
            raise RuntimeError("WorkerExecutionService is not configured.")
        self._container = container
        self._worker = worker_id or generate_worker_id()
        self._service = container.worker_execution_service
        self._lease_config = self._service._lease_config
        self._stop = threading.Event()

    @property
    def worker_id(self) -> str:
        return self._worker

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        self._container.agency.initialize()
        while not self._stop.is_set():
            processed = self._service.process_once(self._worker)
            if not processed:
                self._stop.wait(self._lease_config.poll_interval_seconds)

    def run_until_idle(self, *, max_iterations: int = 100) -> int:
        """Process runnable runs until none remain. Useful in tests."""
        self._container.agency.initialize()
        return self._service.drain_runnable_runs(
            self._worker,
            max_runs=max_iterations,
        )


def install_signal_handlers(loop: WorkerLoop) -> None:
    def _handle(signum, frame) -> None:
        loop.request_stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
