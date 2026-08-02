from __future__ import annotations

from datetime import datetime, timezone

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate

from application.ports.source_ports import SearchProvider, SourceRetriever


class DeterministicSearchProvider(SearchProvider):
    """
    Explicit test/smoke search provider.

    Returns predictable candidates including duplicate URLs across queries.
    """

    _FIXTURES: dict[str, list[dict[str, str]]] = {
        "default": [
            {
                "url": "https://example.com/market-report?utm_source=test",
                "title": "Example Market Report",
                "snippet": "Market overview snippet.",
            },
            {
                "url": "https://research.example.org/brand-health",
                "title": "Brand Health Study",
                "snippet": "Brand health overview.",
            },
            {
                "url": "https://blocked.example/internal",
                "title": "Blocked Source",
                "snippet": "Should fail retrieval.",
            },
        ],
    }

    def __init__(self, *, fixture_key: str = "default") -> None:
        self._fixture_key = fixture_key

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        rows = list(self._FIXTURES.get(self._fixture_key, self._FIXTURES["default"]))
        if "duplicate" in query.information_need_id:
            rows.append(
                {
                    "url": "https://example.com/market-report/",
                    "title": "Duplicate Market Report",
                    "snippet": "Same canonical URL as first result.",
                },
            )
        candidates: list[SourceCandidate] = []
        for index, row in enumerate(rows):
            candidates.append(
                SourceCandidate(
                    provider="deterministic",
                    provider_result_id=f"{query.id}-{index}",
                    url=row["url"],
                    title=row["title"],
                    snippet=row["snippet"],
                    source_type="web",
                    rank=index + 1,
                    query_id=query.id,
                ),
            )
        return candidates


class DeterministicSourceRetriever(SourceRetriever):
    """Explicit test/smoke retriever with predictable HTML/text outcomes."""

    _HTML = """
    <html><head><title>Example Market Report</title></head>
    <body><script>ignore()</script><p>Acquired market report body text.</p></body>
    </html>
    """

    def retrieve(self, candidate: SourceCandidate) -> Source:
        now = datetime.now(timezone.utc).isoformat()
        if "blocked.example" in candidate.url:
            return Source(
                id="",
                project_id="",
                url=candidate.url,
                canonical_url=candidate.url,
                title=candidate.title,
                retrieved_at=now,
                retrieval_status=RetrievalStatus.FAILED,
                metadata={"reason": "Deterministic retrieval failure"},
            )
        if candidate.url.endswith(".pdf"):
            return Source(
                id="",
                project_id="",
                url=candidate.url,
                canonical_url=candidate.url,
                title=candidate.title,
                retrieved_at=now,
                content_type="application/pdf",
                retrieval_status=RetrievalStatus.UNSUPPORTED,
                metadata={"reason": "PDF unsupported in deterministic retriever"},
            )
        return Source(
            id="",
            project_id="",
            url=candidate.url,
            canonical_url=candidate.url,
            title=candidate.title,
            retrieved_at=now,
            content_type="text/html",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="Acquired market report body text.",
            metadata={"deterministic": "true"},
        )
