from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.execution.budget_utils import is_sufficiency_graceful_budget_stop
from application.execution.exceptions import BudgetExhaustedError
from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.research_quality.research_loop_state import (
    SHARED_LOOP_STATE_KEY,
    ResearchLoopState,
)
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_loop_checkpoint import checkpoint_loop_progress
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from application.research_quality.budget_aware_readiness import (
    apply_sufficiency_budget_termination,
)
from domain.planning.research_design import ResearchDesign
from domain.research_quality.research_readiness_result import ResearchReadinessResult

from runtime.workflow_context import WorkflowContext

SHARED_STATE_KEY = "research_readiness"


class ResearchReadinessService:
    """Evaluates run-scoped research readiness and prepares workflow payloads."""

    def __init__(
        self,
        *,
        evaluator: ResearchSufficiencyEvaluator,
        evidence_repository: EvidenceRepository,
        gate: ResearchReadinessGate | None = None,
        loop_service: ResearchLoopService | None = None,
    ) -> None:
        self._evaluator = evaluator
        self._evidence_repository = evidence_repository
        self._gate = gate or ResearchReadinessGate()
        self._loop_service = loop_service

    def evaluate_for_context(
        self,
        context: WorkflowContext,
    ) -> ResearchReadinessResult:
        design = self._require_design(context)
        evidence = self._evidence_repository.list_for_project(
            context.project.id,
            workflow_run_id=context.workflow_run.id,
        )
        return self._evaluator.evaluate(design=design, evidence=evidence)

    @staticmethod
    def _restore_loop_state(context: WorkflowContext) -> ResearchLoopState:
        payload = context.read_shared(SHARED_LOOP_STATE_KEY)
        if isinstance(payload, dict):
            return ResearchLoopState.from_dict(payload)
        return ResearchLoopState()

    def assess_and_apply(
        self,
        context: WorkflowContext,
    ) -> ResearchReadinessResult:
        try:
            result = self.evaluate_for_context(context)
        except BudgetExhaustedError as exc:
            if not is_sufficiency_graceful_budget_stop(exc):
                raise
            result, _ = apply_sufficiency_budget_termination(
                self._missing_readiness_fallback(context),
            )
            loop_state: ResearchLoopState | None = None
            if not result.ready_for_analysis:
                self._gate.apply_not_ready(context)
            self._persist(context, result, loop_state)
            return result

        loop_state: ResearchLoopState | None = None

        if not result.ready_for_analysis and result.targeted_research_required:
            loop_state = self._restore_loop_state(context)
            self._persist(context, result, loop_state)
            checkpoint_loop_progress(context)
            if self._loop_service is not None:
                try:
                    result, loop_state = self._loop_service.run_bounded_loop(
                        context,
                        initial_result=result,
                    )
                except BudgetExhaustedError as exc:
                    if not is_sufficiency_graceful_budget_stop(exc):
                        raise
                    result, loop_state = apply_sufficiency_budget_termination(
                        result,
                        loop_state=loop_state,
                    )
            else:
                result = replace(result, termination_reason="max_research_rounds")

        if not result.ready_for_analysis and not result.targeted_research_required:
            if not result.termination_reason:
                result = replace(result, termination_reason="blocked_gaps")

        if not result.ready_for_analysis:
            self._gate.apply_not_ready(context)

        loop_state = self._resolve_loop_state(context, loop_state)
        self._persist(context, result, loop_state)
        return result

    @staticmethod
    def _resolve_loop_state(
        context: WorkflowContext,
        loop_state: ResearchLoopState | None,
    ) -> ResearchLoopState | None:
        if loop_state is not None:
            return loop_state
        payload = context.read_shared(SHARED_LOOP_STATE_KEY)
        if isinstance(payload, dict):
            return ResearchLoopState.from_dict(payload)
        return None

    def _missing_readiness_fallback(
        self,
        context: WorkflowContext,
    ) -> ResearchReadinessResult:
        """Deterministic-only readiness when sufficiency budget fails before any eval."""
        from application.research_quality.deterministic_sufficiency_evaluator import (
            DeterministicSufficiencyEvaluator,
        )
        from application.research_quality.readiness_aggregation import (
            build_research_readiness_assessment,
            build_research_readiness_result,
        )

        design = self._require_design(context)
        evidence = self._evidence_repository.list_for_project(
            context.project.id,
            workflow_run_id=context.workflow_run.id,
        )
        signals = DeterministicSufficiencyEvaluator().evaluate(
            design=design,
            evidence=evidence,
        )
        need_assessments_by_rq: dict[str, list] = {
            rq.id: [] for rq in design.research_questions
        }
        for item in signals:
            from application.research_quality.readiness_aggregation import (
                build_information_need_assessment,
            )

            assessment = build_information_need_assessment(
                signals=item,
                semantic=None,
            )
            need_assessments_by_rq[item.research_question_id].append(assessment)
        rq_assessments = [
            build_research_readiness_assessment(
                research_question_id=rq.id,
                need_assessments=need_assessments_by_rq.get(rq.id, ()),
            )
            for rq in sorted(design.research_questions, key=lambda item: item.id)
        ]
        return build_research_readiness_result(rq_assessments)

    def build_shared_payload(
        self,
        result: ResearchReadinessResult,
        *,
        loop_state: ResearchLoopState | None = None,
    ) -> dict[str, Any]:
        outcome = self._gate.research_outcome(result)
        payload = result.to_dict()
        payload["research_outcome"] = outcome.value
        if loop_state is not None:
            payload["research_loop_count"] = loop_state.research_loop_count
            payload["research_loop_history"] = [
                item.to_dict() for item in (loop_state.history or [])
            ]
            loop_termination = loop_state.termination_reason
            if loop_termination:
                payload["research_loop_termination_reason"] = loop_termination
        else:
            payload.setdefault("research_loop_count", 0)
            payload.setdefault("research_loop_history", [])
        return payload

    def _persist(
        self,
        context: WorkflowContext,
        result: ResearchReadinessResult,
        loop_state: ResearchLoopState | None,
    ) -> None:
        context.write_shared(
            SHARED_STATE_KEY,
            self.build_shared_payload(result, loop_state=loop_state),
        )
        if loop_state is not None:
            context.write_shared(SHARED_LOOP_STATE_KEY, loop_state.to_dict())

    @staticmethod
    def _require_design(context: WorkflowContext) -> ResearchDesign:
        design = context.workflow_template.research_design_snapshot
        if design is None:
            raise ValueError(
                "Research readiness requires workflow_template.research_design_snapshot",
            )
        return design
