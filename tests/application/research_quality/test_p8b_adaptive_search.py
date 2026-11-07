import unittest
from application.research_quality.deterministic_targeted_research_runner import DeterministicTargetedResearchRunner
from application.research_quality.targeted_search_query_builder import TargetedSearchQueryBuilder
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from tests.application.research_quality.test_targeted_research_loop import (
    RecordingProgressCheckpoint, SequentialSufficiencyEvaluator, _context,
    _missing_result, _build_service, _result_for_needs, _need_assessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY

from application.research_quality.adaptive_search_strategy import (
    DIRECT, PROXY_INDICATORS, SEMANTIC_EXPANSION, SOURCE_DIVERSIFICATION,
    choose_strategy,
)
from application.research_quality.research_loop_state import (
    ResearchLoopIterationRecord, ResearchLoopState,
)
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.research_quality.gap_type import GapType


class P8BAdaptiveSearchTests(unittest.TestCase):
    def _request(self, strategy="direct"):
        return TargetedResearchRequest(
            workflow_run_id="w", research_design_id="d", research_question_id="q",
            information_need_id="n", gap_types=(GapType.NO_EVIDENCE,),
            missing_aspects=("missing period",), strategy_id=strategy,
        )

    def test_t1_direct_then_semantic_expansion(self):
        first, remaining = choose_strategy(
            missing_dimensions=("missing period",), attempted=(), directives=(),
        )
        second, _ = choose_strategy(
            missing_dimensions=("missing period",), attempted=(first,), directives=(),
        )
        self.assertEqual(first, DIRECT)
        self.assertEqual(second, SEMANTIC_EXPANSION)
        self.assertNotIn(first, remaining)

    def test_t2_source_diversification_for_source_gap(self):
        selected, _ = choose_strategy(
            missing_dimensions=("independent source",),
            attempted=(DIRECT,), directives=(),
        )
        self.assertEqual(selected, SOURCE_DIVERSIFICATION)

    def test_t3_proxy_is_explicit_and_not_direct(self):
        selected, _ = choose_strategy(
            missing_dimensions=("proxy indicator permitted",),
            attempted=(DIRECT, SEMANTIC_EXPANSION), directives=(),
        )
        self.assertEqual(selected, PROXY_INDICATORS)
        self.assertNotEqual(selected, DIRECT)

    def test_t4_budget_stop_is_not_strategy_exhaustion(self):
        state = ResearchLoopState(termination_reason="budget_exhausted")
        self.assertEqual(state.termination_reason, "budget_exhausted")
        selected, _ = choose_strategy(
            missing_dimensions=("period",), attempted=(DIRECT,), directives=(),
        )
        self.assertEqual(selected, SEMANTIC_EXPANSION)

    def test_t5_strategy_history_round_trips_without_inventing_attempts(self):
        state = ResearchLoopState(history=[ResearchLoopIterationRecord(
            attempt=1, round_number=1, blocking_need_ids_before=("n",),
            targeted_need_ids=("n",), queries_generated=1, new_sources_count=1,
            new_evidence_count=0, readiness_after={}, improved=False,
            strategy_id=SEMANTIC_EXPANSION, attempt_outcome="no_progress",
            remaining_strategy_ids=(SOURCE_DIVERSIFICATION,),
        )])
        restored = ResearchLoopState.from_dict(state.to_dict())
        record = restored.history[0]
        self.assertEqual(record.strategy_id, SEMANTIC_EXPANSION)
        self.assertEqual(record.attempt_outcome, "no_progress")
        self.assertEqual(record.remaining_strategy_ids, (SOURCE_DIVERSIFICATION,))
        self.assertEqual(self._request().strategy_id, DIRECT)

    def test_adaptive_progression_uses_real_loop_runner_and_checkpoint(self):
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        inner = DeterministicTargetedResearchRunner(
            source_repository=source_repo, evidence_repository=evidence_repo,
        )
        queries = []
        requests = []

        class RecordingRunner:
            def run(self, context, request):
                requests.append(request)
                built = TargetedSearchQueryBuilder().build_queries(
                    design=context.workflow_template.research_design_snapshot,
                    request=request, max_queries=1, max_results=3,
                    brief=context.project.research_brief,
                )
                queries.append(built[0].query_text)
                # The first direct attempt is deliberately insufficient; the
                # second semantic attempt supplies qualifying Evidence.
                if request.strategy_id == SEMANTIC_EXPANSION:
                    return inner.run(context, request)
                from application.research_quality.targeted_research_runner import TargetedResearchIterationResult
                return TargetedResearchIterationResult((), (), 1, 0, 0)

        checkpoint = RecordingProgressCheckpoint()
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _missing_result(),
                                            _result_for_needs(_need_assessment(status=SufficiencyStatus.SUFFICIENT), ready=True)]),
            source_repository=source_repo, evidence_repository=evidence_repo,
            runner=RecordingRunner(), max_rounds=2, max_attempts_per_gap=3,
            adaptive_strategy_mode=True,
        )
        context = _context()
        context.services[CHECKPOINT_SERVICE_KEY] = checkpoint
        result = service.assess_and_apply(context)
        self.assertTrue(result.ready_for_analysis, (result.to_dict(), [item.strategy_id for item in requests], queries))
        self.assertEqual([item.strategy_id for item in requests],
                         [DIRECT, SEMANTIC_EXPANSION])
        self.assertNotEqual(queries[0], queries[1])
        self.assertGreaterEqual(len(checkpoint.shared_states), 2)
        restored = ResearchLoopState.from_dict(
            checkpoint.shared_states[-1]["research_loop_state"],
        )
        self.assertEqual([item.strategy_id for item in restored.history],
                         [DIRECT, SEMANTIC_EXPANSION])


if __name__ == "__main__":
    unittest.main()
