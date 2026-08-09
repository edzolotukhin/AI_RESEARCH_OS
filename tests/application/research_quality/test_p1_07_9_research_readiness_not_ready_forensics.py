"""P1-07.9 forensic snapshots of current Research Readiness not-ready semantics."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.research_termination_reason import SUFFICIENCY_BUDGET_EXHAUSTED
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus

from application.executors.analysis_executor import AnalysisExecutor
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    _current_stage,
    ensure_run_budget,
)
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.readiness_aggregation import (
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)

from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)

from tests.application.research_quality.test_hybrid_sufficiency_evaluator import (
    RecordingSemanticAssessor,
    _design,
    _evidence,
    _semantic,
)
from tests.application.research_quality.test_research_readiness_gate import (
    StubEvidenceRepository,
    _desk_research_context,
    _resolver,
    _run_desk_research,
)
from tests.application.research_quality.test_targeted_research_loop import (
    RecordingTargetedRunner,
    _context as loop_context,
    _design_three_needs,
    _missing_result,
    _ready_result,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _need_assessment(
    *,
    need_id: str,
    rq_id: str,
    status: SufficiencyStatus,
    evidence_count: int = 0,
    missing_aspects: tuple[str, ...] = (),
    gap_types: tuple[GapType, ...] = (),
) -> InformationNeedAssessment:
    if status == SufficiencyStatus.MISSING:
        gap_types = gap_types or (GapType.NO_EVIDENCE,)
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id=rq_id,
        status=status,
        evidence_count=evidence_count,
        independent_source_count=1 if evidence_count else 0,
        missing_aspects=missing_aspects,
        gap_types=gap_types,
        search_directives=missing_aspects,
        reason=f"{need_id} {status.value}",
    )


class HybridReadinessSnapshotTests(unittest.TestCase):
    def test_case_a_all_needs_sufficient_is_ready(self) -> None:
        evaluator = HybridResearchSufficiencyEvaluator(
            semantic_assessor=RecordingSemanticAssessor(
                default=_semantic(status=SufficiencyStatus.SUFFICIENT),
            ),
        )
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1", "in-2")),
            evidence=(
                _evidence(evidence_id="e1", information_need_refs=("in-1",)),
                _evidence(evidence_id="e2", information_need_refs=("in-2",)),
            ),
        )
        self.assertTrue(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.blocking_information_need_ids, ())

    def test_case_b_one_insufficient_need_is_not_ready(self) -> None:
        evaluator = HybridResearchSufficiencyEvaluator(
            semantic_assessor=RecordingSemanticAssessor(
                by_need={
                    "in-1": _semantic(status=SufficiencyStatus.SUFFICIENT),
                    "in-2": _semantic(
                        status=SufficiencyStatus.INSUFFICIENT,
                        missing_aspects=("__legacy_need__",),
                        gap_types=(GapType.INSUFFICIENT_DEPTH,),
                        search_directives=("__legacy_need__",),
                    ),
                },
            ),
        )
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1", "in-2")),
            evidence=(
                _evidence(evidence_id="e1", information_need_refs=("in-1",)),
                _evidence(evidence_id="e2", information_need_refs=("in-2",)),
            ),
        )
        self.assertFalse(result.ready_for_analysis)
        self.assertTrue(result.targeted_research_required)
        self.assertEqual(result.blocking_information_need_ids, ("in-2",))

    def test_case_c_quantity_on_one_need_does_not_imply_readiness(self) -> None:
        evaluator = HybridResearchSufficiencyEvaluator(
            semantic_assessor=RecordingSemanticAssessor(
                default=_semantic(status=SufficiencyStatus.SUFFICIENT),
            ),
        )
        pile = tuple(
            _evidence(
                evidence_id=f"e{index}",
                information_need_refs=("in-1",),
            )
            for index in range(16)
        )
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1", "in-2", "in-3")),
            evidence=pile,
        )
        self.assertEqual(result.research_question_assessments[0].information_need_assessments[0].evidence_count, 16)
        self.assertEqual(result.research_question_assessments[0].information_need_assessments[1].status, SufficiencyStatus.MISSING)
        self.assertFalse(result.ready_for_analysis)
        self.assertIn("in-2", result.blocking_information_need_ids)
        self.assertIn("in-3", result.blocking_information_need_ids)

    def test_case_d_zero_evidence_is_missing_without_semantic_call(self) -> None:
        assessor = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=assessor)
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(),
        )
        self.assertEqual(assessor.calls, [])
        need = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(need.status, SufficiencyStatus.MISSING)
        self.assertEqual(need.gap_types, (GapType.NO_EVIDENCE,))
        self.assertFalse(result.ready_for_analysis)

    def test_case_e_missing_aspects_keep_need_insufficient(self) -> None:
        evaluator = HybridResearchSufficiencyEvaluator(
            semantic_assessor=RecordingSemanticAssessor(
                default=_semantic(
                    status=SufficiencyStatus.INSUFFICIENT,
                    missing_aspects=("__legacy_need__",),
                    gap_types=(GapType.INSUFFICIENT_DEPTH,),
                    search_directives=("__legacy_need__",),
                ),
            ),
        )
        result = evaluator.evaluate(
            design=_design(need_ids=("in-1",)),
            evidence=(_evidence(evidence_id="e1"),),
        )
        need = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(need.status, SufficiencyStatus.INSUFFICIENT)
        self.assertEqual(need.missing_aspects, ("__legacy_need__",))
        self.assertTrue(result.targeted_research_required)
        self.assertFalse(result.ready_for_analysis)


class LoopAndGateSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(_current_budget.set, None)
        self.addCleanup(_current_stage.set, None)
        _current_budget.set(None)
        _current_stage.set(None)

    def test_case_f_gaps_with_budget_attempt_targeted_round(self) -> None:
        context = loop_context(design=_design_three_needs())
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = Mock()
        evaluator.evaluate.side_effect = [_missing_result(), _ready_result()]
        service = ResearchReadinessService(
            evaluator=evaluator,
            evidence_repository=evidence_repo,
            loop_service=ResearchLoopService(
                runner=runner,
                bounds=TargetedResearchBounds(max_gap_rounds_per_run=1, max_attempts_per_gap=1),
                evaluator=evaluator,
                evidence_repository=evidence_repo,
                source_repository=source_repo,
            ),
        )
        result = service.assess_and_apply(context)
        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(result.termination_reason, "ready")

    def test_case_g_max_rounds_terminates_not_ready(self) -> None:
        context = loop_context(design=_design_three_needs())
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = Mock()
        evaluator.evaluate.return_value = _missing_result()
        service = ResearchReadinessService(
            evaluator=evaluator,
            evidence_repository=evidence_repo,
            loop_service=ResearchLoopService(
                runner=runner,
                bounds=TargetedResearchBounds(max_gap_rounds_per_run=1, max_attempts_per_gap=1),
                evaluator=evaluator,
                evidence_repository=evidence_repo,
                source_repository=source_repo,
            ),
        )
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)
        self.assertIn(
            result.termination_reason,
            {"no_material_improvement", "max_research_rounds"},
        )

    def test_case_h_sufficiency_budget_exhaustion_is_fail_closed_not_ready(self) -> None:
        budget = ExecutionBudget(sufficiency_max_llm_calls=2)
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=("src-new",),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=1,
            evidence_extracted=0,
        )

        class _CountingEval:
            def __init__(self) -> None:
                self.calls = 0

            def evaluate(self, *, design, evidence):
                self.calls += 1
                budget.assert_can_call("sufficiency")
                budget.record_llm_call("sufficiency")
                return _missing_result()

        evaluator = _CountingEval()
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        service = ResearchReadinessService(
            evaluator=evaluator,
            evidence_repository=evidence_repo,
            loop_service=ResearchLoopService(
                runner=runner,
                bounds=TargetedResearchBounds(max_gap_rounds_per_run=1, max_attempts_per_gap=1),
                evaluator=evaluator,
                evidence_repository=evidence_repo,
                source_repository=source_repo,
            ),
        )
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.termination_reason, SUFFICIENCY_BUDGET_EXHAUSTED)
        payload = context.read_shared("research_readiness")
        self.assertEqual(payload["research_outcome"], ResearchOutcome.INSUFFICIENT_RESEARCH.value)
        self.assertEqual(payload["research_loop_count"], 1)
        self.assertEqual(evaluator.calls, 2)
        runner.run.assert_called_once()

    def test_not_ready_skips_analysis_report_review(self) -> None:
        evaluator = Mock()
        evaluator.evaluate.return_value = _missing_result()
        context, analysis = _desk_research_context(evaluator=evaluator)
        readiness = ResearchReadinessExecutor(
            research_readiness_service=ResearchReadinessService(
                evaluator=evaluator,
                evidence_repository=StubEvidenceRepository(),
            ),
        )
        context = _run_desk_research(
            context,
            _resolver(
                readiness=readiness,
                analysis_executor=AnalysisExecutor(analysis_service=analysis),
            ),
        )
        statuses = {task.definition_id: task.status for task in context.workflow_run.tasks}
        self.assertEqual(statuses["task-assess-research-readiness"], TaskStatus.COMPLETED)
        self.assertEqual(statuses["task-analyze"], TaskStatus.SKIPPED)
        self.assertEqual(statuses["task-write-report"], TaskStatus.SKIPPED)
        self.assertEqual(statuses["task-review-report"], TaskStatus.SKIPPED)
        self.assertEqual(analysis.calls, 0)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)


class ObservabilityAndAllReadyAggregationTests(unittest.TestCase):
    def test_aggregation_requires_every_information_need(self) -> None:
        ready_need = _need_assessment(
            need_id="IN9",
            rq_id="RQ5",
            status=SufficiencyStatus.SUFFICIENT,
            evidence_count=7,
        )
        missing_need = _need_assessment(
            need_id="IN10",
            rq_id="RQ5",
            status=SufficiencyStatus.MISSING,
        )
        rq = build_research_readiness_assessment(
            research_question_id="RQ5",
            need_assessments=(ready_need, missing_need),
        )
        result = build_research_readiness_result((rq,))
        self.assertFalse(rq.ready_for_analysis)
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(result.blocking_information_need_ids, ("IN10",))

    def test_api_results_surface_readiness_not_usage_summary(self) -> None:
        results_router = (
            REPO_ROOT / "api" / "routers" / "workflow_runs.py"
        ).read_text(encoding="utf-8")
        self.assertIn("extract_research_readiness", results_router)
        self.assertIn("research_loop_count", results_router)
        self.assertNotIn("run_usage_summary", results_router)
        codec = (
            REPO_ROOT / "application" / "research_quality" / "readiness_result_codec.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(codec)
        names = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertIn("get", names)


if __name__ == "__main__":
    unittest.main()
