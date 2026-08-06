from __future__ import annotations

from application.config import ApplicationConfig
from application.evidence.evidence_extraction_service import EvidenceExtractionService
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
        evidence = self._evidence_extraction.extract_for_source_ids(
            context,
            acquisition.source_ids,
            allow_empty=True,
        )
        return TargetedResearchIterationResult(
            source_ids=acquisition.source_ids,
            evidence_ids=evidence.evidence_ids,
            queries_executed=acquisition.queries_executed,
            sources_acquired=acquisition.sources_acquired,
            evidence_extracted=evidence.evidence_extracted,
        )

    @staticmethod
    def _require_design(context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise ValueError(
                "Targeted research requires workflow_template.research_design_snapshot",
            )
        return template.research_design_snapshot
