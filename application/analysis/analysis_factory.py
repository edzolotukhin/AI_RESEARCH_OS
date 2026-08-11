from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.analysis.analysis_service import AnalysisService
from application.analysis.finding_entailment import (
    AcceptAllFindingEntailmentValidator,
    FindingEntailmentValidator,
)
from application.executors.analysis_executor import AnalysisExecutor
from application.ports.analysis_ports import AnalysisEngine, FindingRepository, InsightRepository
from application.ports.evidence_ports import EvidenceRepository
from infrastructure.analysis.deterministic_analysis_engine import DeterministicAnalysisEngine
from infrastructure.analysis.llm_analysis_engine import LlmAnalysisEngine
from infrastructure.analysis.llm_finding_entailment_validator import (
    LlmFindingEntailmentValidator,
)


def build_analysis_engine(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    *,
    llm_client,
) -> AnalysisEngine:
    if overrides.analysis_engine is not None:
        return overrides.analysis_engine
    provider_name = config.analysis_engine.lower()
    if provider_name == "deterministic":
        return DeterministicAnalysisEngine()
    if provider_name == "llm":
        if llm_client is None:
            raise ValueError("LLM client is required for ANALYSIS_ENGINE=llm")
        return LlmAnalysisEngine(
            llm_client=llm_client,
            max_output_tokens=config.analysis_max_output_tokens,
            reasoning_effort=config.analysis_reasoning_effort,
        )
    raise ValueError(
        f"Unsupported ANALYSIS_ENGINE: {provider_name!r}. "
        "Expected one of: llm, deterministic.",
    )


def build_finding_entailment_validator(
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    *,
    llm_client,
) -> FindingEntailmentValidator:
    if overrides.finding_entailment_validator is not None:
        return overrides.finding_entailment_validator
    # Custom engine injection (tests) must not silently add unexpected LLM calls.
    if overrides.analysis_engine is not None:
        return AcceptAllFindingEntailmentValidator()
    provider_name = config.analysis_engine.lower()
    if provider_name == "deterministic":
        # Deterministic smoke path: no extra LLM calls; Findings are synthetic.
        return AcceptAllFindingEntailmentValidator()
    if provider_name == "llm":
        if llm_client is None:
            raise ValueError(
                "LLM client is required for Finding entailment when ANALYSIS_ENGINE=llm",
            )
        return LlmFindingEntailmentValidator(
            llm_client=llm_client,
            max_output_tokens=config.analysis_max_output_tokens,
            reasoning_effort=config.analysis_reasoning_effort,
        )
    raise ValueError(
        f"Unsupported ANALYSIS_ENGINE for entailment: {provider_name!r}.",
    )


def build_analysis_service(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    finding_repository: FindingRepository,
    insight_repository: InsightRepository,
    llm_client,
) -> AnalysisService:
    return AnalysisService(
        analysis_engine=build_analysis_engine(
            config,
            overrides,
            llm_client=llm_client,
        ),
        evidence_repository=evidence_repository,
        finding_repository=finding_repository,
        insight_repository=insight_repository,
        max_evidence_per_batch=config.analysis_max_evidence_per_batch,
        max_chars_per_batch=config.analysis_max_chars_per_batch,
        finding_entailment_validator=build_finding_entailment_validator(
            config,
            overrides,
            llm_client=llm_client,
        ),
    )


def build_analysis_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    finding_repository: FindingRepository,
    insight_repository: InsightRepository,
    llm_client,
) -> AnalysisExecutor:
    return AnalysisExecutor(
        analysis_service=build_analysis_service(
            config=config,
            overrides=overrides,
            evidence_repository=evidence_repository,
            finding_repository=finding_repository,
            insight_repository=insight_repository,
            llm_client=llm_client,
        ),
    )
