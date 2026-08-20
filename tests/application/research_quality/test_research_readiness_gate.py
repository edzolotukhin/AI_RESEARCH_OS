"""Tests for P1-04 research readiness gate workflow integration."""

from __future__ import annotations

import unittest
from typing import Sequence
from unittest.mock import Mock

from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.contracts.base_executor import BaseExecutor
from application.executors.analysis_executor import AnalysisExecutor
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.workflow_task_ids import TASK_ASSESS_RESEARCH_READINESS
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
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run
from tests.application.research_quality.test_targeted_research_loop import (
    _seed_evidence,
    _store_completed_assessments,
)


class PassThroughExecutor(BaseExecutor):
    def run(self, context: WorkflowContext) -> WorkflowContext:
        return context


class RecordingAnalysisService:
    def __init__(self) -> None:
        self.calls = 0

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


class StubEvidenceRepository:
    def __init__(self, evidence: Sequence[Evidence] | None = None) -> None:
        self._evidence = list(evidence or [])

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        source_id: str | None = None,
    ) -> list[Evidence]:
        if workflow_run_id is None:
            return list(self._evidence)
        return [
            item
            for item in self._evidence
            if item.workflow_run_id == workflow_run_id
        ]

    def create(self, evidence: Evidence) -> int:
        self._evidence.append(evidence)
        return len(self._evidence)

    def get_by_id(self, evidence_id: str) -> Evidence | None:
        for item in self._evidence:
            if item.id == evidence_id:
                return item
        return None

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Evidence | None:
        return None


class StubSufficiencyEvaluator:
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
        _store_completed_assessments(design, evidence, self.result)
        return self.result


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


def _ready_result() -> ResearchReadinessResult:
    assessment = InformationNeedAssessment(
        information_need_id="in-1",
        research_question_id="rq-1",
        status=SufficiencyStatus.SUFFICIENT,
        evidence_count=1,
        reason="Ready.",
    )
    return ResearchReadinessResult(
        research_question_assessments=(
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(assessment,),
                ready_for_analysis=True,
            ),
        ),
        ready_for_analysis=True,
    )


def _missing_result() -> ResearchReadinessResult:
    assessment = InformationNeedAssessment(
        information_need_id="in-1",
        research_question_id="rq-1",
        status=SufficiencyStatus.MISSING,
        evidence_count=0,
        gap_types=(GapType.NO_EVIDENCE,),
        reason="No evidence.",
    )
    return ResearchReadinessResult(
        research_question_assessments=(
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(assessment,),
                ready_for_analysis=False,
                blocking_information_need_ids=("in-1",),
            ),
        ),
        ready_for_analysis=False,
        blocking_research_question_ids=("rq-1",),
        blocking_information_need_ids=("in-1",),
        targeted_research_required=True,
    )


def _blocked_result() -> ResearchReadinessResult:
    assessment = InformationNeedAssessment(
        information_need_id="in-1",
        research_question_id="rq-1",
        status=SufficiencyStatus.BLOCKED,
        evidence_count=1,
        gap_types=(GapType.UNRESOLVABLE,),
        reason="Blocked.",
    )
    return ResearchReadinessResult(
        research_question_assessments=(
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(assessment,),
                ready_for_analysis=False,
                blocking_information_need_ids=("in-1",),
            ),
        ),
        ready_for_analysis=False,
        blocking_research_question_ids=("rq-1",),
        blocking_information_need_ids=("in-1",),
        targeted_research_required=False,
    )


def _desk_research_template() -> WorkflowTemplate:
    project = Project(id="project-1", name="Test")
    return ResearchDesignWorkflowMapper().from_research_design(_design(), project)


def _desk_research_context(
    *,
    evaluator: StubSufficiencyEvaluator,
    analysis_service: RecordingAnalysisService | None = None,
) -> tuple[WorkflowContext, RecordingAnalysisService]:
    template = _desk_research_template()
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

    analysis = analysis_service or RecordingAnalysisService()
    context = WorkflowContext(
        project=Project(id="project-1", name="Test"),
        workflow_template=template,
        workflow_run=workflow_run,
    )
    return context, analysis


def _resolver(
    *,
    readiness: ResearchReadinessExecutor,
    analysis_executor: AnalysisExecutor,
) -> Mock:
    resolver = Mock()
    resolver.resolve.side_effect = lambda task: {
        "search": PassThroughExecutor(),
        "evidence": PassThroughExecutor(),
        "research_quality": readiness,
        "analysis": analysis_executor,
        "report": PassThroughExecutor(),
        "review": PassThroughExecutor(),
    }[task.executor_id]
    return resolver


def _run_desk_research(
    context: WorkflowContext,
    resolver: Mock,
) -> WorkflowContext:
    engine = WorkflowEngine(
        scheduler=TaskScheduler(),
        task_executor=TaskExecutor(
            resolver=resolver,
            lifecycle=TaskLifecycleManager(),
        ),
        completion_policy=WorkflowCompletionPolicy(),
    )
    return engine.run(context)


class ResearchReadinessGateWorkflowTests(unittest.TestCase):
    def test_readiness_task_is_between_evidence_and_analysis(self) -> None:
        template = _desk_research_template()
        ids = [task.id for task in template.task_definitions]
        self.assertEqual(
            ids.index("task-extract-evidence") + 1,
            ids.index(TASK_ASSESS_RESEARCH_READINESS),
        )
        self.assertEqual(
            ids.index(TASK_ASSESS_RESEARCH_READINESS) + 1,
            ids.index("task-analyze"),
        )

    def test_ready_path_runs_analysis(self) -> None:
        evaluator = StubSufficiencyEvaluator(_ready_result())
        context, analysis = _desk_research_context(evaluator=evaluator)
        evidence_repository = StubEvidenceRepository()
        _seed_evidence(
            evidence_repository,
            context,
            need_id="in-1",
            research_question_id="rq-1",
            evidence_id="ev-ready",
        )
        readiness = ResearchReadinessExecutor(
            research_readiness_service=ResearchReadinessService(
                evaluator=evaluator,
                evidence_repository=evidence_repository,
            ),
        )
        analysis_executor = AnalysisExecutor(analysis_service=analysis)
        context = _run_desk_research(
            context,
            _resolver(readiness=readiness, analysis_executor=analysis_executor),
        )

        workflow_run = context.workflow_run
        statuses = {task.definition_id: task.status for task in workflow_run.tasks}
        self.assertEqual(statuses[TASK_ASSESS_RESEARCH_READINESS], TaskStatus.COMPLETED)
        self.assertEqual(statuses["task-analyze"], TaskStatus.COMPLETED)
        self.assertEqual(analysis.calls, 1)
        self.assertTrue(context.read_shared("research_readiness")["ready_for_analysis"])

    def test_not_ready_skips_analysis_without_findings(self) -> None:
        evaluator = StubSufficiencyEvaluator(_missing_result())
        context, analysis = _desk_research_context(evaluator=evaluator)
        readiness = ResearchReadinessExecutor(
            research_readiness_service=ResearchReadinessService(
                evaluator=evaluator,
                evidence_repository=StubEvidenceRepository(),
            ),
        )
        analysis_executor = AnalysisExecutor(analysis_service=analysis)
        context = _run_desk_research(
            context,
            _resolver(readiness=readiness, analysis_executor=analysis_executor),
        )

        workflow_run = context.workflow_run
        statuses = {task.definition_id: task.status for task in workflow_run.tasks}
        self.assertEqual(statuses[TASK_ASSESS_RESEARCH_READINESS], TaskStatus.COMPLETED)
        self.assertEqual(statuses["task-analyze"], TaskStatus.SKIPPED)
        self.assertEqual(statuses["task-write-report"], TaskStatus.SKIPPED)
        self.assertEqual(statuses["task-review-report"], TaskStatus.SKIPPED)
        self.assertEqual(analysis.calls, 0)
        self.assertEqual(workflow_run.status, WorkflowStatus.COMPLETED)

        payload = context.read_shared("research_readiness")
        self.assertFalse(payload["ready_for_analysis"])
        self.assertEqual(payload["research_outcome"], ResearchOutcome.INSUFFICIENT_RESEARCH.value)
        self.assertEqual(payload["blocking_information_need_ids"], ["in-1"])
        self.assertTrue(payload["targeted_research_required"])

    def test_blocked_only_sets_targeted_research_false(self) -> None:
        gate = ResearchReadinessGate()
        result = _blocked_result()
        self.assertEqual(
            gate.research_outcome(result),
            ResearchOutcome.INSUFFICIENT_RESEARCH,
        )
        self.assertFalse(result.targeted_research_required)

    def test_research_insufficiency_does_not_raise(self) -> None:
        evaluator = StubSufficiencyEvaluator(_missing_result())
        context, _analysis = _desk_research_context(evaluator=evaluator)
        service = ResearchReadinessService(
            evaluator=evaluator,
            evidence_repository=StubEvidenceRepository(),
        )
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)

    def test_technical_assessor_error_fails_task(self) -> None:
        class FailingEvaluator:
            def evaluate(self, *, design, evidence):
                raise SemanticSufficiencyAssessmentError("provider down")

        evaluator = StubSufficiencyEvaluator(_ready_result())
        context, _analysis = _desk_research_context(evaluator=evaluator)
        readiness = ResearchReadinessExecutor(
            research_readiness_service=ResearchReadinessService(
                evaluator=FailingEvaluator(),
                evidence_repository=StubEvidenceRepository(),
            ),
        )
        resolver = Mock()
        resolver.resolve.return_value = readiness

        readiness_task = next(
            task
            for task in context.workflow_run.tasks
            if task.definition_id == TASK_ASSESS_RESEARCH_READINESS
        )
        for task in context.workflow_run.tasks:
            if task is readiness_task:
                continue
            if not task.is_terminal:
                task.skip()
        readiness_task.ready()
        context.current_task = readiness_task

        lifecycle = TaskLifecycleManager()
        executor = TaskExecutor(resolver=resolver, lifecycle=lifecycle)
        with self.assertRaises(SemanticSufficiencyAssessmentError):
            executor.execute(context)
        self.assertEqual(readiness_task.status, TaskStatus.FAILED)

    def test_sufficiency_stage_budget_is_accounted(self) -> None:
        from application.execution.execution_budget_context import ensure_run_budget

        context, _ = _desk_research_context(
            evaluator=StubSufficiencyEvaluator(_ready_result()),
        )
        budget = ensure_run_budget(context)
        budget.record_llm_call("sufficiency")
        self.assertEqual(budget.stage_calls("sufficiency"), 1)
        summary = budget.summary()
        self.assertIn("sufficiency", summary["stages"])

    def test_sufficiency_budget_exhaustion_is_technical_failure(self) -> None:
        budget = ExecutionBudget(sufficiency_max_llm_calls=0)
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("sufficiency")
        self.assertEqual(ctx.exception.reason, "sufficiency_max_llm_calls")


if __name__ == "__main__":
    unittest.main()
