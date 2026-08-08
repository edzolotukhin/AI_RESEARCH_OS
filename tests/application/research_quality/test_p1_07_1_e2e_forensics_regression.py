"""P1-07.1 offline regressions for Serbia E2E forensics (no providers)."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Sequence
from unittest.mock import Mock

from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import ensure_run_budget
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.research_termination_reason import (
    SUFFICIENCY_BUDGET_EXHAUSTED,
)
from domain.value_objects.task_status import TaskStatus
from domain.workflow_template import WorkflowTemplate

from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _design(*need_ids: str) -> ResearchDesign:
    needs = tuple(
        InformationNeed(
            id=need_id,
            research_question_id="RQ1",
            description=f"Need {need_id}",
        )
        for need_id in need_ids
    )
    return ResearchDesign(
        id="design-1",
        language="en",
        research_questions=(
            ResearchQuestion(
                id="RQ1",
                question="Question?",
                priority=1,
            ),
        ),
        information_needs=needs,
        assumptions=(),
        limitations=(),
        analysis_plan=(),
        source_strategy=(),
        deliverable_plan=(),
    )


def _missing_result(*need_ids: str) -> ResearchReadinessResult:
    need_assessments = tuple(
        InformationNeedAssessment(
            information_need_id=need_id,
            research_question_id="RQ1",
            status=SufficiencyStatus.MISSING,
            evidence_count=0,
            independent_source_count=0,
            gap_types=(GapType.NO_EVIDENCE,),
            reason="missing",
        )
        for need_id in need_ids
    )
    return ResearchReadinessResult(
        research_question_assessments=(
            ResearchReadinessAssessment(
                research_question_id="RQ1",
                information_need_assessments=need_assessments,
                ready_for_analysis=False,
                blocking_information_need_ids=need_ids,
                reason="missing",
            ),
        ),
        ready_for_analysis=False,
        blocking_research_question_ids=("RQ1",),
        blocking_information_need_ids=need_ids,
        targeted_research_required=True,
    )


class BudgetCountingEvaluator:
    """Calls budget.assert_can_call('sufficiency') on every evaluate()."""

    def __init__(self, budget: ExecutionBudget) -> None:
        self._budget = budget
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        self.calls += 1
        self._budget.assert_can_call("sufficiency")
        self._budget.record_llm_call("sufficiency")
        return _missing_result("IN1", "IN2", "IN3", "IN4", "IN5")


class P1071ForensicsRegressionTests(unittest.TestCase):
    def test_sufficiency_budget_exhaustion_during_targeted_loop_terminates_gracefully(
        self,
    ) -> None:
        """P1-07.1 failure path now terminates research without task failure."""
        design = _design("IN1", "IN2", "IN3", "IN4", "IN5")
        template = WorkflowTemplate(
            id="tpl-1",
            name="test",
            research_design_snapshot=design,
        )
        run = make_workflow_run(
            make_task(
                definition_id="task-assess-research-readiness",
                executor_id="research_readiness",
            ),
            run_id="run-1",
            template_id="tpl-1",
        )
        context = WorkflowContext(
            project=Project(id="proj-1", name="p"),
            workflow_run=run,
            workflow_template=template,
            current_task=run.tasks[0],
        )
        budget = ExecutionBudget(sufficiency_max_llm_calls=1)
        context.execution_metadata["execution_budget"] = budget
        ensure_run_budget(context)

        runner = Mock()
        runner.run.return_value = TargetedResearchIterationResult(
            source_ids=(),
            evidence_ids=(),
            queries_executed=1,
            sources_acquired=0,
            evidence_extracted=0,
        )
        evaluator = BudgetCountingEvaluator(budget)
        loop_service = ResearchLoopService(
            runner=runner,
            bounds=TargetedResearchBounds(max_gap_rounds_per_run=1, max_attempts_per_gap=1),
            evaluator=evaluator,
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=InMemorySourceRepository(),
        )
        service = ResearchReadinessService(
            evaluator=evaluator,
            evidence_repository=InMemoryEvidenceRepository(),
            loop_service=loop_service,
        )

        result = service.assess_and_apply(context)

        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.termination_reason, SUFFICIENCY_BUDGET_EXHAUSTED)
        readiness = context.read_shared("research_readiness")
        loop_state = context.read_shared("research_loop_state")
        self.assertEqual(readiness["research_loop_count"], loop_state["research_loop_count"])

    def test_evidence_attribution_maps_by_information_need_refs(self) -> None:
        """Proves readiness uses information_need_refs, not accidental collapse."""
        from application.research_quality.deterministic_sufficiency_evaluator import (
            DeterministicSufficiencyEvaluator,
        )

        design = _design("IN1", "IN2")
        evidence = [
            Evidence(
                id="ev-1",
                project_id="proj-1",
                source_id="src-1",
                source_content_checksum="checksum-1",
                workflow_run_id="run-1",
                research_design_id="design-1",
                research_question_refs=("RQ1",),
                information_need_refs=("IN1",),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                statement="Serbia market size",
                source_excerpt="Serbia market size",
                extraction_method="test",
                created_at="2026-01-01T00:00:00+00:00",
            ),
            Evidence(
                id="ev-2",
                project_id="proj-1",
                source_id="src-2",
                source_content_checksum="checksum-2",
                workflow_run_id="run-1",
                research_design_id="design-1",
                research_question_refs=("RQ1",),
                information_need_refs=("IN2",),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                statement="HoReCa trends",
                source_excerpt="HoReCa trends",
                extraction_method="test",
                created_at="2026-01-01T00:00:00+00:00",
            ),
        ]
        signals = DeterministicSufficiencyEvaluator().evaluate(
            design=design,
            evidence=evidence,
        )
        by_need = {item.information_need_id: item for item in signals}
        self.assertEqual(by_need["IN1"].evidence_count, 1)
        self.assertEqual(by_need["IN2"].evidence_count, 1)


if __name__ == "__main__":
    unittest.main()
