"""P1-21.1 — Initial Search subject/category anchoring (offline acceptance)."""

from __future__ import annotations

import ast
import inspect
import json
import re
import unittest
from pathlib import Path

from application.research_quality.targeted_search_query_builder import (
    TargetedSearchQueryBuilder,
)
from application.sources.expectation_aware_query_intent import (
    build_expectation_aware_query_text,
)
from application.sources.search_query_builder import SearchQueryBuilder
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.targeted_research_request import TargetedResearchRequest

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILDER_PATH = REPO_ROOT / "application" / "sources" / "search_query_builder.py"
INTENT_PATH = REPO_ROOT / "application" / "sources" / "expectation_aware_query_intent.py"
FORENSICS_DUMP = REPO_ROOT / "artifacts" / "acceptance" / "p1_21_forensics_dump.json"

PIZZA_CATEGORY_RE = re.compile(r"\b(pizza|pizzeria|pizzerias)\b", re.I)
UKRAINE_RE = re.compile(r"\b(ukraine|ukrainian)\b", re.I)


def _ee(
    aspects: tuple[str, ...] = (),
    *,
    quantitative: bool = False,
    geography: str | None = "Ukraine",
    timeframe: str | None = "2024-2026",
) -> EvidenceExpectation:
    return EvidenceExpectation(
        nature=EvidenceNature.QUANTITATIVE if quantitative else EvidenceNature.MIXED,
        required_aspects=aspects,
        geography=geography,
        timeframe=timeframe,
        requires_quantitative_evidence=quantitative,
    )


def _design(
    *,
    rq_text: str,
    need_description: str,
    need_id: str = "IN1",
    rq_id: str = "RQ1",
    geography: str = "Ukraine",
    timeframe: str = "2024-2026",
    expectation: EvidenceExpectation | None = None,
) -> ResearchDesign:
    return ResearchDesign(
        id="design-p1-21-1",
        research_questions=(
            ResearchQuestion(id=rq_id, question=rq_text, objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id=need_id,
                research_question_id=rq_id,
                description=need_description,
                geography=geography,
                timeframe=timeframe,
                evidence_expectation=expectation,
            ),
        ),
        language="en",
    )


def _old_query_without_subject(
    *,
    description: str,
    geography: str | None,
    timeframe: str | None,
    aspects: tuple[str, ...] = (),
) -> str:
    return build_expectation_aware_query_text(
        description=description,
        geography=geography,
        timeframe=timeframe,
        semantic_targets=aspects,
    )


def _load_p1_20_2_design() -> ResearchDesign | None:
    if not FORENSICS_DUMP.is_file():
        return None
    payload = json.loads(FORENSICS_DUMP.read_text(encoding="utf-8"))
    design = payload.get("design")
    if not isinstance(design, dict):
        return None
    return ResearchDesign.from_dict(design)


class P1211InitialSearchSubjectAnchoringTests(unittest.TestCase):
    """CASE 1–25 offline acceptance matrix."""

    def test_case_01_generic_in_pizza_rq_anchor_present(self) -> None:
        design = _design(
            rq_text="How has the pizza market in Ukraine developed?",
            need_description="Macroeconomic and wartime factors affecting demand",
            expectation=_ee(("income_trends", "population_shifts")),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertRegex(text, PIZZA_CATEGORY_RE)
        self.assertIn("macroeconomic", text.casefold())

    def test_case_02_macro_in_pizza_rq_both_present(self) -> None:
        design = _design(
            rq_text="How have the full-scale war and subsequent changes affected the pizza market?",
            need_description=(
                "Impact of war on supply: store closures/openings, operating hours, "
                "staffing, input costs, utilities, and logistics."
            ),
            expectation=_ee(("supply_chain_disruptions", "cost_inflation")),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("pizza", text)
        self.assertTrue("war" in text or "logistics" in text or "supply" in text)

    def test_case_03_delivery_in_pizza_rq(self) -> None:
        design = _design(
            rq_text="What are the key pizza consumption, ordering, and delivery trends in Ukraine?",
            need_description=(
                "Delivery trends: platform penetration, delivery times, "
                "service reliability, pick-up/carryout trends."
            ),
            expectation=_ee(("platform_penetration", "delivery_speed")),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("pizza", text)
        self.assertIn("delivery", text)

    def test_case_04_consumer_in_pizza_rq(self) -> None:
        design = _design(
            rq_text="How are consumers ordering pizza in Ukraine?",
            need_description="Ordering behavior and digital channels",
            expectation=_ee(("order_frequency", "channel_split")),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("pizza", text)
        self.assertTrue("ordering" in text or "consumer" in text or "channel" in text)

    def test_case_05_competition_in_pizza_rq(self) -> None:
        design = _design(
            rq_text="Who are the main pizza chains in Ukraine?",
            need_description="Competitive structure and market participants",
            expectation=_ee(("top_players_share_proxy", "outlet_concentration")),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("pizza", text)
        self.assertTrue("competitive" in text or "participants" in text)

    def test_case_06_already_anchored_in_no_excessive_duplication(self) -> None:
        design = _design(
            rq_text="What is the current size of the Ukrainian pizza market?",
            need_description=(
                "Total pizza market value and volume estimates with 3–5 years "
                "historical trend and 2024 baseline."
            ),
            expectation=_ee(("market_value_uah", "market_volume_units")),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        # Dedup: full RQ phrase must not be naively repeated as a second identical blob
        # beyond what phrase-level dedup allows; "pizza" may appear more than once across
        # RQ + IN, but "pizza pizza pizza" style stacking of identical tokens is avoided
        # by phrase dedup for identical fragments.
        self.assertNotIn("pizza pizza pizza", text)
        self.assertEqual(text.count("what is the current size of the ukrainian pizza market?"), 1)

    def test_case_07_ukraine_geo_preserved(self) -> None:
        design = _design(
            rq_text="Pizza restaurant market outlook",
            need_description="Growth drivers and barriers",
            geography="Ukraine",
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertRegex(text, UKRAINE_RE)

    def test_case_08_timeframe_preserved(self) -> None:
        design = _design(
            rq_text="Ukrainian pizza category opportunities",
            need_description="Opportunity spaces and white spaces",
            timeframe="2024–2026",
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertIn("2024", text)
        self.assertIn("2026", text)

    def test_case_09_ee_required_aspects_preserved(self) -> None:
        aspects = ("channel_share_mix", "chain_vs_independent_share")
        design = _design(
            rq_text="Ukrainian pizza market segmentation",
            need_description="Market segmentation by channel and ownership",
            expectation=_ee(aspects),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertIn("channel share mix", text)
        self.assertIn("chain vs independent share", text)

    def test_case_10_quantitative_expectation_semantics_preserved(self) -> None:
        ee = _ee(("market_value_uah",), quantitative=True)
        design = _design(
            rq_text="Ukrainian pizza market size",
            need_description="Market value estimates",
            expectation=ee,
        )
        query = SearchQueryBuilder().build_queries(design)[0]
        need = design.information_needs[0]
        self.assertTrue(need.evidence_expectation.requires_quantitative_evidence)
        self.assertIn("market value uah", query.query_text)
        # Quantitative flag is EE metadata; query count remains one per IN.
        self.assertEqual(len(SearchQueryBuilder().build_queries(design)), 1)

    def test_case_11_empty_rq_subject_falls_back_safely(self) -> None:
        design = _design(
            rq_text="",
            need_description="Published brand tracking statistics",
            geography="Germany",
            timeframe="2024-2026",
            expectation=None,
        )
        # Empty parent question → subject_context omitted → prior IN-only composition.
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        expected = build_expectation_aware_query_text(
            description="Published brand tracking statistics",
            geography="Germany",
            timeframe="2024-2026",
            semantic_targets=(),
        )
        self.assertEqual(text, expected)

    def test_case_12_heat_pump_domain(self) -> None:
        design = _design(
            rq_text="What is the heat pump deployment outlook in the UK?",
            need_description="Installation rates and policy incentives",
            geography="United Kingdom",
            expectation=_ee(("installation_rate",), geography="United Kingdom"),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("heat pump", text)
        self.assertNotIn("pizza", text)

    def test_case_13_upi_domain(self) -> None:
        design = _design(
            rq_text="How is UPI adoption evolving among Indian SMEs?",
            need_description="Transaction volumes and merchant onboarding",
            geography="India",
            expectation=_ee(("transaction_volume",), geography="India"),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("upi", text)
        self.assertNotIn("pizza", text)

    def test_case_14_electricity_domain(self) -> None:
        design = _design(
            rq_text="What drives industrial electricity prices in Germany?",
            need_description="Wholesale price trends and grid fees",
            geography="Germany",
            expectation=_ee(("wholesale_price_trend",), geography="Germany"),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text.casefold()
        self.assertIn("electricity", text)
        self.assertNotIn("pizza", text)

    def test_case_15_no_pizza_hardcoding_in_builder(self) -> None:
        builder_src = BUILDER_PATH.read_text(encoding="utf-8").casefold()
        intent_src = INTENT_PATH.read_text(encoding="utf-8").casefold()
        self.assertNotIn("pizza", builder_src)
        self.assertNotIn("pizzeria", builder_src)
        self.assertNotIn("pizza", intent_src)
        self.assertNotIn("pizzeria", intent_src)

    def test_case_16_targeted_search_subject_context_unchanged(self) -> None:
        design = _design(
            rq_text="How has the pizza market in Ukraine developed?",
            need_description="Macroeconomic and wartime factors affecting demand",
            expectation=_ee(("income_trends",)),
        )
        request = TargetedResearchRequest(
            workflow_run_id="run-1",
            research_design_id=design.id,
            research_question_id="RQ1",
            information_need_id="IN1",
            gap_types=(GapType.INSUFFICIENT_DEPTH,),
            missing_aspects=("income_trends",),
            search_directives=("income_trends",),
            attempt=1,
        )
        targeted = TargetedSearchQueryBuilder().build_queries(
            design=design,
            request=request,
            max_queries=1,
            max_results=3,
        )[0].query_text
        # Targeted still includes RQ subject and missing aspect.
        self.assertIn("pizza", targeted.casefold())
        self.assertIn("income trends", targeted)
        targeted_src = inspect.getsource(TargetedSearchQueryBuilder.build_queries)
        self.assertIn("subject_context", targeted_src)

    def test_case_17_query_count_unchanged_one_per_need(self) -> None:
        design = ResearchDesign(
            id="multi",
            research_questions=(
                ResearchQuestion(id="RQ1", question="Pizza market size?", objective_refs=()),
                ResearchQuestion(id="RQ2", question="Pizza chains?", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(
                    id="IN1",
                    research_question_id="RQ1",
                    description="Value estimates",
                    geography="Ukraine",
                ),
                InformationNeed(
                    id="IN2",
                    research_question_id="RQ2",
                    description="Brand roster",
                    geography="Ukraine",
                ),
            ),
            language="en",
        )
        queries = SearchQueryBuilder(max_results=5).build_queries(design)
        self.assertEqual(len(queries), 2)
        self.assertEqual({q.max_results for q in queries}, {5})

    def test_case_18_builder_does_not_import_scheduler(self) -> None:
        source = BUILDER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("evidence_extraction_scheduler", source)
        self.assertNotIn("build_need_fair_extraction_queue", source)

    def test_case_19_and_20_21_p1_20_2_twelve_in_replay(self) -> None:
        design = _load_p1_20_2_design()
        if design is None:
            self.skipTest("P1-21 forensics dump with design snapshot not available")

        old_by_id: dict[str, str] = {}
        new_by_id: dict[str, str] = {}
        for need in design.information_needs:
            aspects = (
                need.evidence_expectation.required_aspects
                if need.evidence_expectation is not None
                else ()
            )
            old_by_id[need.id] = _old_query_without_subject(
                description=need.description,
                geography=need.geography or None,
                timeframe=need.timeframe or None,
                aspects=aspects,
            )
        for query in SearchQueryBuilder().build_queries(design):
            new_by_id[query.information_need_id] = query.query_text

        self.assertEqual(len(new_by_id), 12)
        old_anchored = sum(1 for t in old_by_id.values() if PIZZA_CATEGORY_RE.search(t))
        new_anchored = sum(1 for t in new_by_id.values() if PIZZA_CATEGORY_RE.search(t))
        self.assertLessEqual(old_anchored, 4)
        self.assertEqual(new_anchored, 12)

        # CASE 20 — IN2 no longer pizza-free
        self.assertIsNone(PIZZA_CATEGORY_RE.search(old_by_id["IN2"]))
        self.assertIsNotNone(PIZZA_CATEGORY_RE.search(new_by_id["IN2"]))
        self.assertIn("segmentation", new_by_id["IN2"].casefold())

        # CASE 21 — IN9–IN11 macro remain category-scoped
        for need_id in ("IN9", "IN10", "IN11"):
            self.assertIsNone(PIZZA_CATEGORY_RE.search(old_by_id[need_id]))
            self.assertIsNotNone(PIZZA_CATEGORY_RE.search(new_by_id[need_id]))
            self.assertRegex(new_by_id[need_id], UKRAINE_RE)

        # Zero pizza-free queries among the former drift set
        for need_id in ("IN2", "IN5", "IN6", "IN8", "IN9", "IN10", "IN11", "IN12"):
            self.assertIsNotNone(
                PIZZA_CATEGORY_RE.search(new_by_id[need_id]),
                msg=f"{need_id} still pizza-free: {new_by_id[need_id]!r}",
            )

    def test_case_22_query_text_non_empty_and_bounded(self) -> None:
        design = _design(
            rq_text="What is the current size of the Ukrainian pizza market and how has it evolved?",
            need_description=(
                "Total pizza market value and volume estimates with 3–5 years "
                "historical trend and 2024 baseline."
            ),
            expectation=_ee(
                (
                    "market_value_uah",
                    "market_volume_units",
                    "historical_trend",
                    "methodology_transparency",
                )
            ),
        )
        text = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertTrue(text.strip())
        # Soft bound: subject+IN+aspects+geo+tf should stay a single searchable string.
        self.assertLessEqual(len(text), 1200)

    def test_case_23_deterministic_same_input_same_query(self) -> None:
        design = _design(
            rq_text="Who are the principal pizza market participants in Ukraine?",
            need_description="Competitive structure indicators",
            expectation=_ee(("top_players_share_proxy",)),
        )
        left = SearchQueryBuilder().build_queries(design)[0].query_text
        right = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertEqual(left, right)

    def test_case_24_no_llm_calls_introduced(self) -> None:
        for path in (BUILDER_PATH, INTENT_PATH):
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
            self.assertNotIn("llm", source.casefold())

    def test_case_25_no_budget_cap_changes_in_touched_files(self) -> None:
        for path in (BUILDER_PATH, INTENT_PATH):
            source = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn("max_llm", source)
            self.assertNotIn("budget", source)
            self.assertNotIn("evidence_max", source)


class P1211GoldenSearchQualityCase(unittest.TestCase):
    """Core golden fixture from P1-21 forensic."""

    def test_golden_generic_macro_need_under_pizza_rq(self) -> None:
        design = _design(
            rq_text=(
                "How have the full-scale war and subsequent changes in consumer "
                "behavior, restaurant operations, and delivery infrastructure "
                "affected the pizza market?"
            ),
            need_description=(
                "Impact of war on supply: store closures/openings, operating hours, "
                "staffing, input costs, utilities, and logistics."
            ),
            need_id="IN10",
            geography="Ukraine",
            timeframe="2022–2024",
            expectation=_ee(
                (
                    "unit_open_close",
                    "operating_constraints",
                    "labor_availability",
                    "cost_inflation",
                    "supply_chain_disruptions",
                ),
                timeframe="2022–2024",
            ),
        )
        old = _old_query_without_subject(
            description=design.information_needs[0].description,
            geography="Ukraine",
            timeframe="2022–2024",
            aspects=design.information_needs[0].evidence_expectation.required_aspects,
        )
        new = SearchQueryBuilder().build_queries(design)[0].query_text
        self.assertIsNone(PIZZA_CATEGORY_RE.search(old))
        self.assertIsNotNone(PIZZA_CATEGORY_RE.search(new))
        self.assertRegex(new, UKRAINE_RE)
        self.assertIn("war", new.casefold())
        self.assertIn("supply chain disruptions", new)
        self.assertIn("2022", new)


if __name__ == "__main__":
    unittest.main()
