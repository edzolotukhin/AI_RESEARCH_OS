from __future__ import annotations

from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate

from application.ports.source_ports import SearchProvider
from application.sources.exceptions import SearchConfigurationError, SearchProviderError


class TavilySearchProvider(SearchProvider):
    """Tavily web search adapter."""

    _API_URL = "https://api.tavily.com/search"

    def __init__(
        self,
        *,
        api_key: str | None,
        http_client=None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._http_client = http_client

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        if not self._api_key:
            raise SearchConfigurationError(
                "SEARCH_API_KEY is required when SEARCH_PROVIDER=tavily",
            )
        client = self._http_client or self._default_client()
        payload = {
            "api_key": self._api_key,
            "query": query.query_text,
            "max_results": query.max_results,
        }
        try:
            response = client.post(self._API_URL, json=payload)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise SearchProviderError(
                f"Tavily search failed for query {query.id}: {exc}",
            ) from exc

        body = response.json()
        results = body.get("results") or []
        candidates: list[SourceCandidate] = []
        for index, item in enumerate(results):
            url = item.get("url")
            if not url:
                continue
            candidates.append(
                SourceCandidate(
                    provider="tavily",
                    provider_result_id=str(item.get("id") or ""),
                    url=str(url),
                    title=str(item.get("title") or ""),
                    snippet=str(item.get("content") or item.get("snippet") or ""),
                    published_at=item.get("published_date"),
                    source_type="web",
                    rank=index + 1,
                    query_id=query.id,
                ),
            )
        return candidates

    def _default_client(self):
        import httpx

        return httpx.Client(timeout=15.0)
