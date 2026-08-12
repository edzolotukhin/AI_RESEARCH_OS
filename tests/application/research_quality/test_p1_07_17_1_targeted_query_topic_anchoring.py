"""P1-07.17.1 deterministic targeted query topic anchoring."""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from application.research_quality.bounded_search_directives import (
    bound_targeted_search_directives,
)
from application.research_quality.targeted_search_query_builder import (
    SEMANTIC_TARGET_EE_FALLBACK,
    SEMANTIC_TARGET_LEGACY_DIRECTIVES,
    SEMANTIC_TARGET_MISSING_ASPECTS,
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
TARGETED_PATH = (
    REPO_ROOT / "application" / "research_quality" / "targeted_search_query_builder.py"
)

IN1_RQ = (
    "What is the Serbian premium microgreens market size, growth outlook, "
    "and maturity for HoReCa in 2025–2026?"
)
IN1_DESCRIPTION = (
    "Size the Serbian microgreens market for HoReCa: value, volume proxies, "
    "growth rate, and maturity indicators."
)
IN1_ASPECTS = (
    "market_value_range_eur",
    "growth_cagr_estimate",
    "maturity_stage_indicators",
    "horeca_share_of_demand",
    "seasonality_signals",
)

IN2_RQ = (
    "What is HoReCa demand, adoption potential, and how do restaurants and "
    "chefs currently use microgreens?"
)
IN2_DESCRIPTION = (
    "Estimate HoReCa adoption potential by segment (fine dining, casual, "
    "hotels, catering) and drivers/barriers."
)
IN2_ASPECTS = (
    "segment_penetration_estimates",
    "usage_frequency",
    "purchase_triggers",
    "barriers_to_adoption",
    "chef_awareness_levels",
)

IN12_RQ = IN1_RQ
IN12_DESCRIPTION = (
    "Triangulate supply-demand balance and capacity gaps to infer attainable "
    "share for a new entrant."
)
IN12_ASPECTS = (
    "installed_capacity_estimate",
    "demand_volume_proxy",
    "unserved_demand_indicators",
    "attainable_share_range",
)

FIVE_ASPECTS = (
    "market_value_estimate",
    "market_volume_estimate",
    "assumption_drivers",
    "share_of_horeca",
    "microgreens_share_of_category",
)
SEVEN_ASPECTS = FIVE_ASPECTS + ("import_export_signals", "maturity_stage_classification")


def _ee(
    aspects: tuple[str, ...],
    *,
    geography: str = "Serbia",
    timeframe: str = "2019-2026",
) -> EvidenceExpectation:
    return EvidenceExpectation(
        nature=EvidenceNature.MIXED,
        required_aspects=aspects,
        geography=geography,
        timeframe=timeframe,
        minimum_independent_sources=2,
        requires_quantitative_evidence=True,
    )


def _design(
    *,
    rq_id: str = "RQ1",
    rq_text: str = "What is the market?",
    rq_rationale: str = "",
    need_id: str = "IN1",
    description: str = "Estimate market size.",
    geography: str = "Serbia",
    timeframe: str = "2019-2026",
    expectation: EvidenceExpectation | None = None,
) -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(
                id=rq_id,
                question=rq_text,
                objective_refs=(),
                rationale=rq_rationale,
            ),
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


def _request(
    *,
    need_id: str = "IN1",
    rq_id: str = "RQ1",
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
        research_question_id=rq_id,
        information_need_id=need_id,
        gap_types=(GapType.NO_EVIDENCE,),
        missing_aspects=missing_aspects,
        search_directives=directives,
        attempt=attempt,
    )


def _phrases(aspects: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(render_aspect_query_terms(item) for item in aspects)


def _build(
    design: ResearchDesign,
    request: TargetedResearchRequest,
    *,
    max_queries: int = 1,
) -> list:
    return TargetedSearchQueryBuilder().build_queries(
        design=design,
        request=request,
        max_queries=max_queries,
        max_results=3,
    )


class TargetedQueryTopicAnchoringTests(unittest.TestCase):
    def test_case_1_explicit_ee_nonempty_missing_aspects(self) -> None:
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description="Size market value and volume proxies.",
            expectation=_ee(FIVE_ASPECTS),
        )
        missing = ("market_volume_estimate", "assumption_drivers")
        query = _build(design, _request(missing_aspects=missing))[0]
        text = query.query_text
        self.assertTrue(text.lower().startswith("what is the serbian premium microgreens"))
        self.assertIn("market volume estimate", text)
        self.assertIn("assumption drivers", text)
        self.assertNotIn("share of horeca", text)
        self.assertNotIn("microgreens share of category", text)
        self.assertIn("Serbia", text)
        self.assertIn("2019-2026", text)
        self.assertIn(SEMANTIC_TARGET_MISSING_ASPECTS, query.rationale)

    def test_case_2_explicit_ee_empty_missing_falls_back_to_required(self) -> None:
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description="Size market value and volume proxies.",
            expectation=_ee(FIVE_ASPECTS),
        )
        query = _build(design, _request(missing_aspects=(), search_directives=()))[0]
        text = query.query_text
        for phrase in _phrases(FIVE_ASPECTS):
            self.assertIn(phrase, text)
        self.assertIn(SEMANTIC_TARGET_EE_FALLBACK, query.rationale)

    def test_case_3_in1_live_style(self) -> None:
        design = _design(
            rq_text=IN1_RQ,
            need_id="IN1",
            description=IN1_DESCRIPTION,
            timeframe="2019-2026 with 2025-2026 focus",
            expectation=_ee(IN1_ASPECTS, timeframe="2019-2026"),
        )
        old = build_expectation_aware_query_text(
            description=IN1_DESCRIPTION,
            geography="Serbia",
            timeframe="2019-2026 with 2025-2026 focus",
            semantic_targets=(),
        )
        new = _build(design, _request(need_id="IN1", missing_aspects=()))[0].query_text
        self.assertNotEqual(old, new)
        self.assertIn("microgreens", new.casefold())
        self.assertIn("horeca", new.casefold())
        self.assertTrue(new.casefold().startswith("what is the serbian premium microgreens"))
        for phrase in _phrases(IN1_ASPECTS):
            self.assertIn(phrase, new)
            self.assertNotIn(phrase, old)
        self.assertIn("Serbia", new)
        self.assertIn("2019-2026 with 2025-2026 focus", new)

    def test_case_4_in2_live_style_retains_parent_product_anchor(self) -> None:
        design = _design(
            rq_id="RQ2",
            rq_text=IN2_RQ,
            need_id="IN2",
            description=IN2_DESCRIPTION,
            timeframe="2022-2026",
            expectation=_ee(
                IN2_ASPECTS,
                geography="Serbia; relevant regional benchmarks (CEE/Balkans) for triangulation",
                timeframe="2022-2026",
            ),
        )
        text = _build(
            design,
            _request(need_id="IN2", rq_id="RQ2", missing_aspects=()),
        )[0].query_text
        self.assertIn("microgreens", text.casefold())
        self.assertIn("horeca", text.casefold())
        for phrase in _phrases(IN2_ASPECTS):
            self.assertIn(phrase, text)
        self.assertTrue(text.casefold().startswith("what is horeca demand"))

    def test_case_5_in12_triangulate_live_style(self) -> None:
        design = _design(
            rq_text=IN12_RQ,
            need_id="IN12",
            description=IN12_DESCRIPTION,
            timeframe="2022-2026",
            expectation=_ee(IN12_ASPECTS, timeframe="2022-2026"),
        )
        old = build_expectation_aware_query_text(
            description=IN12_DESCRIPTION,
            geography="Serbia",
            timeframe="2022-2026",
            semantic_targets=(),
        )
        new = _build(
            design,
            _request(need_id="IN12", missing_aspects=()),
        )[0].query_text
        self.assertTrue(old.casefold().startswith("triangulate"))
        self.assertFalse(new.casefold().startswith("triangulate"))
        self.assertIn("microgreens", new.casefold())
        self.assertIn("horeca", new.casefold())
        self.assertIn("triangulate", new.casefold())
        for phrase in _phrases(IN12_ASPECTS):
            self.assertIn(phrase, new)
            self.assertNotIn(phrase, old)

    def test_case_6_max_queries_1_execution_facing_query_zero(self) -> None:
        self.assertEqual(PROFILE_B_WORKER["TARGETED_MAX_QUERIES_PER_GAP"], "1")
        max_queries = int(PROFILE_B_WORKER["TARGETED_MAX_QUERIES_PER_GAP"])
        design = _design(
            rq_text=IN1_RQ,
            description=IN1_DESCRIPTION,
            expectation=_ee(IN1_ASPECTS),
        )
        queries = _build(
            design,
            _request(missing_aspects=()),
            max_queries=max_queries,
        )
        self.assertEqual(len(queries), 1)
        query = queries[0]
        self.assertEqual(query.id, "sq-target-IN1-a1-0")
        self.assertIn("microgreens", query.query_text.casefold())
        for phrase in _phrases(IN1_ASPECTS):
            self.assertIn(phrase, query.query_text)
        self.assertIn("Serbia", query.query_text)
        self.assertIn("2019-2026", query.query_text)

    def test_case_7_changing_missing_aspects_changes_query(self) -> None:
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description="Size market value and volume proxies.",
            expectation=_ee(FIVE_ASPECTS),
        )
        left = _build(
            design,
            _request(missing_aspects=("market_volume_estimate", "assumption_drivers")),
        )[0].query_text
        right = _build(
            design,
            _request(
                missing_aspects=("share_of_horeca", "microgreens_share_of_category"),
            ),
        )[0].query_text
        self.assertNotEqual(left, right)
        self.assertIn("market volume estimate", left)
        self.assertIn("share of horeca", right)

    def test_case_8_empty_vs_nonempty_gap_behavior(self) -> None:
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description="Size market value and volume proxies.",
            expectation=_ee(FIVE_ASPECTS),
        )
        empty = _build(design, _request(missing_aspects=(), search_directives=()))[0]
        nonempty = _build(
            design,
            _request(missing_aspects=("assumption_drivers", "share_of_horeca")),
        )[0]
        for phrase in _phrases(FIVE_ASPECTS):
            self.assertIn(phrase, empty.query_text)
        self.assertIn("assumption drivers", nonempty.query_text)
        self.assertIn("share of horeca", nonempty.query_text)
        self.assertNotIn("market volume estimate", nonempty.query_text)
        self.assertIn(SEMANTIC_TARGET_EE_FALLBACK, empty.rationale)
        self.assertIn(SEMANTIC_TARGET_MISSING_ASPECTS, nonempty.rationale)

    def test_case_9_deterministic_byte_for_byte(self) -> None:
        design = _design(
            rq_text=IN12_RQ,
            need_id="IN12",
            description=IN12_DESCRIPTION,
            expectation=_ee(IN12_ASPECTS),
        )
        request = _request(need_id="IN12", missing_aspects=())
        builder = TargetedSearchQueryBuilder()
        left = builder.build_queries(
            design=design, request=request, max_queries=1, max_results=3,
        )[0].query_text
        right = builder.build_queries(
            design=design, request=request, max_queries=1, max_results=3,
        )[0].query_text
        self.assertEqual(left, right)

    def test_case_10_duplicate_topic_tokens_not_pathological(self) -> None:
        shared = "Serbian microgreens HoReCa market size and maturity"
        design = _design(
            rq_text=shared,
            description=shared,
            expectation=_ee(("market_value_range_eur", "growth_cagr_estimate")),
        )
        text = _build(design, _request(missing_aspects=()))[0].query_text
        self.assertEqual(text.casefold().count(shared.casefold()), 1)
        self.assertIn("market value range eur", text)
        self.assertIn("growth cagr estimate", text)

    def test_case_11_legacy_ee_none_compatible(self) -> None:
        design = _design(
            rq_text="What is the Serbian premium microgreens market?",
            description="Estimate market size using proxies.",
            expectation=None,
        )
        queries = _build(
            design,
            _request(
                missing_aspects=("__legacy_need__",),
                search_directives=("__legacy_need__",),
            ),
        )
        self.assertEqual(len(queries), 1)
        text = queries[0].query_text
        self.assertNotIn("__legacy_need__", text)
        self.assertIn("microgreens", text.casefold())
        self.assertIn("market size", text.casefold())
        self.assertIn(SEMANTIC_TARGET_LEGACY_DIRECTIVES, queries[0].rationale)

    def test_case_12_search_directives_compatibility_nonempty_missing(self) -> None:
        six = FIVE_ASPECTS + ("import_export_signals",)
        packed = bound_targeted_search_directives(six)
        self.assertEqual(len(packed), 5)
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description="Size market value and volume proxies.",
            expectation=_ee(six),
        )
        text = _build(
            design,
            _request(missing_aspects=six, search_directives=packed),
        )[0].query_text
        for phrase in _phrases(six):
            self.assertIn(phrase, text)

    def test_case_13_initial_search_regression(self) -> None:
        design = _design(
            rq_text=IN1_RQ,
            description=IN1_DESCRIPTION,
            expectation=_ee(IN1_ASPECTS),
        )
        initial = SearchQueryBuilder(max_results=3).build_queries(design)[0].query_text
        # P1-21.1: initial Search now includes parent RQ subject_context (parity
        # with targeted Search). Aspect/geo/timeframe contract otherwise unchanged.
        expected = build_expectation_aware_query_text(
            subject_context=IN1_RQ,
            description=IN1_DESCRIPTION,
            geography="Serbia",
            timeframe="2019-2026",
            semantic_targets=IN1_ASPECTS,
        )
        self.assertEqual(initial, expected)
        self.assertTrue(initial.casefold().startswith("what is the serbian premium"))
        self.assertIn("microgreens", initial.casefold())
        for phrase in _phrases(IN1_ASPECTS):
            self.assertIn(phrase, initial)

    def test_case_14_no_extra_llm_or_provider_imports(self) -> None:
        for path in (INTENT_PATH, TARGETED_PATH):
            source = path.read_text(encoding="utf-8")
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

    def test_case_15_profile_b_config_invariants(self) -> None:
        self.assertEqual(PROFILE_B_WORKER["TARGETED_MAX_QUERIES_PER_GAP"], "1")
        self.assertEqual(PROFILE_B_WORKER["TARGETED_MAX_SOURCES_PER_GAP"], "1")
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_REMEDIATION_MAX_LLM_CALLS_PER_ATTEMPT"], "3")
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS"], "6")
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_MAX_LLM_CALLS"], "36")

    def test_case_16_seven_aspect_contract_not_pathologically_duplicated(self) -> None:
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description="Size market value and volume proxies.",
            expectation=_ee(SEVEN_ASPECTS),
        )
        text = _build(design, _request(missing_aspects=()))[0].query_text
        for phrase in _phrases(SEVEN_ASPECTS):
            self.assertIn(phrase, text)
        self.assertEqual(text.casefold().count("serbian premium microgreens market"), 1)

    def test_case_17_no_methodological_blacklist_dependency(self) -> None:
        # Use a lead verb that is not in the forensic example list.
        design = _design(
            rq_text="What is the Serbian premium microgreens market for HoReCa?",
            description=(
                "Synthesize supply-demand balance and capacity gaps to infer "
                "attainable share for a new entrant."
            ),
            expectation=_ee(IN12_ASPECTS),
        )
        text = _build(design, _request(missing_aspects=()))[0].query_text
        self.assertTrue(text.casefold().startswith("what is the serbian premium microgreens"))
        self.assertIn("synthesize", text.casefold())
        self.assertIn("microgreens", text.casefold())
        for phrase in _phrases(IN12_ASPECTS):
            self.assertIn(phrase, text)
        targeted_src = TARGETED_PATH.read_text(encoding="utf-8")
        for verb in (
            "triangulate",
            "assess",
            "evaluate",
            "estimate",
            "identify",
            "analyze",
            "compare",
            "review",
            "synthesize",
        ):
            self.assertNotIn(f'"{verb}"', targeted_src)
            self.assertNotIn(f"'{verb}'", targeted_src)

    def test_case_18_rq_topic_before_local_method_context(self) -> None:
        design = _design(
            rq_text=IN12_RQ,
            need_id="IN12",
            description=IN12_DESCRIPTION,
            expectation=_ee(IN12_ASPECTS),
        )
        text = _build(design, _request(need_id="IN12", missing_aspects=()))[0].query_text
        rq_pos = text.casefold().find("serbian premium microgreens")
        method_pos = text.casefold().find("triangulate")
        self.assertGreaterEqual(rq_pos, 0)
        self.assertGreaterEqual(method_pos, 0)
        self.assertLess(rq_pos, method_pos)


class SharedHelperCompatibilityTests(unittest.TestCase):
    def test_subject_context_optional_preserves_initial_call_shape(self) -> None:
        without = build_expectation_aware_query_text(
            description="Estimate market size.",
            geography="Serbia",
            timeframe="2019-2026",
            semantic_targets=("market_value_estimate",),
        )
        with_empty = build_expectation_aware_query_text(
            description="Estimate market size.",
            geography="Serbia",
            timeframe="2019-2026",
            semantic_targets=("market_value_estimate",),
            subject_context=None,
        )
        self.assertEqual(without, with_empty)

    def test_helper_source_has_no_llm_budget_coupling(self) -> None:
        source = INTENT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("budget", source.lower())
        builder_src = inspect.getsource(SearchQueryBuilder._build_query)
        targeted_src = inspect.getsource(TargetedSearchQueryBuilder.build_queries)
        resolve_src = inspect.getsource(TargetedSearchQueryBuilder._resolve_semantic_targets)
        self.assertIn("build_expectation_aware_query_text", builder_src)
        self.assertIn("build_expectation_aware_query_text", targeted_src)
        self.assertIn("missing_aspects", resolve_src)
        self.assertIn("required_aspects", resolve_src)
        self.assertIn("subject_context", targeted_src)
        self.assertIn("subject_context", builder_src)


if __name__ == "__main__":
    unittest.main()
