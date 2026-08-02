from __future__ import annotations

import threading

from application.persistence.exceptions import ConcurrentModificationError
from application.ports.source_ports import SourceRepository
from application.sources.exceptions import DuplicateSourceError
from domain.sources.source import Source


class InMemorySourceRepository(SourceRepository):
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._versions: dict[str, int] = {}
        self._lock = threading.Lock()

    def create(self, source: Source) -> int:
        with self._lock:
            key = (source.project_id, source.canonical_url)
            for existing in self._sources.values():
                if (existing.project_id, existing.canonical_url) == key:
                    raise DuplicateSourceError(
                        f"Source already exists for project/canonical URL: {key}",
                    )
            self._sources[source.id] = source
            self._versions[source.id] = 1
            source.version = 1
            return 1

    def save(
        self,
        source: Source,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._lock:
            current = self._sources.get(source.id)
            if current is None:
                raise ValueError(f"Source not found: {source.id}")
            current_version = self._versions[source.id]
            if expected_version is not None and expected_version != current_version:
                raise ConcurrentModificationError(
                    f"Source {source.id} version mismatch: "
                    f"expected {expected_version}, got {current_version}",
                )
            self._sources[source.id] = source
            new_version = current_version + 1
            self._versions[source.id] = new_version
            source.version = new_version
            return new_version

    def get_by_id(self, source_id: str) -> Source | None:
        with self._lock:
            return self._sources.get(source_id)

    def get_by_canonical_url_for_project(
        self,
        project_id: str,
        canonical_url: str,
    ) -> Source | None:
        with self._lock:
            for source in self._sources.values():
                if (
                    source.project_id == project_id
                    and source.canonical_url == canonical_url
                ):
                    return source
            return None

    def list_for_project(
        self,
        project_id: str,
        *,
        research_question_id: str | None = None,
        retrieval_status: str | None = None,
        workflow_run_id: str | None = None,
    ) -> list[Source]:
        with self._lock:
            sources = [
                source
                for source in self._sources.values()
                if source.project_id == project_id
            ]
        if workflow_run_id is not None:
            sources = [
                source
                for source in sources
                if workflow_run_id in source.workflow_run_refs
            ]
        if research_question_id is not None:
            sources = [
                source
                for source in sources
                if research_question_id in source.research_question_refs
            ]
        if retrieval_status is not None:
            sources = [
                source
                for source in sources
                if source.retrieval_status.value == retrieval_status
            ]
        return sorted(sources, key=lambda item: item.id)
