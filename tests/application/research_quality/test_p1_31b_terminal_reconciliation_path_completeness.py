"""PROPERTY AJ: every terminal readiness path uses PROPERTY AI authority."""

from __future__ import annotations

from dataclasses import replace
import unittest

from application.execution.exceptions import BudgetExhaustedError
from application.research_quality.research_loop_state import ResearchLoopState
from application.research_quality.research_readiness_service import ResearchReadinessService
from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from tests.application.research_quality.test_p1_30_2_terminal_information_need_state_truthfulness import (
    _assessment,
    _evidence,
    _result,
)
from tests.application.research_quality.test_targeted_research_loop import (
    SequentialSufficiencyEvaluator,
    _context,
    _missing_result,
    _ready_result,
    _seed_evidence,
)


CONTROLLED_LOOP_TERMINATIONS = (
    "no_actionable_gaps",
    "no_material_improvement",
    "max_research_rounds",
    "evidence_remediation_budget_exhausted",
    "downstream_reserve_exhausted",
)


class CandidateLoop:
    def __init__(self, candidate, reason: str) -> None:
        self.candidate = replace(candidate, termination_reason=reason)
        self.reason = reason
        self.calls = 0

    def run_bounded_loop(self, context, *, initial_result):
        del context, initial_result
        self.calls += 1
        return self.candidate, ResearchLoopState(termination_reason=self.reason)


class BudgetStoppingLoop:
    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    def run_bounded_loop(self, context, *, initial_result):
        del context, initial_result
        self.calls += 1
        raise BudgetExhaustedError(self.reason, stage="sufficiency")


class BudgetStoppingEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, *, design, evidence):
        del design, evidence
        self.calls += 1
        raise BudgetExhaustedError("sufficiency_max_llm_calls", stage="sufficiency")


class CountingReadinessService(ResearchReadinessService):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.finalization_calls = 0

    def _finalize_terminal_readiness(self, context, candidate):
        self.finalization_calls += 1
        return super()._finalize_terminal_readiness(context, candidate)


def _service(*, evaluator, evidence_repository, loop_service=None):
    return CountingReadinessService(
        evaluator=evaluator,
        evidence_repository=evidence_repository,
        loop_service=loop_service,
    )


class TerminalReconciliationPathCompletenessTests(unittest.TestCase):
    def test_initial_ready_is_reconciled_before_authority_and_persistence(self) -> None:
        context = _context()
        evidence = InMemoryEvidenceRepository()
        _seed_evidence(
            evidence,
            context,
            need_id="in-1",
            research_question_id="rq-1",
            evidence_id="ev-ready",
        )
        evaluator = SequentialSufficiencyEvaluator([_ready_result()])
        service = _service(evaluator=evaluator, evidence_repository=evidence)

        result = service.assess_and_apply(context)
        need = result.research_question_assessments[0].information_need_assessments[0]

        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(result.termination_reason, "ready")
        self.assertTrue(need.assessment_current)
        self.assertEqual(need.terminal_evidence_count, 1)
        self.assertEqual(
            need.assessment_evidence_fingerprint,
            need.terminal_evidence_fingerprint,
        )
        self.assertEqual(service.finalization_calls, 1)
        persisted = context.read_shared("research_readiness")
        persisted_need = persisted["research_question_assessments"][0][
            "information_need_assessments"
        ][0]
        self.assertEqual(persisted_need["terminal_evidence_count"], 1)

    def test_all_controlled_loop_results_reach_one_common_boundary(self) -> None:
        for reason in CONTROLLED_LOOP_TERMINATIONS:
            with self.subTest(reason=reason):
                context = _context()
                evidence = InMemoryEvidenceRepository()
                _seed_evidence(
                    evidence,
                    context,
                    need_id="in-1",
                    research_question_id="rq-1",
                    evidence_id=f"ev-{reason}",
                )
                evaluator = SequentialSufficiencyEvaluator([_missing_result()])
                loop = CandidateLoop(_missing_result(), reason)
                service = _service(
                    evaluator=evaluator,
                    evidence_repository=evidence,
                    loop_service=loop,
                )

                result = service.assess_and_apply(context)
                need = result.research_question_assessments[0].information_need_assessments[0]

                self.assertFalse(result.ready_for_analysis)
                expected_reason = (
                    "sufficiency_budget_exhausted"
                    if reason == "sufficiency_max_llm_calls"
                    else reason
                )
                self.assertEqual(result.termination_reason, expected_reason)
                self.assertEqual(need.terminal_evidence_count, 1)
                self.assertTrue(need.assessment_current)
                self.assertEqual(service.finalization_calls, 1)
                self.assertEqual(loop.calls, 1)

    def test_p1_31_evidence_precheck_exit_reconciles_without_model_exception(self) -> None:
        context = _context()
        evidence = InMemoryEvidenceRepository()
        _seed_evidence(
            evidence,
            context,
            need_id="in-1",
            research_question_id="rq-1",
            evidence_id="ev-p1-31",
        )
        evaluator = SequentialSufficiencyEvaluator([_missing_result()])
        loop = CandidateLoop(_missing_result(), "downstream_reserve_exhausted")
        service = _service(
            evaluator=evaluator,
            evidence_repository=evidence,
            loop_service=loop,
        )

        result = service.assess_and_apply(context)
        need = result.research_question_assessments[0].information_need_assessments[0]

        self.assertEqual(evaluator.calls, 1)
        self.assertEqual(loop.calls, 1)
        self.assertEqual(result.termination_reason, "downstream_reserve_exhausted")
        self.assertEqual(need.terminal_evidence_count, 1)
        self.assertTrue(need.assessment_current)
        self.assertEqual(service.finalization_calls, 1)

    def test_mid_sufficiency_and_outer_budget_catches_are_terminally_reconciled(self) -> None:
        for reason in ("downstream_reserve_exhausted", "sufficiency_max_llm_calls"):
            with self.subTest(reason=reason):
                context = _context()
                evidence = InMemoryEvidenceRepository()
                _seed_evidence(
                    evidence,
                    context,
                    need_id="in-1",
                    research_question_id="rq-1",
                    evidence_id=f"ev-catch-{reason}",
                )
                evaluator = SequentialSufficiencyEvaluator([_missing_result()])
                loop = BudgetStoppingLoop(reason)
                service = _service(
                    evaluator=evaluator,
                    evidence_repository=evidence,
                    loop_service=loop,
                )

                result = service.assess_and_apply(context)
                need = result.research_question_assessments[0].information_need_assessments[0]

                expected_reason = (
                    "sufficiency_budget_exhausted"
                    if reason == "sufficiency_max_llm_calls"
                    else reason
                )
                self.assertEqual(result.termination_reason, expected_reason)
                self.assertEqual(need.terminal_evidence_count, 1)
                self.assertEqual(service.finalization_calls, 1)

    def test_initial_sufficiency_budget_fallback_reconciles_zero_evidence(self) -> None:
        context = _context()
        evaluator = BudgetStoppingEvaluator()
        service = _service(
            evaluator=evaluator,
            evidence_repository=InMemoryEvidenceRepository(),
        )

        result = service.assess_and_apply(context)
        need = result.research_question_assessments[0].information_need_assessments[0]

        self.assertEqual(result.termination_reason, "sufficiency_budget_exhausted")
        self.assertEqual(need.status, SufficiencyStatus.MISSING)
        self.assertEqual(need.terminal_evidence_count, 0)
        self.assertTrue(need.assessment_current)
        self.assertEqual(evaluator.calls, 1)
        self.assertEqual(service.finalization_calls, 1)

    def test_post_assessment_mutation_marks_sufficient_stale_and_blocks_ready(self) -> None:
        context = _context()
        evidence = InMemoryEvidenceRepository()
        _seed_evidence(
            evidence,
            context,
            need_id="in-1",
            research_question_id="rq-1",
            evidence_id="ev-assessed",
        )

        class MutatingReadyEvaluator(SequentialSufficiencyEvaluator):
            def evaluate(inner_self, *, design, evidence: tuple):
                result = super(MutatingReadyEvaluator, inner_self).evaluate(
                    design=design,
                    evidence=evidence,
                )
                _seed_evidence(
                    repository,
                    context,
                    need_id="in-1",
                    research_question_id="rq-1",
                    evidence_id="ev-terminal",
                )
                return result

        repository = evidence
        evaluator = MutatingReadyEvaluator([_ready_result()])
        service = _service(evaluator=evaluator, evidence_repository=repository)

        result = service.assess_and_apply(context)
        need = result.research_question_assessments[0].information_need_assessments[0]

        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(need.assessment_current)
        self.assertEqual(need.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(need.terminal_evidence_count, 2)
        self.assertIn(GapType.STALE_EVIDENCE, need.gap_types)
        self.assertNotEqual(
            need.assessment_evidence_fingerprint,
            need.terminal_evidence_fingerprint,
        )
        self.assertEqual(context.read_shared("research_readiness")["ready_for_analysis"], False)

    def test_already_reconciled_partial_cache_is_idempotent_at_common_boundary(self) -> None:
        context = _context()
        evidence = InMemoryEvidenceRepository()
        _seed_evidence(
            evidence,
            context,
            need_id="in-1",
            research_question_id="rq-1",
            evidence_id="ev-current",
        )
        current = _assessment("in-1", SufficiencyStatus.INSUFFICIENT, 1)
        candidate = _result(current)
        evaluator = SequentialSufficiencyEvaluator([candidate])
        loop = CandidateLoop(candidate, "downstream_reserve_exhausted")
        service = _service(
            evaluator=evaluator,
            evidence_repository=evidence,
            loop_service=loop,
        )

        result = service.assess_and_apply(context)
        first_payload = result.to_dict()
        second = service._finalize_terminal_readiness(context, result)

        self.assertEqual(second.to_dict(), first_payload)
        self.assertEqual(result.termination_reason, "downstream_reserve_exhausted")

    def test_raw_payload_preserves_property_ai_metadata(self) -> None:
        context = _context()
        evidence = InMemoryEvidenceRepository()
        _seed_evidence(
            evidence,
            context,
            need_id="in-1",
            research_question_id="rq-1",
            evidence_id="ev-api",
        )
        service = _service(
            evaluator=SequentialSufficiencyEvaluator([_missing_result()]),
            evidence_repository=evidence,
            loop_service=CandidateLoop(_missing_result(), "no_actionable_gaps"),
        )
        result = service.assess_and_apply(context)
        payload = context.read_shared("research_readiness")
        need = payload["research_question_assessments"][0][
            "information_need_assessments"
        ][0]

        self.assertEqual(need["terminal_evidence_count"], 1)
        self.assertTrue(need["assessment_current"])
        self.assertTrue(need["assessment_evidence_fingerprint"])
        self.assertEqual(
            need["assessment_evidence_fingerprint"],
            need["terminal_evidence_fingerprint"],
        )
        result_need = result.to_dict()["research_question_assessments"][0][
            "information_need_assessments"
        ][0]
        self.assertEqual(need, result_need)


if __name__ == "__main__":
    unittest.main()
