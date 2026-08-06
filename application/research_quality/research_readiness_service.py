from __future__ import annotations

from typing import Any

from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from domain.planning.research_design import ResearchDesign
from domain.research_quality.research_outcome import ResearchOutcome
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
    ) -> None:
        self._evaluator = evaluator
        self._evidence_repository = evidence_repository
        self._gate = gate or ResearchReadinessGate()

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

    def assess_and_apply(
        self,
        context: WorkflowContext,
    ) -> ResearchReadinessResult:
        result = self.evaluate_for_context(context)
        context.write_shared(
            SHARED_STATE_KEY,
            self.build_shared_payload(result),
        )
        if not result.ready_for_analysis:
            self._gate.apply_not_ready(context)
        return result

    def build_shared_payload(
        self,
        result: ResearchReadinessResult,
    ) -> dict[str, Any]:
        outcome = self._gate.research_outcome(result)
        payload = result.to_dict()
        payload["research_outcome"] = outcome.value
        return payload

    @staticmethod
    def _require_design(context: WorkflowContext) -> ResearchDesign:
        design = context.workflow_template.research_design_snapshot
        if design is None:
            raise ValueError(
                "Research readiness requires workflow_template.research_design_snapshot",
            )
        return design
