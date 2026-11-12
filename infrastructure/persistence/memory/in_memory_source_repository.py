from __future__ import annotations

import threading
from copy import deepcopy
from uuid import uuid4
from application.sources.source_identity import prepare_snapshot, assert_snapshot_unchanged, acquisition_path_digest

from application.persistence.exceptions import ConcurrentModificationError
from application.ports.source_ports import SourceRepository
from application.sources.exceptions import DuplicateSourceError
from domain.sources.source import Source


class InMemorySourceRepository(SourceRepository):
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._versions: dict[str, int] = {}
        self._lock = threading.Lock()
        self._snapshots = {}
        self._paths = {}

    def create(self, source: Source) -> int:
        prepare_snapshot(source)
        with self._lock:
            key = (source.project_id, source.canonical_url)
            for existing in self._sources.values():
                if (existing.project_id, existing.canonical_url) == key:
                    raise DuplicateSourceError(
                        f"Source already exists for project/canonical URL: {key}",
                    )
            source.version = 1
            self._sources[source.id] = deepcopy(source)
            self._versions[source.id] = 1
            self._snapshots[source.id] = deepcopy(source)
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
            assert_snapshot_unchanged(self._snapshots[source.id], source)
            new_version = current_version + 1
            self._versions[source.id] = new_version
            source.version = new_version
            self._sources[source.id] = deepcopy(source)
            return new_version

    def create_immutable_revision(self, source):
        prepare_snapshot(source)
        with self._lock:
            rows = [s for s in self._sources.values() if s.project_id == source.project_id and s.terminal_resource_key == source.terminal_resource_key]
            for row in rows:
                if (row.raw_content_checksum, row.raw_checksum_kind, row.extraction_revision) == (source.raw_content_checksum, source.raw_checksum_kind, source.extraction_revision):
                    return deepcopy(row)
            same = [r for r in rows if source.raw_checksum_kind == "sha256-bytes" and r.raw_checksum_kind == "sha256-bytes" and r.raw_content_checksum == source.raw_content_checksum]
            source.content_revision = same[0].content_revision if same else max((r.content_revision for r in rows), default=0) + 1
            if not source.id or source.id in self._sources:
                source.id = str(uuid4())
            source.version = 1
            self._sources[source.id] = deepcopy(source)
            self._versions[source.id] = 1
            self._snapshots[source.id] = deepcopy(source)
            return source

    def persist_acquisition_path(self, path):
        digest = acquisition_path_digest(project_id=path.project_id, landing_url=path.landing_url, terminal_url=path.terminal_url, navigation_chain=path.navigation_chain)
        with self._lock:
            source = self._sources.get(path.source_id)
            if source is None or source.project_id != path.project_id:
                raise ValueError("Foreign acquisition path")
            self._paths.setdefault((path.workflow_run_id, digest, path.source_id), deepcopy(path))
        return digest

    def list_acquisition_paths(self, project_id, workflow_run_id):
        return [deepcopy(p) for p in self._paths.values() if p.project_id == project_id and p.workflow_run_id == workflow_run_id]

    def get_by_id(self, source_id: str) -> Source | None:
        with self._lock:
            return deepcopy(self._sources.get(source_id))

    def get_by_canonical_url_for_project(
        self,
        project_id: str,
        canonical_url: str,
    ) -> Source | None:
        with self._lock:
            for source in sorted(self._sources.values(), key=lambda s: (s.content_revision, s.retrieved_at, s.id), reverse=True):
                if (
                    source.project_id == project_id
                    and source.canonical_url == canonical_url
                ):
                    return deepcopy(source)
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
        return deepcopy(sorted(sources, key=lambda item: item.id))
