from __future__ import annotations

import unittest

from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    create_test_engine,
    integration_tests_enabled,
    register_engine_cleanup,
    require_integration_tests,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLConnectionIntegrationTests(unittest.TestCase):
    def test_can_connect_and_query(self) -> None:
        require_integration_tests()
        engine = create_test_engine()
        register_engine_cleanup(self, engine)

        with engine.connect() as connection:
            result = connection.exec_driver_sql("SELECT 1").scalar_one()

        self.assertEqual(result, 1)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLRepositoryIntegrationTests(PostgreSQLIntegrationTestCase):
    def test_project_round_trip_with_nested_fields(self) -> None:
        from domain.client_request import ClientRequest
        from domain.factories.project_factory import ProjectFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        repository = PostgreSQLProjectRepository(self.session_factory)
        factory = ProjectFactory()
        project = factory.create("Nested Project")
        project.client_request = ClientRequest(
            source="email",
            client_name="Acme",
            contact_person="Jane",
            contact_email="jane@example.com",
            contact_phone="+1",
            message="Need research",
        )

        repository.create(project)
        loaded = repository.get_by_id(project.id)

        assert loaded is not None
        assert loaded.client_request is not None
        self.assertEqual(loaded.client_request.client_name, "Acme")

    def test_execution_log_append_idempotency(self) -> None:
        from application.persistence.records import ExecutionLogEntry
        from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
            PostgreSQLExecutionLogStore,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )
        from domain.factories.project_factory import ProjectFactory
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.task_definition import TaskDefinition
        from domain.value_objects.executor_type import ExecutorType
        from domain.workflow_template import WorkflowTemplate

        project_repository = PostgreSQLProjectRepository(self.session_factory)
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        log_store = PostgreSQLExecutionLogStore(self.session_factory)

        project = ProjectFactory().create("Log Project")
        project_repository.create(project)

        template = WorkflowTemplate(
            id="template-log",
            name="Log Template",
            task_definitions=[
                TaskDefinition(
                    id="task-a",
                    name="Task A",
                    executor_id="planner",
                    executor_type=ExecutorType.AGENT,
                ),
            ],
        )
        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template,
            run_id="run-log",
            project_id=project.id,
        )
        run_repository.create(workflow_run, project_id=project.id)

        entry = ExecutionLogEntry(
            event_id="event-log-1",
            run_id="run-log",
            event_type="task.started",
            timestamp="2026-07-31T10:00:00+00:00",
        )
        log_store.append(entry)
        log_store.append(entry)

        self.assertEqual(len(log_store.list_for_run("run-log")), 1)


if __name__ == "__main__":
    unittest.main()
