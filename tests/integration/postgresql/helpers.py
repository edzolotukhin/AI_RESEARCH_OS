"""PostgreSQL integration test helpers."""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import make_url

from application.config import ApplicationConfig
from infrastructure.persistence.postgresql.database import Base
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class DeterministicStructuredPptxRenderer:
    """Provider-free renderer; PostgreSQL job persistence remains production-real."""

    version = "pptx-postgresql-test-v1"
    template_version = "desk-postgresql-test-v1"
    media_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )

    @staticmethod
    def render(document) -> bytes:
        return b"PK\x03\x04" + document.source_id.encode("utf-8")


def configure_structured_finalization_test_boundary(container) -> None:
    """Replace only external PPTX rendering, never the PostgreSQL job repository."""

    if container.project_deliverables_service.presentation_jobs is None:
        raise AssertionError("PostgreSQL presentation job repository is required")
    container.project_deliverables_service.pptx_renderer = (
        DeterministicStructuredPptxRenderer()
    )


def assert_structured_finalization_complete(test_case, container, run_id: str) -> None:
    state = container.workflow_service.get_task_results(run_id).get(
        "desk_deliverable_finalization"
    )
    test_case.assertIsInstance(state, dict)
    test_case.assertEqual(state.get("status"), "finalization_complete")
    test_case.assertTrue(state.get("pptx_id"))
    run = container.workflow_service.get_workflow_run(run_id)
    finalization_tasks = [task for task in run.tasks if task.executor_id == "finalization"]
    test_case.assertEqual(len(finalization_tasks), 1)
    test_case.assertEqual(finalization_tasks[0].status.value, "completed")
    reviews = container.review_query_service._review_repository.list_for_project(
        run.project_id, workflow_run_id=run_id
    )
    approved = [item for item in reviews if item.verdict.value == "approve"]
    test_case.assertEqual(len(approved), 1)
    report = container.report_query_service._report_repository.get_by_id(
        approved[0].report_id
    )
    test_case.assertIsNotNone(report)
    test_case.assertEqual(report.workflow_run_id, run_id)
    test_case.assertEqual(approved[0].verdict.value, "approve")
    test_case.assertEqual(approved[0].report_id, report.id)
    claims = container.project_deliverables_service.report_claims.list_for_report(
        report.id, report.revision_number
    )
    test_case.assertTrue(claims)
    test_case.assertTrue(all(claim.report_workflow_run_id == run_id for claim in claims))
    jobs = [
        job for job in container.project_deliverables_service.presentation_jobs.list_recent()
        if job.run_id == run_id
    ]
    test_case.assertEqual(len(jobs), 1)
    test_case.assertEqual(jobs[0].state, "finalization_complete")
    test_case.assertEqual(jobs[0].completed_deliverable_id, state["pptx_id"])
    test_case.assertEqual(jobs[0].report_revision, report.revision_number)
    test_case.assertEqual(jobs[0].review_id, approved[0].id)
    project = container.project_service.get_project(run.project_id)
    item = container.project_deliverables_service.source(
        run.project_id,
        "DESK",
        report.id,
        owner_id=project.owner_principal_id,
    )
    test_case.assertEqual(item.finalization_state, "finalization_complete")
    test_case.assertIsNotNone(item.pdf)
    test_case.assertIsNotNone(item.pptx)
    test_case.assertEqual(jobs[0].source_run_id, item.document.source_run_id)
    pdf, _ = container.project_deliverables_service.store.get(item.pdf.id)
    pptx, _ = container.project_deliverables_service.store.get(item.pptx.id)
    test_case.assertEqual(pptx.id, state["pptx_id"])
    test_case.assertEqual((pdf.run_id, pptx.run_id), (run_id, run_id))
    test_case.assertEqual((pdf.source_id, pptx.source_id), (report.id, report.id))


def integration_tests_enabled() -> bool:
    if os.environ.get("POSTGRESQL_INTEGRATION_TESTS", "0") != "1":
        return False
    database_url = os.environ.get("DATABASE_URL_TEST")
    if not database_url:
        return False
    if os.environ.get("POSTGRESQL_DISPOSABLE_TEST_DATABASE", "0") != "1":
        return False
    try:
        url = make_url(database_url)
    except Exception:
        return False
    if not url.drivername.startswith("postgresql") or "test" not in (url.database or "").lower():
        return False
    if os.environ.get("CI") == "true":
        return (
            url.host in {"localhost", "127.0.0.1", "::1"}
            and url.database == os.environ.get("CI_POSTGRESQL_TEST_DATABASE")
            and os.environ.get("DATABASE_URL") == database_url
            and bool(url.database)
        )
    return True


def require_integration_tests() -> None:
    if not integration_tests_enabled():
        raise unittest.SkipTest(
            "PostgreSQL integration tests disabled. Set POSTGRESQL_INTEGRATION_TESTS=1 "
            "and POSTGRESQL_DISPOSABLE_TEST_DATABASE=1, and set DATABASE_URL_TEST "
            "to a database whose name contains 'test'."
        )


def get_test_database_url() -> str:
    require_integration_tests()
    database_url = os.environ.get("DATABASE_URL_TEST")
    assert database_url is not None
    return database_url


def postgresql_application_config(
    *,
    deterministic_stage_executors: bool = False,
    background_execution_mode: str = "external",
    search_provider: str = "deterministic",
    evidence_extractor: str = "deterministic",
    analysis_engine: str = "deterministic",
    report_engine: str = "deterministic",
    review_engine: str = "deterministic",
    research_sufficiency_assessor: str = "deterministic",
) -> ApplicationConfig:
    """PostgreSQL ApplicationConfig for integration tests."""
    return ApplicationConfig(
        persistence_backend="postgresql",
        database_url=get_test_database_url(),
        background_execution_mode=background_execution_mode,
        deterministic_stage_executors=deterministic_stage_executors,
        search_provider=search_provider,
        evidence_extractor=evidence_extractor,
        research_sufficiency_assessor=research_sufficiency_assessor,
        analysis_engine=analysis_engine,
        report_engine=report_engine,
        review_engine=review_engine,
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
        "browser_sessions",
        "project_memberships",
        "users",
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
