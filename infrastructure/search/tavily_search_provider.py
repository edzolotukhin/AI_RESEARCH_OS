from __future__ import annotations

from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate

from application.ports.source_ports import SearchProvider
from application.sources.country_resolution import resolve_supported_country
from application.sources.exceptions import SearchConfigurationError, SearchProviderError


class TavilySearchProvider(SearchProvider):
    """Tavily web search adapter."""

    _API_URL = "https://api.tavily.com/search"
    # Tavily Search API country enum (general topic). Kept at the provider
    # capability boundary; Research/Search domain semantics remain neutral.
    _SUPPORTED_COUNTRIES = frozenset(
        {
            "afghanistan", "albania", "algeria", "andorra", "angola",
            "argentina", "armenia", "australia", "austria", "azerbaijan",
            "bahamas", "bahrain", "bangladesh", "barbados", "belarus",
            "belgium", "belize", "benin", "bhutan", "bolivia",
            "bosnia and herzegovina", "botswana", "brazil", "brunei",
            "bulgaria", "burkina faso", "burundi", "cambodia", "cameroon",
            "canada", "cape verde", "central african republic", "chad",
            "chile", "china", "colombia", "comoros", "congo", "costa rica",
            "croatia", "cuba", "cyprus", "czech republic", "denmark",
            "djibouti", "dominican republic", "ecuador", "egypt", "el salvador",
            "equatorial guinea", "eritrea", "estonia", "ethiopia", "fiji",
            "finland", "france", "gabon", "gambia", "georgia", "germany",
            "ghana", "greece", "guatemala", "guinea", "haiti", "honduras",
            "hungary", "iceland", "india", "indonesia", "iran", "iraq",
            "ireland", "israel", "italy", "jamaica", "japan", "jordan",
            "kazakhstan", "kenya", "kuwait", "kyrgyzstan", "latvia", "lebanon",
            "lesotho", "liberia", "libya", "liechtenstein", "lithuania",
            "luxembourg", "madagascar", "malawi", "malaysia", "maldives",
            "mali", "malta", "mauritania", "mauritius", "mexico", "moldova",
            "monaco", "mongolia", "montenegro", "morocco", "mozambique",
            "myanmar", "namibia", "nepal", "netherlands", "new zealand",
            "nicaragua", "niger", "nigeria", "north korea", "north macedonia",
            "norway", "oman", "pakistan", "panama", "papua new guinea",
            "paraguay", "peru", "philippines", "poland", "portugal", "qatar",
            "romania", "russia", "rwanda", "saudi arabia", "senegal", "serbia",
            "singapore", "slovakia", "slovenia", "somalia", "south africa",
            "south korea", "south sudan", "spain", "sri lanka", "sudan",
            "sweden", "switzerland", "syria", "taiwan", "tajikistan",
            "tanzania", "thailand", "togo", "trinidad and tobago", "tunisia",
            "turkey", "turkmenistan", "uganda", "ukraine",
            "united arab emirates", "united kingdom", "united states", "uruguay",
            "uzbekistan", "venezuela", "vietnam", "yemen", "zambia", "zimbabwe",
        },
    )

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
        country_resolution = resolve_supported_country(
            query.geography,
            supported_countries=self._SUPPORTED_COUNTRIES,
        )
        payload = {
            "api_key": self._api_key,
            "query": query.provider_query_text or query.query_text,
            "max_results": query.max_results,
        }
        if country_resolution.country:
            payload["country"] = country_resolution.country
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
            metadata = self._candidate_audit_metadata(
                query=query,
                country=country_resolution.country,
                resolution_status=country_resolution.status.value,
            )
            score = item.get("score")
            if score is not None:
                metadata["provider_score"] = str(score)
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
                    metadata=metadata,
                ),
            )
        return candidates

    @staticmethod
    def _candidate_audit_metadata(
        *,
        query: SearchQuery,
        country: str | None,
        resolution_status: str,
    ) -> dict[str, str]:
        applied = str(country is not None).lower()
        metadata = {
            "provider_name": "tavily",
            "country_prioritization_requested": applied,
            "country_prioritization_applied": applied,
            "country_resolution_status": resolution_status,
            "search_depth": "basic",
            "max_results": str(query.max_results),
        }
        if country:
            metadata["provider_country"] = country
        return metadata

    def _default_client(self):
        import httpx

        return httpx.Client(timeout=15.0)
