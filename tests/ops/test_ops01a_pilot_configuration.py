from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from application.production_config import (
    ProductionConfigurationError,
    validate_production_environment,
)
from api.app import create_fastapi_app
from tests.api.helpers import build_test_container


ROOT = Path(__file__).resolve().parents[2]


def pilot_environment(**overrides: str) -> dict[str, str]:
    values = {
        "APP_ENV": "pilot",
        "PERSISTENCE_BACKEND": "postgresql",
        "DATABASE_URL": "postgresql+psycopg://pilot:a-strong-db-secret@postgres:5432/pilot",
        "ALLOWED_HOSTS": "research.example.org",
        "UI_COOKIE_SECURE": "1",
        "UI_CSRF_SECRET": "a-strong-csrf-secret-with-more-than-32-characters",
        "DEBUG": "0",
    }
    values.update(overrides)
    return values


class PilotConfigurationTests(unittest.TestCase):
    def test_safe_pilot_environment_passes(self) -> None:
        with patch.dict(os.environ, pilot_environment(), clear=True):
            validate_production_environment()

    def test_missing_or_placeholder_database_secret_fails_without_echoing_value(self) -> None:
        for password in ("", "CHANGE_ME_DATABASE_PASSWORD", "ai_research_os_dev"):
            url = f"postgresql+psycopg://pilot:{password}@postgres:5432/pilot"
            with self.subTest(password=password), patch.dict(
                os.environ,
                pilot_environment(DATABASE_URL=url),
                clear=True,
            ):
                with self.assertRaises(ProductionConfigurationError) as caught:
                    validate_production_environment()
                if password:
                    self.assertNotIn(password, str(caught.exception))

    def test_pilot_rejects_insecure_cookie_debug_and_wildcard_host(self) -> None:
        cases = (
            {"UI_COOKIE_SECURE": "0"},
            {"DEBUG": "true"},
            {"ALLOWED_HOSTS": "*"},
            {"UI_CSRF_SECRET": "CHANGE_ME"},
        )
        for values in cases:
            with self.subTest(values=values), patch.dict(
                os.environ,
                pilot_environment(**values),
                clear=True,
            ):
                with self.assertRaises(ProductionConfigurationError):
                    validate_production_environment()

    def test_development_configuration_is_unchanged(self) -> None:
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=True):
            validate_production_environment()

    def test_explicit_host_allowlist_rejects_untrusted_host(self) -> None:
        container = build_test_container()
        try:
            with patch.dict(os.environ, {"ALLOWED_HOSTS": "pilot.example.org"}, clear=False):
                with TestClient(create_fastapi_app(container=container)) as client:
                    self.assertEqual(
                        client.get("/health", headers={"Host": "attacker.invalid"}).status_code,
                        400,
                    )
                    self.assertEqual(
                        client.get("/health", headers={"Host": "pilot.example.org"}).status_code,
                        200,
                    )
        finally:
            container.shutdown()

    def test_pilot_compose_keeps_database_worker_and_api_private(self) -> None:
        compose = (ROOT / "docker-compose.pilot.yml").read_text(encoding="utf-8")
        postgres = compose.split("  postgres:", 1)[1].split("  migrate:", 1)[0]
        api = compose.split("  api:", 1)[1].split("  worker:", 1)[0]
        worker = compose.split("  worker:", 1)[1].split("  proxy:", 1)[0]
        self.assertNotIn("ports:", postgres)
        self.assertNotIn("ports:", api)
        self.assertNotIn("ports:", worker)
        self.assertIn('expose: ["8000"]', api)
        self.assertIn('- "80:80"', compose)
        self.assertIn('- "443:443"', compose)
        self.assertIn("networks: [pilot_frontend, pilot_backend]", api)
        self.assertIn("networks: [pilot_frontend]", compose)

    def test_pilot_compose_has_explicit_storage_health_and_log_bounds(self) -> None:
        compose = (ROOT / "docker-compose.pilot.yml").read_text(encoding="utf-8")
        for volume in ("pilot_postgres_data", "pilot_protected_data", "pilot_project_data"):
            self.assertIn(volume, compose)
        self.assertIn("condition: service_healthy", compose)
        self.assertIn("python -m worker.healthcheck", compose)
        self.assertIn("max-size: 10m", compose)
        self.assertIn("max-file:", compose)

    def test_real_pilot_env_is_ignored_but_template_is_tracked(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env.*", ignore)
        self.assertIn("!.env.pilot.example", ignore)
        template = (ROOT / ".env.pilot.example").read_text(encoding="utf-8")
        self.assertIn("CHANGE_ME", template)
        self.assertNotIn("ai_research_os_dev", template)


if __name__ == "__main__":
    unittest.main()
