"""P1-07.2 budget-aware research orchestration hardening tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Sequence
from unittest.mock import Mock

from application.contracts.base_executor import BaseExecutor
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import ensure_run_budget
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.workflow_engine import WorkflowEngine
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.research_termination_reason import (
    SUFFICIENCY_BUDGET_EXHAUSTED,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
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

from tests.application.research_quality.test_targeted_research_loop import (
    RecordingTargetedRunner,
    _context as loop_context,
    _design_three_needs,
    _missing_result,
    _ready_result,
)
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class PassThroughExecutor(BaseExecutor):
    def run(self, context: WorkflowContext) -> WorkflowContext:
        return context


class BudgetCountingEvaluator:
    def __init__(self, budget: ExecutionBudget) -> None:
        self._budget = budget
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence,
    ) -> ResearchReadinessResult:
        self.calls += 1
        self._budget.assert_can_call("sufficiency")
        self._budget.record_llm_call("sufficiency")
        return _missing_result()


def _build_readiness_service(
    evaluator,
    *,
    runner=None,
    budget: ExecutionBudget | None = None,
) -> ResearchReadinessService:
    source_repo = InMemorySourceRepository()
    evidence_repo = InMemoryEvidenceRepository()
    loop_service = None
    if runner is not None:
        loop_service = ResearchLoopService(
            runner=runner,
            bounds=TargetedResearchBounds(max_gap_rounds_per_run=1, max_attempts_per_gap=1),
            evaluator=evaluator,
            evidence_repository=evidence_repo,
            source_repository=source_repo,
        )
    return ResearchReadinessService(
        evaluator=evaluator,
        evidence_repository=evidence_repo,
        loop_service=loop_service,
    )


class SufficiencyBudgetGracefulTerminationTests(unittest.TestCase):
    def test_targeted_loop_sufficiency_budget_terminates_without_exception(self) -> None:
        budget = ExecutionBudget(sufficiency_max_llm_calls=1)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
        )
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        evaluator = BudgetCountingEvaluator(budget)
        service = _build_readiness_service(evaluator, runner=runner, budget=budget)

        result = service.assess_and_apply(context)

        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.termination_reason, SUFFICIENCY_BUDGET_EXHAUSTED)
        readiness = context.read_shared("research_readiness")
        self.assertEqual(readiness["research_outcome"], ResearchOutcome.INSUFFICIENT_RESEARCH.value)
        loop_state = context.read_shared("research_loop_state")
        self.assertEqual(loop_state["research_loop_count"], 0)
        self.assertEqual(readiness["research_loop_count"], 0)
        self.assertEqual(readiness["research_loop_termination_reason"], SUFFICIENCY_BUDGET_EXHAUSTED)
        runner.run.assert_not_called()
        self.assertEqual(evaluator.calls, 1)

    def test_mid_loop_sufficiency_budget_exhaustion_preserves_loop_count(self) -> None:
        """Matches P1-07 pattern: initial eval + one loop re-eval exhaust budget."""
        budget = ExecutionBudget(sufficiency_max_llm_calls=2)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
        )
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        evaluator = BudgetCountingEvaluator(budget)
        service = _build_readiness_service(evaluator, runner=runner, budget=budget)

        result = service.assess_and_apply(context)

        self.assertEqual(result.termination_reason, SUFFICIENCY_BUDGET_EXHAUSTED)
        self.assertFalse(result.ready_for_analysis)
        runner.run.assert_called_once()
        self.assertEqual(evaluator.calls, 2)
        loop_state = context.read_shared("research_loop_state")
        readiness = context.read_shared("research_readiness")
        self.assertEqual(loop_state["research_loop_count"], 1)
        self.assertEqual(readiness["research_loop_count"], 1)
        self.assertEqual(
            readiness["research_loop_termination_reason"],
            SUFFICIENCY_BUDGET_EXHAUSTED,
        )

    def test_evidence_stage_budget_exhaustion_still_raises(self) -> None:
        budget = ExecutionBudget(evidence_max_llm_calls=0)
        service = _build_readiness_service(BudgetCountingEvaluator(budget))
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence")

    def test_unexpected_exception_still_fails_task(self) -> None:
        class ExplodingEvaluator:
            def evaluate(self, *, design, evidence):
                raise RuntimeError("boom")

        design = _design_three_needs()
        template = WorkflowTemplate(
            id="tpl",
            name="test",
            research_design_snapshot=design,
        )
        readiness_task = make_task(
            definition_id="task-assess-research-readiness",
            executor_id="research_quality",
            status=TaskStatus.CREATED,
        )
        readiness_task.ready()
        run = make_workflow_run(readiness_task, template_id=template.id)
        context = WorkflowContext(
            project=Project(id="project-1", name="Test"),
            workflow_template=template,
            workflow_run=run,
            current_task=readiness_task,
        )
        service = ResearchReadinessService(
            evaluator=ExplodingEvaluator(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        executor = ResearchReadinessExecutor(research_readiness_service=service)
        task_executor = TaskExecutor(
            resolver=Mock(resolve=Mock(return_value=executor)),
            lifecycle=TaskLifecycleManager(),
        )
        with self.assertRaises(RuntimeError):
            task_executor.execute(context)
        self.assertEqual(readiness_task.status, TaskStatus.FAILED)


class InsufficientResearchWorkflowCompletionTests(unittest.TestCase):
    def test_budget_terminated_readiness_completes_workflow(self) -> None:
        budget = ExecutionBudget(sufficiency_max_llm_calls=1)
        runner = RecordingTargetedRunner(
            source_repository=InMemorySourceRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
        )
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        evaluator = BudgetCountingEvaluator(budget)
        service = _build_readiness_service(evaluator, runner=runner, budget=budget)

        result = service.assess_and_apply(context)
        self.assertEqual(result.termination_reason, SUFFICIENCY_BUDGET_EXHAUSTED)

        for task in context.workflow_run.tasks:
            if task.is_terminal:
                continue
            if task.definition_id == "task-assess-research-readiness":
                task.ready()
                task.start()
                task.complete()
            else:
                task.skip()
        status = WorkflowCompletionPolicy.resolve(context.workflow_run)
        self.assertEqual(status, WorkflowStatus.COMPLETED)


class LoopObservabilityTests(unittest.TestCase):
    def test_embedded_readiness_loop_count_matches_loop_state_after_budget_stop(self) -> None:
        budget = ExecutionBudget(sufficiency_max_llm_calls=1)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
        )
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        evaluator = BudgetCountingEvaluator(budget)
        service = _build_readiness_service(evaluator, runner=runner, budget=budget)

        service.assess_and_apply(context)

        readiness = context.read_shared("research_readiness")
        loop_state = context.read_shared("research_loop_state")
        self.assertEqual(
            readiness["research_loop_count"],
            loop_state["research_loop_count"],
        )
        self.assertEqual(readiness["research_loop_count"], loop_state["research_loop_count"])
        self.assertEqual(readiness["research_loop_termination_reason"], SUFFICIENCY_BUDGET_EXHAUSTED)


if __name__ == "__main__":
    unittest.main()
