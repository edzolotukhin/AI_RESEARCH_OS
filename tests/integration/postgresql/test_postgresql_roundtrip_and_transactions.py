from __future__ import annotations

import unittest

from application.config import ApplicationConfig
from application.persistence.exceptions import DuplicateEntityError
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from tests.integration.postgresql.fixtures import (
    assert_projects_semantically_equal,
    build_rich_project,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    dispose_test_engine,
    integration_tests_enabled,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLAggregateRoundTripIntegrationTests(PostgreSQLIntegrationTestCase):
    def test_project_full_round_trip_excludes_runs_collection(self) -> None:
        """
        Project.runs is intentionally excluded from persistence.

        Workflow runs are queried through WorkflowRunRepository.list_for_project.
        """
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        repository = PostgreSQLProjectRepository(self.session_factory)
        project = build_rich_project()

        repository.create(project)
        loaded = repository.get_by_id(project.id)

        assert loaded is not None
        assert_projects_semantically_equal(project, loaded)
        self.assertEqual(loaded.runs, [])

    def test_workflow_run_full_round_trip(self) -> None:
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )
        from infrastructure.persistence.postgresql.models.workflow_run_model import (
            WorkflowRunModel,
        )
        from sqlalchemy.orm import Session

        project_repository = PostgreSQLProjectRepository(self.session_factory)
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)

        project = build_rich_project(project_id="project-run-rich")
        project_repository.create(project)

        template = WorkflowTemplate(
            id="template-rich",
            name="Rich Template",
            task_definitions=[
                TaskDefinition(
                    id="def-a",
                    name="Task A",
                    executor_id="planner",
                    executor_type=ExecutorType.AGENT,
                ),
                TaskDefinition(
                    id="def-b",
                    name="Task B",
                    executor_id="search",
                    executor_type=ExecutorType.AGENT,
                    depends_on=["def-a"],
                ),
            ],
        )
        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template,
            run_id="run-rich-1",
            project_id=project.id,
        )
        run_repository.create(workflow_run, project_id=project.id)

        with Session(self.engine) as session:
            stored_version = session.get(WorkflowRunModel, "run-rich-1").version
        self.assertEqual(stored_version, 0)

        task_id = workflow_run.tasks[0].id
        workflow_run.tasks[0].ready()
        workflow_run.tasks[0].start()
        workflow_run.tasks[0].complete()
        workflow_run.ready()

        new_version = run_repository.save(
            workflow_run,
            expected_version=0,
            task_results={task_id: {"summary": "completed", "score": 9}},
        )
        self.assertEqual(new_version, 1)

        loaded = run_repository.get_by_id("run-rich-1")
        assert loaded is not None

        self.assertEqual(loaded.id, "run-rich-1")
        self.assertEqual(loaded.project_id, project.id)
        self.assertEqual(loaded.workflow_template_id, template.id)
        self.assertEqual(loaded.status, WorkflowStatus.READY)
        self.assertEqual(len(loaded.tasks), 2)
        self.assertEqual(loaded.tasks[0].status, TaskStatus.COMPLETED)
        self.assertEqual(loaded.tasks[0].executor_id, "planner")
        self.assertEqual(loaded.tasks[0].executor_type, ExecutorType.AGENT)
        self.assertEqual(loaded.tasks[1].depends_on, ["def-a"])
        self.assertEqual(
            loaded.dependency_graph.dependencies_of(loaded.tasks[1].id),
            (loaded.tasks[0].id,),
        )
        loaded.validate_dependency_graph()
        self.assertEqual(
            run_repository.get_task_results("run-rich-1"),
            {task_id: {"summary": "completed", "score": 9}},
        )

        task_ids = [task.id for task in loaded.tasks]
        self.assertEqual(len(task_ids), len(set(task_ids)))


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLTransactionIntegrationTests(PostgreSQLIntegrationTestCase):
    def test_duplicate_workflow_run_create_rolls_back(self) -> None:
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.task_definition import TaskDefinition
        from domain.workflow_template import WorkflowTemplate
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session
        from infrastructure.persistence.postgresql.models.task_model import (
            WorkflowTaskModel,
        )

        project_repository = PostgreSQLProjectRepository(self.session_factory)
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        project = build_rich_project(project_id="project-tx")
        project_repository.create(project)

        template = WorkflowTemplate(
            id="template-tx",
            name="Tx",
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
            run_id="run-tx",
            project_id=project.id,
        )
        run_repository.create(workflow_run, project_id=project.id)

        with self.assertRaises(DuplicateEntityError):
            run_repository.create(workflow_run, project_id=project.id)

        with Session(self.engine) as session:
            task_count = session.scalar(
                select(func.count()).select_from(WorkflowTaskModel)
            )
        self.assertEqual(task_count, 1)

    def test_duplicate_execution_log_append_is_noop_and_session_usable(self) -> None:
        from application.persistence.records import ExecutionLogEntry
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.task_definition import TaskDefinition
        from domain.workflow_template import WorkflowTemplate
        from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
            PostgreSQLExecutionLogStore,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )

        project_repository = PostgreSQLProjectRepository(self.session_factory)
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        log_store = PostgreSQLExecutionLogStore(self.session_factory)

        project = build_rich_project(project_id="project-log-tx")
        project_repository.create(project)
        template = WorkflowTemplate(
            id="template-log-tx",
            name="Log",
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
            run_id="run-log-tx",
            project_id=project.id,
        )
        run_repository.create(workflow_run, project_id=project.id)

        entry = ExecutionLogEntry(
            event_id="event-tx-dup",
            run_id="run-log-tx",
            event_type="task.started",
            timestamp="2026-07-31T10:00:00+00:00",
        )
        log_store.append(entry)
        log_store.append(entry)

        follow_up = ExecutionLogEntry(
            event_id="event-tx-follow-up",
            run_id="run-log-tx",
            event_type="task.completed",
            timestamp="2026-07-31T10:00:01+00:00",
        )
        log_store.append(follow_up)

        entries = log_store.list_for_run("run-log-tx")
        self.assertEqual([item.event_id for item in entries], [
            "event-tx-dup",
            "event-tx-follow-up",
        ])

    def test_stale_workflow_run_save_does_not_partially_update_tasks(self) -> None:
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.task_definition import TaskDefinition
        from domain.workflow_template import WorkflowTemplate
        from application.persistence.exceptions import ConcurrentModificationError
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )

        project_repository = PostgreSQLProjectRepository(self.session_factory)
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        project = build_rich_project(project_id="project-stale")
        project_repository.create(project)

        template = WorkflowTemplate(
            id="template-stale",
            name="Stale",
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
            run_id="run-stale",
            project_id=project.id,
        )
        run_repository.create(workflow_run, project_id=project.id)
        run_repository.save(workflow_run, expected_version=0)

        original_status = workflow_run.tasks[0].status
        workflow_run.tasks[0].ready()

        with self.assertRaises(ConcurrentModificationError):
            run_repository.save(workflow_run, expected_version=0)

        reloaded = run_repository.get_by_id("run-stale")
        assert reloaded is not None
        self.assertEqual(reloaded.tasks[0].status, original_status)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLCompositionRootSmokeTests(PostgreSQLIntegrationTestCase):
    def test_composition_root_selects_postgresql_adapters(self) -> None:
        import os

        from application.composition_root import create_application
        from application.services.project_service import ProjectService
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        database_url = os.environ["DATABASE_URL_TEST"]
        config = ApplicationConfig(
            persistence_backend="postgresql",
            database_url=database_url,
        )

        agency = create_application(config=config)
        project_repository = agency._project_service._project_repository
        assert isinstance(project_repository, PostgreSQLProjectRepository)
        self.addCleanup(
            dispose_test_engine,
            project_repository._session_factory.engine,
        )

        self.assertIsInstance(agency._project_service, ProjectService)
        self.assertIsInstance(project_repository, PostgreSQLProjectRepository)

        project = agency.create_project("Compose Root Project")
        loaded = agency._project_service.get_project(project.id)
        self.assertEqual(loaded.name, "Compose Root Project")


if __name__ == "__main__":
    unittest.main()
