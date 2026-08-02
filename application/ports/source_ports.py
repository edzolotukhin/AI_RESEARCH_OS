from __future__ import annotations

from abc import ABC, abstractmethod

from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate


class SearchProvider(ABC):
    """Provider-neutral web search port."""

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        """Execute a search query and return ranked source candidates."""


class SourceRetriever(ABC):
    """Acquires document content for a source candidate."""

    @abstractmethod
    def retrieve(self, candidate: SourceCandidate) -> Source:
        """
        Fetch and extract content for a candidate URL.

        Returns a Source with retrieval_status reflecting outcome.
        Does not persist.
        """


class SourceRepository(ABC):
    """Persistence port for durable research sources."""

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
