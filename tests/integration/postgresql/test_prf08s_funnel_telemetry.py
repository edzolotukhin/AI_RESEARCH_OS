"""Safe funnel journal survives the existing workflow JSONB checkpoint."""
import unittest
from uuid import uuid4
from unittest.mock import Mock

from application import research_funnel_telemetry as funnel
from application.runtime.task_result_codec import capture_task_progress, restore_runtime_state
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from api.mappers.response_mappers import task_results_to_response
from tools.real_research_e2e import _source_acquisition_diagnostics
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from tests.application.test_prf08s_funnel_telemetry import run_fixture
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL required")
class FunnelPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def prepare(self):
        context = run_fixture()[0]
        # run_fixture intentionally uses stable in-memory IDs. PostgreSQL tests
        # need per-test identities because the suite may reuse one database.
        context.project.id = f"pg-funnel-project-{uuid4().hex}"
        context.workflow_run.id = f"pg-funnel-run-{uuid4().hex}"
        context.workflow_run.project_id = context.project.id
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

    def test_failed_acquisition_summary_survives_reload_and_sanitized_projection(self):
        for acquired in (2, 0):
            with self.subTest(acquired=acquired):
                context, repo = self.prepare()
                context.current_task.ready()
                context.current_task.start()
                context.current_task.fail()
                context.shared_state["source_acquisition"] = {
                    "candidate_count_raw": 3,
                    "candidate_count_unique": 3,
                    "candidates_attempted": 3,
                    "acquired_count": acquired,
                    "failed_count": 3 - acquired,
                    "skipped_duplicate_count": 0,
                    "skipped_budget_count": 0,
                    "failure_category_counts": {"http_error": 3 - acquired},
                    "selection_decisions": [
                        {"canonical_url": "https://private.example/secret", "source_id": "private-source-id",
                         "action": "fetch_failed", "reason": "http_error"},
                    ],
                }
                service = Mock()
                service.save_workflow_run.side_effect = repo.save
                persister = WorkflowRuntimePersister(
                    workflow_service=service,
                    audit=None,
                    run_id=context.workflow_run.id,
                    initial_version=0,
                )
                persister.on_task_finished(context, error=RuntimeError("source minimum"))

                fresh_repo = PostgreSQLWorkflowRunRepository(self.session_factory)
                loaded = fresh_repo.get_task_results(context.workflow_run.id)
                api_items = task_results_to_response(context.workflow_run.id, loaded)
                projection = _source_acquisition_diagnostics({"task_results": [
                    {"task_id": item.task_id, "snapshot": item.snapshot}
                    for item in api_items
                ]})
                assert projection is not None
                self.assertEqual(projection["summary"]["acquired_count"], acquired)
                self.assertNotIn("private.example", str(projection))
                self.assertNotIn("private-source-id", str(projection))

    def test_split_subject_and_local_need_rejections_survive_jsonb_checkpoint(self):
        context, repo = self.prepare()
        journal = context.shared_state[funnel.KEY]
        journal["events"].extend((
            {"kind": "extraction_result", "rejections": ["subject_continuity_failure"]},
            {"kind": "extraction_result", "rejections": ["local_need_relevance_failure"]},
        ))
        snapshot = capture_task_progress(context, context.current_task.id)
        repo.save(
            context.workflow_run, expected_version=0,
            task_results={context.current_task.id: snapshot},
        )
        loaded = repo.get_task_results(context.workflow_run.id)
        context.shared_state.clear()
        restore_runtime_state(context, loaded)
        persisted = context.shared_state[funnel.KEY]["events"][-2:]
        self.assertEqual(
            [item["rejections"][0] for item in persisted],
            ["subject_continuity_failure", "local_need_relevance_failure"],
        )
