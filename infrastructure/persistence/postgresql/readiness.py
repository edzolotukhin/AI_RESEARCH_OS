from __future__ import annotations

from typing import Callable


def resolve_expected_alembic_head(*, config_path: str = "alembic.ini") -> str:
    """Resolve the repository Alembic head once at composition time."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(config_path)
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(
            f"Expected exactly one Alembic head, found {len(heads)}: {heads}"
        )
    return heads[0]


def build_postgresql_readiness_check(
    engine: object,
    expected_revision: str,
    shutdown_callbacks: list[Callable[[], None]],
) -> Callable[[], tuple[bool, str]]:
    from sqlalchemy import text

    def _check() -> tuple[bool, str]:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                alembic_table_exists = connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'alembic_version'"
                        ")"
                    )
                ).scalar_one()
                if not alembic_table_exists:
                    return False, "schema_not_ready"

                current_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar_one_or_none()
                if current_revision is None:
                    return False, "schema_not_ready"
                if current_revision != expected_revision:
                    return False, "schema_outdated"
            return True, "ready"
        except Exception:
            return False, "database_unavailable"

    def _dispose() -> None:
        engine.dispose()

    shutdown_callbacks.append(_dispose)
    return _check
