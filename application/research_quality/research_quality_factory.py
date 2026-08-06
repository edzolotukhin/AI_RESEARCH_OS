from __future__ import annotations

from application.config import ApplicationConfig, ApplicationOverrides
from application.executors.deterministic_research_readiness_executor import (
    DeterministicResearchReadinessExecutor,
)
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.ports.evidence_ports import EvidenceRepository
from application.ports.research_quality_ports import ResearchSufficiencyEvaluator
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.research_readiness_service import ResearchReadinessService


def build_research_sufficiency_evaluator(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    llm_client,
) -> ResearchSufficiencyEvaluator:
    if overrides.research_sufficiency_evaluator is not None:
        return overrides.research_sufficiency_evaluator

    provider = config.research_sufficiency_assessor.lower()
    if provider == "deterministic":
        from application.research_quality.deterministic_research_sufficiency_evaluator import (
            DeterministicResearchSufficiencyEvaluator,
        )

        return DeterministicResearchSufficiencyEvaluator()
    if provider == "llm":
        if llm_client is None:
            raise ValueError(
                "LLM client is required for RESEARCH_SUFFICIENCY_ASSESSOR=llm",
            )
        from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
            LlmSemanticSufficiencyAssessor,
        )

        return HybridResearchSufficiencyEvaluator(
            deterministic_evaluator=DeterministicSufficiencyEvaluator(),
            semantic_assessor=LlmSemanticSufficiencyAssessor(llm_client=llm_client),
        )
    raise ValueError(
        f"Unsupported RESEARCH_SUFFICIENCY_ASSESSOR: {provider!r}. "
        "Expected one of: llm, deterministic.",
    )


def build_research_readiness_service(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    llm_client,
) -> ResearchReadinessService:
    return ResearchReadinessService(
        evaluator=build_research_sufficiency_evaluator(
            config=config,
            overrides=overrides,
            llm_client=llm_client,
        ),
        evidence_repository=evidence_repository,
    )


def build_research_readiness_executor(
    *,
    config: ApplicationConfig,
    overrides: ApplicationOverrides,
    evidence_repository: EvidenceRepository,
    llm_client,
) -> ResearchReadinessExecutor | DeterministicResearchReadinessExecutor:
    if overrides.research_readiness_executor is not None:
        return overrides.research_readiness_executor

    use_deterministic = (
        overrides.deterministic_stage_executors
        if overrides.deterministic_stage_executors is not None
        else config.deterministic_stage_executors
    )
    if use_deterministic:
        return DeterministicResearchReadinessExecutor()

    return ResearchReadinessExecutor(
        research_readiness_service=build_research_readiness_service(
            config=config,
            overrides=overrides,
            evidence_repository=evidence_repository,
            llm_client=llm_client,
        ),
    )
