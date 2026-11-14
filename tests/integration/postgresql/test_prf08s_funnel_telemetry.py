"""Safe funnel journal survives the existing workflow JSONB checkpoint."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock
from unittest.mock import patch

from fastapi.testclient import TestClient

from application import research_funnel_telemetry as funnel
from application.config import ApplicationOverrides
from application.composition_root import create_application_container
from application.ports.source_ports import SearchProvider, SourceRetriever
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.runtime.task_result_codec import capture_task_progress, restore_runtime_state
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.sources.exceptions import SourceAcquisitionError
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_budget import SourceAcquisitionBudget
from api.app import create_fastapi_app
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from tools.real_research_e2e import _source_acquisition_diagnostics, _write_diagnostics
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from tests.api.auth_helpers import auth_headers
from tests.application.test_prf08s_funnel_telemetry import run_fixture
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
    postgresql_application_config,
)


class _ThreeCandidateSearch(SearchProvider):
    def search(self, query):
        return [SourceCandidate(
            provider="diagnostic-fixture",
            url=f"https://example.test/{query.information_need_id}",
            title="Synthetic report",
            snippet="Synthetic report",
            query_id=query.id,
            rank=1,
        )]


class _BoundedSuccessRetriever(SourceRetriever):
    def __init__(self, successful: int) -> None:
        self.successful = successful
        self.calls = 0

    def retrieve(self, candidate):
        self.calls += 1
        acquired = self.calls <= self.successful
        return Source(
            id="",
            project_id="",
            url=candidate.url,
            canonical_url=candidate.url,
            title=candidate.title,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=(
                RetrievalStatus.ACQUIRED if acquired else RetrievalStatus.FAILED
            ),
            content_text="Synthetic report body" if acquired else "",
            metadata={} if acquired else {"failure_category": "http_error"},
        )


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL required")
class FunnelPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def prepare(self):
        context = run_fixture()[0]
        # run_fixture is an extraction fixture; this suite exercises the
        # Search-task checkpoint contract consumed by the E2E harness.
        assert context.current_task is not None
        context.current_task.definition_id = "task-collect-evidence"
        context.current_task.executor_id = "search"
        # run_fixture intentionally uses stable in-memory IDs. PostgreSQL tests
        # need per-test identities because the suite may reuse one database.
        context.project.id = f"pg-funnel-project-{uuid4().hex}"
        context.project.owner_principal_id = f"pg-funnel-owner-{uuid4().hex}"
        context.workflow_run.id = f"pg-funnel-run-{uuid4().hex}"
        context.workflow_run.project_id = context.project.id
        PostgreSQLProjectRepository(self.session_factory).create(context.project)
        repo = PostgreSQLWorkflowRunRepository(self.session_factory)
        repo.create(context.workflow_run, project_id=context.project.id)
        return context, repo

    def fail_acquisition(self, context, *, acquired: int) -> None:
        context.execution_metadata["research_funnel_enabled"] = False
        context.shared_state.pop(funnel.KEY, None)
        service = SourceAcquisitionService(
            search_provider=_ThreeCandidateSearch(),
            source_retriever=_BoundedSuccessRetriever(acquired),
            source_repository=InMemorySourceRepository(),
            budget=SourceAcquisitionBudget(
                max_sources_per_run=3,
                min_successful_sources=3,
            ),
        )
        with self.assertRaises(SourceAcquisitionError):
            service.acquire_for_context(context)
        assert context.shared_state["source_acquisition"]["acquired_count"] == acquired
        assert funnel.KEY not in context.shared_state

    @staticmethod
    def api_key_for_owner(container, owner_principal_id: str) -> str:
        plaintext, key_id, key_prefix, key_hash = (
            container.authentication_service.generate_key_material()
        )
        container.authentication_service.register_api_key(
            name="failed-acquisition-diagnostic",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            principal_id=owner_principal_id,
        )
        return plaintext

    def run_real_worker_failure(self, *, acquired: int):
        config = postgresql_application_config(background_execution_mode="external")
        worker = create_application_container(
            config=config,
            overrides=ApplicationOverrides(
                search_provider=_ThreeCandidateSearch(),
                source_retriever=_BoundedSuccessRetriever(acquired),
            ),
        )
        self.addCleanup(worker.shutdown)
        worker.agency.initialize()
        project = worker.project_service.create_project(
            f"Worker acquisition diagnostic {acquired}",
            owner_principal_id=f"worker-diagnostic-owner-{uuid4().hex}",
        )
        design = ResearchDesign(
            id=f"worker-diagnostic-design-{acquired}",
            research_questions=(ResearchQuestion("rq-worker", "Synthetic population"),),
            information_needs=tuple(
                InformationNeed(f"in-worker-{i}", "rq-worker", "Synthetic population")
                for i in range(3)
            ),
        )
        template = ResearchDesignWorkflowMapper().from_research_design(design, project)
        run_id = worker.durable_workflow_service.submit_research(
            project, template,
        ).workflow_run.id

        self.assertTrue(
            worker.worker_execution_service.process_once(
                f"diagnostic-worker-{acquired}",
            )
        )
        repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        reloaded_run = repository.get_by_id(run_id)
        self.assertIsNotNone(reloaded_run)
        collect = next(
            task for task in reloaded_run.tasks
            if task.definition_id == "task-collect-evidence"
        )
        self.assertEqual(collect.status, TaskStatus.FAILED)
        self.assertEqual(reloaded_run.status, WorkflowStatus.FAILED)
        loaded = repository.get_task_results(run_id)
        snapshot = loaded[collect.id]
        self.assertIn("source_acquisition", snapshot.get("shared_state", {}))
        self.assertEqual(snapshot["definition_id"], "task-collect-evidence")
        summary = snapshot["shared_state"]["source_acquisition"]
        self.assertEqual(summary["acquired_count"], acquired)
        self.assertEqual(summary["failed_count"], 3 - acquired)
        self.assertEqual(len(summary["safe_attempt_diagnostics"]), 3)
        self.assertFalse(summary["safe_diagnostics_truncated"])
        self.assertEqual(
            sum(item["action"] == "fetch_failed" for item in summary["safe_attempt_diagnostics"]),
            3 - acquired,
        )
        self.assertEqual(
            summary["failure_category_counts"].get("http_error"),
            3 - acquired,
        )

        api = create_application_container(
            config=postgresql_application_config(background_execution_mode="external"),
        )
        self.addCleanup(api.shutdown)
        token = self.api_key_for_owner(api, project.owner_principal_id)
        with TestClient(create_fastapi_app(container=api)) as client:
            response = client.get(
                f"/workflow-runs/{run_id}/results",
                headers=auth_headers(token),
            )
        self.assertEqual(response.status_code, 200)
        durable_results = response.json()
        projection = _source_acquisition_diagnostics(durable_results)
        self.assertIsNotNone(projection)
        self.assertEqual(projection["summary"]["acquired_count"], acquired)
        self.assertEqual(len(projection["attempts"]), 3)
        return durable_results, projection

    def test_real_worker_failed_acquisition_survives_reload_http_and_projection(self):
        for acquired in (0, 2):
            with self.subTest(acquired=acquired):
                durable_results, projection = self.run_real_worker_failure(
                    acquired=acquired,
                )
                search_results = [
                    item for item in durable_results["task_results"]
                    if item.get("snapshot", {}).get("definition_id")
                    == "task-collect-evidence"
                ]
                self.assertEqual(
                    len(search_results),
                    1,
                )
                serialized = json.dumps(projection, ensure_ascii=False)
                self.assertNotIn("example.test", serialized)
                self.assertNotIn("source_id", serialized)
                self.assertNotIn("provider", serialized)
                self.assertNotIn("credential", serialized)

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
                self.fail_acquisition(context, acquired=acquired)
                context.current_task.ready()
                context.current_task.start()
                context.current_task.fail()
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
                self.assertEqual(
                    loaded[context.current_task.id]["shared_state"]
                    ["source_acquisition"]["acquired_count"],
                    acquired,
                )
                durable_attempts = loaded[context.current_task.id]["shared_state"]["source_acquisition"]["safe_attempt_diagnostics"]
                self.assertEqual(len(durable_attempts), 3)
                self.assertEqual(
                    sum(item["action"] == "fetch_failed" for item in durable_attempts),
                    3 - acquired,
                )
                self.assertNotIn(
                    funnel.KEY,
                    loaded[context.current_task.id]["shared_state"],
                )

                container = create_application_container(
                    config=postgresql_application_config(
                        deterministic_stage_executors=True,
                        background_execution_mode="external",
                    ),
                )
                token = self.api_key_for_owner(
                    container,
                    context.project.owner_principal_id,
                )
                try:
                    with TestClient(create_fastapi_app(container=container)) as client:
                        response = client.get(
                            f"/workflow-runs/{context.workflow_run.id}/results",
                            headers=auth_headers(token),
                        )
                    self.assertEqual(response.status_code, 200)
                    durable_results = response.json()
                finally:
                    container.shutdown()

                projection = _source_acquisition_diagnostics(durable_results)
                assert projection is not None
                self.assertEqual(projection["summary"]["acquired_count"], acquired)
                self.assertEqual(
                    projection["failure_category_counts"].get("http_error"),
                    3 - acquired,
                )
                diagnostics = {
                    "status": "failed",
                    "workflow_status": durable_results["status"],
                    "source_acquisition_diagnostics": projection,
                }
                with tempfile.TemporaryDirectory() as output_dir:
                    _write_diagnostics(Path(output_dir), diagnostics)
                    serialized = (Path(output_dir) / "diagnostics.json").read_text(
                        encoding="utf-8",
                    )
                    persisted_json = json.loads(serialized)
                self.assertEqual(
                    persisted_json["source_acquisition_diagnostics"]
                    ["summary"]["acquired_count"],
                    acquired,
                )
                self.assertNotIn("example.test", serialized)
                self.assertNotIn("source_id", serialized)
                self.assertNotIn("provider", serialized)
                self.assertNotIn("credential", serialized)

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
