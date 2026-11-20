from __future__ import annotations

from typing import Any

from application.config import ApplicationConfig
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.evidence_extraction_diagnostics import (
    EvidenceStageFailureClassification,
)
from application.execution.budget_utils import EVIDENCE_PURPOSE_REMEDIATION
from application.execution.execution_budget_context import (
    get_evidence_call_purpose,
    get_execution_stage,
    set_evidence_call_purpose,
    set_execution_stage,
)
from application.execution.remediation_attempt_envelope import (
    EXTRACTION_ORDERING_DOCUMENT_ORDER,
    SHARED_REMEDIATION_EXTRACTION_KEY,
)
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from application.research_quality.targeted_search_query_builder import (
    TargetedSearchQueryBuilder,
)
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_need_exhaustion import work_item_is_completed_low_value
from application.sources.query_opportunities import KEY as QUERY_HISTORY, focus_repeated_queries
from domain.planning.research_design import ResearchDesign
from domain.research_quality.targeted_research_request import TargetedResearchRequest

from runtime.workflow_context import WorkflowContext


class ProductionTargetedResearchRunner:
    """Production targeted research: bounded query, search, and evidence append."""

    def __init__(
        self,
        *,
        query_builder: TargetedSearchQueryBuilder,
        source_acquisition: SourceAcquisitionService,
        evidence_extraction: EvidenceExtractionService,
        bounds: TargetedResearchBounds,
        config: ApplicationConfig,
    ) -> None:
        self._query_builder = query_builder
        self._source_acquisition = source_acquisition
        self._evidence_extraction = evidence_extraction
        self._bounds = bounds
        self._config = config

    def run(
        self,
        context: WorkflowContext,
        request: TargetedResearchRequest,
    ) -> TargetedResearchIterationResult:
        design = self._require_design(context)
        queries = self._query_builder.build_queries(
            design=design,
            request=request,
            max_queries=self._bounds.max_queries_per_gap,
            max_results=self._config.source_max_candidates_per_query,
            brief=context.project.research_brief,
        )
        queries = focus_repeated_queries(queries, design=design, request=request,
            history=context.shared_state.get(QUERY_HISTORY, ()))
        acquisition = self._source_acquisition.acquire_targeted_queries(
            context,
            queries,
            max_sources=self._bounds.max_sources_per_gap,
        )
        previous_stage = get_execution_stage()
        previous_purpose = get_evidence_call_purpose()
        set_execution_stage("evidence")
        set_evidence_call_purpose(EVIDENCE_PURPOSE_REMEDIATION)
        try:
            evidence = self._evidence_extraction.extract_for_source_ids(
                context,
                acquisition.source_ids,
                allow_empty=True,
                target_information_need_id=request.information_need_id,
                attempt_max_llm_calls=(
                    self._config.evidence_remediation_max_llm_calls_per_attempt
                ),
            )
        finally:
            set_execution_stage(previous_stage)
            set_evidence_call_purpose(previous_purpose)
        context.write_shared(SHARED_REMEDIATION_EXTRACTION_KEY, evidence.to_dict())
        attempt_diagnostics = self._remediation_attempt_diagnostics(
            evidence=evidence,
            acquisition=acquisition,
        )
        return TargetedResearchIterationResult(
            source_ids=acquisition.source_ids,
            evidence_ids=evidence.evidence_ids,
            queries_executed=acquisition.queries_executed,
            sources_acquired=acquisition.sources_acquired,
            evidence_extracted=evidence.evidence_extracted,
            extraction_attempted=True,
            budget_stop_reason=evidence.budget_stop_reason,
            extraction_processing_state=evidence.extraction_processing_state,
            remediation_attempt_diagnostics=attempt_diagnostics,
        )

    @staticmethod
    def _remediation_attempt_diagnostics(
        *,
        evidence,
        acquisition,
    ) -> dict[str, Any]:
        diagnostics = evidence.diagnostics
        payload: dict[str, Any] = {
            "source_ids": list(acquisition.source_ids),
            "sources_acquired": acquisition.sources_acquired,
            "skipped_duplicate_count": acquisition.skipped_duplicate_count,
            "extraction_ordering": EXTRACTION_ORDERING_DOCUMENT_ORDER,
            "evidence_delta": evidence.evidence_extracted,
            "source_delta": acquisition.sources_acquired,
            "attempt_completed": True,
        }
        if diagnostics is None:
            payload["processing_state"] = evidence.extraction_processing_state
            return payload
        payload.update(
            {
                "planned_chunk_count": diagnostics.planned_work_items,
                "processed_chunk_count": diagnostics.processed_work_items,
                "skipped_chunk_count": diagnostics.skipped_work_items,
                "configured_attempt_call_cap": (
                    diagnostics.remediation_attempt_configured_limit
                ),
                "effective_attempt_call_cap": (
                    diagnostics.remediation_attempt_effective_limit
                ),
                "remediation_calls_remaining_before": (
                    diagnostics.remediation_calls_remaining_before
                ),
                "actual_evidence_calls_consumed": (
                    diagnostics.remediation_attempt_calls_consumed
                ),
                "remediation_calls_remaining_after": (
                    diagnostics.remediation_calls_remaining_after
                ),
                "capped": diagnostics.remediation_attempt_capped,
                "processing_state": diagnostics.extraction_processing_state,
                "budget_stop_reason": diagnostics.budget_stop_reason,
            }
        )
        outcome, action = ProductionTargetedResearchRunner._bounded_recovery_decision(
            evidence=evidence,
            acquisition=acquisition,
        )
        payload["recovery_outcome"] = outcome
        payload["recovery_action"] = action
        rejection_codes = sorted({
            item.rejection_code
            for item in diagnostics.candidate_rejection_diagnostics
        })[:16]
        if rejection_codes:
            payload["candidate_rejection_codes"] = rejection_codes
        completed = []
        for item in diagnostics.work_items:
            serialized = item.to_dict()
            if not work_item_is_completed_low_value(serialized):
                continue
            completed.append({
                "source_id": item.source_id,
                "information_need_ids": list(item.information_need_ids),
                "primary_need_id": item.primary_need_id,
                "extractor_status": item.extractor_status,
                "failure_categories": list(serialized.get("failure_categories") or ()),
                "candidate_outcomes": [
                    {"outcome": outcome.get("outcome")}
                    for outcome in serialized.get("candidate_outcomes") or ()
                    if isinstance(outcome, dict)
                ],
                "operation_id": item.operation_id,
                "source_retry_identity": item.source_retry_identity,
            })
        if completed:
            payload["completed_low_value_attempts"] = completed[:32]
            payload["completed_low_value_attempts_truncated"] = len(completed) > 32
        return payload

    @staticmethod
    def _bounded_recovery_decision(*, evidence, acquisition) -> tuple[str, str]:
        """Map observed typed outcomes to the existing bounded loop actions."""
        diagnostics = evidence.diagnostics
        if evidence.budget_stop_reason or acquisition.budget_exhausted:
            return "explicit_stop_or_budget_exhaustion", "stop"
        if evidence.evidence_extracted > 0:
            return "evidence_persisted", "continue_readiness"
        failure_categories = set(acquisition.failure_category_counts)
        if acquisition.retrieval_failures and acquisition.sources_acquired == 0:
            if failure_categories == {"unsupported_content_type"}:
                return "unsupported_source_format", "alternate_supported_source"
            return "retrieval_transport_failure", "alternate_source"
        if diagnostics is None:
            return "no_extraction_diagnostics", "alternate_source"
        classification = diagnostics.failure_classification
        if classification == EvidenceStageFailureClassification.NO_CANDIDATES.value:
            if acquisition.truncated_count:
                return "truncated_content_zero_candidates", "changed_content_or_source"
            return "valid_source_zero_candidates", "diversify_source_or_query"
        if classification == EvidenceStageFailureClassification.PROVENANCE_REJECTED_ALL.value:
            return "provenance_rejection", "alternate_source_or_explicit_correction"
        if classification == EvidenceStageFailureClassification.GROUNDING_REJECTED_ALL.value:
            return "grounding_rejection", "alternate_source_or_explicit_correction"
        if classification == EvidenceStageFailureClassification.EXTRACTOR_FAILURE.value:
            return "extraction_technical_failure", "bounded_retry_or_alternate_source"
        if acquisition.sources_acquired == 0:
            return "no_eligible_source", "alternate_source"
        return "mixed_or_unclassified_failure", "alternate_source"

    @staticmethod
    def _require_design(context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise ValueError(
                "Targeted research requires workflow_template.research_design_snapshot",
            )
        return template.research_design_snapshot
