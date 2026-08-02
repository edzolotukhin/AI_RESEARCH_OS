from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from application.ports.project_repository import ProjectRepository
from application.ports.analysis_ports import AnalysisEngine, FindingRepository, InsightRepository
from application.ports.evidence_ports import EvidenceExtractor, EvidenceRepository
from application.ports.report_ports import ReportEngine, ReportRepository
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
)


@dataclass(frozen=True)
class ApplicationConfig:
    """
    Application-level configuration for composition.
    """

    llm_model: str = "gpt-5"
    llm_max_tokens: int = 4096
    projects_root: str = "agency/projects"
    persistence_backend: str = "file"
    database_url: str | None = None
    durable_workflow_execution: bool | None = None
    background_execution_mode: str | None = None
    deterministic_stage_executors: bool = False
    search_provider: str = "tavily"
    search_api_key: str | None = None
    evidence_extractor: str = "llm"
    evidence_extraction_chunk_chars: int = DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS
    evidence_extraction_chunk_overlap_chars: int = (
        DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS
    )
    analysis_engine: str = "llm"
    analysis_max_evidence_per_batch: int = DEFAULT_ANALYSIS_MAX_EVIDENCE_PER_BATCH
    analysis_max_chars_per_batch: int = DEFAULT_ANALYSIS_MAX_CHARS_PER_BATCH
    report_engine: str = "llm"
    report_max_findings_per_batch: int = DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH
    report_max_chars_per_batch: int = DEFAULT_REPORT_MAX_CHARS_PER_BATCH

    @classmethod
    def from_env(cls) -> ApplicationConfig:
        from infrastructure.persistence.persistence_factory import (
            resolve_persistence_backend,
        )

        return cls(
            llm_model=os.environ.get("LLM_MODEL", "gpt-5"),
            llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "4096")),
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
