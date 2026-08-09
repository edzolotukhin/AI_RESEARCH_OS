"""P1-07.12.1 bounded TargetedResearchRequest directive construction."""

from __future__ import annotations

import inspect
import unittest

from application.research_quality.bounded_search_directives import (
    bound_targeted_search_directives,
)
from application.research_quality.gap_selection import select_actionable_gaps
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.sufficiency_assessment_cache import (
    SufficiencyAssessmentCache,
    _current_cache,
    clear_sufficiency_assessment_cache,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION,
    build_sufficiency_assessment_fingerprint,
)
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from domain.common.exceptions import ValidationError
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import (
    QUALITY_CONTRACT_EXPLICIT,
    InformationNeedAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import (
    MAX_TARGETED_SEARCH_DIRECTIVES,
    TargetedResearchRequest,
)

from tests.application.research_quality.test_hybrid_sufficiency_evaluator import (
    RecordingSemanticAssessor,
    _evidence,
    _semantic,
)
from tests.application.research_quality.test_targeted_research_loop import (
    SequentialSufficiencyEvaluator,
    _build_service,
    _context,
    _design,
    _result_for_needs,
)

SIX_ASPECTS = (
    "market_size",
    "growth_rate",
    "price_level",
    "competitive_intensity",
    "distribution_channels",
    "regulatory_barriers",
)
SEVEN_ASPECTS = SIX_ASPECTS + ("chef_usage",)
FIVE_ASPECTS = SIX_ASPECTS[:5]
THREE_ASPECTS = SIX_ASPECTS[:3]


def _gap_assessment(
    *,
    aspects: tuple[str, ...],
    status: SufficiencyStatus = SufficiencyStatus.INSUFFICIENT,
) -> InformationNeedAssessment:
    return InformationNeedAssessment(
        information_need_id="in-1",
        research_question_id="rq-1",
        status=status,
        evidence_count=1,
        gap_types=(GapType.INSUFFICIENT_DEPTH,),
        missing_aspects=aspects,
        search_directives=aspects,
        reason="Missing required aspects.",
        quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
        required_aspect_ids=aspects,
    )


def _select_request(aspects: tuple[str, ...]) -> TargetedResearchRequest:
    gaps = select_actionable_gaps(
        result=_result_for_needs(_gap_assessment(aspects=aspects)),
        design=_design(),
        workflow_run_id="run-1",
        attempt=1,
        existing_source_ids=(),
        existing_evidence_ids=(),
    )
    assert len(gaps) == 1
    return gaps[0]


def _aspects_represented(aspects: tuple[str, ...], directives: tuple[str, ...]) -> bool:
    blob = " ".join(directives)
    return all(aspect in blob for aspect in aspects)


class CapturingZeroYieldRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[TargetedResearchRequest] = []

    def run(self, context, request: TargetedResearchRequest) -> TargetedResearchIterationResult:
        self.calls += 1
        self.requests.append(request)
        return TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
        )


class BoundSearchDirectivePackerTests(unittest.TestCase):
    def test_case_1_one_to_five_aspects_pass_through(self) -> None:
        for aspects in (SIX_ASPECTS[:1], THREE_ASPECTS, FIVE_ASPECTS):
            request = _select_request(aspects)
            self.assertLessEqual(len(request.search_directives), 5)
            self.assertEqual(request.search_directives, aspects)
            self.assertEqual(request.missing_aspects, aspects)
            self.assertTrue(_aspects_represented(aspects, request.search_directives))

    def test_case_2_six_missing_aspects_pack_without_validation_error(self) -> None:
        request = _select_request(SIX_ASPECTS)
        self.assertLessEqual(len(request.search_directives), MAX_TARGETED_SEARCH_DIRECTIVES)
        self.assertEqual(len(request.search_directives), 5)
        self.assertEqual(request.missing_aspects, SIX_ASPECTS)
        self.assertTrue(_aspects_represented(SIX_ASPECTS, request.search_directives))

    def test_case_3_seven_plus_missing_aspects_remain_represented(self) -> None:
        eight = SEVEN_ASPECTS + ("import_dependence",)
        request = _select_request(eight)
        self.assertLessEqual(len(request.search_directives), 5)
        self.assertEqual(len(request.search_directives), 5)
        self.assertEqual(request.missing_aspects, eight)
        self.assertTrue(_aspects_represented(eight, request.search_directives))

    def test_case_4_identical_gap_input_yields_identical_directives(self) -> None:
        first = bound_targeted_search_directives(SIX_ASPECTS)
        second = bound_targeted_search_directives(SIX_ASPECTS)
        self.assertEqual(first, second)
        self.assertEqual(
            _select_request(SEVEN_ASPECTS).search_directives,
            _select_request(SEVEN_ASPECTS).search_directives,
        )

    def test_case_5_aspect_beyond_position_five_is_not_dropped(self) -> None:
        request = _select_request(SIX_ASPECTS)
        sixth = SIX_ASPECTS[5]
        self.assertNotIn(sixth, FIVE_ASPECTS)
        self.assertIn(sixth, request.missing_aspects)
        self.assertTrue(_aspects_represented((sixth,), request.search_directives))
        self.assertNotEqual(request.search_directives, FIVE_ASPECTS)

    def test_case_6_domain_still_rejects_more_than_five_raw_directives(self) -> None:
        with self.assertRaises(ValidationError) as raised:
            TargetedResearchRequest(
                workflow_run_id="run-1",
                research_design_id="design-1",
                research_question_id="rq-1",
                information_need_id="in-1",
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                missing_aspects=SIX_ASPECTS,
                search_directives=SIX_ASPECTS,
            )
        self.assertIn("search_directives must contain at most 5 items", str(raised.exception))
        with self.assertRaises(ValidationError):
            TargetedResearchRequest.from_dict(
                {
                    "workflow_run_id": "run-1",
                    "research_design_id": "design-1",
                    "research_question_id": "rq-1",
                    "information_need_id": "in-1",
                    "gap_types": ["insufficient_depth"],
                    "missing_aspects": list(SEVEN_ASPECTS),
                    "search_directives": list(SEVEN_ASPECTS),
                    "attempt": 1,
                },
            )


class TargetedBoundedLoopIntegrationTests(unittest.TestCase):
    def test_case_7_readiness_gap_with_oversize_aspects_reaches_targeted_search(self) -> None:
        runner = CapturingZeroYieldRunner()
        gap_result = _result_for_needs(_gap_assessment(aspects=SIX_ASPECTS))
        service = _build_service(
            SequentialSufficiencyEvaluator([gap_result]),
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=1,
        )
        result = service.assess_and_apply(_context())
        self.assertGreaterEqual(runner.calls, 1)
        request = runner.requests[0]
        self.assertEqual(request.information_need_id, "in-1")
        self.assertLessEqual(len(request.search_directives), 5)
        self.assertTrue(_aspects_represented(SIX_ASPECTS, request.search_directives))
        self.assertFalse(result.ready_for_analysis)

    def test_case_8_zero_yield_terminates_without_directive_count_crash(self) -> None:
        runner = CapturingZeroYieldRunner()
        gap_result = _result_for_needs(_gap_assessment(aspects=SEVEN_ASPECTS))
        service = _build_service(
            SequentialSufficiencyEvaluator([gap_result]),
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=2,
        )
        result = service.assess_and_apply(_context())
        self.assertGreaterEqual(runner.calls, 1)
        self.assertLessEqual(len(runner.requests[0].search_directives), 5)
        self.assertFalse(result.ready_for_analysis)
        self.assertIn(
            result.termination_reason,
            {"no_material_improvement", "max_research_rounds", "no_actionable_gaps"},
        )
        self.assertNotIn("search_directives", str(result.termination_reason or ""))


class IncrementalSufficiencyRegressionTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sufficiency_assessment_cache()

    def test_case_9_fingerprint_and_reuse_unchanged_for_six_aspect_expectation(self) -> None:
        self.assertEqual(SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION, "p1-07-11.1")
        source = inspect.getsource(build_sufficiency_assessment_fingerprint)
        self.assertNotIn("bound_targeted_search_directives", source)
        self.assertNotIn("search_directives", source)

        cache = SufficiencyAssessmentCache()
        _current_cache.set(cache)
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        need = InformationNeed(
            id="in-1",
            research_question_id="rq-1",
            description="Need in-1",
            evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.MIXED,
                required_aspects=SIX_ASPECTS,
            ),
        )
        design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q?", objective_refs=()),
            ),
            information_needs=(need,),
        )
        evidence = (_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),)
        first = evaluator.evaluate(design=design, evidence=evidence)
        second = evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(cache.reused_assessments, 1)
        self.assertEqual(
            first.research_question_assessments[0].information_need_assessments[0].status,
            second.research_question_assessments[0].information_need_assessments[0].status,
        )
        rq = design.research_questions[0]
        by_id = {evidence[0].id: evidence[0]}
        self.assertEqual(
            build_sufficiency_assessment_fingerprint(
                information_need=need,
                research_question=rq,
                evidence_ids=(evidence[0].id,),
                evidence_by_id=by_id,
                max_evidence_items=10,
            ),
            build_sufficiency_assessment_fingerprint(
                information_need=need,
                research_question=rq,
                evidence_ids=(evidence[0].id,),
                evidence_by_id=by_id,
                max_evidence_items=10,
            ),
        )

    def test_packer_introduces_no_llm_dependency(self) -> None:
        source = inspect.getsource(bound_targeted_search_directives)
        self.assertNotIn("llm", source.lower())
        module_source = inspect.getsource(
            __import__(
                "application.research_quality.bounded_search_directives",
                fromlist=["bound_targeted_search_directives"],
            ),
        )
        self.assertNotIn("openai", module_source.lower())


if __name__ == "__main__":
    unittest.main()
