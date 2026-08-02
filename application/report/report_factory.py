from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executors.report_executor import ReportExecutor
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportEngine, ReportRepository
from application.ports.source_ports import SourceRepository
from application.report.content_batching import (
    DEFAULT_REPORT_MAX_CHARS_PER_BATCH,
    DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH,
)
from application.report.report_service import ReportService
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from infrastructure.report.llm_report_engine import LlmReportEngine


def build_report_engine(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    *,
    llm_client,
) -> ReportEngine:
    if overrides.report_engine is not None:
        return overrides.report_engine
    provider_name = config.report_engine.lower()
    if provider_name == "deterministic":
        return DeterministicReportEngine()
    if provider_name == "llm":
        if llm_client is None:
            raise ValueError("LLM client is required for REPORT_ENGINE=llm")
        return LlmReportEngine(llm_client=llm_client)
    raise ValueError(
        f"Unsupported REPORT_ENGINE: {provider_name!r}. "
        "Expected one of: llm, deterministic.",
    )


def build_report_service(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    finding_repository: FindingRepository,
    insight_repository: InsightRepository,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    report_repository: ReportRepository,
    artifact_repository: ArtifactRepository,
    llm_client,
) -> ReportService:
    return ReportService(
        report_engine=build_report_engine(config, overrides, llm_client=llm_client),
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        evidence_repository=evidence_repository,
        source_repository=source_repository,
        report_repository=report_repository,
        artifact_repository=artifact_repository,
        max_findings_per_batch=config.report_max_findings_per_batch,
        max_chars_per_batch=config.report_max_chars_per_batch,
    )


def build_report_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    finding_repository: FindingRepository,
    insight_repository: InsightRepository,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    report_repository: ReportRepository,
    artifact_repository: ArtifactRepository,
    llm_client,
) -> ReportExecutor:
    return ReportExecutor(
        report_service=build_report_service(
            config=config,
            overrides=overrides,
            finding_repository=finding_repository,
            insight_repository=insight_repository,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            report_repository=report_repository,
            artifact_repository=artifact_repository,
            llm_client=llm_client,
        ),
    )
