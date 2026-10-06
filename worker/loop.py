from __future__ import annotations

import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
import json

from application.container import ApplicationContainer
from worker.identity import generate_worker_id
from worker.logging_config import configure_worker_logging

logger = configure_worker_logging()


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
        self._worker = worker_id or os.environ.get("WORKER_ID") or generate_worker_id()
        self._service = container.worker_execution_service
        self._lease_config = self._service._lease_config
        self._stop = threading.Event()

    @property
    def worker_id(self) -> str:
        return self._worker

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info(
            "worker_started worker_id=%s poll_interval=%s persistence_backend=%s",
            self._worker,
            self._lease_config.poll_interval_seconds,
            self._container.config.persistence_backend,
        )
        self._container.agency.initialize()
        try:
            while not self._stop.is_set():
                self._write_heartbeat()
                try:
                    processed = self._service.process_once(self._worker)
                    if self._container.project_deliverables_service is not None:
                        processed = (self._container.project_deliverables_service
                                     .process_next_presentation(self._worker)) or processed
                    if self._container.qualitative_service is not None:
                        processed = self._container.qualitative_service.process_next_job(self._worker) or processed
                    if self._container.qualitative_analysis_service is not None:
                        processed = self._container.qualitative_analysis_service.process_next_job(self._worker) or processed
                except Exception:
                    logger.exception(
                        "worker_process_once_unexpected worker_id=%s",
                        self._worker,
                    )
                    processed = False
                if not processed:
                    self._stop.wait(self._lease_config.poll_interval_seconds)
        finally:
            logger.info("worker_loop_stop worker_id=%s", self._worker)

    def _write_heartbeat(self) -> None:
        path = os.environ.get("WORKER_HEARTBEAT_FILE")
        if not path:
            return
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps({"observed_at": datetime.now(timezone.utc).isoformat(), "worker_id": self._worker}), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            logger.exception("worker_heartbeat_write_failed worker_id=%s", self._worker)

    def run_until_idle(self, *, max_iterations: int = 100) -> int:
        """Process runnable runs until none remain. Useful in tests."""
        self._container.agency.initialize()
        runs = self._service.drain_runnable_runs(
            self._worker,
            max_runs=max_iterations,
        )
        presentations = 0
        if self._container.project_deliverables_service is not None:
            for _ in range(max_iterations):
                if not self._container.project_deliverables_service.process_next_presentation(self._worker):
                    break
                presentations += 1
        qualitative = 0
        if self._container.qualitative_service is not None:
            for _ in range(max_iterations):
                if not self._container.qualitative_service.process_next_job(self._worker): break
                qualitative += 1
        if self._container.qualitative_analysis_service is not None:
            for _ in range(max_iterations):
                if not self._container.qualitative_analysis_service.process_next_job(self._worker): break
                qualitative += 1
        return runs + presentations + qualitative


def install_signal_handlers(loop: WorkerLoop) -> None:
    def _handle(signum, frame) -> None:
        loop.request_stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
