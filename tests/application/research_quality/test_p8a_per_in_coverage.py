import unittest
from types import SimpleNamespace

from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.research_loop_state import ResearchLoopIterationRecord, ResearchLoopState
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from tests.application.research_quality.test_targeted_research_loop import (
    RecordingProgressCheckpoint,
    StaticSufficiencyEvaluator,
    _build_service,
    _context as loop_context,
    _missing_result,
)


def _context(payload=None):
    return SimpleNamespace(read_shared=lambda _key: payload)


def _result(*needs):
    rq = ResearchReadinessAssessment(
        research_question_id="rq-1",
        information_need_assessments=tuple(needs),
        ready_for_analysis=all(item.status == SufficiencyStatus.SUFFICIENT for item in needs),
        blocking_information_need_ids=tuple(
            item.information_need_id for item in needs
            if item.status != SufficiencyStatus.SUFFICIENT
        ),
    )
    return ResearchReadinessResult(
        research_question_assessments=(rq,),
        ready_for_analysis=rq.ready_for_analysis,
        blocking_research_question_ids=(() if rq.ready_for_analysis else ("rq-1",)),
        blocking_information_need_ids=rq.blocking_information_need_ids,
        targeted_research_required=not rq.ready_for_analysis,
    )


class P8APerInformationNeedCoverageTests(unittest.TestCase):
    def test_independent_evidence_and_analysis_eligibility(self):
        result = _result(
            InformationNeedAssessment("in-a", "rq-1", SufficiencyStatus.SUFFICIENT, evidence_count=1),
            InformationNeedAssessment("in-b", "rq-1", SufficiencyStatus.MISSING),
        )
        enriched = ResearchReadinessService._attach_per_information_need_coverage(
            _context(), result, ResearchLoopState(),
        )
        values = {
            item.information_need_id: item
            for item in enriched.research_question_assessments[0].information_need_assessments
        }
        self.assertTrue(values["in-a"].analysis_eligible)
        self.assertEqual(values["in-a"].evidence_status, "sufficient")
        self.assertFalse(values["in-b"].analysis_eligible)
        self.assertEqual(values["in-b"].evidence_status, "insufficient")
        self.assertEqual(values["in-b"].search_status, "unknown")

    def test_budget_stop_is_not_strategy_exhaustion(self):
        result = _result(InformationNeedAssessment("in-a", "rq-1", SufficiencyStatus.MISSING))
        state = ResearchLoopState(
            termination_reason="evidence_remediation_budget_exhausted",
            history=[ResearchLoopIterationRecord(
                attempt=1, round_number=1, blocking_need_ids_before=("in-a",),
                targeted_need_ids=("in-a",), queries_generated=1,
                new_sources_count=0, new_evidence_count=0,
                readiness_after={}, improved=False,
            )],
        )
        enriched = ResearchReadinessService._attach_per_information_need_coverage(
            _context(), result, state,
        )
        assessment = enriched.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.search_status, "budget_exhausted")
        self.assertNotEqual(assessment.search_status, "strategies_exhausted")
        self.assertEqual(assessment.attempted_strategies, ())
        self.assertEqual(assessment.stop_reason, "evidence_remediation_budget_exhausted")

    def test_assessment_round_trips_with_legacy_defaults(self):
        original = InformationNeedAssessment(
            "in-a", "rq-1", SufficiencyStatus.INSUFFICIENT,
            missing_dimensions=("period:2025",), search_status="unknown",
            remaining_strategies=("unknown",), stop_reason="blocked_gaps",
        )
        restored = InformationNeedAssessment.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        legacy = InformationNeedAssessment.from_dict({
            "information_need_id": "in-a",
            "research_question_id": "rq-1",
            "status": "missing",
        })
        self.assertEqual(legacy.search_status, "unknown")
        self.assertEqual(legacy.evidence_status, "not_evaluated")

    def test_assess_and_apply_checkpoint_reload_preserves_per_in_coverage(self):
        service = _build_service(
            StaticSufficiencyEvaluator(_missing_result()),
            max_rounds=0,
        )
        context = loop_context()
        checkpoint = RecordingProgressCheckpoint()
        context.services[CHECKPOINT_SERVICE_KEY] = checkpoint

        service.assess_and_apply(context)
        checkpoint.on_task_progress(context)

        persisted = context.read_shared("research_readiness")
        self.assertIsInstance(persisted, dict)
        checkpoint_payload = checkpoint.shared_states[-1]["research_readiness"]
        restored = ResearchReadinessResult.from_dict(checkpoint_payload)
        assessment = restored.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.evidence_status, "insufficient")
        self.assertEqual(assessment.search_status, "unknown")
        self.assertEqual(assessment.stop_reason, restored.termination_reason)
        self.assertEqual(assessment.attempted_strategies, ())
        self.assertEqual(assessment.remaining_strategies, ("unknown",))
        self.assertFalse(assessment.analysis_eligible)


if __name__ == "__main__":
    unittest.main()
