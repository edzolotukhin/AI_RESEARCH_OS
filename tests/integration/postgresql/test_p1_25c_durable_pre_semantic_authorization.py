from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace

from api.app import create_fastapi_app
from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.vertical_service import RealQuantitativeStageService
from application.quantitative.workflow import (
    SEMANTIC_AUTHORITY_FINGERPRINT_KEY,
    QuantitativeApprovalService,
    QuantitativeWorkflowError,
)
from domain.factories.project_factory import ProjectFactory
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_quantitative_state_repository import (
    PostgreSQLQuantitativeStateRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient
from tests.application.quantitative import test_property_qs_durable_worker_quantitative_service_resolution as qs_tests
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    create_test_engine,
    dispose_test_engine,
    integration_tests_enabled,
    postgresql_application_config,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "P1-25C PostgreSQL proof requires POSTGRESQL_INTEGRATION_TESTS=1.",
)
class P125CDurablePreSemanticAuthorizationPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_pause_snapshot_and_service_survive_fresh_application(self):
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as root:
            config = replace(
                postgresql_application_config(
                    deterministic_stage_executors=True,
                    background_execution_mode="external",
                ),
                projects_root=root,
            )
            app_a = create_application_container(
                config=config,
                overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
            )
            plaintext = bootstrap_test_api_key(app_a)
            client_context = TestClient(create_fastapi_app(container=app_a))
            raw_client = client_context.__enter__()
            client = AuthenticatedTestClient(raw_client, auth_headers(plaintext))
            fixture = qs_tests.PropertyQsDurableWorkerResolutionTests(methodName="runTest")
            fixture.container = app_a
            fixture.client = client
            try:
                study = fixture._ready_study("p1-25c-postgresql-pause")
                fixture._activate(study)
                self.assertTrue(app_a.worker_execution_service.process_once("p1-25c-a"))
                run_a = app_a.workflow_service.get_workflow_run(study.run_id)
                paused_a = next(task for task in run_a.tasks if task.status.value == "paused")
                snapshot_a = app_a.workflow_service.get_task_results(study.run_id)[paused_a.id]
                self.assertEqual(snapshot_a["definition_id"], "quant_findings")
                self.assertIn("quantitative", snapshot_a["shared_state"])
                self.assertIn(
                    SEMANTIC_AUTHORITY_FINGERPRINT_KEY,
                    snapshot_a["shared_state"]["quantitative"],
                )
            finally:
                client_context.__exit__(None, None, None)
                app_a.shutdown()

            app_b = create_application_container(
                config=config,
                overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
            )
            try:
                run_b = app_b.workflow_service.get_workflow_run(study.run_id)
                self.assertEqual(run_b.status.value, "paused")
                paused_b = next(task for task in run_b.tasks if task.status.value == "paused")
                self.assertEqual(paused_b.id, paused_a.id)
                self.assertEqual(
                    app_b.workflow_service.get_task_results(study.run_id)[paused_b.id],
                    snapshot_a,
                )
                restored = app_b.durable_workflow_service._load_context(study.run_id)
                self.assertIsInstance(
                    restored.services["quantitative_stage_service"],
                    RealQuantitativeStageService,
                )
            finally:
                app_b.shutdown()

    def test_authorization_consumption_survives_fresh_engine_and_blocks_duplicate(self):
        project = ProjectFactory().create("P1-25C durable authorization")
        project.id = "p1-25c-project"
        PostgreSQLProjectRepository(self.session_factory).create(project)
        digest = Sha256DigestProvider()
        safe = {
            "dataset_version_id": "dataset-v1",
            "dataset_fingerprint": "dataset-fp",
            "codebook_version_id": "codebook-v1",
            "analysis_manifest_record_id": "analysis-v1",
        }
        state_a = QuantitativeStateService(
            repository=PostgreSQLQuantitativeStateRepository(self.session_factory),
            digest_provider=digest,
        )
        approvals_a = QuantitativeApprovalService(state_a, digest)
        authority = approvals_a.semantic_authority_fingerprint(
            project_id=project.id, run_id="p1-25c-run", safe_state=safe
        )
        grant = approvals_a.grant_semantic_pipeline(
            project_id=project.id,
            run_id="p1-25c-run",
            quantitative_authority_fingerprint=authority,
            actor_id="reviewer",
            authorized_at="2026-09-14T10:00:00+00:00",
            rationale="authorized",
        )

        engine_b = create_test_engine()
        try:
            state_b = QuantitativeStateService(
                repository=PostgreSQLQuantitativeStateRepository(
                    DatabaseSessionFactory(engine_b)
                ),
                digest_provider=digest,
            )
            approvals_b = QuantitativeApprovalService(state_b, digest)
            consumed = approvals_b.require_and_consume_semantic_pipeline(
                project_id=project.id,
                run_id="p1-25c-run",
                safe_state=dict(
                    safe, **{SEMANTIC_AUTHORITY_FINGERPRINT_KEY: authority}
                ),
            )
            self.assertEqual(consumed.authorization_id, grant.authorization_id)
        finally:
            dispose_test_engine(engine_b)

        engine_c = create_test_engine()
        try:
            approvals_c = QuantitativeApprovalService(
                QuantitativeStateService(
                    repository=PostgreSQLQuantitativeStateRepository(
                        DatabaseSessionFactory(engine_c)
                    ),
                    digest_provider=digest,
                ),
                digest,
            )
            with self.assertRaisesRegex(QuantitativeWorkflowError, "already consumed"):
                approvals_c.require_and_consume_semantic_pipeline(
                    project_id=project.id,
                    run_id="p1-25c-run",
                    safe_state=dict(
                        safe, **{SEMANTIC_AUTHORITY_FINGERPRINT_KEY: authority}
                    ),
                )
        finally:
            dispose_test_engine(engine_c)


if __name__ == "__main__":
    unittest.main()