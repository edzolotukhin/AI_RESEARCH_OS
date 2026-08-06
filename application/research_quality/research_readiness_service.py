from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.research_quality.research_loop_state import (
    SHARED_LOOP_STATE_KEY,
    ResearchLoopState,
)
from application.research_quality.research_loop_service import ResearchLoopService
from application.research_quality.research_loop_checkpoint import checkpoint_loop_progress
from application.research_quality.research_readiness_gate import ResearchReadinessGate
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
        result = self.evaluate_for_context(context)
        loop_state: ResearchLoopState | None = None

        if not result.ready_for_analysis and result.targeted_research_required:
            loop_state = self._restore_loop_state(context)
            self._persist(context, result, loop_state)
            checkpoint_loop_progress(context)
            if self._loop_service is not None:
                result, loop_state = self._loop_service.run_bounded_loop(
                    context,
                    initial_result=result,
                )
            else:
                result = replace(result, termination_reason="max_research_rounds")

        if not result.ready_for_analysis and not result.targeted_research_required:
            result = replace(result, termination_reason="blocked_gaps")

        if not result.ready_for_analysis:
            self._gate.apply_not_ready(context)

        self._persist(context, result, loop_state)
        return result

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
            if loop_state.termination_reason:
                payload["research_loop_termination_reason"] = (
                    loop_state.termination_reason
                )
        else:
            payload["research_loop_count"] = 0
            payload["research_loop_history"] = []
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
