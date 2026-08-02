from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from infrastructure.persistence.file.file_project_repository import (
    FileProjectRepository,
)
from infrastructure.persistence.memory.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
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
from infrastructure.persistence.memory.in_memory_research_submission_repository import (
    InMemoryResearchSubmissionRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_execution_repository import (
    InMemoryWorkflowRunExecutionRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
    InMemoryWorkflowRunRepository,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.persistence.memory.in_memory_workflow_template_repository import (
    InMemoryWorkflowTemplateRepository,
)
from infrastructure.persistence.postgresql.config import PostgreSQLConfig
from infrastructure.persistence.postgresql.database import create_database_engine
from infrastructure.persistence.postgresql.repositories.postgresql_api_key_repository import (
    PostgreSQLApiKeyRepository,
)
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
from infrastructure.persistence.postgresql.repositories.postgresql_research_submission_repository import (
    PostgreSQLResearchSubmissionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_execution_repository import (
    PostgreSQLWorkflowRunExecutionRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import (
    PostgreSQLWorkflowRunRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
    PostgreSQLFindingRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
    PostgreSQLInsightRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
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
    research_submission_repository: object | None
    api_key_repository: object | None
    artifact_repository: object
    knowledge_repository: object
    source_repository: object
    evidence_repository: object
    finding_repository: object
    insight_repository: object
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
            research_submission_repository=InMemoryResearchSubmissionRepository(),
            api_key_repository=InMemoryApiKeyRepository(),
            artifact_repository=InMemoryArtifactRepository(),
            knowledge_repository=InMemoryKnowledgeRepository(),
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            execution_log_store=InMemoryExecutionLogStore(),
        )

    if backend == "file":
        workflow_run_repository = InMemoryWorkflowRunRepository()
        return PersistenceBundle(
            project_repository=FileProjectRepository(projects_root=projects_root),
            workflow_template_repository=InMemoryWorkflowTemplateRepository(),
            workflow_run_repository=workflow_run_repository,
            workflow_run_execution_repository=None,
            research_submission_repository=None,
            api_key_repository=InMemoryApiKeyRepository(),
            artifact_repository=InMemoryArtifactRepository(),
            knowledge_repository=InMemoryKnowledgeRepository(),
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
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
            research_submission_repository=PostgreSQLResearchSubmissionRepository(
                session_factory,
            ),
            api_key_repository=PostgreSQLApiKeyRepository(session_factory),
            artifact_repository=PostgreSQLArtifactRepository(session_factory),
            knowledge_repository=PostgreSQLKnowledgeRepository(session_factory),
            source_repository=PostgreSQLSourceRepository(session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(session_factory),
            finding_repository=PostgreSQLFindingRepository(session_factory),
            insight_repository=PostgreSQLInsightRepository(session_factory),
            execution_log_store=PostgreSQLExecutionLogStore(session_factory),
            engine=engine,
        )

    raise ValueError(
        f"Unsupported PERSISTENCE_BACKEND: {backend!r}. "
        "Expected one of: file, memory, postgresql."
    )
