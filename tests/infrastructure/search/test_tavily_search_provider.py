from __future__ import annotations

import unittest
from unittest.mock import Mock

from domain.sources.search_query import SearchQuery

from application.sources.exceptions import SearchConfigurationError, SearchProviderError
from infrastructure.search.tavily_search_provider import TavilySearchProvider


class TavilySearchProviderTests(unittest.TestCase):
    def test_maps_response_to_candidates(self) -> None:
        client = Mock()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [
                {
                    "url": "https://example.com/a",
                    "title": "A",
                    "content": "Snippet A",
                    "score": 0.42,
                },
            ],
        }
        client.post.return_value = response
        provider = TavilySearchProvider(api_key="test-key", http_client=client)
        query = SearchQuery(
            id="sq-1",
            research_question_id="rq-1",
            information_need_id="in-1",
            query_text="brand awareness",
        )
        candidates = provider.search(query)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider, "tavily")
        self.assertEqual(candidates[0].url, "https://example.com/a")
        self.assertEqual(candidates[0].query_id, "sq-1")
        self.assertEqual(candidates[0].metadata.get("provider_score"), "0.42")
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["query"], "brand awareness")
        self.assertEqual(set(payload), {"api_key", "query", "max_results"})

    def test_missing_api_key_raises_on_search(self) -> None:
        provider = TavilySearchProvider(api_key=None)
        query = SearchQuery(
            id="sq-1",
            research_question_id="rq-1",
            information_need_id="in-1",
            query_text="brand awareness",
        )
        with self.assertRaises(SearchConfigurationError):
            provider.search(query)

    def test_http_error_raises_search_provider_error(self) -> None:
        client = Mock()
        client.post.side_effect = RuntimeError("network down")
        provider = TavilySearchProvider(api_key="test-key", http_client=client)
        query = SearchQuery(
            id="sq-1",
            research_question_id="rq-1",
            information_need_id="in-1",
            query_text="brand awareness",
        )
        with self.assertRaises(SearchProviderError):
            provider.search(query)


if __name__ == "__main__":
    unittest.main()
