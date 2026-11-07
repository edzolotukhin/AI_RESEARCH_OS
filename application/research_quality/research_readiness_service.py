from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.execution.budget_utils import is_sufficiency_graceful_budget_stop
from application.execution.exceptions import BudgetExhaustedError
from application.ports.evidence_ports import EvidenceRepository
from application.ports.source_ports import SourceRepository
from application.evidence.temporal_scope import qualifying_evidence
from application import research_funnel_telemetry as funnel
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
from domain.planning.research_design import ResearchDesign
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.research_termination_reason import (
    BUDGET_CONTROLLED_TERMINATION_REASONS,
)

from runtime.workflow_context import WorkflowContext

SHARED_STATE_KEY = "research_readiness"


class ReadinessSourceUnavailableError(RuntimeError):
    """Operational dependency failure, never an ordinary research refusal."""


class ResearchReadinessService:
    """Evaluates run-scoped research readiness and prepares workflow payloads."""

    def __init__(
        self,
        *,
        evaluator: ResearchSufficiencyEvaluator,
        evidence_repository: EvidenceRepository,
        gate: ResearchReadinessGate | None = None,
        loop_service: ResearchLoopService | None = None,
        source_repository: SourceRepository | None = None,
        composed_authority_repository=None,
    ) -> None:
        self._evaluator = evaluator
        self._evidence_repository = evidence_repository
        self._gate = gate or ResearchReadinessGate()
        self._loop_service = loop_service
        self._source_repository = source_repository
        self._composed_authority_repository = composed_authority_repository

    def _evidence_for_context(self, context: WorkflowContext):
        from application.authority_extension import composition_for_context
        composition = composition_for_context(
            context, self._composed_authority_repository,
        )
        if composition is None:
            return self._evidence_repository.list_for_project(
                context.project.id, workflow_run_id=context.workflow_run.id,
            )
        values = []
        seen = set()
        for run_id in composition.member_workflow_run_ids:
            for item in self._evidence_repository.list_for_project(
                context.project.id, workflow_run_id=run_id,
            ):
                if item.id not in seen:
                    seen.add(item.id)
                    values.append(item)
        return values

    @funnel.observed("qualification")
    def evaluate_for_context(
        self,
        context: WorkflowContext,
    ) -> ResearchReadinessResult:
        self._require_source_repository()
        design = self._require_design(context)
        evidence = self._evidence_for_context(context)
        evidence = qualifying_evidence(
            design=design, evidence=evidence,
            source_repository=self._source_repository,
            brief=(context.workflow_template.research_brief_snapshot if context.workflow_template else None),
        )
        previous = get_sufficiency_assessment_cache()
        bind_sufficiency_assessment_cache(context)
        try:
            return self._evaluator.evaluate(design=design, evidence=evidence)
        finally:
            persist_sufficiency_assessment_cache(context)
            reset_sufficiency_assessment_cache(previous)

    @staticmethod
    def _restore_loop_state(context: WorkflowContext) -> ResearchLoopState:
        payload = context.read_shared(SHARED_LOOP_STATE_KEY)
        if isinstance(payload, dict):
            return ResearchLoopState.from_dict(payload)
        return ResearchLoopState()

    @funnel.observed("readiness")
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
                reason=exc.reason,
            )
            loop_state: ResearchLoopState | None = None
        else:
            loop_state = None

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
                        reason=exc.reason,
                    )
            else:
                result = replace(result, termination_reason="max_research_rounds")

        result = self._finalize_terminal_readiness(context, result)
        result = self._attach_per_information_need_coverage(
            context,
            result,
            loop_state,
        )

        if not result.ready_for_analysis and not result.targeted_research_required:
            if not result.termination_reason:
                result = replace(result, termination_reason="blocked_gaps")

        self._gate.apply_analysis_gate(context, result)

        loop_state = self._resolve_loop_state(context, loop_state)
        self._persist(context, result, loop_state)
        return result

    @staticmethod
    def _attach_per_information_need_coverage(
        context: WorkflowContext,
        result: ResearchReadinessResult,
        loop_state: ResearchLoopState | None,
    ) -> ResearchReadinessResult:
        """Persist an independent, conservative coverage view for each IN.

        Strategy identifiers are never inferred from query counts or free text.
        Historical state without strategy metadata remains explicitly unknown.
        """
        state = loop_state or ResearchReadinessService._restore_loop_state(context)
        history = tuple(state.history or ())
        reason = state.termination_reason or result.termination_reason
        reason_lower = reason.casefold()
        if "budget" in reason_lower:
            search_status = "budget_exhausted"
        elif "technical" in reason_lower or "failed" in reason_lower:
            search_status = "technically_interrupted"
        elif not history:
            search_status = "unknown"
        else:
            search_status = "in_progress"

        assessments = []
        for research_question in result.research_question_assessments:
            needs = []
            for assessment in research_question.information_need_assessments:
                need_id = assessment.information_need_id
                sufficient = assessment.status.value == "sufficient" and assessment.assessment_current
                dimensions = tuple(dict.fromkeys((*assessment.missing_aspects, *(item.value for item in assessment.gap_types))))
                needs.append(replace(
                    assessment,
                    evidence_status=("sufficient" if sufficient else "insufficient"),
                    # Evidence sufficiency does not prove strategy coverage.
                    search_status=search_status,
                    missing_dimensions=dimensions,
                    # Existing history has targeted INs, not strategy IDs.
                    attempted_strategies=tuple(dict.fromkeys(
                        record.strategy_id for record in history
                        if need_id in record.targeted_need_ids
                        and record.strategy_id not in {"", "unknown"}
                    )),
                    remaining_strategies=tuple(dict.fromkeys(
                        strategy for record in history
                        if need_id in record.targeted_need_ids
                        for strategy in record.remaining_strategy_ids
                    )) or (("unknown",) if not history else ()),
                    stop_reason=reason,
                    analysis_eligible=sufficient,
                ))
            assessments.append(replace(
                research_question,
                information_need_assessments=tuple(needs),
            ))
        return replace(result, research_question_assessments=tuple(assessments))

    def _finalize_terminal_readiness(
        self,
        context: WorkflowContext,
        candidate: ResearchReadinessResult,
    ) -> ResearchReadinessResult:
        """Establish one authoritative terminal per-IN Evidence snapshot.

        A mid-Sufficiency budget stop may already have reconciled its partial
        cache for remediation-history accuracy. Every other legitimate READY
        or controlled-NOT_READY result reaches this boundary before gating or
        persistence.
        """
        self._require_source_repository()
        design = self._require_design(context)
        cache_payload = context.read_shared(SHARED_SUFFICIENCY_CACHE_KEY)
        reconciled = reconcile_terminal_readiness(
            design=design,
            evidence=qualifying_evidence(
                design=design,
                source_repository=self._source_repository,
            evidence=self._evidence_for_context(context),
                brief=(context.workflow_template.research_brief_snapshot if context.workflow_template else None),
            ),
            previous=candidate,
            cache_payload=(cache_payload if isinstance(cache_payload, dict) else None),
        )

        # Reconciliation rebuilds the authoritative assessment from Evidence,
        # but must retain the already-computed per-IN coverage diagnostics.
        prior_by_need = {
            item.information_need_id: item
            for rq in candidate.research_question_assessments
            for item in rq.information_need_assessments
        }
        reconciled = replace(
            reconciled,
            research_question_assessments=tuple(
                replace(
                    rq,
                    information_need_assessments=tuple(
                        replace(
                            item,
                            evidence_status=prior_by_need[item.information_need_id].evidence_status,
                            search_status=prior_by_need[item.information_need_id].search_status,
                            missing_dimensions=prior_by_need[item.information_need_id].missing_dimensions,
                            attempted_strategies=prior_by_need[item.information_need_id].attempted_strategies,
                            remaining_strategies=prior_by_need[item.information_need_id].remaining_strategies,
                            stop_reason=prior_by_need[item.information_need_id].stop_reason,
                            analysis_eligible=prior_by_need[item.information_need_id].analysis_eligible,
                        )
                        if item.information_need_id in prior_by_need else item
                        for item in rq.information_need_assessments
                    ),
                )
                for rq in reconciled.research_question_assessments
            ),
        )

        termination_reason = candidate.termination_reason
        if reconciled.ready_for_analysis:
            termination_reason = "ready"
        elif termination_reason == "ready":
            termination_reason = ""

        targeted_research_required = reconciled.targeted_research_required
        if termination_reason in BUDGET_CONTROLLED_TERMINATION_REASONS:
            targeted_research_required = False

        return replace(
            reconciled,
            targeted_research_required=targeted_research_required,
            termination_reason=termination_reason,
        )

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

        self._require_source_repository()
        design = self._require_design(context)
        evidence = self._evidence_for_context(context)
        evidence = qualifying_evidence(
            design=design, evidence=evidence,
            source_repository=self._source_repository,
            brief=(context.workflow_template.research_brief_snapshot if context.workflow_template else None),
        )
        signals = DeterministicSufficiencyEvaluator().evaluate(
            design=design,
            evidence=evidence,
        )
        needs_by_id = {need.id: need for need in design.information_needs}
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
                information_need=needs_by_id.get(item.information_need_id),
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

    def _require_source_repository(self):
        if self._source_repository is None or not callable(
            getattr(self._source_repository, "get_by_id", None)
        ):
            raise ReadinessSourceUnavailableError("readiness_source_repository_unavailable")

    def build_shared_payload(
        self,
        result: ResearchReadinessResult,
        *,
        loop_state: ResearchLoopState | None = None,
    ) -> dict[str, Any]:
        outcome = self._gate.research_outcome(result)
        payload = result.to_dict()
        payload["research_outcome"] = outcome.value
        if not result.ready_for_analysis:
            payload["research_product_outcome"] = {
                "outcome": "INSUFFICIENT",
                "derivation_version": "p8d3-v1",
                "unresolved_information_need_ids": list(
                    result.blocking_information_need_ids
                ),
            }
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

    @staticmethod
    def _attach_sufficiency_diagnostics(
        context: WorkflowContext,
        payload: dict[str, Any],
    ) -> None:
        cache_payload = context.read_shared(SHARED_SUFFICIENCY_CACHE_KEY)
        if isinstance(cache_payload, dict):
            payload["sufficiency_assessment_diagnostics"] = {
                "semantic_assessment_calls": cache_payload.get(
                    "semantic_assessment_calls",
                    0,
                ),
                "reused_assessments": cache_payload.get("reused_assessments", 0),
                "reassessed_fingerprint_changed": cache_payload.get(
                    "reassessed_fingerprint_changed",
                    0,
                ),
                "missing_no_evidence": cache_payload.get("missing_no_evidence", 0),
                "missing_prior_state": cache_payload.get("missing_prior_state", 0),
                "reused_need_ids": list(cache_payload.get("reused_need_ids", [])),
                "reassessed_need_ids": list(
                    cache_payload.get("reassessed_need_ids", []),
                ),
                "missing_need_ids": list(cache_payload.get("missing_need_ids", [])),
            }

    @staticmethod
    def _attach_quality_contract_diagnostics(
        design: ResearchDesign,
        result: ResearchReadinessResult,
        payload: dict[str, Any],
    ) -> None:
        explicit = sum(
            1
            for need in design.information_needs
            if need.evidence_expectation is not None
        )
        payload["quality_contract_diagnostics"] = {
            "information_need_count": len(design.information_needs),
            "explicit_expectation_count": explicit,
            "legacy_fallback_count": len(design.information_needs) - explicit,
            "assessment_quality_contract_modes": {
                assessment.information_need_id: assessment.quality_contract_mode
                for rq in result.research_question_assessments
                for assessment in rq.information_need_assessments
            },
            "assessment_required_aspect_ids": {
                assessment.information_need_id: list(assessment.required_aspect_ids)
                for rq in result.research_question_assessments
                for assessment in rq.information_need_assessments
            },
        }

    def _persist(
        self,
        context: WorkflowContext,
        result: ResearchReadinessResult,
        loop_state: ResearchLoopState | None,
    ) -> None:
        payload = self.build_shared_payload(result, loop_state=loop_state)
        self._attach_sufficiency_diagnostics(context, payload)
        self._attach_quality_contract_diagnostics(
            self._require_design(context),
            result,
            payload,
        )
        context.write_shared(
            SHARED_STATE_KEY,
            payload,
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
