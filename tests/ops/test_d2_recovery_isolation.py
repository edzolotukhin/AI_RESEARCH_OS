from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "docker-compose.recovery-drill.yml"
EXAMPLE = ROOT / ".env.recovery-drill.example"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_restore_compose_isolated_from_production_names_and_networks() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    forbidden = (
        "pilot_postgres_data",
        "pilot_project_data",
        "pilot_protected_data",
        "pilot_runtime_status",
        "pilot_backend",
        "app-postgres",
    )
    assert not any(value in text for value in forbidden)
    assert "name: airos_recovery_drill_private" not in text
    config = _compose()
    database_url = config["services"]["recovery"]["environment"]["DATABASE_URL"]
    assert "@recovery-postgres:5432/" in database_url
    assert "@postgres:5432/" not in database_url
    assert config["networks"]["airos_recovery_drill_private"] in (None, {})
    assert set(config["volumes"]) == {
        "airos_recovery_drill_postgres_data",
        "airos_recovery_drill_protected_data",
        "airos_recovery_drill_project_data",
        "airos_recovery_drill_work",
        "airos_recovery_drill_runtime_status",
    }


def test_restore_compose_has_no_host_ports_or_production_status_mount() -> None:
    config = _compose()
    assert all("ports" not in service for service in config["services"].values())
    mounts = str(config["services"]["recovery"]["volumes"])
    assert "pilot_runtime_status" not in mounts
    assert "airos_recovery_drill_runtime_status" in mounts
    assert "RESTORE_CONFIRMATION" in str(config["services"]["recovery"]["environment"])


def test_example_requires_explicit_identity_and_disposable_confirmation() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    for key in ("APP_SHA=", "ALEMBIC_HEAD=", "RESTIC_REPOSITORY=", "RESTIC_PASSWORD_FILE_HOST=", "RESTORE_CONFIRMATION="):
        assert key in text
    assert "DISPOSABLE_EMPTY_TARGET" in text
    assert "Remote restic repository URI" in text
    assert "host filesystem" not in text.casefold()
    assert "production" in text.casefold()


def test_restore_tool_requires_identity_and_confirmation() -> None:
    source = (ROOT / "tools" / "pilot_recovery.py").read_text(encoding="utf-8")
    assert 'required("APP_SHA")' in source
    assert 'required("ALEMBIC_HEAD")' in source
    assert 'required("RESTORE_CONFIRMATION") != "DISPOSABLE_EMPTY_TARGET"' in source
