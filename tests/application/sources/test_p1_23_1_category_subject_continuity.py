"""P1-23.1 PROPERTY Z — Brief-level category-subject continuity."""

from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from application.research_quality.targeted_search_query_builder import TargetedSearchQueryBuilder
from application.sources.category_subject import resolve_category_subject
from application.sources.deterministic_source_relevance import (
    CATEGORY_NOT_PRESERVING,
    CATEGORY_PRESERVING,
    build_relevance_context,
    evaluate_candidate,
)
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService, _PendingCandidate
from application.sources.source_budget import SourceAcquisitionBudget
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.research_brief import ResearchBrief
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate


PRODUCTION_FILES = (
    Path("application/sources/category_subject.py"),
    Path("application/sources/search_query_builder.py"),
    Path("application/sources/deterministic_source_relevance.py"),
    Path("application/research_quality/targeted_search_query_builder.py"),
)


def _brief(
    title: str = "Ukraine Pizza Market 2024-2026",
    question: str = "What is the current state of the pizza market in Ukraine?",
    geography: tuple[str, ...] = ("Ukraine",),
) -> ResearchBrief:
    return ResearchBrief(
        title=title,
        business_question=question,
        geography=geography,
        timeframe="2024-2026",
    )


def _live_design() -> ResearchDesign:
    rqs = (
        ("RQ1", "What is the market size and growth trajectory of Ukraine's pizza market?"),
        ("RQ2", "What is the competitive structure across major chains and independents?"),
        ("RQ3", "How do delivery channels and on-premise/off-premise mixes operate?"),
        ("RQ4", "What are consumer behaviors and preferences for pizza in Ukraine?"),
        ("RQ5", "What are price positioning tiers across chains and independents?"),
        ("RQ6", "What are the drivers, barriers, and opportunities for Ukraine pizza through 2026?"),
    )
    descriptions = (
        "Current market size, historical trend, forecasts and channel splits",
        "Macro context affecting outlook, income, inflation and disruptions",
        "Landscape of major pizza chains and independents",
        "Market concentration metrics overall and by major cities",
        "Channel structure, direct delivery, aggregators and commissions",
        "Platform coverage, service reliability and regional availability",
        "Consumer demand indicators and ordering triggers",
        "Consumer service expectations for delivery and dine-in",
        "Price ladders by brand and region for premium pizza",
        "Cost and inflation context impacting pricing",
        "Growth drivers through 2026",
        "Barriers, risks, regulations and opportunities",
    )
    rq_refs = ("RQ1", "RQ1", "RQ2", "RQ2", "RQ3", "RQ3", "RQ4", "RQ4", "RQ5", "RQ5", "RQ6", "RQ6")
    return ResearchDesign(
        id="p1-22-2-live-replay",
        research_questions=tuple(ResearchQuestion(id=i, question=q) for i, q in rqs),
        information_needs=tuple(
            InformationNeed(
                id=f"IN{index}",
                research_question_id=rq_refs[index - 1],
                description=description,
                geography="Ukraine",
                timeframe="2024-2026",
            )
            for index, description in enumerate(descriptions, start=1)
        ),
    )


def _candidate(title: str, url: str, rank: int = 1) -> SourceCandidate:
    return SourceCandidate(provider="fixture", title=title, url=url, snippet="", query_id="sq-IN1", rank=rank)


def _targeted(design: ResearchDesign, brief: ResearchBrief, *, max_queries: int = 2) -> list[SearchQuery]:
    return TargetedSearchQueryBuilder().build_queries(
        design=design,
        brief=brief,
        request=TargetedResearchRequest(
            workflow_run_id="run",
            research_design_id=design.id,
            research_question_id="RQ2",
            information_need_id="IN4",
            gap_types=("no_evidence",),
            missing_aspects=("hhi_index",),
            search_directives=("city level concentration",),
            attempt=1,
        ),
        max_queries=max_queries,
        max_results=5,
    )


class P1231CategorySubjectContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = _brief()
        self.design = _live_design()

    def test_case_01_all_rqs_repeat_category_is_reliable(self) -> None:
        design = ResearchDesign(
            id="all",
            research_questions=(ResearchQuestion(id="RQ1", question="Pizza market size"),),
            information_needs=(InformationNeed(id="IN1", research_question_id="RQ1", description="Pizza sales"),),
        )
        self.assertEqual(resolve_category_subject(brief=self.brief, design=design).text, "pizza")

    def test_case_02_some_rqs_omit_category(self) -> None:
        self.assertEqual(resolve_category_subject(brief=self.brief, design=self.design).tokens, frozenset({"pizza"}))

    def test_case_03_majority_rqs_may_omit_category(self) -> None:
        omitted = sum("pizza" not in rq.question.casefold() for rq in self.design.research_questions)
        self.assertGreaterEqual(omitted, 3)
        self.assertIsNotNone(resolve_category_subject(brief=self.brief, design=self.design))

    def test_case_04_generic_initial_rq_and_in_still_anchor(self) -> None:
        query = SearchQueryBuilder().build_queries(self.design, brief=self.brief)[3]
        self.assertIn("pizza", query.query_text.casefold())

    def test_case_05_anchored_rq_has_no_pathological_duplication(self) -> None:
        text = SearchQueryBuilder().build_queries(self.design, brief=self.brief)[0].query_text.casefold()
        self.assertNotIn("pizza pizza", text)
        self.assertLessEqual(text.count("pizza"), 1)

    def test_case_06_targeted_base_query_preserves_category(self) -> None:
        self.assertIn("pizza", _targeted(self.design, self.brief)[0].query_text.casefold())

    def test_case_07_relevance_sees_subject_when_rqs_omit_it(self) -> None:
        context = build_relevance_context(self.design, self.design.information_needs[3], brief=self.brief)
        self.assertEqual(context.category_subject_tokens, frozenset({"pizza"}))

    def test_case_08_category_candidate_is_preserving(self) -> None:
        context = build_relevance_context(self.design, self.design.information_needs[3], brief=self.brief)
        result = evaluate_candidate(context, _candidate("Ukraine pizza operators", "https://example.test/pizza"))
        self.assertEqual(result.category_alignment, CATEGORY_PRESERVING)

    def test_case_09_macro_candidate_is_not_preserving(self) -> None:
        context = build_relevance_context(self.design, self.design.information_needs[3], brief=self.brief)
        result = evaluate_candidate(context, _candidate("Ukraine CPI and inflation", "https://stats.test/cpi"))
        self.assertEqual(result.category_alignment, CATEGORY_NOT_PRESERVING)

    def test_case_10_global_category_is_preserving_with_weaker_geo(self) -> None:
        context = build_relevance_context(self.design, self.design.information_needs[0], brief=self.brief)
        result = evaluate_candidate(context, _candidate("Global pizza report", "https://global.test/pizza"))
        self.assertEqual(result.category_alignment, CATEGORY_PRESERVING)
        self.assertNotEqual(result.geo_alignment, "direct")

    def _ordered(self, candidates: list[SourceCandidate]) -> list:
        query = SearchQuery(id="sq-IN1", research_question_id="RQ1", information_need_id="IN1", query_text="pizza")
        grouped = {
            item.url: [_PendingCandidate(candidate=item, query=query, canonical_url=item.url)]
            for item in candidates
        }
        service = SourceAcquisitionService(
            search_provider=Mock(), source_retriever=Mock(), source_repository=Mock(),
            budget=SourceAcquisitionBudget(max_sources_per_run=30),
        )
        return service._select_groups(grouped, design=self.design, brief=self.brief, exhausted_pairs=frozenset())[0]

    def test_case_11_ukraine_category_outranks_global_category(self) -> None:
        ordered = self._ordered([
            _candidate("Global pizza market", "https://global.test/pizza", 1),
            _candidate("Ukraine pizza market", "https://ua.test/pizza", 5),
        ])
        self.assertEqual(ordered[0].canonical_url, "https://ua.test/pizza")

    def test_case_12_global_category_outranks_ukraine_macro(self) -> None:
        ordered = self._ordered([
            _candidate("Official Ukraine CPI statistics", "https://stats.gov.ua/statistics/cpi.csv", 1),
            _candidate("Global pizza market", "https://global.test/pizza", 5),
        ])
        self.assertEqual(ordered[0].canonical_url, "https://global.test/pizza")

    def test_case_13_p1_12_operates_inside_category_tier(self) -> None:
        quantitative = replace(
            self.design,
            information_needs=(
                replace(
                    self.design.information_needs[0],
                    evidence_expectation=EvidenceExpectation(
                        nature=EvidenceNature.QUANTITATIVE,
                        required_aspects=("market_value",),
                        geography="Ukraine",
                        requires_quantitative_evidence=True,
                    ),
                ),
                *self.design.information_needs[1:],
            ),
        )
        original = self.design
        self.design = quantitative
        ordered = self._ordered([
            _candidate("Ukraine pizza guide", "https://blog.test/pizza", 1),
            _candidate("Official Ukraine pizza statistics", "https://stats.gov.ua/statistics/pizza.csv", 5),
        ])
        self.design = original
        self.assertEqual(ordered[0].canonical_url, "https://stats.gov.ua/statistics/pizza.csv")

    def test_case_14_official_macro_cannot_cross_category_tier(self) -> None:
        self.test_case_12_global_category_outranks_ukraine_macro()

    def test_case_15_ambiguous_brief_fails_open(self) -> None:
        brief = _brief("Exploratory policy research", "What policy options should be considered?", ())
        design = ResearchDesign(
            id="ambiguous",
            research_questions=(ResearchQuestion(id="RQ1", question="Which regulations apply?"), ResearchQuestion(id="RQ2", question="What funding exists?")),
            information_needs=(InformationNeed(id="IN1", research_question_id="RQ1", description="Rules"),),
        )
        self.assertIsNone(resolve_category_subject(brief=brief, design=design))

    def _cross_domain(self, title: str, question: str, geography: str, expected: set[str]) -> None:
        subject = resolve_category_subject(brief=_brief(title, question, (geography,)), design=self.design)
        self.assertEqual(subject.tokens, frozenset(expected))

    def test_case_16_heat_pump_continuity(self) -> None:
        self._cross_domain("UK Residential Heat Pumps 2024-2026", "How is the residential heat pumps market developing in the UK?", "UK", {"residential", "heat", "pumps"})

    def test_case_17_upi_continuity(self) -> None:
        self._cross_domain("India UPI Payments 2024-2026", "How are UPI payments developing in India?", "India", {"upi", "payments"})

    def test_case_18_electricity_continuity(self) -> None:
        self._cross_domain("Industrial Electricity Market", "What is changing in the industrial electricity market?", "Germany", {"industrial", "electricity"})

    def test_case_19_no_domain_hardcoding(self) -> None:
        source = Path("application/sources/category_subject.py").read_text(encoding="utf-8").casefold()
        for literal in ("pizza", "pizzeria", "heat pump", "upi"):
            self.assertNotIn(literal, source)

    def test_case_20_exact_live_replay_moves_8_to_12(self) -> None:
        old = SearchQueryBuilder().build_queries(self.design)
        new = SearchQueryBuilder().build_queries(self.design, brief=self.brief)
        self.assertEqual(sum("pizza" in q.query_text.casefold() for q in old), 8)
        self.assertEqual(sum("pizza" in q.query_text.casefold() for q in new), 12)

    def test_case_21_live_derivation_moves_fail_open_to_reliable(self) -> None:
        self.assertIsNone(resolve_category_subject(brief=None, design=self.design))
        self.assertEqual(resolve_category_subject(brief=self.brief, design=self.design).text, "pizza")

    def test_case_22_macro_no_longer_unscored(self) -> None:
        decision = evaluate_candidate(
            build_relevance_context(self.design, self.design.information_needs[3], brief=self.brief),
            _candidate("Ukraine CPI", "https://macro.test/cpi"),
        )
        self.assertEqual(decision.category_alignment, CATEGORY_NOT_PRESERVING)

    def test_case_23_query_count_unchanged(self) -> None:
        self.assertEqual(len(SearchQueryBuilder().build_queries(self.design, brief=self.brief)), 12)

    def test_case_24_attempt_cap_unchanged(self) -> None:
        self.assertEqual(SourceAcquisitionBudget().max_sources_per_run, 30)

    def test_case_25_targeted_directive_parity(self) -> None:
        queries = _targeted(self.design, self.brief)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all("pizza" in query.query_text.casefold() for query in queries))

    def test_case_26_deterministic_same_input(self) -> None:
        left = SearchQueryBuilder().build_queries(self.design, brief=self.brief)
        right = SearchQueryBuilder().build_queries(self.design, brief=self.brief)
        self.assertEqual(left, right)

    def test_case_27_no_provider_call_increase(self) -> None:
        provider = Mock()
        provider.search.return_value = []
        queries = SearchQueryBuilder().build_queries(self.design, brief=self.brief)
        for query in queries:
            provider.search(query)
        self.assertEqual(provider.search.call_count, 12)

    def test_case_28_no_search_query_count_increase(self) -> None:
        self.assertEqual(len(SearchQueryBuilder().build_queries(self.design, brief=self.brief)), len(self.design.information_needs))

    def test_case_29_no_llm_or_network_dependency(self) -> None:
        for path in PRODUCTION_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = {node.module.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            self.assertNotIn("openai", imports)
            self.assertNotIn("infrastructure", imports)

    def test_case_30_no_budget_or_cap_change_in_resolver(self) -> None:
        source = Path("application/sources/category_subject.py").read_text(encoding="utf-8").casefold()
        for literal in ("max_results", "max_sources", "evidence_max", "llm_call"):
            self.assertNotIn(literal, source)


if __name__ == "__main__":
    unittest.main()
