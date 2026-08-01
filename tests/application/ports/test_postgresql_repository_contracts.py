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
    """Persist a contract Project through the repository port."""
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
    """Persist a contract WorkflowRun; requires the parent Project to exist."""
    _seed_project(session_factory, project_id=project_id)
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
    session_factory: object

    def build_repository(self):
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )

        self.session_factory = self.fresh_session_factory()
        return PostgreSQLWorkflowRunRepository(self.session_factory)

    def prepare_project(self, project_id: str) -> None:
        _seed_project(self.session_factory, project_id=project_id)


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
        _seed_workflow_run(session_factory, project_id="project-1", run_id="run-1")
        return PostgreSQLExecutionLogStore(session_factory)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL contract tests require POSTGRESQL_INTEGRATION_TESTS=1 "
    "and DATABASE_URL_TEST with 'test' in the database name.",
)
class PostgreSQLWorkflowRunContractPrerequisiteTests(
    PostgreSQLRepositoryContractTestCase,
):
    """
    Regression tests for WorkflowRun contract FK prerequisites.

    workflow_runs.project_id enforces FK → projects.id.
    workflow_runs.workflow_template_id is intentionally NOT an FK: runs store
    the template id from the in-memory aggregate snapshot at creation time.
    """

    def setUp(self) -> None:
        self.session_factory = self.fresh_session_factory()

    def test_prepare_project_persists_parent_before_run_create(self) -> None:
        from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
            PostgreSQLProjectRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )
        from tests.application.ports.test_workflow_run_repository_contract import (
            _template,
        )
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory

        _seed_project(self.session_factory, project_id="project-prereq")

        project_repository = PostgreSQLProjectRepository(self.session_factory)
        loaded = project_repository.get_by_id("project-prereq")
        self.assertIsNotNone(loaded)

        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            _template("template-prereq"),
            run_id="run-prereq",
        )
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)
        run_repository.create(workflow_run, project_id="project-prereq")

        self.assertIsNotNone(run_repository.get_by_id("run-prereq"))

    def test_create_rejects_missing_project_via_foreign_key(self) -> None:
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
            PostgreSQLWorkflowRunRepository,
        )
        from tests.application.ports.test_workflow_run_repository_contract import (
            _template,
        )
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from sqlalchemy.exc import IntegrityError

        workflow_run = WorkflowRunFactory(task_factory=TaskFactory()).create(
            _template("template-missing-project"),
            run_id="run-missing-project",
        )
        run_repository = PostgreSQLWorkflowRunRepository(self.session_factory)

        with self.assertRaises(IntegrityError):
            run_repository.create(workflow_run, project_id="missing-project")


if __name__ == "__main__":
    unittest.main()
