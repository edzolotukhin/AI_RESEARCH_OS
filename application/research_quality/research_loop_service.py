from __future__ import annotations

from dataclasses import replace

from application.execution.budget_utils import is_sufficiency_graceful_budget_stop
from application.execution.exceptions import BudgetExhaustedError
from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.ports.source_ports import SourceRepository
from application.execution.execution_budget_context import get_execution_budget
from application.research_quality.gap_scheduler import decide_next_actionable_gap
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
    apply_evidence_remediation_budget_termination,
    apply_sufficiency_budget_termination,
    evidence_remediation_unavailable_reason,
    sufficiency_unavailable_reason,
)
from application.research_quality.sufficiency_assessment_cache import (
    SHARED_SUFFICIENCY_CACHE_KEY,
    bind_sufficiency_assessment_cache,
    get_sufficiency_assessment_cache,
    persist_sufficiency_assessment_cache,
    reset_sufficiency_assessment_cache,
)
from application.research_quality.terminal_state_reconciliation import (
    reconcile_terminal_readiness,
)
from application.execution.budget_utils import (
    EVIDENCE_REMEDIATION_BUDGET_REASON,
    EVIDENCE_STAGE_CAP_REASON,
)
from application.execution.remediation_attempt_envelope import (
    EXTRACTION_BOUNDED_PARTIAL,
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

                decision = decide_next_actionable_gap(
                    gaps,
                    gap_attempt_counts=loop_state.gap_attempt_counts,
                    stalled_need_ids=stalled_need_ids,
                    max_attempts_per_gap=self._bounds.max_attempts_per_gap,
                    remaining_remediation_evidence_calls=(
                        self._remaining_remediation_evidence_calls()
                    ),
                    prior_improved_need_ids=self._prior_improved_need_ids(
                        loop_state,
                    ),
                )
                request = decision.selected
                if request is None:
                    sufficiency_stop = sufficiency_unavailable_reason()
                    if sufficiency_stop is not None:
                        result, loop_state = apply_sufficiency_budget_termination(
                            result,
                            loop_state=loop_state,
                            reason=sufficiency_stop,
                        )
                        return self._finalize(context, result, loop_state)
                    break

                sufficiency_stop = sufficiency_unavailable_reason()
                if sufficiency_stop is not None:
                    result, loop_state = apply_sufficiency_budget_termination(
                        result,
                        loop_state=loop_state,
                        reason=sufficiency_stop,
                    )
                    return self._finalize(context, result, loop_state)

                remediation_stop = evidence_remediation_unavailable_reason()
                if remediation_stop is not None:
                    result, loop_state = apply_evidence_remediation_budget_termination(
                        result,
                        loop_state=loop_state,
                        reason=remediation_stop,
                    )
                    return self._finalize(context, result, loop_state)

                loop_state.scheduler_decisions.append(decision.to_dict())
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
                if (
                    iteration.extraction_processing_state != EXTRACTION_BOUNDED_PARTIAL
                    and iteration.budget_stop_reason
                    in {
                        EVIDENCE_STAGE_CAP_REASON,
                        EVIDENCE_REMEDIATION_BUDGET_REASON,
                    }
                    and iteration.evidence_extracted == 0
                ):
                    result, loop_state = apply_evidence_remediation_budget_termination(
                        result,
                        loop_state=loop_state,
                        reason=iteration.budget_stop_reason,
                    )
                    return self._finalize(context, result, loop_state)
                try:
                    result = self._evaluate_for_context(context, design)
                except BudgetExhaustedError as exc:
                    if not is_sufficiency_graceful_budget_stop(exc):
                        raise
                    cache_payload = context.read_shared(SHARED_SUFFICIENCY_CACHE_KEY)
                    result = reconcile_terminal_readiness(
                        design=design,
                        evidence=self._evidence_repository.list_for_project(
                            context.project.id,
                            workflow_run_id=context.workflow_run.id,
                        ),
                        previous=previous,
                        cache_payload=(
                            cache_payload if isinstance(cache_payload, dict) else None
                        ),
                    )
                    result, loop_state = apply_sufficiency_budget_termination(
                        result,
                        loop_state=loop_state,
                        reason=exc.reason,
                    )
                    gap_improved = need_readiness_improved(
                        previous,
                        result,
                        need_id,
                    )
                    loop_state.gap_attempt_counts[need_id] = (
                        loop_state.gap_attempt_counts.get(need_id, 0) + 1
                    )
                    loop_state.research_loop_count += 1
                    outcome = self._gate.research_outcome(result).value
                    cache_payload = (
                        cache_payload if isinstance(cache_payload, dict) else {}
                    )
                    attempt_diagnostics = dict(
                        iteration.remediation_attempt_diagnostics or {},
                    )
                    attempt_diagnostics.update(
                        {
                            "research_question_id": request.research_question_id,
                            "information_need_id": need_id,
                            "attempt_number": request.attempt,
                            "attempt_completed": True,
                            "improved": gap_improved,
                            "sufficiency_reassessed": bool(
                                cache_payload.get("reassessed_need_ids"),
                            ),
                            "fingerprint_changed": int(
                                cache_payload.get("reassessed_fingerprint_changed") or 0,
                            )
                            > 0,
                            "status_before": self._need_status_value(previous, need_id),
                            "status_after": self._need_status_value(result, need_id),
                            "terminal_state_reconciled": True,
                            "termination_reason": exc.reason,
                        }
                    )
                    loop_state.history.append(
                        ResearchLoopIterationRecord(
                            attempt=loop_state.research_loop_count,
                            round_number=round_number,
                            blocking_need_ids_before=blocking_before,
                            targeted_need_ids=(need_id,),
                            queries_generated=iteration.queries_executed,
                            new_sources_count=iteration.sources_acquired,
                            new_evidence_count=iteration.evidence_extracted,
                            readiness_after=serialize_readiness(
                                result,
                                research_outcome=outcome,
                            ),
                            improved=gap_improved,
                            extraction_attempted=iteration.extraction_attempted,
                            budget_stop_reason=iteration.budget_stop_reason,
                            reused_need_ids=tuple(
                                str(item)
                                for item in cache_payload.get("reused_need_ids", [])
                            ),
                            reassessed_need_ids=tuple(
                                str(item)
                                for item in cache_payload.get("reassessed_need_ids", [])
                            ),
                            missing_need_ids=tuple(
                                str(item)
                                for item in cache_payload.get("missing_need_ids", [])
                            ),
                            remediation_attempt_diagnostics=attempt_diagnostics,
                        )
                    )
                    loop_state.previous_readiness_result = serialize_readiness(
                        previous,
                        research_outcome=self._gate.research_outcome(previous).value,
                    )
                    loop_state.pending_targeted_need_id = ""
                    loop_state.pending_attempt = 0
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
                cache_payload = context.read_shared(SHARED_SUFFICIENCY_CACHE_KEY)
                if not isinstance(cache_payload, dict):
                    cache_payload = {}
                attempt_diagnostics = dict(
                    iteration.remediation_attempt_diagnostics or {},
                )
                attempt_diagnostics.update(
                    {
                        "research_question_id": request.research_question_id,
                        "information_need_id": need_id,
                        "attempt_number": request.attempt,
                        "attempt_completed": True,
                        "improved": gap_improved,
                        "sufficiency_reassessed": bool(
                            cache_payload.get("reassessed_need_ids"),
                        ),
                        "fingerprint_changed": int(
                            cache_payload.get("reassessed_fingerprint_changed") or 0,
                        )
                        > 0,
                        "status_before": self._need_status_value(previous, need_id),
                        "status_after": self._need_status_value(result, need_id),
                        "termination_reason": None,
                    }
                )
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
                    extraction_attempted=iteration.extraction_attempted,
                    budget_stop_reason=iteration.budget_stop_reason,
                    reused_need_ids=tuple(
                        str(item) for item in cache_payload.get("reused_need_ids", [])
                    ),
                    reassessed_need_ids=tuple(
                        str(item)
                        for item in cache_payload.get("reassessed_need_ids", [])
                    ),
                    missing_need_ids=tuple(
                        str(item) for item in cache_payload.get("missing_need_ids", [])
                    ),
                    remediation_attempt_diagnostics=attempt_diagnostics,
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
                sufficiency_stop = sufficiency_unavailable_reason()
                if sufficiency_stop is not None:
                    result, loop_state = apply_sufficiency_budget_termination(
                        result,
                        loop_state=loop_state,
                        reason=sufficiency_stop,
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
        previous = get_sufficiency_assessment_cache()
        bind_sufficiency_assessment_cache(context)
        try:
            return self._evaluator.evaluate(design=design, evidence=evidence)
        finally:
            persist_sufficiency_assessment_cache(context)
            reset_sufficiency_assessment_cache(previous)

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

    @staticmethod
    def _prior_improved_need_ids(loop_state: ResearchLoopState) -> set[str]:
        last_improved: dict[str, bool] = {}
        for record in loop_state.history or []:
            for need_id in record.targeted_need_ids:
                last_improved[need_id] = bool(record.improved)
        return {need_id for need_id, flag in last_improved.items() if flag}

    @staticmethod
    def _need_status_value(
        result: ResearchReadinessResult,
        need_id: str,
    ) -> str | None:
        for assessment in result.research_question_assessments:
            for need in assessment.information_need_assessments:
                if need.information_need_id == need_id:
                    return need.status.value
        return None

    @staticmethod
    def _remaining_remediation_evidence_calls() -> int | None:
        budget = get_execution_budget()
        if budget is None:
            return None
        return max(
            0,
            budget.evidence_remediation_reserved - budget.evidence_remediation_calls,
        )
