"""PostgreSQL integration test helpers."""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from application.config import ApplicationConfig
from infrastructure.persistence.postgresql.database import Base
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


def integration_tests_enabled() -> bool:
    if os.environ.get("POSTGRESQL_INTEGRATION_TESTS", "0") != "1":
        return False

    database_url = os.environ.get("DATABASE_URL_TEST") or os.environ.get(
        "DATABASE_URL",
    )
    if not database_url:
        return False

    return "test" in database_url.rsplit("/", 1)[-1].lower()


def require_integration_tests() -> None:
    if not integration_tests_enabled():
        raise unittest.SkipTest(
            "PostgreSQL integration tests disabled. Set POSTGRESQL_INTEGRATION_TESTS=1 "
            "and DATABASE_URL_TEST to a database whose name contains 'test'."
        )


def get_test_database_url() -> str:
    require_integration_tests()
    database_url = os.environ.get("DATABASE_URL_TEST") or os.environ.get(
        "DATABASE_URL",
    )
    assert database_url is not None
    return database_url


def postgresql_application_config(
    *,
    deterministic_stage_executors: bool = False,
    background_execution_mode: str = "external",
    search_provider: str = "deterministic",
    evidence_extractor: str = "deterministic",
) -> ApplicationConfig:
    """PostgreSQL ApplicationConfig for integration tests."""
    return ApplicationConfig(
        persistence_backend="postgresql",
        database_url=get_test_database_url(),
        background_execution_mode=background_execution_mode,
        deterministic_stage_executors=deterministic_stage_executors,
        search_provider=search_provider,
        evidence_extractor=evidence_extractor,
    )


def create_test_engine() -> Engine:
    return create_engine(
        get_test_database_url(),
        future=True,
        poolclass=NullPool,
    )


def dispose_test_engine(engine: Engine | None) -> None:
    if engine is not None:
        engine.dispose()


def register_engine_cleanup(
    test_case: unittest.TestCase,
    engine: Engine,
) -> None:
    test_case.addCleanup(dispose_test_engine, engine)


def reset_schema(engine: Engine) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def truncate_all_tables(engine: Engine) -> None:
    table_names = [
        "research_submissions",
        "api_keys",
        "execution_log_entries",
        "workflow_tasks",
        "workflow_runs",
        "workflow_templates",
        "artifacts",
        "sources",
        "knowledge_items",
        "projects",
    ]
    with engine.begin() as connection:
        existing = set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            ).scalars()
        )
        for table_name in table_names:
            if table_name not in existing:
                continue
            connection.execute(
                text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE")
            )


def ensure_schema_migrated(engine: Engine | None = None) -> None:
    """Apply Alembic migrations when PF-03 tables are missing."""
    resolved_engine = engine or create_test_engine()
    owns_engine = engine is None
    try:
        with resolved_engine.connect() as connection:
            has_projects = connection.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename = 'projects'"
                    ")"
                )
            ).scalar_one()
        if has_projects:
            return

        from alembic import command
        from alembic.config import Config

        database_url = get_test_database_url()
        os.environ["DATABASE_URL"] = database_url
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if owns_engine:
            dispose_test_engine(resolved_engine)


def build_session_factory(engine: Engine) -> DatabaseSessionFactory:
    ensure_schema_migrated(engine)
    return DatabaseSessionFactory(engine)


@dataclass
class PostgreSQLTestResources:
    engine: Engine
    session_factory: DatabaseSessionFactory

    def dispose(self) -> None:
        dispose_test_engine(self.engine)


def create_test_resources() -> PostgreSQLTestResources:
    engine = create_test_engine()
    ensure_schema_migrated(engine)
    truncate_all_tables(engine)
    return PostgreSQLTestResources(
        engine=engine,
        session_factory=DatabaseSessionFactory(engine),
    )


class PostgreSQLIntegrationTestCase(unittest.TestCase):
    """Base test case with one shared engine per class and per-test cleanup."""

    engine: Engine
    session_factory: DatabaseSessionFactory
    _class_engine: Engine | None = None

    @classmethod
    def setUpClass(cls) -> None:
        require_integration_tests()
        cls._class_engine = create_test_engine()
        ensure_schema_migrated(cls._class_engine)

    @classmethod
    def tearDownClass(cls) -> None:
        dispose_test_engine(cls._class_engine)
        cls._class_engine = None

    def setUp(self) -> None:
        assert self._class_engine is not None
        self.engine = self._class_engine
        truncate_all_tables(self.engine)
        self.session_factory = DatabaseSessionFactory(self.engine)


class PostgreSQLRepositoryContractTestCase(unittest.TestCase):
    """Shared engine lifecycle for PostgreSQL repository contract suites."""

    _class_engine: Engine | None = None

    @classmethod
    def setUpClass(cls) -> None:
        require_integration_tests()
        cls._class_engine = create_test_engine()
        ensure_schema_migrated(cls._class_engine)

    @classmethod
    def tearDownClass(cls) -> None:
        dispose_test_engine(cls._class_engine)
        cls._class_engine = None

    def fresh_session_factory(self) -> DatabaseSessionFactory:
        assert self._class_engine is not None
        truncate_all_tables(self._class_engine)
        return DatabaseSessionFactory(self._class_engine)
