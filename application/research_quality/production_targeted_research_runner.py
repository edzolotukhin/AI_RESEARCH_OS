from __future__ import annotations

from typing import Any

from application.config import ApplicationConfig
from application.evidence.evidence_extraction_service import EvidenceExtractionService
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
        )
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
        return payload

    @staticmethod
    def _require_design(context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise ValueError(
                "Targeted research requires workflow_template.research_design_snapshot",
            )
        return template.research_design_snapshot
