from __future__ import annotations

from abc import ABC, abstractmethod

from domain.sources.search_query import SearchQuery
from domain.sources.retrieval_arm import RetrievalArm
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate


class SearchProvider(ABC):
    """Provider-neutral web search port."""

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        """Execute a search query and return ranked source candidates."""

    def supports_retrieval_arm(
        self,
        arm: RetrievalArm,
        query: SearchQuery,
    ) -> bool:
        """Whether this provider can safely execute the semantic arm."""
        return arm is RetrievalArm.BASELINE


class SourceRetriever(ABC):
    """Acquires document content for a source candidate."""

    def known_unsupported_url(self, url: str) -> bool:
        """Whether the URL unambiguously names a format this retriever cannot read."""
        return False

    @abstractmethod
    def retrieve(self, candidate: SourceCandidate) -> Source:
        """
        Fetch and extract content for a candidate URL.

        Returns a Source with retrieval_status reflecting outcome.
        Does not persist.
        """


class SourceRepository(ABC):
    """Persistence port for durable research sources."""

    def resolve_terminal_identity(self, project_id, terminal_url):
        from application.sources.source_identity import terminal_resource_key
        return terminal_resource_key(project_id, terminal_url)

    def find_latest_for_landing(self, project_id, landing_url):
        return self.get_by_canonical_url_for_project(project_id, landing_url)

    def find_latest_content_revision(self, project_id, resource_key):
        rows = [s for s in self.list_for_project(project_id) if s.terminal_resource_key == resource_key]
        return max(rows, key=lambda s: (s.content_revision, s.retrieved_at, s.id), default=None)

    def find_matching_revision(self, project_id, resource_key, raw_checksum, extraction_revision, *, raw_checksum_kind="sha256-bytes"):
        return next((s for s in self.list_for_project(project_id) if s.terminal_resource_key == resource_key and s.raw_content_checksum == raw_checksum and s.raw_checksum_kind == raw_checksum_kind and s.extraction_revision == extraction_revision), None)

    def create_immutable_revision(self, source):
        raise NotImplementedError

    def persist_acquisition_path(self, path):
        raise NotImplementedError

    @abstractmethod
    def create(self, source: Source) -> int:
        """Persist a new source. Returns version."""

    @abstractmethod
    def save(
        self,
        source: Source,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Update an existing source. Returns version."""

    @abstractmethod
    def get_by_id(self, source_id: str) -> Source | None:
        pass

    @abstractmethod
    def get_by_canonical_url_for_project(
        self,
        project_id: str,
        canonical_url: str,
    ) -> Source | None:
        pass

    @abstractmethod
    def list_for_project(
        self,
        project_id: str,
        *,
        research_question_id: str | None = None,
        retrieval_status: str | None = None,
        workflow_run_id: str | None = None,
    ) -> list[Source]:
        pass
