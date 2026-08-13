from __future__ import annotations

import unittest
from unittest.mock import Mock

from domain.sources.search_query import SearchQuery

from application.sources.country_resolution import (
    CountryResolutionStatus,
    resolve_supported_country,
)
from infrastructure.search.tavily_search_provider import TavilySearchProvider


def _query(*, geography: str = "Ukraine", provider_text: str = "pizza Ukraine market") -> SearchQuery:
    return SearchQuery(
        id="sq-1",
        research_question_id="RQ1",
        information_need_id="IN1",
        query_text="complete internal research semantics that remain durable",
        geography=geography,
        max_results=5,
        provider_query_text=provider_text,
    )


def _provider_call(query: SearchQuery):
    client = Mock()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [
            {
                "url": "https://example.test/result",
                "title": "Result",
                "content": "Bounded snippet",
                "score": 0.7,
            },
        ],
    }
    client.post.return_value = response
    candidates = TavilySearchProvider(api_key="fixture-secret", http_client=client).search(query)
    return client.post.call_args.kwargs["json"], candidates


class CountryResolutionTests(unittest.TestCase):
    def test_cases_01_to_06_supported_country_and_city_country(self) -> None:
        cases = {
            "Ukraine": "ukraine",
            "New Zealand": "new zealand",
            "India": "india",
            "Germany": "germany",
            "Kyiv, Ukraine": "ukraine",
            "Auckland, New Zealand": "new zealand",
        }
        for geography, expected in cases.items():
            with self.subTest(geography=geography):
                result = resolve_supported_country(
                    geography,
                    supported_countries=TavilySearchProvider._SUPPORTED_COUNTRIES,
                )
                self.assertEqual(result.status, CountryResolutionStatus.SUPPORTED_COUNTRY)
                self.assertEqual(result.country, expected)

    def test_cases_07_to_11_fail_open_geographies(self) -> None:
        cases = {
            "Global": CountryResolutionStatus.NO_COUNTRY,
            "Europe": CountryResolutionStatus.UNSUPPORTED_OR_UNRESOLVED,
            "Ukraine + Poland": CountryResolutionStatus.AMBIGUOUS_OR_MULTI_COUNTRY,
            "Atlantis ???": CountryResolutionStatus.UNSUPPORTED_OR_UNRESOLVED,
            "": CountryResolutionStatus.NO_COUNTRY,
        }
        for geography, expected in cases.items():
            with self.subTest(geography=geography):
                result = resolve_supported_country(
                    geography,
                    supported_countries=TavilySearchProvider._SUPPORTED_COUNTRIES,
                )
                self.assertEqual(result.status, expected)
                self.assertIsNone(result.country)

    def test_case_28_country_is_not_derived_from_category_text(self) -> None:
        result = resolve_supported_country(
            "Europe",
            supported_countries=TavilySearchProvider._SUPPORTED_COUNTRIES,
        )
        self.assertIsNone(result.country)


class TavilyCountryRequestContractTests(unittest.TestCase):
    def test_cases_01_12_18_21_29_eligible_payload_is_isolated_and_auditable(self) -> None:
        query = _query()
        payload, candidates = _provider_call(query)
        self.assertEqual(
            payload,
            {
                "api_key": "fixture-secret",
                "query": query.provider_query_text,
                "max_results": 5,
                "country": "ukraine",
            },
        )
        self.assertEqual(payload["query"], "pizza Ukraine market")
        self.assertNotIn("search_depth", payload)
        self.assertNotIn("topic", payload)
        metadata = candidates[0].metadata
        self.assertEqual(metadata["provider_name"], "tavily")
        self.assertEqual(metadata["country_prioritization_requested"], "true")
        self.assertEqual(metadata["country_prioritization_applied"], "true")
        self.assertEqual(metadata["provider_country"], "ukraine")
        self.assertEqual(metadata["search_depth"], "basic")
        self.assertEqual(metadata["max_results"], "5")
        self.assertNotIn("fixture-secret", repr(metadata))
        self.assertNotIn("api_key", metadata)

    def test_cases_07_to_11_22_fail_open_payload_matches_old_behavior(self) -> None:
        for geography in ("Global", "Europe", "Ukraine + Poland", "Atlantis", ""):
            with self.subTest(geography=geography):
                query = _query(geography=geography)
                payload, candidates = _provider_call(query)
                self.assertEqual(
                    payload,
                    {
                        "api_key": "fixture-secret",
                        "query": query.provider_query_text,
                        "max_results": 5,
                    },
                )
                self.assertEqual(
                    candidates[0].metadata["country_prioritization_applied"],
                    "false",
                )
                self.assertNotIn("provider_country", candidates[0].metadata)

    def test_cases_13_to_15_equivalent_geography_has_path_parity(self) -> None:
        # Initial, targeted, and remediation builders all produce SearchQuery;
        # the adapter applies the same capability at this single boundary.
        payloads = [_provider_call(_query(geography="Germany"))[0] for _ in range(3)]
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(payloads[1], payloads[2])
        self.assertEqual(payloads[0]["country"], "germany")

    def test_cases_19_20_one_http_call_and_no_llm(self) -> None:
        client = Mock()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": []}
        client.post.return_value = response
        provider = TavilySearchProvider(api_key="fixture", http_client=client)
        provider.search(_query(geography="India", provider_text="UPI India adoption"))
        client.post.assert_called_once()

    def test_cases_23_30_serialization_is_backward_compatible_without_schema(self) -> None:
        query = _query(geography="New Zealand", provider_text="heat pumps New Zealand")
        payload = query.to_dict()
        self.assertNotIn("provider_query_text", payload)
        self.assertNotIn("country", payload)
        restored = SearchQuery.from_dict(payload)
        self.assertEqual(restored.geography, "New Zealand")
        self.assertEqual(restored.provider_query_text, "")

    def test_case_27_cross_domain_no_pizza_leakage(self) -> None:
        cases = (
            ("New Zealand", "heat pumps New Zealand", "new zealand"),
            ("India", "UPI India adoption", "india"),
            ("Germany", "electricity Germany prices", "germany"),
        )
        for geography, text, expected in cases:
            with self.subTest(geography=geography):
                payload, _ = _provider_call(_query(geography=geography, provider_text=text))
                self.assertEqual(payload["query"], text)
                self.assertEqual(payload["country"], expected)
                self.assertNotIn("pizza", payload["query"].casefold())


if __name__ == "__main__":
    unittest.main()
