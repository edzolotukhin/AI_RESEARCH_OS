from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PostgreSQLConfig:
    """Infrastructure-level PostgreSQL connection settings."""

    database_url: str

    @classmethod
    def from_env(cls) -> PostgreSQLConfig:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "DATABASE_URL is required when PERSISTENCE_BACKEND=postgresql."
            )
        return cls(database_url=database_url)

    @classmethod
    def from_env_or_default(cls, default_url: str) -> PostgreSQLConfig:
        database_url = os.environ.get("DATABASE_URL", default_url)
        return cls(database_url=database_url)
