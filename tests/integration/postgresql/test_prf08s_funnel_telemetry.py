"""Safe funnel journal survives the existing workflow JSONB checkpoint."""
import unittest
from unittest.mock import Mock

from application import research_funnel_telemetry as funnel
from application.runtime.task_result_codec import capture_task_progress, restore_runtime_state
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from tests.application.test_prf08s_funnel_telemetry import run_fixture
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL required")
class FunnelPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def prepare(self):
        context = run_fixture()[0]
        PostgreSQLProjectRepository(self.session_factory).create(context.project)
        repo = PostgreSQLWorkflowRunRepository(self.session_factory)
        repo.create(context.workflow_run, project_id=context.project.id)
        return context, repo

    def test_jsonb_checkpoint_restore_and_legacy_absence(self):
        context, repo = self.prepare()
        self.assertEqual(repo.get_task_results(context.workflow_run.id), {})
        expected = context.shared_state[funnel.KEY]
        snapshot = capture_task_progress(context, context.current_task.id)
        repo.save(context.workflow_run, expected_version=0, task_results={context.current_task.id: snapshot})
        loaded = repo.get_task_results(context.workflow_run.id)
        context.shared_state.clear()
        restore_runtime_state(context, loaded)
        self.assertEqual(context.shared_state[funnel.KEY], expected)

    def test_failed_task_keeps_safe_funnel_snapshot(self):
        context, repo = self.prepare()
        context.current_task.ready()
        context.current_task.start()
        context.current_task.fail()
        service = Mock()
        service.save_workflow_run.side_effect = repo.save
        persister = WorkflowRuntimePersister(workflow_service=service, audit=None,
            run_id=context.workflow_run.id, initial_version=0)
        persister.on_task_finished(context, error=RuntimeError("PRIVATE_ERROR_NOT_A_TELEMETRY_FIELD"))
        loaded = repo.get_task_results(context.workflow_run.id)
        self.assertEqual(loaded[context.current_task.id]["shared_state"][funnel.KEY], context.shared_state[funnel.KEY])
        self.assertNotIn("PRIVATE_ERROR_NOT_A_TELEMETRY_FIELD", str(loaded))
