from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executors.review_executor import ReviewExecutor
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportRepository
from application.ports.review_ports import ReviewRepository, SemanticReviewEngine
from application.ports.source_ports import SourceRepository
from application.report.report_factory import build_report_service
from application.review.review_service import ReviewService
from infrastructure.review.deterministic_review_engine import DeterministicReviewEngine
from infrastructure.review.llm_review_engine import LlmReviewEngine


def build_semantic_review_engine(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    *,
    llm_client,
) -> SemanticReviewEngine:
    if overrides.review_engine is not None:
        return overrides.review_engine
    provider = config.review_engine.lower()
    if provider == "deterministic":
        return DeterministicReviewEngine()
    if provider == "llm":
        if llm_client is None:
            raise ValueError("LLM client is required for REVIEW_ENGINE=llm")
        return LlmReviewEngine(
            llm_client=llm_client,
            max_chars_per_section=config.review_max_chars_per_section,
            max_issues_per_section=config.review_max_issues_per_section,
            max_output_tokens=config.review_max_output_tokens,
            reasoning_effort=config.review_reasoning_effort,
            structured_output_max_attempts=config.review_structured_output_max_attempts,
            max_review_calls=config.review_max_calls,
        )
    raise ValueError(
        f"Unsupported REVIEW_ENGINE: {provider!r}. Expected one of: llm, deterministic.",
    )


def build_review_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    finding_repository: FindingRepository,
    insight_repository: InsightRepository,
    evidence_repository: EvidenceRepository,
    source_repository: SourceRepository,
    report_repository: ReportRepository,
    artifact_repository: ArtifactRepository,
    review_repository: ReviewRepository,
    llm_client,
) -> ReviewExecutor:
    report_service = build_report_service(
        config=config,
        overrides=overrides,
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        evidence_repository=evidence_repository,
        source_repository=source_repository,
        report_repository=report_repository,
        artifact_repository=artifact_repository,
        llm_client=llm_client,
    )
    review_service = ReviewService(
        semantic_review_engine=build_semantic_review_engine(
            config,
            overrides,
            llm_client=llm_client,
        ),
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        evidence_repository=evidence_repository,
        report_repository=report_repository,
        artifact_repository=artifact_repository,
        review_repository=review_repository,
        report_service=report_service,
        max_revision_attempts=config.review_max_revision_attempts,
        max_chars_per_section=config.review_max_chars_per_section,
    )
    return ReviewExecutor(review_service=review_service)
