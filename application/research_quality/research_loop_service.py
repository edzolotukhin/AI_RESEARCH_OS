from __future__ import annotations

from dataclasses import replace

from application.execution.budget_utils import is_sufficiency_graceful_budget_stop
from application.execution.exceptions import BudgetExhaustedError
from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.ports.source_ports import SourceRepository
from application.research_quality.gap_scheduler import select_next_actionable_gap
from application.research_quality.gap_selection import select_actionable_gaps
from application.research_quality.research_loop_checkpoint import checkpoint_loop_progress
from application.research_quality.research_loop_state import (
    SHARED_LOOP_STATE_KEY,
    ResearchLoopIterationRecord,
    ResearchLoopState,
    serialize_readiness,
)
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from application.research_quality.budget_aware_readiness import (
    apply_sufficiency_budget_termination,
    sufficiency_budget_available,
)
from domain.research_quality.research_termination_reason import (
    BUDGET_CONTROLLED_TERMINATION_REASONS,
)
from application.research_quality.status_rank import (
    blocking_need_ids,
    need_readiness_improved,
)
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import TargetedResearchRunner
from domain.planning.research_design import ResearchDesign
from domain.research_quality.research_readiness_result import ResearchReadinessResult

from runtime.workflow_context import WorkflowContext


class ResearchLoopService:
    """Bounded targeted research loop orchestration inside readiness assessment."""

    def __init__(
        self,
        *,
        runner: TargetedResearchRunner,
        bounds: TargetedResearchBounds,
        evaluator: ResearchSufficiencyEvaluator,
        evidence_repository: EvidenceRepository,
        source_repository: SourceRepository,
        gate: ResearchReadinessGate | None = None,
    ) -> None:
        self._runner = runner
        self._bounds = bounds
        self._evaluator = evaluator
        self._evidence_repository = evidence_repository
        self._source_repository = source_repository
        self._gate = gate or ResearchReadinessGate()

    def run_bounded_loop(
        self,
        context: WorkflowContext,
        *,
        initial_result: ResearchReadinessResult,
    ) -> tuple[ResearchReadinessResult, ResearchLoopState]:
        design = self._require_design(context)
        loop_state = self._restore_loop_state(context)
        result = initial_result
        workflow_run_id = context.workflow_run.id

        if result.ready_for_analysis:
            loop_state.termination_reason = "ready"
            return result, loop_state

        start_round = loop_state.current_round if loop_state.current_round > 0 else 1
        if start_round > self._bounds.max_gap_rounds_per_run:
            loop_state.termination_reason = "max_research_rounds"
            return self._finalize(context, result, loop_state)

        for round_number in range(start_round, self._bounds.max_gap_rounds_per_run + 1):
            loop_state.current_round = round_number
            round_had_improvement = False
            stalled_need_ids = self._stalled_need_ids_for_round(loop_state, round_number)

            while True:
                if result.ready_for_analysis:
                    loop_state.termination_reason = "ready"
                    break

                source_ids, evidence_ids = self._collect_existing_ids(context)
                gaps = select_actionable_gaps(
                    result=result,
                    design=design,
                    workflow_run_id=workflow_run_id,
                    attempt=loop_state.research_loop_count + 1,
                    existing_source_ids=source_ids,
                    existing_evidence_ids=evidence_ids,
                )
                if not gaps:
                    loop_state.termination_reason = "no_actionable_gaps"
                    break

                request = select_next_actionable_gap(
                    gaps,
                    gap_attempt_counts=loop_state.gap_attempt_counts,
                    stalled_need_ids=stalled_need_ids,
                    max_attempts_per_gap=self._bounds.max_attempts_per_gap,
                )
                if request is None:
                    if not sufficiency_budget_available():
                        result, loop_state = apply_sufficiency_budget_termination(
                            result,
                            loop_state=loop_state,
                        )
                        return self._finalize(context, result, loop_state)
                    break

                if not sufficiency_budget_available():
                    result, loop_state = apply_sufficiency_budget_termination(
                        result,
                        loop_state=loop_state,
                    )
                    return self._finalize(context, result, loop_state)

                need_id = request.information_need_id
                request = replace(
                    request,
                    attempt=loop_state.gap_attempt_counts.get(need_id, 0) + 1,
                )
                previous = result
                blocking_before = blocking_need_ids(previous)

                loop_state.pending_targeted_need_id = need_id
                loop_state.pending_attempt = request.attempt
                self._persist_loop_state(context, loop_state)
                checkpoint_loop_progress(context)
                iteration = self._runner.run(context, request)
                try:
                    result = self._evaluate_for_context(context, design)
                except BudgetExhaustedError as exc:
                    if not is_sufficiency_graceful_budget_stop(exc):
                        raise
                    result, loop_state = apply_sufficiency_budget_termination(
                        previous,
                        loop_state=loop_state,
                    )
                    return self._finalize(context, result, loop_state)

                gap_improved = need_readiness_improved(previous, result, need_id)
                if gap_improved:
                    round_had_improvement = True
                else:
                    stalled_need_ids.add(need_id)

                loop_state.gap_attempt_counts[need_id] = (
                    loop_state.gap_attempt_counts.get(need_id, 0) + 1
                )
                loop_state.research_loop_count += 1
                outcome = self._gate.research_outcome(result).value
                record = ResearchLoopIterationRecord(
                    attempt=loop_state.research_loop_count,
                    round_number=round_number,
                    blocking_need_ids_before=blocking_before,
                    targeted_need_ids=(need_id,),
                    queries_generated=iteration.queries_executed,
                    new_sources_count=iteration.sources_acquired,
                    new_evidence_count=iteration.evidence_extracted,
                    readiness_after=serialize_readiness(result, research_outcome=outcome),
                    improved=gap_improved,
                )
                loop_state.history.append(record)
                loop_state.previous_readiness_result = serialize_readiness(
                    previous,
                    research_outcome=self._gate.research_outcome(previous).value,
                )
                loop_state.pending_targeted_need_id = ""
                loop_state.pending_attempt = 0
                self._persist_loop_state(context, loop_state)
                checkpoint_loop_progress(context)

                if result.ready_for_analysis:
                    loop_state.termination_reason = "ready"
                    break

            if result.ready_for_analysis:
                break
            if loop_state.termination_reason == "no_actionable_gaps":
                break
            if not round_had_improvement:
                if not sufficiency_budget_available():
                    result, loop_state = apply_sufficiency_budget_termination(
                        result,
                        loop_state=loop_state,
                    )
                    return self._finalize(context, result, loop_state)
                loop_state.termination_reason = "no_material_improvement"
                break
        else:
            if not result.ready_for_analysis and not loop_state.termination_reason:
                loop_state.termination_reason = "max_research_rounds"

        return self._finalize(context, result, loop_state)

    def _finalize(
        self,
        context: WorkflowContext,
        result: ResearchReadinessResult,
        loop_state: ResearchLoopState,
    ) -> tuple[ResearchReadinessResult, ResearchLoopState]:
        if (
            result.termination_reason not in BUDGET_CONTROLLED_TERMINATION_REASONS
            and loop_state.termination_reason
            and not result.ready_for_analysis
        ):
            result = replace(
                result,
                termination_reason=loop_state.termination_reason,
            )
        elif result.ready_for_analysis:
            result = replace(result, termination_reason="ready")
        self._persist_loop_state(context, loop_state)
        return result, loop_state

    def _evaluate_for_context(
        self,
        context: WorkflowContext,
        design: ResearchDesign,
    ) -> ResearchReadinessResult:
        evidence = self._evidence_repository.list_for_project(
            context.project.id,
            workflow_run_id=context.workflow_run.id,
        )
        return self._evaluator.evaluate(design=design, evidence=evidence)

    @staticmethod
    def _require_design(context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise ValueError(
                "Research loop requires workflow_template.research_design_snapshot",
            )
        return template.research_design_snapshot

    @staticmethod
    def _restore_loop_state(context: WorkflowContext) -> ResearchLoopState:
        payload = context.read_shared(SHARED_LOOP_STATE_KEY)
        if isinstance(payload, dict):
            return ResearchLoopState.from_dict(payload)
        return ResearchLoopState()

    @staticmethod
    def _persist_loop_state(
        context: WorkflowContext,
        loop_state: ResearchLoopState,
    ) -> None:
        context.write_shared(SHARED_LOOP_STATE_KEY, loop_state.to_dict())

    def _collect_existing_ids(
        self,
        context: WorkflowContext,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        sources = self._source_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        evidence = self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        return (
            tuple(sorted(source.id for source in sources)),
            tuple(sorted(item.id for item in evidence)),
        )

    @staticmethod
    def _stalled_need_ids_for_round(
        loop_state: ResearchLoopState,
        round_number: int,
    ) -> set[str]:
        stalled: set[str] = set()
        for record in loop_state.history or []:
            if record.round_number != round_number or record.improved:
                continue
            stalled.update(record.targeted_need_ids)
        return stalled
