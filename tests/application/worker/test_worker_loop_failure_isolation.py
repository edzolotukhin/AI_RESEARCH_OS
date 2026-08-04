"""Worker loop survives per-run execution failures."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.container import ApplicationContainer
from application.execution.lease_config import LeaseConfig
from application.report.exceptions import ReportError
from application.services.worker_execution_service import WorkerExecutionService
from worker.loop import WorkerLoop


class WorkerLoopFailureIsolationTests(unittest.TestCase):
    def test_run_continues_polling_after_process_once_returns_true_on_failure(self) -> None:
        service = Mock(spec=WorkerExecutionService)
        service._lease_config = LeaseConfig(poll_interval_seconds=0.01)
        calls = {"count": 0}

        def _process_once(worker_id: str) -> bool:
            calls["count"] += 1
            if calls["count"] >= 2:
                loop.request_stop()
            return True

        container = Mock(spec=ApplicationContainer)
        container.config = Mock(persistence_backend="postgresql")
        container.agency = Mock()
        container.worker_execution_service = service

        loop = WorkerLoop(container, worker_id="worker-loop-test")
        service.process_once.side_effect = _process_once
        loop.run()
        self.assertEqual(calls["count"], 2)

    def test_report_error_does_not_stop_worker_loop(self) -> None:
        service = Mock(spec=WorkerExecutionService)
        service._lease_config = LeaseConfig(poll_interval_seconds=0.01)
        calls = {"count": 0}

        def _process_once(worker_id: str) -> bool:
            calls["count"] += 1
            if calls["count"] == 1:
                service._last_run_error = ReportError(
                    "No valid report sections produced for workflow run test-run",
                )
            if calls["count"] >= 2:
                loop.request_stop()
            return True

        container = Mock(spec=ApplicationContainer)
        container.config = Mock(persistence_backend="postgresql")
        container.agency = Mock()
        container.worker_execution_service = service

        loop = WorkerLoop(container, worker_id="worker-report-test")
        service.process_once.side_effect = _process_once
        loop.run()
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
