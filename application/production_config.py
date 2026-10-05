from __future__ import annotations

import os
from urllib.parse import urlsplit


class ProductionConfigurationError(RuntimeError):
    """Bounded operator-facing error for an unsafe pilot configuration."""


_UNSAFE = {
    "",
    "changeme",
    "change-me",
    "password",
    "secret",
    "example",
    "replace-me",
    "ai_research_os_dev",
}


def _unsafe_secret(value: str) -> bool:
    raw = value.strip().casefold()
    normalized = raw.replace("_", "-")
    return raw in _UNSAFE or normalized in _UNSAFE or any(
        marker in normalized for marker in ("change-me", "changeme", "replace-me")
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProductionConfigurationError(f"{name} is required in pilot mode")
    return value


def validate_production_environment() -> None:
    """Fail closed on pilot settings without ever including secret values."""
    if os.environ.get("APP_ENV", "").casefold() not in {"production", "prod", "pilot"}:
        return

    if os.environ.get("PERSISTENCE_BACKEND", "").casefold() != "postgresql":
        raise ProductionConfigurationError(
            "PERSISTENCE_BACKEND must be postgresql in pilot mode",
        )

    database_url = _required("DATABASE_URL")
    parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    if not parsed.password or _unsafe_secret(parsed.password):
        raise ProductionConfigurationError(
            "DATABASE_URL must contain a non-placeholder database password",
        )
    if parsed.hostname in {None, "localhost", "127.0.0.1", "0.0.0.0"}:
        raise ProductionConfigurationError(
            "DATABASE_URL must use the private pilot database service",
        )

    allowed_hosts = [item.strip() for item in _required("ALLOWED_HOSTS").split(",")]
    if any(not item or item == "*" for item in allowed_hosts):
        raise ProductionConfigurationError(
            "ALLOWED_HOSTS must be an explicit host allowlist",
        )
    if os.environ.get("UI_COOKIE_SECURE", "").casefold() not in {"1", "true", "yes"}:
        raise ProductionConfigurationError("UI_COOKIE_SECURE must be enabled in pilot mode")
    csrf_secret = _required("UI_CSRF_SECRET")
    if len(csrf_secret) < 32 or _unsafe_secret(csrf_secret):
        raise ProductionConfigurationError(
            "UI_CSRF_SECRET must be a strong non-placeholder runtime secret",
        )
    if os.environ.get("DEBUG", "").casefold() in {"1", "true", "yes", "on"}:
        raise ProductionConfigurationError("DEBUG must be disabled in pilot mode")


def configured_allowed_hosts() -> list[str]:
    return [
        item.strip()
        for item in os.environ.get("ALLOWED_HOSTS", "").split(",")
        if item.strip()
    ]
