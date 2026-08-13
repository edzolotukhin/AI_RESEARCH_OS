"""P1-24.1 PROPERTY AA — bounded provider query projection."""

from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

from application.sources.provider_query_projector import (
    MAX_PROVIDER_QUERY_CHARS,
    project_provider_query_text,
)
from application.sources.search_query_builder import SearchQueryBuilder
from domain.sources.search_query import SearchQuery
from infrastructure.search.tavily_search_provider import TavilySearchProvider
from tests.application.sources.test_p1_23_1_category_subject_continuity import (
    _brief,
    _live_design,
    _targeted,
)


class P1241BoundedProviderQueryProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = _brief()
        self.design = _live_design()
        self.queries = SearchQueryBuilder().build_queries(self.design, brief=self.brief)

    def test_case_01_full_internal_search_query_is_unchanged(self) -> None:
        old = SearchQueryBuilder().build_queries(self.design, brief=self.brief)
        self.assertEqual([q.query_text for q in self.queries], [q.query_text for q in old])

    def test_case_02_provider_query_is_shorter(self) -> None:
        self.assertTrue(all(len(q.provider_query_text) < len(q.query_text) for q in self.queries))
        self.assertTrue(all(len(q.provider_query_text) <= MAX_PROVIDER_QUERY_CHARS for q in self.queries))

    def test_case_03_category_is_retained(self) -> None:
        self.assertTrue(all("pizza" in q.provider_query_text.casefold() for q in self.queries))

    def test_case_04_geography_is_retained(self) -> None:
        self.assertTrue(all("ukraine" in q.provider_query_text.casefold() for q in self.queries))

    def test_case_05_core_information_need_intent_is_retained(self) -> None:
        self.assertIn("market size", self.queries[0].provider_query_text.casefold())

    def test_case_06_duplicate_rq_prose_is_removed(self) -> None:
        self.assertNotIn("what is", self.queries[0].provider_query_text.casefold())
        self.assertLess(len(self.queries[0].provider_query_text), len(self.queries[0].query_text))

    def test_case_07_evidence_expectation_enumeration_is_not_copied(self) -> None:
        self.assertNotIn("semantic targets", self.queries[0].provider_query_text.casefold())

    def test_case_08_useful_timeframe_is_retained(self) -> None:
        self.assertIn("2024-2026", self.queries[0].provider_query_text)

    def test_case_09_non_year_timeframe_is_safely_omitted(self) -> None:
        text = project_provider_query_text(
            category_subject="widgets", geography="France", core_intent="market size", timeframe="current",
        )
        self.assertEqual(text, "widgets France market size")

    def test_case_10_projector_has_no_domain_vocabulary(self) -> None:
        source = Path("application/sources/provider_query_projector.py").read_text(encoding="utf-8").casefold()
        for literal in ("pizza", "pizzeria", "heat pump", "upi", "electricity"):
            self.assertNotIn(literal, source)

    def test_case_11_twelve_query_replay_preserves_continuity(self) -> None:
        self.assertEqual(len(self.queries), 12)
        self.assertEqual(sum("pizza" in q.provider_query_text.casefold() for q in self.queries), 12)

    def test_case_12_in12_cannot_lexically_hijack_category(self) -> None:
        query = self.queries[11].provider_query_text.casefold()
        self.assertTrue(query.startswith("pizza ukraine"))
        self.assertLess(query.index("pizza"), query.index("barriers"))

    def test_case_13_targeted_search_has_projection_parity(self) -> None:
        query = _targeted(self.design, self.brief)[0]
        self.assertIn("pizza", query.provider_query_text.casefold())
        self.assertIn("ukraine", query.provider_query_text.casefold())
        self.assertIn("hhi", query.provider_query_text.casefold())

    def test_case_14_remediation_directive_has_projection_parity(self) -> None:
        query = _targeted(self.design, self.brief)[1]
        self.assertIn("pizza", query.provider_query_text.casefold())
        self.assertIn("city level concentration", query.provider_query_text.casefold())

    def test_case_15_ambiguous_projection_fails_open_at_adapter(self) -> None:
        query = self._query(provider_query_text="")
        payload = self._payload(query)
        self.assertEqual(payload["query"], query.query_text)

    def test_case_16_missing_structured_input_fails_open(self) -> None:
        self.assertIsNone(project_provider_query_text(category_subject=None, geography="Ukraine", core_intent="size"))
        self.assertIsNone(project_provider_query_text(category_subject="pizza", geography="", core_intent="size"))

    def test_case_17_projection_does_not_mutate_search_query(self) -> None:
        query = self.queries[0]
        with self.assertRaises(FrozenInstanceError):
            query.query_text = "changed"  # type: ignore[misc]

    def test_case_18_tavily_max_results_remains_five(self) -> None:
        self.assertEqual(self._payload(self._query())["max_results"], 5)

    def test_case_19_provider_parameters_are_unchanged(self) -> None:
        self.assertEqual(set(self._payload(self._query())), {"api_key", "query", "max_results"})

    def test_case_20_provider_call_count_is_unchanged(self) -> None:
        client = self._client()
        provider = TavilySearchProvider(api_key="fixture", http_client=client)
        for query in self.queries:
            provider.search(query)
        self.assertEqual(client.post.call_count, 12)

    def test_case_21_projection_makes_no_llm_call(self) -> None:
        tree = ast.parse(Path("application/sources/provider_query_projector.py").read_text(encoding="utf-8"))
        imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(any("llm" in item or "openai" in item for item in imports))

    def test_case_22_no_budget_or_cap_change(self) -> None:
        source = Path("application/sources/provider_query_projector.py").read_text(encoding="utf-8")
        self.assertNotIn("max_sources_per_run", source)
        self.assertNotIn("evidence_budget", source)

    def test_case_23_p1_21_subject_anchoring_remains(self) -> None:
        self.assertIn("market size and growth trajectory", self.queries[0].query_text.casefold())

    def test_case_24_p1_22_property_y_boundary_is_unchanged(self) -> None:
        self.assertNotIn("source_acquisition_service", Path("application/sources/provider_query_projector.py").read_text())

    def test_case_25_p1_23_category_resolution_remains(self) -> None:
        self.assertTrue(all(q.provider_query_text.casefold().startswith("pizza ") for q in self.queries))

    def test_case_26_p1_12_ranking_is_not_imported(self) -> None:
        self.assertNotIn("official", Path("application/sources/provider_query_projector.py").read_text().casefold())

    def test_case_27_p1_17_scheduler_boundary_is_unchanged(self) -> None:
        self.assertFalse(Path("application/sources/provider_query_projector.py").read_text().find("scheduler") >= 0)

    def test_case_28_p1_14_acquisition_boundary_is_unchanged(self) -> None:
        self.assertNotIn("retriever", Path("application/sources/provider_query_projector.py").read_text())

    def test_case_29_p1_09_entailment_boundary_is_unchanged(self) -> None:
        self.assertNotIn("entailment", Path("application/sources/provider_query_projector.py").read_text())

    def test_case_30_p1_08_analysis_boundary_is_unchanged(self) -> None:
        self.assertNotIn("analysis", Path("application/sources/provider_query_projector.py").read_text())

    def test_case_31_api_shape_is_unchanged(self) -> None:
        self.assertNotIn("provider_query_text", self.queries[0].to_dict())

    def test_case_32_cross_domain_heat_pumps(self) -> None:
        self._cross_domain("residential heat pumps", "United Kingdom", "installation market", {"heat", "pumps", "united kingdom"})

    def test_case_33_cross_domain_upi(self) -> None:
        self._cross_domain("UPI payments", "India", "transaction growth", {"upi", "payments", "india"})

    def test_case_34_cross_domain_electricity(self) -> None:
        self._cross_domain("industrial electricity", "Germany", "price outlook", {"electricity", "germany"})

    def test_case_35_no_persistence_schema_or_dependency_change(self) -> None:
        restored = SearchQuery.from_dict(self.queries[0].to_dict())
        self.assertEqual(restored.query_text, self.queries[0].query_text)
        self.assertEqual(restored.provider_query_text, "")

    @staticmethod
    def _query(provider_query_text: str = "pizza Ukraine market size") -> SearchQuery:
        return SearchQuery(
            id="sq-IN1", research_question_id="RQ1", information_need_id="IN1",
            query_text="complete internal query", provider_query_text=provider_query_text,
        )

    @staticmethod
    def _client() -> Mock:
        response = Mock()
        response.json.return_value = {"results": []}
        return Mock(post=Mock(return_value=response))

    def _payload(self, query: SearchQuery) -> dict:
        client = self._client()
        TavilySearchProvider(api_key="fixture", http_client=client).search(query)
        return client.post.call_args.kwargs["json"]

    def _cross_domain(self, category: str, geo: str, intent: str, terms: set[str]) -> None:
        projected = project_provider_query_text(category_subject=category, geography=geo, core_intent=intent)
        self.assertIsNotNone(projected)
        folded = projected.casefold()
        self.assertTrue(all(term in folded for term in terms))


if __name__ == "__main__":
    unittest.main()
