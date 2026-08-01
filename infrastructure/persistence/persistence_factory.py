from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from infrastructure.persistence.file.file_project_repository import (
    FileProjectRepository,
)
from infrastructure.persistence.memory.in_memory_artifact_repository import (
    InMemoryArtifactRepository,
)
from infrastructure.persistence.memory.in_memory_execution_log_store import (
    InMemoryExecutionLogStore,
)
from infrastructure.persistence.memory.in_memory_knowledge_repository import (
    InMemoryKnowledgeRepository,
)
from infrastructure.persistence.memory.in_memory_project_repository import (
    InMemoryProjectRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_execution_repository import (
    InMemoryWorkflowRunExecutionRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_template_repository import (
    InMemoryWorkflowTemplateRepository,
)
from infrastructure.persistence.postgresql.config import PostgreSQLConfig
from infrastructure.persistence.postgresql.database import create_database_engine
from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
    PostgreSQLArtifactRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_execution_log_store import (
    PostgreSQLExecutionLogStore,
)
from infrastructure.persistence.postgresql.repositories.postgresql_knowledge_repository import (
    PostgreSQLKnowledgeRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
    PostgreSQLWorkflowRunExecutionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
    PostgreSQLWorkflowRunRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import (
    PostgreSQLWorkflowTemplateRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


@dataclass(frozen=True)
class PersistenceBundle:
    project_repository: object
    workflow_template_repository: object
    workflow_run_repository: object
    workflow_run_execution_repository: object | None
    artifact_repository: object
    knowledge_repository: object
    execution_log_store: object
    engine: Engine | None = None


def resolve_persistence_backend() -> str:
    return os.environ.get("PERSISTENCE_BACKEND", "file").lower()


def build_persistence_bundle(
    *,
    persistence_backend: str | None = None,
    projects_root: str = "agency/projects",
    database_url: str | None = None,
) -> PersistenceBundle:
    backend = (persistence_backend or resolve_persistence_backend()).lower()

    if backend == "memory":
        workflow_run_repository = InMemoryWorkflowRunRepository()
        return PersistenceBundle(
            project_repository=InMemoryProjectRepository(),
            workflow_template_repository=InMemoryWorkflowTemplateRepository(),
            workflow_run_repository=workflow_run_repository,
            workflow_run_execution_repository=InMemoryWorkflowRunExecutionRepository(
                workflow_run_repository,
            ),
            artifact_repository=InMemoryArtifactRepository(),
            knowledge_repository=InMemoryKnowledgeRepository(),
            execution_log_store=InMemoryExecutionLogStore(),
        )

    if backend == "file":
        workflow_run_repository = InMemoryWorkflowRunRepository()
        return PersistenceBundle(
            project_repository=FileProjectRepository(projects_root=projects_root),
            workflow_template_repository=InMemoryWorkflowTemplateRepository(),
            workflow_run_repository=workflow_run_repository,
            workflow_run_execution_repository=None,
            artifact_repository=InMemoryArtifactRepository(),
            knowledge_repository=InMemoryKnowledgeRepository(),
            execution_log_store=InMemoryExecutionLogStore(),
        )

    if backend == "postgresql":
        config = PostgreSQLConfig(
            database_url=database_url or PostgreSQLConfig.from_env().database_url,
        )
        engine = create_database_engine(config.database_url)
        session_factory = DatabaseSessionFactory(engine)
        return PersistenceBundle(
            project_repository=PostgreSQLProjectRepository(session_factory),
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(
                session_factory,
            ),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(session_factory),
            workflow_run_execution_repository=PostgreSQLWorkflowRunExecutionRepository(
                session_factory,
            ),
            artifact_repository=PostgreSQLArtifactRepository(session_factory),
            knowledge_repository=PostgreSQLKnowledgeRepository(session_factory),
            execution_log_store=PostgreSQLExecutionLogStore(session_factory),
            engine=engine,
        )

    raise ValueError(
        f"Unsupported PERSISTENCE_BACKEND: {backend!r}. "
        "Expected one of: file, memory, postgresql."
    )
