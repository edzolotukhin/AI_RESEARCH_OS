"""Worker loop configuration defaults."""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from application.container import ApplicationContainer
from application.execution.lease_config import LeaseConfig
from application.services.worker_execution_service import WorkerExecutionService
from worker.loop import WorkerLoop


class WorkerLoopDefaultsTests(unittest.TestCase):

    def _container(self) -> ApplicationContainer:
        container = Mock(spec=ApplicationContainer)
        container.agency = Mock()
        container.worker_execution_service = WorkerExecutionService(
            durable_workflow_service=Mock(),
            execution_port=Mock(),
            lease_config=LeaseConfig(
                lease_duration_seconds=30,
                heartbeat_interval_seconds=10,
                poll_interval_seconds=2.5,
            ),
        )
        return container

    def test_worker_id_defaults_when_env_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("WORKER_ID", None)
            loop = WorkerLoop(self._container())
            self.assertTrue(loop.worker_id)
            self.assertNotEqual(loop.worker_id, "")

    def test_worker_id_honors_env_override(self) -> None:
        with patch.dict("os.environ", {"WORKER_ID": "worker-test-1"}):
            loop = WorkerLoop(self._container(), worker_id=None)
            self.assertEqual(loop.worker_id, "worker-test-1")

    def test_poll_interval_default_from_env(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("WORKER_POLL_INTERVAL_SECONDS", None)
            config = LeaseConfig.from_env()
            self.assertEqual(config.poll_interval_seconds, 1.0)


if __name__ == "__main__":
    unittest.main()
