from __future__ import annotations

import unittest
from unittest.mock import Mock

from domain.sources.retrieval_arm import RetrievalArm
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate

from application.ports.source_ports import SearchProvider
from application.sources.provenance_merge import build_discovery_record, merge_discovery_records
from application.sources.exceptions import SearchProviderError
from application.sources.retrieval_portfolio import (
    MAX_INITIAL_RETRIEVAL_ARMS_PER_INFORMATION_NEED,
    derive_initial_retrieval_portfolio,
)
from application.sources.source_acquisition_service import SourceAcquisitionService
from infrastructure.search.tavily_search_provider import TavilySearchProvider


def _query(
    geography: str = "Ukraine",
    *,
    query_id: str = "sq-IN1",
    text: str = "pizza Ukraine market size",
) -> SearchQuery:
    return SearchQuery(
        id=query_id,
        research_question_id="RQ1",
        information_need_id=query_id.removeprefix("sq-"),
        query_text="complete internal semantic query",
        provider_query_text=text,
        geography=geography,
        max_results=5,
        retrieval_arm=RetrievalArm.BASELINE,
    )


class _PortfolioProvider(SearchProvider):
    def __init__(self, rows=None, *, fail_localized: bool = False) -> None:
        self.rows = rows or {}
        self.fail_localized = fail_localized
        self.calls: list[SearchQuery] = []

    def supports_retrieval_arm(self, arm: RetrievalArm, query: SearchQuery) -> bool:
        if arm is RetrievalArm.BASELINE:
            return True
        return arm is RetrievalArm.LOCALIZED and query.geography in {
            "Ukraine", "Kyiv, Ukraine", "New Zealand", "Auckland, New Zealand",
            "India", "Germany",
        }

    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        self.calls.append(query)
        if self.fail_localized and query.retrieval_arm is RetrievalArm.LOCALIZED:
            raise SearchProviderError("localized unavailable")
        values = self.rows.get(query.retrieval_arm, ())
        return [
            SourceCandidate(
                provider="fixture",
                url=url,
                title=title,
                snippet="",
                query_id=query.id,
                rank=rank,
                metadata={"retrieval_arm": (query.retrieval_arm or RetrievalArm.BASELINE).value},
            )
            for rank, (url, title) in enumerate(values, start=1)
        ]


class _BaselineOnlyProvider(SearchProvider):
    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        return []


def _portfolio(query: SearchQuery, provider: SearchProvider) -> tuple[SearchQuery, ...]:
    return derive_initial_retrieval_portfolio(query, supports_arm=provider.supports_retrieval_arm)


def _tavily_payload(query: SearchQuery) -> tuple[dict, list[SourceCandidate]]:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [{"url": "https://example.test/a", "title": "A", "content": "x", "score": 0.5}]
    }
    client = Mock(post=Mock(return_value=response))
    candidates = TavilySearchProvider(api_key="secret", http_client=client).search(query)
    return client.post.call_args.kwargs["json"], candidates


class RetrievalPortfolioDerivationTests(unittest.TestCase):
    def test_cases_01_10_21_to_24_supported_country_has_two_ordered_arms(self) -> None:
        provider = _PortfolioProvider()
        cases = ("Ukraine", "Kyiv, Ukraine", "New Zealand", "Auckland, New Zealand", "India", "Germany")
        for geography in cases:
            with self.subTest(geography=geography):
                query = _query(geography)
                arms = _portfolio(query, provider)
                self.assertEqual([item.retrieval_arm for item in arms], [RetrievalArm.BASELINE, RetrievalArm.LOCALIZED])
                self.assertLessEqual(len(arms), MAX_INITIAL_RETRIEVAL_ARMS_PER_INFORMATION_NEED)
                self.assertEqual(arms[0].query_text, arms[1].query_text)
                self.assertEqual(arms[0].provider_query_text, arms[1].provider_query_text)
                self.assertEqual(arms[0].max_results, arms[1].max_results)

    def test_cases_02_to_06_25_to_27_unsafe_geography_is_baseline_only(self) -> None:
        provider = _PortfolioProvider()
        for geography in ("Global", "Europe", "Ukraine + Poland", "Atlantis", ""):
            with self.subTest(geography=geography):
                arms = _portfolio(_query(geography), provider)
                self.assertEqual(len(arms), 1)
                self.assertIs(arms[0].retrieval_arm, RetrievalArm.BASELINE)

    def test_case_06_provider_without_capability_is_baseline_only(self) -> None:
        arms = _portfolio(_query("Ukraine"), _BaselineOnlyProvider())
        self.assertEqual([item.retrieval_arm for item in arms], [RetrievalArm.BASELINE])

    def test_cases_07_08_16_28_query_semantics_and_cross_domain_are_unchanged(self) -> None:
        provider = _PortfolioProvider()
        fixtures = (
            ("Ukraine", "pizza Ukraine market"),
            ("New Zealand", "residential heat pumps New Zealand"),
            ("India", "UPI merchant payments India"),
            ("Germany", "industrial electricity Germany"),
        )
        for geography, text in fixtures:
            arms = _portfolio(_query(geography, text=text), provider)
            self.assertTrue(all(item.provider_query_text == text for item in arms))
        self.assertNotIn("pizza", fixtures[1][1].casefold())

    def test_case_18_twelve_eligible_queries_are_bounded_to_24_calls(self) -> None:
        provider = _PortfolioProvider()
        arms = [arm for index in range(12) for arm in _portfolio(_query(query_id=f"sq-IN{index + 1}"), provider)]
        self.assertEqual(len(arms), 24)
        self.assertEqual(sum(item.retrieval_arm is RetrievalArm.BASELINE for item in arms), 12)
        self.assertEqual(sum(item.retrieval_arm is RetrievalArm.LOCALIZED for item in arms), 12)


class TavilyArmContractTests(unittest.TestCase):
    def test_cases_07_to_09_baseline_and_localized_differ_only_by_country(self) -> None:
        query = _query()
        baseline, localized = _portfolio(query, TavilySearchProvider(api_key="secret", http_client=Mock()))
        before, before_candidates = _tavily_payload(baseline)
        after, after_candidates = _tavily_payload(localized)
        self.assertEqual(before, {"api_key": "secret", "query": query.provider_query_text, "max_results": 5})
        self.assertEqual(after, {**before, "country": "ukraine"})
        self.assertEqual(before_candidates[0].metadata["retrieval_arm"], "baseline")
        self.assertEqual(after_candidates[0].metadata["retrieval_arm"], "localized")
        self.assertEqual(after_candidates[0].metadata["provider_query_text"], query.provider_query_text)
        self.assertEqual(after_candidates[0].metadata["provider_result_count"], "1")
        self.assertNotIn("secret", repr(before_candidates[0].metadata))
        self.assertNotIn("secret", repr(after_candidates[0].metadata))

    def test_case_17_property_ab_resolver_controls_capability(self) -> None:
        provider = TavilySearchProvider(api_key="secret", http_client=Mock())
        self.assertTrue(provider.supports_retrieval_arm(RetrievalArm.LOCALIZED, _query("Germany")))
        self.assertFalse(provider.supports_retrieval_arm(RetrievalArm.LOCALIZED, _query("Europe")))


class CrossArmDedupAndLineageTests(unittest.TestCase):
    def _service(self, provider: SearchProvider) -> SourceAcquisitionService:
        return SourceAcquisitionService(
            search_provider=provider,
            source_retriever=Mock(),
            source_repository=Mock(),
        )

    def test_cases_11_13_duplicate_url_is_one_group_before_source_cap(self) -> None:
        provider = _PortfolioProvider(
            {
                RetrievalArm.BASELINE: (("https://example.test/a?utm_source=x", "A"),),
                RetrievalArm.LOCALIZED: (("https://example.test/a", "A local"),),
            }
        )
        arms = _portfolio(_query(), provider)
        raw, grouped = self._service(provider)._collect_candidates(list(arms))
        self.assertEqual(raw, 2)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(next(iter(grouped.values()))), 2)

    def test_case_11_union_a_b_and_b_c_is_a_b_c(self) -> None:
        provider = _PortfolioProvider(
            {
                RetrievalArm.BASELINE: (("https://x.test/a", "A"), ("https://x.test/b", "B")),
                RetrievalArm.LOCALIZED: (("https://x.test/b", "B2"), ("https://x.test/c", "C")),
            }
        )
        raw, grouped = self._service(provider)._collect_candidates(list(_portfolio(_query(), provider)))
        self.assertEqual(raw, 4)
        self.assertEqual(len(grouped), 3)

    def test_cases_12_30_arm_lineage_is_distinct_and_deterministic(self) -> None:
        baseline = build_discovery_record(
            provider="tavily", query_id="sq-IN2", rank=2, workflow_run_id="run",
            research_design_id="design", information_need_id="IN2", retrieval_arm="baseline",
        )
        localized = build_discovery_record(
            provider="tavily", query_id="sq-IN2", rank=1, workflow_run_id="run",
            research_design_id="design", information_need_id="IN2", retrieval_arm="localized",
            provider_country="ukraine",
        )
        merged = merge_discovery_records([], (baseline, localized))
        self.assertEqual([row["retrieval_arm"] for row in merged], ["baseline", "localized"])
        self.assertEqual(merged[1]["provider_country"], "ukraine")

    def test_case_29_localized_failure_preserves_baseline_candidates(self) -> None:
        provider = _PortfolioProvider(
            {RetrievalArm.BASELINE: (("https://example.test/baseline", "Baseline"),)},
            fail_localized=True,
        )
        raw, grouped = self._service(provider)._collect_candidates(list(_portfolio(_query(), provider)))
        self.assertEqual(raw, 1)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(provider.calls), 2)

    def test_cases_14_15_arm_does_not_enter_ranking_algorithm(self) -> None:
        from pathlib import Path
        source = Path("application/sources/deterministic_source_relevance.py").read_text(encoding="utf-8")
        self.assertNotIn("retrieval_arm", source)

    def test_cases_19_20_no_llm_or_evidence_budget_changes(self) -> None:
        from pathlib import Path
        source = Path("application/sources/retrieval_portfolio.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("llm", source)
        self.assertNotIn("evidence", source)


if __name__ == "__main__":
    unittest.main()
