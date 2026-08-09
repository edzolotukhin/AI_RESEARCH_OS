"""P1-07.10.2 structural offline regression for P1-07.11 control-loop fixes."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.execution.budget_utils import EVIDENCE_PURPOSE_REMEDIATION
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import _current_budget
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.sufficiency_assessment_cache import (
    SufficiencyAssessmentCache,
    _current_cache,
    clear_sufficiency_assessment_cache,
)
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.research_termination_reason import (
    EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus

from tests.application.research_quality.test_hybrid_sufficiency_evaluator import (
    RecordingSemanticAssessor,
    _evidence,
    _semantic,
)
from tests.application.research_quality.test_targeted_research_loop import (
    SequentialSufficiencyEvaluator,
    _build_service,
    _context,
    _insufficient_result,
)

SERBIA_IN_COUNT = 12


def _serbia_like_design() -> ResearchDesign:
    rqs = tuple(
        ResearchQuestion(
            id=f"RQ{index}",
            question=f"Question {index}?",
            objective_refs=(),
        )
        for index in range(1, 7)
    )
    needs = []
    mapping = {
        1: 1,
        2: 1,
        3: 2,
        4: 2,
        5: 3,
        6: 3,
        7: 4,
        8: 4,
        9: 4,
        10: 5,
        11: 6,
        12: 6,
    }
    for index in range(1, 13):
        needs.append(
            InformationNeed(
                id=f"IN{index}",
                research_question_id=f"RQ{mapping[index]}",
                description=f"Serbia microgreens need IN{index}",
            )
        )
    return ResearchDesign(
        id="serbia-design",
        research_questions=rqs,
        information_needs=tuple(needs),
    )


def _profile_b_budget() -> ExecutionBudget:
    return ExecutionBudget(
        llm_max_calls_per_run=120,
        evidence_max_llm_calls=36,
        evidence_remediation_reserved_llm_calls=6,
        sufficiency_max_llm_calls=36,
        analysis_max_llm_calls=10,
        report_max_llm_calls=12,
        review_max_llm_calls=3,
    )


class ProfileBControlLoopRegressionTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sufficiency_assessment_cache()
        _current_budget.set(None)

    def test_initial_evidence_cannot_starve_targeted_extract(self) -> None:
        budget = _profile_b_budget()
        for _ in range(budget.evidence_initial_allowance):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence")
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(budget.evidence_remediation_calls, 1)
        self.assertEqual(budget.stage_calls("evidence"), 31)

    def test_unchanged_ins_do_not_repeat_sufficiency_calls(self) -> None:
        cache = SufficiencyAssessmentCache()
        _current_cache.set(cache)
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _serbia_like_design()
        evidence = tuple(
            _evidence(
                evidence_id=f"ev-{index}",
                information_need_refs=(f"IN{index}",),
                research_question_refs=(design.information_needs[index - 1].research_question_id,),
            )
            for index in range(1, 12)
        )
        first = evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 11)
        self.assertFalse(first.ready_for_analysis)
        second = evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 11)
        self.assertEqual(cache.reused_assessments, 11)
        self.assertFalse(second.ready_for_analysis)

        changed = evidence + (
            _evidence(
                evidence_id="ev-2b",
                information_need_refs=("IN2",),
                research_question_refs=("RQ1",),
            ),
        )
        third = evaluator.evaluate(design=design, evidence=changed)
        self.assertEqual(len(semantic.calls), 12)
        self.assertIn("IN2", cache.reassessed_need_ids)
        self.assertFalse(third.ready_for_analysis)

        fourth = evaluator.evaluate(design=design, evidence=changed)
        self.assertEqual(len(semantic.calls), 12)
        self.assertFalse(fourth.ready_for_analysis)

    def test_targeted_zero_yield_does_not_burn_duplicate_sufficiency_calls(self) -> None:
        cache = SufficiencyAssessmentCache()
        _current_cache.set(cache)
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _serbia_like_design()
        evidence = tuple(
            _evidence(
                evidence_id=f"ev-{index}",
                information_need_refs=(f"IN{index}",),
                research_question_refs=(design.information_needs[index - 1].research_question_id,),
            )
            for index in range(1, 12)
        )
        evaluator.evaluate(design=design, evidence=evidence)
        evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 11)

    def test_remediation_allowance_exhausted_terminates_loop_without_crash(self) -> None:
        budget = _profile_b_budget()
        for _ in range(30):
            budget.record_llm_call("evidence")
        for _ in range(6):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        token = _current_budget.set(budget)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=0,
            sources_acquired=0,
            evidence_extracted=0,
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([_insufficient_result()]),
            runner=runner,
        )
        context = _context()
        try:
            result = service.assess_and_apply(context)
        finally:
            _current_budget.reset(token)
        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(
            result.termination_reason,
            EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
        )
        runner.run.assert_not_called()

    def test_readiness_stays_fail_closed_unless_all_ins_sufficient(self) -> None:
        _current_cache.set(SufficiencyAssessmentCache())
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _serbia_like_design()
        evidence = tuple(
            _evidence(
                evidence_id=f"ev-{index}",
                information_need_refs=(f"IN{index}",),
                research_question_refs=(design.information_needs[index - 1].research_question_id,),
            )
            for index in range(1, 13)
        )
        result = evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(result.blocking_information_need_ids), SERBIA_IN_COUNT)
        self.assertFalse(result.ready_for_analysis)
