from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from application.config import ApplicationConfig
from application.runtime.background_execution_capability import (
    BackgroundExecutionMode,
    resolve_background_execution_capability,
    resolve_background_execution_mode,
)


class BackgroundExecutionCapabilityTests(unittest.TestCase):

    def test_postgresql_external_mode_supports_http_and_worker(self) -> None:
        config = ApplicationConfig(
            persistence_backend="postgresql",
            background_execution_mode="external",
        )
        capability = resolve_background_execution_capability(
            config,
            execution_port_available=True,
        )
        self.assertTrue(capability.http_submission)
        self.assertTrue(capability.in_process_worker)
        self.assertTrue(capability.multi_process_worker)

    def test_memory_embedded_mode_supports_http_only_in_process(self) -> None:
        config = ApplicationConfig(
            persistence_backend="memory",
            background_execution_mode="embedded",
        )
        capability = resolve_background_execution_capability(
            config,
            execution_port_available=True,
        )
        self.assertTrue(capability.http_submission)
        self.assertTrue(capability.in_process_worker)
        self.assertFalse(capability.multi_process_worker)

    def test_memory_disabled_mode_does_not_support_http_submission(self) -> None:
        config = ApplicationConfig(
            persistence_backend="memory",
            background_execution_mode="disabled",
        )
        capability = resolve_background_execution_capability(
            config,
            execution_port_available=True,
        )
        self.assertFalse(capability.http_submission)
        self.assertFalse(capability.in_process_worker)
        self.assertFalse(capability.multi_process_worker)

    def test_file_backend_never_supports_background_execution(self) -> None:
        for mode in ("disabled", "embedded", "external"):
            with self.subTest(mode=mode):
                config = ApplicationConfig(
                    persistence_backend="file",
                    background_execution_mode=mode,
                )
                capability = resolve_background_execution_capability(
                    config,
                    execution_port_available=False,
                )
                self.assertFalse(capability.http_submission)

    def test_postgresql_defaults_to_external_mode(self) -> None:
        config = ApplicationConfig(persistence_backend="postgresql")
        self.assertEqual(
            resolve_background_execution_mode(config),
            BackgroundExecutionMode.EXTERNAL,
        )

    def test_memory_defaults_to_disabled_mode(self) -> None:
        config = ApplicationConfig(persistence_backend="memory")
        self.assertEqual(
            resolve_background_execution_mode(config),
            BackgroundExecutionMode.DISABLED,
        )


class DeterministicPlannerSelectionTests(unittest.TestCase):

    def test_live_llm_client_is_default_without_deterministic_planner(self) -> None:
        from application.composition_root import _create_llm_client
        from infrastructure.llm.openai_client import OpenAIClient

        env = os.environ.copy()
        env.pop("DETERMINISTIC_PLANNER", None)
        with patch.dict(os.environ, env, clear=True):
            client = _create_llm_client(ApplicationConfig())
        self.assertIsInstance(client, OpenAIClient)

    def test_deterministic_planner_does_not_change_legacy_live_constructor(self) -> None:
        """P1-08.2: _create_llm_client is live-only; planner flag is stage-scoped."""
        from application.composition_root import _create_llm_client
        from infrastructure.llm.openai_client import OpenAIClient

        with patch.dict(os.environ, {"DETERMINISTIC_PLANNER": "1"}, clear=False):
            client = _create_llm_client(ApplicationConfig())
        self.assertIsInstance(client, OpenAIClient)

    def test_stage_clients_isolate_deterministic_planner(self) -> None:
        from application.llm.stage_llm_clients import (
            resolve_stage_llm_clients,
            unwrap_llm_client,
        )
        from infrastructure.llm.deterministic_llm_client import DeterministicLLMClient
        from infrastructure.llm.openai_client import OpenAIClient

        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        self.assertIsInstance(unwrap_llm_client(clients.planner), DeterministicLLMClient)
        self.assertIsInstance(unwrap_llm_client(clients.analysis), OpenAIClient)
        self.assertIsInstance(unwrap_llm_client(clients.report), OpenAIClient)
        self.assertIsInstance(unwrap_llm_client(clients.review), OpenAIClient)
        self.assertIsInstance(unwrap_llm_client(clients.evidence), OpenAIClient)


if __name__ == "__main__":
    unittest.main()
