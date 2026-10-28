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
from application.report.claim_first_report_service import ClaimFirstReportService
from application.ports.report_claim_repository import ReportClaimRepository
from application.report.editorial_composer import EditorialComposer
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
        return LlmReportEngine(
            llm_client=llm_client,
            max_output_tokens=config.report_max_output_tokens,
            reasoning_effort=config.report_reasoning_effort,
            max_sections=config.report_max_sections,
            max_findings_per_section=config.report_max_findings_per_section,
            max_insights_per_section=config.report_max_insights_per_section,
            structured_output_max_attempts=config.report_structured_output_max_attempts,
        )
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
    report_claim_repository: ReportClaimRepository,
    artifact_repository: ArtifactRepository,
    llm_client,
    report_contract_version: str = "desk_report_claim_v1",
    editorial_composer: EditorialComposer | None = None,
) -> ReportService:
    return ClaimFirstReportService(
        report_claim_repository=report_claim_repository,
        report_contract_version=report_contract_version,
        editorial_composer=editorial_composer,
        report_engine=build_report_engine(config, overrides, llm_client=llm_client),
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        evidence_repository=evidence_repository,
        source_repository=source_repository,
        report_repository=report_repository,
        artifact_repository=artifact_repository,
        max_findings_per_batch=config.report_max_findings_per_batch,
        max_chars_per_batch=config.report_max_chars_per_batch,
        max_rq_correction_attempts=config.report_max_rq_correction_attempts,
        max_sections=config.report_max_sections,
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
    report_claim_repository: ReportClaimRepository,
    artifact_repository: ArtifactRepository,
    llm_client,
    report_contract_version: str = "desk_report_claim_v1",
    editorial_composer: EditorialComposer | None = None,
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
            report_claim_repository=report_claim_repository,
            artifact_repository=artifact_repository,
            llm_client=llm_client,
            report_contract_version=report_contract_version,
            editorial_composer=editorial_composer,
        ),
    )
