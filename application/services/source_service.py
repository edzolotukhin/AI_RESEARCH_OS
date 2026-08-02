from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.source_ports import SourceRepository
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.sources.provenance_merge import is_successful_acquisition


class SourceService:
    """Application service for durable research source access."""

    def __init__(self, *, source_repository: SourceRepository) -> None:
        self._source_repository = source_repository

    def get_source(self, source_id: str) -> Source:
        source = self._source_repository.get_by_id(source_id)
        if source is None:
            raise EntityNotFoundError(f"Source not found: {source_id}")
        return source

    def list_sources_for_project(
        self,
        project_id: str,
        *,
        research_question_id: str | None = None,
        retrieval_status: RetrievalStatus | None = None,
        workflow_run_id: str | None = None,
    ) -> list[Source]:
        status_value = retrieval_status.value if retrieval_status is not None else None
        return self._source_repository.list_for_project(
            project_id,
            research_question_id=research_question_id,
            retrieval_status=status_value,
            workflow_run_id=workflow_run_id,
        )

    def list_sources_for_run(self, workflow_run_id: str, *, project_id: str) -> list[Source]:
        return self._source_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )

    def count_acquired_for_run(self, project_id: str, workflow_run_id: str) -> int:
        sources = self.list_sources_for_run(workflow_run_id, project_id=project_id)
        return sum(
            1 for source in sources if is_successful_acquisition(source.retrieval_status)
        )

    def run_has_acquired_sources(self, project_id: str, workflow_run_id: str) -> bool:
        return self.count_acquired_for_run(project_id, workflow_run_id) > 0
