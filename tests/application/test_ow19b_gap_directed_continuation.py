"""OW-19B finite gap-directed Desk continuation regressions."""

import unittest
from dataclasses import replace

from application.methods.desk.adapter import DeskAdapter
from application.execution.execution_budget_context import execution_budget_scope
from application.execution.execution_budget_factory import create_execution_budget
from application.research_kernel.controller import Controller
from application.research_kernel.contracts import Gap, Observation
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.research_subject import (
    LexicalRepresentation,
    RepresentationApprovalStatus,
    ResearchSubject,
    SubjectResolutionStatus,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus
from tests.application.test_ark02_desk import Search, fixture
from tests.application.test_ark02_kernel import Store


def _design() -> ResearchDesign:
    expectation = EvidenceExpectation(
        nature=EvidenceNature.MIXED,
        required_aspects=("market_measure", "decision_driver"),
        geography="Market Y",
        timeframe="2025-2026",
        minimum_independent_sources=1,
        requires_quantitative_evidence=True,
    )
    return ResearchDesign(
        "generic-product-x",
        research_questions=(ResearchQuestion("rq", "Product category X in Market Y"),),
        information_needs=(
            InformationNeed("in-zero", "rq", "Competitors and positioning", geography="Market Y",
                            evidence_expectation=expectation),
            InformationNeed("in-aspect", "rq", "Pricing and value", geography="Market Y",
                            evidence_expectation=expectation),
            InformationNeed("in-depth", "rq", "Channels and preferences", geography="Market Y",
                            evidence_expectation=expectation),
        ),
        language="en",
        research_subject=ResearchSubject(
            subject_id="product-x",
            canonical_label="Product category X",
            canonical_language="en",
            core_concepts=("product-category-x",),
            lexical_representations=(LexicalRepresentation(
                "product-x-en", "en", "Product category X",
                ("product category x",), ("product-category-x",), "fixture",
                RepresentationApprovalStatus.APPROVED,
            ),),
            resolution_status=SubjectResolutionStatus.RESOLVED,
        ),
    )


def _result() -> ResearchReadinessResult:
    needs = (
        InformationNeedAssessment(
            "in-zero", "rq", SufficiencyStatus.MISSING, evidence_count=0,
            missing_aspects=("market_measure",), gap_types=(GapType.NO_EVIDENCE,),
            search_directives=("competitor market share",),
        ),
        InformationNeedAssessment(
            "in-aspect", "rq", SufficiencyStatus.INSUFFICIENT, evidence_count=1,
            missing_aspects=("decision_driver",), gap_types=(GapType.INSUFFICIENT_DEPTH,),
            search_directives=("willingness to pay",),
        ),
        InformationNeedAssessment(
            "in-depth", "rq", SufficiencyStatus.INSUFFICIENT, evidence_count=1,
            gap_types=(GapType.INSUFFICIENT_DIVERSITY,),
            search_directives=("independent channel evidence",),
        ),
    )
    rq = ResearchReadinessAssessment(
        "rq", needs, False, tuple(item.information_need_id for item in needs),
    )
    return ResearchReadinessResult(
        (rq,), False, ("rq",), tuple(item.information_need_id for item in needs), True,
    )


def _continuation_adapter():
    config, context, sources, evidence, llm, adapter, overrides, client = fixture()
    design = _design()
    adapter.design = design
    adapter.primitives.design = design
    adapter.last_result = _result()
    state = adapter.initial_state()
    state.used["initial"] = state.limits["initial"]
    state.used["initial_llm"] = state.limits["initial_llm"]
    observation = Observation(
        "authoritative-gap-state",
        tuple(
            # Deliberately reverse lexical ordering: policy must prefer zero,
            # then a required aspect, then depth-only enrichment.
            Gap(
                assessment.information_need_id,
                assessment.status.value,
                index,
                assessment.evidence_count,
                assessment.missing_aspects,
            )
            for index, assessment in enumerate(
                _result().research_question_assessments[0].information_need_assessments
            )
        ),
    )
    return config, context, sources, evidence, llm, adapter, state, observation


class GapDirectedContinuationTests(unittest.TestCase):
    def test_blocking_gap_materializes_compact_targeted_search(self):
        _, _, _, _, _, adapter, state, observation = _continuation_adapter()
        searches = [action for action in adapter.propose(state, observation) if action.kind == "search"]
        self.assertTrue(searches)
        self.assertEqual(searches[0].target, "in-zero")
        query = adapter.queries[searches[0].refs[0]]
        self.assertIn("Product category X", query.provider_query_text)
        self.assertIn("Market Y", query.provider_query_text)
        self.assertIn("market measure", query.provider_query_text)
        self.assertNotIn("Channels and preferences", query.provider_query_text)

    def test_zero_then_missing_aspect_then_depth_priority_is_deterministic(self):
        _, _, _, _, _, adapter, state, observation = _continuation_adapter()
        searches = [action for action in adapter.propose(state, observation) if action.kind == "search"]
        self.assertEqual([action.target for action in searches], ["in-zero", "in-aspect", "in-depth"])

    def test_same_directive_is_not_proposed_twice_after_reconciliation(self):
        _, _, _, _, _, adapter, state, observation = _continuation_adapter()
        first = next(action for action in adapter.propose(state, observation) if action.kind == "search")
        state.attempted_strategies.append(first.strategy_key)
        repeated = adapter.propose(state, observation)
        self.assertNotIn(first.strategy_key, [action.strategy_key for action in repeated])

    def test_restart_rebuilds_same_identity_without_duplicate_dispatch(self):
        config, context, _, evidence, _, adapter, state, observation = _continuation_adapter()
        first = next(action for action in adapter.propose(state, observation) if action.kind == "search")
        state.attempted_strategies.append(first.strategy_key)
        restarted = DeskAdapter(context, config, adapter.primitives, adapter.readiness, evidence)
        restarted.design = adapter.design
        restarted.primitives.design = adapter.design
        restarted.last_result = adapter.last_result
        self.assertNotIn(first.strategy_key, [
            action.strategy_key for action in restarted.propose(state, observation)
        ])

    def test_search_envelope_uses_configured_continuation_partition_only(self):
        config, _, _, _, _, adapter, state, _ = _continuation_adapter()
        paths = len(adapter.design.information_needs) * min(
            config.research_max_gap_rounds_per_run,
            config.targeted_max_attempts_per_gap,
        )
        self.assertEqual(
            state.limits["continuation_search"],
            paths * config.targeted_max_queries_per_gap,
        )
        self.assertEqual(
            state.limits["search"],
            state.limits["initial_search"] + state.limits["continuation_search"],
        )

    def test_nominal_global_capacity_without_gap_capacity_is_not_an_opportunity(self):
        _, _, _, _, _, adapter, state, observation = _continuation_adapter()
        for need in adapter.design.information_needs:
            state.used["search:gap:" + need.id] = state.limits["search:gap:" + need.id]
        self.assertFalse([action for action in adapter.propose(state, observation) if action.kind == "search"])

    def test_zero_evidence_exhausted_initial_arms_open_targeted_search(self):
        config, context, _, evidence, _, adapter, _, _ = fixture()
        expectation = EvidenceExpectation(
            EvidenceNature.QUANTITATIVE,
            required_aspects=("market_measure",),
            requires_quantitative_evidence=True,
        )
        adapter.design = replace(
            adapter.design,
            information_needs=tuple(
                replace(need, evidence_expectation=expectation)
                for need in adapter.design.information_needs
            ),
        )
        adapter.primitives.design = adapter.design

        class TargetOnlySearch(Search):
            def search(self, query):
                return super().search(query) if query.id.startswith("sq-target-") else []

        adapter.primitives.acquisition._search_provider.delegate = TargetOnlySearch()
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(adapter.initial_state())
            adapter.finish(result)
        self.assertEqual(result.used["initial_search"], result.limits["initial_search"])
        self.assertGreater(result.used.get("continuation_search", 0), 0)
        self.assertLessEqual(result.used["continuation_search"], result.limits["continuation_search"])
        self.assertFalse(context.shared_state["research_readiness"]["ready_for_analysis"])
        self.assertFalse(evidence.list_for_project(context.project.id))

    def test_duplicate_continuation_frontier_stops_within_finite_envelope(self):
        config, context, _, _, _, adapter, _, _ = fixture()

        class DuplicateTargetSearch(Search):
            def search(self, query):
                rows = super().search(query) if query.id.startswith("sq-target-") else []
                return [replace(item, url="https://example.test/one-source") for item in rows]

        adapter.primitives.acquisition._search_provider.delegate = DuplicateTargetSearch()
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(adapter.initial_state())
        self.assertIsNotNone(result.terminal)
        self.assertLessEqual(result.used.get("continuation_search", 0), result.limits["continuation_search"])
        self.assertLessEqual(result.used.get("continuation_acquisitions", 0),
                             result.limits["continuation_acquisitions"])


if __name__ == "__main__":
    unittest.main()
