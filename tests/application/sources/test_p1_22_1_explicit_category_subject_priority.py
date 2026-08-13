"""P1-22.1 explicit category-subject priority — offline acceptance."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from application.evidence.evidence_extraction_scheduler import (
    PHASE_FIRST_OPPORTUNITY,
    build_need_fair_extraction_queue,
)
from application.research_quality.targeted_search_query_builder import (
    TargetedSearchQueryBuilder,
)
from application.sources.deterministic_source_relevance import (
    CATEGORY_NOT_PRESERVING,
    CATEGORY_PRESERVING,
    CATEGORY_UNSCORED,
    build_relevance_context,
    evaluate_candidate,
)
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import (
    SourceAcquisitionService,
    _PendingCandidate,
)
from application.sources.source_budget import SourceAcquisitionBudget
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate


def _ee() -> EvidenceExpectation:
    return EvidenceExpectation(
        nature=EvidenceNature.QUANTITATIVE,
        required_aspects=("market_value", "growth_rate"),
        geography="Ukraine",
        timeframe="2024-2026",
        requires_quantitative_evidence=True,
    )


def _pizza_design() -> ResearchDesign:
    return ResearchDesign(
        id="design-p1-22-1",
        research_questions=(
            ResearchQuestion(
                id="RQ1",
                question="What is the Ukraine pizza market size and growth?",
            ),
            ResearchQuestion(
                id="RQ2",
                question="Which pizza competitors operate across Ukraine?",
            ),
        ),
        information_needs=(
            InformationNeed(
                id="IN1",
                research_question_id="RQ1",
                description="Measure market value and historical growth",
                geography="Ukraine",
                timeframe="2024-2026",
                preferred_source_types=("official statistics",),
                evidence_expectation=_ee(),
            ),
            InformationNeed(
                id="IN2",
                research_question_id="RQ2",
                description="Identify chains, stores, and competitive shares",
                geography="Ukraine",
                timeframe="2024-2026",
                evidence_expectation=_ee(),
            ),
        ),
    )


def _candidate(
    url: str,
    title: str,
    *,
    snippet: str = "",
    rank: int = 1,
    query_id: str = "sq-IN1",
) -> SourceCandidate:
    return SourceCandidate(
        provider="fixture",
        url=url,
        title=title,
        snippet=snippet,
        query_id=query_id,
        rank=rank,
    )


def _query(need_id: str = "IN1", query_id: str = "sq-IN1") -> SearchQuery:
    rq_id = "RQ1" if need_id == "IN1" else "RQ2"
    return SearchQuery(
        id=query_id,
        research_question_id=rq_id,
        information_need_id=need_id,
        query_text="Ukraine pizza market",
        max_results=5,
    )


def _service(*, cap: int = 30, provider=None) -> SourceAcquisitionService:
    return SourceAcquisitionService(
        search_provider=provider or Mock(),
        source_retriever=Mock(),
        source_repository=Mock(),
        budget=SourceAcquisitionBudget(max_sources_per_run=cap),
    )


def _ordered(
    design: ResearchDesign,
    rows: list[tuple[SourceCandidate, SearchQuery]],
) -> list:
    grouped = {
        candidate.url: [
            _PendingCandidate(
                candidate=candidate,
                query=query,
                canonical_url=candidate.url,
            )
        ]
        for candidate, query in rows
    }
    eligible, _, _, _ = _service()._select_groups(
        grouped,
        design=design,
        exhausted_pairs=frozenset(),
    )
    return eligible


class P1221ExplicitCategorySubjectPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.design = _pizza_design()
        self.context = build_relevance_context(
            self.design,
            self.design.information_needs[0],
        )
        self.assertEqual(self.context.category_subject_tokens, frozenset({"pizza"}))

    def test_case_1_ukraine_pizza_outranks_official_ukraine_macro(self) -> None:
        rows = [
            (
                _candidate(
                    "https://stats.gov.ua/statistics/macro-dashboard",
                    "Official Ukraine macroeconomic statistics dashboard",
                    snippet="Ukraine national GDP and investment statistics",
                    rank=1,
                ),
                _query(),
            ),
            (
                _candidate(
                    "https://industry.example/ukraine-pizza-market",
                    "Ukraine pizza market operators and sales",
                    rank=5,
                ),
                _query(),
            ),
        ]
        ordered = _ordered(self.design, rows)
        self.assertEqual(ordered[0].canonical_url, rows[1][0].url)

    def test_case_2_global_pizza_outranks_ukraine_macro(self) -> None:
        rows = [
            (
                _candidate(
                    "https://stats.gov.ua/statistics/economy",
                    "Official Ukraine economic growth statistics",
                    rank=1,
                ),
                _query(),
            ),
            (
                _candidate(
                    "https://global.example/pizza-market",
                    "Global pizza market size and growth",
                    rank=5,
                ),
                _query(),
            ),
        ]
        self.assertEqual(_ordered(self.design, rows)[0].canonical_url, rows[1][0].url)

    def test_case_3_ukraine_pizza_outranks_global_pizza(self) -> None:
        rows = [
            (
                _candidate(
                    "https://global.example/pizza-market",
                    "Global pizza market size",
                    rank=1,
                ),
                _query(),
            ),
            (
                _candidate(
                    "https://ua.example/pizza-market",
                    "Ukraine pizza market size",
                    rank=5,
                ),
                _query(),
            ),
        ]
        self.assertEqual(_ordered(self.design, rows)[0].canonical_url, rows[1][0].url)

    def test_case_4_p1_12_boost_operates_within_category_tier(self) -> None:
        official = evaluate_candidate(
            self.context,
            _candidate(
                "https://stats.example.gov.ua/statistics/pizza-market.csv",
                "Official Ukraine pizza market statistics dataset",
                rank=5,
            ),
        )
        blog = evaluate_candidate(
            self.context,
            _candidate(
                "https://blog.example/ukraine-pizza-market",
                "Ukraine pizza market guide",
                rank=1,
            ),
        )
        self.assertEqual(official.category_alignment, CATEGORY_PRESERVING)
        self.assertGreater(official.expectation_boost, blog.expectation_boost)
        rows = [
            (_candidate("https://blog.example/ukraine-pizza-market", "Ukraine pizza market guide"), _query()),
            (_candidate("https://stats.example.gov.ua/statistics/pizza-market.csv", "Official Ukraine pizza market statistics dataset", rank=5), _query()),
        ]
        self.assertEqual(_ordered(self.design, rows)[0].canonical_url, rows[1][0].url)

    def test_case_5_official_macro_cannot_cross_category_tier(self) -> None:
        macro = evaluate_candidate(
            self.context,
            _candidate(
                "https://stats.example.gov.ua/statistics/gdp.csv",
                "Official Ukraine GDP statistics dataset",
            ),
        )
        self.assertEqual(macro.category_alignment, CATEGORY_NOT_PRESERVING)
        self.assertEqual(macro.expectation_boost, 0)
        self.assertNotEqual(macro.eligibility, "direct")

    def test_case_6_unavailable_subject_fails_open(self) -> None:
        design = ResearchDesign(
            id="no-shared-subject",
            research_questions=(
                ResearchQuestion(id="RQ1", question="How did inflation change?"),
                ResearchQuestion(id="RQ2", question="Which regulations apply?"),
            ),
            information_needs=(
                InformationNeed(id="IN1", research_question_id="RQ1", description="Annual price index"),
                InformationNeed(id="IN2", research_question_id="RQ2", description="Current legal obligations"),
            ),
        )
        context = build_relevance_context(design, design.information_needs[0])
        decision = evaluate_candidate(
            context,
            _candidate("https://example.test/page", "Annual inflation index"),
        )
        self.assertFalse(context.category_subject_tokens)
        self.assertEqual(decision.category_alignment, CATEGORY_UNSCORED)

    def test_case_7_zero_category_matches_remain_bounded_fallback(self) -> None:
        rows = [
            (_candidate("https://macro.example/one", "Ukraine economic outlook", rank=2), _query()),
            (_candidate("https://macro.example/two", "Ukraine investment growth", rank=1), _query()),
        ]
        ordered = _ordered(self.design, rows)
        self.assertEqual(len(ordered), 2)
        self.assertTrue(
            all(group.decision.category_alignment == CATEGORY_NOT_PRESERVING for group in ordered)
        )

    def test_case_8_provider_rank_is_deterministic_inside_equal_tier(self) -> None:
        rows = [
            (_candidate("https://pizza.example/rank-3", "Global pizza outlook", rank=3), _query()),
            (_candidate("https://pizza.example/rank-1", "Global pizza outlook", rank=1), _query()),
        ]
        first = [group.canonical_url for group in _ordered(self.design, rows)]
        second = [group.canonical_url for group in _ordered(self.design, list(reversed(rows)))]
        self.assertEqual(first, second)
        self.assertEqual(first[0], rows[1][0].url)

    def test_case_9_attempt_cap_cannot_exclude_late_category_candidate(self) -> None:
        rows = [
            (
                _candidate(
                    f"https://stats.example.gov.ua/statistics/macro-{index}.csv",
                    f"Official Ukraine macro statistics dataset {index}",
                    rank=1,
                ),
                _query(),
            )
            for index in range(30)
        ]
        category = (
            _candidate(
                "https://industry.example/global-pizza",
                "Global pizza market report",
                rank=99,
            ),
            _query(),
        )
        ordered = _ordered(self.design, rows + [category])
        attempted = [group.canonical_url for group in ordered[:30]]
        self.assertIn(category[0].url, attempted)
        self.assertEqual(ordered[0].canonical_url, category[0].url)

    def test_case_10_canonical_group_merges_query_rq_in_lineage(self) -> None:
        canonical = "https://shared.example/pizza-market"
        items = [
            _PendingCandidate(
                candidate=_candidate(canonical, "Pizza market", query_id="sq-IN1"),
                query=_query("IN1", "sq-IN1"),
                canonical_url=canonical,
            ),
            _PendingCandidate(
                candidate=_candidate(canonical, "Pizza competitors", query_id="sq-IN2"),
                query=_query("IN2", "sq-IN2"),
                canonical_url=canonical,
            ),
        ]
        delta = _service()._build_delta(
            items=items,
            workflow_run_id="run-1",
            research_design_id=self.design.id,
        )
        self.assertEqual(delta.query_refs, ("sq-IN1", "sq-IN2"))
        self.assertEqual(delta.research_question_refs, ("RQ1", "RQ2"))
        self.assertEqual(delta.information_need_refs, ("IN1", "IN2"))

    def test_case_11_targeted_search_uses_identical_category_priority(self) -> None:
        request = TargetedResearchRequest(
            workflow_run_id="run-1",
            research_design_id=self.design.id,
            research_question_id="RQ1",
            information_need_id="IN1",
            attempt=1,
            gap_types=("no_evidence",),
        )
        targeted = TargetedSearchQueryBuilder().build_queries(
            design=self.design,
            request=request,
            max_queries=1,
            max_results=5,
        )[0]
        initial = SearchQueryBuilder(max_results=5).build_queries(self.design)[0]
        self.assertIn("pizza", targeted.query_text.casefold())
        candidates = [
            _candidate("https://macro.example/ukraine", "Ukraine macro statistics"),
            _candidate("https://global.example/pizza", "Global pizza market", rank=5),
        ]
        initial_order = _ordered(self.design, [(candidates[0], initial), (candidates[1], initial)])
        targeted_order = _ordered(self.design, [(candidates[0], targeted), (candidates[1], targeted)])
        self.assertEqual(initial_order[0].canonical_url, candidates[1].url)
        self.assertEqual(targeted_order[0].canonical_url, candidates[1].url)

    def test_case_12_p1_21_2_macro_replay_has_zero_false_category_direct(self) -> None:
        fixtures = (
            ("https://bti-project.org/en/reports/country-report/UKR", "BTI 2026 Ukraine Country Report"),
            ("https://ukraine.un.org/en/country-analysis", "Ukraine Country Analysis 2026"),
            ("https://trade.gov/ukraine-distribution", "Ukraine Distribution and Sales Channels"),
            ("https://example.test/ukraine-logistics", "Ukraine freight and logistics market"),
            ("https://example.test/war-food-security", "Impact of war on Ukraine food security"),
        )
        decisions = [
            evaluate_candidate(self.context, _candidate(url, title))
            for url, title in fixtures
        ]
        self.assertTrue(
            all(item.category_alignment == CATEGORY_NOT_PRESERVING for item in decisions)
        )
        self.assertTrue(all(item.eligibility != "direct" for item in decisions))

    def test_case_13_cross_domain_subjects_have_no_domain_leakage(self) -> None:
        fixtures = (
            ("residential heat pump", "England"),
            ("UPI payments", "India"),
            ("electricity retail", "Germany"),
        )
        for subject, geography in fixtures:
            with self.subTest(subject=subject):
                design = ResearchDesign(
                    id=f"design-{subject}",
                    research_questions=(
                        ResearchQuestion(id="RQ1", question=f"What is the {subject} market in {geography}?"),
                        ResearchQuestion(id="RQ2", question=f"Which {subject} providers operate in {geography}?"),
                    ),
                    information_needs=(
                        InformationNeed(id="IN1", research_question_id="RQ1", description="Measure market scale", geography=geography),
                        InformationNeed(id="IN2", research_question_id="RQ2", description="Identify providers", geography=geography),
                    ),
                )
                context = build_relevance_context(design, design.information_needs[0])
                preserving = evaluate_candidate(
                    context,
                    _candidate("https://category.example/report", f"Global {subject} report"),
                )
                macro = evaluate_candidate(
                    context,
                    _candidate("https://macro.example/report", f"Official {geography} macroeconomic report"),
                )
                self.assertEqual(preserving.category_alignment, CATEGORY_PRESERVING)
                self.assertEqual(macro.category_alignment, CATEGORY_NOT_PRESERVING)
                self.assertNotIn("pizza", context.category_subject_tokens)

    def test_case_14_evidence_first_opportunity_scheduler_is_unchanged(self) -> None:
        sources = []
        for index, need_id in enumerate(("IN1", "IN2"), start=1):
            sources.append(
                Source(
                    id=f"source-{index}",
                    project_id="project",
                    url=f"https://example.test/{index}",
                    canonical_url=f"https://example.test/{index}",
                    title=f"Source {index}",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    workflow_run_refs=("run-1",),
                    research_design_refs=(self.design.id,),
                    information_need_refs=(need_id,),
                    retrieval_status=RetrievalStatus.ACQUIRED,
                    content_text="x" * 200,
                )
            )
        queue = build_need_fair_extraction_queue(
            sources,
            design=self.design,
            workflow_run_id="run-1",
            research_design_id=self.design.id,
            chunk_chars=100,
            overlap_chars=0,
        )
        self.assertEqual([item.phase for item in queue[:2]], [PHASE_FIRST_OPPORTUNITY] * 2)
        self.assertEqual({item.source.id for item in queue[:2]}, {"source-1", "source-2"})

    def test_case_15_call_and_budget_bounds_are_unchanged(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = 0

            def search(self, query: SearchQuery) -> list[SourceCandidate]:
                self.calls += 1
                return []

        provider = Provider()
        service = _service(provider=provider)
        queries = SearchQueryBuilder(max_results=5).build_queries(self.design)
        raw_count, grouped = service._collect_candidates(queries)
        self.assertEqual(provider.calls, len(queries))
        self.assertEqual(len(queries), len(self.design.information_needs))
        self.assertEqual(raw_count, 0)
        self.assertEqual(grouped, {})
        self.assertEqual(service._budget.max_candidates_per_query, 5)
        self.assertEqual(service._budget.max_sources_per_run, 30)


if __name__ == "__main__":
    unittest.main()
