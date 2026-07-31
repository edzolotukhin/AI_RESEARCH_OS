from __future__ import annotations

import unittest

from tests.application.ports.test_project_repository_contract import (
    ExecutionLogStoreContractTests,
    ProjectRepositoryContractTests,
)
from tests.application.ports.test_repository_contracts import (
    ArtifactRepositoryContractTests,
    KnowledgeRepositoryContractTests,
    WorkflowTemplateRepositoryContractTests,
)
from tests.application.ports.test_workflow_run_repository_contract import (
    WorkflowRunRepositoryContractTests,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLRepositoryContractTestCase,
    integration_tests_enabled,
)


def _seed_project(session_factory, project_id: str = "project-1") -> None:
    from domain.factories.project_factory import ProjectFactory
    from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
        PostgreSQLProjectRepository,
    )

    project = ProjectFactory().create("Contract Project")
    project.id = project_id
    PostgreSQLProjectRepository(session_factory).create(project)


def _seed_workflow_run(
    session_factory,
    *,
    project_id: str = "project-1",
    run_id: str = "run-log-contract",
) -> None:
    from domain.factories.task_factory import TaskFactory
    from domain.factories.workflow_run_factory import WorkflowRunFactory
    from domain.task_definition import TaskDefinition
    from domain.value_objects.executor_type import ExecutorType
    from domain.workflow_template import WorkflowTemplate
    from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
        PostgreSQLWorkflowRunRepository,
    )

    template = WorkflowTemplate(
        id="template-log-contract",
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
        run_id=run_id,
        project_id=project_id,
    )
    PostgreSQLWorkflowRunRepository(session_factory).create(
        workflow_run,
        project_id=project_id,
    )


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLProjectRepositoryContractTests(
    ProjectRepositoryContractTests,
    PostgreSQLRepositoryContractTestCase,
):
    def build_repository(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )

        return PostgreSQLProjectRepository(self.fresh_session_factory())


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLWorkflowRunRepositoryContractTests(
    WorkflowRunRepositoryContractTests,
    PostgreSQLRepositoryContractTestCase,
):
    def build_repository(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )

        session_factory = self.fresh_session_factory()
        _seed_project(session_factory, project_id="project-1")
        _seed_project(session_factory, project_id="project-list")
        _seed_project(session_factory, project_id="project-version")
        return PostgreSQLWorkflowRunRepository(session_factory)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLWorkflowTemplateRepositoryContractTests(
    WorkflowTemplateRepositoryContractTests,
    PostgreSQLRepositoryContractTestCase,
):
    def build_repository(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import (
            PostgreSQLWorkflowTemplateRepository,
        )

        session_factory = self.fresh_session_factory()
        _seed_project(session_factory, project_id="project-1")
        return PostgreSQLWorkflowTemplateRepository(session_factory)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLArtifactRepositoryContractTests(
    ArtifactRepositoryContractTests,
    PostgreSQLRepositoryContractTestCase,
):
    def build_repository(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
            PostgreSQLArtifactRepository,
        )

        session_factory = self.fresh_session_factory()
        _seed_project(session_factory, project_id="project-1")
        return PostgreSQLArtifactRepository(session_factory)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLKnowledgeRepositoryContractTests(
    KnowledgeRepositoryContractTests,
    PostgreSQLRepositoryContractTestCase,
):
    def build_repository(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_knowledge_repository import (
            PostgreSQLKnowledgeRepository,
        )

        session_factory = self.fresh_session_factory()
        _seed_project(session_factory, project_id="project-1")
        return PostgreSQLKnowledgeRepository(session_factory)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLExecutionLogStoreContractTests(
    ExecutionLogStoreContractTests,
    PostgreSQLRepositoryContractTestCase,
):
    def build_store(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
            PostgreSQLExecutionLogStore,
        )

        session_factory = self.fresh_session_factory()
        _seed_project(session_factory, project_id="project-1")
        _seed_workflow_run(session_factory, project_id="project-1", run_id="run-1")
        return PostgreSQLExecutionLogStore(session_factory)


if __name__ == "__main__":
    unittest.main()
