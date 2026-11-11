from __future__ import annotations

import concurrent.futures
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from sqlalchemy import select, update

from infrastructure.persistence.postgresql.models.authority_extension_model import (
    AuthorityExtensionModel,
)
from infrastructure.persistence.postgresql.models.project_model import ProjectModel
from infrastructure.persistence.postgresql.models.task_model import WorkflowTaskModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.repositories.postgresql_authority_extension_repository import (
    PostgreSQLAuthorityExtensionRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    create_test_engine,
    integration_tests_enabled,
)


@unittest.skipUnless(integration_tests_enabled(), "disposable PostgreSQL required")
class AuthorityExtensionRecoveryPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        with self.engine.begin() as connection:
            connection.execute(ProjectModel.__table__.insert().values(
                id="project", name="Recovery test", status="ACTIVE",
                created_at="2026-01-01", updated_at="2026-01-01", version=0,
            ))
            connection.execute(WorkflowRunModel.__table__.insert(), [
                {"id": "parent", "project_id": "project", "workflow_template_id": "template",
                 "status": "completed", "dependency_graph": {}, "task_results": {}, "version": 0},
                {"id": "extension-run", "project_id": "project", "workflow_template_id": "template",
                 "status": "failed", "dependency_graph": {}, "task_results": {}, "version": 0},
            ])
            connection.execute(WorkflowTaskModel.__table__.insert().values(
                workflow_run_id="extension-run", task_id="plan", definition_id="plan",
                name="extension_plan", description="", executor_id="authority-plan",
                executor_type="tool", depends_on=[], status="failed",
                created_at="2026-01-01", updated_at="2026-01-01", sort_order=0,
            ))
            connection.execute(AuthorityExtensionModel.__table__.insert().values(
                extension_id="extension", project_id="project", research_design_id="design",
                parent_source_workflow_run_id="parent", extension_workflow_run_id="extension-run",
                selected_information_need_ids=["in1"], gap_contract_digest="digest",
                idempotency_key="recovery-test", created_at="2026-01-01", status="active",
                terminal_reason=None,
            ))

    def _repo(self):
        return PostgreSQLAuthorityExtensionRepository(DatabaseSessionFactory(self.engine))

    def _args(self, **overrides):
        values = {
            "project_id": "project", "extension_id": "extension",
            "expected_workflow_run_id": "extension-run",
            "failure_class": "RuntimeError", "reason": "test", "dry_run": False,
        }
        values.update(overrides)
        return values

    def test_apply_and_fresh_reload(self):
        result = self._repo().reconcile_failed_active(
            project_id="project", extension_id="extension",
            expected_workflow_run_id="extension-run", failure_class="RuntimeError",
            reason="stale failed workflow", dry_run=False,
        )
        self.assertEqual(result["code"], "reconciled")
        fresh = self._repo().get_by_id("extension")
        self.assertEqual(fresh.status.value, "technical_error")
        with self.engine.connect() as connection:
            event_count = connection.exec_driver_sql(
                "SELECT count(*) FROM execution_log_entries WHERE event_type='authority_extension_reconciled'"
            ).scalar_one()
        self.assertEqual(event_count, 1)

    def test_concurrent_apply_is_single_transition_and_idempotent(self):
        def apply_once():
            return self._repo().reconcile_failed_active(
                project_id="project", extension_id="extension",
                expected_workflow_run_id="extension-run", failure_class="RuntimeError",
                reason="concurrent test", dry_run=False,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: apply_once(), range(2)))
        self.assertEqual(sorted(item["code"] for item in results), ["already_reconciled", "reconciled"])
        repeat = apply_once()
        self.assertEqual(repeat["code"], "already_reconciled")
        with self.engine.connect() as connection:
            count = connection.exec_driver_sql(
                "SELECT count(*) FROM execution_log_entries WHERE event_type='authority_extension_reconciled'"
            ).scalar_one()
        self.assertEqual(count, 1)

    def test_dry_run_and_active_lease_are_non_mutating(self):
        dry = self._repo().reconcile_failed_active(
            project_id="project", extension_id="extension",
            expected_workflow_run_id="extension-run", failure_class="RuntimeError",
            reason="dry run", dry_run=True,
        )
        self.assertEqual(dry["code"], "dry_run")
        self.assertEqual(self._repo().get_by_id("extension").status.value, "active")
        with self.engine.begin() as connection:
            connection.execute(update(WorkflowRunModel).where(
                WorkflowRunModel.id == "extension-run",
            ).values(
                claimed_by="worker", heartbeat_at=datetime.now(timezone.utc),
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ))
        refused = self._repo().reconcile_failed_active(
            project_id="project", extension_id="extension",
            expected_workflow_run_id="extension-run", failure_class="RuntimeError",
            reason="lease test", dry_run=False,
        )
        self.assertEqual(refused["code"], "active_execution_lease")
        self.assertEqual(self._repo().get_by_id("extension").status.value, "active")

    def test_rollback_after_status_update_leaves_no_partial_rows(self):
        base = DatabaseSessionFactory(self.engine)

        class FailingFactory:
            def __init__(self, delegate):
                self.delegate = delegate
                self.failed = False

            @contextmanager
            def session(self):
                session = self.delegate._session_factory()
                try:
                    yield session
                    if not self.failed:
                        self.failed = True
                        raise RuntimeError("injected post-update failure")
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

        failing = FailingFactory(base)
        with self.assertRaisesRegex(RuntimeError, "injected"):
            PostgreSQLAuthorityExtensionRepository(failing).reconcile_failed_active(**self._args())
        with self.engine.connect() as connection:
            status = connection.exec_driver_sql(
                "SELECT status FROM research_authority_extensions WHERE extension_id='extension'"
            ).scalar_one()
            audit = connection.exec_driver_sql(
                "SELECT count(*) FROM execution_log_entries WHERE event_type='authority_extension_reconciled'"
            ).scalar_one()
        self.assertEqual(status, "active")
        self.assertEqual(audit, 0)
        self.assertEqual(self._repo().reconcile_failed_active(**self._args())["code"], "reconciled")

    def test_foreign_project_and_wrong_linkage_are_rejected(self):
        self.assertEqual(
            self._repo().reconcile_failed_active(**self._args(project_id="foreign-project"))["code"],
            "project_mismatch",
        )
        self.assertEqual(
            self._repo().reconcile_failed_active(**self._args(expected_workflow_run_id="parent"))["code"],
            "workflow_linkage_mismatch",
        )
        self.assertEqual(self._repo().get_by_id("extension").status.value, "active")
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql(
                "SELECT count(*) FROM execution_log_entries WHERE event_type='authority_extension_reconciled'"
            ).scalar_one(), 0)

    def test_nonterminal_task_is_rejected_and_terminal_tasks_are_allowed(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE workflow_tasks SET status='running' WHERE workflow_run_id='extension-run'"
            )
        self.assertEqual(self._repo().reconcile_failed_active(**self._args())["code"], "nonterminal_task")
        self.assertEqual(self._repo().get_by_id("extension").status.value, "active")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE workflow_tasks SET status='skipped' WHERE workflow_run_id='extension-run'"
            )
        self.assertEqual(self._repo().reconcile_failed_active(**self._args())["code"], "reconciled")

    def test_terminal_failed_workflow_cannot_be_claimed_by_worker(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
            PostgreSQLWorkflowRunExecutionRepository,
        )
        execution = PostgreSQLWorkflowRunExecutionRepository(DatabaseSessionFactory(self.engine))
        self.assertIsNone(execution.try_claim_run(
            "extension-run", worker_id="worker", lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
            now=datetime.now(timezone.utc),
        ))
        self.assertEqual(self._repo().reconcile_failed_active(**self._args())["code"], "reconciled")

