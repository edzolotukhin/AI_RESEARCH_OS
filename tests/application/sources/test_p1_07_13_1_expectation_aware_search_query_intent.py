"""P1-07.13.1 expectation-aware Search query intent."""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from application.research_quality.bounded_search_directives import (
    bound_targeted_search_directives,
)
from application.research_quality.targeted_search_query_builder import (
    TargetedSearchQueryBuilder,
)
from application.sources.expectation_aware_query_intent import (
    build_expectation_aware_query_text,
    render_aspect_query_terms,
)
from application.sources.search_query_builder import SearchQueryBuilder
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.targeted_research_request import TargetedResearchRequest

from tests.application.research_quality.test_p1_07_10_1_full_pipeline_acceptance_profile import (
    PROFILE_B_WORKER,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTENT_PATH = REPO_ROOT / "application" / "sources" / "expectation_aware_query_intent.py"

FIVE_ASPECTS = (
    "market_value_estimate",
    "market_volume_estimate",
    "assumption_drivers",
    "share_of_horeca",
    "microgreens_share_of_category",
)
IN1_DESCRIPTION = (
    "Estimate market size using proxies (leafy greens, herbs, specialty produce) "
    "and microgreens share for Serbia HoReCa."
)
IN2_DESCRIPTION = (
    "Assess growth and maturity indicators (CAGR, supplier count, product "
    "availability, awareness) and 2025-2026 outlook."
)
IN2_ASPECTS = (
    "historical_cagr",
    "supplier_density_trend",
    "menu_mentions_trend",
    "import_export_signals",
    "maturity_stage_classification",
)


def _design(
    *,
    need_id: str = "IN1",
    rq_id: str = "RQ1",
    description: str = IN1_DESCRIPTION,
    geography: str = "Serbia",
    timeframe: str = "2019-2026",
    expectation: EvidenceExpectation | None = None,
) -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id=rq_id, question="What is the market?", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id=need_id,
                research_question_id=rq_id,
                description=description,
                geography=geography,
                timeframe=timeframe,
                evidence_expectation=expectation,
            ),
        ),
        language="en",
    )


def _explicit_ee(aspects: tuple[str, ...] = FIVE_ASPECTS) -> EvidenceExpectation:
    return EvidenceExpectation(
        nature=EvidenceNature.QUANTITATIVE,
        required_aspects=aspects,
        geography="Serbia",
        timeframe="2019-2026",
        minimum_independent_sources=2,
        requires_quantitative_evidence=True,
    )


def _targeted_request(
    *,
    missing_aspects: tuple[str, ...] = (),
    search_directives: tuple[str, ...] | None = None,
    attempt: int = 1,
) -> TargetedResearchRequest:
    directives = (
        search_directives
        if search_directives is not None
        else bound_targeted_search_directives(missing_aspects)
    )
    return TargetedResearchRequest(
        workflow_run_id="run-1",
        research_design_id="design-1",
        research_question_id="RQ1",
        information_need_id="IN1",
        gap_types=(GapType.INSUFFICIENT_DEPTH,),
        missing_aspects=missing_aspects,
        search_directives=directives,
        attempt=attempt,
    )


def _aspect_phrases(aspects: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(render_aspect_query_terms(item) for item in aspects)


class ExpectationAwareInitialQueryTests(unittest.TestCase):
    def test_case_1_explicit_initial_expectation(self) -> None:
        design = _design(expectation=_explicit_ee())
        queries = SearchQueryBuilder(max_results=3).build_queries(design)
        self.assertEqual(len(queries), 1)
        text = queries[0].query_text
        self.assertIn("market size", text.lower())
        self.assertIn("Serbia", text)
        self.assertIn("2019-2026", text)
        for phrase in _aspect_phrases(FIVE_ASPECTS):
            self.assertIn(phrase, text)

    def test_case_2_five_aspect_initial_contract(self) -> None:
        design = _design(expectation=_explicit_ee(FIVE_ASPECTS))
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        for phrase in _aspect_phrases(FIVE_ASPECTS):
            self.assertIn(phrase, text)
        self.assertNotIn("__", text)

    def test_case_6_initial_determinism(self) -> None:
        design = _design(expectation=_explicit_ee())
        left = SearchQueryBuilder().build_queries(design)[0].query_text
        right = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertEqual(left, right)

    def test_case_7_legacy_ee_none_compatible(self) -> None:
        design = _design(expectation=None)
        query = SearchQueryBuilder().build_queries(design)[0]
        self.assertEqual(
            query.query_text,
            build_expectation_aware_query_text(
                description=IN1_DESCRIPTION,
                geography="Serbia",
                timeframe="2019-2026",
                semantic_targets=(),
            ),
        )
        self.assertNotIn("market value estimate", query.query_text)
        self.assertIn("Serbia", query.query_text)
        self.assertIn("2019-2026", query.query_text)

    def test_in1_in2_style_before_after_fixture_shapes(self) -> None:
        old_in1 = build_expectation_aware_query_text(
            description=IN1_DESCRIPTION,
            geography="Serbia",
            timeframe="2019-2026",
        )
        new_in1 = SearchQueryBuilder().build_queries(
            _design(expectation=_explicit_ee(FIVE_ASPECTS)),
        )[0].query_text
        self.assertNotEqual(old_in1, new_in1)
        for phrase in _aspect_phrases(FIVE_ASPECTS):
            self.assertNotIn(phrase, old_in1)
            self.assertIn(phrase, new_in1)

        old_in2 = build_expectation_aware_query_text(
            description=IN2_DESCRIPTION,
            geography="Serbia",
            timeframe="2019-2026",
        )
        new_in2 = SearchQueryBuilder().build_queries(
            _design(
                need_id="IN2",
                description=IN2_DESCRIPTION,
                expectation=_explicit_ee(IN2_ASPECTS),
            ),
        )[0].query_text
        self.assertNotEqual(old_in2, new_in2)
        self.assertIn("historical cagr", new_in2)
        self.assertIn("menu mentions trend", new_in2)


class ExpectationAwareTargetedQueryTests(unittest.TestCase):
    def test_case_3_max_queries_1_encodes_missing_aspects(self) -> None:
        missing = (
            "market_value_estimate",
            "market_volume_estimate",
            "microgreens_share_of_category",
        )
        generic = build_expectation_aware_query_text(
            description=IN1_DESCRIPTION,
            geography="Serbia",
            timeframe="2019-2026",
        )
        queries = TargetedSearchQueryBuilder().build_queries(
            design=_design(expectation=_explicit_ee()),
            request=_targeted_request(missing_aspects=missing),
            max_queries=1,
            max_results=3,
        )
        self.assertEqual(len(queries), 1)
        text = queries[0].query_text
        self.assertNotEqual(text, generic)
        self.assertIn("market size", text.lower())
        self.assertIn("Serbia", text)
        for phrase in _aspect_phrases(missing):
            self.assertIn(phrase, text)
        self.assertNotIn("assumption drivers", text)
        self.assertNotIn("share of horeca", text)

    def test_case_4_targeted_subset_not_full_ee(self) -> None:
        queries = TargetedSearchQueryBuilder().build_queries(
            design=_design(expectation=_explicit_ee(FIVE_ASPECTS)),
            request=_targeted_request(missing_aspects=("assumption_drivers", "share_of_horeca")),
            max_queries=1,
            max_results=3,
        )
        text = queries[0].query_text
        self.assertIn("assumption drivers", text)
        self.assertIn("share of horeca", text)
        self.assertNotIn("market volume estimate", text)
        self.assertNotIn("microgreens share of category", text)

    def test_case_5_changing_gap_changes_query(self) -> None:
        design = _design(expectation=_explicit_ee())
        builder = TargetedSearchQueryBuilder()
        left = builder.build_queries(
            design=design,
            request=_targeted_request(
                missing_aspects=("assumption_drivers", "share_of_horeca"),
            ),
            max_queries=1,
            max_results=3,
        )[0].query_text
        right = builder.build_queries(
            design=design,
            request=_targeted_request(
                missing_aspects=("market_volume_estimate", "microgreens_share_of_category"),
            ),
            max_queries=1,
            max_results=3,
        )[0].query_text
        self.assertNotEqual(left, right)
        self.assertIn("assumption drivers", left)
        self.assertIn("market volume estimate", right)

    def test_case_6_targeted_determinism(self) -> None:
        request = _targeted_request(missing_aspects=("historical_cagr", "import_export_signals"))
        design = _design(expectation=_explicit_ee(IN2_ASPECTS))
        builder = TargetedSearchQueryBuilder()
        self.assertEqual(
            builder.build_queries(
                design=design, request=request, max_queries=1, max_results=3,
            )[0].query_text,
            builder.build_queries(
                design=design, request=request, max_queries=1, max_results=3,
            )[0].query_text,
        )

    def test_case_8_packed_p1_07_12_1_request_uses_all_missing_aspects(self) -> None:
        six = FIVE_ASPECTS + ("import_export_signals",)
        packed = bound_targeted_search_directives(six)
        self.assertEqual(len(packed), 5)
        request = _targeted_request(missing_aspects=six, search_directives=packed)
        self.assertEqual(len(request.search_directives), 5)
        self.assertEqual(len(request.missing_aspects), 6)
        text = TargetedSearchQueryBuilder().build_queries(
            design=_design(expectation=_explicit_ee(six)),
            request=request,
            max_queries=1,
            max_results=3,
        )[0].query_text
        for phrase in _aspect_phrases(six):
            self.assertIn(phrase, text)

    def test_case_10_profile_b_max_queries_one_execution_facing_text(self) -> None:
        self.assertEqual(PROFILE_B_WORKER["TARGETED_MAX_QUERIES_PER_GAP"], "1")
        max_queries = int(PROFILE_B_WORKER["TARGETED_MAX_QUERIES_PER_GAP"])
        missing = (
            "market_value_estimate",
            "market_volume_estimate",
            "microgreens_share_of_category",
        )
        query = TargetedSearchQueryBuilder().build_queries(
            design=_design(expectation=_explicit_ee()),
            request=_targeted_request(missing_aspects=missing),
            max_queries=max_queries,
            max_results=3,
        )[0]
        self.assertEqual(query.id, "sq-target-IN1-a1-0")
        for phrase in _aspect_phrases(missing):
            self.assertIn(phrase, query.query_text)

    def test_case_7_legacy_targeted_without_expectation(self) -> None:
        design = _design(expectation=None)
        queries = TargetedSearchQueryBuilder().build_queries(
            design=design,
            request=_targeted_request(
                missing_aspects=("__legacy_need__",),
                search_directives=("__legacy_need__",),
            ),
            max_queries=1,
            max_results=3,
        )
        self.assertEqual(len(queries), 1)
        self.assertNotIn("__legacy_need__", queries[0].query_text)
        self.assertIn("market size", queries[0].query_text.lower())


class NoExtraLlmBudgetTests(unittest.TestCase):
    def test_case_9_pure_deterministic_no_llm_imports(self) -> None:
        source = INTENT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertNotIn("openai", imported)
        self.assertNotIn("httpx", imported)
        self.assertNotIn("infrastructure", imported)
        call_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    call_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    call_names.add(func.attr)
        forbidden_calls = {
            name
            for name in call_names
            if any(token in name.lower() for token in ("llm", "complete", "chat", "invoke"))
        }
        self.assertEqual(forbidden_calls, set())
        self.assertNotIn("budget", source.lower())
        builder_src = inspect.getsource(SearchQueryBuilder._build_query)
        targeted_src = inspect.getsource(TargetedSearchQueryBuilder.build_queries)
        self.assertIn("build_expectation_aware_query_text", builder_src)
        self.assertIn("build_expectation_aware_query_text", targeted_src)
        self.assertIn("missing_aspects", targeted_src)


if __name__ == "__main__":
    unittest.main()
