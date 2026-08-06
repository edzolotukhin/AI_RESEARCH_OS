from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from application.ports.project_repository import ProjectRepository
from application.ports.analysis_ports import AnalysisEngine, FindingRepository, InsightRepository
from application.ports.evidence_ports import EvidenceExtractor, EvidenceRepository
from application.ports.report_ports import ReportEngine, ReportRepository
from application.ports.review_ports import SemanticReviewEngine
from application.ports.source_ports import SearchProvider, SourceRepository, SourceRetriever
from application.services.project_service import ProjectService
from infrastructure.llm.llm_client import LLMClient

from registry.registry import Registry

from application.analysis.evidence_batching import (
    DEFAULT_ANALYSIS_MAX_CHARS_PER_BATCH,
    DEFAULT_ANALYSIS_MAX_EVIDENCE_PER_BATCH,
)
from application.evidence.content_chunking import (
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
)
from application.report.content_batching import (
    DEFAULT_REPORT_MAX_CHARS_PER_BATCH,
    DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH,
    DEFAULT_REPORT_MAX_FINDINGS_PER_SECTION,
    DEFAULT_REPORT_MAX_INSIGHTS_PER_SECTION,
    DEFAULT_REPORT_MAX_OUTPUT_TOKENS,
    DEFAULT_REPORT_MAX_RQ_CORRECTION_ATTEMPTS,
    DEFAULT_REPORT_MAX_SECTIONS,
    DEFAULT_REPORT_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
)
from application.review.review_structured_output import (
    DEFAULT_REVIEW_MAX_OUTPUT_TOKENS,
    DEFAULT_REVIEW_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
)


@dataclass(frozen=True)
class ApplicationConfig:
    """
    Application-level configuration for composition.
    """

    llm_model: str = "gpt-5"
    llm_max_tokens: int = 4096
    planner_reasoning_effort: str = "minimal"
    planner_max_output_tokens: int = 8192
    projects_root: str = "agency/projects"
    persistence_backend: str = "file"
    database_url: str | None = None
    durable_workflow_execution: bool | None = None
    background_execution_mode: str | None = None
    deterministic_stage_executors: bool = False
    search_provider: str = "tavily"
    search_api_key: str | None = None
    evidence_extractor: str = "llm"
    research_sufficiency_assessor: str = "llm"
    evidence_extraction_chunk_chars: int = DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS
    evidence_extraction_chunk_overlap_chars: int = (
        DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS
    )
    analysis_engine: str = "llm"
    analysis_max_evidence_per_batch: int = DEFAULT_ANALYSIS_MAX_EVIDENCE_PER_BATCH
    analysis_max_chars_per_batch: int = DEFAULT_ANALYSIS_MAX_CHARS_PER_BATCH
    analysis_reasoning_effort: str = "minimal"
    analysis_max_output_tokens: int = 8192
    source_max_candidates_per_query: int = 5
    source_max_candidates_per_information_need: int = 5
    source_max_sources_per_run: int = 30
    source_http_timeout_seconds: float = 10.0
    source_max_redirects: int = 5
    source_max_body_bytes: int = 512_000
    source_acquisition_max_seconds: float = 900.0
    source_min_successful_sources: int = 3
    source_min_information_need_coverage_ratio: float = 1.0
    source_dns_timeout_seconds: float = 5.0
    report_engine: str = "llm"
    report_max_findings_per_batch: int = DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH
    report_max_chars_per_batch: int = DEFAULT_REPORT_MAX_CHARS_PER_BATCH
    report_reasoning_effort: str = "minimal"
    report_max_output_tokens: int = 8192
    report_max_sections: int = 10
    report_max_findings_per_section: int = 15
    report_max_insights_per_section: int = 8
    report_structured_output_max_attempts: int = 3
    report_max_rq_correction_attempts: int = 2
    review_engine: str = "llm"
    review_max_revision_attempts: int = 1
    review_max_chars_per_section: int = 8000
    review_max_issues_per_section: int = 5
    review_reasoning_effort: str = "minimal"
    review_max_output_tokens: int = DEFAULT_REVIEW_MAX_OUTPUT_TOKENS
    review_structured_output_max_attempts: int = DEFAULT_REVIEW_STRUCTURED_OUTPUT_MAX_ATTEMPTS
    review_max_calls: int = 7
    report_max_llm_calls: int = 20
    evidence_max_llm_calls: int = 50
    sufficiency_max_llm_calls: int = 20
    analysis_max_llm_calls: int = 14
    llm_max_calls_per_run: int = 100
    evidence_max_items_per_run: int = 500
    evidence_max_items_per_source: int = 50
    analysis_max_findings: int = 100
    analysis_max_insights: int = 30

    @classmethod
    def from_env(cls) -> ApplicationConfig:
        from infrastructure.persistence.persistence_factory import (
            resolve_persistence_backend,
        )

        return cls(
            llm_model=os.environ.get("LLM_MODEL", "gpt-5"),
            llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "4096")),
            planner_reasoning_effort=os.environ.get(
                "PLANNER_REASONING_EFFORT",
                "minimal",
            ).strip().lower(),
            planner_max_output_tokens=int(
                os.environ.get("PLANNER_MAX_OUTPUT_TOKENS", "8192"),
            ),
            projects_root=os.environ.get("PROJECTS_ROOT", "agency/projects"),
            persistence_backend=resolve_persistence_backend(),
            database_url=os.environ.get("DATABASE_URL"),
            background_execution_mode=os.environ.get("BACKGROUND_EXECUTION_MODE"),
            deterministic_stage_executors=os.environ.get(
                "DETERMINISTIC_STAGE_EXECUTORS",
                "",
            ).lower()
            in {"1", "true", "yes"},
            search_provider=os.environ.get("SEARCH_PROVIDER", "tavily"),
            search_api_key=os.environ.get("SEARCH_API_KEY"),
            evidence_extractor=os.environ.get("EVIDENCE_EXTRACTOR", "llm"),
            research_sufficiency_assessor=os.environ.get(
                "RESEARCH_SUFFICIENCY_ASSESSOR",
                "llm",
            ),
            evidence_extraction_chunk_chars=int(
                os.environ.get(
                    "EVIDENCE_EXTRACTION_CHUNK_CHARS",
                    str(DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS),
                ),
            ),
            evidence_extraction_chunk_overlap_chars=int(
                os.environ.get(
                    "EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS",
                    str(DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS),
                ),
            ),
            analysis_engine=os.environ.get("ANALYSIS_ENGINE", "llm"),
            analysis_max_evidence_per_batch=int(
                os.environ.get(
                    "ANALYSIS_MAX_EVIDENCE_PER_BATCH",
                    str(DEFAULT_ANALYSIS_MAX_EVIDENCE_PER_BATCH),
                ),
            ),
            analysis_max_chars_per_batch=int(
                os.environ.get(
                    "ANALYSIS_MAX_CHARS_PER_BATCH",
                    str(DEFAULT_ANALYSIS_MAX_CHARS_PER_BATCH),
                ),
            ),
            analysis_reasoning_effort=os.environ.get(
                "ANALYSIS_REASONING_EFFORT",
                "minimal",
            ).strip().lower(),
            analysis_max_output_tokens=int(
                os.environ.get("ANALYSIS_MAX_OUTPUT_TOKENS", "8192"),
            ),
            source_max_candidates_per_query=int(
                os.environ.get("SOURCE_MAX_CANDIDATES_PER_QUERY", "5"),
            ),
            source_max_candidates_per_information_need=int(
                os.environ.get(
                    "SOURCE_MAX_CANDIDATES_PER_INFORMATION_NEED",
                    "5",
                ),
            ),
            source_max_sources_per_run=int(
                os.environ.get("SOURCE_MAX_SOURCES_PER_RUN", "30"),
            ),
            source_http_timeout_seconds=float(
                os.environ.get("SOURCE_HTTP_TIMEOUT_SECONDS", "10"),
            ),
            source_max_redirects=int(os.environ.get("SOURCE_MAX_REDIRECTS", "5")),
            source_max_body_bytes=int(
                os.environ.get("SOURCE_MAX_BODY_BYTES", "512000"),
            ),
            source_acquisition_max_seconds=float(
                os.environ.get("SOURCE_ACQUISITION_MAX_SECONDS", "900"),
            ),
            source_min_successful_sources=int(
                os.environ.get("SOURCE_MIN_SUCCESSFUL_SOURCES", "3"),
            ),
            source_min_information_need_coverage_ratio=float(
                os.environ.get("SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO", "1.0"),
            ),
            source_dns_timeout_seconds=float(
                os.environ.get("SOURCE_DNS_TIMEOUT_SECONDS", "5"),
            ),
            report_engine=os.environ.get("REPORT_ENGINE", "llm"),
            report_max_findings_per_batch=int(
                os.environ.get(
                    "REPORT_MAX_FINDINGS_PER_BATCH",
                    str(DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH),
                ),
            ),
            report_max_chars_per_batch=int(
                os.environ.get(
                    "REPORT_MAX_CHARS_PER_BATCH",
                    str(DEFAULT_REPORT_MAX_CHARS_PER_BATCH),
                ),
            ),
            report_reasoning_effort=os.environ.get(
                "REPORT_REASONING_EFFORT",
                "minimal",
            ).strip().lower(),
            report_max_output_tokens=int(
                os.environ.get(
                    "REPORT_MAX_OUTPUT_TOKENS",
                    str(DEFAULT_REPORT_MAX_OUTPUT_TOKENS),
                ),
            ),
            report_max_sections=int(
                os.environ.get("REPORT_MAX_SECTIONS", str(DEFAULT_REPORT_MAX_SECTIONS)),
            ),
            report_max_findings_per_section=int(
                os.environ.get(
                    "REPORT_MAX_FINDINGS_PER_SECTION",
                    str(DEFAULT_REPORT_MAX_FINDINGS_PER_SECTION),
                ),
            ),
            report_max_insights_per_section=int(
                os.environ.get(
                    "REPORT_MAX_INSIGHTS_PER_SECTION",
                    str(DEFAULT_REPORT_MAX_INSIGHTS_PER_SECTION),
                ),
            ),
            report_structured_output_max_attempts=int(
                os.environ.get(
                    "REPORT_STRUCTURED_OUTPUT_MAX_ATTEMPTS",
                    str(DEFAULT_REPORT_STRUCTURED_OUTPUT_MAX_ATTEMPTS),
                ),
            ),
            report_max_rq_correction_attempts=int(
                os.environ.get(
                    "REPORT_MAX_RQ_CORRECTION_ATTEMPTS",
                    str(DEFAULT_REPORT_MAX_RQ_CORRECTION_ATTEMPTS),
                ),
            ),
            review_engine=os.environ.get("REVIEW_ENGINE", "llm"),
            review_max_revision_attempts=int(
                os.environ.get("REVIEW_MAX_REVISION_ATTEMPTS", "1"),
            ),
            review_max_chars_per_section=int(
                os.environ.get("REVIEW_MAX_CHARS_PER_SECTION", "8000"),
            ),
            review_max_issues_per_section=int(
                os.environ.get("REVIEW_MAX_ISSUES_PER_SECTION", "5"),
            ),
            review_reasoning_effort=os.environ.get(
                "REVIEW_REASONING_EFFORT",
                "minimal",
            ).strip().lower(),
            review_max_output_tokens=int(
                os.environ.get(
                    "REVIEW_MAX_OUTPUT_TOKENS",
                    str(DEFAULT_REVIEW_MAX_OUTPUT_TOKENS),
                ),
            ),
            review_structured_output_max_attempts=int(
                os.environ.get(
                    "REVIEW_STRUCTURED_OUTPUT_MAX_ATTEMPTS",
                    str(DEFAULT_REVIEW_STRUCTURED_OUTPUT_MAX_ATTEMPTS),
                ),
            ),
            review_max_calls=int(os.environ.get("REVIEW_MAX_CALLS", "7")),
            report_max_llm_calls=int(os.environ.get("REPORT_MAX_LLM_CALLS", "20")),
            evidence_max_llm_calls=int(os.environ.get("EVIDENCE_MAX_LLM_CALLS", "50")),
            sufficiency_max_llm_calls=int(
                os.environ.get("SUFFICIENCY_MAX_LLM_CALLS", "20"),
            ),
            analysis_max_llm_calls=int(os.environ.get("ANALYSIS_MAX_LLM_CALLS", "14")),
            llm_max_calls_per_run=int(os.environ.get("LLM_MAX_CALLS_PER_RUN", "100")),
            evidence_max_items_per_run=int(
                os.environ.get("EVIDENCE_MAX_ITEMS_PER_RUN", "500"),
            ),
            evidence_max_items_per_source=int(
                os.environ.get("EVIDENCE_MAX_ITEMS_PER_SOURCE", "50"),
            ),
            analysis_max_findings=int(
                os.environ.get("ANALYSIS_MAX_FINDINGS", "100"),
            ),
            analysis_max_insights=int(
                os.environ.get("ANALYSIS_MAX_INSIGHTS", "30"),
            ),
        )


@dataclass
class ApplicationOverrides:
    """
    Optional dependency overrides for tests and custom wiring.
    """

    llm_client: LLMClient | None = None
    project_repository: ProjectRepository | None = None
    project_service: ProjectService | None = None
    registry: Registry | None = None
    planner_agent: Any | None = None
    deterministic_stage_executors: bool | None = None
    search_provider: SearchProvider | None = None
    source_retriever: SourceRetriever | None = None
    source_repository: SourceRepository | None = None
    evidence_extractor: EvidenceExtractor | None = None
    evidence_repository: EvidenceRepository | None = None
    analysis_engine: AnalysisEngine | None = None
    finding_repository: FindingRepository | None = None
    insight_repository: InsightRepository | None = None
    report_engine: ReportEngine | None = None
    report_repository: ReportRepository | None = None
    report_executor: Any | None = None
    review_engine: SemanticReviewEngine | None = None
    review_repository: Any | None = None
    review_executor: Any | None = None
    research_sufficiency_evaluator: Any | None = None
    research_readiness_executor: Any | None = None
