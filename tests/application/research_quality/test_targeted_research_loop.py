"""Tests for P1-05 bounded targeted research loop."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Sequence
from unittest.mock import Mock

from application.contracts.base_executor import BaseExecutor
from application.executors.analysis_executor import AnalysisExecutor
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.execution.execution_budget_retry import consume_llm_call_retry_flag
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.research_quality.deterministic_targeted_research_runner import (
    DeterministicTargetedResearchRunner,
)
from application.research_quality.gap_selection import select_actionable_gaps
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_loop_state import (
    SHARED_LOOP_STATE_KEY,
    ResearchLoopIterationRecord,
    ResearchLoopState,
    serialize_readiness,
)
from application.research_quality.research_loop_checkpoint import checkpoint_loop_progress
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.status_rank import readiness_improved
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from application.research_quality.targeted_search_query_builder import (
    TargetedSearchQueryBuilder,
)
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate

from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class PassThroughExecutor(BaseExecutor):
    def run(self, context: WorkflowContext) -> WorkflowContext:
        return context


class RecordingAnalysisService:
    def __init__(self) -> None:
        self.calls = 0
        self.llm_calls = 0

    def analyze_for_context(self, context: WorkflowContext):
        self.calls += 1
        from application.analysis.analysis_service import AnalysisSummary

        return AnalysisSummary(
            finding_ids=(),
            insight_ids=(),
            evidence_batches_processed=0,
            finding_candidates_rejected=0,
            insight_candidates_rejected=0,
            batch_failures=0,
        )


class SequentialSufficiencyEvaluator:
    def __init__(self, results: Sequence[ResearchReadinessResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        self.calls += 1
        if not self._results:
            return _ready_result()
        if len(self._results) == 1:
            return self._results[0]
        return self._results.pop(0)


class RecordingTargetedRunner:
    def __init__(
        self,
        *,
        source_repository: InMemorySourceRepository,
        evidence_repository: InMemoryEvidenceRepository,
    ) -> None:
        self.calls = 0
        self.targeted_need_ids: list[str] = []
        self._inner = DeterministicTargetedResearchRunner(
            source_repository=source_repository,
            evidence_repository=evidence_repository,
        )

    def run(self, context: WorkflowContext, request: TargetedResearchRequest):
        self.calls += 1
        self.targeted_need_ids.append(request.information_need_id)
        return self._inner.run(context, request)


def _design_two_needs() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="What is the market outlook?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id="rq-2",
                question="Who are the competitors?",
                objective_refs=(),
            ),
        ),
        information_needs=(
            InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Market size data",
            ),
            InformationNeed(
                id="in-2",
                research_question_id="rq-2",
                description="Competitor list",
            ),
        ),
    )


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="What is the market outlook?",
                objective_refs=(),
            ),
        ),
        information_needs=(
            InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Market size data",
            ),
        ),
    )


def _need_assessment(
    *,
    need_id: str = "in-1",
    rq_id: str = "rq-1",
    status: SufficiencyStatus,
    search_directives: tuple[str, ...] = ("market size 2024",),
) -> InformationNeedAssessment:
    gap_types: tuple[GapType, ...] = ()
    evidence_count = 1
    if status == SufficiencyStatus.MISSING:
        gap_types = (GapType.NO_EVIDENCE,)
        evidence_count = 0
    elif status == SufficiencyStatus.BLOCKED:
        gap_types = (GapType.UNRESOLVABLE,)
    elif status in {SufficiencyStatus.PARTIAL, SufficiencyStatus.INSUFFICIENT}:
        gap_types = (GapType.INSUFFICIENT_DEPTH,)
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id=rq_id,
        status=status,
        evidence_count=evidence_count,
        gap_types=gap_types,
        search_directives=search_directives,
        reason=f"Status={status.value}.",
    )


def _result_for_needs(
    *assessments: InformationNeedAssessment,
    ready: bool | None = None,
) -> ResearchReadinessResult:
    by_rq: dict[str, list[InformationNeedAssessment]] = {}
    for assessment in assessments:
        by_rq.setdefault(assessment.research_question_id, []).append(assessment)

    rq_assessments = tuple(
        ResearchReadinessAssessment(
            research_question_id=rq_id,
            information_need_assessments=tuple(items),
            ready_for_analysis=all(
                item.status == SufficiencyStatus.SUFFICIENT for item in items
            ),
            blocking_information_need_ids=tuple(
                item.information_need_id
                for item in items
                if item.status
                in {
                    SufficiencyStatus.MISSING,
                    SufficiencyStatus.PARTIAL,
                    SufficiencyStatus.INSUFFICIENT,
                    SufficiencyStatus.BLOCKED,
                }
            ),
        )
        for rq_id, items in sorted(by_rq.items())
    )
    all_ready = ready
    if all_ready is None:
        all_ready = all(item.ready_for_analysis for item in rq_assessments)
    blocking_rq = tuple(
        item.research_question_id for item in rq_assessments if not item.ready_for_analysis
    )
    blocking_needs = tuple(
        need.information_need_id
        for item in rq_assessments
        for need in item.information_need_assessments
        if need.status
        in {
            SufficiencyStatus.MISSING,
            SufficiencyStatus.PARTIAL,
            SufficiencyStatus.INSUFFICIENT,
            SufficiencyStatus.BLOCKED,
        }
    )
    has_actionable = any(
        need.status
        in {
            SufficiencyStatus.MISSING,
            SufficiencyStatus.PARTIAL,
            SufficiencyStatus.INSUFFICIENT,
        }
        for item in rq_assessments
        for need in item.information_need_assessments
    )
    return ResearchReadinessResult(
        research_question_assessments=rq_assessments,
        ready_for_analysis=all_ready,
        blocking_research_question_ids=blocking_rq if not all_ready else (),
        blocking_information_need_ids=blocking_needs if not all_ready else (),
        targeted_research_required=has_actionable if not all_ready else False,
    )


def _ready_result() -> ResearchReadinessResult:
    return _result_for_needs(
        _need_assessment(status=SufficiencyStatus.SUFFICIENT),
        ready=True,
    )


def _missing_result() -> ResearchReadinessResult:
    return _result_for_needs(_need_assessment(status=SufficiencyStatus.MISSING))


def _partial_result() -> ResearchReadinessResult:
    return _result_for_needs(_need_assessment(status=SufficiencyStatus.PARTIAL))


def _insufficient_result() -> ResearchReadinessResult:
    return _result_for_needs(_need_assessment(status=SufficiencyStatus.INSUFFICIENT))


def _blocked_result() -> ResearchReadinessResult:
    return _result_for_needs(_need_assessment(status=SufficiencyStatus.BLOCKED))


def _desk_research_template(design: ResearchDesign | None = None) -> WorkflowTemplate:
    project = Project(id="project-1", name="Test")
    return ResearchDesignWorkflowMapper().from_research_design(
        design or _design(),
        project,
    )


def _context(
    *,
    design: ResearchDesign | None = None,
) -> WorkflowContext:
    template = _desk_research_template(design)
    definition_ids = [task.id for task in template.task_definitions]
    task_by_def = {task.id: task for task in template.task_definitions}
    tasks = [
        make_task(
            definition_id,
            depends_on=list(task_by_def[definition_id].depends_on),
            executor_id=task_by_def[definition_id].executor_id,
        )
        for definition_id in definition_ids
    ]
    workflow_run = make_workflow_run(*tasks, template_id=template.id)
    return WorkflowContext(
        project=Project(id="project-1", name="Test"),
        workflow_template=template,
        workflow_run=workflow_run,
    )


def _design_three_needs() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ResearchQuestion(id="rq-3", question="Q3", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Need 1",
            ),
            InformationNeed(
                id="in-2",
                research_question_id="rq-2",
                description="Need 2",
            ),
            InformationNeed(
                id="in-3",
                research_question_id="rq-3",
                description="Need 3",
            ),
        ),
    )


class StaticSufficiencyEvaluator:
    def __init__(self, result: ResearchReadinessResult) -> None:
        self.result = result
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        self.calls += 1
        return self.result


class EvidenceAwareGapEvaluator:
    """Marks a need sufficient once targeted evidence exists; IN1 can stay stuck."""

    def __init__(self, *, stuck_need_id: str = "in-1") -> None:
        self.stuck_need_id = stuck_need_id
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        self.calls += 1
        assessments: list[InformationNeedAssessment] = []
        for need in design.information_needs:
            has_evidence = any(
                need.id in item.information_need_refs for item in evidence
            )
            if not has_evidence:
                status = SufficiencyStatus.MISSING
            elif need.id == self.stuck_need_id:
                status = SufficiencyStatus.MISSING
            else:
                status = SufficiencyStatus.SUFFICIENT
            assessments.append(
                _need_assessment(
                    need_id=need.id,
                    rq_id=need.research_question_id,
                    status=status,
                ),
            )
        return _result_for_needs(*assessments)


class RecordingProgressCheckpoint:
    def __init__(self) -> None:
        self.progress_calls = 0
        self.shared_states: list[dict[str, object]] = []

    def on_task_progress(self, context: WorkflowContext) -> None:
        self.progress_calls += 1
        self.shared_states.append(dict(context.shared_state))


def _build_service(
    evaluator,
    *,
    source_repository: InMemorySourceRepository | None = None,
    evidence_repository: InMemoryEvidenceRepository | None = None,
    runner=None,
    max_rounds: int = 2,
    max_attempts_per_gap: int = 2,
) -> ResearchReadinessService:
    source_repo = source_repository or InMemorySourceRepository()
    evidence_repo = evidence_repository or InMemoryEvidenceRepository()
    bounds = TargetedResearchBounds(
        max_gap_rounds_per_run=max_rounds,
        max_attempts_per_gap=max_attempts_per_gap,
        max_queries_per_gap=2,
        max_sources_per_gap=3,
    )
    runner = runner or DeterministicTargetedResearchRunner(
        source_repository=source_repo,
        evidence_repository=evidence_repo,
    )
    loop_service = ResearchLoopService(
        runner=runner,
        bounds=bounds,
        evaluator=evaluator,
        evidence_repository=evidence_repo,
        source_repository=source_repo,
    )
    return ResearchReadinessService(
        evaluator=evaluator,
        evidence_repository=evidence_repo,
        loop_service=loop_service,
    )


class TargetedResearchLoopTests(unittest.TestCase):
    def test_ready_initial_assessment_skips_targeted_research(self) -> None:
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=0,
            sources_acquired=0,
            evidence_extracted=0,
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([_ready_result()]),
            runner=runner,
        )
        context = _context()
        result = service.assess_and_apply(context)
        self.assertTrue(result.ready_for_analysis)
        runner.run.assert_not_called()
        self.assertEqual(context.read_shared("research_readiness")["research_loop_count"], 0)

    def test_missing_need_triggers_targeted_research_for_that_need(self) -> None:
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        evaluator = SequentialSufficiencyEvaluator(
            [_missing_result(), _ready_result()],
        )
        service = _build_service(
            evaluator,
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
        )
        context = _context()
        result = service.assess_and_apply(context)
        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(runner.targeted_need_ids, ["in-1"])
        self.assertEqual(runner.calls, 1)

    def test_partial_triggers_targeted_research(self) -> None:
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([_partial_result(), _ready_result()]),
            runner=runner,
        )
        service.assess_and_apply(_context())
        self.assertEqual(runner.calls, 1)

    def test_insufficient_triggers_targeted_research(self) -> None:
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([_insufficient_result(), _ready_result()]),
            runner=runner,
        )
        service.assess_and_apply(_context())
        self.assertEqual(runner.calls, 1)

    def test_blocked_does_not_trigger_targeted_research(self) -> None:
        runner = Mock()
        service = _build_service(
            SequentialSufficiencyEvaluator([_blocked_result()]),
            runner=runner,
        )
        context = _context()
        result = service.assess_and_apply(context)
        runner.run.assert_not_called()
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.termination_reason, "blocked_gaps")

    def test_round_visits_each_actionable_gap_before_round_terminates(self) -> None:
        design = _design_two_needs()
        missing_both = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(missing_both),
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=design)
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(runner.targeted_need_ids, ["in-1", "in-2"])
        self.assertEqual(result.termination_reason, "no_material_improvement")

    def test_targeted_request_scoped_to_existing_need_in_design(self) -> None:
        design = _design()
        result = _missing_result()
        gaps = select_actionable_gaps(
            result=result,
            design=design,
            workflow_run_id="run-1",
            attempt=1,
            existing_source_ids=(),
            existing_evidence_ids=(),
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].research_question_id, "rq-1")
        self.assertEqual(gaps[0].information_need_id, "in-1")
        with self.assertRaises(ValueError):
            TargetedSearchQueryBuilder().build_queries(
                design=design,
                request=replace(
                    gaps[0],
                    information_need_id="in-unknown",
                ),
                max_queries=1,
                max_results=5,
            )

    def test_new_evidence_appended_to_same_workflow_run(self) -> None:
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _ready_result()]),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        context = _context()
        service.assess_and_apply(context)
        evidence = evidence_repo.list_for_project(
            "project-1",
            workflow_run_id=context.workflow_run.id,
        )
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].workflow_run_id, context.workflow_run.id)

    def test_new_evidence_tagged_with_targeted_information_need_id(self) -> None:
        evidence_repo = InMemoryEvidenceRepository()
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _ready_result()]),
            evidence_repository=evidence_repo,
        )
        context = _context()
        service.assess_and_apply(context)
        evidence = evidence_repo.list_for_project(
            "project-1",
            workflow_run_id=context.workflow_run.id,
        )
        self.assertIn("in-1", evidence[0].information_need_refs)

    def test_existing_sources_and_evidence_deduplicated(self) -> None:
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = DeterministicTargetedResearchRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        service = _build_service(
            SequentialSufficiencyEvaluator(
                [_missing_result(), _missing_result(), _ready_result()],
            ),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=2,
        )
        context = _context()
        service.assess_and_apply(context)
        self.assertEqual(
            len(source_repo.list_for_project("project-1", workflow_run_id=context.workflow_run.id)),
            1,
        )
        self.assertEqual(
            len(evidence_repo.list_for_project("project-1", workflow_run_id=context.workflow_run.id)),
            1,
        )

    def test_improvement_to_sufficient_runs_analysis(self) -> None:
        evaluator = SequentialSufficiencyEvaluator([_missing_result(), _ready_result()])
        context = _context()
        analysis = RecordingAnalysisService()
        readiness = ResearchReadinessExecutor(
            research_readiness_service=_build_service(evaluator),
        )
        analysis_executor = AnalysisExecutor(analysis_service=analysis)
        resolver = Mock()
        resolver.resolve.side_effect = lambda task: {
            "search": PassThroughExecutor(),
            "evidence": PassThroughExecutor(),
            "research_quality": readiness,
            "analysis": analysis_executor,
            "report": PassThroughExecutor(),
            "review": PassThroughExecutor(),
        }[task.executor_id]
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(resolver=resolver, lifecycle=TaskLifecycleManager()),
            completion_policy=WorkflowCompletionPolicy(),
        )
        engine.run(context)
        self.assertEqual(analysis.calls, 1)

    def test_bounded_next_iteration_when_still_not_ready(self) -> None:
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        still_missing = _missing_result()
        partial = _partial_result()
        service = _build_service(
            SequentialSufficiencyEvaluator([still_missing, partial, partial]),
            runner=runner,
            max_rounds=2,
        )
        service.assess_and_apply(_context())
        self.assertEqual(runner.calls, 2)

    def test_max_rounds_reaches_controlled_insufficient_research(self) -> None:
        design = _design_two_needs()
        missing_both = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        round1_in1 = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.INSUFFICIENT),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        round1_done = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.INSUFFICIENT),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.INSUFFICIENT),
        )
        round2_in1 = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.PARTIAL),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.INSUFFICIENT),
        )
        round2_done = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.PARTIAL),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.PARTIAL),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator(
                [missing_both, round1_in1, round1_done, round2_in1, round2_done],
            ),
            max_rounds=2,
            max_attempts_per_gap=2,
        )
        context = _context(design=design)
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)
        payload = context.read_shared("research_readiness")
        self.assertEqual(payload["research_outcome"], ResearchOutcome.INSUFFICIENT_RESEARCH.value)
        self.assertEqual(result.termination_reason, "max_research_rounds")
        self.assertGreaterEqual(payload["research_loop_count"], 2)

    def test_no_material_improvement_terminates(self) -> None:
        unchanged = _missing_result()
        service = _build_service(
            SequentialSufficiencyEvaluator([unchanged, unchanged]),
            max_rounds=3,
        )
        context = _context()
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(result.termination_reason, "no_material_improvement")

    def test_all_blocked_no_research_calls(self) -> None:
        runner = Mock()
        service = _build_service(
            SequentialSufficiencyEvaluator([_blocked_result()]),
            runner=runner,
        )
        service.assess_and_apply(_context())
        runner.run.assert_not_called()

    def test_analysis_never_executes_before_ready(self) -> None:
        service = _build_service(SequentialSufficiencyEvaluator([_missing_result()]), max_rounds=1)
        context = _context()
        analysis = RecordingAnalysisService()
        readiness = ResearchReadinessExecutor(research_readiness_service=service)
        analysis_executor = AnalysisExecutor(analysis_service=analysis)
        resolver = Mock()
        resolver.resolve.side_effect = lambda task: {
            "search": PassThroughExecutor(),
            "evidence": PassThroughExecutor(),
            "research_quality": readiness,
            "analysis": analysis_executor,
            "report": PassThroughExecutor(),
            "review": PassThroughExecutor(),
        }[task.executor_id]
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(resolver=resolver, lifecycle=TaskLifecycleManager()),
            completion_policy=WorkflowCompletionPolicy(),
        )
        engine.run(context)
        self.assertEqual(analysis.calls, 0)

    def test_research_iteration_does_not_consume_retry_flag(self) -> None:
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _ready_result()]),
        )
        service.assess_and_apply(_context())
        self.assertFalse(consume_llm_call_retry_flag())

    def test_research_loop_count_persisted(self) -> None:
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _ready_result()]),
        )
        context = _context()
        service.assess_and_apply(context)
        self.assertEqual(context.read_shared("research_readiness")["research_loop_count"], 1)

    def test_loop_history_persisted(self) -> None:
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _ready_result()]),
        )
        context = _context()
        service.assess_and_apply(context)
        history = context.read_shared("research_readiness")["research_loop_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["targeted_need_ids"], ["in-1"])
        self.assertTrue(history[0]["improved"])

    def test_worker_recovery_does_not_repeat_completed_iteration(self) -> None:
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        missing_both = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(missing_both),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=1,
        )
        context = _context(design=_design_two_needs())
        record = ResearchLoopIterationRecord(
            attempt=1,
            round_number=1,
            blocking_need_ids_before=("in-1",),
            targeted_need_ids=("in-1",),
            queries_generated=1,
            new_sources_count=1,
            new_evidence_count=1,
            readiness_after=serialize_readiness(
                _missing_result(),
                research_outcome=ResearchOutcome.INSUFFICIENT_RESEARCH.value,
            ),
            improved=False,
        )
        loop_state = ResearchLoopState(
            research_loop_count=1,
            current_round=1,
            gap_attempt_counts={"in-1": 1},
            history=[record],
        )
        context.write_shared(SHARED_LOOP_STATE_KEY, loop_state.to_dict())
        service.assess_and_apply(context)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(runner.targeted_need_ids, ["in-2"])

    def test_gap_selection_is_deterministic(self) -> None:
        design = _design_two_needs()
        result = _result_for_needs(
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.PARTIAL),
        )
        gaps = select_actionable_gaps(
            result=result,
            design=design,
            workflow_run_id="run-1",
            attempt=1,
            existing_source_ids=(),
            existing_evidence_ids=(),
        )
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0].information_need_id, "in-1")
        self.assertEqual(gaps[1].information_need_id, "in-2")

    def test_targeted_query_builder_scoped_to_need(self) -> None:
        design = _design()
        request = TargetedResearchRequest(
            workflow_run_id="run-1",
            research_design_id=design.id,
            research_question_id="rq-1",
            information_need_id="in-1",
            gap_types=(GapType.NO_EVIDENCE,),
            search_directives=("TAM estimate",),
            attempt=1,
        )
        queries = TargetedSearchQueryBuilder().build_queries(
            design=design,
            request=request,
            max_queries=2,
            max_results=5,
        )
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(query.information_need_id == "in-1" for query in queries))

    def test_readiness_improved_detects_status_progression(self) -> None:
        before = _missing_result()
        after = _result_for_needs(
            _need_assessment(status=SufficiencyStatus.INSUFFICIENT),
        )
        self.assertTrue(readiness_improved(before, after))

    def test_exhausted_path_skips_downstream_tasks(self) -> None:
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result()]),
            max_rounds=1,
        )
        context = _context()
        analysis = RecordingAnalysisService()
        readiness = ResearchReadinessExecutor(research_readiness_service=service)
        analysis_executor = AnalysisExecutor(analysis_service=analysis)
        resolver = Mock()
        resolver.resolve.side_effect = lambda task: {
            "search": PassThroughExecutor(),
            "evidence": PassThroughExecutor(),
            "research_quality": readiness,
            "analysis": analysis_executor,
            "report": PassThroughExecutor(),
            "review": PassThroughExecutor(),
        }[task.executor_id]
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(resolver=resolver, lifecycle=TaskLifecycleManager()),
            completion_policy=WorkflowCompletionPolicy(),
        )
        engine.run(context)
        statuses = {task.definition_id: task.status for task in context.workflow_run.tasks}
        self.assertEqual(statuses["task-analyze"], TaskStatus.SKIPPED)
        self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)


class GapStarvationRegressionTests(unittest.TestCase):
    def test_three_actionable_gaps_first_stalled_others_still_researched(self) -> None:
        design = _design_three_needs()
        all_missing = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.PARTIAL),
            _need_assessment(need_id="in-3", rq_id="rq-3", status=SufficiencyStatus.INSUFFICIENT),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(all_missing),
            runner=runner,
            max_rounds=1,
        )
        result = service.assess_and_apply(_context(design=design))
        self.assertEqual(runner.targeted_need_ids, ["in-1", "in-2", "in-3"])
        self.assertEqual(result.termination_reason, "no_material_improvement")

    def test_first_gap_stalled_second_improves_continues_loop(self) -> None:
        design = _design_two_needs()
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        service = _build_service(
            EvidenceAwareGapEvaluator(stuck_need_id="in-1"),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=2,
        )
        result = service.assess_and_apply(_context(design=design))
        self.assertFalse(result.ready_for_analysis)
        self.assertIn("in-1", runner.targeted_need_ids)
        self.assertIn("in-2", runner.targeted_need_ids)
        self.assertGreaterEqual(runner.calls, 2)

    def test_full_round_zero_improvement_terminates(self) -> None:
        design = _design_three_needs()
        all_missing = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-3", rq_id="rq-3", status=SufficiencyStatus.MISSING),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(all_missing),
            runner=runner,
            max_rounds=2,
        )
        result = service.assess_and_apply(_context(design=design))
        self.assertEqual(result.termination_reason, "no_material_improvement")
        self.assertEqual(runner.calls, 3)

    def test_ready_mid_round_stops_immediately(self) -> None:
        design = _design_two_needs()
        missing_both = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([missing_both, _ready_result()]),
            runner=runner,
            max_rounds=2,
        )
        result = service.assess_and_apply(_context(design=design))
        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(runner.calls, 1)

    def test_blocked_gap_skipped_without_starving_actionable_gaps(self) -> None:
        design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
                ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(id="in-1", research_question_id="rq-1", description="Blocked"),
                InformationNeed(id="in-2", research_question_id="rq-2", description="Missing"),
            ),
        )
        mixed = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.BLOCKED),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(mixed),
            runner=runner,
            max_rounds=1,
        )
        service.assess_and_apply(_context(design=design))
        self.assertEqual(runner.targeted_need_ids, ["in-2"])

    def test_per_gap_and_round_bounds_cap_total_attempts(self) -> None:
        design = _design_two_needs()
        missing_both = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(missing_both),
            runner=runner,
            max_rounds=2,
            max_attempts_per_gap=1,
        )
        result = service.assess_and_apply(_context(design=design))
        self.assertEqual(runner.calls, 2)
        self.assertIn(
            result.termination_reason,
            {"no_material_improvement", "max_research_rounds"},
        )


class ResearchLoopDurabilityTests(unittest.TestCase):
    def test_checkpoint_called_after_each_completed_iteration(self) -> None:
        checkpoint = RecordingProgressCheckpoint()
        service = _build_service(
            SequentialSufficiencyEvaluator([_missing_result(), _ready_result()]),
        )
        context = _context()
        context.services[CHECKPOINT_SERVICE_KEY] = checkpoint
        service.assess_and_apply(context)
        self.assertGreaterEqual(checkpoint.progress_calls, 2)
        self.assertIn(SHARED_LOOP_STATE_KEY, checkpoint.shared_states[-1])

    def test_restored_loop_state_skips_completed_gap_attempt(self) -> None:
        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        runner = RecordingTargetedRunner(
            source_repository=source_repo,
            evidence_repository=evidence_repo,
        )
        design = _design_two_needs()
        missing_both = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            StaticSufficiencyEvaluator(missing_both),
            source_repository=source_repo,
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=1,
        )
        context = _context(design=design)
        loop_state = ResearchLoopState(
            research_loop_count=1,
            current_round=1,
            gap_attempt_counts={"in-1": 1},
            history=[
                ResearchLoopIterationRecord(
                    attempt=1,
                    round_number=1,
                    blocking_need_ids_before=("in-1", "in-2"),
                    targeted_need_ids=("in-1",),
                    queries_generated=1,
                    new_sources_count=1,
                    new_evidence_count=1,
                    readiness_after=serialize_readiness(
                        missing_both,
                        research_outcome=ResearchOutcome.INSUFFICIENT_RESEARCH.value,
                    ),
                    improved=False,
                ),
            ],
        )
        context.write_shared(SHARED_LOOP_STATE_KEY, loop_state.to_dict())
        service.assess_and_apply(context)
        self.assertEqual(runner.targeted_need_ids, ["in-2"])


if __name__ == "__main__":
    unittest.main()
