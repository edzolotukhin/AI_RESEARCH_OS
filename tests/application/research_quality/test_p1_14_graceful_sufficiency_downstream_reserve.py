"""P1-14 — Graceful Sufficiency downstream-reserve exhaustion (offline)."""

from __future__ import annotations

import unittest
from typing import Sequence
from unittest.mock import Mock

from application.execution.budget_utils import (
    DOWNSTREAM_RESERVE_REASON,
    EVIDENCE_PURPOSE_REMEDIATION,
    GLOBAL_RUN_BUDGET_REASON,
    SUFFICIENCY_STAGE_CAP_REASON,
    is_sufficiency_graceful_budget_stop,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    ensure_run_budget,
)
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.research_quality.budget_aware_readiness import (
    apply_sufficiency_budget_termination,
    sufficiency_budget_available,
    sufficiency_unavailable_reason,
)
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from domain.project import Project
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.research_termination_reason import (
    DOWNSTREAM_RESERVE_EXHAUSTED,
    EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED,
    SUFFICIENCY_BUDGET_EXHAUSTED,
)
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

from tests.application.research_quality.test_p1_07_2_budget_aware_orchestration import (
    BudgetCountingEvaluator,
    _build_readiness_service,
)
from tests.application.research_quality.test_targeted_research_loop import (
    RecordingTargetedRunner,
    _context as loop_context,
    _design_three_needs,
    _missing_result,
)
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _stock_budget() -> ExecutionBudget:
    return ExecutionBudget(
        llm_max_calls_per_run=100,
        evidence_max_llm_calls=50,
        evidence_remediation_reserved_llm_calls=0,
        sufficiency_max_llm_calls=20,
        analysis_max_llm_calls=14,
        report_max_llm_calls=20,
        review_max_llm_calls=7,
    )


def _fill_evidence(budget: ExecutionBudget, n: int = 50) -> None:
    """Bill Evidence like stock live runs: initial until reserve, then remediation."""
    initial = 0
    while initial < n:
        try:
            budget.assert_can_call("evidence")
        except BudgetExhaustedError:
            break
        budget.record_llm_call("evidence")
        initial += 1
    rem = 0
    while initial + rem < n:
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        rem += 1


def _fill_sufficiency(budget: ExecutionBudget, n: int) -> None:
    for _ in range(n):
        budget.assert_can_call("sufficiency")
        budget.record_llm_call("sufficiency")


def _fill_p1_10_like(budget: ExecutionBudget) -> None:
    """Global=58: Evidence 50 + Sufficiency 8."""
    _fill_evidence(budget, 50)
    _fill_sufficiency(budget, 8)


def _fill_p1_12_like(budget: ExecutionBudget) -> None:
    """Global=59: Evidence 50 + Sufficiency 9."""
    _fill_evidence(budget, 50)
    _fill_sufficiency(budget, 9)


def _activate(budget: ExecutionBudget):
    return _current_budget.set(budget)


class CachedMissingEvaluator:
    """Returns a fixed missing result after billing one sufficiency call when allowed."""

    def __init__(self, budget: ExecutionBudget, result: ResearchReadinessResult) -> None:
        self._budget = budget
        self._result = result
        self.calls = 0
        self.billed = 0

    def evaluate(self, *, design, evidence) -> ResearchReadinessResult:
        self.calls += 1
        self._budget.assert_can_call("sufficiency")
        self._budget.record_llm_call("sufficiency")
        self.billed += 1
        return self._result


class P114GracefulClassificationUnitTests(unittest.TestCase):
    def test_case1_stage_cap_still_graceful(self) -> None:
        err = BudgetExhaustedError(SUFFICIENCY_STAGE_CAP_REASON, stage="sufficiency")
        self.assertTrue(is_sufficiency_graceful_budget_stop(err))
        budget = _stock_budget()
        token = _activate(budget)
        try:
            _fill_sufficiency(budget, 20)
            reason = sufficiency_unavailable_reason()
            self.assertEqual(reason, SUFFICIENCY_STAGE_CAP_REASON)
            self.assertFalse(sufficiency_budget_available())
        finally:
            _current_budget.reset(token)

    def test_case3_boundary_before_reserve_allows_call(self) -> None:
        budget = _stock_budget()
        token = _activate(budget)
        try:
            _fill_p1_10_like(budget)
            self.assertEqual(budget._total_llm_calls, 58)
            self.assertIsNone(sufficiency_unavailable_reason())
            budget.assert_can_call("sufficiency")
        finally:
            _current_budget.reset(token)

    def test_case4_boundary_at_reserve_blocks_without_extra_call(self) -> None:
        budget = _stock_budget()
        token = _activate(budget)
        try:
            _fill_p1_12_like(budget)
            self.assertEqual(budget._total_llm_calls, 59)
            reason = sufficiency_unavailable_reason()
            self.assertEqual(reason, DOWNSTREAM_RESERVE_REASON)
            self.assertEqual(budget._total_llm_calls, 59)
            self.assertEqual(budget.stage_calls("analysis"), 0)
            self.assertEqual(budget.stage_calls("report"), 0)
            self.assertEqual(budget.stage_calls("review"), 0)
        finally:
            _current_budget.reset(token)

    def test_case8_unexpected_budget_error_still_raises(self) -> None:
        err = BudgetExhaustedError(GLOBAL_RUN_BUDGET_REASON, stage="sufficiency")
        self.assertFalse(is_sufficiency_graceful_budget_stop(err))
        budget = _stock_budget()
        budget._total_llm_calls = 100
        budget._exhausted = True
        budget._exhaustion_reason = GLOBAL_RUN_BUDGET_REASON
        token = _activate(budget)
        try:
            with self.assertRaises(BudgetExhaustedError) as ctx:
                sufficiency_unavailable_reason()
            self.assertEqual(ctx.exception.reason, GLOBAL_RUN_BUDGET_REASON)
        finally:
            _current_budget.reset(token)

    def test_termination_reason_preserves_downstream_reserve(self) -> None:
        result, _ = apply_sufficiency_budget_termination(
            _missing_result(),
            reason=DOWNSTREAM_RESERVE_REASON,
        )
        self.assertEqual(result.termination_reason, DOWNSTREAM_RESERVE_EXHAUSTED)
        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)


class P114ReadinessLoopTests(unittest.TestCase):
    def test_case2_and_10_reserve_stop_completes_workflow(self) -> None:
        budget = _stock_budget()
        _fill_p1_12_like(budget)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=0,
            sources_acquired=0,
            evidence_extracted=0,
        )
        context = loop_context()
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        evaluator = CachedMissingEvaluator(budget, _missing_result())
        service = _build_readiness_service(evaluator, runner=runner, budget=budget)

        result = service.assess_and_apply(context)

        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.termination_reason, DOWNSTREAM_RESERVE_EXHAUSTED)
        readiness = context.read_shared("research_readiness")
        self.assertEqual(
            readiness["research_outcome"],
            ResearchOutcome.INSUFFICIENT_RESEARCH.value,
        )
        self.assertEqual(budget._total_llm_calls, 59)
        self.assertEqual(evaluator.billed, 0)
        runner.run.assert_not_called()

        for task in context.workflow_run.tasks:
            if task.is_terminal:
                continue
            if task.definition_id == "task-assess-research-readiness":
                task.ready()
                task.start()
                task.complete()
            else:
                task.skip()
        self.assertEqual(
            WorkflowCompletionPolicy.resolve(context.workflow_run),
            WorkflowStatus.COMPLETED,
        )
        analysis = [
            t
            for t in context.workflow_run.tasks
            if t.definition_id == "task-analyze"
        ]
        self.assertTrue(analysis)
        self.assertEqual(analysis[0].status, TaskStatus.SKIPPED)

    def test_case5_blocking_in_keeps_analysis_skipped(self) -> None:
        # Covered by case2_and_10 apply_not_ready; assert explicitly on gate outcome.
        budget = _stock_budget()
        _fill_p1_12_like(budget)
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        service = _build_readiness_service(
            CachedMissingEvaluator(budget, _missing_result()),
            runner=Mock(
                run=Mock(
                    return_value=TargetedResearchIterationResult(
                        source_ids=(),
                        evidence_ids=(),
                        queries_executed=0,
                        sources_acquired=0,
                        evidence_extracted=0,
                    )
                )
            ),
            budget=budget,
        )
        result = service.assess_and_apply(context)
        self.assertFalse(result.ready_for_analysis)
        skipped = [
            t.status
            for t in context.workflow_run.tasks
            if t.definition_id
            in {
                "task-analyze",
                "task-write-report",
                "task-review-report",
            }
        ]
        self.assertTrue(skipped)
        self.assertTrue(all(status == TaskStatus.SKIPPED for status in skipped))

    def test_case6_cached_assessments_unchanged_on_graceful_stop(self) -> None:
        budget = _stock_budget()
        _fill_p1_10_like(budget)  # 58 — allow one more eval
        context = loop_context()
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        fixed = _missing_result()
        evaluator = CachedMissingEvaluator(budget, fixed)
        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
        )
        service = _build_readiness_service(evaluator, runner=runner, budget=budget)

        result = service.assess_and_apply(context)

        # Initial eval billed to 59; loop then stops on reserve without re-eval/mutation.
        self.assertEqual(evaluator.billed, 1)
        self.assertEqual(budget._total_llm_calls, 59)
        self.assertEqual(result.termination_reason, DOWNSTREAM_RESERVE_EXHAUSTED)
        self.assertEqual(
            result.blocking_information_need_ids,
            fixed.blocking_information_need_ids,
        )
        self.assertFalse(result.ready_for_analysis)

    def test_case11_p1_10_like_evidence_remediation_stop(self) -> None:
        """At global=58 after initial eval already persisted, Evidence stop wins."""

        class NoBillEvaluator:
            def __init__(self, result: ResearchReadinessResult) -> None:
                self._result = result
                self.calls = 0

            def evaluate(self, *, design, evidence):
                self.calls += 1
                return self._result

        budget = _stock_budget()
        _fill_p1_10_like(budget)
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        service = _build_readiness_service(
            NoBillEvaluator(_missing_result()),
            runner=Mock(
                run=Mock(
                    return_value=TargetedResearchIterationResult(
                        source_ids=(),
                        evidence_ids=(),
                        queries_executed=0,
                        sources_acquired=0,
                        evidence_extracted=0,
                    )
                )
            ),
            budget=budget,
        )
        result = service.assess_and_apply(context)
        self.assertEqual(result.termination_reason, EVIDENCE_REMEDIATION_BUDGET_EXHAUSTED)
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(budget._total_llm_calls, 58)
        self.assertEqual(budget.stage_calls("analysis"), 0)

    def test_case7_when_both_exhausted_reserve_is_first_causal(self) -> None:
        class NoBillEvaluator:
            def evaluate(self, *, design, evidence):
                return _missing_result()

        budget = _stock_budget()
        _fill_p1_12_like(budget)
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        service = _build_readiness_service(
            NoBillEvaluator(),
            runner=Mock(),
            budget=budget,
        )
        result = service.assess_and_apply(context)
        self.assertEqual(result.termination_reason, DOWNSTREAM_RESERVE_EXHAUSTED)
        self.assertEqual(budget._total_llm_calls, 59)

    def test_case9_provider_error_still_fails_task(self) -> None:
        class ExplodingEvaluator:
            def evaluate(self, *, design, evidence):
                raise RuntimeError("provider boom")

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
        budget = _stock_budget()
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
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

    def test_case12_no_downstream_budget_consumed(self) -> None:
        budget = _stock_budget()
        _fill_p1_12_like(budget)
        context = loop_context(design=_design_three_needs())
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)
        service = _build_readiness_service(
            CachedMissingEvaluator(budget, _missing_result()),
            runner=Mock(),
            budget=budget,
        )
        service.assess_and_apply(context)
        self.assertEqual(budget.stage_calls("analysis"), 0)
        self.assertEqual(budget.stage_calls("report"), 0)
        self.assertEqual(budget.stage_calls("review"), 0)
        self.assertEqual(budget._total_llm_calls, 59)

    def test_case1_stage_cap_path_unchanged_via_service(self) -> None:
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
        self.assertEqual(result.termination_reason, SUFFICIENCY_BUDGET_EXHAUSTED)
        self.assertFalse(result.ready_for_analysis)
        runner.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
