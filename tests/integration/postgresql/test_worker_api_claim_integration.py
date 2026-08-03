"""API submission to separate worker process_once claim path."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
    PostgreSQLExecutionLogStore,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
    PostgreSQLWorkflowRunExecutionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
    PostgreSQLWorkflowRunRepository,
)

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, open_test_client
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
    postgresql_application_config,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL API→worker claim tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class PostgreSQLApiWorkerClaimIntegrationTests(PostgreSQLIntegrationTestCase):

    def test_post_research_is_claimed_by_separate_worker_process_once(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        api_container = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(api_container)
        self.addCleanup(api_container.shutdown)
        raw_client, _, context = open_test_client(api_container)
        self.addCleanup(lambda: close_test_client(context, api_container))
        client = AuthenticatedTestClient(
            raw_client,
            auth_headers(api_container._test_api_key_plaintext),
        )

        project_id = client.post("/projects", json={"name": "API Worker Claim"}).json()[
            "id"
        ]
        started = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        )
        self.assertEqual(started.status_code, 202)
        payload = started.json()
        run_id = payload["run_id"]
        self.assertEqual(payload["status"], "created")

        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        persisted = run_repository.get_by_id(run_id)
        assert persisted is not None
        self.assertEqual(persisted.status, WorkflowStatus.CREATED)
        execution_repository = PostgreSQLWorkflowRunExecutionRepository(
            self.session_factory,
        )
        self.assertIsNone(execution_repository.get_lease(run_id))

        worker_container = create_application_container(
            config=postgresql_application_config(
                background_execution_mode="external",
                deterministic_stage_executors=True,
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(worker_container.shutdown)
        assert worker_container.worker_execution_service is not None
        worker_container.agency.initialize()
        worker_id = "integration-worker-claim"
        processed = worker_container.worker_execution_service.process_once(worker_id)
        self.assertTrue(processed)

        log_store = PostgreSQLExecutionLogStore(self.session_factory)
        event_types = [
            entry.event_type for entry in log_store.list_for_run(run_id)
        ]
        self.assertIn("workflow_created", event_types)
        self.assertIn("workflow_started", event_types)

        reloaded = run_repository.get_by_id(run_id)
        assert reloaded is not None
        collect = next(
            task
            for task in reloaded.tasks
            if task.definition_id == "task-collect-evidence"
        )
        self.assertNotEqual(collect.status, TaskStatus.CREATED)


if __name__ == "__main__":
    unittest.main()
